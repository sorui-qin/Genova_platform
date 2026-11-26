"""Final-text guards: facts the backend already holds that a reply has to carry.

They run once, after the last reply check (which may replace the whole message), and only add what is missing:
- a failure reply names the task it read and quotes that task's last error line verbatim;
- a from-scratch draft with the default method names the other from-scratch method when a reference ligand is bound.
"""
import logging
import re

from backend.agent.errors import log_failure

_ALTERNATIVE = re.compile(r'e\s*-?\s*cloud\s*-?\s*gen', re.I)
_DEFAULT = re.compile(r'surf\s*-?\s*gen', re.I)
_OTHER_METHOD = re.compile(r'\b(?:DELETE|EPSO)\b')
_CHOSEN = re.compile(r'surf\s*-?\s*gen|e\s*-?\s*cloud\s*-?\s*gen', re.I)
_ROUTE_NOTE = {
    'zh': '备选：这组文件也可以用 ECloudGen。这里默认用 SurfGen：它从蛋白局部表面出发，可借助参考配体定位区域，并给出原始三维构象；'
          'ECloudGen 以口袋为条件生成，参考配体可选，只给出结构记录、没有原始三维构象（评价阶段可再做对接）。想改用它请直接告诉我，默认路线不变。',
    'en': 'Alternative: ECloudGen is also available for these files. SurfGen stays the default here: it works from the local protein surface, '
          'can use the reference ligand to locate the region, and returns original three-dimensional poses; ECloudGen is pocket-conditioned, '
          'treats the reference ligand as optional, and returns structure records without original poses (evaluation can dock them later). '
          'Tell me if you want ECloudGen instead; the default route is unchanged.',
}


def _flat(text):
    return ' '.join(str(text).split())


def cite_task(message, facts, language):
    """Prefix the message with the task that was read and its last error line, whichever the reply does not already carry."""
    jobs = {}
    for fact in facts:
        result = fact.get('result')
        if fact.get('tool') == 'get_job_diagnostics' and isinstance(result, dict) and result.get('job_id') and not result.get('error_code'):
            jobs[result['job_id']] = result
    failed = [(job, task) for job in jobs.values() for task in job.get('tasks') or []
              if task.get('status') == 'failed' and task.get('error_last_line')]
    if len(failed) > 1:
        # Several failed tasks were read: the reply is about the one whose last line it already quotes, if exactly one.
        failed = [(job, task) for job, task in failed if _flat(task['error_last_line']) in _flat(message)]
    if len(failed) != 1:
        return message  # which task a reply is about is not for code to guess
    job, task = failed[0]
    head, name, short = message[:300].lower(), (job.get('name') or '').strip(), job['job_id'][:8]
    zh = language == 'zh'
    lead = []
    if short.lower() not in head and not (len(name) >= 3 and name.lower() in head):
        label = (f'{name}（编号 {short}）' if zh else f'{name} (id {short})') if name else (f'编号 {short}' if zh else f'id {short}')
        lead.append(f'读取的任务：{label}。' if zh else f'Task read: {label}.')
    line = task['error_last_line']
    if _flat(line) not in _flat(message):
        lead.append(f'日志最后一行（原文）：{line}' if zh else f'Last line of its log, verbatim: {line}')
    return ('' if zh else ' ').join(lead) + '\n\n' + message if lead else message


def generation_method(decision, response, state):
    """The from-scratch or optimization method a draft carries: its own settings, the saved plan, then the saved preference."""
    workflow = decision.task_plan.workflow if decision.task_plan else None
    generation = decision.generation_request or (workflow.generation if workflow else None)
    if generation is not None:
        return generation.engine
    if response is not None and response.plan_valid and response.normalized_plan:
        return response.normalized_plan.generator
    return ((state.get('workflow_preferences') or {}).get('generation') or {}).get('engine')


def route_note(message, language, decision, response, deps, user_message):
    """Name the other from-scratch method after the first paragraph when the default one is used and a reference ligand is bound."""
    safety = deps.safety_assessment or {}
    if decision is None or safety.get('answer_only') is not False or safety.get('task_state') == 'blocked':
        return message
    if decision.operation not in {'prepare', 'plan', 'task_plan'} or _ALTERNATIVE.search(message) or _CHOSEN.search(user_message or ''):
        return message  # a question, an explanation, or a method the user already named or the reply already offers
    state = deps.session_context or {}
    assets = {**(state.get('assets') or {}), **(decision.assets or {})}
    if not assets.get('ligand_dataset_id') or 'ecloudgen' not in {item.name for item in deps.catalog.get_enabled_generators()}:
        return message
    if any(_ALTERNATIVE.search((turn.get('response') or {}).get('message') or '') for turn in state.get('turns') or []):
        return message  # the researcher was told once; later revisions of the draft do not repeat it
    method = generation_method(decision, response, state)
    if method is None and _DEFAULT.search(message) and not _OTHER_METHOD.search(message):
        method = 'surfgen'  # the decision records no method, but the reply itself presents the default one
    if method != 'surfgen':
        return message
    first, separator, rest = message.partition('\n\n')
    return f'{first}\n\n{_ROUTE_NOTE[language]}' + (separator + rest if rest else '')


def final_guards(message, deps, *, decision=None, response=None, user_message='', trigger=None):
    language = 'zh' if (deps.safety_assessment or {}).get('language') == 'zh' else 'en'
    guards = (lambda text: cite_task(text, deps.response_facts, language),
              lambda text: text if trigger else route_note(text, language, decision, response, deps, user_message))
    for guard in guards:
        try:
            message = guard(message)
        except Exception as exc:  # a guard only adds text: it never fails the turn
            log_failure(logging.getLogger('backend-agent'), exc, stage='reply_guard')
    return message
