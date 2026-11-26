import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import json
import logging
import time
import traceback
import uuid
from typing import Dict

import redis

from genova_runtime.utils import utc_now_iso
from genova_runtime.queue_delivery import acknowledge_message, queue_consumer, reserve_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genova Redis worker")
    parser.add_argument(
        "--task",
        choices=["surfgen", "ecloudgen", "epso", "tarpass", "delete", "protein_preparation"],
        required=True,
    )
    parser.add_argument("--redis_url", default="redis://localhost:6379/0")
    parser.add_argument("--queue_name", default="")
    parser.add_argument("--result_queue", default="genova:queue:result")
    parser.add_argument("--dead_queue", default="genova:queue:dead")
    parser.add_argument("--job_key_prefix", default="genova:job:")
    parser.add_argument("--job_ttl_seconds", type=int, default=172800)
    parser.add_argument("--poll_timeout", type=int, default=5)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


def execute_task(task: str, payload: Dict, dry_run: bool, cancel_check=None) -> Dict:
    if payload.get('operation') == 'prepare_context_inputs' and not dry_run:
        return execute_automatic_preparation({**payload, 'compatibility_engine':task}, cancel_check)
    if task == "epso":
        from genova_runtime.entry_epso import run_job
        return run_job(payload, dry_run=dry_run)
    if task == "ecloudgen":
        from genova_runtime.entry_ecloudgen import run_job
        return run_job(payload, dry_run=dry_run, cancel_check=cancel_check)
    if task == "tarpass":
        from genova_runtime.entry_tarpass import run_job
        return run_job(payload, dry_run=dry_run)
    if task == "surfgen":
        from genova_runtime.entry_surfgen import run_job as run_surfgen_job

        return run_surfgen_job(payload, dry_run=dry_run, cancel_check=cancel_check)
    if task == "delete":
        from genova_runtime.entry_delete import run_job as run_delete_job

        return run_delete_job(payload, dry_run=dry_run, cancel_check=cancel_check)
    if task == "protein_preparation":
        if not dry_run:
            return execute_automatic_preparation(payload, cancel_check)
        from genova_runtime.automatic_preparation import run_job as run_protein_preparation_job

        return run_protein_preparation_job(payload, dry_run=dry_run)
    raise ValueError(f"Unsupported task: {task}")


def execute_automatic_preparation(payload, cancel_check=None):
    import signal
    import subprocess
    import sys
    from genova_runtime.automatic_preparation import PreparationFailure
    from genova_runtime.preparation_errors import describe_preparation_error
    compatibility = payload.get('operation') == 'prepare_context_inputs'
    module = 'genova_runtime.context_features' if compatibility else 'genova_runtime.automatic_preparation'
    from genova_runtime.pdb2pqr_compat import file_sha256
    output = Path(payload['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / 'execution_result.json'
    timeout = int(os.environ.get('PROTEIN_PREPARATION_TIMEOUT_SECONDS', '14400'))
    if timeout <= 0:
        raise ValueError('PROTEIN_PREPARATION_TIMEOUT_SECONDS must be positive')
    with (output / 'execution.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', module, str(result_path)],
            stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
        started = time.monotonic()
        reason = None
        while process.poll() is None:
            if cancel_check and cancel_check():
                reason = 'CANCELED: protein preparation was canceled'
            elif time.monotonic() - started > timeout:
                reason = f'PREPARATION_TIMEOUT: exceeded {timeout} seconds'
            if reason:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                break
            time.sleep(0.25)
    if not reason and cancel_check and cancel_check():
        reason = "CANCELED: protein preparation was canceled"
    if reason:
        report_path = output / 'execution_interrupted_report.json'
        prior = output / 'preparation_report.json'
        report = json.loads(prior.read_text()) if prior.is_file() else {}
        info = describe_preparation_error(reason, 'execution')
        report['error_info'] = info
        if compatibility:
            from genova_runtime.context_features import context_fingerprint
            report.update(status='failed', context_id=payload['context_id'], engine=payload['compatibility_engine'], input_fingerprint=context_fingerprint(payload['structure_context'],payload['input_parameters']), error=reason)
        else:
            report.update(status='failed', requested_spec=payload['prepared_spec'], error=reason)
        report.setdefault('diagnostics', []).append({'code': 'EXECUTION_INTERRUPTED', 'stage': 'execution', 'severity': 'error', 'evidence': reason, 'action': 'retain_existing_files', 'impact': 'preparation', 'retryable': False})
        report_path.write_text(json.dumps(report))
        if compatibility:
            raise PreparationFailure(reason, {'error_info':info, 'compatibility_report':str(report_path), 'report_sha256':file_sha256(report_path)})
        raise PreparationFailure(reason, {'error_info':info, 'report': str(report_path), 'artifact_sha256': {'report': file_sha256(report_path)}})
    if not result_path.is_file():
        error = RuntimeError(f'Preparation process exited with code {process.returncode}; inspect {output / "execution.log"}')
        raise PreparationFailure(str(error), {'error_info':describe_preparation_error(error, 'execution')})
    envelope = json.loads(result_path.read_text())
    if process.returncode != 0 or envelope['status'] != 'succeeded':
        raise PreparationFailure(envelope.get('error', 'Preparation process failed'), envelope.get('result', {}))
    return envelope['result']


def save_receipt(path: Path, receipt: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(receipt, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def compact_receipt(path: Path, status: str, *, result=None, error=None) -> bool:
    """Discard replay data only after the backend has committed the same result."""
    if not path.is_file():
        return False
    with path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        receipt = json.loads(path.read_text())
        if receipt.get('expired') or receipt.get('acknowledged') or not receipt.get('published'):
            return False
        if receipt['message']['status'] != status:
            return False
        message = receipt['message']
        if result is not None and any(result.get(key) != value for key, value in (message.get('result') or {}).items()):
            return False
        if error is not None and (message.get('error') or '')[:8000] != error:
            return False
        compact = {'acknowledged': True, 'fingerprint': receipt['fingerprint']}
        if message.get('error'):
            compact['error'] = message['error']
        save_receipt(path, compact)
        return True


def process_message(client, args, job: dict, receipt_root: Path) -> None:
    job_id = str(uuid.UUID(str(job["job_id"])))
    if job.get("task", args.task) != args.task or not isinstance(job.get("payload", {}), dict):
        raise ValueError("Queue task or payload is invalid")
    payload = {**job.get("payload", {}), "job_id": job_id}
    from genova_runtime.generation_rounds import GENERATION_POLICY
    resumable = (args.task in {'surfgen', 'ecloudgen', 'delete'}
                 and payload.get('generation_policy') == GENERATION_POLICY)
    result_queue = str(job.get("result_queue", args.result_queue))
    identity = {"task": args.task, "payload": payload, "dry_run": args.dry_run, "result_queue": result_queue}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
    path = receipt_root / (job_id + ".json")
    # ponytail: shared local filesystem locks; multi-host deployment needs a
    # shared execution authority, not expiring Redis leases around GPU work.
    with path.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if path.exists():
            receipt = json.loads(path.read_text())
            if receipt.get("expired"):
                return
            if receipt["fingerprint"] != fingerprint:
                raise ValueError("Queue job ID was reused with different execution inputs")
            if receipt.get('acknowledged'):
                return
            if receipt["message"]["status"] == "running" and not resumable:
                receipt["message"].update(status="failed", finished_at=utc_now_iso(),
                    error="EXECUTION_INTERRUPTED: Previous execution ended without a durable result. Inspect artifacts and explicitly retry with a new queue job ID.")
                save_receipt(path, receipt)
        else:
            now = utc_now_iso()
            receipt = {"fingerprint": fingerprint, "job": {**job, "job_id": job_id, "task": args.task, "payload": payload, "result_queue": result_queue}, "task": args.task, "dry_run": args.dry_run,
                "published": False, "message": {"job_id": job_id, "task": args.task, "status": "running", "started_at": now}}
            previous = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in client.hgetall(f"{args.job_key_prefix}{job_id}").items()}
            if previous.get("status") in {"succeeded", "failed"}:
                receipt["message"].update(status=previous["status"],
                    started_at=previous.get("started_at", now), finished_at=previous.get("finished_at", now))
                if previous["status"] == "succeeded":
                    receipt["message"]["result"] = json.loads(previous["result"])
                else:
                    receipt["message"]["error"] = previous.get("error", "Previous execution failed")
            elif previous.get("status") == "running":
                receipt["message"].update(status="failed", finished_at=now,
                    error="EXECUTION_UNVERIFIED: Redis records a previous execution without a durable receipt. Inspect it before explicitly retrying with a new queue job ID.")
            save_receipt(path, receipt)

        if receipt["message"]["status"] == "running":
            status_key = f"{args.job_key_prefix}{job_id}"

            def canceled():
                value = client.hget(status_key, "error") or ""
                return (value.decode() if isinstance(value, bytes) else value).startswith("CANCELED:")

            start = time.perf_counter()
            try:
                if resumable and canceled():
                    raise RuntimeError("CANCELED: the generation task was canceled")
                client.hset(status_key, mapping={**receipt["message"], "updated_at": utc_now_iso()})
                can_cancel = (resumable or payload.get('operation') == 'prepare_context_inputs'
                              or args.task == "protein_preparation" and
                              (payload.get("prepared_spec", {}).get("preparation") or {}).get("strategy") == "generation_auto_v1")
                result = execute_task(args.task, payload, dry_run=args.dry_run,
                                      cancel_check=canceled if can_cancel else None)
                if not args.dry_run:
                    from genova_runtime.artifact_json import finalize_artifacts
                    result = finalize_artifacts(result)
            except Exception as exc:
                receipt["message"].update(status="failed", error=f"{exc}\n{traceback.format_exc()}")
                if getattr(exc, "result", None):
                    receipt["message"]["result"] = exc.result
                elif str(exc).split(':', 1)[0] in {'CONTEXT_CACHE_STALE', 'CONTEXT_CACHE_CHANGED', 'CONTEXT_INPUTS_NOT_READY'}:
                    from genova_runtime.preparation_errors import describe_preparation_error
                    receipt['message']['result'] = {'error_info': describe_preparation_error(exc, 'initializing_inputs')}
            else:
                receipt["message"].update(status="succeeded", result=result)
            receipt["message"].update(finished_at=utc_now_iso(), elapsed_seconds=round(time.perf_counter() - start, 6))
            save_receipt(path, receipt)

        message = receipt["message"]
        status = {key: value for key, value in message.items() if key != "result"}
        status["updated_at"] = message["finished_at"]
        if "result" in message:
            status["result"] = json.dumps(message["result"], ensure_ascii=False)
        status_key = f"{args.job_key_prefix}{job_id}"
        with client.pipeline(transaction=True) as transaction:
            transaction.hset(status_key, mapping=status)
            if args.job_ttl_seconds > 0:
                transaction.expire(status_key, args.job_ttl_seconds)
            if result_queue:
                transaction.lpush(result_queue, json.dumps(message, ensure_ascii=False))
            transaction.execute()
        receipt["published"] = True
        save_receipt(path, receipt)


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger(f"genova-worker-{args.task}")
    queue_name = args.queue_name or f"genova:queue:{args.task}"
    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    receipt_root = Path(os.environ.get("DATA_ROOT", "/app/data")) / ".runtime_receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    logger.info("Worker online. task=%s queue=%s dry_run=%s", args.task, queue_name, args.dry_run)

    with queue_consumer(client, queue_name):
        # Recover durable results even if the input message was already popped.
        # ponytail: startup scans retained receipts; add a pending index if history makes startup slow.
        for path in receipt_root.glob("*.json"):
            receipt = json.loads(path.read_text())
            if not receipt.get("expired") and not receipt.get('acknowledged') and receipt["task"] == args.task and receipt["dry_run"] == args.dry_run and not receipt["published"]:
                process_message(client, args, receipt["job"], receipt_root)

        while True:
            raw = reserve_message(client, queue_name, args.poll_timeout)
            if raw is None:
                if args.once:
                    break
                continue
            try:
                job = json.loads(raw)
                if not isinstance(job, dict):
                    raise ValueError("Queue message must be an object")
                process_message(client, args, job, receipt_root)
            except (ValueError, KeyError, TypeError) as exc:
                client.lpush(args.dead_queue, raw)
                logger.error("Invalid job moved to dead queue: %s", exc)
            acknowledge_message(client, queue_name, raw)
            if args.once:
                break


if __name__ == "__main__":
    main()
