"""Owned, bounded task evidence for read-only troubleshooting."""
import hashlib
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select

from backend.config import settings
from backend.models import Dataset, Job, JobTask
from backend.agent.runner import estimate_tokens


def redact(text):
    text = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|bearer\s+)[^\s,;\'"}]+', r'\1[REDACTED]', str(text))
    text = re.sub(r'(?i)(["\']?(?:api[_-]?key|access_token|refresh_token|password|secret|token)["\']?\s*[:=]\s*)["\']?[^\s,;\'"}]+', r'\1[REDACTED]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', text)
    text = re.sub(r'(?:https?|rediss?|postgres(?:ql)?(?:\+\w+)?):\/\/[^\s"\']+', '[URL]', text)
    return re.sub(r'(?<![\w.])/(?:[\w.@+-]+/)+[\w.@+-]*', lambda m: '[path]/' + Path(m[0]).name, text)


def owned_job(db, user_id, job_id):
    return db.scalar(select(Job).where(Job.id == job_id, Job.owner_user_id == user_id, Job.is_deleted.is_(False)))


def job_summary(job):
    return dict(job_id=str(job.id), name=job.params.get('job_name') or job.params.get('name') or '',
                job_type=job.job_type, status=job.status, created_at=job.created_at.isoformat())


def find_jobs(db, user_id, query, offset=0, status=None, job_type=None):
    query = query.strip()[:200]
    owned = [Job.owner_user_id == user_id, Job.is_deleted.is_(False), *([Job.status == status] if status else []),
             *([Job.job_type == job_type] if job_type else [])]
    if not query:
        # No name given ("the one that just failed"): the newest jobs, optionally of one status.
        rows = db.scalars(select(Job).where(*owned).order_by(Job.created_at.desc(), Job.id).offset(offset).limit(11)).all()
        return dict(jobs=[job_summary(job) for job in rows[:10]], resources=[],
                    next_offset=offset + 10 if len(rows) > 10 else None, selection_required=False)
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    filters = [Job.params['job_name'].astext.ilike(pattern, escape='\\'), Job.params['name'].astext.ilike(pattern, escape='\\')]
    try:
        identity = UUID(query)
        filters.append(Job.id == identity)
    except ValueError:
        identity = None
    datasets = db.scalars(select(Dataset).where(Dataset.owner_user_id == user_id,
        or_(Dataset.name.ilike(pattern, escape='\\'), Dataset.id == identity) if identity else Dataset.name.ilike(pattern, escape='\\'))
        .order_by(Dataset.created_at.desc()).limit(20)).all()
    prepared_ids = [str(row.id) for row in datasets if row.kind == 'prepared_receptor']
    if prepared_ids:
        datasets += db.scalars(select(Dataset).where(Dataset.owner_user_id == user_id,
            Dataset.kind == 'protein_context', Dataset.meta['prepared_receptor_id'].astext.in_(prepared_ids))
            .order_by(Dataset.created_at.desc()).limit(20)).all()
    datasets = list({row.id: row for row in datasets}.values())
    linked = []
    resources = []
    for dataset in datasets:
        meta = dataset.meta or {}
        ids = [item.get('job_id') for item in (meta.get('execution') or {}, meta.get('compatibility') or {})]
        ids = [UUID(value) for value in ids if value]
        linked.extend(ids)
        resources.append(dict(id=str(dataset.id), name=dataset.name, kind=dataset.kind, job_ids=[str(value) for value in ids]))
    if linked:
        filters.append(Job.id.in_(linked))
    rows = db.scalars(select(Job).where(*owned, or_(*filters))
        .order_by(Job.created_at.desc(), Job.id).offset(offset).limit(11)).all()
    groups = {(row.meta or {}).get('prepared_receptor_id') or str(row.id) for row in datasets}
    groups.update(str(row.id) for row in rows if row.id not in linked)
    return dict(jobs=[job_summary(job) for job in rows[:10]], resources=resources,
                next_offset=offset + 10 if len(rows) > 10 else None, selection_required=len(groups) > 1,
                relation_note='Preparation and model-input jobs linked to the same prepared resource are different stages, not ambiguous task matches.')


def diagnostic_sources(job_id):
    jobs_root = (Path(settings.data_root) / 'jobs').resolve()
    root = jobs_root / str(job_id)
    sources = {}
    if root.is_symlink():
        return sources
    root = root.resolve()
    if not root.is_relative_to(jobs_root):
        return sources
    if root.is_dir():
        for path in sorted(root.rglob('*')):
            if not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            if path.suffix.lower() not in {'.log', '.out', '.err'} and path.name.removesuffix('.gz') not in {
                'compatibility_report.json', 'model_initialization.json', 'preparation_report.json', 'failure_report.json'}:
                continue
            name = path.relative_to(root).as_posix()
            source_id = hashlib.sha256(name.encode()).hexdigest()[:24]
            stat = path.stat()
            sources[source_id] = (path, dict(source_id=source_id, name=name, size_bytes=stat.st_size,
                source_version=f'{stat.st_mtime_ns}:{stat.st_size}', ref=f'job:{job_id}:source:{source_id}'))
    return sources


def bounded_error(text, limit=4000, head=1500):
    """A long error keeps its beginning and its end: the reason is usually the last line."""
    if len(text) <= limit:
        return text, False
    return f'{text[:head]}\n[... middle omitted ...]\n{text[-(limit - head):]}', True


def error_tail(text, count=10, chars=2400):
    """The last non-empty lines of an error text, and its exact last line."""
    rows = [row.rstrip() for row in text.splitlines() if row.strip()]
    return '\n'.join(rows[-count:])[-chars:], (rows[-1][:1000] if rows else '')


def job_diagnostics(db, user_id, job_id):
    job = owned_job(db, user_id, job_id)
    if job is None:
        return {'error_code': 'RESOURCE_NOT_FOUND'}
    tasks = []
    for task in db.scalars(select(JobTask).where(JobTask.job_id == job.id).order_by(JobTask.created_at, JobTask.id)):
        info = task.output_payload.get('error_info') or {}
        error, truncated = bounded_error(redact(info.get('message') or task.error_message or ''))
        # The task's own error text, whose last line is the stated reason; quoted from here, not from a large report file.
        tail, last_line = error_tail(redact(task.error_message or info.get('message') or ''))
        tasks.append(dict(task_id=str(task.id), task_code=task.task_code, engine=task.runtime_task, status=task.status,
            stage=info.get('stage'), error_code=info.get('error_code'), error_category=info.get('error_category'),
            error=error, error_truncated=truncated, error_tail=tail, error_last_line=last_line, objects=info.get('objects', [])[:30],
            recovery_action=info.get('recovery_action'), ref=f'job:{job.id}:task:{task.id}'))
    sources = [entry[1] for entry in diagnostic_sources(job_id).values()]
    result = dict(**job_summary(job), tasks=tasks, sources=sources)
    saved = (job.params or {}).get('postprocessing') or {}
    if saved:
        # The evaluation's real settings and outcome, so a diagnosis quotes them instead of defaults.
        result['settings'] = {key: saved.get(key) for key in ('prefilters', 'key_interactions', 'source_job_id', 'reference_dataset_id')}
    if any(task['task_code'] == 'tarpass' and task['status'] == 'succeeded' for task in tasks):
        from collections import Counter
        from backend.services.results import load_tarpass_results, ResultServiceError
        try:
            rows = load_tarpass_results(db, user_id=user_id, job_id=job.id)[2]
            result['result_counts'] = {'total': len(rows), 'status': dict(Counter(row.get('status') for row in rows)),
                'prefilter_reasons': dict(Counter(reason for row in rows for reason in row.get('prefilter_reasons') or []))}
        except ResultServiceError:
            pass
    return result


def read_diagnostic(db, user_id, job_id, source_id, start_line=1, limit=200, query='', context_lines=5,
                    start_column=0, source_version=None):
    if owned_job(db, user_id, job_id) is None:
        return {'error_code': 'RESOURCE_NOT_FOUND'}
    entry = diagnostic_sources(job_id).get(source_id)
    if entry is None:
        return {'error_code': 'DIAGNOSTIC_SOURCE_MISSING', 'message': 'The requested diagnostic was not retained or no longer exists.'}
    path, source = entry
    if source_version and source_version != source['source_version']:
        return {**source, 'error_code': 'DIAGNOSTIC_SOURCE_CHANGED', 'message': 'Source changed; re-read and verify previous evidence.'}
    return read_text_source(path, {**source, 'job_id': str(job_id)}, start_line, limit, query,
                            context_lines, start_column)


LONG_LINE_TAIL = 8000


def read_text_source(path, source, start_line=1, limit=200, query='', context_lines=5, start_column=0):
    from genova_runtime.artifact_json import open_json
    if start_line < 1 and not query:
        # A tail read: the last `limit` lines, where a failed run's final error usually is.
        total, last = 0, ''
        with open_json(path) as handle:
            for total, last in enumerate(handle, 1):
                pass
        start_line, start_column = max(1, total - limit + 1), 0
        if len(last) > LONG_LINE_TAIL:
            # The last line alone is longer than a page (a one-line JSON report): show its end, where the outcome is written.
            start_line, start_column = total, max(0, len(redact(last.rstrip('\n'))) - LONG_LINE_TAIL)
    start_line = max(1, start_line)
    result = {**source, 'query': query, 'start_line': start_line, 'start_column': start_column,
              'lines': [], 'truncated': False, 'next_line': None, 'next_column': 0, 'scan_complete': False}
    remaining, history, through = 6000, [], start_line + context_lines if query and start_line > 1 else 0
    with open_json(path) as handle:
        for number, raw in enumerate(handle, 1):
            if number < start_line:
                if query and context_lines:
                    history = (history + [(number, raw.rstrip('\n'))])[-context_lines:]
                continue
            raw = raw.rstrip('\n')
            matched = bool(query and query.casefold() in raw.casefold())
            if matched:
                result.setdefault('matched_lines', []).append(number)
                through = number + context_lines
                candidates = history + [(number, raw)]
            elif not query or number <= through:
                candidates = [(number, raw)]
            else:
                history = (history + [(number, raw)])[-context_lines:] if context_lines else []
                # A search can be resumed without retaining the entire file in memory.
                if number - start_line >= 20000:
                    result.update(truncated=True, next_line=number + 1)
                    break
                continue
            for line_number, content in candidates:
                if result['lines'] and line_number <= result['lines'][-1]['line']:
                    continue
                column = start_column if line_number == start_line else 0
                safe_content = redact(content)
                if query and matched and line_number == number and not column:
                    column = max(0, safe_content.casefold().find(query.casefold()) - 500)
                text = safe_content[column:]
                if len(result['lines']) >= limit or remaining <= 32:
                    result.update(truncated=True, next_line=line_number, next_column=column)
                    break
                excerpt = text[:remaining * 3]
                if estimate_tokens(excerpt) > remaining:
                    excerpt = text[:remaining]
                shown = dict(line=line_number, column=column, text=excerpt)
                if len(excerpt) < len(safe_content):
                    shown['line_chars'] = len(safe_content)  # only part of a long line is shown
                result['lines'].append(shown)
                remaining -= estimate_tokens(excerpt) + 16
                if len(excerpt) < len(text):
                    result.update(truncated=True, next_line=line_number, next_column=column + len(excerpt))
                    break
            if result['truncated']:
                break
            history = []
        else:
            result['scan_complete'] = True
            if query and not result.get('matched_lines'):
                result['note'] = 'No line contains this text (literal, case-insensitive). Try another term, or read the end of the source with start_line=0.'
    result['ref'] = source['ref'] + f":L{start_line}:C{start_column}"
    return result


def remember(deps, result):
    if result.get('error_code'):
        return
    state = dict(getattr(deps, 'diagnostic_state', {}))
    if 'tasks' in result:
        state['job'] = {key: result[key] for key in ('job_id', 'name', 'status', 'tasks')}
        errors = [entry for entry in state.get('errors', []) if entry['job_id'] != result['job_id']]
        errors.extend({**task, 'job_id': result['job_id']} for task in result['tasks'] if task.get('error'))
        state['errors'] = errors[-8:]
    if 'lines' in result:
        pages = [item for item in state.get('sources', []) if item['source_id'] != result['source_id']]
        pages.append({key: result[key] for key in ('job_id', 'source_id', 'name', 'source_version', 'ref', 'query',
                      'start_line', 'start_column', 'next_line', 'next_column', 'scan_complete')})
        state['sources'] = pages[-12:]
        matched = [line for line in result['lines'] if re.search(r'(?i)\b(?:\w*Error|\w*Exception|failed|fatal)\b|did not converge|cannot be satisfied|失败|错误', line['text'])]
        selected = matched or result['lines']
        excerpts = state.get('evidence', []) + [dict(ref=result['ref'], name=result['name'], source_version=result['source_version'], is_error=bool(matched),
            truncated=len(result['lines']) > 3 or any(len(line['text']) > 800 for line in selected[:3]),
            lines=[{**line, 'text': line['text'][:800]} for line in selected[:3]])]
        state['evidence'] = sorted(excerpts, key=lambda entry: entry.get('is_error', False))[-6:]
    deps.diagnostic_state = state


def paused_reply(deps, code):
    from backend.agent.language import interface_text
    state = getattr(deps, 'diagnostic_state', {})
    return dict(message=interface_text(deps.interface_language, '本轮读取已暂停，读取位置与已有结果已保存。', 'Reading has paused. Your progress and existing results have been saved.'),
        investigation_status='paused', pause_reason=code, diagnostic_evidence=state,
        source_read_state=deps.source_read_state)
