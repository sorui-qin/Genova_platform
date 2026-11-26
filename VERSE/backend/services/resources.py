import fcntl
import os
import stat
from pathlib import Path

from sqlalchemy import select

from backend.config import settings
from backend.models import DataRetentionDeletion, Dataset, Job, JobTask, User


ACTIVE = ('pending', 'blocked', 'queued', 'running')


def storage_usage(db, user_id):
    roots = [settings.data_root / directory / str(item)
             for model, directory in ((Job, 'jobs'), (Dataset, 'datasets'))
             for item in db.scalars(select(model.id).where(model.owner_user_id == user_id))]
    for paths in db.scalars(select(DataRetentionDeletion.paths).where(DataRetentionDeletion.owner_user_id == user_id)):
        roots.extend(settings.data_root / item for item in paths)
    seen, total = set(), 0
    for root in set(roots):
        if root.is_symlink():
            continue
        for directory, _, names in os.walk(root, followlinks=False):
            for name in names:
                try:
                    item = (Path(directory) / name).lstat()
                except FileNotFoundError:
                    continue
                identity = (item.st_dev, item.st_ino)
                if stat.S_ISREG(item.st_mode) and identity not in seen:
                    seen.add(identity)
                    total += item.st_size
    return total


def check_admission(db, user_id, *, compute=True):
    from backend.services.jobs import DomainValidationError

    user = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    limit = 1 if user.is_guest else 3
    if compute:
        jobs = set(db.scalars(select(Job.id).where(Job.owner_user_id == user_id, Job.status.in_(ACTIVE))))
        previews = 0
        tasks = db.scalars(select(JobTask).join(Job, Job.id == JobTask.job_id).where(
            Job.owner_user_id == user_id, JobTask.status.in_((*ACTIVE, 'canceled'))))
        for task in tasks:
            busy = task.status in ACTIVE
            if task.status == 'canceled':
                lock = settings.data_root / '.runtime_receipts' / f'{task.queue_job_id}.lock'
                if lock.exists():
                    with lock.open('r') as stream:
                        try:
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            busy = True
            if busy:
                if task.task_code.startswith('plip2d_'):
                    previews += 1
                else:
                    jobs.add(task.job_id)
        if len(jobs) + previews >= limit:
            raise DomainValidationError(f'At most {limit} unfinished computation(s) per account',
                                        code='ACTIVE_JOB_LIMIT', http_status=429)
    quota = (settings.guest_storage_quota_mb if user.is_guest else settings.user_storage_quota_mb) * 1024 * 1024
    remaining = quota - storage_usage(db, user_id)
    if remaining <= 0:
        raise DomainValidationError('Storage quota reached; delete unused tasks or datasets to reclaim space',
                                    code='STORAGE_QUOTA_EXCEEDED', http_status=413)
    return remaining
