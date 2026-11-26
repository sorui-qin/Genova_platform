import gzip
from backend.artifact_downloads import artifact_response
import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile
from typing import Annotated, Literal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from starlette.background import BackgroundTask
from starlette.formparsers import MultiPartException, MultiPartParser, parse_options_header
from sqlalchemy import String, and_, case, cast, column, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, aliased, defer

from backend import schemas
from starlette.concurrency import run_in_threadpool

from backend.config import settings
from backend.builtin_datasets import BUILTIN_OWNER_ID, is_builtin
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import DatasetUploadAttempt, AgentSession, Dataset, DatasetFile, Job, JobTask, User, WorkflowPlanningRequest
from backend.services.workflows import ACTIVE_JOB_STATUSES
from backend.structure_contracts import PreparationOptions
from backend.utils import utcnow


router = APIRouter(prefix="/datasets", tags=["datasets"])

MAX_FILENAME_BYTES = 255


class _FilenameError(MultiPartException):
    def __init__(self, code: str, size: int | None = None):
        super().__init__(code)
        self.size = size

    def http_error(self) -> HTTPException:
        if self.size is None:
            return HTTPException(422, self.message)
        return HTTPException(422, {
            "error_code": self.message,
            "actual_bytes": self.size,
            "max_bytes": MAX_FILENAME_BYTES,
        })


def _check_filename(name: str) -> None:
    try:
        size = len(name.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise _FilenameError("FILENAME_INVALID_UTF8") from exc
    if size > MAX_FILENAME_BYTES:
        raise _FilenameError("FILENAME_TOO_LONG", size)
    if "\x00" in name or name in {".", ".."}:
        raise _FilenameError("Invalid dataset name")


class _DatasetMultipartParser(MultiPartParser):
    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._current_part.content_disposition)
        raw_filename = options.get(b"filename")
        if raw_filename is None:
            super().on_headers_finished()
            return
        try:
            filename = raw_filename.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _FilenameError("FILENAME_INVALID_UTF8") from exc
        _check_filename(Path(filename).name)
        super().on_headers_finished()
        # Form fields can use the request charset. File names always use UTF-8.
        self._current_part.file.filename = filename


class _DatasetUploadRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def handle_upload(request: Request):
            content_type, _ = parse_options_header(request.headers.get("content-type"))
            if content_type == b"multipart/form-data":
                try:
                    # FastAPI uses this cached form for File/Form validation and closes it at request end.
                    request._form = await _DatasetMultipartParser(request.headers, request.stream()).parse()
                except _FilenameError as exc:
                    raise exc.http_error() from exc
                except MultiPartException as exc:
                    raise HTTPException(400, exc.message) from exc
            return await handle(request)

        return handle_upload


def _upload_storage_name(file_id: uuid.UUID, original_filename: str) -> str:
    # The download handler uses the compound suffix to recognize compressed JSON.
    suffix = ".json.gz" if original_filename.endswith(".json.gz") else Path(original_filename).suffix
    candidate = f"{file_id}{suffix}"
    return candidate if len(candidate.encode("utf-8")) <= MAX_FILENAME_BYTES else str(file_id)


def _archive_filename(name: str, used: set[str]) -> str:
    candidate = name
    path = Path(name)
    n = 1
    while candidate in used:
        tail = f"_{n}{path.suffix}"
        remaining = MAX_FILENAME_BYTES - len(tail.encode("utf-8"))
        if remaining < 0:
            tail = f"_{n}"
            remaining = MAX_FILENAME_BYTES - len(tail)
        stem = path.stem.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        candidate = stem + tail
        n += 1
    used.add(candidate)
    return candidate


async def _save_upload_file(upload: UploadFile, target_path: Path, max_bytes: int | None = None,
                            too_large: str = "Upload exceeds the structure file size limit") -> tuple[int, str]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    total_size = 0
    digest = hashlib.sha256()
    with target_path.open("wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total_size += len(chunk)
            if max_bytes is not None and total_size > max_bytes:
                f.close()
                target_path.unlink(missing_ok=True)
                await upload.close()
                raise HTTPException(413, too_large)
            digest.update(chunk)
            f.write(chunk)
    await upload.close()
    return total_size, digest.hexdigest()


def _dataset_or_404(db: Session, dataset_id: uuid.UUID, user_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(select(Dataset).where(
        Dataset.id == dataset_id,
        or_(Dataset.owner_user_id == user_id, Dataset.owner_user_id == BUILTIN_OWNER_ID),
    ))
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


def _files_for_output(dataset: Dataset, rows: list[DatasetFile]) -> list[DatasetFile]:
    if dataset.kind == "prepared_receptor" or (dataset.kind == "protein_context" and (dataset.meta or {}).get("version") == 4):
        meta = dataset.meta or {}
        identities = list((meta.get("artifacts") or {}).values()) + list((meta.get("failure_artifacts") or {}).values())
        reference = meta.get("generation_reference") or {}
        identities += [reference[key] for key in ("structure", "chemical_mapping") if reference.get(key)]
        for entry in (meta.get('compatibility') or {}).get('models', {}).values():
            identities.extend(entry.get('artifacts', {}).values())
        ids = {identity["file_id"] for identity in identities}
        return [row for row in rows if str(row.id) in ids]
    return list(rows)


def _dataset_list_query(*, summary: bool, selectable: bool):
    if selectable:
        return select(Dataset).where(Dataset.kind.notin_(["prepared_receptor", "protein_context"])).options(defer(Dataset.meta, raiseload=True))
    if not summary:
        return select(Dataset)
    fields = func.jsonb_each(Dataset.meta).table_valued(column("key", String), column("value", JSONB)).alias("summary_fields")
    value = fields.c.value
    empty = literal({}, type_=JSONB)
    models = func.jsonb_each(case((func.jsonb_typeof(value["models"]) == "object", value["models"]), else_=empty)).table_valued(
        column("key", String), column("value", JSONB)).alias("summary_models")
    model_artifacts = select(func.coalesce(func.jsonb_object_agg(models.c.key,
        func.jsonb_build_object("artifacts", models.c.value["artifacts"])), empty)).select_from(models).correlate(fields).scalar_subquery()
    projected = case(
        (fields.c.key == "preparation", func.jsonb_build_object(*[item for key in PreparationOptions.model_fields for item in (key, value[key])])),
        (fields.c.key == "capabilities", func.jsonb_build_object(*[item for key in
            ("receptor_policy", "input_preparation", "structure_validation") for item in (key, value[key])])),
        (fields.c.key == "site", func.jsonb_build_object("anchor", func.jsonb_build_object("kind", value["anchor"]["kind"]), "box", value["box"])),
        (fields.c.key == "compatibility", func.jsonb_build_object("models", model_artifacts)),
        else_=value,
    )
    metadata = select(func.coalesce(func.jsonb_strip_nulls(func.jsonb_object_agg(fields.c.key, projected)), empty)).select_from(fields).where(
        fields.c.key.in_(["version", "source_filename", "source", "prepared_receptor_id", "preparation", "site",
            "generation_reference", "artifacts", "failure_artifacts", "capabilities", "compatibility"])
    ).correlate(Dataset).scalar_subquery()
    return select(*[c for c in Dataset.__table__.columns if c.key != "meta"], metadata.label("meta"))


def _datasets_for_output(db: Session, datasets, *, selectable: bool = False) -> list[schemas.DatasetOut]:
    files = {dataset.id: [] for dataset in datasets}
    if files:
        for row in db.scalars(select(DatasetFile).where(DatasetFile.dataset_id.in_(files))).all():
            files[row.dataset_id].append(row)
    out = []
    for dataset in datasets:
        if selectable:
            item = schemas.DatasetOut(id=dataset.id, owner_user_id=dataset.owner_user_id,
                name=dataset.name, kind=dataset.kind, description=dataset.description,
                status=dataset.status, meta={}, created_at=dataset.created_at, updated_at=dataset.updated_at)
        else:
            item = schemas.DatasetOut.model_validate(dataset)
        item.files = [schemas.DatasetFileOut.model_validate(row) for row in _files_for_output(dataset, files[dataset.id])]
        out.append(item)
    return out


async def upload_dataset(
    name: str = Form(...),
    kind: str = Form(...),
    description: str | None = Form(default=None),
    file_roles: list[str] = Form(default=[]),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    input_policy: Literal["generation_auto_v1"] | None = Form(default=None),
    upload_id: uuid.UUID | None = Form(default=None),
):
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files is required")
    if kind in {"protein_context", "prepared_receptor"}:
        raise HTTPException(422, "Derived resources must be created through their domain API")
    if file_roles and len(file_roles) != len(files):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file_roles length must match files length")

    protein = kind in {"agent_protein", "protein_pdb"}
    structure_kind = protein or kind == "agent_ligand"
    names = [Path(upload.filename or "").name or f"file_{idx}" for idx, upload in enumerate(files)]
    suffixes = [Path(filename).suffix.lower() for filename in names]
    if any(suffix in {".fasta", ".fa", ".faa", ".fna", ".fst"} for suffix in suffixes):
        raise HTTPException(422, "FASTA uploads are not supported")
    if structure_kind and (len(files) != 1 or (protein and suffixes[0] not in {".pdb", ".cif", ".mmcif"})):
        raise HTTPException(422, "Upload one PDB/mmCIF structure or one reference ligand")
    if input_policy == "generation_auto_v1" and kind == "agent_ligand" and suffixes[0] not in {".sdf", ".mol", ".mol2"}:
        raise HTTPException(422, "Reference ligand requires SDF, MOL or MOL2")
    if upload_id is not None:
        # The cancellation endpoint takes the same account lock. Whichever transaction
        # commits first decides whether the file was stored or canceled.
        await run_in_threadpool(db.scalar, select(User).where(User.id == current_user.id).with_for_update())
        attempt = await run_in_threadpool(db.get, DatasetUploadAttempt, (current_user.id, upload_id))
        if attempt is not None:
            if attempt.dataset_id is None:
                raise HTTPException(409, detail={"error_code": "UPLOAD_CANCELED"})
            existing = await run_in_threadpool(db.get, Dataset, attempt.dataset_id)
            if existing is None:
                raise HTTPException(410, detail={"error_code": "UPLOAD_DATASET_GONE"})
            return _datasets_for_output(db, [existing])[0]
    from backend.services.resources import check_admission
    remaining = await run_in_threadpool(check_admission, db, current_user.id, compute=False)
    quota_mb = settings.guest_storage_quota_mb if current_user.is_guest else settings.user_storage_quota_mb
    dataset = Dataset(owner_user_id=current_user.id, name=name, kind=kind,
                      description=description, status="ready", meta={})
    db.add(dataset)
    db.flush()
    dataset_dir = settings.data_root / "datasets" / str(dataset.id)
    rows = []
    try:
        for idx, (upload, safe_name) in enumerate(zip(files, names, strict=True)):
            file_id = uuid.uuid4()
            target_path = dataset_dir / _upload_storage_name(file_id, safe_name)
            role = file_roles[idx] if idx < len(file_roles) else "attachment"
            cap = (50 if protein else 10) * 1024 * 1024 if structure_kind else settings.upload_file_max_mb * 1024 * 1024
            size_bytes, sha256 = await _save_upload_file(upload, target_path, min(cap, remaining),
                f"Upload exceeds your {quota_mb} MB storage quota; delete unused data first"
                if remaining < cap else "Upload exceeds the structure file size limit" if structure_kind
                else f"Upload exceeds the {settings.upload_file_max_mb} MB file size limit")
            remaining -= size_bytes
            if structure_kind and size_bytes == 0:
                raise HTTPException(422, "Structure file is empty")
            if structure_kind and not protein and input_policy != "generation_auto_v1":
                from backend.agent.input_validation import validate_structure_input
                validate_structure_input(target_path, "protein" if protein else "ligand")
            row = DatasetFile(id=file_id, dataset_id=dataset.id, file_role=role,
                storage_path=str(target_path), original_filename=safe_name,
                content_type=upload.content_type, size_bytes=size_bytes, sha256=sha256)
            db.add(row)
            rows.append(row)
        dataset.updated_at = utcnow()
        dataset.created_at = dataset.updated_at
        for row in rows:
            row.created_at = dataset.created_at
        if upload_id is not None:
            db.add(DatasetUploadAttempt(owner_user_id=current_user.id, key=upload_id, dataset_id=dataset.id))
        db.commit()
    except BaseException:
        db.rollback()
        shutil.rmtree(dataset_dir, ignore_errors=True)
        raise
    return _datasets_for_output(db, [dataset])[0]



router.add_api_route("/upload", upload_dataset, methods=["POST"], response_model=schemas.DatasetOut,
                     route_class_override=_DatasetUploadRoute)


@router.post("/uploads/{upload_id}/cancel")
def cancel_dataset_upload(upload_id: uuid.UUID, db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    db.scalar(select(User).where(User.id == current_user.id).with_for_update())
    attempt = db.get(DatasetUploadAttempt, (current_user.id, upload_id))
    if attempt is None:
        db.add(DatasetUploadAttempt(owner_user_id=current_user.id, key=upload_id))
        db.commit()
        return {"status": "canceled"}
    if attempt.dataset_id is None:
        return {"status": "canceled"}
    dataset = db.get(Dataset, attempt.dataset_id)
    if dataset is None:
        return {"status": "canceled"}
    return {"status": "uploaded", "dataset": _datasets_for_output(db, [dataset])[0]}



@router.get("/builtin", response_model=list[schemas.DatasetOut])
def list_builtin_datasets(
    summary: bool = False,
    selectable: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _dataset_list_query(summary=summary, selectable=selectable).where(Dataset.owner_user_id == BUILTIN_OWNER_ID).order_by(Dataset.name)
    rows = db.execute(query).all() if summary and not selectable else db.scalars(query).all()
    return _datasets_for_output(db, rows, selectable=selectable)


@router.get("", response_model=list[schemas.DatasetOut])
def list_datasets(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    summary: bool = False,
    selectable: bool = False,
    search: Annotated[str | None, Query(max_length=200)] = None,
    attachment: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _dataset_list_query(summary=summary, selectable=selectable).where(
        Dataset.owner_user_id == current_user.id, Dataset.status != "archived"
    )
    files = select(DatasetFile.id).where(DatasetFile.dataset_id == Dataset.id)
    if attachment:
        file_count = select(func.count()).select_from(DatasetFile).where(
            DatasetFile.dataset_id == Dataset.id).correlate(Dataset).scalar_subquery()
        files = files.where(or_(DatasetFile.original_filename.op("~*")(r"\.(pdb|cif|mmcif)$"),
            and_(file_count == 1, DatasetFile.original_filename.op("~*")(r"\.(sdf|mol|mol2)$"))))
        query = query.where(Dataset.kind.notin_(["prepared_receptor", "protein_context"]), files.exists())
    if search and search.strip():
        keyword = search.strip()
        query = query.where(or_(Dataset.name.icontains(keyword, autoescape=True),
            files.where(DatasetFile.original_filename.icontains(keyword, autoescape=True)).exists()))
    query = query.order_by(Dataset.created_at.desc(), Dataset.id.desc()).limit(limit).offset(offset)
    rows = db.execute(query).all() if summary and not selectable else db.scalars(query).all()
    return _datasets_for_output(db, rows, selectable=selectable)


@router.get("/{dataset_id}", response_model=schemas.DatasetOut)
def get_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dataset = _dataset_or_404(db, dataset_id, current_user.id)
    return _datasets_for_output(db, [dataset])[0]


@router.patch("/{dataset_id}", response_model=schemas.DatasetOut)
def rename_dataset(
    dataset_id: uuid.UUID,
    payload: schemas.DatasetRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dataset = _dataset_or_404(db, dataset_id, current_user.id)
    if is_builtin(dataset):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Built-in datasets cannot be renamed")
    name = payload.name.strip()
    if not name or name in {".", ".."} or Path(name).name != name or "\\" in name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid dataset name")
    if payload.file_id:
        try:
            _check_filename(name)
        except _FilenameError as exc:
            raise exc.http_error() from exc
        # The displayed file is renamed too; its extension selects the parser.
        row = db.scalar(select(DatasetFile).where(DatasetFile.id == payload.file_id, DatasetFile.dataset_id == dataset.id))
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset file not found")
        if Path(name).suffix.lower() != Path(row.original_filename).suffix.lower():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File extension cannot change")
        row.original_filename = name
    elif len(payload.name) > 255:
        raise HTTPException(422, "Invalid dataset name")
    dataset.name = name
    dataset.updated_at = utcnow()
    db.commit()
    return _datasets_for_output(db, [dataset])[0]


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dataset = _dataset_or_404(db, dataset_id, current_user.id)
    if is_builtin(dataset):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Built-in datasets cannot be deleted")
    # Agent planning history keeps a foreign key to its Protein Context; deleting it would fail in Postgres.
    if db.scalar(select(WorkflowPlanningRequest.id).where(WorkflowPlanningRequest.protein_context_id == dataset_id).limit(1)) or \
            db.scalar(select(AgentSession.id).where(AgentSession.assets["protein_context_id"].astext == str(dataset_id)).limit(1)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DATASET_IN_USE_BY_AGENT")
    # Uploaded references retain UUID text accepted by uuid.UUID (hex, braces or URN).
    reference_id = Dataset.meta["reference_ligand"]["dataset_id"].astext
    for marker in ("urn:", "uuid:", "{", "}", "-"):
        reference_id = func.replace(reference_id, marker, "")
    if db.scalar(select(Dataset.id).where(
            Dataset.owner_user_id == current_user.id, Dataset.kind.in_(["protein_context", "prepared_receptor"]),
            or_(Dataset.meta["protein_dataset_id"].astext == str(dataset_id),
                Dataset.meta["source"]["dataset_id"].astext == str(dataset_id),
                Dataset.meta["prepared_receptor_id"].astext == str(dataset_id),
                Dataset.meta["site"]["anchor"]["source"]["dataset_id"].astext == str(dataset_id),
                Dataset.meta["generation_reference"]["structure"]["dataset_id"].astext == str(dataset_id),
                Dataset.meta["generation_reference"]["chemical_mapping"]["dataset_id"].astext == str(dataset_id),
                Dataset.meta["generation_reference"]["source_structure"]["dataset_id"].astext == str(dataset_id),
                (Dataset.meta["reference_ligand"]["source"].astext == "uploaded") &
                (func.lower(reference_id) == dataset_id.hex))).limit(1)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DATASET_IN_USE_BY_CONTEXT")
    # SurfGen keeps an optional extra ligand dataset beside its Protein Context.
    # Jobs created before ligand_dataset_id was recorded still name the ligand file in their task payload.
    ligand_paths = select(DatasetFile.storage_path).where(DatasetFile.dataset_id == dataset_id)
    def reads_dataset(job):
        return (job.input_dataset_id == dataset_id) | (job.params["protein_context_id"].astext == str(dataset_id)) | \
            (job.params["molecule_generation"]["ligand_dataset_id"].astext == str(dataset_id)) | \
            select(JobTask.id).where(JobTask.job_id == job.id, JobTask.input_payload["reference_ligand"].astext.in_(ligand_paths)).exists()
    # Postprocessing reads its source job's inputs and an optional reference dataset without recording them itself.
    source = aliased(Job)
    source_ids = select(cast(source.id, String)).where(source.owner_user_id == current_user.id, reads_dataset(source))
    postprocessing = Job.params["postprocessing"]
    if db.scalar(select(Job.id).where(Job.owner_user_id == current_user.id, Job.status.in_(ACTIVE_JOB_STATUSES),
            reads_dataset(Job) | postprocessing["source_job_id"].astext.in_(source_ids) |
            (postprocessing["reference_dataset_id"].astext == str(dataset_id))).limit(1)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DATASET_IN_USE_BY_JOB")
    db.execute(update(Job).where(Job.input_dataset_id == dataset_id).values(input_dataset_id=None))
    db.delete(dataset)
    db.commit()
    shutil.rmtree(settings.data_root / "datasets" / str(dataset_id), ignore_errors=True)


@router.get("/{dataset_id}/download")
def download_dataset(
    dataset_id: uuid.UUID,
    file_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dataset = _dataset_or_404(db, dataset_id, current_user.id)
    files_rows = db.scalars(select(DatasetFile).where(DatasetFile.dataset_id == dataset.id)).all()
    if not files_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset has no files")

    if file_id is not None:
        row = next((f for f in files_rows if f.id == file_id), None)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in dataset")
        return artifact_response(row.storage_path, row.original_filename, row.content_type)

    if len(files_rows) == 1:
        row = files_rows[0]
        return artifact_response(row.storage_path, row.original_filename, row.content_type)

    bundle_dir = settings.data_root / "tmp"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    # A private file per request, removed after sending, so concurrent downloads never share a half-written zip.
    fd, zip_path = tempfile.mkstemp(prefix=f"dataset_{dataset.id}_", suffix=".zip", dir=bundle_dir)
    os.close(fd)
    try:
        used = set()
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for row in files_rows:
                file_path = Path(row.storage_path)
                if file_path.exists():
                    name = Path(row.original_filename).name or "file"
                    if file_path.name.endswith('.json.gz'):
                        arcname = _archive_filename(name.removesuffix('.gz'), used)
                        with gzip.open(file_path, 'rb') as source, zf.open(arcname, 'w') as target:
                            shutil.copyfileobj(source, target)
                    else:
                        zf.write(file_path, arcname=_archive_filename(name, used))
    except BaseException:
        os.unlink(zip_path)
        raise
    return FileResponse(path=zip_path, filename=f"dataset_{dataset.id}.zip", media_type="application/zip",
                        background=BackgroundTask(os.unlink, zip_path))
