from sqlalchemy import Float, String, case, cast, func, or_, select

from backend.models import SmallMoleculeResult as Result


GENERATION_METRICS = {'qed': 'QED', 'logp': 'LogP', 'sa': 'SA', 'tpsa': 'TPSA', 'weight': 'Weight'}


def numeric(text):
    return case((text == 'true', 1.0), (text == 'false', 0.0),
                (text.op('~')(r'^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$'), cast(text, Float)), else_=None)


def generation_metric(key):
    upper = GENERATION_METRICS[key]
    value = func.coalesce(Result.extra['raw'][upper].astext, Result.extra['raw'][key].astext, Result.extra[key].astext)
    return numeric(value)


def generation_query(job_id, task_code=None, smiles=None, search=None):
    statement = select(Result).where(Result.job_id == job_id)
    if task_code:
        statement = statement.where(Result.task_code == task_code)
    if smiles:
        statement = statement.where(Result.smiles_canonical == smiles)
    if search:
        pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        statement = statement.where(or_(Result.smiles.ilike(pattern), cast(Result.extra, String).ilike(pattern)))
    return statement
