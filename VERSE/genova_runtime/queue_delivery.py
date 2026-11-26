import fcntl
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def queue_consumer(client, queue_name):
    directory = Path(os.environ.get('DATA_ROOT', '/app/data')) / '.queue_locks'
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(queue_name.encode()).hexdigest()
    # One consumer per queue on the shared host makes crash recovery safe without expiring leases.
    with (directory / key).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        while client.lmove(queue_name + ':processing', queue_name, 'LEFT', 'RIGHT') is not None:
            pass
        yield


def reserve_message(client, queue_name, timeout):
    return client.blmove(queue_name, queue_name + ':processing', timeout, 'RIGHT', 'LEFT')


def acknowledge_message(client, queue_name, raw):
    client.lrem(queue_name + ':processing', 1, raw)
