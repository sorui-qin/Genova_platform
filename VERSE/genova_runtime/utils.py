import shlex
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def command_to_string(cmd: List[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run_subprocess(cmd: List[str], cwd: Path, dry_run: bool, pass_fds=(), timeout=None, env=None, log_path=None) -> Dict[str, str]:
    cmd_str = command_to_string(cmd)
    if dry_run:
        return {
            "command": cmd_str,
            "stdout": "",
            "stderr": "",
            "returncode": 0,
            "dry_run": True,
        }

    if timeout is None:
        proc = subprocess.run(cmd, cwd=str(cwd), text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False, pass_fds=pass_fds, env=env)
    else:
        process = subprocess.Popen(cmd, cwd=str(cwd), text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=pass_fds, env=env, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            if log_path:
                Path(log_path).write_text(stdout + "\nSTDERR:\n" + stderr)
            raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
        proc = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    if log_path:
        Path(log_path).write_text(proc.stdout + "\nSTDERR:\n" + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {cmd_str}\n"
            f"STDOUT:\n{proc.stdout[-4000:]}\n"
            f"STDERR:\n{proc.stderr[-4000:]}"
        )

    return {
        "command": cmd_str,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
        "dry_run": False,
    }
