"""Preview or remove empty Agent sessions after exporting their complete rows."""
import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, delete, exists, func, select
from sqlalchemy.orm import Session

from backend.models import AgentSession, AgentTurn, ActionProposal, CandidateSet


def empty_conditions():
    return [func.btrim(AgentSession.goal) == "", AgentSession.phase == "awaiting_upload",
        AgentSession.input_revision == 0, AgentSession.assets == {}, AgentSession.confirmed_fields == {},
        AgentSession.pending_requirements == [], AgentSession.preparation_job_id.is_(None),
        AgentSession.active_workflow_id.is_(None), AgentSession.last_error.is_(None),
        ~exists(select(AgentTurn.id).where(AgentTurn.session_id == AgentSession.id)),
        ~exists(select(ActionProposal.id).where(ActionProposal.session_id == AgentSession.id)),
        ~exists(select(CandidateSet.id).where(CandidateSet.session_id == AgentSession.id))]


def cleanup(db, *, backup=None):
    query = select(AgentSession).where(*empty_conditions()).order_by(AgentSession.id)
    rows = list(db.scalars(query.with_for_update() if backup else query))
    if backup:
        payload = [{column.name: getattr(row, column.name) for column in AgentSession.__table__.columns} for row in rows]
        # Never replace an earlier backup; the export must exist before DELETE.
        with Path(backup).open("x") as stream:
            os.chmod(backup, 0o600)
            json.dump(payload, stream, default=str, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if rows:
            db.execute(delete(AgentSession).where(AgentSession.id.in_([r.id for r in rows]), *empty_conditions()))
    return [str(row.id) for row in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", help="New JSON export path, required with --apply")
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        parser.error("Set DATABASE_URL explicitly; no application database default is used")
    if args.apply != bool(args.backup):
        parser.error("Use --apply together with --backup; omit both for a read-only preview")
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with Session(engine) as db, db.begin():
            ids = cleanup(db, backup=args.backup if args.apply else None)
        print(json.dumps({"deleted" if args.apply else "would_delete": len(ids), "ids": ids}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
