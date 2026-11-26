import uuid
from sqlalchemy import select
from backend.models import EditSession, DeleteEditSpec, DatasetFile
from backend.services import agent_sessions as sessions
from backend.services.jobs import validate_protein_context_for_generation, get_owned_dataset
from backend.services.workflows import WorkflowError
from backend.workflows.commands import execute, design
from backend.workflows.contracts import Command
from backend.workflows.bindings import validate_resources
from genova_runtime.pdb2pqr_compat import file_sha256
from backend.utils import utcnow


def open_edit(db, session, kind, expected_version):
    if session.input_revision != expected_version:
        raise WorkflowError("INPUT_CHANGED", "Refresh the current draft", 409)
    draft = design(db, session)
    bound = sessions.fingerprint(db, session)
    existing = db.scalar(select(EditSession).where(
        EditSession.session_id == session.id,
        EditSession.owner_user_id == session.owner_user_id,
        EditSession.kind == kind,
        EditSession.expected_revision == expected_version,
        EditSession.status == "open",
    ).order_by(EditSession.created_at.desc(), EditSession.id.desc()))
    if existing is not None and existing.inputs == bound:
        return existing
    state = {"assets": draft.assets, "values": draft.values}
    if session.active_workflow_id:
        from backend.services.workflows import owned_workflow
        state["workflow_plan"] = owned_workflow(db, session.active_workflow_id, session.owner_user_id).plan_json
    if draft.assets.get("protein_context_id"):
        context = get_owned_dataset(db, uuid.UUID(draft.assets["protein_context_id"]), session.owner_user_id)
        state = {**state, "context": context.meta}
    if kind == "delete" and not draft.assets.get("protein_context_id"):
        raise WorkflowError("PROTEIN_CONTEXT_REQUIRED", "Prepare a Context first", 422)
    if kind == "delete" and draft.values.get("delete_edit_spec_id"):
        spec = db.get(DeleteEditSpec, uuid.UUID(draft.values["delete_edit_spec_id"]))
        if spec is None or spec.owner_user_id != session.owner_user_id or not any(
            file["id"] == spec.specification["reference_file_id"] and file["sha256"] == spec.reference_sha256
            for resource in bound["resources"] for file in resource["files"]
        ):
            raise WorkflowError("INPUT_CHANGED", "DELETE reference changed; select a new edit", 409)
        state["draft"] = spec.specification["edit"]
    row = EditSession(owner_user_id=session.owner_user_id, session_id=session.id, kind=kind,
        expected_revision=expected_version, inputs=bound, state=state)
    session.last_user_activity_at = utcnow()
    db.add(row)
    db.flush()
    return row


def owned_edit(db, edit_id, user_id):
    row = db.scalar(select(EditSession).where(EditSession.id == edit_id, EditSession.owner_user_id == user_id).with_for_update())
    if row is None:
        raise WorkflowError("RESOURCE_NOT_FOUND", "Editor session not found", 404)
    return row


def edit_out(row):
    return {"id": str(row.id), "session_id": str(row.session_id), "kind": row.kind,
        "expected_version": row.expected_revision, "status": row.status, "state": row.state, "result": row.result,
        "return_path": "/agent", "allowed_fields": (["structure_selection"] if row.kind == "protein" else ["delete_edit"] if row.kind == "delete" else ["workflow_draft"] if row.kind == "workflow" else ["selection"])}


def save_edit(db, row, changes, *, interface_language=None):
    session = sessions.owned_session(db, row.session_id, row.owner_user_id, lock=True)
    digest = sessions.digest(changes)
    if row.status == "saved":
        if row.result["submission_hash"] != digest:
            raise WorkflowError("IDEMPOTENCY_KEY_REUSED", "Editor already saved different changes", 409)
        return row.result
    if row.status != "open" or session.input_revision != row.expected_revision:
        raise WorkflowError("INPUT_CHANGED", "Editor is closed or the draft changed; reopen it", 409)
    if row.kind in {"workflow", "selection"}:
        raise WorkflowError("COMMAND_REQUIRED", "Save workflow and selection drafts through versioned commands", 422)
    validate_resources(db, row.owner_user_id, row.inputs["resources"])
    if row.kind == 'protein' and changes.keys() & {'prepared_spec', 'site'}:
        result = execute(db, session, Command(command_id=row.id, expected_version=row.expected_revision,
            operation='select_context', changes=changes), source='visual_editor', interaction_id=row.id, interface_language=interface_language)
        operation = 'save_site' if 'site' in changes else 'prepare'
        if (operation == 'prepare' and session.assets.get('prepared_receptor_id')
                and get_owned_dataset(db, uuid.UUID(session.assets['prepared_receptor_id']), row.owner_user_id).status == 'ready'):
            session.phase = 'awaiting_site'
            result['reused_preparation'] = True
        else:
            submitted = execute(db, session, Command(command_id=uuid.uuid5(row.id, operation), expected_version=session.input_revision,
                operation=operation, changes=changes if operation == 'save_site' else {}), source='visual_editor', interaction_id=row.id, interface_language=interface_language)
            result = {**result, **submitted}
        if operation == 'save_site':
            result['reused_preparation'] = True
    elif row.kind == "protein":
        structural = {field["requirement"] for field in sessions.pending_clarification_fields(db, session) if field["type"] == "structure"}
        remaining = [item for item in session.pending_requirements or [] if item not in structural]
        from backend.agent.input_validation import validate_structure_input
        from backend.services.protein_contexts import _protein_file_or_400, _validate_uploaded_ligand
        assets = row.state["assets"]
        source_id = assets.get("protein_dataset_id") or row.state["context"]["protein_dataset_id"]
        file_id = changes.get("protein_file_id") or row.state.get("context", {}).get("protein_file_id")
        file = _protein_file_or_400(db, uuid.UUID(source_id), file_id)
        validated = validate_structure_input(file.storage_path, "context", changes)
        _validate_uploaded_ligand(db, row.owner_user_id, validated)
        values = {**changes, **validated, "protein_file_id": str(file.id)}
        result = execute(db, session, Command(command_id=row.id, expected_version=row.expected_revision,
            operation="select_context", changes=values), source="visual_editor", interaction_id=row.id, interface_language=interface_language)
        if not session.assets.get("protein_context_id"):
            proposal_command = Command(command_id=uuid.uuid5(row.id, "prepare"), expected_version=session.input_revision, operation="prepare")
            proposal = execute(db, session, proposal_command, source="visual_editor", interaction_id=row.id, interface_language=interface_language)
            result = {**result, "proposal_id": proposal.get("proposal_id")}
        session.pending_requirements = remaining
        result = {**result, "missing_requirements": remaining}
    else:
        from genova_runtime.delete_edits import DeleteEditValidationError, read_reference, validate_delete_edit
        from backend.agent.schemas import DeleteEditConfig
        edit = DeleteEditConfig.model_validate(changes).model_dump(mode="json", exclude_none=True)
        if edit.get("edit_spec_id"):
            raise WorkflowError("INVALID_INPUT", "An editor must submit an actual edit", 422)
        context_id = row.state["assets"]["protein_context_id"]
        context = validate_protein_context_for_generation(db, row.owner_user_id, uuid.UUID(context_id))
        from backend.services.jobs import DomainValidationError, delete_reference_path
        try:
            reference = delete_reference_path(context)
            metadata = validate_delete_edit(reference, edit)
        except DeleteEditValidationError as exc:
            raise WorkflowError(exc.code, str(exc), 422) from exc
        except DomainValidationError as exc:
            raise WorkflowError(exc.code, exc.message, exc.http_status) from exc
        except ValueError as exc:
            raise WorkflowError("INVALID_INPUT", str(exc), 422) from exc
        reference_file = db.scalar(select(DatasetFile).where(DatasetFile.storage_path == reference))
        if reference_file is None:
            raise WorkflowError("INPUT_UNAVAILABLE", "Prepared reference file is not registered", 409)
        specification = {"edit": edit, **metadata, "reference_file_id": str(reference_file.id),
            "reference_sha256": file_sha256(reference), "mapping_version": "rdkit-removeHs-v1",
            "deleted_atom_indices": sorted(set(range(read_reference(reference).GetNumAtoms())) - set(metadata["retained_atom_indices"])),
            "input_version": row.expected_revision, "validation": "passed"}
        current_id = row.state["values"].get("delete_edit_spec_id")
        spec = db.get(DeleteEditSpec, uuid.UUID(current_id)) if current_id else None
        if spec is None or spec.reference_sha256 != specification["reference_sha256"] or spec.specification["edit"] != edit:
            spec = DeleteEditSpec(owner_user_id=row.owner_user_id, reference_sha256=specification["reference_sha256"],
                spec_hash=sessions.digest(specification), specification=specification)
            db.add(spec)
            db.flush()
        values = {"delete_edit_spec_id": str(spec.id)}
        result = execute(db, session, Command(command_id=row.id, expected_version=row.expected_revision,
            operation="select_context", changes=values), source="visual_editor", interaction_id=row.id, interface_language=interface_language)
        result = {**result, "edit_spec_id": str(spec.id), "mode": edit["mode"], "summary": metadata}
        plan = row.state.get("workflow_plan")
        if plan and plan["generator"] == "delete":
            plan = {**plan, "generation": {**plan["generation"], "edit": {"mode": edit["mode"], "edit_spec_id": str(spec.id)}}}
            saved = execute(db, session, Command(command_id=uuid.uuid5(row.id, "delete-plan"), expected_version=session.input_revision,
                operation="create_workflow", changes=plan), source="visual_editor", interaction_id=row.id, interface_language=interface_language)
            result = {**result, "proposal_id": saved["proposal_id"]}
    row.status = "saved"
    row.result = {**result, "submission_hash": digest}
    return row.result
