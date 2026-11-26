"""A short "change the count to N" command, recognised by pattern, so a draft edit the model only announced is still applied.

The model normally makes the edit itself. This is the net under it: when the user's whole message is such a command,
a draft is open for editing and the decision does not carry the change, the model is asked once more and then the
backend writes the count itself. Only short, clear commands match (a message with other numbers or instructions does not).
"""
import re
import unicodedata
from copy import deepcopy

from genova_runtime.generation_settings import COUNT_LIMITS

_VERB = r'(?:改成|改为|改到|调成|调为|调整为|调整到|设成|设为|设置为|换成|变成|降到|降为|减到|减少到|增加到|提高到|降低到|加到)'
_PATTERNS = (
    re.compile(rf'(?:生成)?(?:数量|个数|数目|总数)\s*(?:再|就|直接|也)?\s*{_VERB}\s*(\d{{1,6}})\s*(?:个|条|只)?'),
    re.compile(r'\b(?:change|set|update|adjust|make|reduce|increase|lower|raise)\b[^0-9]{0,40}?\b(?:count|quantity|number)\b[^0-9]{0,30}?(?:\bto\b|=)\s*(\d{1,6})\b', re.I),
    re.compile(rf'{_VERB}\s*(\d{{1,6}})\s*(?:个|条|只)'),
)
# In Chinese only filler may surround the command, so other settings or a second instruction are not swallowed by it.
_FILLER = re.compile(r'(?:请|麻烦|帮我|帮忙|好的|好|嗯|那就|那|就|先|再|也|直接|把|将|它|这个|那个|这一版|这一轮|这版|当前|现在|目前|此|本|草稿|方案|计划|生成|最终|总共|共|一共|里面|里|中|上|的|吧|吗|呢|啊|了|一下)*')


def requested_count(message):
    """N when the whole message is a short command to change the count to N, else None."""
    text = unicodedata.normalize('NFKC', message)
    for index, pattern in enumerate(_PATTERNS):
        match = pattern.search(text)
        if match:
            rest = re.sub(r'[\W_]+', '', text[:match.start()] + text[match.end():])
            clean = len(rest) <= 16 if index == 1 else _FILLER.fullmatch(rest)
            return int(match.group(1)) if clean and not re.search(r'\d', rest) else None
    return None


def count_field(engine):
    return 'target_num_molecules' if engine == 'ecloudgen' else 'num_molecules'


def pending_edit(message, state):
    """The edit to guarantee for this message, or None: no short command, no draft open for editing, a count out of range, or no change."""
    count = requested_count(message)
    if count is None:
        return None
    plan = (state or {}).get('task_plan') or {}
    definition = plan.get('definition') or {}
    run = ((state or {}).get('scientific_state') or {}).get('workflow') or {}
    # The stage draft is what the approval card shows, so it comes first; a saved workflow draft is edited with modify.
    if plan.get('state') == 'awaiting_approval' and (definition.get('workflow') or {}).get('generation'):
        kind, generation = 'task_plan', definition['workflow']['generation']
    elif run.get('status') == 'awaiting_approval' and (run.get('plan') or {}).get('generation'):
        kind, generation = 'workflow', run['plan']['generation']
    else:
        return None
    engine = generation.get('engine')
    field = count_field(engine)
    if engine not in COUNT_LIMITS or not 1 <= count <= COUNT_LIMITS[engine] or generation.get(field) == count:
        return None
    return {'kind': kind, 'engine': engine, 'field': field, 'count': count, 'definition': definition, 'plan': run.get('plan')}


def applies(output, edit):
    """True when the decision already carries the change in the shape that is saved for this kind of draft."""
    if edit['kind'] == 'workflow':
        return output.operation == 'modify' and output.quantity_patch == edit['count']
    workflow = output.task_plan.workflow if output.operation == 'task_plan' and output.task_plan else None
    return workflow is not None and getattr(workflow.generation, edit['field'], None) == edit['count']


def hint(edit):
    if edit['kind'] == 'workflow':
        return (f"The user's message changes the saved draft's count to {edit['count']}, but this decision does not apply it. "
                f"Return operation=modify with quantity_patch={edit['count']} and an exact substring of the message in command_evidence. "
                "Do not say the change was made unless the decision applies it.")
    return (f"The user's message changes the stage draft's count to {edit['count']}, but this decision does not apply it. "
            "There is no saved workflow, so return that stage's operation (prepare for a preparation-stage draft, plan for a generation-stage draft) "
            f"with generation_request carrying engine {edit['engine']} and {edit['field']}={edit['count']}, and an exact substring of the message in command_evidence. "
            "Do not say the change was made unless the decision applies it.")


def apply(output, edit, message, language):
    """Write the count into the decision. False (decision untouched) when the changed plan would not validate."""
    from backend.agent.schemas import WorkflowPlan
    from backend.agent.task_plan import TaskPlan
    try:
        if edit['kind'] == 'workflow':
            plan = deepcopy(edit['plan'])
            plan['generation'][edit['field']] = edit['count']
            WorkflowPlan.model_validate(plan)
            changes = {'operation': 'modify', 'quantity_patch': edit['count'], 'task_plan': None}
        else:
            draft = output.task_plan.model_dump(mode='json') if output.task_plan and output.task_plan.workflow else deepcopy(edit['definition'])
            draft['workflow']['generation'][edit['field']] = edit['count']
            changes = {'operation': 'task_plan', 'task_plan': TaskPlan.model_validate(draft), 'quantity_patch': None}
    except ValueError:
        return False
    changes.update(generation_request=None, preparation_request=None, missing_requirements=[], clarification_fields=[],
                   command_evidence=message.strip(),
                   message=(f"数量已改为 {edit['count']}，并生成了新一版草稿卡片，请检查后批准；批准前不会开始计算。" if language == 'zh'
                            else f"The count is now {edit['count']}. A new draft card was created; review and approve it before anything runs."))
    for key, value in changes.items():
        setattr(output, key, value)
    return True
