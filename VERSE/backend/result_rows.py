from genova_runtime.artifact_json import read_json
import csv
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, defer

from backend.models import JobTask, SmallMoleculeResult
from backend.utils import utcnow

DEDUP_SMALL_MOLECULE_TASK_CODES = {"molecule_generation", "property_optimization"}


def read_tarpass_rows(result_payload):
    rows = read_json(Path(result_payload['results_json']))
    return [{'smiles': row['smiles'], 'extra': row} for row in rows]


def canonicalize_smiles(smiles: str) -> str:
    return smiles.strip()


def build_small_molecule_result_values(
    *,
    job_id: uuid.UUID,
    job_task_id: uuid.UUID,
    task_code: str,
    rows: list[dict[str, Any]],
    existing_smiles_canonical: set[str] | None = None,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    now = utcnow()
    should_dedup = task_code in DEDUP_SMALL_MOLECULE_TASK_CODES
    seen_smiles_canonical = set(existing_smiles_canonical or set()) if should_dedup else set()

    for row in rows:
        smiles = str(row.get("smiles", "")).strip()
        if not smiles and task_code != 'tarpass':
            continue
        smiles_canonical = canonicalize_smiles(str(row.get("smiles_canonical", smiles)))
        if should_dedup:
            if smiles_canonical in seen_smiles_canonical:
                continue
            seen_smiles_canonical.add(smiles_canonical)
        values.append(
            {
                "id": uuid.uuid4(),
                "job_id": job_id,
                "job_task_id": job_task_id,
                "task_code": task_code,
                "smiles": smiles,
                "smiles_canonical": smiles_canonical,
                "extra": dict(row.get("extra", {})),
                "created_at": now,
                "updated_at": now,
            }
        )

    return values


def upsert_small_molecule_rows(
    db: Session,
    *,
    job_id: uuid.UUID,
    job_task_id: uuid.UUID,
    task_code: str,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0

    existing_smiles_canonical: set[str] | None = None
    if task_code in DEDUP_SMALL_MOLECULE_TASK_CODES:
        existing_smiles_canonical = set(
            db.scalars(
                select(SmallMoleculeResult.smiles_canonical).where(SmallMoleculeResult.job_task_id == job_task_id)
            ).all()
        )

    values = build_small_molecule_result_values(
        job_id=job_id,
        job_task_id=job_task_id,
        task_code=task_code,
        rows=rows,
        existing_smiles_canonical=existing_smiles_canonical,
    )
    if not values:
        return 0

    for start in range(0, len(values), 500):
        db.execute(insert(SmallMoleculeResult).values(values[start:start + 500]))
    return len(values)


def ensure_tarpass_rows(db, task):
    if (task.output_payload or {}).get('result_index_version') == 1:
        return
    task = db.scalar(select(JobTask).where(JobTask.id == task.id).with_for_update().execution_options(populate_existing=True))
    if task.output_payload.get('result_index_version') == 1:
        return
    existing = set(db.scalars(select(SmallMoleculeResult.extra['molecule_id'].astext)
                             .where(SmallMoleculeResult.job_task_id == task.id)).all())
    rows = [row for row in read_tarpass_rows(task.output_payload) if row['extra']['molecule_id'] not in existing]
    upsert_small_molecule_rows(db, job_id=task.job_id, job_task_id=task.id, task_code='tarpass', rows=rows)
    task.output_payload = {**task.output_payload, 'result_index_version': 1}
    db.commit()


def read_molecule_generation_rows(result_payload: dict[str, Any]) -> list[dict[str, Any]]:
    output_csv_raw = str(result_payload.get("output_csv", "")).strip()
    source_path = Path(output_csv_raw) if output_csv_raw else None
    rows: list[dict[str, Any]] = []
    if source_path is None or not source_path.exists():
        return rows

    with source_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        field_names = reader.fieldnames or []
        lower_map = {field.lower(): field for field in field_names}
        smiles_key = lower_map.get("smiles")

        for row in reader:
            smiles = str(row.get(smiles_key, "")).strip() if smiles_key else ""
            if not smiles:
                continue

            extra = {
                "source": "molecule_generation_output_csv",
                "engine": result_payload.get("engine"),
                "protein_path": row.get("protein_path") or result_payload.get("protein_path"),
                "raw": row,
            }
            rows.append({"smiles": smiles, "extra": extra})
    return rows


def read_property_optimization_rows(result_payload: dict[str, Any]) -> list[dict[str, Any]]:
    output_csv_raw = str(result_payload.get("output_csv", "")).strip()
    output_csv = Path(output_csv_raw) if output_csv_raw else None
    rows: list[dict[str, Any]] = []
    if output_csv is None or not output_csv.exists():
        return rows

    def _as_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except Exception:
            return None

    with output_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            smiles = str(row.get("smiles", "")).strip()
            if not smiles:
                continue
            rows.append(
                {
                    "smiles": smiles,
                    "extra": {
                        "source": "property_optimization_output_csv",
                        "fitness": _as_float(row.get("fitness")),
                        "qed": _as_float(row.get("qed")),
                        "sa": _as_float(row.get("sa")),
                        "logp": _as_float(row.get("logp")),
                        "generation": row.get("generation"),
                        "raw": row,
                        **({
                            "engine": "epso", "rank": int(row['rank']),
                            "generation": int(row['generation']),
                            "metrics": {key: _as_float(row[key]) for key in
                                        ('qed', 'sa', 'mw', 'logp', 'lipinski', 'hba', 'hbd', 'heavy_atom_count', 'similarity',
                                         'gnina_affinity', 'gnina_affinity_improvement')
                                        if key in row},
                        } if result_payload.get('engine') == 'epso' else {}),
                    },
                }
            )
    return rows

RESULT_ROW_READERS = {
    "tarpass": read_tarpass_rows,
    "molecule_generation": read_molecule_generation_rows,
    "property_optimization": read_property_optimization_rows,
}


def backfill_small_molecule_results_for_job(
    db: Session,
    *,
    job_id: uuid.UUID,
    task_code: str | None = None,
) -> int:
    supported_task_codes = {task_code} if task_code else set(RESULT_ROW_READERS.keys())
    supported_task_codes &= set(RESULT_ROW_READERS.keys())
    if not supported_task_codes:
        return 0

    tasks = db.scalars(
        select(JobTask).where(
            JobTask.job_id == job_id,
            JobTask.status == "succeeded",
            JobTask.task_code.in_(sorted(supported_task_codes)),
            ~select(SmallMoleculeResult.id).where(SmallMoleculeResult.job_task_id == JobTask.id).exists(),
        )
        .options(defer(JobTask.input_payload))
    ).all()

    inserted_total = 0
    for task in tasks:
        reader = RESULT_ROW_READERS.get(task.task_code)
        if reader is None:
            continue
        rows = reader(task.output_payload or {})
        inserted = upsert_small_molecule_rows(
            db,
            job_id=task.job_id,
            job_task_id=task.id,
            task_code=task.task_code,
            rows=rows,
        )
        if inserted:
            payload = dict(task.output_payload or {})
            payload["inserted_rows"] = inserted
            task.output_payload = payload
            task.updated_at = utcnow()
            inserted_total += inserted

    return inserted_total
