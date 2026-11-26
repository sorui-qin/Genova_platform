from pathlib import Path

from backend.config import settings
from genova_runtime.artifact_json import read_json


def task_artifact_candidates(task):
    if task.status != 'succeeded':
        return []
    payload, result = task.input_payload, task.output_payload
    if not payload.get('output_dir'):
        return []
    root = Path(payload['output_dir']).resolve()
    if not root.is_relative_to((settings.data_root / 'jobs').resolve()):
        return []
    protected = set()
    def protect(value):
        if isinstance(value, dict):
            for item in value.values():
                protect(item)
        elif isinstance(value, list):
            for item in value:
                protect(item)
        elif isinstance(value, str) and value.startswith('/'):
            protected.add(Path(value).resolve())
    protect(result)
    if result.get('cache_manifest'):
        protect(read_json(result['cache_manifest']))
    candidates = []
    if task.task_code == 'protein_preparation' or task.task_code.startswith('context_compatibility_'):
        candidates = [p for p in root.rglob('*') if p.is_file() and p.suffix not in {'.log', '.out', '.err'}
                      and p.name != 'model_initialization.json']
    elif task.runtime_task == 'surfgen':
        candidates = list(root.glob('*/SDF/*.sdf')) + list(root.glob('*/*.ply')) + [root / 'results.json']
    elif task.runtime_task == 'ecloudgen':
        candidates = [p for pattern in ('inputs/**/*', 'round_*/**/*') for p in root.glob(pattern) if p.is_file()]
    elif task.runtime_task == 'tarpass':
        candidates = [p for p in root.glob('batch-*') if p.is_file() and p.suffix != '.log']
    # finalize_artifacts leaves originals available until backend validation commits.
    for value in result.values():
        if isinstance(value, str) and value.endswith('.json.gz'):
            candidates.append(Path(value.removesuffix('.gz')))
    return {path for path in candidates if path.is_file() and path.resolve().is_relative_to(root)
            and path.resolve() not in protected}


def cleanup_task_artifacts(task):
    candidates = task_artifact_candidates(task)
    if not candidates:
        return
    root = Path(task.input_payload['output_dir']).resolve()
    for path in candidates:
        path.unlink(missing_ok=True)
    for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
