from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ModuleSessionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    module: Literal['tarpass', 'molecule_generation', 'property_optimization']
    job_id: UUID | None = None


class ModuleView(BaseModel):
    model_config = {"extra": "forbid"}
    filters: list[dict] = Field(default_factory=list, max_length=20)
    sort_by: str = 'molecule_id'
    descending: bool = Field(default=False, strict=True)
    include_prefiltered: bool = Field(default=False, strict=True)
    include_failed: bool = Field(default=False, strict=True)
    clustering: dict | None = None


class ModulePageContext(BaseModel):
    model_config = {"extra": "forbid"}
    engine: Literal['tarpass', 'surfgen', 'ecloudgen', 'delete', 'epso']
    source_job_id: UUID | None = None
    protein_context_id: UUID | None = None
    ligand_dataset_id: UUID | None = None
    form: dict[str, Any] = Field(default_factory=dict)
    view: ModuleView = Field(default_factory=ModuleView)
    view_draft: ModuleView | None = None
    selected_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def bounded_form(self):
        import json
        if len(json.dumps(self.form)) > 40000 or any(len(value) > 200 for value in self.selected_ids):
            raise ValueError('Module context is too large')
        return self


class ModulePatch(BaseModel):
    model_config = {"extra": "forbid"}
    target: Literal['view', 'draft']
    changes: dict[str, Any]
    reason: str = Field(min_length=1, max_length=2000)


class ModuleReply(BaseModel):
    model_config = {"extra": "forbid"}
    message: str = Field(max_length=8000)
    suggestions: list[ModulePatch] = Field(default_factory=list, max_length=3)


class ModuleSuggestions(BaseModel):
    """What the suggestions-only pass returns: the fill-in cards for values a reply already recommends."""
    model_config = {"extra": "forbid"}
    suggestions: list[ModulePatch] = Field(default_factory=list, max_length=3)
