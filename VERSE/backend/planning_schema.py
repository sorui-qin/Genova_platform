"""Startup audit for the durable-planning database contract."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import inspect


PLANNING_SCHEMA_VALIDATION_FAILED = "PLANNING_SCHEMA_VALIDATION_FAILED"
PLANNING_TABLE = "workflow_planning_requests"
_REQUIRED_COLUMNS = {
    "id",
    "owner_user_id",
    "client_request_id",
    "message",
    "protein_context_id",
    "status",
    "attempt",
    "workflow_id",
    "last_error",
    "created_at",
    "updated_at",
}


def _check_text(value: str) -> str:
    return re.sub(r"[\s\"()]", "", value.lower())


def _string_literals(value: str) -> set[str]:
    return {item.replace("''", "'") for item in re.findall(r"'((?:''|[^'])*)'", value.lower())}


def _has_foreign_key(
    foreign_keys: list[dict[str, Any]],
    *,
    column: str,
    table: str,
    referred_column: str = "id",
    ondelete: str | None = None,
) -> bool:
    for key in foreign_keys:
        if key.get("constrained_columns") != [column]:
            continue
        if key.get("referred_table") != table or key.get("referred_columns") != [referred_column]:
            continue
        actual_delete = str((key.get("options") or {}).get("ondelete") or "").upper()
        if ondelete is None or actual_delete == ondelete:
            return True
    return False


def planning_schema_issues(bind) -> list[str]:
    """Return stable, sorted descriptions of every missing planning boundary."""
    inspector = inspect(bind)
    dialect_name = inspector.bind.dialect.name
    if not inspector.has_table(PLANNING_TABLE):
        return [f"table:{PLANNING_TABLE}"]

    issues: list[str] = []
    columns = {column["name"]: column for column in inspector.get_columns(PLANNING_TABLE)}
    for name in sorted(_REQUIRED_COLUMNS - columns.keys()):
        issues.append(f"column:{name}")

    for name in sorted({
        "owner_user_id",
        "client_request_id",
        "message",
        "protein_context_id",
        "status",
        "attempt",
        "created_at",
        "updated_at",
    } & columns.keys()):
        if columns[name].get("nullable") is not False:
            issues.append(f"not_null:{name}")

    primary_key = inspector.get_pk_constraint(PLANNING_TABLE)
    if primary_key.get("constrained_columns") != ["id"]:
        issues.append("primary_key:id")

    unique_constraints = inspector.get_unique_constraints(PLANNING_TABLE)
    if not any(
        item.get("column_names") == ["owner_user_id", "client_request_id"]
        and (dialect_name == "sqlite" or item.get("name") == "uq_workflow_planning_owner_client_request")
        for item in unique_constraints
    ):
        issues.append("unique:owner_user_id,client_request_id")
    if not any(item.get("column_names") == ["workflow_id"] for item in unique_constraints):
        issues.append("unique:workflow_id")

    reflected_checks = inspector.get_check_constraints(PLANNING_TABLE)
    checks = {item.get("name"): _check_text(str(item.get("sqltext") or ""))
              for item in reflected_checks if item.get("name")}
    if dialect_name == "sqlite":
        # SQLite reflection drops these names; production PostgreSQL still requires them.
        for item in reflected_checks:
            if item.get("name"):
                continue
            expression = _check_text(str(item.get("sqltext") or ""))
            if "statusin" in expression:
                checks.setdefault("ck_workflow_planning_status", expression)
            elif "workflow_idisnotnull" in expression:
                checks.setdefault("ck_workflow_planning_link", expression)
    status_check = checks.get("ck_workflow_planning_status", "")
    if "status" not in status_check or _string_literals(status_check) != {"planning", "interrupted", "failed", "linked"}:
        issues.append("check:ck_workflow_planning_status")
    attempt_check = checks.get("ck_workflow_planning_attempt", "")
    if "attempt>=1" not in attempt_check or "attempt<=1000" not in attempt_check:
        issues.append("check:ck_workflow_planning_attempt")
    link_check = checks.get("ck_workflow_planning_link", "")
    if (
        not all(value in link_check for value in ("status", "workflow_idisnotnull"))
        or _string_literals(link_check) != {"linked"}
    ):
        issues.append("check:ck_workflow_planning_link")

    foreign_keys = inspector.get_foreign_keys(PLANNING_TABLE)
    if not _has_foreign_key(
        foreign_keys,
        column="owner_user_id",
        table="users",
        ondelete=None if dialect_name == "sqlite" else "CASCADE",
    ):
        issues.append("foreign_key:owner_user_id->users.id ON DELETE CASCADE")
    if not _has_foreign_key(foreign_keys, column="protein_context_id", table="datasets"):
        issues.append("foreign_key:protein_context_id->datasets.id")
    if not _has_foreign_key(
        foreign_keys,
        column="workflow_id",
        table="workflow_runs",
        ondelete=None if dialect_name == "sqlite" else "RESTRICT",
    ):
        issues.append("foreign_key:workflow_id->workflow_runs.id ON DELETE RESTRICT")

    indexes = inspector.get_indexes(PLANNING_TABLE)
    if not any(
        item.get("name") == "idx_workflow_planning_owner_updated"
        and item.get("column_names") == ["owner_user_id", "updated_at"]
        for item in indexes
    ):
        issues.append("index:idx_workflow_planning_owner_updated(owner_user_id,updated_at)")
    return sorted(issues)


def validate_planning_schema(bind) -> None:
    issues = planning_schema_issues(bind)
    if issues:
        raise RuntimeError(f"{PLANNING_SCHEMA_VALIDATION_FAILED}: {', '.join(issues)}")
