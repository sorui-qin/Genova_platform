from typing import Literal, Annotated

from pydantic import BaseModel, Field, model_validator, field_validator, field_serializer, TypeAdapter
from typing_extensions import TypedDict, NotRequired
from backend.structure_contracts import PreparedReceptorSpec, Identifier

from backend.agent.schemas import WorkflowPlan, EPSOConfig, MetricFilter
from genova_runtime.epso_objectives import validate_requested_count
from genova_runtime.generation_settings import COUNT_LIMITS, DEFAULT_GENERATION_COUNT


class PlannedWorkflow(WorkflowPlan):
    protein_context_id: str | None = None


class IterationPolicy(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool = False
    engine: Literal["epso", "delete"] = "epso"
    max_rounds: int = Field(default=2, ge=1, le=20)
    num_molecules: int = Field(default=100, ge=1, le=COUNT_LIMITS['delete'])
    delete_mode: Literal["r_group", "side_chain", "linker", "scaffold_hopping"] = "r_group"
    epso: EPSOConfig = Field(default_factory=EPSOConfig)


    @model_validator(mode='before')
    @classmethod
    def default_delete_count(cls, value):
        if isinstance(value, dict) and value.get('engine') == 'delete' and 'num_molecules' not in value:
            return {**value, 'num_molecules': DEFAULT_GENERATION_COUNT}
        return value

    @model_validator(mode='after')
    def validate_count(self):
        if self.engine == 'epso':
            validate_requested_count(self.num_molecules, self.epso.objectives)
        return self


class SamplingPolicy(BaseModel):
    model_config = {'extra':'forbid'}
    enabled: bool = True
    max_rounds: int = Field(default=2, ge=0, le=10)


class PreparationPlan(TypedDict):
    prepared_spec: PreparedReceptorSpec
    name: NotRequired[Annotated[Identifier,Field(max_length=255)]]
    target_chain_component_id: NotRequired[str]
    chain_selection_reason: NotRequired[str]


PreparationPlan.__pydantic_config__={'extra':'forbid'}


class TaskPlan(BaseModel):
    model_config = {"extra": "forbid"}
    stage: Literal["preparation", "generation", "postprocessing"] | None = None
    goal: str = Field(min_length=1, max_length=4000)
    completion: str = Field(min_length=1, max_length=4000)
    preparation: PreparationPlan | None = None
    site: dict | None = None
    workflow: PlannedWorkflow | None = None
    sampling: SamplingPolicy | None = None
    iteration: IterationPolicy = Field(default_factory=IterationPolicy)
    key_interactions: list[dict] = Field(default_factory=list)
    reference_dataset_id: str | None = None
    success_filters: list[MetricFilter] = Field(default_factory=list)
    required_candidates: int = Field(default=1, ge=1, le=10000)
    max_recoveries: int = Field(default=0, ge=0, le=10)
    auto_hours: float = Field(default=24, gt=0, le=720)

    @field_validator('preparation')
    @classmethod
    def preparation_record(cls,value):
        return TypeAdapter(PreparationPlan).dump_python(value,mode='json') if value is not None else None

    @field_serializer('preparation')
    def serialize_preparation(self,value):
        return value

    @model_validator(mode="after")
    def validate_stages(self):
        self.iteration.enabled = False
        self.success_filters = []
        self.max_recoveries = 0
        if self.stage is None:
            self.stage = 'generation' if self.workflow and self.workflow.protein_context_id else 'preparation'
        if self.stage == 'preparation':
            if not self.preparation:
                raise ValueError('Protein preparation requires confirmed preparation inputs')
        elif self.workflow is None or not self.workflow.protein_context_id:
            raise ValueError('Molecular stages require a prepared Context')
        return self
