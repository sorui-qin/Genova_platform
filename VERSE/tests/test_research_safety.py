"""Task-scoped safety regression tests using a disposable PostgreSQL database.

Run with GENOVA_ISOLATED_REGRESSION=1 and a dedicated database.
Model outputs are simulated; no scientific computation or external model is called.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from types import SimpleNamespace
import os
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from sqlalchemy import func, select
from pydantic_ai.models.test import TestModel

from backend.agent import research_safety
from backend.agent.research_safety import RiskEvidence, SafetyVerdict, effective_verdict, require_task
from backend.agent.session_schemas import SessionTurnRequest
from backend.db import SessionLocal
from backend.models import (ActionProposal, AgentSession, AgentTurn, EditSession, Job, QueueOutbox,
                            ResearchTask, User, WorkflowRun)
from backend.services import agent_sessions, agent_turns
from backend.services.workflows import WorkflowError
from backend.utils import utcnow


def verdict(decision, reason_code, *, language='zh', assistance_kind=None, material_risk=None, **kwargs):
    return SafetyVerdict(decision=decision, reason_code=reason_code, reason='Synthetic assessment',
        language=language, assistance_kind=assistance_kind or ('non_operational' if kwargs.get('answer_only') else 'operational'),
        material_risk=material_risk or ('clear' if reason_code in {'harmful_operation', 'blocked_goal'}
            else 'uncertain' if reason_code == 'ambiguous_intent' else 'none'), **kwargs)


def reviewed(material_risk, assistance_kind='operational'):
    return RiskEvidence(assistance_kind=assistance_kind, material_risk=material_risk, reason='Synthetic risk review')


class EffectiveVerdictTests(unittest.TestCase):
    def test_explicit_risk_overrides_clarify_and_allow(self):
        for decision in ('allow', 'clarify', 'refuse'):
            for reason in ('harmful_operation', 'blocked_goal', 'policy_violation'):
                result = effective_verdict(verdict(decision, reason, answer_only=True),
                                           blocked=False, new=False)
                self.assertEqual((result.decision, result.answer_only), ('refuse', False))

    def test_blocked_only_allows_nonoperational_education(self):
        safe = verdict('allow', 'legitimate_request', answer_only=True)
        self.assertEqual(effective_verdict(safe, blocked=True, new=False).decision, 'allow')
        self.assertEqual(effective_verdict(safe, blocked=True, new=False, action_requested=True).decision, 'refuse')
        self.assertEqual(effective_verdict(verdict('allow', 'legitimate_request', answer_only=True, assistance_kind='operational'),
                                           blocked=True, new=False).decision, 'refuse')
        self.assertEqual(effective_verdict(verdict('clarify', 'ambiguous_intent'),
                                           blocked=True, new=False).decision, 'refuse')
        self.assertEqual(effective_verdict(verdict('clarify', 'ambiguous_intent'),
                                           blocked=False, new=False).decision, 'clarify')
        self.assertEqual(effective_verdict(verdict('allow', 'legitimate_request'),
                                           blocked=False, new=True, prior_blocked=True).decision, 'refuse')

    def test_clear_risk_overrides_an_ambiguous_reason_in_one_pass(self):
        for decision, reason in [('clarify', 'ambiguous_intent'), ('allow', 'legitimate_request')]:
            primary = verdict(decision, reason, material_risk='clear')
            result = effective_verdict(primary, blocked=False, new=False)
            self.assertEqual((result.decision, result.reason_code, result.answer_only),
                             ('refuse', 'harmful_operation', False))
        contradiction = verdict('allow', 'legitimate_request', answer_only=True,
            assistance_kind='non_operational', material_risk='clear')
        self.assertEqual(effective_verdict(contradiction, blocked=False, new=False).decision, 'refuse')

    def test_review_can_strengthen_but_not_weaken_safety(self):
        primary = verdict('clarify', 'ambiguous_intent')
        for review in (reviewed('none'), reviewed('uncertain')):
            self.assertEqual(effective_verdict(primary, blocked=False, new=False, review=review).decision, 'clarify')
        result = effective_verdict(primary, blocked=False, new=False, review=reviewed('clear'))
        self.assertEqual((result.decision, result.reason_code, result.material_risk),
                         ('refuse', 'harmful_operation', 'clear'))
        for primary in (verdict('allow', 'legitimate_request', material_risk='uncertain'),
                        verdict('allow', 'legitimate_request', assistance_kind='unclear')):
            self.assertEqual(effective_verdict(primary, blocked=False, new=False).decision, 'clarify')
            self.assertEqual(effective_verdict(primary, blocked=False, new=False, review=reviewed('clear')).decision, 'refuse')


@asynccontextmanager
async def mock_client(**kwargs):
    yield None


@unittest.skipUnless(os.environ.get('GENOVA_ISOLATED_REGRESSION') == '1',
                     'requires a disposable PostgreSQL database')
class ResearchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.owner = uuid.uuid4()
        with SessionLocal() as db:
            db.add(User(id=self.owner, username=f'qa-{self.owner}',
                        email=f'{self.owner}@example.invalid', password_hash='unused'))
            db.commit()
        self.create_session()

    def create_session(self):
        with SessionLocal() as db:
            session = AgentSession(owner_user_id=self.owner, goal='Synthetic research topic')
            db.add(session)
            db.flush()
            self.session_id = session.id
            db.commit()

    def queue_turn(self, message, intent='ask', *, language='zh', **kwargs):
        with SessionLocal() as db:
            session = agent_sessions.owned_session(db, self.session_id, self.owner, lock=True)
            request = SessionTurnRequest(client_request_id=uuid.uuid4(), intent=intent,
                message=message, base_revision=session.input_revision, interface_language=language, **kwargs)
            turn = agent_sessions.submit_request(db, session, request)
            turn.status = 'running'
            db.commit()
            return turn.id, turn.attempt

    def run_turn(self, turn, assessment, on_assess=None, *, risk_review=None, on_review=None, expected_safety_calls=None):
        async def simulated_assessment(*args, **kwargs):
            if kwargs['stage'] == 'input_safety':
                if on_assess:
                    on_assess()
                result = assessment
            else:
                self.assertEqual(kwargs['stage'], 'input_safety_review')
                if on_review:
                    on_review()
                result = risk_review if risk_review is not None else reviewed('uncertain')
            if isinstance(result, Exception):
                raise result
            return SimpleNamespace(output=result)

        async def verified_reply(service, deps, message, reply):
            return reply

        with patch.object(research_safety, 'run_agent', side_effect=simulated_assessment) as assess_mock, \
             patch.object(research_safety, 'check_reply', side_effect=verified_reply), \
             patch.object(agent_turns, 'public_client', mock_client), \
             patch.object(agent_turns, 'personal_proxy', return_value=None), \
             patch.object(agent_turns, '_get_service', return_value=SimpleNamespace(_model=TestModel())), \
             patch.object(agent_turns, '_get_knowledge', return_value=None), \
             patch.object(agent_turns, 'answer', new_callable=AsyncMock,
                          return_value=({'message': 'Synthetic safe answer'}, {})) as answer, \
             patch.object(agent_turns, 'publish_turn') as publish:
            asyncio.run(agent_turns.run_turn(self.session_id, turn[0], self.owner, turn[1], config={}))
        if expected_safety_calls is not None:
            self.assertEqual(assess_mock.call_count, expected_safety_calls)
        with SessionLocal() as db:
            row = db.get(AgentTurn, turn[0])
            self.assertTrue(publish.called)
            self.assertEqual(publish.call_args.args[1]['response'], row.response)
            self.assertGreater(row.response.get('stream_seq', 0), 0)
            return row.response, row.research_task_id, answer.call_count, row.audit

    def state(self):
        with SessionLocal() as db:
            session = db.get(AgentSession, self.session_id)
            task = db.get(ResearchTask, session.research_task_id)
            return session, task

    def counts(self):
        with SessionLocal() as db:
            return (
                db.scalar(select(func.count()).select_from(ActionProposal).where(ActionProposal.session_id == self.session_id)),
                db.scalar(select(func.count()).select_from(WorkflowRun).where(WorkflowRun.owner_user_id == self.owner)),
                db.scalar(select(func.count()).select_from(Job).where(Job.owner_user_id == self.owner)),
                db.scalar(select(func.count()).select_from(QueueOutbox)),
            )

    def test_multiturn_refusal_and_independent_task(self):
        response, original, calls, _ = self.run_turn(self.queue_turn('Academic question'),
            verdict('allow', 'legitimate_request', answer_only=True))
        self.assertEqual((response['safety_decision'], calls), ('allow', 1))
        response, _, calls, _ = self.run_turn(self.queue_turn('Unclear purpose'),
            verdict('clarify', 'ambiguous_intent'))
        self.assertEqual((response['safety_decision'], calls), ('clarify', 0))
        self.assertTrue(self.state()[0].pending_requirements)
        before = self.counts()
        for decision, reason in [('clarify', 'harmful_operation'), ('clarify', 'blocked_goal'),
                                 ('allow', 'legitimate_request')]:
            response, task_id, calls, audit = self.run_turn(self.queue_turn('Synthetic risk case'),
                verdict(decision, reason))
            self.assertEqual(task_id, original)
            self.assertEqual((response['safety_decision'], calls), ('refuse', 0))
            self.assertEqual(audit['raw_safety_verdict']['decision'], decision)
            self.assertEqual(audit['safety']['decision'], 'refuse')
            self.assertFalse(response.get('missing_requirements'))
            session, task = self.state()
            self.assertEqual(task.state, 'blocked')
            self.assertFalse(session.pending_requirements)
        self.assertEqual(self.counts(), before)
        response, _, calls, _ = self.run_turn(self.queue_turn('Safety education question'),
            verdict('allow', 'legitimate_request', answer_only=True))
        self.assertEqual((response['safety_decision'], calls), ('allow', 1))
        self.assertEqual(self.state()[1].state, 'blocked')
        response, rejected, calls, _ = self.run_turn(self.queue_turn('Related objective', 'new_task'),
            verdict('allow', 'legitimate_request', independent_goal=False))
        self.assertEqual((response['safety_decision'], calls), ('refuse', 0))
        self.assertNotEqual(rejected, original)
        self.assertEqual(self.state()[1].id, original)
        response, separate, calls, _ = self.run_turn(self.queue_turn('Independent legitimate goal', 'new_task'),
            verdict('allow', 'legitimate_request', independent_goal=True))
        self.assertEqual((response['safety_decision'], calls), ('allow', 0))
        self.assertNotEqual(original, separate)
        self.assertEqual(self.state()[1].id, separate)
        self.assertEqual(self.state()[1].state, 'allowed')
        with SessionLocal() as db:
            self.assertEqual(db.get(ResearchTask, original).state, 'blocked')
        self.assertEqual(self.counts(), before)

    def test_bilingual_first_turn_risk_review_and_persistent_refusal(self):
        for language, message, refusal in (
            ('en', 'Synthetic safety fixture', 'I cannot provide operational plans'),
            ('zh', '模拟安全审核用例', '我无法提供操作方案'),
        ):
            with self.subTest(language=language):
                self.create_session()
                before = self.counts()
                turn = self.queue_turn(message, language=language)
                response, task_id, calls, audit = self.run_turn(turn,
                    verdict('clarify', 'ambiguous_intent', language=language, assistance_kind='operational'),
                    risk_review=reviewed('clear'), expected_safety_calls=2)
                self.assertEqual((response['safety_decision'], calls), ('refuse', 0))
                self.assertIn(refusal, response['message'])
                self.assertEqual(audit['raw_safety_verdict']['decision'], 'clarify')
                self.assertEqual(audit['raw_safety_verdict']['material_risk'], 'uncertain')
                self.assertEqual(audit['safety_risk_review']['material_risk'], 'clear')
                self.assertEqual(audit['safety']['material_risk'], 'clear')
                self.assertEqual(audit['safety']['reason_code'], 'harmful_operation')
                self.assertEqual(self.state()[1].state, 'blocked')
                self.assertEqual(self.state()[1].assessment['blocked_assessment']['material_risk'], 'clear')
                self.assertFalse(self.state()[0].pending_requirements)
                response, same_task, calls, _ = self.run_turn(self.queue_turn(message, language=language),
                    verdict('allow', 'legitimate_request', language=language), expected_safety_calls=1)
                self.assertEqual((response['safety_decision'], calls, same_task), ('refuse', 0, task_id))
                self.assertEqual(self.counts(), before)

    def test_clear_risk_and_normal_requests_need_only_one_assessment(self):
        for answer_only in (True, False):
            response, _, calls, audit = self.run_turn(self.queue_turn('Permissible fixture'),
                verdict('allow', 'legitimate_request', answer_only=answer_only), expected_safety_calls=1)
            self.assertEqual((response['safety_decision'], calls), ('allow', 1))
            self.assertIsNone(audit['safety_risk_review'])
        response, _, calls, audit = self.run_turn(self.queue_turn('Synthetic risk fixture'),
            verdict('clarify', 'ambiguous_intent', material_risk='clear'), expected_safety_calls=1)
        self.assertEqual((response['safety_decision'], calls), ('refuse', 0))
        self.assertIsNone(audit['safety_risk_review'])
        self.assertEqual(audit['safety']['material_risk'], 'clear')
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_uncertain_assessment_is_not_relaxed_by_review(self):
        response, _, calls, audit = self.run_turn(self.queue_turn('Unresolved fixture'),
            verdict('allow', 'legitimate_request', material_risk='uncertain'),
            risk_review=reviewed('none', 'non_operational'), expected_safety_calls=2)
        self.assertEqual((response['safety_decision'], calls), ('clarify', 0))
        self.assertEqual(audit['safety_risk_review']['material_risk'], 'none')
        self.assertEqual(self.state()[1].state, 'unassessed')
        self.assertTrue(self.state()[0].pending_requirements)
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_pending_assessment_and_blocked_approval(self):
        first = self.queue_turn('Ordinary goal')
        _, task_id, _, _ = self.run_turn(first, verdict('allow', 'legitimate_request'))
        with SessionLocal() as db:
            proposal = ActionProposal(session_id=self.session_id, turn_id=first[0],
                kind='prepare', payload={}, input_fingerprint={}, action_hash='a'*64)
            editor = EditSession(owner_user_id=self.owner, session_id=self.session_id,
                kind='workflow', expected_revision=0, inputs={}, state={'draft': {'fixture': True}})
            db.add_all([proposal, editor])
            db.commit()
            proposal_id = proposal.id
            editor_id = editor.id

        def try_approval():
            with SessionLocal() as db:
                session = agent_sessions.owned_session(db, self.session_id, self.owner, lock=True)
                try:
                    agent_sessions.approve_proposal(db, session, proposal_id, 'a'*64)
                except WorkflowError as exc:
                    return exc.code
                self.fail('Approval unexpectedly passed')

        before = self.counts()
        pending = self.queue_turn('Synthetic transition')
        with ThreadPoolExecutor(max_workers=2) as pool:
            def during_assessment():
                results = [pool.submit(try_approval) for _ in range(2)]
                self.assertEqual([f.result(timeout=10) for f in results], ['SAFETY_ASSESSMENT_REQUIRED']*2)
            response, _, _, _ = self.run_turn(pending, verdict('clarify', 'ambiguous_intent'), during_assessment,
                risk_review=reviewed('clear'), on_review=during_assessment, expected_safety_calls=2)
            self.assertEqual(response['safety_decision'], 'refuse')
            results = [pool.submit(try_approval) for _ in range(2)]
            self.assertEqual([f.result(timeout=10) for f in results], ['RESEARCH_TASK_BLOCKED']*2)
        with SessionLocal() as db:
            self.assertEqual(db.get(ActionProposal, proposal_id).status, 'stale')
            self.assertEqual(db.get(EditSession, editor_id).status, 'canceled')
            self.assertEqual(db.get(EditSession, editor_id).state['draft'], {'fixture': True})
            origin = db.get(AgentTurn, first[0])
            origin.status = 'failed'
            session = agent_sessions.owned_session(db, self.session_id, self.owner, lock=True)
            with self.assertRaises(WorkflowError) as resume_error:
                agent_sessions.resume_turn(db, session, origin.id)
            self.assertEqual(resume_error.exception.code, 'RESEARCH_TASK_BLOCKED')
            with self.assertRaises(WorkflowError) as error:
                require_task(db, task_id, self.owner)
            self.assertEqual(error.exception.code, 'RESEARCH_TASK_BLOCKED')
        self.assertEqual(self.counts(), before)

    def test_assessment_unavailable_retry(self):
        turn = self.queue_turn('Ordinary question')
        response, task_id, calls, _ = self.run_turn(turn, RuntimeError('Simulated service failure'))
        self.assertEqual(response['error_code'], 'SAFETY_CHECK_UNAVAILABLE')
        self.assertEqual(calls, 0)
        self.assertEqual(self.state()[1].state, 'unassessed')
        with SessionLocal() as db:
            session = agent_sessions.owned_session(db, self.session_id, self.owner, lock=True)
            retry = agent_sessions.resume_turn(db, session, turn[0])
            retry.status = 'running'
            db.commit()
            retry_id = retry.id, retry.attempt
        response, retry_task, calls, _ = self.run_turn(retry_id,
            verdict('allow', 'legitimate_request', answer_only=True))
        self.assertEqual((response['safety_decision'], calls, retry_task), ('allow', 1, task_id))

    def test_risk_review_unavailable_does_not_clear_task(self):
        turn = self.queue_turn('Synthetic unresolved fixture')
        before = self.counts()
        response, original, calls, audit = self.run_turn(turn,
            verdict('clarify', 'ambiguous_intent'), risk_review=RuntimeError('Simulated review failure'),
            expected_safety_calls=2)
        self.assertEqual((response['error_code'], calls), ('SAFETY_CHECK_UNAVAILABLE', 0))
        self.assertEqual(audit['raw_safety_verdict']['decision'], 'clarify')
        self.assertEqual(audit['safety_review_error'], 'SAFETY_CHECK_UNAVAILABLE')
        self.assertIsNone(audit['safety_risk_review'])
        self.assertEqual(self.state()[1].state, 'unassessed')
        self.assertIsNone(self.state()[1].pending_turn_id)
        with SessionLocal() as db:
            session = agent_sessions.owned_session(db, self.session_id, self.owner, lock=True)
            retry = agent_sessions.resume_turn(db, session, turn[0])
            retry.status = 'running'
            db.commit()
            retry_id = retry.id, retry.attempt
        response, same_task, calls, audit = self.run_turn(retry_id,
            verdict('clarify', 'ambiguous_intent'), risk_review=reviewed('clear'), expected_safety_calls=2)
        self.assertEqual((response['safety_decision'], calls, same_task), ('refuse', 0, original))
        self.assertIsNone(audit['safety_review_error'])
        self.assertEqual(self.state()[1].state, 'blocked')
        self.assertEqual(self.counts(), before)

    def test_new_task_assessment_retry_preserves_old_block(self):
        _, original, _, _ = self.run_turn(self.queue_turn('Synthetic risk case'),
            verdict('clarify', 'harmful_operation'))
        turn = self.queue_turn('Independent legitimate goal', 'new_task')
        response, candidate, _, _ = self.run_turn(turn, RuntimeError('Simulated service failure'))
        self.assertEqual(response['error_code'], 'SAFETY_CHECK_UNAVAILABLE')
        self.assertNotEqual(candidate, original)
        self.assertEqual(self.state()[1].id, original)
        with SessionLocal() as db:
            session = agent_sessions.owned_session(db, self.session_id, self.owner, lock=True)
            retry = agent_sessions.resume_turn(db, session, turn[0])
            retry.status = 'running'
            db.commit()
            retry_id = retry.id, retry.attempt
        response, task, _, _ = self.run_turn(retry_id,
            verdict('allow', 'legitimate_request', independent_goal=True))
        self.assertEqual(response['safety_decision'], 'allow')
        self.assertEqual(task, candidate)
        self.assertEqual(self.state()[1].id, candidate)
        with SessionLocal() as db:
            self.assertEqual(db.get(ResearchTask, original).state, 'blocked')

    def test_module_refusal_snapshot(self):
        with SessionLocal() as db:
            session = db.get(AgentSession, self.session_id)
            session.assets = {'module_assistant': {'module': 'molecule_generation', 'job_id': None}}
            db.commit()
        with patch('backend.agent.module_assistant.page_context'):
            turn = self.queue_turn('Synthetic module request', module_context={'engine': 'surfgen'})
        response, task, calls, _ = self.run_turn(turn, verdict('clarify', 'ambiguous_intent'),
            risk_review=reviewed('clear'), expected_safety_calls=2)
        self.assertEqual((response['safety_decision'], calls), ('refuse', 0))
        with SessionLocal() as db:
            snapshot = agent_sessions.snapshot(db, db.get(AgentSession, self.session_id))
            self.assertEqual(snapshot['research_task_state'], 'blocked')
            self.assertEqual(snapshot['research_task_id'], str(task))
            self.assertEqual(snapshot['turns'][-1]['response'], response)
            self.assertFalse(snapshot['pending_requirements'])
        self.assertEqual(self.counts(), (0, 0, 0, 0))
