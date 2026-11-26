"""Read-only module conversations and validated, unapplied form suggestions."""
import asyncio
import json
import logging
import re
import time
from copy import deepcopy
from uuid import UUID

from pydantic_ai import Agent, ModelRetry, PromptedOutput, RunContext, UnexpectedModelBehavior
from sqlalchemy import select

from backend.agent.deps import AgentDeps
from backend.agent.errors import log_failure, validation_issues
from backend.agent.facts import model_parameter_specs
from backend.agent.module_contracts import ModulePageContext, ModuleReply, ModuleSuggestions, ModuleView
from backend.agent.runner import run_agent, diagnostic, presentation_available
from backend.agent.tools import guarded_tool, prepare_tool
from backend.models import JobTask, SmallMoleculeResult
from backend.services.jobs import get_owned_job, get_owned_dataset
from backend.services.results import ResultServiceError, load_tarpass_results, apply_query, filter_guide, project_row, summarize_metric
from backend.services.workflows import WorkflowError


JOB_TYPES = {'tarpass': 'molecule_postprocessing', 'molecule_generation': 'molecule_generation',
             'property_optimization': 'property_optimization'}
EDITABLE = {
    'tarpass': {'prefilters', 'key_interactions'},
    'surfgen': {'num_molecules', 'beam_size', 'max_steps', 'seed'},
    'ecloudgen': {'target_num_molecules', 'noise', 'inv_temp', 'num_clouds', 'decodes_per_cloud', 'seed'},
    'delete': {'num_molecules', 'beam_size', 'max_steps', 'seed'},
    'epso': {'num_molecules', 'objectives', 'optimizer'},
}


def module_job(db, user_id, binding):
    if not binding.get('job_id'):
        return None
    job = get_owned_job(db, user_id, UUID(binding['job_id']))
    if job.job_type != JOB_TYPES[binding['module']]:
        raise WorkflowError('INVALID_INPUT', 'Task does not belong to this module', 422)
    return job


def user_visible_form(form):
    """An older page may still send the editor's 0-based node positions; the editor shows no node numbers, so only their count reaches the model."""
    state = form.get('editor_state')
    if not isinstance(state, dict) or 'selected_node_indices' not in state:
        return form
    indices = state['selected_node_indices']
    state = {key: value for key, value in state.items() if key != 'selected_node_indices'}
    if 'selected_node_count' not in state and isinstance(indices, list):
        state['selected_node_count'] = len(indices)
    return {**form, 'editor_state': state}


def page_context(db, user_id, binding, page):
    page = ModulePageContext.model_validate(page).model_dump(mode='json')
    page['form'] = user_visible_form(page['form'])
    job = module_job(db, user_id, binding)
    expected = {'tarpass': {'tarpass'}, 'molecule_generation': {'surfgen', 'ecloudgen'},
                'property_optimization': {'delete', 'epso'}}[binding['module']]
    if page['engine'] not in expected:
        raise WorkflowError('INVALID_INPUT', 'Engine does not belong to this module', 422)
    if job:
        key = 'postprocessing' if binding['module'] == 'tarpass' else binding['module']
        saved = deepcopy(job.params.get(key) or {})
        engine = 'tarpass' if key == 'postprocessing' else saved.get('engine')
        if engine != page['engine']:
            raise WorkflowError('INVALID_INPUT', 'Engine differs from the saved task', 422)
        page['form'] = saved
        page['source_job_id'] = saved.get('source_job_id') if key == 'postprocessing' else None
        page['protein_context_id'] = saved.get('protein_context_id') or job.params.get('protein_context_id')
        seed = (job.params.get('seed_source') or saved) if engine == 'epso' else {}
        page['ligand_dataset_id'] = seed.get('ligand_dataset_id')
    if page.get('source_job_id'):
        if binding['module'] != 'tarpass':
            raise WorkflowError('INVALID_INPUT', 'Only TarPass binds a source task', 422)
        source = get_owned_job(db, user_id, UUID(page['source_job_id']))
        if source.job_type not in {'molecule_generation', 'property_optimization'} or source.status != 'succeeded':
            raise WorkflowError('INVALID_INPUT', 'Select a completed generation task', 422)
    if page.get('protein_context_id'):
        get_owned_dataset(db, UUID(page['protein_context_id']), user_id)
    for dataset_id in (page.get('ligand_dataset_id'), page['form'].get('reference_dataset_id')):
        if dataset_id:
            get_owned_dataset(db, UUID(dataset_id), user_id)
    validate_view(page['view'])
    if page.get('view_draft'):
        validate_view(page['view_draft'])
    return page


def validate_view(view):
    from tarpass.filters import METRICS, validate_filters
    from backend.routers.postprocessing import ClusteringQuery
    view = ModuleView.model_validate(view).model_dump(mode='json')
    validate_filters(view['filters'])
    if view['sort_by'] not in METRICS | {'molecule_id'}:
        raise ValueError('Unsupported sort metric')
    if view.get('clustering'):
        ClusteringQuery.model_validate(view['clustering'])
    return view


def validate_changes(engine, target, changes, page, *, db=None, user_id=None):
    from tarpass.filters import validate_filters
    from backend.agent.schemas import SurfGenConfig, ECloudGenConfig, EPSOConfig
    if not changes:
        raise ValueError('A suggestion must change at least one field')
    allowed = {'filters', 'sort_by', 'descending', 'include_prefiltered', 'include_failed'} if target == 'view' else EDITABLE[engine]
    if changes.keys() - allowed or (target == 'view' and engine != 'tarpass'):
        raise ValueError('Suggestion contains a locked or unsupported field')
    baseline = (page.get('view_draft') or page['view']) if target == 'view' else page['form']
    merged = {**deepcopy(baseline), **changes}
    if target == 'view':
        validate_view(merged)
    elif engine == 'tarpass':
        validate_filters(merged.get('prefilters', []), pre=True)
        if not merged.get('reference_dataset_id') and any(rule['metric'] in {'reference_similarity', 'scaffold_similarity'} for rule in merged.get('prefilters', [])):
            raise ValueError('Reference similarity prefilters require a selected reference dataset')
        if 'key_interactions' in changes:
            if not page.get('source_job_id'):
                raise ValueError('Select a source task before proposing interactions')
            from backend.routers.postprocessing import options
            from backend.models import User
            from tarpass.contracts import validate_interactions
            spec = options(UUID(page['source_job_id']), db, db.get(User, user_id),
                           UUID(page['protein_context_id']) if page.get('protein_context_id') else None)
            validate_interactions(changes['key_interactions'], spec['residues'])
    elif engine == 'delete':
        count = merged.get('num_molecules')
        if type(count) is not int or not 1 <= count <= 10000:
            raise ValueError('num_molecules must be between 1 and 10000')
        from genova_runtime.generation_settings import generation_settings
        generation_settings('delete', merged)
        if merged.get('beam_size', 500) > 5000 or merged.get('max_steps', 50) > 500:
            raise ValueError('DELETE sampling parameters exceed their limits')
    else:
        if engine == 'epso' and 'optimizer' in changes:
            old = baseline.get('optimizer') or {}
            if not isinstance(changes['optimizer'], dict):
                raise ValueError('optimizer must be an object')
            if changes['optimizer'].get('num_swarms', 1) != old.get('num_swarms', 1):
                raise ValueError('num_swarms is locked')
            changes = {**changes, 'optimizer': {**old, **changes['optimizer']}}
            merged['optimizer'] = changes['optimizer']
        schema = {'surfgen': SurfGenConfig, 'ecloudgen': ECloudGenConfig, 'epso': EPSOConfig}[engine]
        schema.model_validate({key: value for key, value in merged.items() if key in schema.model_fields})
    return [{ 'field': key, 'before': baseline.get(key), 'after': value }
            for key, value in changes.items() if baseline.get(key) != value]


def job_facts(db, job):
    if job is None:
        return None
    return {'job_id': str(job.id), 'job_type': job.job_type, 'status': job.status,
            'name': job.params.get('job_name'),
            'tasks': [{'task': task.task_code, 'status': task.status,
                       'error': task.error_message,
                       'output': {key: value for key, value in (task.output_payload or {}).items()
                                  if key in {'engine', 'result_count', 'counts', 'warnings', 'target_num_molecules',
                                             'shortfall', 'sampling', 'timings', 'metadata', 'requested_count',
                                             'reached_target', 'unique_evaluated_count', 'decode_failures',
                                             'no_new_molecules', 'no_fitness_improvement'}}}
                      for task in db.scalars(select(JobTask).where(JobTask.job_id == job.id))]}


def metric_error(keys, allowed):
    # The names the model can retry with, so a wrong metric name is corrected in the same turn.
    return {'error': 'INVALID_SUMMARY_METRIC', 'rejected': sorted(set(keys) - set(allowed)), 'max_metrics': 10,
            'allowed_metrics': sorted(allowed), 'retry': 'Call again with summary_metrics chosen from allowed_metrics.'}


def add_contacts(db, job, records, raw):
    """Contacts kept by the evaluation for these records, per pose: from the stored record, else the result file."""
    ids = [record['molecule_id'] for record in records if record.get('molecule_id')]
    stored = {row.get('molecule_id'): row for row in db.scalars(select(SmallMoleculeResult.extra).where(
        SmallMoleculeResult.job_id == job.id, SmallMoleculeResult.task_code == 'tarpass',
        SmallMoleculeResult.extra['molecule_id'].astext.in_(ids)))} if ids else {}
    for record in records:
        metrics = (stored.get(record.get('molecule_id')) or raw.get(record.get('molecule_id')) or {}).get('metrics') or {}
        record['contacts'] = {}
        for pose in ('original', 'docked'):
            nearest = {}  # one entry per (type, residue), the shortest distance; keeps the reply checker's evidence small
            for c in ((metrics.get(pose) or {}).get('interaction_details') or {}).get('contacts') or []:
                distance = c.get('distance') if isinstance(c.get('distance'), (int, float)) else float('inf')
                key = (c.get('type'), c.get('residue_id'))
                nearest[key] = min(distance, nearest.get(key, distance))
            if nearest:
                record['contacts'][pose] = [f'{kind} {residue} {distance:.2f}' if distance != float('inf') else f'{kind} {residue}'
                                            for (kind, residue), distance in sorted(nearest.items(), key=lambda item: item[1])[:12]]


@guarded_tool
async def query_module_results(ctx: RunContext[AgentDeps], upstream: bool = False,
                               filters: list[dict] | None = None, sort_by: str | None = None,
                               descending: bool | None = None, offset: int = 0, limit: int = 10,
                               summary_metrics: list[str] | None = None, include_contacts: bool = False) -> dict:
    """Read current task results, or its directly bound source; statistics are backend-computed.
    Null filters/sort use the current result view. Page size is at most 20.
    A filter is exactly {"metric", "op", "value"} (op gt/lt/gte/lte/eq, value a number); sort_by is a metric name or molecule_id.
    The record at rank N of the current view is offset=N-1 with limit=1 and needs no filter; when offset is past the last
    matching record the result says so in rank_note: that rank does not exist.
    include_contacts=true adds retained contacts ("type residue_id distance", nearest first, per pose) to at most five
    records, selected records first, then this page; use offset and limit to target a ranked record.
    An interaction rule missing from the evaluation form does not mean these details are absent.
    """
    from tarpass.filters import METRICS
    from tarpass.selection import cluster_rows
    state = ctx.deps.session_context
    page, binding = state['module_context'], state['assets']['module_assistant']
    job_id = page.get('source_job_id') if upstream else binding.get('job_id')
    if not job_id:
        return {'error': 'NO_BOUND_TASK'}
    job = get_owned_job(ctx.deps.db, ctx.deps.user_id, UUID(job_id))
    if job.status != 'succeeded':
        return {'job_id': job_id, 'results_ready': False, 'task': job_facts(ctx.deps.db, job)}
    if job.job_type == 'molecule_postprocessing':
        _, _, rows = load_tarpass_results(ctx.deps.db, user_id=ctx.deps.user_id, job_id=job.id)
        view = page['view']
        keys = summary_metrics if summary_metrics is not None else ['qed', 'sa_score', 'docked.affinity']
        if len(keys) > 10 or set(keys) - METRICS:
            return metric_error(keys, METRICS)
        try:
            selected = apply_query(rows, filters=view['filters'] if filters is None else filters,
                                   sort_by=sort_by or view['sort_by'], descending=view['descending'] if descending is None else descending,
                                   include_prefiltered=view['include_prefiltered'], include_failed=view['include_failed'])
        except ResultServiceError as exc:
            if exc.code != 'INVALID_FILTER':
                raise
            # A wrong filter or sort name is corrected by the model in this turn, like a wrong summary metric.
            return filter_guide(exc.message)
        if view.get('clustering'):
            selected, _ = cluster_rows(selected, view['clustering'], sort_by or view['sort_by'])
        chosen = [row for row in rows if row.get('molecule_id') in page['selected_ids']]
        start, size = max(0, offset), min(20, max(1, limit))
        def result_record(row):
            result = {**project_row(row), **{key: row.get(key) for key in
                      ('source_index', 'has_original_pose', 'prefilter_reasons', 'errors')}}
            for pose in ('original', 'docked'):
                if (row.get('metrics', {}).get(pose) or {}).get('errors'):
                    result['metrics'].setdefault(pose, {})['errors'] = row['metrics'][pose]['errors']
            return result
        picked, page_rows = [result_record(row) for row in chosen], [result_record(row) for row in selected[start:start + size]]
        if include_contacts:
            add_contacts(ctx.deps.db, job, (picked + page_rows)[:5], {row.get('molecule_id'): row for row in rows})
        found = {'job_id': job_id, 'scope': 'current_view', 'total_records': len(rows), 'matching_records': len(selected),
                 'status_counts': {status: sum(row.get('status') == status for row in rows)
                                   for status in {'succeeded', 'partial', 'prefiltered', 'failed', 'invalid'}},
                 'summary': {key: summarize_metric(selected, key) for key in keys},
                 'selected_rows': picked, 'rows': page_rows,
                 'offset': start, 'returned_count': len(page_rows)}
        if start >= len(selected):
            found['rank_note'] = f'offset {start} is past the last matching record ({len(selected)} in this view): no record has rank {start + 1}.'
        return found
    statement = select(SmallMoleculeResult).join(JobTask).where(JobTask.job_id == job.id)
    from sqlalchemy import func
    total = ctx.deps.db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = list(ctx.deps.db.scalars(statement.order_by(SmallMoleculeResult.created_at, SmallMoleculeResult.id)
                                  .offset(max(0, offset)).limit(min(20, max(1, limit)))))
    selected_ids = []
    for value in page['selected_ids']:
        try:
            selected_ids.append(UUID(value))
        except ValueError:
            continue
    chosen = list(ctx.deps.db.scalars(statement.where(SmallMoleculeResult.id.in_(selected_ids)))) if selected_ids else []
    from backend.result_query import generation_metric, GENERATION_METRICS, numeric
    from genova_runtime.epso_objectives import METRICS as EPSO_METRICS
    is_epso = (job.params.get('property_optimization') or {}).get('engine') == 'epso'
    keys = summary_metrics if summary_metrics is not None else (['qed', 'sa', 'mw'] if is_epso else ['qed', 'sa', 'weight'])
    allowed = set(EPSO_METRICS) if is_epso else set(GENERATION_METRICS)
    if len(keys) > 10 or set(keys) - allowed:
        return metric_error(keys, allowed)
    summary = {}
    for key in keys:
        value = numeric(SmallMoleculeResult.extra['metrics'][key].astext) if is_epso else generation_metric(key)
        count, mean, low, high = ctx.deps.db.execute(select(func.count(value), func.avg(value), func.min(value), func.max(value))
                                                   .where(SmallMoleculeResult.job_id == job.id)).one()
        summary[key] = {'count': count, 'missing': total - count, 'mean': mean, 'min': low, 'max': high}
    def record(row):
        return {'result_id': str(row.id), 'smiles': row.smiles, 'metrics': row.extra}
    whole = {'job_id': job_id, 'scope': 'whole_task', 'total_records': total, 'summary': summary,
             'rows': [record(row) for row in rows], 'selected_rows': [record(row) for row in chosen],
             'offset': max(0, offset), 'returned_count': len(rows)}
    if max(0, offset) >= total:
        whole['rank_note'] = f'offset {max(0, offset)} is past the last record ({total} in this task): no record has rank {max(0, offset) + 1}.'
    return whole


def shape_suggestions(deps, page, binding, patches):
    """The validated suggestion cards (what changes from what) for the patches a model returned; a patch that changes nothing is dropped."""
    suggestions = []
    for suggestion in patches:
        changes = validate_changes(page['engine'], suggestion.target, suggestion.changes, page, db=deps.db, user_id=deps.user_id)
        if changes:
            suggestions.append({'target': suggestion.target, 'reason': suggestion.reason, 'changes': changes,
                                'engine': page['engine'], 'job_id': binding.get('job_id'),
                                'source_job_id': page.get('source_job_id'),
                                'input_binding': {'protein_context_id': page.get('protein_context_id'),
                                                  'ligand_dataset_id': page.get('ligand_dataset_id'),
                                                  'reference_dataset_id': page['form'].get('reference_dataset_id')}})
    return suggestions


# The suggestions-only pass: a reply on a parameter page that states values for editable fields carries them as fill-in cards.
_NUMBER = re.compile(r'(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![A-Za-z0-9_])')
_RECOMMENDS = re.compile(r'建议|推荐|提高|调高|调低|调整|改为|改成|设为|设成|设置为|增加|减少|降低|→|->|'
                         r'\b(?:recommend\w*|suggest\w*|increas\w*|rais(?:e|es|ed|ing)|lower(?:ed|ing)?|reduc\w*)\b|\b(?:set|change)\b.{0,40}?\bto\b', re.I)
_LIST_MARKER = re.compile(r'(?m)^[ \t]*(?:\d+[.)、]|[①②③④⑤⑥⑦⑧⑨⑩])[ \t]*')
TARPASS_SUGGESTION_RULES = '''
For a new screening run use target draft. Each requested alternative has its own card, relative to the same current form.
prefilters is a complete replacement array. Include retained rules and use only metric, op and numeric value in each rule.
Keep unrelated settings. Only propose key_interactions for known residues requested by the user.
Result interpretation and descriptions of existing cutoffs do not request a draft. Filtering the displayed results uses target view.
'''
SUGGESTION_PASS_RULES = '''You turn an assistant reply into form suggestions. You receive the user's question, the reply, the engine, its editable_fields and the current_form.
Return a suggestion only for concrete values the reply itself recommends for editable fields, such as a requested preset (higher precision, a budget, a count).
Use target "draft". changes holds only the fields whose recommended value differs from current_form, keyed by editable field identifiers and shaped like the current form
(an object field such as optimizer is an object holding the changed keys). reason is one concise sentence in the language of the reply.
Return an empty list when the reply only explains, restates current or default values, reports results, or recommends nothing concrete.
Never add a value the reply does not state. Keep locked parameters unchanged (num_swarms is locked).
EPSO counts evaluations as num_particles * (num_steps + 1), at most 20000. EPSO supports qed, sa, mw, logp, lipinski, hba, hbd, heavy_atom_count, similarity and gnina_affinity;
sa is normalized 0..1; use gnina_affinity with seed_relative mode and an optional positive weight.
'''


def _numbers(value):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _numbers(item)
    elif isinstance(value, list):
        for item in value:
            yield from _numbers(item)


def new_values_stated(message, page):
    """A coarse pre-filter, not a judgement: the reply may recommend values when it gives a number the form does not hold yet, a number next to
    a recommending word, or names an editable field (an identifier with an underscore, or a plain word in backticks or followed by = or :).
    A reply that only restates the current numbers, or has no number and no field name, does not; the extra call decides the rest."""
    held = set(_numbers(page['form']))
    text = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', _LIST_MARKER.sub('', message))
    numbers = _NUMBER.findall(text)
    if any(float(token) not in held for token in numbers) or (numbers and _RECOMMENDS.search(message)):
        return True
    names = set(EDITABLE[page['engine']]) | {key for value in page['form'].values() if isinstance(value, dict) for key in value}
    word = lambda name: rf'(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])'
    return any(re.search(word(name) if '_' in name else rf'`{re.escape(name)}`|{word(name)}\s*[=:：]', message) for name in names)


def suggestion_pass_available(deps):
    """Room for the pass after the final reply check: a few requests, some output budget and time to spare."""
    return (deps.usage is not None and deps.usage.requests + 3 <= deps.budget.requests
            and deps.budget.turn_output - deps.usage.output_tokens - getattr(deps, 'unknown_output_reserved', 0) > 5000
            and deps.deadline is not None and deps.deadline - time.monotonic() > 30)


async def complete_suggestions(service, deps, question, reply):
    """After the final reply check: when the reply states recommended values for editable fields but carries no suggestion,
    one extra call returns them as suggestion cards (validated like any other). None when nothing is added; it never fails the turn."""
    state = deps.session_context or {}
    binding, page = (state.get('assets') or {}).get('module_assistant'), state.get('module_context')
    if (not binding or not page or reply.get('module_suggestions') or reply.get('error_code')
            or not reply.get('message') or (deps.safety_assessment or {}).get('task_state') == 'blocked'
            or not new_values_stated(reply['message'], page) or not suggestion_pass_available(deps)):
        return None
    tarpass = page['engine'] == 'tarpass'
    if tarpass and not _RECOMMENDS.search(question + ' ' + reply['message']):
        return None
    try:
        agent = Agent(service._model, deps_type=AgentDeps, output_type=PromptedOutput(ModuleSuggestions), retries=2,
                      system_prompt=SUGGESTION_PASS_RULES + (TARPASS_SUGGESTION_RULES if tarpass else ''))

        @agent.output_validator
        def validate(output: ModuleSuggestions):
            try:
                for suggestion in output.suggestions:
                    if suggestion.target != 'draft':
                        raise ValueError('This pass only fills a new task draft; return no cards for view changes')
                    validate_changes(page['engine'], suggestion.target, suggestion.changes, page, db=deps.db, user_id=deps.user_id)
            except ValueError as exc:
                raise ModelRetry(str(exc)) from exc
            return output

        prompt = {'question': question, 'reply': reply['message'], 'engine': page['engine'],
                  'editable_fields': sorted(EDITABLE[page['engine']]), 'current_form': page['form']}
        if tarpass:
            prompt['parameter_spec'] = model_parameter_specs('tarpass')
        deps.db.rollback()
        result = await asyncio.wait_for(run_agent(agent, json.dumps(prompt, ensure_ascii=False), deps, stage='output_evidence_suggestions'),
                                        timeout=min(45, deps.deadline - time.monotonic() - 10))
        return shape_suggestions(deps, page, binding, result.output.suggestions) or None
    except Exception as exc:  # the reply already stands on its own: a failed pass leaves it as it is
        log_failure(logging.getLogger('backend-agent'), exc, stage='suggestions')
        return None


async def answer_module(service, deps, message, state):
    from backend.agent.session_chat import get_parameter_spec, get_metric_spec
    from backend.agent.tools import list_project_knowledge, read_project_knowledge
    from backend.agent.prompts import REPLY_STYLE, RESEARCH_RULES
    from backend.agent.service import run_streamed
    binding = state['assets']['module_assistant']
    page = page_context(deps.db, deps.user_id, binding, state['module_context'])
    state['module_context'] = page
    job = module_job(deps.db, deps.user_id, binding)
    facts = {'current_task': job_facts(deps.db, job), 'page': page,
             'editable_fields': sorted(EDITABLE[page['engine']])}
    tarpass = page['engine'] == 'tarpass'
    if tarpass:
        facts['parameter_spec'] = model_parameter_specs('tarpass')
    if page.get('source_job_id'):
        facts['source_task'] = job_facts(deps.db, get_owned_job(deps.db, deps.user_id, UUID(page['source_job_id'])))
    deps.response_facts.append({'tool': 'module_context', 'result': facts})
    tools = [list_project_knowledge, read_project_knowledge, get_parameter_spec, get_metric_spec, query_module_results]
    blocked = (deps.safety_assessment or {}).get('task_state') == 'blocked'
    if blocked:
        tools = [list_project_knowledge, read_project_knowledge, get_parameter_spec, get_metric_spec]
    deps.allowed_tools = frozenset(tool.__name__ for tool in tools)
    deps.allow_plan_mutation = False
    instructions = RESEARCH_RULES + REPLY_STYLE + '''
You assist the CURRENT module using read-only tools. Platform documentation and saved task data are
authoritative; use general model knowledge only as clearly identified supplementary explanation.
There is no Internet retrieval. Never invent computed properties, statistics, evidence, or citations.
For result interpretation call query_module_results; distinguish whole-run counts, filtered-view statistics,
selected records and paginated examples. Cite job_id, molecule_id and metric names/values when relevant.
When a tool returns a correctable error with allowed values (INVALID_SUMMARY_METRIC with allowed_metrics; INVALID_FILTER with
filter_shape, allowed_metrics and allowed_sort_by), call it again once with corrected arguments before answering; never answer
with counts only because a call failed. A rank N is the position N in the current view's order: offset=N-1, limit=1, no filter.
When the result carries rank_note, no record has that rank: say so with the number of records, and never invent one.
When one question asks for several ranks, read each with its own call.
For key interacting residues or contacts of evaluation records, call query_module_results with include_contacts=true
and list the returned contacts, naming the record and pose; an interaction rule missing from the evaluation settings
does not mean the contacts are absent. Say the contacts are unavailable only when the returned record has none.
Explain missing metrics as missing, never as zero. 2D ECloudGen/EPSO outputs have no original 3D poses.
page.form.editor_state, when present, is the DELETE structure editor's unsent state: selected_node_count, selected_node_elements (element to count), deleted_node_count and has_unsaved_edit. The editor shows no node numbers, so describe a selection only by its count and element types (for example 3 selected nodes: 2 C, 1 N); never invent or quote node numbers or positions.
Ask about the user's scientific priority when ranking criteria are unspecified; do not invent a universal score.
Only propose changes to editable_fields of the current engine, or TarPass view filters and sorting.
A view suggestion changes existing results only. A draft suggestion fills a subsequent task's form only.
Neither action runs computation. Never suggest changing engine, input datasets, source job or DELETE structure.
Return suggestions only when useful for the user's current request; pure questions can have no suggestions.
EPSO supports qed, sa, mw, logp, lipinski, hba, hbd, heavy_atom_count, similarity, and gnina_affinity.
EPSO sa is normalized 0..1; TarPass sa_score is raw SA and its thresholds cannot be copied to EPSO.
Use gnina_affinity with seed_relative mode and an optional positive weight. This goal requires a validated shared receptor and docking box. Lower energy is better. EPSO uses seed-relative scores and penalizes regressions more strongly.
Read reviewed documentation for model or metric explanations. Read runtime parameter and metric specs for current defaults, ranges and identifiers before giving parameter recommendations.
Keep locked parameters unchanged. Each suggestion has a concise reason and a dict of changed field values.
When the answer recommends concrete values for editable fields, including a requested preset such as higher precision,
also return them as a draft suggestion; never leave recommended values only in the message.
EPSO counts evaluations as num_particles * (num_steps + 1), at most 20000; use that formula when quoting the budget.
''' + (TARPASS_SUGGESTION_RULES if tarpass else '')
    agent = Agent(service._model, deps_type=AgentDeps, output_type=PromptedOutput(ModuleReply), retries=2,
                  system_prompt=instructions)
    for tool in tools:
        agent.tool(tool, prepare=prepare_tool)

    @agent.output_validator
    def validate(output: ModuleReply):
        try:
            if blocked and output.suggestions:
                raise ValueError('This conversation only permits explanatory answers')
            for suggestion in output.suggestions:
                if suggestion.target == 'view' and not binding.get('job_id'):
                    raise ValueError('No current results to filter')
                validate_changes(page['engine'], suggestion.target, suggestion.changes, page,
                                 db=deps.db, user_id=deps.user_id)
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        return output

    prompt = {'question': message, 'session': {'id': state['id'], 'turns': state.get('turns', [])}, 'module': facts}
    deps.db.rollback()
    run_decision = run_streamed if deps.progress else run_agent
    try:
        result = await run_decision(agent, json.dumps(prompt, ensure_ascii=False), deps, stage='decision')
    except UnexpectedModelBehavior as exc:
        if (not tarpass or blocked or not any(issue['type'] == 'json_invalid' for issue in validation_issues(exc))
                or not presentation_available(deps)):
            raise
        # A provider can return prose with invalid JSON escaping after its normal retries.
        # Read the same evidence once using a structured output tool and the original validator.
        from backend.agent.sources import bounded_facts
        retry = Agent(service._model, deps_type=AgentDeps, output_type=ModuleReply, retries=0, system_prompt=instructions)
        retry.output_validator(validate)
        prompt['previous_tool_evidence'] = bounded_facts(deps.response_facts)
        result = await run_agent(retry, json.dumps(prompt, ensure_ascii=False), deps, stage='decision_format_retry')
    output = result.output
    suggestions = shape_suggestions(deps, page, binding, output.suggestions)
    return {'message': output.message, 'module_suggestions': suggestions,
            'evidence_details': [ref.model_dump(mode='json') for ref in deps.retrieved_evidence_details]}, {'diagnostic': diagnostic(deps)}
