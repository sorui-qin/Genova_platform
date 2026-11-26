import argparse
import json
import logging
import uuid

import redis

from genova_runtime.utils import utc_now_iso
from genova_runtime.queue_delivery import acknowledge_message, queue_consumer, reserve_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genova Redis dispatcher")
    parser.add_argument("--redis_url", default="redis://localhost:6379/0")
    parser.add_argument("--dispatch_queue", default="genova:queue:dispatch")
    parser.add_argument("--surfgen_queue", default="genova:queue:surfgen")
    parser.add_argument("--ecloudgen_queue", default="genova:queue:ecloudgen")
    parser.add_argument("--tarpass_queue", default="genova:queue:tarpass")
    parser.add_argument("--epso_queue", default="genova:queue:epso")
    parser.add_argument("--delete_queue", default="genova:queue:delete")
    parser.add_argument("--protein_preparation_queue", default="genova:queue:protein_preparation")
    parser.add_argument("--dead_queue", default="genova:queue:dead")
    parser.add_argument("--job_key_prefix", default="genova:job:")
    parser.add_argument("--job_ttl_seconds", type=int, default=172800)
    parser.add_argument("--poll_timeout", type=int, default=5)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("genova-dispatcher")

    queue_map = {
        "surfgen": args.surfgen_queue,
        "ecloudgen": args.ecloudgen_queue,
        "tarpass": args.tarpass_queue,
        "delete": args.delete_queue,
        "epso": args.epso_queue,
        "protein_preparation": args.protein_preparation_queue,
    }

    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    logger.info("Dispatcher online. dispatch_queue=%s", args.dispatch_queue)

    with queue_consumer(client, args.dispatch_queue):
        while True:
            raw = reserve_message(client, args.dispatch_queue, args.poll_timeout)
            if raw is None:
                continue

            now = utc_now_iso()

            try:
                job = json.loads(raw)
                task = job.get("task")
                if task not in queue_map:
                    raise ValueError(f"Unsupported task: {task}")
            except Exception as exc:
                client.lpush(args.dead_queue, raw)
                acknowledge_message(client, args.dispatch_queue, raw)
                logger.error("Invalid job moved to dead queue: %s", exc)
                continue

            job_id = str(job.get("job_id") or uuid.uuid4())
            task = str(job["task"])
            target_queue = queue_map[task]

            job["job_id"] = job_id
            job["queued_at"] = now
            if "payload" not in job:
                job["payload"] = {}

            status_key = f"{args.job_key_prefix}{job_id}"
            dispatched = client.eval("""
                if redis.call('exists', KEYS[3]) == 1 then return 0 end
                redis.call('lpush', KEYS[1], ARGV[1])
                redis.call('hsetnx', KEYS[2], 'status', 'queued')
                redis.call('hset', KEYS[2], 'job_id', ARGV[2], 'task', ARGV[3], 'queue', KEYS[1])
                redis.call('hsetnx', KEYS[2], 'updated_at', ARGV[4])
                if tonumber(ARGV[5]) > 0 then redis.call('expire', KEYS[2], ARGV[5]) end
                return 1
            """, 3, target_queue, status_key, f"genova:expired:{job_id}",
                json.dumps(job, ensure_ascii=False), job_id, task, now, args.job_ttl_seconds)
            acknowledge_message(client, args.dispatch_queue, raw)
            if not dispatched:
                continue

            logger.info("job_id=%s dispatched -> %s", job_id, target_queue)


if __name__ == "__main__":
    main()
