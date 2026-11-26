"""Conversation language and fixed interface text are independent."""


def interface_text(language, zh, en):
    return zh if language == 'zh' else en


def turn_text(turn, zh, en):
    return interface_text((turn.request or {}).get('interface_language'), zh, en)


def session_interface_language(db, session):
    """Use the latest explicit request's page language for background notices."""
    from sqlalchemy import or_, select
    from backend.models import AgentTurn
    language = AgentTurn.request['interface_language'].as_string()
    return db.scalar(select(language).where(AgentTurn.session_id == session.id,
        or_(AgentTurn.audit['trigger'].as_string().is_(None), AgentTurn.audit['recovery_of'].as_string().is_not(None)),
        language.in_(('zh', 'en')))
        .order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc()).limit(1)) or 'en'


def session_text(db, session, zh, en):
    return interface_text(session_interface_language(db, session), zh, en)


def task_language(task):
    return (task.workflow_preferences or {}).get('reply_language', 'en')


def task_text(task, zh, en):
    return zh if task_language(task) == 'zh' else en


def completion_text(stage, language):
    messages = {
        'preparation': ('交付准备后的蛋白，再确认位点并形成后续阶段草稿。',
                        'Deliver the prepared protein, then review the binding site and draft the next stage.'),
        'generation': ('交付当前阶段的分子生成／优化结果。',
                       'Deliver the molecule generation / optimization results for this stage.'),
        'postprocessing': ('交付当前阶段的评价结果。', 'Deliver the evaluation results for this stage.'),
    }
    return messages[stage][0 if language == 'zh' else 1]
