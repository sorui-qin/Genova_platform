"""Persistent Agent turns and approved actions; model calls never own this transaction."""
from __future__ import annotations

from copy import deepcopy
from backend.services.jobs import delete_reference_path
from genova_runtime.generation_settings import DEFAULT_GENERATION_COUNT

from typing import get_args

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agent.language import session_text, session_interface_language, turn_text
from backend import schemas
from backend.workflows.contracts import digest
from backend.agent.session_schemas import AssetField, ScientificField, StructureField, SelectionSpec, SessionTurnRequest
from backend.agent.schemas import WorkflowPlan, calculate_plan_hash
from backend.agent.runner import Budget
from backend.models import AgentSession, AgentTurn, ActionProposal, CandidateSet, Dataset, DatasetFile, EditSession, Job, ResearchTask, WorkflowRun, WorkflowStep, WorkflowPlanningRequest
from backend.services import protein_contexts
from backend.services.jobs import (get_owned_dataset, get_dataset_files, get_owned_job,
    create_protein_preparation_job, validate_protein_context_for_generation,
    create_postprocessing_job, resolve_job_artifact, DomainValidationError, ResourceNotFound)
from backend.services.results import ResultServiceError, load_tarpass_results
from backend.services.workflows import (WorkflowError, POSTPROCESSING_APPROVAL_PROTOCOL_VERSION,
    owned_workflow, workflow_status_dict, workflow_steps, approve_workflow, cancel_workflow)
from backend.utils import utcnow
from genova_runtime.pdb2pqr_compat import file_sha256
from genova_runtime.generation_settings import generation_settings
from genova_runtime.epso_objectives import validate_parameters
from tarpass.filters import METRICS




def owned_session(db, session_id, user_id, *, lock=False):
    stmt = select(AgentSession).where(AgentSession.id == session_id, AgentSession.owner_user_id == user_id)
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if row is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Agent session not found", 404)
    return row


def session_values(session):
    return {key: value["value"] for key, value in session.confirmed_fields.items()}


def postprocessing_operation(db, session):
    run = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
    steps = {step.step_key: step for step in workflow_steps(db, run.id)}
    if steps["generation"].status == "succeeded" and steps["postprocessing"].status != "failed":
        return "prepare_postprocessing"
    return "retry_postprocessing"


def record_postprocessing_choice(db, session, turn, choice, evidence):
    if choice not in {"run", "skip"} or not evidence:
        raise WorkflowError("INVALID_INPUT", "A postprocessing choice requires exact user evidence", 422)
    task = db.scalar(select(ResearchTask).where(
        ResearchTask.id == session.research_task_id,
        ResearchTask.owner_user_id == session.owner_user_id,
    ).with_for_update())
    if task is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Research task not found", 404)
    preferences = deepcopy(task.workflow_preferences or {})
    preferences["postprocessing"] = {
        **preferences.get('postprocessing', {}),
        "choice": choice,
        "evidence": evidence[:4000],
        "turn_id": str(turn.id),
        "updated_at": utcnow().isoformat(),
    }
    task.workflow_preferences = preferences
    turn.audit = {**(turn.audit or {}), "postprocessing_choice": preferences["postprocessing"]}
    db.flush()
    return preferences["postprocessing"]


def pending_clarification_fields(db, session):
    from backend.agent.clarification import presentation_fields
    from backend.agent.session_schemas import CLARIFICATION_IDS
    requirements = session.pending_requirements or []
    known = []
    unresolved = set(requirements)
    if unresolved:
        turns = db.scalars(select(AgentTurn).where(AgentTurn.session_id == session.id, AgentTurn.research_task_id == session.research_task_id,
            AgentTurn.status == "needs_input").order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc()))
        for turn in turns:
            matching = unresolved.intersection(turn.response.get("missing_requirements", []))
            saved = [field for field in turn.response.get('clarification_fields', [])
                     if field['requirement'] in matching and field['id'] in CLARIFICATION_IDS]
            known.extend(saved)
            unresolved -= {field['requirement'] for field in saved}
            if not unresolved:
                break
    return presentation_fields(requirements, known)


def fingerprint(db, session, payload=None):
    from backend.workflows.commands import design
    from backend.workflows.bindings import snapshot_inputs
    draft = design(db, session)
    if draft.revision != session.input_revision:
        raise WorkflowError("INPUT_CHANGED", "Draft and session projection versions differ; refresh before approval", 409)
    return snapshot_inputs(db, draft.owner_user_id, draft.assets, draft.values, draft.revision, payload)


def interrupt_turn(db, session, turn):
    turn.status = "interrupted"
    planning = db.scalar(select(WorkflowPlanningRequest).where(
        WorkflowPlanningRequest.owner_user_id == session.owner_user_id,
        WorkflowPlanningRequest.client_request_id == uuid.UUID(turn.audit.get("command_turn_id", str(turn.id))),
    ).with_for_update())
    if planning is not None and planning.status == "planning":
        planning.status = "interrupted"
        planning.last_error = "PLANNING_INTERRUPTED"
        planning.updated_at = utcnow()


def claim_turn(db, session, request: SessionTurnRequest, *, queued=False):
    now = utcnow()
    body = request.model_dump(mode="json", exclude={"retry"})
    if body.get("task_plan") is None:
        body.pop("task_plan", None)
    if body.get("interface_language") is None:
        body.pop("interface_language", None)
    # The page language can change between a send and its retry; it is not part of what was asked.
    request_hash = digest({k: v for k, v in body.items() if k != "interface_language"})
    turns = db.scalars(select(AgentTurn).where(AgentTurn.session_id == session.id,
        (AgentTurn.client_request_id == request.client_request_id) | AgentTurn.status.in_(["running", "queued"]))).all()
    existing = None
    for row in turns:
        if row.status == "running" and row.lease_until.replace(tzinfo=timezone.utc) <= now:
            interrupt_turn(db, session, row)
        if row.client_request_id == request.client_request_id:
            existing = row
    if existing:
        if request.retry and existing.audit.get("resumed_by"):
            raise WorkflowError("TURN_SUPERSEDED", "Continue the latest recovery turn instead", 409)
        if existing.request_hash != request_hash:
            raise WorkflowError("REQUEST_CONFLICT", "Request ID was used for different content", 409)
        if not request.retry or existing.status not in {"interrupted", "failed"}:
            return existing, False
    if existing and existing.attempt >= 3:
        raise WorkflowError("PLANNING_RETRY_LIMIT", "This turn reached its three-attempt limit", 409)
    if any(row.status == "running" or (row.status == "queued" and not row.audit.get("trigger")) for row in turns):
        raise WorkflowError("TURN_RUNNING", "Another turn is still running", 409)
    expected_revision = existing.audit.get("execution_revision", request.base_revision) if existing else request.base_revision
    if request.intent != "ask" and expected_revision != session.input_revision:
        raise WorkflowError("INPUT_CHANGED", "Refresh the session before changing its inputs", 409)
    row = existing or AgentTurn(session_id=session.id, client_request_id=request.client_request_id,
                                request_hash=request_hash, request=body, attempt=0)
    if existing:
        row.audit = {**row.audit, "attempts": {**row.audit.get("attempts", {}), str(row.attempt): {
            "diagnostic": row.audit.get("diagnostic", {}), "status": row.status, "response": row.response,
            "error_code": row.response.get("error_code")}}}
    if existing and request.interface_language:
        row.request = {**row.request, 'interface_language': request.interface_language}
    row.attempt += 1
    row.status = "queued" if queued else "running"
    row.lease_until = now + timedelta(seconds=Budget().lease_seconds)
    row.response = {}
    db.add(row)
    db.flush()
    return row, True


def change_inputs(db, session, turn, request):
    from backend.agent.research_safety import require_task
    require_task(db, session.research_task_id, session.owner_user_id)
    from backend.workflows.commands import design, emit, update_inputs
    pending = list(session.pending_requirements or [])
    fields = pending_clarification_fields(db, session)
    resolved = set(request.values)
    if request.values.get('protein_context_id'):
        resolved.update(get_args(StructureField))
    answered = {field['requirement'] for field in fields if field['id'] in resolved}
    pending = [item for item in pending if item not in answered]
    draft = design(db, session)
    changes = update_inputs(db, draft, request.intent, request.values)
    session.assets = dict(draft.assets)
    session.confirmed_fields = {key: session.confirmed_fields[key] if key in session.confirmed_fields and session.confirmed_fields[key]["value"] == value else {"value": value, "source": (turn.audit or {}).get("source", "chat"), "turn_id": str(turn.id)} for key, value in draft.values.items()}
    session.input_revision = draft.revision
    if changes:
        session.last_error = None
        if request.intent == "bind" or request.values.keys() & {"protein_file_id", "prepared_spec", "site", "generation_reference", "delete_edit_spec_id"}:
            session.active_workflow_id = None
            session.preparation_job_id = None
        for proposal in db.scalars(select(ActionProposal).where(
                ActionProposal.session_id == session.id,
                ActionProposal.status.in_(["pending", "approved"]))).all():
            if proposal.status == "pending" or (
                    proposal.kind == "postprocessing"
                    and not (proposal.execution or {}).get("job_id")):
                proposal.status = "stale"
        emit(db, draft.id, draft.revision, "inputs_updated", f"inputs:{draft.id}:{draft.revision}", {"turn_id": str(turn.id)})
        effects = list((turn.audit or {}).get("committed_effects", []))
        effect = {"kind": "inputs_saved", "version": draft.revision}
        if effect not in effects:
            effects.append(effect)
        turn.audit = {**(turn.audit or {}), "committed_effects": effects}
    session.phase = "ready_for_planning" if session.assets.get("protein_context_id") else ("awaiting_selection" if session.assets else "awaiting_upload")
    if session.assets.get('prepared_receptor_id'):
        session.phase, pending = 'awaiting_site', list(dict.fromkeys(pending + ['site']))
    session.pending_requirements = pending
    return {"message": turn_text(turn, "已保存输入选择。", "Input selection has been saved."), "missing_requirements": pending, "diff": changes}


def create_proposal(db, session, turn, kind, payload, *, workflow=None):
    bound = fingerprint(db, session, payload)
    action_hash = digest({"kind": kind, "payload": payload, "input": bound})
    existing = db.scalar(select(ActionProposal).where(ActionProposal.session_id == session.id,
        ActionProposal.action_hash == action_hash, ActionProposal.status == "pending"))
    if existing is not None:
        return existing
    proposal = ActionProposal(session_id=session.id, turn_id=turn.id, kind=kind, payload=payload,
        input_fingerprint=bound, action_hash=action_hash,
        workflow_id=workflow.id if workflow else None, status="pending", execution={})
    db.add(proposal)
    db.flush()
    return proposal


def prepare_proposal(db, session, turn):
    structural = {field["requirement"] for field in pending_clarification_fields(db, session) if field["type"] == "structure"}
    remaining = [item for item in session.pending_requirements or [] if item not in structural]
    values = session_values(session)
    if 'prepared_spec' in values:
        from backend.structure_contracts import PreparedReceptorSpec
        from backend.services.prepared_receptors import get_component_manifest, _validate_edits
        spec = PreparedReceptorSpec.model_validate(values['prepared_spec'])
        if str(spec.source.dataset_id) != session.assets.get('protein_dataset_id'):
            raise WorkflowError('INPUT_CHANGED', 'Preparation source must match the bound protein dataset', 409)
        manifest = get_component_manifest(spec.source, db, session.owner_user_id)
        _validate_edits(spec, manifest)
        proposal = create_proposal(db, session, turn, 'prepare', {'preparation_protocol_version': spec.version,
            'prepared_spec': spec.model_dump(mode='json'), 'name': values.get('name', 'Prepared receptor')})
        session.phase, session.pending_requirements = 'awaiting_preparation_approval', remaining
        return {'message': turn_text(turn, '准备提案已生成；批准后仅准备结构，完成后再定义位点。', 'A preparation proposal has been created. Approval prepares the structure; the site is defined afterward.'), 'proposal_id': str(proposal.id), 'missing_requirements': remaining}
    session.pending_requirements = list(dict.fromkeys(remaining + ['prepared_spec']))
    return {'message': turn_text(turn, '请在结构卡片确认完整输入、组分操作和准备策略。', 'Confirm the complete inputs, component operations, and preparation settings in the structure card.'), 'missing_requirements': session.pending_requirements}


def runtime_sources():
    import os
    return {"release": os.environ.get("GENOVA_RELEASE_ID", "unrecorded"),
        "model_images": os.environ.get("GENOVA_MODEL_IMAGES", "unrecorded")}


def effective_generation(plan, seed_source=None):
    config = plan.generation.model_dump(mode="json")
    if plan.generator == "epso":
        result = {"engine": "epso", **validate_parameters(config)}
    else:
        from backend.services.jobs import validated_generation_settings
        result = {**config, **validated_generation_settings(plan.generator, config)}
        if plan.generator == 'ecloudgen' and config.get('num_clouds') is None:
            result['num_clouds'] = None
    seed_source = seed_source or plan.seed_source
    if seed_source and plan.generator == "epso":
        result["seed_source"] = deepcopy(seed_source)
        result["ligand_dataset_id"] = str(seed_source["dataset_id"])
    return result


def workflow_proposal(db, session, turn, workflow, selection=None):
    plan = WorkflowPlan.model_validate(workflow.plan_json)
    if str(plan.protein_context_id) != session.assets.get("protein_context_id"):
        raise WorkflowError("INPUT_CHANGED", "The proposed plan must use the session Context", 409)
    context = validate_protein_context_for_generation(db, session.owner_user_id, uuid.UUID(plan.protein_context_id))
    from tarpass.contracts import protein_residues, validate_interactions
    from backend.services.jobs import pick_dataset_file
    extras = session_values(session)
    try:
        interactions = validate_interactions(extras.get("key_interactions", []), protein_residues(context["protein_pdb"]))
    except ValueError as exc:
        raise WorkflowError("INVALID_INTERACTIONS", str(exc), 422) from exc
    reference_id = extras.get("reference_dataset_id")
    if reference_id:
        reference = get_owned_dataset(db, uuid.UUID(str(reference_id)), session.owner_user_id)
        if not pick_dataset_file(get_dataset_files(db, reference.id), ["attachment"], {".sdf", ".smi", ".txt"}):
            raise WorkflowError("INVALID_REFERENCE", "Reference dataset requires SDF or SMILES text", 422)
    if plan.seed_source:
        try:
            seed_dataset_id = uuid.UUID(str(plan.seed_source["dataset_id"]))
            seed_file_id = uuid.UUID(str(plan.seed_source["file_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkflowError("INVALID_INPUT", "Optimization seed source is invalid", 422) from exc
        seed_dataset = get_owned_dataset(db, seed_dataset_id, session.owner_user_id)
        seed_file = db.scalar(select(DatasetFile).where(
            DatasetFile.id == seed_file_id, DatasetFile.dataset_id == seed_dataset.id))
        if seed_file is None or Path(seed_file.original_filename).suffix.lower() != ".sdf":
            raise WorkflowError("INVALID_INPUT", "Optimization seed requires one owned SDF file", 422)
        if plan.seed_source.get("sha256") and plan.seed_source["sha256"] != seed_file.sha256:
            raise WorkflowError("INPUT_CHANGED", "Optimization seed artifact changed", 409)
    seed_source = session.assets.get("optimization_seed") or plan.seed_source
    payload = {"workflow_id": str(workflow.id), "plan_version": workflow.plan_version, "plan_hash": workflow.plan_hash,
        "input_revision": session.input_revision, "plan": workflow.plan_json,
        "effective_generation": effective_generation(plan, seed_source),
        "selection": (selection or SelectionSpec(**plan.selection.model_dump())).model_dump(mode="json"),
        "key_interactions": interactions,
        "reference_dataset_id": reference_id, "binding_version": 1,
        "runtime_sources": runtime_sources(),
    }
    if seed_source:
        payload["seed_source"] = deepcopy(seed_source)
    if plan.generator == "delete" and plan.generation.edit.edit_spec_id:
        from backend.models import DeleteEditSpec
        spec = db.get(DeleteEditSpec, plan.generation.edit.edit_spec_id)
        if spec is None or spec.owner_user_id != session.owner_user_id:
            raise WorkflowError("RESOURCE_NOT_FOUND", "DELETE edit specification not found", 404)
        if digest(spec.specification) != spec.spec_hash or file_sha256(delete_reference_path(context)) != spec.reference_sha256:
            raise WorkflowError("INPUT_CHANGED", "DELETE reference ligand changed; reopen the editor", 409)
        if spec.specification["edit"]["mode"] != plan.generation.edit.mode:
            raise WorkflowError("INVALID_INPUT", "DELETE edit mode mismatch", 422)
        payload["effective_generation"]["edit"] = spec.specification["edit"]
        payload["delete_edit_spec"] = {"id": str(spec.id), "hash": spec.spec_hash, "reference_sha256": spec.reference_sha256}
    for old in db.scalars(select(ActionProposal).where(
            ActionProposal.workflow_id == workflow.id,
            ActionProposal.status.in_(["pending", "approved"]))).all():
        if old.status == "pending" or (old.kind == "postprocessing" and not (old.execution or {}).get("job_id")):
            old.status = "stale"
    proposal = create_proposal(db, session, turn, "workflow", payload, workflow=workflow)
    workflow.action_proposal_id = proposal.id
    session.active_workflow_id = workflow.id
    session.phase = "awaiting_workflow_approval"
    return proposal


def prepare_postprocessing(db, session, turn, changes):
    from backend.agent.research_safety import require_task
    from tarpass.filters import validate_filters

    require_task(db, session.research_task_id, session.owner_user_id)
    if not session.active_workflow_id:
        raise WorkflowError("WORKFLOW_REQUIRED", "Create a generation plan before configuring postprocessing", 409)
    run = owned_workflow(db, session.active_workflow_id, session.owner_user_id, lock=True)
    steps = {step.step_key: step for step in workflow_steps(db, run.id)}
    post = steps.get("postprocessing")
    if post is None:
        raise WorkflowError("WORKFLOW_INVALID", "Workflow postprocessing step is missing", 409)
    if (post.job_id and db.get(Job, post.job_id).status not in {'failed', 'canceled'}) or post.status in {"submitted", "running", "succeeded"}:
        raise WorkflowError("POSTPROCESSING_ALREADY_STARTED", "Postprocessing has already started; create a new workflow to change it", 409)
    choice = changes.get("choice")
    if choice not in {"run", "skip"}:
        raise WorkflowError("POSTPROCESSING_CHOICE_REQUIRED", "Choose whether to run postprocessing", 422)
    evidence = str(changes.get("evidence") or changes.get("command_evidence") or choice)
    record_postprocessing_choice(db, session, turn, choice, evidence)
    if choice == "skip":
        task = db.get(ResearchTask, session.research_task_id)
        if task.task_plan and task.task_plan['definition'].get('stage') == 'postprocessing':
            from backend.services.task_plans import store, internal_turn
            value = deepcopy(task.task_plan)
            value['state'] = 'completed'
            value['run']['stop_reason'] = 'user_skipped'
            store(task, value)
            session.phase = 'results_ready'
            internal_turn(db, session, task, f"skip-post:{value['version']}", session_text(db, session, '已跳过后处理，生成结果已保留。', 'Postprocessing was skipped. Generation results have been saved.'))
        post.status = "skipped"
        post.updated_at = utcnow()
        if run.status == "succeeded":
            run.refinement_state = "closed"
            run.updated_at = post.updated_at
            session.phase = "results_ready"
        return {"choice": "skip", "workflow_id": str(run.id), "postprocessing": {"status": "skipped"},
                "message": turn_text(turn, "已记录本研究任务不运行后处理。", "The choice to skip postprocessing for this task has been saved.")}

    workflow_proposal_row = db.get(ActionProposal, run.action_proposal_id) if run.action_proposal_id else None
    bound_payload = workflow_proposal_row.payload if workflow_proposal_row and workflow_proposal_row.kind == "workflow" else {}
    plan = WorkflowPlan.model_validate(run.plan_json)
    supplied = changes.get("postprocessing")
    if supplied is None:
        supplied = {key: changes[key] for key in ("prefilters",) if key in changes}
    if not isinstance(supplied, dict):
        raise WorkflowError("INVALID_INPUT", "Postprocessing parameters must be an object", 422)
    unsupported = set(supplied) - {"enabled", "prefilters", "key_interactions", "reference_dataset_id", "selection"}
    if unsupported:
        raise WorkflowError("INVALID_INPUT", "Unsupported postprocessing parameter", 422)
    try:
        task = db.get(ResearchTask, session.research_task_id)
        saved = ((task.workflow_preferences if task else {}) or {}).get('postprocessing', {})
        prefilters = supplied.get("prefilters", saved.get('prefilters', [item.model_dump(mode="json") for item in plan.postprocessing.prefilters]))
        validate_filters(prefilters, pre=True)
    except (TypeError, ValueError) as exc:
        raise WorkflowError("INVALID_INPUT", str(exc), 422) from exc
    key_interactions = supplied.get("key_interactions", bound_payload.get("key_interactions", []))
    reference_dataset_id = supplied.get("reference_dataset_id", bound_payload.get("reference_dataset_id"))
    selection = supplied.get("selection", bound_payload.get("selection", plan.selection.model_dump(mode="json")))
    context = validate_protein_context_for_generation(db, session.owner_user_id, uuid.UUID(plan.protein_context_id))
    from tarpass.contracts import protein_residues, validate_interactions
    try:
        key_interactions = validate_interactions(key_interactions, protein_residues(context["protein_pdb"]))
    except (TypeError, ValueError) as exc:
        raise WorkflowError("INVALID_INTERACTIONS", str(exc), 422) from exc
    if reference_dataset_id:
        from backend.services.jobs import pick_dataset_file
        reference = get_owned_dataset(db, uuid.UUID(str(reference_dataset_id)), session.owner_user_id)
        if not pick_dataset_file(get_dataset_files(db, reference.id), ["attachment"], {".sdf", ".smi", ".txt"}):
            raise WorkflowError("INVALID_REFERENCE", "Reference dataset requires SDF or SMILES text", 422)
    post_config = {
        "enabled": True,
        "prefilters": prefilters,
        "key_interactions": deepcopy(key_interactions),
        "reference_dataset_id": str(reference_dataset_id) if reference_dataset_id else None,
        "protein_context_id": str(plan.protein_context_id),
    }
    postprocessing_hash = digest({"config": post_config, "protocol_version": POSTPROCESSING_APPROVAL_PROTOCOL_VERSION})
    payload = {
        "source_workflow_id": str(run.id),
        "workflow_id": str(run.id),
        "generation_plan_version": run.plan_version,
        "generation_plan_hash": run.plan_hash,
        "generation_input_revision": session.input_revision,
        "postprocessing": post_config,
        "selection": deepcopy(selection),
        "postprocessing_hash": postprocessing_hash,
        "runtime_config_version": POSTPROCESSING_APPROVAL_PROTOCOL_VERSION,
        "runtime_sources": runtime_sources(),
        **({"reference_dataset_id": str(reference_dataset_id)} if reference_dataset_id else {}),
    }
    for old in db.scalars(select(ActionProposal).where(
            ActionProposal.session_id == session.id,
            ActionProposal.workflow_id == run.id,
            ActionProposal.kind == "postprocessing",
            ActionProposal.status.in_(["pending", "approved"]))).all():
        if old.status == "approved" and (old.execution or {}).get("job_id"):
            continue
        old.status = "stale"
    proposal = create_proposal(db, session, turn, "postprocessing", payload, workflow=run)
    post.status = "authorized" if proposal.status == "approved" else "awaiting_approval"
    post.updated_at = utcnow()
    if steps["generation"].status == "succeeded":
        session.phase = "awaiting_postprocessing_approval" if proposal.status == "pending" else "executing"
    from backend.services.task_plans import capture_postprocessing
    task_draft = capture_postprocessing(db, session, turn, run, proposal)
    return {
        "choice": "run", "workflow_id": str(run.id), "proposal": proposal_out(proposal),
        "proposal_id": str(proposal.id), "message": (turn_text(turn, "完整任务方案已生成，批准后将复用已有结果运行后处理并分析。", "The task plan has been created. Approval will reuse existing results for postprocessing and analysis.")
            if task_draft else turn_text(turn, "后处理已按批准方案绑定。", "Postprocessing has been bound to the approved plan.")),
    }


def validate_binding(db, proposal, session):
    expected = digest({"kind": proposal.kind, "payload": proposal.payload, "input": proposal.input_fingerprint})
    if expected != proposal.action_hash or fingerprint(db, session, proposal.payload) != proposal.input_fingerprint:
        raise WorkflowError("INPUT_CHANGED", "Inputs or configuration changed; create and approve a new proposal", 409)



def save_candidate_set(db, session, proposal, job_id):
    from backend.workflows.results import save_candidate_set as save
    return save(db, session.owner_user_id, proposal, job_id)


def approve_proposal(db, session, proposal_id, action_hash):
    from backend.agent.research_safety import require_task
    require_task(db, session.research_task_id, session.owner_user_id)
    proposal = db.scalar(select(ActionProposal).where(ActionProposal.id == proposal_id, ActionProposal.session_id == session.id).with_for_update())
    if proposal is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Proposal not found", 404)
    if action_hash != proposal.action_hash:
        raise WorkflowError("ACTION_CHANGED", "Approve the exact proposal hash", 409)
    if proposal.status == "approved":
        return proposal
    if proposal.status != "pending" or session.phase in {"cancel_requested", "canceled"}:
        raise WorkflowError("ACTION_STALE", "Proposal is no longer pending", 409)
    origin = db.get(AgentTurn, proposal.turn_id)
    if origin.research_task_id != session.research_task_id:
        raise WorkflowError("ACTION_STALE", "The proposal belongs to a different research task", 409)
    if proposal.kind != 'task_plan':
        from backend.services.task_plans import require_editable
        require_editable(db, session, origin)
    require_task(db, origin.research_task_id, session.owner_user_id)
    validate_binding(db, proposal, session)
    proposal.status = "approved"
    if proposal.kind == "task_plan":
        from backend.services.task_plans import approve
        approve(db, session, proposal)
    elif proposal.kind == "prepare":
        if proposal.payload.get('preparation_protocol_version') != 2:
            raise WorkflowError("INVALID_INPUT", "Preparation protocol v2 is required", 422)
        from backend.services.prepared_receptors import create_prepared_receptor
        from backend.structure_contracts import PreparedReceptorCreate
        receptor = create_prepared_receptor(PreparedReceptorCreate(**proposal.payload['prepared_spec'], name=proposal.payload['name']), db, session.owner_user_id)
        job = create_protein_preparation_job(schemas.JobCreateRequest(job_type='protein_preparation', prepared_receptor_id=receptor['id']), db, session.owner_user_id)
        session.assets = {**{k: v for k, v in session.assets.items() if k != 'protein_context_id'}, 'prepared_receptor_id': receptor['id']}
        proposal.execution = {'job_id': str(job.id), 'prepared_receptor_id': receptor['id']}
        from backend.workflows.commands import design
        design(db, session).assets = dict(session.assets)
        session.preparation_job_id, session.phase = job.id, 'preparing'
    elif proposal.kind == "workflow":
        run = owned_workflow(db, proposal.workflow_id, session.owner_user_id, lock=True)
        binding = {'payload':deepcopy(proposal.payload), 'inputs':deepcopy(proposal.input_fingerprint),
            'plan':deepcopy(proposal.payload['plan']), 'effective_generation':deepcopy(proposal.payload['effective_generation']),
            'proposal_id':str(proposal.id), 'action_hash':proposal.action_hash}
        run.execution_binding = binding
        db.flush()
        run = approve_workflow(db, workflow_id=proposal.workflow_id, owner_user_id=session.owner_user_id,
            plan_version=proposal.payload["plan_version"], plan_hash=proposal.payload["plan_hash"])
        session.phase = "executing"
        proposal.execution = {"workflow_id": str(run.id)}
    elif proposal.kind == "selection":
        save_candidate_set(db, session, proposal, uuid.UUID(proposal.payload["postprocessing_job_id"]))
    elif proposal.kind == "postprocessing":
        from backend.services.workflows import dispatch_postprocessing_proposal
        run = owned_workflow(db, proposal.workflow_id, session.owner_user_id, lock=True)
        steps = {step.step_key: step for step in workflow_steps(db, run.id)}
        can_resume_skipped = (
            run.status == "succeeded"
            and steps.get("generation") is not None
            and steps["generation"].status == "succeeded"
            and steps.get("postprocessing") is not None
            and steps["postprocessing"].status in {"skipped", "awaiting_approval", "authorized"}
        )
        if run.status in {"failed", "canceled", "superseded"} or (run.status == "succeeded" and not can_resume_skipped):
            raise WorkflowError("WORKFLOW_ALREADY_STARTED", "The generation workflow cannot accept this postprocessing approval", 409)
        post = steps.get("postprocessing")
        generation = steps.get("generation")
        if post is None or generation is None or post.job_id or post.status == "skipped":
            raise WorkflowError("POSTPROCESSING_ALREADY_STARTED", "Postprocessing is no longer awaiting approval", 409)
        generation_job = get_owned_job(db, session.owner_user_id, generation.job_id) if generation.job_id else None
        if generation_job and generation_job.status == "succeeded":
            job = dispatch_postprocessing_proposal(db, run, proposal, generation_job)
            post.job_id = job.id
            post.status = "submitted"
            post.updated_at = utcnow()
            session.phase = "executing"
            if run.status == "succeeded":
                run.status = "running"
                run.refinement_state = "running"
                run.updated_at = post.updated_at
            proposal.execution = {**(proposal.execution or {}), "authorized": True, "job_id": str(job.id)}
        else:
            post.status = "authorized"
            post.updated_at = utcnow()
            proposal.execution = {**(proposal.execution or {}), "authorized": True, "workflow_id": str(run.id)}
    elif proposal.kind == "retry_postprocessing":
        from backend.services.workflows import ACTIVE_JOB_STATUSES, _agent_generation_binding_is_current
        for old in db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id,
                ActionProposal.workflow_id == proposal.workflow_id, ActionProposal.kind == "retry_postprocessing",
                ActionProposal.status == "approved", ActionProposal.id != proposal.id)):
            if old.execution.get("job_id") and get_owned_job(db, session.owner_user_id, uuid.UUID(old.execution["job_id"])).status in ACTIVE_JOB_STATUSES:
                raise WorkflowError("RETRY_NOT_AVAILABLE", "Postprocessing retry is already running", 409)
        run = owned_workflow(db, proposal.workflow_id, session.owner_user_id, lock=True)
        steps = {step.step_key: step for step in workflow_steps(db, run.id)}
        generation = steps.get("generation")
        original = db.get(ActionProposal, run.action_proposal_id) if run.action_proposal_id else None
        try:
            from backend.workflows.bindings import workflow_binding
            workflow_binding(db, run)
            binding_current = _agent_generation_binding_is_current(db, run)
        except WorkflowError:
            binding_current = False
        if (generation is None or generation.status != "succeeded" or generation.job_id is None
                or original is None or original.kind != "workflow" or original.status != "approved"
                or not binding_current):
            raise WorkflowError("INPUT_CHANGED", "The original generation approval is no longer bound to the current session", 409)
        source = get_owned_job(db, session.owner_user_id, uuid.UUID(proposal.payload["source_job_id"]))
        if source.id != generation.job_id or source.owner_user_id != run.owner_user_id or source.status != "succeeded":
            raise WorkflowError("SOURCE_NOT_READY", "Generation has not succeeded", 409)
        retry_config = proposal.payload.get("postprocessing") or {}
        if retry_config.get("source_job_id") != str(source.id):
            raise WorkflowError("INPUT_CHANGED", "Retry source no longer matches the generation step", 409)
        job = create_postprocessing_job(db, owner_user_id=session.owner_user_id, params={"postprocessing": proposal.payload["postprocessing"]})
        proposal.execution = {"job_id": str(job.id)}
        session.phase = "executing"
    db.flush()
    return proposal


def _reconcile_session(db, session):
    now = utcnow()
    if session.phase == "cancel_requested":
        from backend.services.workflows import ACTIVE_JOB_STATUSES
        job_ids = {session.preparation_job_id} if session.preparation_job_id else set()
        for proposal in db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id, ActionProposal.status == "approved",
                ActionProposal.turn_id.in_(select(AgentTurn.id).where(AgentTurn.research_task_id == session.research_task_id)))):
            if proposal.execution.get("job_id"):
                job_ids.add(uuid.UUID(proposal.execution["job_id"]))
        if session.active_workflow_id:
            run = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
            if run.status in {"approved", "running", "cancel_requested"}:
                return
            job_ids.update(step.job_id for step in workflow_steps(db, run.id) if step.job_id)
        if any(get_owned_job(db, session.owner_user_id, job_id).status in ACTIVE_JOB_STATUSES for job_id in job_ids):
            return
        session.phase = "canceled"
        from backend.workflows.commands import emit
        emit(db, session.id, session.input_revision, "cancellation_confirmed", f"canceled:{session.id}:{session.input_revision}")
    if session.phase in {"canceled", "archived"}:
        return
    if session.phase == 'preparing' and session.assets.get('context_validation_job_id'):
        context = get_owned_dataset(db, uuid.UUID(session.assets['protein_context_id']), session.owner_user_id)
        states = (context.meta.get('compatibility') or {}).get('models', {})
        if any(row['status'] == 'pending' for row in states.values()):
            return
        usable = any(row['status'] in {'full', 'limited'} for row in states.values())
        session.phase = 'ready_for_planning' if usable else 'failed'
        session.pending_requirements = [] if usable else ['site']
        session.last_error = None if usable else 'CONTEXT_INPUTS_INCOMPATIBLE'
        return
    if session.phase == "preparing" and session.preparation_job_id:
        job = get_owned_job(db, session.owner_user_id, session.preparation_job_id)
        if job.status == "succeeded" and (job.params or {}).get('preparation_protocol_version') == 2:
            from backend.services.prepared_receptors import get_prepared_receptor
            prepared = get_prepared_receptor(uuid.UUID(session.assets['prepared_receptor_id']), db, session.owner_user_id)
            if prepared['status'] != 'ready':
                session.phase, session.last_error = 'failed', 'PREPARATION_INVALID'
            else:
                session.phase, session.pending_requirements = 'awaiting_site', ['site']
            return
        if job.status in {"failed", "canceled"}:
            session.phase = "failed"
            session.last_error = "PREPARATION_" + job.status.upper()
    if session.phase == 'executing' and not session.active_workflow_id:
        proposal = db.scalar(select(ActionProposal).where(ActionProposal.session_id == session.id,
            ActionProposal.status == 'approved', ActionProposal.execution['job_id'].as_string().is_not(None),
            ActionProposal.turn_id.in_(select(AgentTurn.id).where(AgentTurn.research_task_id == session.research_task_id)))
            .order_by(ActionProposal.created_at.desc()).limit(1))
        if proposal:
            job = get_owned_job(db, session.owner_user_id, uuid.UUID(proposal.execution['job_id']))
            if job.status in {'succeeded', 'failed', 'canceled'}:
                session.phase = 'results_ready' if job.status == 'succeeded' else job.status
                session.last_error = None if job.status == 'succeeded' else 'POSTPROCESSING_' + job.status.upper()
    if session.phase != "executing" or not session.active_workflow_id:
        return
    proposals = db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id, ActionProposal.status == "approved").order_by(ActionProposal.created_at.desc())).all()
    retry = next((p for p in proposals if p.kind == "retry_postprocessing" and p.workflow_id == session.active_workflow_id), None)
    if retry and retry.execution.get("job_id"):
        job = get_owned_job(db, session.owner_user_id, uuid.UUID(retry.execution["job_id"]))
        if job.status == "succeeded":
            session.phase = "results_ready"
        elif job.status in {"failed", "canceled"}:
            session.phase = "failed"
            session.last_error = "POSTPROCESSING_" + job.status.upper()
        return
    run = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
    run_steps = {step.step_key: step for step in workflow_steps(db, run.id)}
    if (run.status == "running"
            and run_steps.get("generation")
            and run_steps["generation"].status == "succeeded"
            and run_steps.get("postprocessing")
            and run_steps["postprocessing"].status == "awaiting_approval"):
        session.phase = "awaiting_postprocessing_approval"
        return
    if run.status == "succeeded":
        session.phase = "results_ready"
    elif run.status in {"failed", "canceled"}:
        session.phase = "failed" if run.status == "failed" else "canceled"
        session.last_error = "WORKFLOW_" + run.status.upper()


def proposal_out(row):
    return {"id": str(row.id), "kind": row.kind, "payload": row.payload, "action_hash": row.action_hash,
            "input_revision": (row.input_fingerprint or {}).get("revision"),
            "status": row.status, "execution": row.execution, "turn_id": str(row.turn_id),
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def turn_out(row):
    return {"id": str(row.id), "research_task_id": str(row.research_task_id) if row.research_task_id else None, "client_request_id": str(row.client_request_id), "intent": row.request["intent"],
        "message": row.request["message"], "request": row.request, "source": row.audit.get("source", "chat"), "status": row.status, "attempt": row.attempt, "response": row.response, "trigger": row.audit.get("trigger"),
        "resumed_by": row.audit.get("resumed_by") or row.audit.get('reading_resumed_by'), "recovery_of": row.audit.get("recovery_of"), "recovery_count": row.audit.get("recovery_count", 0),
        "can_resume": not row.audit.get('pending_review') and row.audit.get("trigger") != "task_plan" and row.status in {"failed", "interrupted"} and row.audit.get("recovery_count", 0) < 2 and not (row.audit.get("resumed_by") or row.audit.get('reading_resumed_by')),
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def _workflow_round(db, run, candidate_sets):
    status = workflow_status_dict(db, run)
    generation = status["generation"]
    postprocessing = status["postprocessing"]
    related = [item for item in candidate_sets if item["workflow_id"] == str(run.id)]
    return {
        "workflow_id": str(run.id),
        "engine": (run.plan_json.get("generation") or {}).get("engine") or run.plan_json.get("generator"),
        "status": run.status,
        "plan_version": run.plan_version,
        "generation": generation,
        "postprocessing": postprocessing,
        "result_summary": related[0]["summary"] if related else None,
        "candidate_set_ids": [item["id"] for item in related],
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def _session_presentation(db, session, candidate_sets):
    workflow_ids = set(db.scalars(select(ActionProposal.workflow_id).where(
        ActionProposal.session_id == session.id, ActionProposal.workflow_id.is_not(None))).all())
    if session.active_workflow_id:
        workflow_ids.add(session.active_workflow_id)
    runs = list(db.scalars(select(WorkflowRun).where(
        WorkflowRun.owner_user_id == session.owner_user_id,
        WorkflowRun.id.in_(workflow_ids) if workflow_ids else WorkflowRun.id == uuid.UUID(int=0),
    ).order_by(WorkflowRun.created_at.asc(), WorkflowRun.id.asc())).all())
    rounds = [_workflow_round(db, run, candidate_sets) for run in runs]
    generation_job_ids = {round["generation"].get("job_id") for round in rounds if round["generation"].get("job_id")}
    bound_postprocessing_ids = {round["postprocessing"].get("job_id") for round in rounds if round["postprocessing"].get("job_id")}
    related_postprocessing_jobs = []
    if generation_job_ids:
        for job in db.scalars(select(Job).where(
                Job.owner_user_id == session.owner_user_id,
                Job.job_type == "molecule_postprocessing",
                Job.params["postprocessing"]["source_job_id"].astext.in_(generation_job_ids),
            ).order_by(Job.created_at.desc()).limit(100)).all():
            source_job_id = str(((job.params or {}).get("postprocessing") or {}).get("source_job_id") or "")
            if source_job_id in generation_job_ids and str(job.id) not in bound_postprocessing_ids:
                related_postprocessing_jobs.append({"id": str(job.id), "source_job_id": source_job_id, "status": job.status})
    active_round_id = str(session.active_workflow_id) if session.active_workflow_id else None
    phase = session.phase
    current_key = {
        "awaiting_upload": "input", "awaiting_selection": "input", "selecting_input": "input",
        "preparing": "preparation", "awaiting_preparation_approval": "preparation",
        "awaiting_site": "site", "saving_site": "site", "ready_for_planning": "generation",
        "planning": "generation", "awaiting_approval": "generation", "awaiting_workflow_approval": "generation",
        "executing": "generation", "results_ready": "selection", "failed": "selection", "canceled": "selection",
        "awaiting_postprocessing_approval": "postprocessing",
    }.get(phase, "input")
    assets = session.assets or {}
    input_ready = bool(assets.get("protein_dataset_id") or assets.get("protein_context_id") or assets.get("prepared_receptor_id"))
    prepared_ready = bool(assets.get("prepared_receptor_id"))
    context_ready = bool(assets.get("protein_context_id"))
    if not prepared_ready and assets.get("protein_context_id"):
        try:
            context = get_owned_dataset(db, uuid.UUID(assets["protein_context_id"]), session.owner_user_id)
        except ResourceNotFound:
            context_ready = False
            input_ready = bool(assets.get('protein_dataset_id'))
        else:
            prepared_ready = bool((context.meta or {}).get("prepared_receptor_id"))
    round_status = None
    active_round = next((item for item in rounds if item["workflow_id"] == active_round_id), None)
    if active_round:
        round_status = active_round
        if (active_round["generation"]["status"] == "succeeded"
                and active_round["postprocessing"]["status"] not in {"succeeded", "skipped"}):
            current_key = "postprocessing"
    prep_status = None
    prep_job_id = None
    if session.preparation_job_id:
        job = get_owned_job(db, session.owner_user_id, session.preparation_job_id)
        prep_status, prep_job_id = job.status, str(job.id)
    elif prepared_ready:
        prep_status = "succeeded"
    elif input_ready:
        prep_status = "pending"
    else:
        prep_status = "blocked"
    generation_stage = active_round["generation"]["status"] if active_round else ("succeeded" if context_ready and phase == "results_ready" else "pending")
    postprocessing_stage = active_round["postprocessing"]["status"] if active_round else "pending"
    selection_stage = "succeeded" if candidate_sets else ("ready" if postprocessing_stage == "succeeded" else "pending")
    stages = [
        {"key": "input", "status": "succeeded" if input_ready else "blocked", "current": current_key == "input",
         "reason": None if input_ready else "protein_input_required"},
        {"key": "preparation", "status": prep_status, "current": current_key == "preparation", "job_id": prep_job_id},
        {"key": "site", "status": "succeeded" if context_ready else ("blocked" if prepared_ready else "pending"),
         "current": current_key == "site", "reason": None if context_ready else ("binding_site_required" if prepared_ready else None)},
        {"key": "generation", "status": generation_stage, "current": current_key == "generation",
         "job_id": active_round["generation"].get("job_id") if active_round else None},
        {"key": "postprocessing", "status": postprocessing_stage, "current": current_key == "postprocessing",
         "job_id": active_round["postprocessing"].get("job_id") if active_round else None},
        {"key": "selection", "status": selection_stage, "current": current_key == "selection"},
    ]
    blocker = None
    if session.pending_requirements:
        blocker = {"kind": "input", "requirements": list(session.pending_requirements), "reason": "input_required"}
    elif session.last_error:
        blocker = {"kind": "error", "reason": session.last_error}
    elif round_status and round_status["status"] == "awaiting_approval":
        blocker = {"kind": "approval", "reason": "workflow_approval_required", "workflow_id": active_round_id}
    elif round_status and round_status["generation"]["status"] == "succeeded" and round_status["postprocessing"]["status"] == "awaiting_approval":
        post_proposal = db.scalar(select(ActionProposal).where(
            ActionProposal.session_id == session.id,
            ActionProposal.workflow_id == session.active_workflow_id,
            ActionProposal.kind == "postprocessing",
            ActionProposal.status == "pending",
        ).order_by(ActionProposal.created_at.desc()))
        blocker = {"kind": "approval", "reason": "postprocessing_approval_required", "workflow_id": active_round_id,
                   "proposal_id": str(post_proposal.id) if post_proposal else None}
    drafts = [{"id": str(row.id), "kind": row.kind, "status": row.status,
               "expected_version": row.expected_revision,
               "has_draft": bool((row.state or {}).get("draft")),
               "created_at": row.created_at.isoformat() if row.created_at else None}
              for row in db.scalars(select(EditSession).where(
                  EditSession.session_id == session.id,
                  EditSession.owner_user_id == session.owner_user_id,
              ).order_by(EditSession.created_at.desc(), EditSession.id.desc()).limit(12)).all()]
    research_plan = None
    if active_round:
        run = next((row for row in runs if str(row.id) == active_round_id), None)
        if run is not None:
            generation_proposal = db.scalar(select(ActionProposal).where(
                ActionProposal.session_id == session.id, ActionProposal.workflow_id == run.id,
                ActionProposal.kind == "workflow",
            ).order_by(ActionProposal.created_at.desc()))
            post_proposal = db.scalar(select(ActionProposal).where(
                ActionProposal.session_id == session.id, ActionProposal.workflow_id == run.id,
                ActionProposal.kind == "postprocessing",
            ).order_by(ActionProposal.created_at.desc()))
            compact_proposal = lambda row: ({
                "id": str(row.id), "status": row.status, "action_hash": row.action_hash,
                "execution": row.execution, "created_at": row.created_at.isoformat() if row.created_at else None,
            } if row else None)
            research_plan = {
                "workflow_id": str(run.id), "plan_version": run.plan_version, "plan_hash": run.plan_hash,
                "plan": deepcopy(run.plan_json), "status": run.status,
                "generation_approval": compact_proposal(generation_proposal),
                "postprocessing_approval": compact_proposal(post_proposal),
                "postprocessing_status": active_round["postprocessing"],
            }
    return {"rounds": rounds, "stages": stages, "active_round_id": active_round_id,
            "blocker": blocker, "drafts": drafts, "related_postprocessing_jobs": related_postprocessing_jobs,
            "research_plan": research_plan}


def snapshot(db, session, *, model_view=False):
    limit = 24 if model_view else 50
    result = {"id": str(session.id), "research_task_id": str(session.research_task_id) if session.research_task_id else None, "goal": session.goal, "phase": session.phase, "input_revision": session.input_revision,
        "assets": session.assets, "confirmed_fields": session.confirmed_fields, "pending_requirements": session.pending_requirements,
        "pending_clarification_fields": pending_clarification_fields(db, session),
        "last_error": session.last_error, "turns": [turn_out(r) for r in db.scalars(select(AgentTurn).where(AgentTurn.session_id == session.id).order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc()).limit(limit))][::-1],
        "proposals": [proposal_out(p) for p in db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id).order_by(ActionProposal.created_at.desc()).limit(12 if model_view else 50))][::-1],
        "candidate_sets": [{"id": str(s.id), "summary": s.summary, "proposal_id": str(s.proposal_id),
            "selection": s.selection_spec,
            "postprocessing_job_id": str(s.postprocessing_job_id),
            "workflow_id": str(proposal.workflow_id) if (proposal := db.get(ActionProposal, s.proposal_id)).workflow_id else None,
            "created_at": s.created_at.isoformat()} for s in db.scalars(select(CandidateSet).where(CandidateSet.session_id == session.id).order_by(CandidateSet.created_at.desc()).limit(2 if model_view else 50))][::-1]}
    task = db.get(ResearchTask, session.research_task_id) if session.research_task_id else None
    result['research_task_state'] = task.state if task else None
    legacy_task = task and str(session.id) in task.assessment.get('legacy_session_ids', [])
    if legacy_task:
        for turn in result['turns']:
            if turn['research_task_id'] is None and datetime.fromisoformat(turn['created_at']) <= task.created_at:
                turn['research_task_id'] = str(task.id)
    if task and task.state == 'blocked':
        result['pending_requirements'] = []
        result['pending_clarification_fields'] = []
        for turn in result['turns']:
            if turn['research_task_id'] == result['research_task_id']:
                turn['can_resume'] = False
    result['turns'] = [turn for turn in result['turns'] if turn.get('trigger') != 'task_plan'
        or turn.get('response', {}).get('message') or turn.get('status') in {'queued', 'running', 'failed'}]
    result["task_plan"] = deepcopy(task.task_plan) if task else None
    if result['task_plan'] and not model_view:
        result['task_plan']['history'] = [{'version': proposal.payload.get('task_plan_version'), 'status': proposal.status,
            'created_at': proposal.created_at.isoformat()} for proposal in db.scalars(select(ActionProposal).join(AgentTurn, AgentTurn.id == ActionProposal.turn_id).where(
                ActionProposal.session_id == session.id, AgentTurn.research_task_id == session.research_task_id,
                ActionProposal.kind == 'task_plan').order_by(ActionProposal.created_at.desc()).limit(30))]
    result["workflow_preferences"] = deepcopy(task.workflow_preferences or {}) if task else {}
    from backend.agent.user_settings import list_work_preferences
    # The researcher's saved standing preferences apply to every session, so each snapshot carries them.
    saved_preferences = list_work_preferences(db, session.owner_user_id)
    if saved_preferences:
        result["workflow_preferences"]["user_preferences"] = saved_preferences
    result["presentation"] = _session_presentation(db, session, result["candidate_sets"])
    result["drafts"] = result["presentation"]["drafts"]
    pose_draft = (session.assets or {}).get("optimization_pose_draft")
    if pose_draft and pose_draft.get("next_step"):
        result["pose_preparation_draft"] = {**pose_draft["next_step"], "seed": pose_draft.get("seed"),
                                             "source": pose_draft.get("source")}
    pose_job = (session.assets or {}).get("optimization_pose_job")
    if pose_job and pose_job.get("job_id"):
        job = get_owned_job(db, session.owner_user_id, uuid.UUID(pose_job["job_id"]))
        result["pose_preparation"] = {**pose_job, "status": job.status}
    if (not any(session.assets.get(key) for key in ('protein_dataset_id', 'protein_context_id', 'prepared_receptor_id'))
            and any(field['id'] == 'protein_dataset_id' for field in result['pending_clarification_fields'])):
        from backend.agent.inputs import search_inputs
        query = next((turn['response']['input_query'] for turn in reversed(result['turns'])
            if turn['status'] == 'needs_input' and turn['research_task_id'] == result['research_task_id'] and turn['response'].get('input_query')), session.goal)
        result['input_selection'] = {'candidates': search_inputs(db, session.owner_user_id, query, protein_only=True)}
    if model_view:
        allowed_turns = set(db.scalars(select(AgentTurn.id).where(AgentTurn.session_id == session.id, AgentTurn.research_task_id == session.research_task_id)))
        result['turns'] = [t for t in result['turns'] if uuid.UUID(t['id']) in allowed_turns]
        result['proposals'] = [p for p in result['proposals'] if uuid.UUID(p['turn_id']) in allowed_turns]
        allowed_proposals = {p['id'] for p in result['proposals']}
        result['candidate_sets'] = [c for c in result['candidate_sets'] if c['proposal_id'] in allowed_proposals]
        from backend.workflows.commands import design
        draft = design(db, session)
        result["scientific_state"] = {"draft_id": str(draft.id), "revision": draft.revision,
            "assets": draft.assets, "values": draft.values, "provenance": draft.provenance}
        if session.active_workflow_id:
            run = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
            result["scientific_state"]["workflow"] = {"id": str(run.id), "status": run.status,
                "plan": run.plan_json, "version": run.plan_version, "hash": run.plan_hash,
                "execution_binding": run.execution_binding}
        result["scientific_state"]["active_runs"] = [{"id": str(run.id), "status": run.status,
            "plan": run.plan_json, "execution_binding": run.execution_binding}
            for run in db.scalars(select(WorkflowRun).join(ActionProposal, ActionProposal.workflow_id == WorkflowRun.id)
                .where(ActionProposal.session_id == session.id, ActionProposal.status == "approved",
                    WorkflowRun.owner_user_id == session.owner_user_id, WorkflowRun.research_task_id == session.research_task_id, WorkflowRun.status.in_(["approved", "running", "cancel_requested"]))
                .distinct().order_by(WorkflowRun.created_at.desc()).limit(3))]
        result["pending_proposals"] = [{"id": str(p.id), "kind": p.kind, "turn_id": str(p.turn_id)}
            for p in db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id,
                ActionProposal.status == "pending", ActionProposal.turn_id.in_(allowed_turns)).order_by(ActionProposal.created_at.desc()).limit(20))]
        result["task_summary"] = [{"source_turn_id": str(t.id), "user_goal": t.request["message"],
            "status": t.status, "resolved_intent": t.audit.get("resolved_intent"),
            "saved_effects": t.audit.get("committed_effects", []), "proposal_id": t.response.get("proposal_id")}
            for t in db.scalars(select(AgentTurn).where(AgentTurn.session_id == session.id, AgentTurn.research_task_id == session.research_task_id,
                (AgentTurn.audit["resolved_intent"].as_string() != "ask") | (AgentTurn.status == "needs_input") |
                AgentTurn.request["intent"].as_string().not_in(["auto", "ask"]))
                .order_by(AgentTurn.created_at.desc()).limit(12))]
    if session_values(session).get("delete_edit_spec_id"):
        from backend.models import DeleteEditSpec
        edit = db.get(DeleteEditSpec, uuid.UUID(session_values(session)["delete_edit_spec_id"]))
        if edit and edit.owner_user_id == session.owner_user_id:
            result["delete_edit"] = {"id": str(edit.id), "mode": edit.specification["edit"]["mode"]}
    for item in result["proposals"]:
        origin = db.get(AgentTurn, uuid.UUID(item["turn_id"]))
        origin_task_id = origin.research_task_id or (task.id if legacy_task and origin.created_at <= task.created_at else None)
        item["research_task_id"] = str(origin_task_id) if origin_task_id else None
        if item["execution"].get("job_id"):
            job = get_owned_job(db, session.owner_user_id, uuid.UUID(item["execution"]["job_id"]))
            item["job_status"] = job.status
        if item["execution"].get("workflow_id"):
            item["workflow"] = workflow_status_dict(db, owned_workflow(db, uuid.UUID(item["execution"]["workflow_id"]), session.owner_user_id))
    if session.assets.get("protein_context_id"):
        try:
            context = get_owned_dataset(db, uuid.UUID(session.assets["protein_context_id"]), session.owner_user_id)
        except ResourceNotFound:
            result['last_error'] = 'RESOURCE_NOT_FOUND'
        else:
            meta = context.meta or {}
            result['context_spec'] = {**deepcopy(meta), "id": str(context.id), "name": context.name, "status": context.status}
    prepared_id = session.assets.get('prepared_receptor_id') or (result.get('context_spec') or {}).get('prepared_receptor_id')
    if prepared_id:
        prepared = get_owned_dataset(db, uuid.UUID(prepared_id), session.owner_user_id)
        meta = prepared.meta or {}
        result['prepared_receptor'] = {
            "id": str(prepared.id), "name": prepared.name, "status": prepared.status,
            **{key: deepcopy(meta[key]) for key in (
                "version", "source", "preparation", "edits", "artifacts", "capabilities",
                "execution", "failure_artifacts", "warnings",
            ) if key in meta},
            "created_at": prepared.created_at.isoformat() if prepared.created_at else None,
            "updated_at": prepared.updated_at.isoformat() if prepared.updated_at else None,
        }
    if session.preparation_job_id:
        job = get_owned_job(db, session.owner_user_id, session.preparation_job_id)
        result["preparation"] = {"job_id": str(job.id), "status": job.status}
    if session.active_workflow_id:
        result["workflow"] = workflow_status_dict(db, owned_workflow(db, session.active_workflow_id, session.owner_user_id))
    if session.active_workflow_id:
        from backend.workflows.commands import design
        draft = design(db, session)
        ids = (draft.condition_ids or {}).get(str(session.active_workflow_id), [])
        run = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
        result["workflow"]["prefilter_conditions"] = [{"id": key, **rule} for key, rule in zip(ids, run.plan_json["postprocessing"]["prefilters"])]
    if session.phase in {"cancel_requested", "canceled"}:
        result["process_termination_confirmed"] = False
    return result


def execute_action(db, session, turn, request):
    if request.intent in {'bind', 'select_context', 'prepare', 'save_site', 'prepare_postprocessing', 'retry_postprocessing'}:
        from backend.services.task_plans import require_editable
        require_editable(db, session, turn)
    if request.intent == 'task_plan':
        from backend.services.task_plans import save
        return save(db, session, turn, request.task_plan.model_dump(mode='json'))
    if request.intent == "prepare_postprocessing":
        return prepare_postprocessing(db, session, turn, {"choice": "run", "evidence": request.message})
    if request.intent in {"bind", "select_context"}:
        reply = change_inputs(db, session, turn, request)
    elif request.intent == "prepare":
        try:
            reply = prepare_proposal(db, session, turn)
        except HTTPException as exc:
            if exc.status_code not in {400, 422}:
                raise
            structural = {field["requirement"] for field in pending_clarification_fields(db, session) if field["type"] == "structure"}
            remaining = [item for item in session.pending_requirements or [] if item not in structural]
            reply = {"message": str(exc.detail), "missing_requirements": remaining + ["valid_structure_selection"]}
            session.pending_requirements = reply["missing_requirements"]
    elif request.intent == 'save_site':
        from backend.services.binding_sites import create_site
        from backend.services.prepared_receptors import get_prepared_receptor
        structural = {field['requirement'] for field in pending_clarification_fields(db, session) if field['type'] == 'structure'}
        remaining = [item for item in session.pending_requirements or [] if item not in structural]
        receptor_id = session.assets.get('prepared_receptor_id')
        if not receptor_id:
            raise WorkflowError('PREPARED_RECEPTOR_REQUIRED', 'Prepare a receptor before defining a site', 422)
        prepared = get_prepared_receptor(uuid.UUID(receptor_id), db, session.owner_user_id)
        if prepared['status'] != 'ready' or not request.values.get('site'):
            raise WorkflowError('SITE_REQUIRED', 'Complete preparation and define a site first', 422)
        if request.values.get('prepared_artifact_sha256') not in {None, prepared['artifacts']['prepared_complex']['sha256']}:
            raise WorkflowError('INPUT_CHANGED', 'Prepared artifact binding changed', 409)
        context = create_site({'version': 4, 'name': request.values.get('name', 'Binding site'),
            'prepared_receptor_id': receptor_id,
            'prepared_artifact_sha256': prepared['artifacts']['prepared_complex']['sha256'],
            'site': request.values['site'], 'generation_reference': request.values.get('generation_reference'), 'input_parameters': request.values.get('input_parameters')}, db, session.owner_user_id)
        from backend.workflows.commands import update_inputs, design
        draft = design(db, session)
        update_inputs(db, draft, 'bind', {'protein_context_id': context['id']})
        session.assets, session.input_revision = dict(draft.assets), draft.revision
        session.confirmed_fields = {}
        task = db.get(ResearchTask, session.research_task_id)
        if task and 'site_request' in (task.workflow_preferences or {}):
            task.workflow_preferences = {key: value for key, value in task.workflow_preferences.items() if key != 'site_request'}
        session.active_workflow_id, session.phase, session.pending_requirements = None, 'ready_for_planning', remaining
        if context.get('compatibility'):
            session.assets = {**session.assets, 'context_validation_job_id':context['compatibility']['job_id']}
            session.phase = 'preparing'
        for proposal in db.scalars(select(ActionProposal).where(
                ActionProposal.session_id == session.id,
                ActionProposal.status.in_(['pending', 'approved']))).all():
            if proposal.status == 'pending' or (
                    proposal.kind == 'postprocessing' and not (proposal.execution or {}).get('job_id')):
                proposal.status = 'stale'
        reply = {'message': turn_text(turn, '位点已保存；生成计算需要另行批准。', 'The site has been saved. Generation requires separate approval.'), 'protein_context_id': context['id'], 'missing_requirements': remaining}
    elif request.intent == "selection":
        if not request.selection:
            raise WorkflowError("SELECTION_REQUIRED", "Specify selection conditions", 422)
        sets = db.scalars(select(CandidateSet).where(CandidateSet.session_id == session.id).order_by(CandidateSet.created_at.desc())).all()
        if session.active_workflow_id:
            run = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
            job_id = next((s.job_id for s in workflow_steps(db, run.id) if s.step_key == "postprocessing" and s.status == "succeeded"), None)
        else:
            job_id = sets[0].postprocessing_job_id if sets else None
        if not job_id:
            raise WorkflowError('SOURCE_NOT_READY', 'Complete postprocessing before selecting candidates', 409)
        job, task, rows = load_tarpass_results(db, user_id=session.owner_user_id, job_id=job_id)
        from backend.services.results import apply_query
        selected = apply_query(rows, filters=[f.model_dump() for f in request.selection.filters],
            sort_by=request.selection.sort_by or "molecule_id", descending=request.selection.descending)
        payload = {"postprocessing_job_id": str(job.id), "selection": request.selection.model_dump(mode="json"),
            "artifact_hash": file_sha256(resolve_job_artifact(job, task.output_payload["results_json"]))}
        proposal = create_proposal(db, session, turn, "selection", payload, workflow=run if session.active_workflow_id else None)
        reply = {"message": turn_text(turn, "筛选提案已生成，请批准保存候选集合。", "A selection proposal has been created. Approve it to save the candidate set."), "proposal_id": str(proposal.id),
                 "matched_count": len(selected), "selected_count": min(len(selected), request.selection.top_k or len(selected))}
    else:
        run = owned_workflow(db, session.active_workflow_id, session.owner_user_id)
        steps = {s.step_key: s for s in workflow_steps(db, run.id)}
        if run.status != "failed" or steps["generation"].status != "succeeded" or steps["postprocessing"].status != "failed":
            raise WorkflowError("RETRY_NOT_AVAILABLE", "Only failed postprocessing with successful generation can be retried", 409)
        return prepare_postprocessing(db, session, turn, {'choice': 'run', 'evidence': 'user requested postprocessing retry'})
    return reply


def submit_request(db, session, request):
    binding = (session.assets or {}).get('module_assistant')
    if binding:
        if request.intent != 'ask' or request.module_context is None or request.attachments or request.values or request.task_plan or request.selection:
            raise WorkflowError('INVALID_INPUT', 'Module assistants only accept questions and parameter suggestions', 422)
        from backend.agent.module_assistant import page_context
        try:
            page_context(db, session.owner_user_id, binding, request.module_context)
        except ValueError as exc:
            raise WorkflowError('INVALID_INPUT', str(exc), 422) from exc
    elif request.module_context is not None:
        raise WorkflowError('INVALID_INPUT', 'Module context requires a module conversation', 422)
    if request.intent == "auto" and not request.message.strip() and not request.attachments:
        raise WorkflowError("EMPTY_MESSAGE", "Send a message or an attachment", 422)
    if request.attachments and request.intent != "auto":
        raise WorkflowError("INVALID_INPUT", "Attachments require an automatic conversation turn", 422)
    if request.intent in {"plan", "modify"} and session.phase in {"cancel_requested", "canceled", "archived"}:
        raise WorkflowError("SESSION_BUSY", "The current session cannot create another plan", 409)
    turn, claimed = claim_turn(db, session, request, queued=True)
    if not claimed:
        return turn
    from backend.agent.research_safety import ensure_task, pending_active
    if turn.research_task_id and request.intent != "new_task" and turn.research_task_id != session.research_task_id:
        raise WorkflowError("INPUT_CHANGED", "The turn belongs to another research task", 409)
    from backend.models import ResearchTask
    task = db.scalar(select(ResearchTask).where(ResearchTask.id == turn.research_task_id,
        ResearchTask.owner_user_id == session.owner_user_id).with_for_update().execution_options(populate_existing=True)) if turn.research_task_id else ensure_task(db, session.owner_user_id, request.message or session.goal, session=session, new=request.intent == "new_task")
    if task is None:
        raise WorkflowError('RESOURCE_NOT_FOUND', 'Research task not found', 404)
    if task.pending_turn_id != turn.id and pending_active(db, task):
        raise WorkflowError('SAFETY_ASSESSMENT_REQUIRED', 'Another assessment is in progress', 409)
    turn.research_task_id = task.id
    if task.task_plan and task.task_plan['state'] == 'waiting_input':
        from backend.services.task_plans import store
        value = deepcopy(task.task_plan)
        value['run']['answer_turn_id'] = str(turn.id)
        store(task, value)
    task.pending_turn_id = turn.id
    if task.state != "blocked":
        task.state = "unassessed"
    if not session.goal and request.message.strip():
        session.goal = request.message.strip()[:4000]
    session.updated_at = utcnow()
    session.last_user_activity_at = utcnow()
    return turn


def reconcile_session(db, session):
    try:
        with db.begin_nested():
            _sync_session(db, session)
    except (ResourceNotFound, WorkflowError) as error:
        if error.code != 'RESOURCE_NOT_FOUND':
            raise
        session.phase = 'awaiting_selection'
        session.last_error = error.code
        session.pending_requirements = ['protein_context_id'] if session.assets.get('protein_context_id') else []


def _sync_session(db, session):
    if isinstance(session, AgentSession):
        db.flush()
        db.refresh(session, with_for_update=True)
    now = utcnow()
    for turn in db.scalars(select(AgentTurn).where(AgentTurn.session_id == session.id, AgentTurn.status == "running", AgentTurn.lease_until < now)):
        interrupt_turn(db, session, turn)
    explicit_turn = db.scalar(select(AgentTurn.id).where(
        AgentTurn.session_id == session.id,
        AgentTurn.status.in_(["queued", "running"]),
        AgentTurn.audit["trigger"].as_string().is_(None),
    ).order_by(AgentTurn.created_at).with_for_update().limit(1))
    if explicit_turn:
        return
    task = db.get(ResearchTask, session.research_task_id) if session.research_task_id else None
    if task and task.state == 'blocked':
        session.pending_requirements = []
        return
    if (session.assets or {}).get('module_assistant'):
        return
    if session.phase == 'ready_for_planning' and session.assets.get('protein_context_id'):
        get_owned_dataset(db, uuid.UUID(session.assets['protein_context_id']), session.owner_user_id)
    if session.research_task_id:
        continue_reading(db, session)
    from backend.services import task_plans
    if session.research_task_id and task_plans.advance(db, session):
        return
    _reconcile_session(db, session)
    if session.phase in {"canceled", "cancel_requested"}:
        return
    task = db.get(ResearchTask, session.research_task_id) if session.research_task_id else None
    active_turn = db.scalar(select(AgentTurn.id).where(AgentTurn.session_id == session.id,
        AgentTurn.status.in_(['queued', 'running'])).order_by(AgentTurn.created_at).with_for_update().limit(1))
    if task and task.state == 'allowed' and not task.pending_turn_id and not active_turn and session.phase == 'ready_for_planning' and session.assets.get('protein_context_id'):
        from backend.agent.schemas import WorkflowPlan
        from backend.workflows.commands import save_plan
        values = session_values(session)
        preferences = task.workflow_preferences or {}
        future = (task.task_plan or {}).get('definition', {}).get('workflow') or {}
        versioned = task.task_plan or {}
        preference_version = preferences.get('generation_source_version', 0)
        use_preferences = preferences.get('generation_source') in {'optimization_draft', 'agent_turn'} \
            and versioned.get('version', 0) <= preference_version
        if use_preferences:
            requested = preferences.get('generation') or {}
            seed_source = preferences.get('seed_source') or session.assets.get('optimization_seed')
            future = {}
        else:
            requested = future.get('generation') or preferences.get('generation') or {}
            seed_source = future.get('seed_source')
        engine = requested.get('engine')
        if not engine:
            session.phase, session.pending_requirements = 'waiting_input', ['engine']
            turn = task_plans.internal_turn(db, session, task,
                f"method-required:{session.assets['protein_context_id']}:{versioned.get('version', 0)}",
                session_text(db, session, '蛋白准备和位点选择已完成。下一步请确认计算方法：SurfGen / ECloudGen 用于从头生成，DELETE 用于指定片段改造，EPSO 用于完整分子的二维性质优化。确认方法后会提出当前阶段方案，批准后才执行。', 'Protein preparation and site selection are complete. Choose a method: SurfGen / ECloudGen for de novo generation, DELETE for selected fragment editing, or EPSO for 2D property optimization of whole molecules. A stage plan will be proposed for approval before execution.'))
            turn.status = 'needs_input'
            turn.response = {**turn.response, 'missing_requirements': ['engine'],
                'clarification_fields': [{'requirement': 'engine', 'id': 'engine'}]}
            return
        if engine not in {'surfgen', 'ecloudgen', 'delete', 'epso'}:
            raise WorkflowError('INVALID_INPUT', 'Choose a supported generation or optimization method', 422)
        if engine in {'surfgen', 'ecloudgen'} and not (not use_preferences and future.get('seed_source')):
            seed_source = None
        elif seed_source is None and engine in {'delete', 'epso'}:
            seed_source = session.assets.get('optimization_seed')
        field = 'target_num_molecules' if engine == 'ecloudgen' else 'num_molecules'
        postprocessing = dict(future.get('postprocessing') or {})
        if 'prefilters' in preferences.get('postprocessing', {}):
            postprocessing['prefilters'] = deepcopy(preferences['postprocessing']['prefilters'])
        choice = (preferences.get('postprocessing') or {}).get('choice')
        if choice in {'run', 'skip'}:
            postprocessing['enabled'] = choice == 'run'
        selection_source = preferences.get('selection') or future.get('selection') or {}
        selection = {key: value for key, value in selection_source.items()
            if key in {'sort_by', 'descending', 'top_k'}}
        generation = deepcopy(requested)
        generation.setdefault('engine', engine)
        default_count = 100 if engine == 'epso' else DEFAULT_GENERATION_COUNT
        generation.setdefault(field, int(values.get(field, values.get('num_molecules', default_count))))
        if engine == 'delete':
            edit_spec_id = generation.get('edit', {}).get('edit_spec_id') or values.get('delete_edit_spec_id')
            spec = None
            if edit_spec_id:
                from backend.models import DeleteEditSpec
                try:
                    spec = db.get(DeleteEditSpec, uuid.UUID(str(edit_spec_id)))
                except (TypeError, ValueError):
                    spec = None
            context_valid = False
            if spec and spec.owner_user_id == session.owner_user_id:
                try:
                    context = validate_protein_context_for_generation(
                        db, session.owner_user_id, uuid.UUID(session.assets['protein_context_id']))
                    context_valid = file_sha256(delete_reference_path(context)) == spec.reference_sha256
                except (KeyError, ValueError, WorkflowError, DomainValidationError):
                    context_valid = False
            if not context_valid:
                source_key = digest({
                    'context': session.assets['protein_context_id'],
                    'engine': engine,
                    'seed_source': seed_source,
                    'task_plan_version': versioned.get('version', 0),
                    'generation_source_version': preference_version if use_preferences else None,
                })
                missing = task_plans.internal_turn(db, session, task, f'delete-editor-required:{source_key}',
                    session_text(db, session, 'DELETE 需要先在结构编辑器中保存编辑片段；保存后再继续创建方案。', 'Save the DELETE fragments in the structure editor before creating the plan.'))
                session.phase, session.pending_requirements = 'waiting_input', ['delete_edit_spec_id']
                missing.status = 'needs_input'
                # The saved edit is bound to the current Context reference and is checked again at submission.
                if missing.status == 'needs_input':
                    missing.response = {'message': session_text(db, session, 'DELETE 需要先在结构编辑器中保存编辑片段；保存后再继续创建方案。', 'Save the DELETE fragments in the structure editor before creating the plan.'),
                        'missing_requirements': ['delete_edit_spec_id']}
            else:
                generation = {**generation, 'edit': {
                    'mode': spec.specification['edit']['mode'], 'edit_spec_id': str(spec.id)}}
        if engine != 'delete' or (spec and context_valid):
            try:
                plan = WorkflowPlan(protein_context_id=session.assets['protein_context_id'], generator=engine,
                    template=f'{engine}_tarpass_v1', generation=generation,
                    seed_source=deepcopy(seed_source), postprocessing=postprocessing, selection=selection)
                effective_generation(plan)
            except (ValueError, DomainValidationError) as error:
                session.phase, session.pending_requirements = 'waiting_input', ['engine']
                session.last_error = 'INVALID_GENERATION_PARAMETERS'
                turn = task_plans.internal_turn(db, session, task,
                    f"parameters-required:{session.assets['protein_context_id']}:{digest(generation)}",
                    session_text(db, session,
                        '蛋白准备和位点选择已完成，尚未启动分子计算。方案参数不完整或无效。'
                        + ('EPSO 需要至少一个有效的优化目标。请确认使用 DELETE 片段改造还是 EPSO 性质优化，再核对方案中的目标和参数。'
                           if engine == 'epso' else '请重新确认计算方法，再核对方案中的参数。'),
                        'Protein preparation and site selection are complete. Molecular computation has not started. The plan parameters are incomplete or invalid. '
                        + ('EPSO requires at least one valid objective. Confirm whether to use DELETE fragment editing or EPSO property optimization, then check the objectives and parameters.'
                           if engine == 'epso' else 'Confirm the method again and review the plan parameters.')))
                turn.status = 'needs_input'
                turn.response = {**turn.response, 'missing_requirements': ['engine'],
                    'clarification_fields': [{'requirement': 'engine', 'id': 'engine'}],
                    'validation_error': str(error)[:2000]}
                return
            source_key = digest({
                'context': session.assets['protein_context_id'],
                'workflow': plan.model_dump(mode='json'),
                'task_plan_version': versioned.get('version', 0),
                'generation_source_version': preference_version if use_preferences else None,
            })
            key = f"context-ready:{source_key}"
            turn = task_plans.internal_turn(db, session, task, key,
                session_text(db, session, '位点与模型输入已准备好，已生成下一阶段草稿。请检查模型和参数后批准执行。', 'The binding site and model inputs are ready. Review the next-stage draft and its parameters before approval.'))
            if not db.scalar(select(ActionProposal.id).where(ActionProposal.turn_id == turn.id)):
                save_plan(db, session, turn, plan, new=True)
                session.last_error = None
                # This turn creates a draft, so it must receive a separate approval.
                stage_turn = task_plans.internal_turn(db, session, task, key + ':stage')
                task_plans.save(db, session, stage_turn, {'stage': 'generation', 'workflow': plan.model_dump(mode='json'), 'preparation': None, 'site': None})
                session.pending_requirements = []
                run = db.get(WorkflowRun, session.active_workflow_id)
                db.get(ActionProposal, run.action_proposal_id).status = 'stale'
    proposals = db.scalars(select(ActionProposal).where(ActionProposal.session_id == session.id,
        ActionProposal.status == 'approved').order_by(ActionProposal.created_at)).all()
    for proposal in proposals:
        origin = db.get(AgentTurn, proposal.turn_id)
        if proposal.kind == 'task_plan' or origin.audit.get('task_plan_event') or origin.research_task_id != session.research_task_id:
            continue
        job_id = proposal.execution.get('job_id')
        if proposal.kind == 'workflow':
            run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == proposal.workflow_id,
                WorkflowRun.owner_user_id == session.owner_user_id)) if proposal.workflow_id else None
            if run is None:
                proposal.status = 'stale'
                continue
            generation = next(step for step in workflow_steps(db, run.id) if step.step_key == 'generation')
            resource_id, status = str(run.id), generation.status
            label = ('分子生成／优化', 'Molecular generation / optimization')
        elif job_id:
            job = get_owned_job(db, session.owner_user_id, uuid.UUID(job_id))
            resource_id, status = str(job.id), job.status
            label = ('蛋白准备', 'Protein preparation') if proposal.kind == 'prepare' else ('后处理', 'Postprocessing')
        else:
            continue
        if status not in {'succeeded', 'failed', 'canceled'}:
            continue
        key = uuid.uuid5(session.id, f'completion:{proposal.id}:{resource_id}:{status}')
        if db.scalar(select(AgentTurn.id).where(AgentTurn.session_id == session.id, AgentTurn.client_request_id == key)):
            continue
        following = ('', '')
        if status == 'succeeded':
            if proposal.kind == 'prepare':
                following = ('下一步请在结构编辑器中确认结合位点；保存后会生成分子计算草稿。', ' Confirm the binding site in the structure editor next. Saving it creates a molecular calculation draft.')
            elif proposal.kind != 'workflow':
                following = ('你可以让我帮助分析结果，或选择分子参与后续优化。', ' You can ask me to analyze the results or select molecules for further optimization.')
        language = session_interface_language(db, session)
        index = 0 if language == 'zh' else 1
        ending = {'succeeded': ('已完成。', ' is complete.'), 'failed': ('执行失败，已停止。请查看错误后重试或修改方案。', ' failed and has stopped. Inspect the error, then retry or revise the plan.'), 'canceled': ('已取消。', ' was canceled.')}[status]
        request = SessionTurnRequest(client_request_id=key, intent='ask', interface_language=language).model_dump(mode='json')
        db.add(AgentTurn(session_id=session.id, research_task_id=origin.research_task_id, client_request_id=key,
            request_hash=digest(request), request=request, status='completed', attempt=1,
            audit={'trigger': 'completion', 'proposal_id': str(proposal.id), 'execution_revision': session.input_revision},
            response={'message': label[index] + ending[index] + following[index]}))
        db.flush()


def history_page(db, session, *, query="", offset=0, limit=50, research_task_id=None):
    stmt = select(AgentTurn).where(AgentTurn.session_id == session.id)
    if research_task_id is not None:
        stmt = stmt.where(AgentTurn.research_task_id == research_task_id)
    if query:
        stmt = stmt.where(AgentTurn.request["message"].as_string().contains(query[:200], autoescape=True) |
                          AgentTurn.response["message"].as_string().contains(query[:200], autoescape=True) |
                          AgentTurn.response["diagnostic_notes"].as_string().contains(query[:200], autoescape=True))
    turns = [turn_out(row) for row in db.scalars(stmt.order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc()).offset(offset).limit(limit))]
    proposals = [proposal_out(row) for row in db.scalars(select(ActionProposal).where(
        ActionProposal.session_id == session.id, ActionProposal.turn_id.in_([uuid.UUID(t["id"]) for t in turns])))]
    for turn in turns:
        turn["proposals"] = [p for p in proposals if p["turn_id"] == turn["id"]]
    return turns


def continuation_stopped(db, session_id, since, *, research_task_id=None):
    return db.scalar(select(AgentTurn.id).where(AgentTurn.session_id == session_id,
        (AgentTurn.audit["operation"].as_string() == "archive") | ((AgentTurn.audit["operation"].as_string() == "stop_continuation") & (AgentTurn.research_task_id == research_task_id)),
        AgentTurn.created_at > since).limit(1)) is not None


def stop_turn(db, session, turn_id):
    turn = db.scalar(select(AgentTurn).where(AgentTurn.id == turn_id, AgentTurn.session_id == session.id))
    if turn is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Turn not found", 404)
    if turn.status not in {"queued", "running"}:
        return turn
    interrupt_turn(db, session, turn)
    turn.status = "canceled"
    turn.lease_until = None
    turn.response = {**turn.response, "message": "", "stopped_by_user": True,
        "stream_seq": turn.response.get("stream_seq", 0) + 1,
        "tools": [{**tool, "status": "canceled"} if tool.get("status") == "running" else tool
                  for tool in turn.response.get("tools", [])]}
    if turn.research_task_id:
        task = db.get(ResearchTask, turn.research_task_id)
        if task.pending_turn_id == turn.id:
            task.pending_turn_id = None
    session.last_user_activity_at = utcnow()
    return turn


def resume_turn(db, session, turn_id, *, interface_language=None):
    from sqlalchemy import func
    from backend.models import User
    source = db.scalar(select(AgentTurn).where(AgentTurn.id == turn_id, AgentTurn.session_id == session.id))
    if source is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Turn not found", 404)
    from backend.agent.research_safety import bind_legacy_turn, pending_active
    bind_legacy_turn(db,session,source)
    task = db.scalar(select(ResearchTask).where(ResearchTask.id == source.research_task_id,
        ResearchTask.owner_user_id == session.owner_user_id).with_for_update().execution_options(populate_existing=True))
    if task and task.state == 'blocked':
        raise WorkflowError('RESEARCH_TASK_BLOCKED', 'This research task is not cleared for scientific operations', 409)
    if task and task.pending_turn_id != source.id and pending_active(db, task):
        raise WorkflowError('SAFETY_ASSESSMENT_REQUIRED', 'Another assessment is in progress', 409)
    retry_new_task = source.request['intent'] == 'new_task' and source.response.get('error_code') == 'SAFETY_CHECK_UNAVAILABLE'
    if source.research_task_id != session.research_task_id and not retry_new_task:
        raise WorkflowError("INPUT_CHANGED", "The stopped turn belongs to another research task", 409)
    resumed_by = source.audit.get('resumed_by') or source.audit.get('reading_resumed_by')
    if resumed_by:
        return db.get(AgentTurn, uuid.UUID(resumed_by))
    if source.status not in {"failed", "interrupted"}:
        raise WorkflowError("TURN_NOT_RECOVERABLE", "Only a stopped turn can be continued", 409)
    # A completion turn runs its continuation goal; once stopped there is nothing to resume.
    if source.audit.get("trigger") and (not source.audit.get("continuation") or continuation_stopped(db, session.id, source.created_at, research_task_id=source.research_task_id)):
        raise WorkflowError("TURN_NOT_RECOVERABLE", "Automatic continuation was stopped; send a new message", 409)
    count = source.audit.get("recovery_count", 0)
    if count >= 2:
        raise WorkflowError("TURN_RECOVERY_LIMIT", "This task has used its two explicit continuations", 409)
    if session.phase == "archived" or (session.phase in {"canceled", "cancel_requested"} and not retry_new_task):
        raise WorkflowError("SESSION_BUSY", "This session cannot continue the stopped task", 409)
    revision = source.audit.get("execution_revision", source.request.get("base_revision"))
    if source.request["intent"] != "ask" and revision != session.input_revision:
        raise WorkflowError("INPUT_CHANGED", "Inputs changed; send a new message for the current state", 409)
    db.scalar(select(User).where(User.id == session.owner_user_id).with_for_update())
    recent = db.scalar(select(func.count()).select_from(AgentTurn).join(AgentSession).where(
        AgentSession.owner_user_id == session.owner_user_id, AgentTurn.created_at > utcnow() - timedelta(hours=1),
        AgentTurn.audit["recovery_of"].as_string().is_not(None)))
    if recent >= 10:
        raise WorkflowError("TURN_RECOVERY_RATE_LIMIT", "Too many continuations; try again later", 429)
    request = SessionTurnRequest.model_validate({**source.request, "client_request_id": str(uuid.uuid4()),
        "base_revision": session.input_revision, "retry": False,
        "interface_language": interface_language or session_interface_language(db, session)})
    row, _ = claim_turn(db, session, request, queued=True)
    row.research_task_id = source.research_task_id
    if row.research_task_id:
        task = db.get(ResearchTask, row.research_task_id)
        task.pending_turn_id = row.id
        if task.state != "blocked":
            task.state = "unassessed"
    root = source.audit.get("command_turn_id", str(source.id))
    row.audit = {"recovery_of": str(source.id), "recovery_count": count + 1, "command_turn_id": root,
        "checkpoint": source.audit.get("checkpoint"), "execution_revision": session.input_revision,
        **({'pending_review': source.audit['pending_review']} if source.audit.get('pending_review') else {}),
        "source_read_state": source.audit.get("source_read_state", {}),
        "committed_effects": source.audit.get("committed_effects", []),
        **{key: source.audit[key] for key in ("trigger", "proposal_id", "continuation") if source.audit.get(key)}}
    source.audit = {**source.audit, "resumed_by": str(row.id)}
    return row


def continue_reading(db, session):
    if session.phase in {'paused', 'cancel_requested', 'canceled', 'archived'}:
        return
    source = db.scalar(select(AgentTurn).where(AgentTurn.session_id == session.id,
        AgentTurn.research_task_id == session.research_task_id,
        AgentTurn.audit['trigger'].as_string().is_distinct_from('task_plan'))
        .order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc()).limit(1))
    if source is None:
        return
    paused = source.status == 'completed' and source.response.get('investigation_status') == 'paused'
    interrupted = source.status == 'interrupted' or (source.status == 'failed' and source.response.get('retryable'))
    if not paused and not interrupted:
        return
    if interrupted and not (source.audit.get('source_read_state') or source.audit.get('diagnostic_state')):
        return
    effects = [*source.response.get('committed_effects', []), *source.audit.get('committed_effects', [])]
    if any(effect['kind'] != 'inputs_saved' for effect in effects) or source.audit.get('reading_resumed_by'):
        return
    if continuation_stopped(db, session.id, source.created_at, research_task_id=session.research_task_id):
        source.audit = {**source.audit, 'reading_stopped': True}
        return
    progress = source.audit.get('source_read_state') or source.audit.get('diagnostic_state') or {}
    previous = source.audit.get('reading_progress')
    stalled = source.audit.get('reading_stalled', 0) + 1 if progress == previous else 0
    if stalled >= 2:
        source.audit = {**source.audit, 'reading_stalled':stalled}
        source.response = {**source.response, 'investigation_status':'blocked',
            'message':(source.response.get('message') or '') + '\n\n' + session_text(db, session, '连续两次读取没有取得进展，已停止自动续读；读取位置与已有结果已保留。', 'Reading made no progress in two consecutive attempts. Automatic continuation has stopped; your reading progress and results have been saved.')}
        db.flush()
        return
    task = db.get(ResearchTask, session.research_task_id)
    if task.task_plan and (task.task_plan['state'] in {'paused','pause_requested','blocked','waiting_input'} or (
            task.task_plan.get('run', {}).get('deadline') and utcnow() >= datetime.fromisoformat(task.task_plan['run']['deadline']))):
        return
    identity = uuid.uuid5(source.id, 'continue-reading')
    intent = source.audit.get('resolved_intent', source.request['intent'])
    intent = intent if intent in {'ask','plan','modify'} else 'ask'
    request = SessionTurnRequest.model_validate({**source.request, 'client_request_id':identity,
        'intent':intent, 'base_revision':session.input_revision, 'retry':False, 'attachments':{}, 'values':{}})
    body = request.model_dump(mode='json')
    row = AgentTurn(id=identity, session_id=session.id, research_task_id=session.research_task_id,
        client_request_id=identity, request_hash=digest(body), request=body, status='queued', attempt=1,
        response={}, audit={'trigger':'reading', 'execution_revision':session.input_revision,
            'reading_progress':progress, 'reading_stalled':stalled,
            'source_read_state':source.audit.get('source_read_state', {}), 'diagnostic_state':source.audit.get('diagnostic_state', {})})
    db.add(row)
    source.audit = {**source.audit, 'reading_resumed_by':str(row.id)}
    source.response = {**source.response, 'investigation_status':'continuing',
        'message':source.response.get('message') or session_text(db, session, '已保存读取位置，将继续查看并回答。', 'Reading progress has been saved. I will continue reviewing it and respond.')}
    db.flush()
