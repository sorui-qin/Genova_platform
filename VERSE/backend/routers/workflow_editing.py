import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import update
from pydantic import BaseModel, Field
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import User, AgentSession
from backend.utils import utcnow
from backend.routers.agent_sessions import page_language, read_errors
from backend.workflows.editing import owned_edit, edit_out, save_edit

router = APIRouter(prefix="/workflow-edit-sessions", tags=["workflow-editing"])


class EditSubmission(BaseModel):
    model_config = {"extra": "forbid"}
    changes: dict = Field(default_factory=dict)
    approve_after_save: bool = False


@router.get("/{edit_id}")
@read_errors
def get(edit_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return edit_out(owned_edit(db, edit_id, user.id))


@router.post("/{edit_id}/save")
@read_errors
async def save(edit_id: uuid.UUID, request: EditSubmission, http: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = owned_edit(db, edit_id, user.id)
    try:
        from backend.agent.research_safety import assess_existing
        from backend.services.agent_sessions import owned_session
        session = owned_session(db,row.session_id,user.id)
        await assess_existing(db,user.id,session=session,action={'operation':'save_editor','changes':request.changes})
        row = owned_edit(db,edit_id,user.id)
        result = save_edit(db, row, request.changes, interface_language=page_language(http))
        if request.approve_after_save and result.get('proposal_id'):
            from backend.models import ActionProposal
            from backend.services.agent_sessions import approve_proposal
            proposal = db.get(ActionProposal, uuid.UUID(result['proposal_id']))
            approve_proposal(db, session, proposal.id, proposal.action_hash)
            result = {**result, 'approved': True}
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, {"error_code": "INVALID_STRUCTURE_EDIT", "message": str(exc)[:300]}) from exc


@router.post("/{edit_id}/cancel")
@read_errors
def cancel(edit_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = owned_edit(db, edit_id, user.id)
    if row.status == "open":
        row.status = "canceled"
        db.execute(update(AgentSession).where(AgentSession.id == row.session_id).values(last_user_activity_at=utcnow()))
    result = edit_out(row)
    db.commit()
    return result


@router.patch("/{edit_id}/draft")
@read_errors
def save_draft(edit_id: uuid.UUID, request: EditSubmission, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    import json
    row = owned_edit(db, edit_id, user.id)
    if row.status != "open":
        raise HTTPException(409, "Editor is closed")
    if len(json.dumps(request.changes).encode()) > 1_000_000:
        raise HTTPException(413, "Editor draft is too large")
    row.state = {**row.state, "draft": request.changes}
    db.execute(update(AgentSession).where(AgentSession.id == row.session_id).values(last_user_activity_at=utcnow()))
    db.commit()
    return {"status": "saved", "id": str(row.id)}
