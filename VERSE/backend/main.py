import asyncio
import time
from uuid import UUID

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

from backend.builtin_datasets import seed_builtin_datasets
from backend.config import settings
from backend.agent.user_settings import router as agent_settings_router
from backend.agent.chatgpt_oauth import router as chatgpt_oauth_router
from backend.agent.knowledge import models as knowledge_models  # register tables before create_all
from backend.db import Base, SessionLocal, engine, get_db
from backend.deps import _resolve_guest_user, get_current_user
from backend.routers import agent_sessions, admin, agent, auth, datasets, jobs, prepared_receptors, protein_contexts, results, postprocessing, structures, help
from backend.models import User
from backend.planning_schema import validate_planning_schema
from backend.realtime import get_async_redis_client, get_user_channel
from backend.security import access_matches_user, decode_access_token, hash_token
from backend.utils import utcnow


app = FastAPI(title=settings.app_name)


from backend.services.jobs import DomainValidationError


@app.exception_handler(DomainValidationError)
async def domain_error(request, exc):
    return JSONResponse(status_code=exc.http_status, content={'detail': {'error_code': exc.code, 'message': exc.message}})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path == settings.api_prefix + "/auth/password":
        return JSONResponse(status_code=422, content={"detail": "PASSWORD_INVALID_INPUT"})
    if request.url.path == settings.api_prefix + "/agent/settings/proxy":
        return JSONResponse(status_code=422, content={"detail": {
            "error_code": "AGENT_PROXY_INVALID", "error_source": "configuration", "recovery_action": "reconfigure_agent",
            "message": "Use an unauthenticated HTTP(S) proxy address or null for direct connections", "status_code": 422}})
    if request.url.path.startswith(settings.api_prefix + "/agent/settings"):
        return JSONResponse(status_code=422, content={"detail": {
            "error_code": "AGENT_INVALID_SETTINGS", "error_source": "configuration", "recovery_action": "reconfigure_agent", "message": "Check the API base URL, model, reasoning settings and key format", "status_code": 422}})
    return await request_validation_exception_handler(request, exc)


def _ensure_user_admin_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"))


def _ensure_guest_user_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_guest BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS guest_code_hash VARCHAR(128) NULL"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS guest_code_expires_at TIMESTAMPTZ NULL"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS guest_code_last_used_at TIMESTAMPTZ NULL"))


def _ensure_job_soft_delete_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("jobs"):
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL"))


def _ensure_workflow_refinement_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("workflow_runs"):
        return

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS "
            "refinement_state VARCHAR(32) NOT NULL DEFAULT 'awaiting_feedback'"
        ))
        conn.execute(text(
            "UPDATE workflow_runs SET refinement_state = CASE "
            "WHEN status = 'approved' THEN 'approved' "
            "WHEN status = 'running' THEN 'running' "
            "WHEN status IN ('succeeded', 'failed', 'canceled', 'superseded') THEN 'closed' "
            "ELSE refinement_state END "
            "WHERE status <> 'awaiting_approval'"
        ))


def _ensure_durable_planning_schema(bind=None) -> None:
    schema_engine = bind or engine
    inspector = inspect(schema_engine)
    if not all(inspector.has_table(name) for name in ("users", "datasets", "workflow_runs")):
        return

    if inspector.has_table("workflow_planning_requests"):
        validate_planning_schema(schema_engine)
        return

    with schema_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS workflow_planning_requests (
                id UUID PRIMARY KEY,
                owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                client_request_id UUID NOT NULL,
                message TEXT NOT NULL,
                protein_context_id UUID NOT NULL REFERENCES datasets(id),
                status VARCHAR(32) NOT NULL DEFAULT 'planning'
                    CONSTRAINT ck_workflow_planning_status
                    CHECK (status IN ('planning', 'interrupted', 'failed', 'linked')),
                attempt INTEGER NOT NULL DEFAULT 1
                    CONSTRAINT ck_workflow_planning_attempt CHECK (attempt >= 1 AND attempt <= 1000),
                workflow_id UUID NULL UNIQUE REFERENCES workflow_runs(id) ON DELETE RESTRICT,
                last_error VARCHAR(128) NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CONSTRAINT uq_workflow_planning_owner_client_request
                    UNIQUE (owner_user_id, client_request_id),
                CONSTRAINT ck_workflow_planning_link
                    CHECK ((status = 'linked') = (workflow_id IS NOT NULL))
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_workflow_planning_owner_updated "
            "ON workflow_planning_requests (owner_user_id, updated_at)"
        ))
    validate_planning_schema(schema_engine)


@app.on_event("startup")
async def startup_event() -> None:
    from backend.agent.runner import Budget
    from dataclasses import asdict
    import logging
    logging.getLogger("backend-agent").warning("Agent effective budget: %s", asdict(Budget()))
    from pathlib import Path
    if inspect(engine).has_table("agent_research_tasks"):
        with engine.begin() as conn:
            conn.execute(text((Path(__file__).parent / 'migrations/20261104_task_plans.sql').read_text()))
    if inspect(engine).has_table("users"):
        with engine.begin() as conn:
            conn.execute(text((Path(__file__).parent / "migrations/20261125_job_submissions.sql").read_text()))
            conn.execute(text((Path(__file__).parent / "migrations/20261125_dataset_upload_attempts.sql").read_text()))
            for statement in (Path(__file__).parent / 'migrations/20261125_agent_work_preferences.sql').read_text().split(';'):
                if statement.strip():
                    conn.execute(text(statement))
    if not settings.auto_create_tables:
        validate_planning_schema(engine)
        if settings.knowledge_backend in {"postgres", "memory"}:
            from backend.agent.knowledge.ingestion_service import ingest_bundled_protocols
            await asyncio.to_thread(ingest_bundled_protocols, agent._get_knowledge())
        return
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS "
                "action_proposal_id UUID CONSTRAINT fk_workflow_action_proposal "
                "REFERENCES agent_action_proposals(id)"
            ))
    from pathlib import Path
    if inspect(engine).has_table("agent_llm_profiles"):
        migration = Path(__file__).parent / "migrations/20261014_agent_chatgpt_oauth.sql"
        with engine.begin() as conn:
            for statement in migration.read_text().split(";"):
                if statement.strip() and statement.strip() not in {"BEGIN", "COMMIT"}:
                    conn.execute(text(statement))
    _ensure_user_admin_schema()
    if inspect(engine).has_table("agent_llm_profiles"):
        from pathlib import Path
        migration = Path(__file__).parent / "migrations/20261014_agent_reasoning.sql"
        with engine.begin() as conn:
            for statement in migration.read_text().split(";"):
                if statement.strip() and statement.strip() not in {"BEGIN", "COMMIT"}:
                    conn.execute(text(statement))
    _ensure_guest_user_schema()
    with engine.begin() as conn:
        conn.execute(text((Path(__file__).parent / "migrations/20261028_agent_context_window.sql").read_text()))
        conn.execute(text((Path(__file__).parent / "migrations/20261029_research_safety.sql").read_text()))
        conn.execute(text((Path(__file__).parent / "migrations/20261103_workflow_preferences.sql").read_text()))
    _ensure_job_soft_delete_schema()
    _ensure_workflow_refinement_schema()
    _ensure_durable_planning_schema()
    from backend.retention import initialize_schema
    initialize_schema()
    if settings.knowledge_backend in {"postgres", "memory"}:
        from backend.agent.knowledge.ingestion_service import ingest_bundled_protocols

        await asyncio.to_thread(ingest_bundled_protocols, agent._get_knowledge())
    with SessionLocal() as db:
        from backend.services.workflows import reconcile_stale_planning_requests

        reconcile_stale_planning_requests(db, active_requests=set())
        db.commit()
        seed_builtin_datasets(db)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get(settings.api_prefix + "/platform/retention")
def data_retention_policy(db=Depends(get_db), user=Depends(get_current_user)):
    from backend.retention import policy_status
    return policy_status(db)


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    while True:
        await websocket.receive()


BEARER_WS_PROTOCOL = "genova.bearer"
GUEST_WS_PROTOCOL = "genova.guest"


def _extract_ws_token(websocket: WebSocket) -> str:
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    if len(protocols) == 2 and protocols[0] == BEARER_WS_PROTOCOL:
        return protocols[1]

    auth_header = str(websocket.headers.get("authorization", "")).strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _ws_guest_code(websocket: WebSocket) -> str:
    # Browsers cannot set headers on a WebSocket, so the code comes as the second subprotocol and stays out of URLs and logs.
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    return protocols[1] if len(protocols) == 2 and protocols[0] == GUEST_WS_PROTOCOL else ""


def _get_ws_user(websocket: WebSocket) -> User | None:
    raw_token = _extract_ws_token(websocket)
    if not raw_token:
        guest_code = _ws_guest_code(websocket)
        if not guest_code:
            return None
        with SessionLocal() as db:
            return _resolve_guest_user(db, guest_code)

    try:
        payload = decode_access_token(raw_token)
        user_id = UUID(str(payload.get("sub", "")))
    except Exception:
        return None

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not access_matches_user(payload, user):
            return None
        return user


@app.websocket("/ws/subscribe")
async def subscribe_ws(websocket: WebSocket) -> None:
    websocket.scope["query_string"] = b""
    user = _get_ws_user(websocket)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    protocol = protocols[0] if len(protocols) == 2 and protocols[0] in {BEARER_WS_PROTOCOL, GUEST_WS_PROTOCOL} else None
    await websocket.accept(subprotocol=protocol)
    redis_client = get_async_redis_client()
    pubsub = redis_client.pubsub()
    channel = get_user_channel(user.id)
    disconnect_task = asyncio.create_task(_wait_for_disconnect(websocket))
    checked_at = time.monotonic()

    def authorized():
        token = _extract_ws_token(websocket)
        if token:
            try:
                payload = decode_access_token(token)
            except Exception:
                return False
        with SessionLocal() as db:
            current = db.get(User, user.id)
            if token:
                return access_matches_user(payload, current)
            return bool(current and current.is_active and current.is_guest
                and current.guest_code_hash == hash_token(_ws_guest_code(websocket))
                and (current.guest_code_expires_at is None or current.guest_code_expires_at > utcnow()))

    try:
        await pubsub.subscribe(channel)
        await websocket.send_json(
            {
                "event": "ws.subscribed",
                "object": {
                    "user_id": str(user.id),
                },
            }
        )

        while True:
            if disconnect_task.done():
                break

            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message or time.monotonic() - checked_at >= 5:
                if not await asyncio.to_thread(authorized):
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break
                checked_at = time.monotonic()
            if not message:
                continue

            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="ignore")
            if isinstance(data, str) and data:
                await websocket.send_text(data)
    except WebSocketDisconnect:
        pass
    finally:
        disconnect_task.cancel()
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        await pubsub.aclose()
        await redis_client.aclose()


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(datasets.router, prefix=settings.api_prefix)
app.include_router(protein_contexts.router, prefix=settings.api_prefix)
app.include_router(prepared_receptors.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(results.router, prefix=settings.api_prefix)
app.include_router(postprocessing.router, prefix=settings.api_prefix)
app.include_router(agent.router, prefix=settings.api_prefix)
app.include_router(agent_sessions.router, prefix=settings.api_prefix)
app.include_router(agent_settings_router, prefix=settings.api_prefix)
app.include_router(chatgpt_oauth_router, prefix=settings.api_prefix)
app.include_router(structures.router, prefix=settings.api_prefix)
app.include_router(help.router, prefix=settings.api_prefix)

from backend.routers import workflow_editing
app.include_router(workflow_editing.router, prefix=settings.api_prefix)
