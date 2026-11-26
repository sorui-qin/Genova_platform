"""Independent Agent sessions; the old workflow API remains available."""
import uuid

from functools import wraps

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agent.safety import normalize_and_check_prompt, PromptBlocked
from backend.agent.module_contracts import ModuleSessionRequest
from backend.agent.session_schemas import OptimizationDraftRequest, OptimizationPoseApprovalRequest, SessionCreate, SessionTurnRequest, ProposalApproval, SessionStart
from backend.agent.user_settings import personal_config
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import AgentSession, AgentTurn, ActionProposal, CandidateSet, SmallMoleculeResult, User, WorkflowCommand
from backend.services import agent_sessions as service
from backend.services.jobs import DomainValidationError, validate_protein_context_for_generation, resolve_job_artifact
from backend.services.results import ResultServiceError, load_tarpass_results, project_row
from backend.services.workflows import WorkflowError, owned_workflow, cancel_workflow
from genova_runtime.pdb2pqr_compat import file_sha256
from backend.utils import utcnow

router = APIRouter(prefix="/agent/sessions", tags=["agent-sessions"])


def http_error(exc):
    return HTTPException(exc.http_status, {"error_code": exc.code, "message": exc.message})


def read_errors(fn):
    import inspect
    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def wrapped_async(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except (WorkflowError, DomainValidationError, ResultServiceError) as exc:
                raise http_error(exc) from exc
        return wrapped_async
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (WorkflowError, DomainValidationError, ResultServiceError) as exc:
            raise http_error(exc) from exc
    return wrapped


@router.post("", status_code=201)
def create(request: SessionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = AgentSession(owner_user_id=user.id, goal=request.goal)
    db.add(row)
    db.flush()
    if request.workflow_id:
        try:
            run = owned_workflow(db, request.workflow_id, user.id)
        except WorkflowError as exc:
            raise http_error(exc) from exc
        row.research_task_id = run.research_task_id
        row.active_workflow_id = run.id
        row.assets = {"protein_context_id": run.plan_json["protein_context_id"]}
        row.phase = {"awaiting_approval": "awaiting_workflow_approval", "approved": "executing", "running": "executing", "succeeded": "results_ready"}.get(run.status, run.status)
    result = service.snapshot(db, row)
    db.commit()
    return result


@router.get("")
def list_sessions(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [{"id": str(row.id), "goal": row.goal, "phase": row.phase} for row in db.scalars(
        select(AgentSession).where(AgentSession.owner_user_id == user.id,
            AgentSession.assets['module_assistant'].astext.is_(None)).order_by(AgentSession.created_at.desc()).limit(limit))]


@router.post('/module')
@read_errors
def module_session(request: ModuleSessionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.agent.module_assistant import module_job
    binding = request.model_dump(mode='json')
    module_job(db, user.id, binding)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = db.scalar(select(AgentSession).where(AgentSession.owner_user_id == user.id,
        AgentSession.assets.contains({'module_assistant': binding})).order_by(AgentSession.created_at).limit(1))
    if row is None:
        row = AgentSession(owner_user_id=user.id, phase='module_assistant', assets={'module_assistant': binding})
        db.add(row)
        db.flush()
    service.reconcile_session(db, row)
    result = service.snapshot(db, row)
    db.commit()
    return result


@router.post('/{session_id}/module-job')
@read_errors
def bind_module_job(session_id: uuid.UUID, request: ModuleSessionRequest,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.agent.module_assistant import module_job
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    session = service.owned_session(db, session_id, user.id, lock=True)
    binding = (session.assets or {}).get('module_assistant')
    if not binding or binding['module'] != request.module or not request.job_id:
        raise HTTPException(422, 'Invalid module task binding')
    if binding.get('job_id') and binding['job_id'] != str(request.job_id):
        raise HTTPException(409, 'Conversation already belongs to a task')
    updated = request.model_dump(mode='json')
    module_job(db, user.id, updated)
    session.assets = {**session.assets, 'module_assistant': updated}
    result = service.snapshot(db, session)
    db.commit()
    return result


def page_language(http: Request):
    tag = (http.headers.get("accept-language") or "").split(",")[0].strip().lower()
    return "zh" if tag.startswith("zh") else "en" if tag.startswith("en") else None


@router.post("/start", status_code=202)
def start(request: SessionStart, http: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from sqlalchemy.dialects.postgresql import insert
    request.turn.interface_language = page_language(http) or request.turn.interface_language
    try:
        if request.turn.intent != "auto" or not (request.turn.message.strip() or request.turn.attachments):
            raise WorkflowError("EMPTY_MESSAGE", "Start with a message or an attachment", 422)
        request.turn.message = normalize_and_check_prompt(request.turn.message) if request.turn.message else ""
        personal_config(db, user.id)
        db.execute(insert(AgentSession).values(id=request.client_session_id, owner_user_id=user.id)
            .on_conflict_do_nothing(index_elements=["id"]))
        session = service.owned_session(db, request.client_session_id, user.id, lock=True)
        first = db.scalar(select(AgentTurn).where(AgentTurn.session_id == session.id).order_by(AgentTurn.created_at).limit(1))
        if first and first.client_request_id != request.turn.client_request_id:
            raise WorkflowError("REQUEST_CONFLICT", "Session already has a first message", 409)
        service.submit_request(db, session, request.turn)
        result = service.snapshot(db, session)
        db.commit()
        return result
    except PromptBlocked as exc:
        db.rollback()
        raise HTTPException(400, {"error_code": "PROMPT_BLOCKED", "message": exc.reason}) from exc
    except (WorkflowError, DomainValidationError, ResultServiceError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, "Invalid session input") from exc


@router.get("/{session_id}")
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        row = service.owned_session(db, session_id, user.id, lock=True)
        service.reconcile_session(db, row)
        result = service.snapshot(db, row)
        db.commit()
        return result
    except (WorkflowError, DomainValidationError, ResultServiceError) as exc:
        db.rollback()
        raise http_error(exc) from exc


@router.post("/{session_id}/turns")
def submit_turn(session_id: uuid.UUID, request: SessionTurnRequest, http: Request,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    request.interface_language = page_language(http) or request.interface_language
    try:
        if request.message:
            request.message = normalize_and_check_prompt(request.message)
        session = service.owned_session(db, session_id, user.id, lock=True)
        service.reconcile_session(db, session)
        if request.intent in {"auto", "ask", "plan", "modify"}:
            personal_config(db, user.id)
        turn = service.submit_request(db, session, request)
        result = service.turn_out(turn)
        db.commit()
        return JSONResponse(result, status_code=202 if turn.status in {"queued", "running"} else 200)
    except PromptBlocked as exc:
        db.rollback()
        raise HTTPException(400, {"error_code": "PROMPT_BLOCKED", "message": exc.reason}) from exc
    except (WorkflowError, DomainValidationError, ResultServiceError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    except (ValueError, StopIteration) as exc:
        db.rollback()
        raise HTTPException(422, "Invalid or unavailable session input") from exc


@router.post("/{session_id}/turns/{turn_id}/stop")
def stop_turn(session_id: uuid.UUID, turn_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        session = service.owned_session(db, session_id, user.id, lock=True)
        turn = service.stop_turn(db, session, turn_id)
        result = service.turn_out(turn)
        db.commit()
        from backend.services.agent_turns import publish_turn
        publish_turn(user.id, {**result, "session_id": str(session_id)})
        return result
    except WorkflowError as exc:
        db.rollback()
        raise http_error(exc) from exc


@router.post("/{session_id}/turns/{turn_id}/resume", status_code=202)
def resume(session_id: uuid.UUID, turn_id: uuid.UUID, http: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        session = service.owned_session(db, session_id, user.id, lock=True)
        personal_config(db, user.id)
        turn = service.resume_turn(db, session, turn_id, interface_language=page_language(http))
        session.last_user_activity_at = utcnow()
        result = service.turn_out(turn)
        db.commit()
        return result
    except WorkflowError as exc:
        db.rollback()
        raise http_error(exc) from exc


@router.get("/{session_id}/history")
@read_errors
def history(session_id: uuid.UUID, query: str = Query("", max_length=200), offset: int = Query(0, ge=0),
            limit: int = Query(50, ge=1, le=50), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = service.owned_session(db, session_id, user.id)
    return service.history_page(db, session, query=query, offset=offset, limit=limit)


@router.get("/{session_id}/specs")
@read_errors
def specs(session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = service.owned_session(db, session_id, user.id)
    from backend.agent.facts import parameter_specs, metric_specs
    from tarpass.contracts import INTERACTION_TYPES, protein_residues
    residues = []
    if session.assets.get("protein_context_id") and session.phase not in {"preparing", "awaiting_upload", "awaiting_selection"}:
        try:
            context = validate_protein_context_for_generation(db, user.id, uuid.UUID(session.assets["protein_context_id"]))
            residues = protein_residues(context["protein_pdb"])
        except DomainValidationError:
            pass
    from backend.agent.catalog import CapabilityCatalog
    return {"capabilities": CapabilityCatalog().to_dict(), "parameters": parameter_specs(), "metrics": metric_specs(), "interaction_types": sorted(INTERACTION_TYPES), "residues": residues}


@router.get("/{session_id}/protein-analysis")
@read_errors
def inspect_protein(session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = service.owned_session(db, session_id, user.id)
    source_id = session.assets.get("protein_dataset_id")
    if not source_id:
        raise HTTPException(409, "Bind a protein dataset first")
    from backend.services.protein_contexts import _protein_file_or_400
    from backend.services.jobs import get_owned_dataset
    source = get_owned_dataset(db, uuid.UUID(source_id), user.id)
    row = _protein_file_or_400(db, source.id, service.session_values(session).get("protein_file_id"))
    if file_sha256(row.storage_path) != row.sha256:
        raise HTTPException(409, "Protein input changed")
    from backend.services.prepared_receptors import get_component_manifest
    from backend.structure_contracts import StructureSource
    from genova_runtime.structure_inventory import inventory_summary
    manifest = get_component_manifest(StructureSource(dataset_id=source.id, file_id=row.id, sha256=row.sha256, model_id='1'), db, user.id)
    return inventory_summary(manifest.model_dump(mode='json'))


@router.get("/{session_id}/turns/{turn_id}")
def get_turn(session_id: uuid.UUID, turn_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.owned_session(db, session_id, user.id)
    row = db.scalar(select(AgentTurn).where(AgentTurn.id == turn_id, AgentTurn.session_id == session_id))
    if row is None:
        raise HTTPException(404, "Turn not found")
    return service.turn_out(row)


@router.post("/{session_id}/proposals/{proposal_id}/approve")
async def approve(session_id: uuid.UUID, proposal_id: uuid.UUID, request: ProposalApproval,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        session = service.owned_session(db, session_id, user.id, lock=True)
        from backend.agent.research_safety import assess_existing
        from backend.models import ActionProposal, AgentTurn, WorkflowRun
        original = db.get(ActionProposal, proposal_id)
        if original is None or original.session_id != session.id:
            raise WorkflowError("RESOURCE_NOT_FOUND", "Proposal not found", 404)
        origin = db.get(AgentTurn, original.turn_id)
        workflow = db.get(WorkflowRun, original.workflow_id) if original.workflow_id else None
        await assess_existing(db, user.id, workflow=workflow, session=session, origin=origin)
        session = service.owned_session(db, session_id, user.id, lock=True)
        proposal = service.approve_proposal(db, session, proposal_id, request.action_hash)
        session.last_user_activity_at = utcnow()
        result = service.proposal_out(proposal)
        db.commit()
        return result
    except (WorkflowError, DomainValidationError, ResultServiceError) as exc:
        db.rollback()
        raise http_error(exc) from exc


@router.post("/{session_id}/cancel")
def cancel(session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        session = service.owned_session(db, session_id, user.id, lock=True)
        if session.active_workflow_id:
            run = owned_workflow(db, session.active_workflow_id, user.id)
            if run.status in {"awaiting_approval", "approved", "running"}:
                cancel_workflow(db, workflow_id=run.id, owner_user_id=user.id)
        session.phase = "cancel_requested"
        session.last_user_activity_at = utcnow()
        result = service.snapshot(db, session)
        db.commit()
        return result
    except WorkflowError as exc:
        raise http_error(exc) from exc


def candidate_rows(db, session_id, set_id, user_id):
    service.owned_session(db, session_id, user_id)
    row = db.scalar(select(CandidateSet).where(CandidateSet.id == set_id, CandidateSet.session_id == session_id, CandidateSet.owner_user_id == user_id))
    if row is None:
        raise HTTPException(404, "Candidate set not found")
    job, task, rows = load_tarpass_results(db, user_id=user_id, job_id=row.postprocessing_job_id)
    if file_sha256(resolve_job_artifact(job, task.output_payload["results_json"])) != row.artifact_hash:
        raise HTTPException(409, "Candidate set source artifact changed")
    by_id = {r["molecule_id"]: r for r in rows}
    return row, job, task, [by_id[key] for key in row.molecule_ids]


@router.post("/{session_id}/optimization-drafts")
@read_errors
def optimization_draft(session_id: uuid.UUID, request: OptimizationDraftRequest,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = service.owned_session(db, session_id, user.id, lock=True)
    body_hash = service.digest(request.model_dump(mode="json"))
    previous = db.get(WorkflowCommand, request.command_id)
    if previous is not None:
        if previous.owner_user_id != user.id or previous.target_id != session.id or previous.request_hash != body_hash or previous.source != "card":
            raise WorkflowError("IDEMPOTENCY_KEY_REUSED", "Command ID is already bound to different content", 409)
        return previous.response
    service.reconcile_session(db, session)
    from backend.agent.research_safety import require_task
    require_task(db, session.research_task_id, user.id)
    if request.expected_version != session.input_revision:
        raise WorkflowError("INPUT_CHANGED", f"Draft version changed; current version is {session.input_revision}", 409)
    from backend.services.optimization_drafts import derive_optimization_draft
    try:
        result = derive_optimization_draft(db, session, request)
    except BaseException:
        db.rollback()
        raise
    result = {**result, "command_id": str(request.command_id), "version": session.input_revision}
    db.add(WorkflowCommand(id=request.command_id, owner_user_id=user.id, target_id=session.id,
                           request_hash=body_hash, source="card", response=result))
    db.commit()
    return result


@router.post("/{session_id}/optimization-drafts/approve-pose")
@read_errors
def approve_optimization_pose(session_id: uuid.UUID, request: OptimizationPoseApprovalRequest,
                              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = service.owned_session(db, session_id, user.id, lock=True)
    from backend.agent.research_safety import require_task
    require_task(db, session.research_task_id, user.id)
    body_hash = service.digest(request.model_dump(mode="json"))
    previous = db.get(WorkflowCommand, request.command_id)
    if previous is not None:
        if previous.owner_user_id != user.id or previous.target_id != session.id or previous.request_hash != body_hash or previous.source != "card":
            raise WorkflowError("IDEMPOTENCY_KEY_REUSED", "Command ID is already bound to different content", 409)
        return previous.response
    if request.expected_version != session.input_revision:
        raise WorkflowError("INPUT_CHANGED", f"Draft version changed; current version is {session.input_revision}", 409)
    if not session.assets.get("protein_context_id"):
        raise WorkflowError("PROTEIN_CONTEXT_REQUIRED", "Prepare a Protein Context before running TarPass", 409)
    from backend.services.optimization_drafts import resolve_pose_approval
    from backend.services.jobs import create_postprocessing_job
    try:
        contract = resolve_pose_approval(db, session, request)
        job, task, row = contract["job"], contract["task"], contract["row"]
        molecule_id, pose = contract["molecule_id"], contract["pose"]
        pose_source_job_id = contract["pose_source_job_id"]
        seed, effective_postprocessing = contract["seed"], contract["effective_postprocessing"]
        post = create_postprocessing_job(db, owner_user_id=user.id, params={
            "postprocessing": effective_postprocessing,
            "job_name": f"Pose preparation {molecule_id}",
        })
        post.params = {**(post.params or {}), "pose_approval": {
            "protocol_version": effective_postprocessing["protocol_version"],
            "approval_hash": contract["approval_hash"],
            "target": contract["target"],
            "effective_postprocessing": effective_postprocessing,
        }}
        result = {"status": "submitted", "job_id": str(post.id), "source_job_id": str(job.id),
                  "result_id": str(row.id), "molecule_id": molecule_id, "pose": request.pose,
                  "seed_dataset_id": str(request.seed_dataset_id), "scope": {"kind": "single_molecule", "count": 1},
                  "pose_source_job_id": str(pose_source_job_id),
                  "approval_hash": contract["approval_hash"],
                  "effective_postprocessing": effective_postprocessing,
                  "provenance": {"selected_job_id": str(job.id), "selected_task_id": str(task.id),
                                  "selected_result_id": str(row.id), "selected_molecule_id": molecule_id,
                                  "input_source_job_id": str(pose_source_job_id),
                                  "target": contract["target"]},
                  "requires_approval": False, "message": "TarPass pose preparation was submitted explicitly for the selected molecule."}
        session.assets = {**(session.assets or {}), "optimization_pose_job": {
            "job_id": str(post.id), "source_job_id": str(job.id), "source_result_id": str(row.id),
            "input_source_job_id": str(pose_source_job_id), "molecule_id": molecule_id,
            "seed_dataset_id": str(request.seed_dataset_id), "selected_task_code": task.task_code,
            "approval_hash": contract["approval_hash"], "effective_postprocessing": effective_postprocessing,
            "provenance": result["provenance"],
            "scope": {"kind": "single_molecule", "count": 1}}}
        session.assets.pop("optimization_pose_draft", None)
    except BaseException:
        db.rollback()
        raise
    db.add(WorkflowCommand(id=request.command_id, owner_user_id=user.id, target_id=session.id,
                           request_hash=body_hash, source="card", response=result))
    db.commit()
    return result


@router.get("/{session_id}/candidate-sets/{set_id}")
@read_errors
def get_set(session_id: uuid.UUID, set_id: uuid.UUID, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row, _, task, rows = candidate_rows(db, session_id, set_id, user.id)
    page = rows[offset:offset + limit]
    ids = {str(molecule_id): str(result_id) for result_id, molecule_id in db.execute(
        select(SmallMoleculeResult.id, SmallMoleculeResult.extra['molecule_id'].astext).where(
            SmallMoleculeResult.job_task_id == task.id)).all()}
    page = [{**item, **({'result_id': ids[item['molecule_id']]} if item.get('molecule_id') in ids else {})} for item in page]
    return {"id": str(row.id), "summary": row.summary, "selection": row.selection_spec, "returned_count": len(page), "rows": [project_row(r) for r in page]}


@router.get("/{session_id}/candidate-sets/{set_id}/export")
@read_errors
def export_set(session_id: uuid.UUID, set_id: uuid.UUID, format: str = Query("csv", pattern="^(csv|sdf|json)$"),
               pose: str = Query("docked", pattern="^(original|docked)$"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row, job, task, rows = candidate_rows(db, session_id, set_id, user.id)
    if format == "json":
        proposal = db.get(ActionProposal, row.proposal_id)
        return JSONResponse({"id": str(row.id), "summary": row.summary, "selection": row.selection_spec,
            "molecule_ids": row.molecule_ids, "artifact_hash": row.artifact_hash, "action_hash": proposal.action_hash,
            "input_fingerprint": proposal.input_fingerprint, "execution": proposal.payload},
            headers={"Content-Disposition": f'attachment; filename="candidate-set-{row.id}.json"'})
    if format == "sdf":
        key = pose + "_sdf"
        expected = row.summary.get("artifacts", {}).get(key)
        if expected and file_sha256(resolve_job_artifact(job, task.output_payload[key])) != expected:
            raise HTTPException(409, "Candidate set pose artifact changed")
    from backend.services.result_exports import export_rows
    return export_rows(job, task, rows, pose=pose, format=format)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.services.agent_history import delete_session as remove
    try:
        remove(db, session_id, user.id)
        db.commit()
        return Response(status_code=204)
    except WorkflowError as exc:
        db.rollback()
        raise http_error(exc) from exc


from backend.workflows.contracts import Command, OpenEdit


@router.post("/{session_id}/commands")
@read_errors
async def command(session_id: uuid.UUID, request: Command, http: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.workflows.commands import execute
    session = service.owned_session(db, session_id, user.id, lock=True)
    try:
        if request.operation not in {"cancel","stop_continuation","archive"}:
            from backend.agent.research_safety import assess_existing
            from backend.models import WorkflowRun, ActionProposal, AgentTurn
            workflow = db.get(WorkflowRun,session.active_workflow_id) if session.active_workflow_id else None
            origin = None
            if request.operation == 'approve':
                proposal = db.get(ActionProposal,request.proposal_id)
                if proposal is None or proposal.session_id != session.id:
                    raise WorkflowError('RESOURCE_NOT_FOUND','Proposal not found',404)
                origin = db.get(AgentTurn,proposal.turn_id)
                workflow = db.get(WorkflowRun,proposal.workflow_id) if proposal.workflow_id else None
            from backend.models import ResearchTask
            task = db.get(ResearchTask, session.research_task_id) if session.research_task_id else None
            previous = ((task.task_plan or {}).get('definition') or {'goal': task.goal}) if task else {}
            purpose_changed = request.operation in {'approve_task_plan', 'create_task_plan', 'patch_task_plan'} and any(
                key in request.changes and request.changes[key] != previous.get(key) for key in ('goal', 'completion'))
            await assess_existing(db,user.id,workflow=workflow,session=session,origin=origin,
                action=request.model_dump(mode='json'), force=purpose_changed)
            session = service.owned_session(db,session_id,user.id,lock=True)
        result = execute(db, session, request, source="card", interface_language=page_language(http))
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, {"error_code": "INVALID_INPUT", "message": "Invalid scientific parameters"}) from exc


@router.get("/{session_id}/commands/{command_id}")
@read_errors
def command_status(session_id: uuid.UUID, command_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.models import WorkflowCommand
    service.owned_session(db, session_id, user.id)
    row = db.get(WorkflowCommand, command_id)
    if row is None or row.owner_user_id != user.id or row.target_id != session_id:
        raise HTTPException(404, "Command not found")
    return row.response


@router.post("/{session_id}/edit-sessions")
@read_errors
async def open_editor(session_id: uuid.UUID, request: OpenEdit, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.workflows.editing import open_edit, edit_out
    session = service.owned_session(db, session_id, user.id, lock=True)
    from backend.agent.research_safety import assess_existing
    await assess_existing(db,user.id,session=session,action={'operation':'open_editor','kind':request.kind})
    session = service.owned_session(db,session_id,user.id,lock=True)
    row = open_edit(db, session, request.kind, request.expected_version)
    result = edit_out(row)
    db.commit()
    return result


@router.get("/{session_id}/diagnostics/{turn_id}")
@read_errors
def diagnostics(session_id: uuid.UUID, turn_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.owned_session(db, session_id, user.id)
    turn = db.get(AgentTurn, turn_id)
    if turn is None or turn.session_id != session_id:
        raise HTTPException(404, "Turn not found")
    return {"turn_id": str(turn.id), "attempt": turn.attempt, "diagnostic": turn.audit.get("diagnostic", {}), "attempts": turn.audit.get("attempts", {})}


@router.get("/{session_id}/events")
@read_errors
def events(session_id: uuid.UUID, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from backend.models import WorkflowEvent
    session = service.owned_session(db, session_id, user.id)
    objects = [session.id] + list(db.scalars(select(ActionProposal.workflow_id).where(ActionProposal.session_id == session.id, ActionProposal.workflow_id.is_not(None))))
    return [{"event_id": str(row.id), "object_id": str(row.object_id), "version": row.version, "kind": row.kind,
             "created_at": row.created_at.isoformat(), "payload": row.payload}
            for row in db.scalars(select(WorkflowEvent).where(WorkflowEvent.object_id.in_(objects)).order_by(WorkflowEvent.created_at.desc(), WorkflowEvent.id).limit(limit))]
