"""Regression coverage of ordinary submission and attachment transactions.

Run against a disposable PostgreSQL database with GENOVA_ISOLATED_REGRESSION=1.
The job implementation is a queue-only fixture; no computation worker is involved.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
import uuid

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select

from backend import schemas
from backend.config import settings
from backend.db import SessionLocal
from backend.models import Dataset, DatasetFile, DatasetUploadAttempt, Job, JobSubmission, JobTask, QueueOutbox, User
from backend.routers import datasets, jobs


@unittest.skipUnless(os.environ.get("GENOVA_ISOLATED_REGRESSION") == "1", "requires separate regression database")
class SubmissionAndUploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        from pathlib import Path
        storage = patch.object(settings, "data_root", Path(self.directory.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.owner = uuid.uuid4()
        with SessionLocal() as db:
            db.add(User(id=self.owner, username=f"qa-{self.owner}", email=f"{self.owner}@example.invalid",
                        password_hash="unused", is_guest=True))
            db.commit()

    def counts(self):
        with SessionLocal() as db:
            return (
                db.scalar(select(func.count()).select_from(Job).where(Job.owner_user_id == self.owner)),
                db.scalar(select(func.count()).select_from(QueueOutbox).join(JobTask, JobTask.id == QueueOutbox.job_task_id)
                          .join(Job, Job.id == JobTask.job_id).where(Job.owner_user_id == self.owner)),
                db.scalar(select(func.count()).select_from(JobSubmission).where(JobSubmission.owner_user_id == self.owner)),
            )

    @staticmethod
    def register_only(payload, db, user):
        job = Job(id=uuid.uuid4(), owner_user_id=user.id, job_type=payload.job_type, status="pending", params={}, summary={})
        db.add(job)
        db.flush()
        task = JobTask(id=uuid.uuid4(), job_id=job.id, task_code="qa_fixture", status="pending", queue_job_id=uuid.uuid4())
        db.add(task)
        db.flush()
        db.add(QueueOutbox(job_task_id=task.id, queue_name="qa-only", payload={"task": "fixture"}))
        db.flush()
        return jobs._serialize_job(db, job, with_tasks=True)

    def submit(self, key, payload):
        with SessionLocal() as db:
            return jobs.create_job(payload, db, db.get(User, self.owner), key)

    def test_concurrent_replay_conflict_and_new_submission(self):
        key = uuid.uuid4()
        payload = schemas.JobCreateRequest(job_type="protein_preparation", prepared_receptor_id=uuid.uuid4())
        barrier = Barrier(2)

        def concurrent():
            barrier.wait()
            return self.submit(key, payload).id

        with patch.object(jobs, "_create_protein_preparation_job", side_effect=self.register_only) as register, \
             patch.object(jobs, "_publish_job_event_safely"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = [pool.submit(concurrent) for _ in range(2)]
                ids = [item.result(timeout=15) for item in future]
            self.assertEqual(ids[0], ids[1])
            self.assertEqual(self.counts(), (1, 1, 1))
            self.assertEqual(register.call_count, 1)
            # A guest has reached its one-active-job limit, but replay must still succeed.
            self.assertEqual(self.submit(key, payload).id, ids[0])
            with self.assertRaises(HTTPException) as error:
                self.submit(key, schemas.JobCreateRequest(job_type="protein_preparation", prepared_receptor_id=uuid.uuid4()))
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(self.counts(), (1, 1, 1))
            # The same parameters with a new explicit key form another submission once capacity is available.
            with SessionLocal() as db:
                user = db.get(User, self.owner)
                canceled = jobs.cancel_job(ids[0], db, user)
                self.assertEqual(canceled["status"], "canceled")
                self.assertEqual(jobs.get_job(ids[0], False, db, user).status, "canceled")
                self.assertEqual(db.scalar(select(QueueOutbox.status).join(JobTask, JobTask.id == QueueOutbox.job_task_id)
                                           .where(JobTask.job_id == ids[0])), "canceled")
            self.assertNotEqual(self.submit(uuid.uuid4(), payload).id, ids[0])
            self.assertEqual(self.counts(), (2, 2, 2))

    def test_missing_context_creates_no_job_or_queue(self):
        missing = uuid.uuid4()
        payload = schemas.JobCreateRequest(job_type="molecule_generation", protein_context_id=missing,
                                           params={"molecule_generation": {"engine": "fixture"}})
        with self.assertRaises(HTTPException) as error:
            self.submit(uuid.uuid4(), payload)
        self.assertEqual(error.exception.detail["error_code"], "PROTEIN_CONTEXT_STALE")
        self.assertEqual(error.exception.detail["protein_context_id"], str(missing))
        self.assertEqual(self.counts(), (0, 0, 0))

    def upload(self, key):
        with SessionLocal() as db:
            return asyncio.run(datasets.upload_dataset(
                name="fixture.txt", kind="upload", description=None, file_roles=["attachment"],
                files=[UploadFile(BytesIO(b"fixture"), filename="fixture.txt")],
                db=db, current_user=db.get(User, self.owner), input_policy=None, upload_id=key,
            ))

    def cancel(self, key):
        with SessionLocal() as db:
            return datasets.cancel_dataset_upload(key, db, db.get(User, self.owner))

    def test_canceled_upload_and_committed_upload_are_distinguished(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        uploaded = self.upload(first)
        self.assertEqual(self.cancel(first)["dataset"].id, uploaded.id)
        self.assertEqual(self.cancel(second)["status"], "canceled")
        with self.assertRaises(HTTPException) as error:
            self.upload(second)
        self.assertEqual(error.exception.detail["error_code"], "UPLOAD_CANCELED")
        self.assertEqual(self.upload(first).id, uploaded.id)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner_user_id == self.owner)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(DatasetFile).where(DatasetFile.dataset_id == uploaded.id)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(DatasetUploadAttempt).where(DatasetUploadAttempt.owner_user_id == self.owner)), 2)

    def test_upload_and_cancel_race_matches_committed_record(self):
        key = uuid.uuid4()
        barrier = Barrier(2)
        def upload():
            barrier.wait()
            try:
                return self.upload(key).id
            except HTTPException as exc:
                self.assertEqual(exc.detail["error_code"], "UPLOAD_CANCELED")
                return None
        def cancel():
            barrier.wait()
            return self.cancel(key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending_upload = pool.submit(upload)
            pending_cancel = pool.submit(cancel)
            dataset_id, outcome = pending_upload.result(timeout=15), pending_cancel.result(timeout=15)
        with SessionLocal() as db:
            row = db.get(DatasetUploadAttempt, (self.owner, key))
            self.assertEqual(row.dataset_id, dataset_id)
            self.assertEqual(outcome["status"], "uploaded" if dataset_id else "canceled")
            self.assertEqual(db.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner_user_id == self.owner)), int(dataset_id is not None))

    def test_already_approved_proposal_replay_does_not_enqueue(self):
        """Two existing views reading an already-approved non-computing fixture."""
        from backend.models import ActionProposal, AgentSession, AgentTurn, ResearchTask
        from backend.services import agent_sessions
        from backend.services.workflows import WorkflowError

        with SessionLocal() as db:
            assessment = ResearchTask(id=uuid.uuid4(), owner_user_id=self.owner, goal="UI regression fixture",
                                      state="allowed", assessment={})
            db.add(assessment)
            db.flush()
            session = AgentSession(id=uuid.uuid4(), owner_user_id=self.owner, research_task_id=assessment.id,
                                   goal="UI regression fixture")
            db.add(session)
            db.flush()
            turn = AgentTurn(id=uuid.uuid4(), session_id=session.id, research_task_id=assessment.id,
                             client_request_id=uuid.uuid4(), request_hash="0"*64, request={}, status="succeeded")
            db.add(turn)
            db.flush()
            proposal = ActionProposal(id=uuid.uuid4(), session_id=session.id, turn_id=turn.id,
                                      kind="task_plan", payload={}, input_fingerprint={},
                                      action_hash="a"*64, status="approved", execution={})
            db.add(proposal)
            session_id, proposal_id = session.id, proposal.id
            db.commit()
        for _ in range(2):
            with SessionLocal() as db:
                session = agent_sessions.owned_session(db, session_id, self.owner, lock=True)
                self.assertEqual(agent_sessions.approve_proposal(db, session, proposal_id, "a"*64).status, "approved")
                db.commit()
        with SessionLocal() as db:
            session = agent_sessions.owned_session(db, session_id, self.owner, lock=True)
            with self.assertRaises(WorkflowError) as error:
                agent_sessions.approve_proposal(db, session, proposal_id, "b"*64)
            self.assertEqual(error.exception.code, "ACTION_CHANGED")
        self.assertEqual(self.counts(), (0, 0, 0))
