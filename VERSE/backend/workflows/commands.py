"""Authenticated, versioned commands shared by chat, cards and editors."""
import copy
import uuid
from sqlalchemy import select
from backend.models import DesignDraft, WorkflowCommand, WorkflowEvent, AgentTurn, ActionProposal
from backend.utils import utcnow
from backend.agent.language import session_interface_language, turn_text
from backend.agent.schemas import WorkflowPlan
from backend.agent.session_schemas import SessionTurnRequest, SelectionSpec
from backend.services.workflows import WorkflowError, owned_workflow, persist_workflow_preview


def emit(db, object_id, version, kind, key, payload=None):
    from sqlalchemy.dialects.postgresql import insert
    db.execute(insert(WorkflowEvent).values(id=uuid.uuid4(), object_id=object_id, version=version,
        kind=kind, event_key=key, payload=payload or {}).on_conflict_do_nothing(index_elements=["event_key"]))


def design(db, session):
    row = db.get(DesignDraft, session.id)
    if row is None:
        if session.input_revision:
            raise WorkflowError("INPUT_UNVERIFIED", "Create a new session with current input bindings", 409)
        row = DesignDraft(id=session.id, owner_user_id=session.owner_user_id, revision=session.input_revision,
            assets=dict(session.assets), values={k: v["value"] for k, v in session.confirmed_fields.items()},
            provenance="verified")
        db.add(row)
        db.flush()
    return row


def diff(before, after, prefix=""):
    changes = []
    for key in sorted(before.keys() | after.keys()):
        path = f"{prefix}.{key}".lstrip(".")
        old, new = before.get(key), after.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            changes.extend(diff(old, new, path))
        elif old != new:
            changes.append({"field": path, "before": old, "after": new})
    return changes


def merge_patch(before, changes):
    result = copy.deepcopy(before)
    for key, value in changes.items():
        result[key] = merge_patch(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def patch_plan(plan, changes):
    if changes.keys() - {"generation", "selection", "postprocessing", "generator", "template", "seed_source"}:
        raise WorkflowError("INVALID_INPUT", "Unsupported workflow field", 422)
    result = copy.deepcopy(plan)
    for key, value in changes.items():
        if key in {"generation", "selection", "postprocessing"} and isinstance(value, dict):
            if key == "generation" and value.get("engine", result[key]["engine"]) != result[key]["engine"]:
                result[key] = value
            else:
                result[key] = merge_patch(result[key], value)
        else:
            result[key] = value
    return WorkflowPlan.model_validate(result)


def save_plan(db, session, turn, plan, *, expected_plan_version=None, new=False, create_workflow_id=None):
    from backend.services import agent_sessions as sessions
    from backend.agent.research_safety import require_task
    task = require_task(db, turn.research_task_id or session.research_task_id, session.owner_user_id)
    from backend.services.jobs import validate_protein_context_for_generation
    from backend.agent.catalog import CATALOG
    if plan.generator == "delete" and not plan.generation.edit.edit_spec_id:
        raise WorkflowError("DELETE_EDITOR_REQUIRED", "Confirm DELETE sites in the visual editor before creating a proposal", 422)
    context = validate_protein_context_for_generation(db, session.owner_user_id, uuid.UUID(plan.protein_context_id))
    from genova_runtime.structure_inputs import validate_context_engine_support
    try:
        validate_context_engine_support(context, plan.generator)
    except ValueError as exc:
        raise WorkflowError('PREPARATION_REQUIRED', str(exc), 422) from exc
    if plan.generator in {"delete", "epso"} and not context.get("reference_ligand_path") and not context.get("generation_reference"):
        raise WorkflowError("REFERENCE_REQUIRED", "This engine requires a prepared reference ligand", 422)
    if any(not CATALOG.validate_prefilter_metric(f.metric) for f in plan.postprocessing.prefilters):
        raise WorkflowError("INVALID_INPUT", "Invalid TarPass configuration", 422)
    if plan.selection.sort_by and plan.selection.sort_by != "molecule_id" and not CATALOG.validate_sort_field(plan.selection.sort_by):
        raise WorkflowError("INVALID_METRIC", "Unknown sort metric", 422)
    old = owned_workflow(db, session.active_workflow_id, session.owner_user_id, lock=True) if session.active_workflow_id and not new else None
    if old:
        db.refresh(old, with_for_update=True)
        if create_workflow_id is not None:
            updating = old.status == "awaiting_approval"
            reserved_existing = create_workflow_id == old.id
            if updating != reserved_existing:
                raise WorkflowError("PLAN_CHANGED", "Workflow state changed; preview the plan again before saving", 409)
    before = copy.deepcopy(old.plan_json) if old else {}
    run = persist_workflow_preview(db, owner_user_id=session.owner_user_id, plan=plan,
        workflow_id=old.id if old and old.status == "awaiting_approval" else None,
        expected_plan_version=expected_plan_version if old and old.status == "awaiting_approval" else None, domain_managed=True, create_workflow_id=create_workflow_id)
    run.research_task_id = task.id
    changes = diff(before, run.plan_json)
    if not changes and old:
        pending = db.scalar(select(ActionProposal).where(ActionProposal.workflow_id == old.id, ActionProposal.status == "pending"))
        if pending:
            return {"workflow_id": str(run.id), "version": session.input_revision, "diff": [], "noop": True, "proposal_id": str(pending.id)}
        proposal = sessions.workflow_proposal(db, session, turn, run)
        return {"workflow_id": str(run.id), "version": session.input_revision, "diff": [], "proposal_id": str(proposal.id), "message": turn_text(turn, "已刷新输入绑定，请批准当前提案。", "Input bindings have been refreshed. Approve the current proposal.")}
    session.input_revision += 1
    draft = design(db, session)
    draft.revision = session.input_revision
    old_filters = before.get("postprocessing", {}).get("prefilters", [])
    previous_ids = (draft.condition_ids or {}).get(str(old.id), []) if old else []
    ids = []
    for rule in run.plan_json["postprocessing"]["prefilters"]:
        matches = [i for i, item in enumerate(old_filters) if item["metric"] == rule["metric"] and item["op"] == rule["op"]]
        ids.append(previous_ids[matches[0]] if len(matches) == 1 and matches[0] < len(previous_ids) else str(uuid.uuid4()))
    draft.condition_ids = {**(draft.condition_ids or {}), str(run.id): ids}
    proposal = sessions.workflow_proposal(db, session, turn, run)
    from backend.services.task_plans import capture_workflow
    capture_workflow(db, session, turn, run)
    emit(db, run.id, run.plan_version, "draft_updated", f"draft:{run.id}:{run.plan_version}", {"source_turn_id": str(turn.id)})
    return {"workflow_id": str(run.id), "version": session.input_revision, "plan_version": run.plan_version,
            "proposal_id": str(proposal.id), "diff": changes, "message": turn_text(turn, "方案已保存，请批准当前版本。", "The plan has been saved. Approve the current version.")}


def execute(db, session, command, *, source, interaction_id=None, interface_language=None):
    from backend.services import agent_sessions as sessions
    from backend.services.workflows import cancel_workflow
    if source not in {"chat", "card", "visual_editor"}:
        raise ValueError("Invalid server command source")
    if command.operation not in {"cancel", "stop_continuation", "archive"}:
        from backend.agent.research_safety import require_task
        require_task(db, session.research_task_id, session.owner_user_id)
    body = command.model_dump(mode="json")
    if body.get("task_plan_version") is None:
        body.pop("task_plan_version", None)
    body_hash = sessions.digest(body)
    prior = db.get(WorkflowCommand, command.command_id)
    if prior:
        if prior.owner_user_id != session.owner_user_id or prior.target_id != session.id or prior.request_hash != body_hash or prior.source != source:
            raise WorkflowError("IDEMPOTENCY_KEY_REUSED", "Command ID is already bound to different content", 409)
        return prior.response
    if command.expected_version != session.input_revision:
        raise WorkflowError("INPUT_CHANGED", f"Draft version changed; current version is {session.input_revision}", 409)
    draft = design(db, session)
    before = {"assets": copy.deepcopy(draft.assets), "values": copy.deepcopy(draft.values)}
    session.last_user_activity_at = utcnow()
    row = WorkflowCommand(id=command.command_id, owner_user_id=session.owner_user_id, target_id=session.id,
        request_hash=body_hash, source=source)
    db.add(row)
    request = SessionTurnRequest(client_request_id=command.command_id, intent="ask", base_revision=session.input_revision,
        interface_language=interface_language or session_interface_language(db, session))
    turn = AgentTurn(id=uuid.uuid4(), session_id=session.id, research_task_id=session.research_task_id, client_request_id=command.command_id,
        request_hash=body_hash, request=request.model_dump(mode="json"), status="completed", attempt=1,
        response={}, audit={"source": source, "interaction_id": str(interaction_id) if interaction_id else None, "operation": command.operation})
    db.add(turn)
    db.flush()
    operation = command.operation
    if operation in {'bind', 'select_context', 'prepare', 'save_site', 'create_workflow', 'patch_workflow', 'prepare_postprocessing', 'retry_postprocessing'}:
        from backend.services.task_plans import require_editable
        require_editable(db, session, turn)
    if operation in {"approve_task_plan", "create_task_plan", "patch_task_plan", "pause_task", "resume_task"}:
        from backend.services import task_plans
        if operation in {"approve_task_plan", "create_task_plan", "patch_task_plan"}:
            if operation in {"approve_task_plan", "patch_task_plan"}:
                from backend.models import ResearchTask
                task = db.get(ResearchTask, session.research_task_id)
                if command.task_plan_version != (task.task_plan or {}).get('version'):
                    raise WorkflowError('PLAN_CHANGED', 'Refresh the task plan before editing', 409)
            preparation = command.changes.get('preparation')
            if preparation and command.changes.get('stage') == 'preparation':
                sessions.change_inputs(db, session, turn, SessionTurnRequest(client_request_id=turn.client_request_id,
                    intent='select_context', values={key: preparation[key] for key in ('name', 'prepared_spec') if key in preparation}))
            result = task_plans.save(db, session, turn, command.changes)
            session.last_error = None
            if operation == 'approve_task_plan':
                proposal = db.get(ActionProposal, uuid.UUID(result['proposal_id']))
                sessions.approve_proposal(db, session, proposal.id, proposal.action_hash)
                result['message'] = turn_text(turn, '已批准当前阶段，开始执行。', 'The current stage has been approved. Execution is starting.')
        elif operation == "pause_task":
            result = task_plans.pause(db, session)
        else:
            result = task_plans.resume(db, session)
    elif operation == 'retry_session':
        if session.last_error != 'SESSION_RECONCILIATION_FAILED':
            raise WorkflowError('INVALID_INPUT', 'This session does not require synchronization recovery', 409)
        if session.active_workflow_id:
            run = owned_workflow(db, session.active_workflow_id, session.owner_user_id, lock=True)
            if run.refinement_state == 'reconciliation_failed':
                run.refinement_state = 'running'
        session.last_error = None
        session.phase = 'executing' if session.active_workflow_id else ('ready_for_planning' if session.assets.get('protein_context_id') else 'preparing' if session.preparation_job_id else 'awaiting_selection')
        result = {'message': turn_text(turn, '已恢复状态同步，将复用已有任务和结果继续检查。', 'Status synchronization has resumed using existing tasks and results.')}
    elif operation in {"create_workflow", "patch_workflow"}:
        old = owned_workflow(db, session.active_workflow_id, session.owner_user_id, lock=True) if operation == "patch_workflow" else None
        changes = dict(command.changes)
        if old and "filter_updates" in changes:
            ids = (draft.condition_ids or {}).get(str(old.id), [])
            existing = old.plan_json["postprocessing"]["prefilters"]
            if len(ids) != len(existing):
                raise WorkflowError("INPUT_CHANGED", "Refresh the proposal before editing conditions", 409)
            conditions = dict(zip(ids, existing))
            updates = changes.pop("filter_updates")
            if not isinstance(updates, dict):
                raise WorkflowError("INVALID_INPUT", "Filter updates must be keyed by stable condition IDs", 422)
            for key, value in updates.items():
                uuid.UUID(key)
                if value is None:
                    if key not in conditions:
                        raise WorkflowError("INPUT_CHANGED", "Filter condition no longer exists", 409)
                    del conditions[key]
                else:
                    conditions[key] = {**conditions.get(key, {}), **value}
            changes["postprocessing"] = {**changes.get("postprocessing", {}), "prefilters": list(conditions.values())}
        else:
            conditions = None
        plan = patch_plan(old.plan_json, changes) if old else WorkflowPlan.model_validate(changes)
        result = save_plan(db, session, turn, plan, expected_plan_version=old.plan_version if old else None, new=old is None)
        if conditions is not None:
            draft.condition_ids = {**(draft.condition_ids or {}), result["workflow_id"]: list(conditions)}
    elif operation == "prepare_postprocessing":
        result = sessions.prepare_postprocessing(db, session, turn, dict(command.changes))
    elif operation == "approve":
        proposal = sessions.approve_proposal(db, session, command.proposal_id, command.action_hash)
        result = {"proposal": sessions.proposal_out(proposal), "message": turn_text(turn, "已批准当前提案。", "The current proposal has been approved.")}
    elif operation == "cancel":
        from backend.services.task_plans import stop
        stop(db, session, cancel=True)
        if session.active_workflow_id:
            run = owned_workflow(db, session.active_workflow_id, session.owner_user_id, lock=True)
            if run.status in {"awaiting_approval", "approved", "running", "cancel_requested"}:
                cancel_workflow(db, workflow_id=run.id, owner_user_id=session.owner_user_id)
        session.phase = "cancel_requested"
        result = {"message": turn_text(turn, "已请求停止后续执行；底层任务状态以执行器回报为准。", "A stop has been requested. Task status follows the executor’s reported state.")}
    elif operation in {"stop_continuation", "archive"}:
        from backend.services.task_plans import stop
        stop(db, session, cancel=operation == "archive")
        for origin in db.scalars(select(AgentTurn).where(AgentTurn.session_id == session.id, (AgentTurn.research_task_id == session.research_task_id) if operation == "stop_continuation" else True)):
            if operation == 'stop_continuation' and origin.audit.get('trigger') == 'task_plan':
                continue
            origin.audit = {**origin.audit, "continuation": None}
            if origin.audit.get("trigger") and origin.status == "queued":
                origin.status = "completed"
        if operation == "archive":
            session.phase = "archived"
        result = {"message": turn_text(turn, "已停止自动续接，已批准的计算继续执行。", "Automatic continuation has stopped. Approved computations will continue.")}
    else:
        req = request.model_copy(update={"intent": operation, "values": command.changes,
            "selection": SelectionSpec.model_validate(command.changes) if operation == "selection" else None})
        result = sessions.execute_action(db, session, turn, req)
    if command.approve_after_save:
        if operation not in {'create_workflow', 'patch_workflow', 'prepare_postprocessing', 'selection'}:
            raise WorkflowError('INVALID_INPUT', 'This command does not support saving and approving', 422)
        from backend.models import ResearchTask
        task = db.get(ResearchTask, session.research_task_id)
        identity = result.get('proposal_id') if operation == 'selection' else (task.task_plan or {}).get('proposal_id') or result.get('proposal_id')
        proposal = db.get(ActionProposal, uuid.UUID(identity))
        sessions.approve_proposal(db, session, proposal.id, proposal.action_hash)
        result['message'] = (turn_text(turn, '候选集合已保存。', 'The candidate set has been saved.') if operation == 'selection'
            else turn_text(turn, '已批准当前阶段，开始执行。', 'The current stage has been approved. Execution is starting.'))
    result = {**result, "version": session.input_revision, "command_id": str(command.command_id), "source": source}
    if "diff" not in result:
        result["diff"] = diff(before, {"assets": draft.assets, "values": draft.values})
    turn.response = result
    row.response = result
    emit(db, session.id, session.input_revision, operation, f"command:{command.command_id}", {"command_id": str(command.command_id), "source": source})
    db.flush()
    return result


def update_inputs(db, draft, operation, changes):
    from typing import get_args
    from backend.agent.session_schemas import AssetField, ScientificField, validate_structure_values
    from backend.services.jobs import get_owned_dataset, validate_protein_context_for_generation, validate_protein_context_ready
    from backend.services.protein_contexts import _protein_file_or_400
    before = {"assets": copy.deepcopy(draft.assets), "values": copy.deepcopy(draft.values)}
    assets, values = dict(draft.assets), dict(draft.values)
    if operation == "bind":
        if changes.keys() - set(get_args(AssetField)) or ((changes.get("protein_context_id") or changes.get("prepared_receptor_id")) and len(changes) != 1):
            raise WorkflowError("INVALID_INPUT", "Bind either a Context or source datasets", 422)
        for key, value in changes.items():
            if value is None:
                assets.pop(key, None)
                continue
            resource = get_owned_dataset(db, uuid.UUID(str(value)), draft.owner_user_id)
            if key == "protein_context_id":
                validate_protein_context_ready(db, draft.owner_user_id, resource.id)
                assets = {key: str(resource.id)}
            elif key == "prepared_receptor_id":
                if resource.kind != "prepared_receptor" or resource.status != "ready":
                    raise WorkflowError("PREPARATION_REQUIRED", "Select a completed prepared receptor", 422)
                from backend.services.prepared_receptors import prepared_spec
                try:
                    prepared_spec(resource.meta)
                except ValueError as exc:
                    raise WorkflowError('PREPARATION_REQUIRED', 'Select a current prepared receptor', 422) from exc
                assets = {key: str(resource.id)}
            else:
                old_context = assets.pop("protein_context_id", None)
                if old_context and key == "ligand_dataset_id":
                    raise WorkflowError('INPUT_CHANGED', 'Create a new binding site to change its generation reference', 409)
                if key == "protein_dataset_id" and assets.get(key) not in (None, str(resource.id)):
                    # The reference file and prepared result belonged to the replaced file, unless sent again with it.
                    for derived in ("ligand_dataset_id", "prepared_receptor_id"):
                        if derived not in changes:
                            assets.pop(derived, None)
                assets[key] = str(resource.id)
        if assets != draft.assets:
            values = {}
    else:
        if changes.keys() - set(get_args(ScientificField)):
            raise WorkflowError("INVALID_INPUT", "Unsupported scientific field", 422)
        validate_structure_values(changes)
        if assets.get("protein_context_id") and changes.keys() & {"site", "generation_reference"}:
            context = get_owned_dataset(db, uuid.UUID(assets["protein_context_id"]), draft.owner_user_id)
            if context.meta.get("version") != 4:
                raise WorkflowError("INVALID_INPUT", "Protein Context v4 is required", 422)
            assets = {"prepared_receptor_id": context.meta["prepared_receptor_id"]}
            values = {key: context.meta[key] for key in ("site", "generation_reference", "prepared_artifact_sha256")}
        if changes.get("prepared_spec"):
            from backend.structure_contracts import PreparedReceptorSpec
            spec = PreparedReceptorSpec.model_validate(changes['prepared_spec'])
            if str(spec.source.dataset_id) != assets.get('protein_dataset_id'):
                raise WorkflowError('INPUT_CHANGED', 'Bind the matching source dataset before preparation', 409)
            previous = values.get('prepared_spec')
            if previous and PreparedReceptorSpec.model_validate(previous) == spec:
                changes = {**changes, 'prepared_spec': previous}
            else:
                assets.pop('prepared_receptor_id', None)
                assets.pop('protein_context_id', None)
        if 'site' in changes:
            values.pop('prepared_spec', None)
        base_values = copy.deepcopy(values)
        before["values"] = base_values
        for key, value in changes.items():
            values[key] = value
        if changes.get("protein_file_id") and assets.get("protein_dataset_id"):
            _protein_file_or_400(db, uuid.UUID(assets["protein_dataset_id"]), values["protein_file_id"])
        if values.get("delete_edit_spec_id"):
            from backend.models import DeleteEditSpec
            from genova_runtime.pdb2pqr_compat import file_sha256
            spec = db.get(DeleteEditSpec, uuid.UUID(values["delete_edit_spec_id"]))
            if spec is None or spec.owner_user_id != draft.owner_user_id or not assets.get("protein_context_id"):
                raise WorkflowError("INVALID_STRUCTURE_EDIT", "Select an owned DELETE edit and prepared Context", 422)
            context = validate_protein_context_for_generation(db, draft.owner_user_id, uuid.UUID(assets["protein_context_id"]))
            from backend.services.jobs import delete_reference_path
            if file_sha256(delete_reference_path(context)) != spec.reference_sha256:
                raise WorkflowError("INPUT_CHANGED", "Reference ligand changed", 409)
    changeset = diff(before, {"assets": assets, "values": values})
    if changeset:
        draft.assets, draft.values = assets, values
        draft.revision += 1
    return changeset
