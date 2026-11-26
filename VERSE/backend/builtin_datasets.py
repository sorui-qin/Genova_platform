import hashlib
import mimetypes
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from backend.models import Dataset, DatasetFile, User


BUILTIN_OWNER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
BUILTIN_DIR = Path(__file__).resolve().parent.parent / "builtin_datasets"


def is_builtin(dataset: Dataset) -> bool:
    return dataset.owner_user_id == BUILTIN_OWNER_ID


def seed_builtin_datasets(db: Session) -> None:
    if db.get(User, BUILTIN_OWNER_ID) is None:
        db.add(User(
            id=BUILTIN_OWNER_ID,
            email="builtin@genova.local",
            username="builtin",
            password_hash="!",
            is_active=False,
        ))
        db.flush()

    for path in sorted(BUILTIN_DIR.iterdir()):
        if path.suffix.lower() not in {".pdb", ".sdf"}:
            continue
        dataset_id = uuid.uuid5(BUILTIN_OWNER_ID, path.name)
        file_id = uuid.uuid5(dataset_id, path.name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        kind, role = ("protein", "pocket_pdb") if path.suffix.lower() == ".pdb" else ("ligand", "ligand_input")
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            db.add(Dataset(
                id=dataset_id,
                owner_user_id=BUILTIN_OWNER_ID,
                name=path.stem,
                kind=kind,
                status="ready",
                meta={"builtin": True},
            ))
        else:
            dataset.description = None
        file = db.get(DatasetFile, file_id)
        if file is None:
            db.add(DatasetFile(
                id=file_id,
                dataset_id=dataset_id,
                file_role=role,
                storage_path=str(path),
                original_filename=path.name,
                content_type=mimetypes.guess_type(path.name)[0],
                size_bytes=path.stat().st_size,
                sha256=digest,
            ))
        else:
            file.storage_path = str(path)
            file.size_bytes = path.stat().st_size
            file.sha256 = digest
    db.commit()
