from copy import deepcopy
from datetime import datetime, timedelta
import uuid

from sqlalchemy import select
from sqlalchemy.orm import object_session

from backend.agent.task_plan import TaskPlan
from backend.agent.session_schemas import SessionTurnRequest
from backend.models import AgentTurn, ActionProposal, ResearchTask, WorkflowRun, Job, JobTask
from backend.services.workflows import WorkflowError, workflow_steps
from backend.utils import utcnow
from backend.workflows.contracts import digest
from backend.agent.language import completion_text, task_language, task_text, session_text, session_interface_language, turn_text


ACTIVE = {'approved', 'running', 'pause_requested', 'analyzing'}


def store(task, value):
    task.task_plan = deepcopy(value)
    object_session(task).flush()


def internal_turn(db, session, task, key, message='', *, queued=False):
    identity = uuid.uuid5(task.id, key)
    existing = db.scalar(select(AgentTurn).where(AgentTurn.session_id == session.id, AgentTurn.client_request_id == identity))
    if existing:
        return existing
    request = SessionTurnRequest(client_request_id=identity, intent='ask', message=message,
        interface_language=session_interface_language(db, session)).model_dump(mode='json')
    turn = AgentTurn(id=identity, session_id=session.id, research_task_id=task.id, client_request_id=identity,
        request_hash=digest(request), request=request, status='queued' if queued else 'completed',
        response={} if queued else {'message': message}, audit={'task_plan_version': (task.task_plan or {}).get('version', 1), 'task_plan_event': key,
            'trigger': 'task_plan', 'execution_revision': session.input_revision})
    db.add(turn)
    db.flush()
    return turn


def save(db, session, turn, changes):
    from backend.services import agent_sessions as sessions
    task = db.scalar(select(ResearchTask).where(ResearchTask.id == session.research_task_id).with_for_update())
    current = task.task_plan or {}
    if current.get('state') in ACTIVE:
        raise WorkflowError('TASK_PAUSE_REQUIRED', 'Pause the task before revising its plan', 409)
    from backend.agent.schemas import WorkflowPlan
    from backend.workflows.commands import merge_patch
    definition = merge_patch(current.get('definition', {}), changes)
    previous_workflow = current.get('definition', {}).get('workflow') or {}
    generation_changes = (changes.get('workflow') or {}).get('generation', {})
    if generation_changes.get('engine') and generation_changes['engine'] != previous_workflow.get('generation', {}).get('engine'):
        definition['workflow']['generation'] = deepcopy(generation_changes)
    if 'workflow' not in definition and session.active_workflow_id:
        run = db.get(WorkflowRun, session.active_workflow_id)
        definition['workflow'] = deepcopy(run.plan_json)
    extras = sessions.session_values(session)
    definition.setdefault('key_interactions', extras.get('key_interactions', []))
    definition.setdefault('reference_dataset_id', extras.get('reference_dataset_id'))
    definition.setdefault('goal', task.goal)
    if 'completion' not in changes and changes.get('stage') != current.get('definition', {}).get('stage'):
        definition['completion'] = completion_text(definition.get('stage') or ('generation' if definition.get('workflow') else 'preparation'), task_language(task))
    definition.setdefault('completion', completion_text(definition.get('stage') or 'preparation', task_language(task)))
    if not current and definition.get('workflow'):
        definition.setdefault('sampling', {'enabled':True, 'max_rounds':2})
    plan = TaskPlan.model_validate(definition)
    if current.get('state') == 'paused' and current.get('run', {}).get('workflow_id'):
        child = db.get(WorkflowRun, uuid.UUID(current['run']['workflow_id']))
        steps = {step.step_key: step for step in workflow_steps(db, child.id)}
        previous = current['definition']['workflow']
        if plan.workflow is None:
            raise WorkflowError('STAGE_ALREADY_STARTED', 'An existing molecular calculation cannot be removed', 409)
        actual = plan.workflow.model_dump(mode='json')
        if steps['generation'].job_id and any(actual.get(field) != previous.get(field) for field in ('generator', 'generation', 'protein_context_id', 'seed_source')):
            raise WorkflowError('STAGE_ALREADY_STARTED', 'Generation inputs cannot change after submission', 409)
        if steps['postprocessing'].job_id and actual['postprocessing']['enabled'] != previous['postprocessing']['enabled']:
            raise WorkflowError('STAGE_ALREADY_STARTED', 'Submitted postprocessing cannot be removed', 409)
    if plan.reference_dataset_id:
        from backend.services.jobs import get_owned_dataset
        get_owned_dataset(db, uuid.UUID(plan.reference_dataset_id), session.owner_user_id)
    if current.get('state') == 'paused' and current.get('definition', {}).get('preparation'):
        if session.preparation_job_id and plan.preparation != current['definition']['preparation']:
            raise WorkflowError('STAGE_ALREADY_STARTED', 'Submitted protein preparation cannot change', 409)
        if current.get('run', {}).get('phase') not in {'start', 'preparing'} and plan.site != current['definition']['site']:
            raise WorkflowError('STAGE_ALREADY_STARTED', 'The binding site has already been applied', 409)
    if plan.site:
        SessionTurnRequest(client_request_id=turn.client_request_id, intent='save_site', values=plan.site)
    if plan.preparation:
        from backend.structure_contracts import PreparedReceptorCreate
        spec = PreparedReceptorCreate.model_validate({**plan.preparation['prepared_spec'], 'name': plan.preparation.get('name', 'Prepared receptor')})
        if str(spec.source.dataset_id) != session.assets.get('protein_dataset_id'):
            raise WorkflowError('INPUT_CHANGED', 'Preparation source must match the bound protein dataset', 409)
        from backend.services.prepared_receptors import get_component_manifest, _validate_edits
        _validate_edits(spec, get_component_manifest(spec.source, db, session.owner_user_id))
    if plan.workflow:
        sessions.effective_generation(plan.workflow)
        from tarpass.filters import validate_filters
        validate_filters([rule.model_dump(mode='json') for rule in plan.workflow.postprocessing.prefilters], pre=True)
    if plan.workflow and plan.workflow.protein_context_id:
        from backend.services.jobs import validate_protein_context_for_generation
        validate_protein_context_for_generation(db, session.owner_user_id, uuid.UUID(plan.workflow.protein_context_id))
        if plan.workflow.protein_context_id != session.assets.get('protein_context_id'):
            raise WorkflowError('INPUT_CHANGED', 'Bind the selected Context before saving the plan', 409)
    value = {'definition': plan.model_dump(mode='json'), 'version': current.get('version', 0) + 1,
        'state': 'awaiting_approval', 'run': deepcopy(current.get('run', {})) if current.get('state') in {'paused', 'awaiting_approval'} and current.get('definition', {}).get('stage') == plan.stage else {}}
    if current.get('state') == 'blocked' and plan.stage == 'generation' and previous_workflow.get('protein_context_id') == (plan.workflow.protein_context_id if plan.workflow else None):
        previous_run = current.get('run', {})
        value['run'] = {key: deepcopy(previous_run[key]) for key in ('rounds', 'sampling_round', 'sampling_total') if key in previous_run}
    if current.get('state') == 'blocked' and plan.stage == 'postprocessing':
        previous_run = current.get('run', {})
        value['run'] = {key: deepcopy(previous_run[key]) for key in
            ('rounds', 'source_workflow_ids', 'postprocessed_workflow_ids') if key in previous_run}
    if plan.stage == 'postprocessing' and current.get('state') in {'completed', 'partial'}:
        previous_run = current.get('run', {})
        value['run'].update({key: deepcopy(previous_run[key]) for key in (
            'round', 'rounds', 'source_workflow_ids', 'stop_reason', 'generated_count',
            'generation_target', 'sampling_round', 'sampling_total', 'postprocessed_workflow_ids') if key in previous_run})
    value['run'].pop('error', None)
    if value['run'].get('deadline'):
        value['run'].setdefault('budget_hours', current['definition']['auto_hours'])
    if plan.stage == 'postprocessing' and plan.workflow and not value['run'].get('workflow_id'):
        source_id = next(iter(value['run'].get('source_workflow_ids', [])), None) or session.active_workflow_id
        source = db.get(WorkflowRun, uuid.UUID(str(source_id))) if source_id else None
        if source is None:
            value['run'].pop('source_workflow_id', None)
        else:
            steps = {step.step_key: step for step in workflow_steps(db, source.id)}
            previous_plan = WorkflowPlan.model_validate(source.plan_json).model_dump(mode='json')
            if ((steps['generation'].status == 'succeeded' or source.status in {'approved', 'running'})
                    and not steps['postprocessing'].job_id
                    and all(plan.workflow.model_dump(mode='json').get(field) == previous_plan.get(field)
                        for field in ('generator', 'generation', 'protein_context_id', 'seed_source'))):
                value['run']['source_workflow_id'] = str(source.id)
            else:
                value['run'].pop('source_workflow_id', None)
    if plan.stage == 'postprocessing' and not value['run'].get('source_workflow_id') and not value['run'].get('workflow_id'):
        raise WorkflowError('SOURCE_NOT_READY', 'Postprocessing requires successful generation results', 409)
    if value['run'].get('source_workflow_id') and not plan.iteration.enabled:
        value['definition']['sampling'] = None
    store(task, value)
    if plan.workflow:
        preferences = deepcopy(task.workflow_preferences or {})
        preferences['postprocessing'] = {**preferences.get('postprocessing', {}),
            'prefilters': [rule.model_dump(mode='json') for rule in plan.workflow.postprocessing.prefilters]}
        task.workflow_preferences = preferences
    for old in db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id,
            ActionProposal.kind == 'task_plan', ActionProposal.status == 'pending')):
        old.status = 'stale'
    proposal = sessions.create_proposal(db, session, turn, 'task_plan',
        {'task_plan': value['definition'], 'task_plan_version': value['version'],
         **({'prepared_spec': plan.preparation['prepared_spec']} if plan.preparation else {}),
         **({'reference_dataset_id': plan.reference_dataset_id} if plan.reference_dataset_id else {})})
    value['proposal_id'] = str(proposal.id)
    store(task, value)
    session.phase = {'preparation':'awaiting_preparation_approval',
        'postprocessing':'awaiting_postprocessing_approval','generation':'awaiting_workflow_approval'}[plan.stage]
    return {'task_plan': value, 'proposal_id': str(proposal.id), 'message': turn_text(turn, '当前阶段方案已保存，请批准后执行。', 'The current stage plan has been saved. Please approve it to proceed.')}


def approve(db, session, proposal):
    task = db.scalar(select(ResearchTask).where(ResearchTask.id == session.research_task_id).with_for_update())
    value = deepcopy(task.task_plan)
    if value['proposal_id'] != str(proposal.id) or proposal.payload['task_plan'] != value['definition']:
        raise WorkflowError('PLAN_CHANGED', 'Approve the current task plan', 409)
    value['state'] = 'running'
    run = value.setdefault('run', {})
    if run.get('phase') == 'analysis':
        policy = value['definition']['iteration']
        if value['definition']['workflow'] and policy['enabled'] and run['round'] < policy['max_rounds']:
            run['phase'] = 'workflow'
        else:
            value['state'] = 'analyzing'
    now = utcnow()
    if run.get('paused_at'):
        paused = datetime.fromisoformat(run.pop('paused_at'))
        if run.get('deadline'):
            run['deadline'] = (datetime.fromisoformat(run['deadline']) + (now - paused)).isoformat()
    if run.get('deadline'):
        difference = value['definition']['auto_hours'] - run.get('budget_hours', value['definition']['auto_hours'])
        run['deadline'] = (datetime.fromisoformat(run['deadline']) + timedelta(hours=difference)).isoformat()
    run['budget_hours'] = value['definition']['auto_hours']
    run.setdefault('deadline', (now + timedelta(hours=value['definition']['auto_hours'])).isoformat())
    run.setdefault('round', 0)
    run.setdefault('rounds', [])
    run.setdefault('recoveries', {})
    run.setdefault('phase', 'start')
    store(task, value)
    child = db.get(WorkflowRun, uuid.UUID(run['workflow_id'])) if run.get('workflow_id') else None
    if child:
        steps = {step.step_key: step for step in workflow_steps(db, child.id)}
        child.execution_binding = {**child.execution_binding, 'task_plan_version': value['version']}
        if steps['generation'].job_id is None:
            child.status = 'superseded'
            run.pop('workflow_id', None)
            run['phase'] = 'start'
        elif value['definition'].get('stage') == 'postprocessing' and steps['postprocessing'].job_id is None:
            from backend.services import agent_sessions as sessions
            post_turn = internal_turn(db, session, task, f"revise-post:{value['version']}")
            definition = value['definition']['workflow']
            result = sessions.prepare_postprocessing(db, session, post_turn, {'choice': 'run' if definition['postprocessing']['enabled'] else 'skip',
                'evidence': 'approved task plan', 'postprocessing': {**definition['postprocessing'], 'selection': definition['selection'],
                    'key_interactions':value['definition']['key_interactions'], 'reference_dataset_id':value['definition']['reference_dataset_id']}})
            if result.get('proposal_id'):
                post = db.get(ActionProposal, uuid.UUID(result['proposal_id']))
                sessions.approve_proposal(db, session, post.id, post.action_hash)
    elif session.active_workflow_id:
        draft = db.get(WorkflowRun, session.active_workflow_id)
        if draft.status == 'awaiting_approval':
            draft.status, draft.refinement_state = 'superseded', 'closed'
            for old in db.scalars(select(ActionProposal).where(ActionProposal.workflow_id == draft.id, ActionProposal.status == 'pending')):
                old.status = 'stale'
    store(task, value)
    session.phase = 'executing'
    proposal.execution = {'research_task_id': str(task.id), 'version': value['version']}


def pause(db, session):
    task = db.scalar(select(ResearchTask).where(ResearchTask.id == session.research_task_id).with_for_update())
    value = deepcopy(task.task_plan)
    if not value or value['state'] not in ACTIVE:
        raise WorkflowError('TASK_NOT_RUNNING', 'No task is running', 409)
    value['state'] = 'pause_requested'
    value['run']['paused_at'] = utcnow().isoformat()
    store(task, value)
    return {'message': session_text(db, session, '已停止新增调度；当前计算完成后可以修订方案。', 'New scheduling has stopped. Revise the plan after the current calculation finishes.')}


def resume(db, session):
    task = db.scalar(select(ResearchTask).where(ResearchTask.id == session.research_task_id).with_for_update())
    value = deepcopy(task.task_plan)
    if not value or value['state'] != 'paused':
        raise WorkflowError('TASK_NOT_PAUSED', 'The task is not paused', 409)
    now = utcnow()
    paused = datetime.fromisoformat(value['run'].pop('paused_at'))
    value['run']['deadline'] = (datetime.fromisoformat(value['run']['deadline']) + (now - paused)).isoformat()
    value['state'] = 'analyzing' if value['run'].get('phase') == 'analysis' else 'running'
    store(task, value)
    session.phase = 'analyzing' if value['state'] == 'analyzing' else 'executing'
    return {'message': session_text(db, session, '已恢复任务，将复用已完成结果继续执行。', 'The task has resumed using completed results.')}


def _start_round(db, session, task, value, plan):
    from backend.workflows.commands import save_plan
    from backend.services import agent_sessions as sessions
    from backend.agent.schemas import WorkflowPlan
    plan = WorkflowPlan.model_validate(plan).model_dump(mode='json')
    run = value['run']
    if plan['generator'] == 'delete' and not plan['generation']['edit'].get('edit_spec_id'):
        raise WorkflowError('DELETE_EDITOR_REQUIRED', 'Save the DELETE edit in the visual editor before execution', 422)
    if value['definition'].get('stage') == 'generation':
        sessions.record_postprocessing_choice(db, session, internal_turn(db, session, task,
            f"postprocessing-skip:{value['version']}:{run['round']}:{run.get('sampling_round', 0)}"),
            'skip', 'approved generation stage')
        plan['postprocessing'] = {'enabled': False, 'prefilters': plan['postprocessing'].get('prefilters', [])}
    key = f"task:{value['version']}:round:{run['round']}:sample:{run.get('sampling_round', 0)}:attempt:{run.get('attempt', 0)}"
    turn = internal_turn(db, session, task, key)
    source_id = run.get('source_workflow_id') if value['definition'].get('stage') == 'postprocessing' else None
    if source_id:
        child = db.get(WorkflowRun, uuid.UUID(source_id))
        from backend.agent.schemas import WorkflowPlan
        original = WorkflowPlan.model_validate(child.plan_json).model_dump(mode='json')
        if any(plan.get(field) != original.get(field) for field in ('generator', 'generation', 'protein_context_id', 'seed_source')):
            raise WorkflowError('INPUT_CHANGED', 'The generation plan changed; existing results cannot be reused', 409)
        session.active_workflow_id = child.id
    else:
        result = save_plan(db, session, turn, WorkflowPlan.model_validate(plan), new=True,
            create_workflow_id=uuid.uuid5(task.id, key))
        proposal = db.get(ActionProposal, uuid.UUID(result['proposal_id']))
        if run.get('sampling_round', 0):
            effective = deepcopy(proposal.payload['effective_generation'])
            offset = run['sampling_round']
            if plan['generator'] == 'epso':
                effective['optimizer']['seed'] = (effective['optimizer']['seed'] + offset) % (2 ** 32)
            else:
                effective['seed'] = (effective['seed'] + offset) % (2 ** 32)
            proposal.payload = {**proposal.payload, 'effective_generation': effective}
            proposal.input_fingerprint = sessions.fingerprint(db, session, proposal.payload)
            proposal.action_hash = digest({'kind':proposal.kind, 'payload':proposal.payload, 'input':proposal.input_fingerprint})
        sessions.approve_proposal(db, session, proposal.id, proposal.action_hash)
        child = db.get(WorkflowRun, uuid.UUID(result['workflow_id']))
    child.execution_binding = {**child.execution_binding, 'task_plan_version': value['version']}
    run['workflow_id'] = str(child.id)
    run.setdefault('attempts', []).append(str(child.id))
    run.setdefault('batches', {}).setdefault(str(run['round']), []).append(str(child.id))
    if value['definition'].get('stage') == 'postprocessing':
        post_step = next(step for step in workflow_steps(db, child.id) if step.step_key == 'postprocessing')
        if post_step.job_id and db.get(Job, post_step.job_id).status in {'failed', 'canceled'}:
            post_step.job_id, post_step.status = None, 'awaiting_approval'
            post_step.error_code = post_step.error_message = None
            child.status, child.refinement_state = 'running', 'running'
        post_turn = internal_turn(db, session, task, key + ':postprocessing')
        post = sessions.prepare_postprocessing(db, session, post_turn, {'choice': 'run', 'evidence': 'approved postprocessing stage',
            'postprocessing': {**plan['postprocessing'], 'selection': plan['selection'],
                'key_interactions': value['definition']['key_interactions'], 'reference_dataset_id': value['definition']['reference_dataset_id']}})
        post_proposal = db.get(ActionProposal, uuid.UUID(post['proposal_id']))
        sessions.approve_proposal(db, session, post_proposal.id, post_proposal.action_hash)
    elif not plan['postprocessing']['enabled']:
        sessions.record_postprocessing_choice(db, session, turn, 'skip', 'approved generation stage')
    run['phase'] = 'workflow'
    store(task, value)


def _finish(db, session, task, value, reason):
    value['state'] = 'completed' if reason == 'completed' else 'partial'
    value['run']['stop_reason'] = reason
    value['run']['phase'] = 'completed'
    store(task, value)
    session.phase = 'results_ready'
    stage = value['definition'].get('stage')
    messages = {
        'preparation': ('蛋白准备已完成。下一步请确认结合位点，随后会生成分子计算草稿。', 'Protein preparation is complete. Confirm the binding site next to create the molecule calculation draft.'),
        'generation': ('分子生成／优化已完成，结果已保留。', 'Molecule generation / optimization is complete. The results have been saved.'),
        'postprocessing': ('后处理已完成。你可以让我帮助分析结果，或选择分子参与后续优化。', 'Postprocessing is complete. You can ask me to analyze the results or select molecules for further optimization.'),
    }
    message = session_text(db, session, *messages.get(stage, ('当前阶段已完成。', 'This stage is complete.')))
    if reason == 'time_limit':
        message = session_text(db, session, '已达到执行时限，现有结果已保留。', 'The time limit has been reached. Existing results have been saved.')
    elif reason == 'quantity_shortfall':
        message += session_text(db, session, '数量补采样预算已耗尽，未达到目标数量；已有结果可继续后处理。', ' The resampling budget is exhausted and the target count was not reached. Existing results can proceed to postprocessing.')
    internal_turn(db, session, task, f"task:{value['version']}:final:{reason}", message)


def _advance(db, session):
    from backend.services import agent_sessions as sessions
    task = db.scalar(select(ResearchTask).where(ResearchTask.id == session.research_task_id).with_for_update(skip_locked=True))
    if task is None:
        return True
    if not task.task_plan:
        return False
    if (task.assessment or {}).get('needs_action_clearance'):
        session.last_error, session.phase = 'SAFETY_ASSESSMENT_REQUIRED', 'waiting_input'
        return True
    if task.state != 'allowed':
        return task.task_plan['state'] in ACTIVE | {'paused', 'blocked', 'waiting_input'}
    value = deepcopy(task.task_plan)
    if value['state'] == 'awaiting_approval':
        session.phase = {'preparation':'awaiting_preparation_approval',
            'postprocessing':'awaiting_postprocessing_approval', 'generation':'awaiting_workflow_approval'}[value['definition']['stage']]
        return True
    if value['state'] in {'paused', 'blocked'}:
        return True
    if value['state'] == 'waiting_input':
        answer_id = value['run'].get('answer_turn_id')
        if answer_id:
            answer = db.get(AgentTurn, uuid.UUID(answer_id))
            if answer.status == 'completed' and not answer.response.get('error_code'):
                question = db.get(AgentTurn, uuid.UUID(value['run']['analysis_turn_id']))
                following = internal_turn(db, session, task, f"answer:{answer.id}",
                    question.request['message'] + task_text(task, '\n用户补充：', '\nUser clarification: ') + answer.request['message'], queued=True)
                value['run']['analysis_turn_id'] = str(following.id)
                value['run'].pop('answer_turn_id', None)
                value['state'] = 'analyzing'
                session.phase, session.pending_requirements = 'analyzing', []
                store(task, value)
        return True
    if value['state'] not in ACTIVE:
        return False
    plan = TaskPlan.model_validate(value['definition'])
    state = value['run']
    if value['state'] == 'analyzing':
        turn = db.get(AgentTurn, uuid.UUID(state['analysis_turn_id']))
        if turn.status == 'canceled':
            value['state'] = 'partial'
            state['stop_reason'] = 'analysis_canceled'
            session.phase = 'results_ready'
            store(task, value)
            return True
        if turn.audit.get('task_plan_version') != value['version']:
            turn = internal_turn(db, session, task, f"analysis:version:{value['version']}", turn.request['message'], queued=True)
            state['analysis_turn_id'] = str(turn.id)
            store(task, value)
        if turn.status == 'needs_input':
            value['state'] = 'waiting_input'
            session.phase = 'waiting_input'
            session.pending_requirements = turn.response.get('missing_requirements', [])
            store(task, value)
        elif turn.status == 'completed' and turn.response.get('investigation_status') != 'paused':
            value['state'] = 'completed' if state['stop_reason'] == 'completed' else 'partial'
            session.phase = 'results_ready'
            store(task, value)
        elif turn.status == 'completed' and turn.response.get('investigation_status') == 'paused':
            if utcnow() >= datetime.fromisoformat(state['deadline']):
                value['state'] = 'partial'
                session.phase = 'results_ready'
                state['stop_reason'] = 'analysis_time_limit'
                store(task, value)
                internal_turn(db, session, task, f"analysis:limit:{value['version']}", session_text(db, session, '分析已达到自动推进时限，已有结果与读取位置已保存。', 'Analysis reached its continuation time limit. Existing results and reading progress have been saved.'))
                return True
            current = turn.audit.get('source_read_state') or turn.audit.get('diagnostic_state') or {}
            previous = state.get('analysis_progress')
            stalled = state.get('analysis_stalled', 0) + 1 if current == previous else 0
            state['analysis_stalled'], state['analysis_progress'] = stalled, current
            if stalled >= 2:
                value['state'] = 'blocked'
                state['error'] = session_text(db, session, '分析连续两次没有取得进展，结果与读取位置已保存。', 'Analysis made no progress in two consecutive attempts. Your results and reading progress have been saved.')
            else:
                next_turn = internal_turn(db, session, task, f"analysis:continue:{turn.id}", turn.request['message'], queued=True)
                next_turn.audit = {**next_turn.audit, 'source_read_state': turn.audit.get('source_read_state', {}),
                    'diagnostic_state': turn.audit.get('diagnostic_state', {})}
                state['analysis_turn_id'] = str(next_turn.id)
            store(task, value)
        elif turn.status in {'failed', 'interrupted'}:
            count = state['recoveries'].get('analysis', 0)
            if count < plan.max_recoveries:
                state['recoveries']['analysis'] = count + 1
                resumed = internal_turn(db, session, task, f"analysis:retry:{value['version']}:{count + 1}", turn.request['message'], queued=True)
                resumed.audit = {**resumed.audit, 'source_read_state': turn.audit.get('source_read_state', {})}
                state['analysis_turn_id'] = str(resumed.id)
                store(task, value)
            else:
                value['state'] = 'blocked'
                state['error'] = session_text(db, session, '结果已保留，分析阶段未能完成。', 'The analysis stage could not finish. Existing results have been saved.')
                store(task, value)
        return True
    child = db.get(WorkflowRun, uuid.UUID(state['workflow_id'])) if state.get('workflow_id') else None
    active_jobs = [db.get(Job, step.job_id) for step in workflow_steps(db, child.id) if step.job_id] if child else []
    if state['phase'] == 'preparing' and session.preparation_job_id:
        active_jobs.append(db.get(Job, session.preparation_job_id))
    if state['phase'] in {'context', 'prepare_iteration'} and session.assets.get('context_validation_job_id'):
        active_jobs.append(db.get(Job, uuid.UUID(session.assets['context_validation_job_id'])))
    stage_jobs = {step.step_key: str(step.job_id) for step in workflow_steps(db, child.id) if step.job_id} if child else {}
    if state.get('stage_jobs') != stage_jobs:
        state['stage_jobs'] = stage_jobs
        store(task, value)
    if value['state'] == 'pause_requested':
        if not any(job.status in {'pending', 'queued', 'running', 'cancel_requested'} for job in active_jobs):
            value['state'] = 'paused'
            session.phase = 'paused'
            store(task, value)
        return True
    if task.pending_turn_id:
        return True
    if utcnow() >= datetime.fromisoformat(state['deadline']):
        if not any(job.status in {'pending', 'queued', 'running', 'cancel_requested'} for job in active_jobs):
            _finish(db, session, task, value, 'time_limit')
        return True
    if state['phase'] == 'start':
        definition = plan.workflow.model_dump(mode='json') if plan.workflow else None
        if plan.stage == 'preparation':
            turn = internal_turn(db, session, task, f"prepare:{value['version']}:{state['recoveries'].get('preparation', 0)}")
            payload = {**plan.preparation, 'preparation_protocol_version': 2}
            proposal = sessions.create_proposal(db, session, turn, 'prepare', payload)
            sessions.approve_proposal(db, session, proposal.id, proposal.action_hash)
            state['phase'] = 'preparing'
            store(task, value)
            return True
        if plan.stage == 'generation' and state['rounds']:
            produced = valid_generation_count(db, session, state['rounds']) or 0
            field = 'target_num_molecules' if definition['generator'] == 'ecloudgen' else 'num_molecules'
            definition['generation'][field] = max(1, definition['generation'][field] - produced)
        _start_round(db, session, task, value, definition)
        return True
    if state['phase'] == 'preparing':
        job = db.get(Job, session.preparation_job_id)
        if job.status in {'pending', 'queued', 'running'}:
            return True
        if job.status != 'succeeded':
            value['state'] = 'blocked'
            state['error'] = session_text(db, session, '蛋白准备失败，请查看错误后重试或修改方案。', 'Protein preparation failed. Inspect the error, then retry or revise the plan.')
            store(task, value)
            internal_turn(db, session, task, f"prepare-failed:{value['version']}", state['error'])
            return True
        if plan.workflow is None or not plan.site:
            _finish(db, session, task, value, 'completed')
            session.phase, session.pending_requirements = 'awaiting_site', ['site']
            return True
        from backend.services.prepared_receptors import get_prepared_receptor
        from backend.services.binding_sites import artifact
        from backend.structure_contracts import FileIdentity
        from genova_runtime.artifact_json import read_json
        from pathlib import Path
        prepared = get_prepared_receptor(uuid.UUID(session.assets['prepared_receptor_id']), db, session.owner_user_id)
        manifest = artifact(db, session.owner_user_id, FileIdentity.model_validate(prepared['artifacts']['component_manifest']))
        frame = read_json(Path(manifest.storage_path))['coordinate_frame_id']
        site_values = deepcopy(plan.site)
        for binding in (site_values['site']['anchor'], site_values.get('generation_reference')):
            if binding and binding.get('coordinate_frame_id') == 'prepared':
                binding['coordinate_frame_id'] = frame
        turn = internal_turn(db, session, task, f"site:{value['version']}")
        reply = sessions.execute_action(db, session, turn, SessionTurnRequest(client_request_id=turn.client_request_id,
            intent='save_site', values=site_values))
        state['prepared_context_id'] = reply['protein_context_id']
        state['phase'] = 'context'
        internal_turn(db, session, task, f"prepared:{value['version']}", session_text(db, session, '蛋白准备已完成，已保存位点；检查模型输入后将生成待批准的分子计算草稿。', 'Protein preparation is complete and the binding site is saved. A molecule calculation draft will follow the model input checks.'))
        store(task, value)
        return True
    if state['phase'] == 'context':
        validation_id = session.assets.get('context_validation_job_id')
        if validation_id:
            validation = db.get(Job, uuid.UUID(validation_id))
            if validation.status in {'pending', 'queued', 'running'}:
                return True
            if validation.status != 'succeeded':
                raise WorkflowError('CONTEXT_VALIDATION_FAILED', 'Prepared Context validation failed', 409)
        definition = plan.workflow.model_dump(mode='json')
        definition['protein_context_id'] = state['prepared_context_id']
        _finish(db, session, task, value, 'completed')
        turn = internal_turn(db, session, task, f"generation-draft:{value['version']}", session_text(db, session, '位点与模型输入已准备好，请检查分子计算方案并批准执行。', 'The binding site and model inputs are ready. Review the molecule calculation plan before approval.'))
        save(db, session, turn, {'stage': 'generation', 'preparation': None, 'site': None, 'workflow': definition})
        return True
    if state['phase'] == 'workflow':
        steps = {step.step_key: step for step in workflow_steps(db, child.id)}
        stage = plan.stage
        step = steps['postprocessing' if stage == 'postprocessing' else 'generation']
        if child.status in {'failed', 'canceled'} or step.status in {'failed', 'canceled'}:
            value['state'] = 'blocked'
            notice = session_text(db, session, '阶段执行失败，已停止。可以重试原方案或修改模型及参数后重新批准。', 'This stage failed and has stopped. Retry the original plan or revise it and approve again.')
            state['error'] = notice + ('\n' + step.error_message if step.error_message else '')
            store(task, value)
            internal_turn(db, session, task, f"failed:{value['version']}:{child.id}", notice)
            return True
        if step.status != 'succeeded':
            session.phase = 'executing'
            return True
        if str(child.id) not in state['rounds']:
            state['rounds'].append(str(child.id))
        if stage == 'generation':
            target = plan.workflow.generation.model_dump().get('target_num_molecules') or plan.workflow.generation.num_molecules
            produced = valid_generation_count(db, session, state['rounds'])
            state['generated_count'], state['generation_target'] = produced, target
            if produced is not None and produced < target and plan.sampling and plan.sampling.enabled and state.get('sampling_total', 0) < plan.sampling.max_rounds:
                state['sampling_round'] = state.get('sampling_round', 0) + 1
                state['sampling_total'] = state.get('sampling_total', 0) + 1
                next_plan = deepcopy(child.plan_json)
                field = 'target_num_molecules' if next_plan['generator'] == 'ecloudgen' else 'num_molecules'
                next_plan['generation'][field] = target - produced
                internal_turn(db, session, task, f"sample:{value['version']}:{state['sampling_round']}",
                    session_text(db, session, f'当前得到 {produced} 个有效唯一分子，目标 {target} 个；将补采样缺少的 {target - produced} 个。', f'Generated {produced} valid unique molecules out of {target}; sampling will fill the remaining {target - produced}.'))
                _start_round(db, session, task, value, next_plan)
                return True
            _finish(db, session, task, value, 'quantity_shortfall' if produced is not None and produced < target else 'completed')
            if plan.workflow.postprocessing.enabled:
                # A separate draft grants no permission to dispatch TarPass.
                following = deepcopy(task.task_plan)
                following['run']['source_workflow_ids'] = list(state['rounds'])
                following['run']['postprocessed_workflow_ids'] = []
                store(task, following)
                postprocessing = plan.workflow.postprocessing.model_dump(mode='json')
                if 'prefilters' in (task.workflow_preferences or {}).get('postprocessing', {}):
                    postprocessing['prefilters'] = deepcopy(task.workflow_preferences['postprocessing']['prefilters'])
                turn = internal_turn(db, session, task, f"post-draft:{value['version']}",
                    session_text(db, session, '已生成后处理草稿，请检查方案中的实际前筛条件并批准执行。' if postprocessing['prefilters'] else '已生成后处理草稿，不设置性质前筛。请检查方案并批准执行。',
                        'A postprocessing draft has been created. Review its configured prefilters before approval.' if postprocessing['prefilters'] else 'A postprocessing draft has been created without property prefilters. Review the plan before approval.'))
                source = db.get(WorkflowRun, uuid.UUID(state['rounds'][0]))
                definition = deepcopy(source.plan_json)
                definition['postprocessing'] = postprocessing
                save(db, session, turn, {'stage': 'postprocessing', 'workflow': definition, 'sampling': None,
                    'preparation': None, 'site': None})
                session.phase = 'awaiting_postprocessing_approval'
            return True
        if stage == 'postprocessing' and str(child.id) not in state.setdefault('postprocessed_workflow_ids', []):
            state['postprocessed_workflow_ids'].append(str(child.id))
        remaining = [identity for identity in state.get('source_workflow_ids', [])
            if identity not in state.get('postprocessed_workflow_ids', [])]
        if remaining:
            source = db.get(WorkflowRun, uuid.UUID(remaining[0]))
            state['source_workflow_id'] = str(source.id)
            definition = deepcopy(source.plan_json)
            definition['postprocessing'] = plan.workflow.postprocessing.model_dump(mode='json')
            definition['selection'] = plan.workflow.selection.model_dump(mode='json')
            _start_round(db, session, task, value, definition)
            return True
        _finish(db, session, task, value, 'completed')
        return True
    return True


def can_submit(db, workflow):
    version = (workflow.execution_binding or {}).get('task_plan_version')
    if version is None:
        return True
    task = db.get(ResearchTask, workflow.research_task_id)
    value = task.task_plan
    return bool(value and value['state'] == 'running' and value['version'] == version
        and utcnow() < datetime.fromisoformat(value['run']['deadline']))


def advance(db, session):
    task = db.get(ResearchTask, session.research_task_id)
    if task is None or not task.task_plan:
        return False
    from fastapi import HTTPException
    from backend.services.jobs import DomainValidationError
    try:
        with db.begin_nested():
            handled = _advance(db, session)
            if task.task_plan['state'] == 'blocked':
                session.phase = 'failed'
            return handled
    except (WorkflowError, DomainValidationError, HTTPException, ValueError) as error:
        task = db.get(ResearchTask, session.research_task_id)
        if task is None or not task.task_plan or task.task_plan['state'] not in ACTIVE:
            raise
        value = deepcopy(task.task_plan)
        value['state'] = 'blocked'
        session.phase = 'failed'
        value['run']['error'] = str(getattr(error, 'message', None) or getattr(error, 'detail', None) or error)[:2000]
        store(task, value)
        internal_turn(db, session, task, f"blocked:{value['version']}:{value['run'].get('phase')}",
            session_text(db, session, '任务已暂停，请查看错误详情。', 'The task is paused. See error details.'))
        return True


def capture_workflow(db, session, source_turn, workflow):
    task = db.get(ResearchTask, session.research_task_id)
    if source_turn.audit.get('task_plan_event'):
        return
    if task.task_plan and task.task_plan['state'] in ACTIVE:
        raise WorkflowError('TASK_PAUSE_REQUIRED', 'Pause the task before revising its plan', 409)
    turn = internal_turn(db, session, task, f'draft:{source_turn.id}')
    existing = db.scalar(select(ActionProposal).where(ActionProposal.turn_id == turn.id))
    if existing:
        return
    planned = deepcopy(workflow.plan_json)
    choice = ((task.workflow_preferences or {}).get('postprocessing') or {}).get('choice')
    if choice in {'run', 'skip'}:
        planned['postprocessing']['enabled'] = choice == 'run'
    save(db, session, turn, {'stage': 'generation', 'workflow': planned, 'preparation': None, 'site': None})
    if workflow.action_proposal_id:
        db.get(ActionProposal, workflow.action_proposal_id).status = 'stale'


def require_editable(db, session, turn):
    task = db.get(ResearchTask, session.research_task_id)
    if task and task.task_plan and task.task_plan['state'] in ACTIVE and not turn.audit.get('task_plan_event'):
        raise WorkflowError('TASK_PAUSE_REQUIRED', 'Pause the task before changing its inputs or plan', 409)


def stop(db, session, *, cancel=False):
    task = db.get(ResearchTask, session.research_task_id)
    if task and task.task_plan and task.task_plan['state'] in ACTIVE:
        if cancel:
            value = deepcopy(task.task_plan)
            value['state'] = 'canceled'
            store(task, value)
        else:
            pause(db, session)


def approved_analysis(db, session, turn):
    from backend.agent.research_safety import require_task
    task = require_task(db, session.research_task_id, session.owner_user_id)
    value = task.task_plan
    if not value or value['state'] not in ACTIVE or value['version'] != turn.audit.get('task_plan_version'):
        raise WorkflowError('PLAN_CHANGED', 'The automatic turn belongs to an inactive task plan', 409)
    proposal = db.get(ActionProposal, uuid.UUID(value['proposal_id']))
    if proposal.status != 'approved' or proposal.payload['task_plan_version'] != value['version']:
        raise WorkflowError('ACTION_APPROVAL_REQUIRED', 'Approve the task plan before automatic analysis', 409)
    return {**task.assessment, 'task_id': str(task.id), 'revision': task.revision, 'decision': 'allow',
        'task_state': 'allowed', 'language': task_language(task), 'answer_only': False}


def capture_postprocessing(db, session, source_turn, workflow, proposal):
    if source_turn.audit.get('task_plan_event'):
        return
    task = db.get(ResearchTask, session.research_task_id)
    turn = internal_turn(db, session, task, f'postdraft:{source_turn.id}')
    existing = db.scalar(select(ActionProposal).where(ActionProposal.turn_id == turn.id))
    if existing:
        return
    planned = deepcopy(workflow.plan_json)
    config = proposal.payload['postprocessing']
    planned['postprocessing'] = {'enabled': True, 'prefilters': config['prefilters']}
    selected = proposal.payload['selection']
    planned['selection'] = {key: selected.get(key) for key in ('sort_by', 'descending', 'top_k')}
    result = save(db, session, turn, {'stage': 'postprocessing', 'workflow': planned, 'key_interactions': config['key_interactions'],
        'reference_dataset_id':config.get('reference_dataset_id')})
    proposal.status = 'stale'
    return result


def ranked_candidates(db, session, workflow_ids, selection):
    from backend.services.results import load_tarpass_results, apply_query
    rows = []
    for workflow_id in workflow_ids:
        post = next(step for step in workflow_steps(db, uuid.UUID(workflow_id)) if step.step_key == 'postprocessing')
        if post.status != 'succeeded' or not post.job_id:
            continue
        _, _, results = load_tarpass_results(db, user_id=session.owner_user_id, job_id=post.job_id)
        rows.extend({**row, 'source_job_id':str(post.job_id), 'workflow_id':workflow_id}
            for row in results if row['status'] == 'succeeded')
    return apply_query(rows, filters=[], sort_by=selection.sort_by or 'molecule_id', descending=selection.descending)


def valid_generation_count(db, session, workflow_ids):
    import csv
    from rdkit import Chem
    from backend.services.jobs import get_owned_job, resolve_job_artifact
    unique = set()
    completed = False
    for workflow_id in workflow_ids:
        generation = next(step for step in workflow_steps(db, uuid.UUID(workflow_id)) if step.step_key == 'generation')
        if generation.status != 'succeeded':
            continue
        completed = True
        job = get_owned_job(db, session.owner_user_id, generation.job_id)
        task = db.scalar(select(JobTask).where(JobTask.job_id == job.id))
        output = task.output_payload if task else {}
        if not output or not output.get('output_csv'):
            return None
        with resolve_job_artifact(job, output['output_csv']).open(newline='') as source:
            for row in csv.DictReader(source):
                molecule = Chem.MolFromSmiles(row['smiles'])
                if molecule:
                    unique.add(Chem.MolToSmiles(molecule))
    return len(unique) if completed else None
