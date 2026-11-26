import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def gpu_lock():
    path = Path(os.environ.get('GPU_LOCK_PATH', '/app/data/.locks/gpu-0.lock'))
    path.parent.mkdir(parents=True, exist_ok=True)
    # ponytail: single-host shared GPU lock; per-device paths for separate GPUs.
    with path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield lock.fileno()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
