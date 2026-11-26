from fastapi import APIRouter

from backend.agent.knowledge.help_catalog import help_catalog

router = APIRouter(tags=['help'])


@router.get('/help')
def get_help():
    return help_catalog()
