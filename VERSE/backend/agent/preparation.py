"""Resolve preparation choices against the session's confirmed structure."""
from pydantic import BaseModel, Field, model_validator
from typing import Literal, Annotated

from backend.structure_contracts import PreparationOptions, PreparedReceptorSpec, ComponentEdits, StructureSource, Identifier, Vector3, PositiveNumber


class CoordinateSiteRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    center: Vector3
    size: tuple[PositiveNumber, PositiveNumber, PositiveNumber] | None = None


class PreparationChoices(PreparationOptions):
    strategy: Literal['generation_auto_v1']='generation_auto_v1'
    water_policy: Literal['remove_all']='remove_all'
    scope_policy: Literal['supported_protein_v1']='supported_protein_v1'
    receptor_policy: Literal['protein_metals_v1']='protein_metals_v1'

    @model_validator(mode='before')
    @classmethod
    def retained_protonation_default(cls,value):
        if isinstance(value,dict) and value.get('protonation_policy')=='preserve' and 'ph' not in value:
            return {**value,'ph':None}
        return value


class PreparationRequest(BaseModel):
    model_config = {'extra':'forbid'}
    name: Annotated[Identifier,Field(max_length=255)] | None = None
    selected_chain_component_ids: list[str] | None = Field(default=None,
        description='Exact chain component IDs recommended from inspected target evidence and shown for user review. Do not use author chain labels as unique identities.')
    target_chain_component_id: str | None = None
    chain_selection_reason: str = Field(default='', max_length=2000,
        description='Explain target identification and why any additional protein chains need to be retained. Shown before preparation approval.')
    excluded_component_ids: list[str] = Field(default_factory=list)
    retained_component_ids: list[str] = Field(default_factory=list)
    altloc_choices: dict[str,str] = Field(default_factory=dict)
    options: PreparationChoices = Field(default_factory=PreparationChoices,
        description='Unspecified settings preserve confirmed preparation choices; initial requests use runtime defaults.')

    @model_validator(mode='after')
    def target_and_environment(self):
        selected = self.selected_chain_component_ids
        if selected and self.target_chain_component_id and self.target_chain_component_id not in selected:
            raise ValueError('The target chain must be among the selected chains.')
        if selected and len(set(selected)) > 1 and (not self.target_chain_component_id or not self.chain_selection_reason.strip()):
            raise ValueError('Recommend one target chain by default. Retaining additional chains requires an explicit target chain and an explanation for user review.')
        return self


def confirmed_preparation(state,dataset_id,file_id,sha256):
    fields=state.get('confirmed_fields') or {}
    current=((state.get('task_plan') or {}).get('definition') or {}).get('preparation') or {}
    candidates=[current.get('prepared_spec'),fields.get('prepared_spec',{}).get('value'),
        ((state.get('scientific_state') or {}).get('values') or {}).get('prepared_spec')]
    return next((spec for spec in candidates if spec and str(spec['source']['dataset_id'])==str(dataset_id)
        and str(spec['source']['file_id'])==str(file_id) and spec['source']['sha256']==sha256),{})


def _chain_scope_component_ids(manifest, selected):
    chains=[component for component in manifest.components if component.selection_kind=='chain_records' and component.atoms]
    scope=set(selected)
    for chain in chains:
        if chain.component_id not in selected:
            continue
        atom=chain.atoms[0]
        scope.update(next((group.component_ids for group in manifest.selection_groups if chain.component_id in group.component_ids),[]))
        unique_chain=sum(component.atoms[0].author_chain_id==atom.author_chain_id for component in chains)==1
        # TER-separated heterogens share author labels only when the polymer identity is unambiguous.
        scope.update(component.component_id for component in manifest.components
            if component.atoms[0].chain_instance_id==atom.chain_instance_id
            or unique_chain and atom.author_chain_id and component.atoms[0].author_chain_id==atom.author_chain_id)
    return scope


def resolve_preparation(deps, request):
    from uuid import UUID
    from backend.services.jobs import get_owned_dataset
    from backend.services.protein_contexts import _protein_file_or_400
    from backend.services.prepared_receptors import get_component_manifest, _validate_edits
    state=deps.session_context or {}
    identity=(state.get('assets') or {}).get('protein_dataset_id')
    if not identity:
        raise ValueError('Confirm an original protein file in the input card before preparation.')
    dataset=get_owned_dataset(deps.db,UUID(identity),deps.user_id)
    fields=state.get('confirmed_fields') or {}
    file=_protein_file_or_400(deps.db,dataset.id,fields.get('protein_file_id',{}).get('value'))
    current=((state.get('task_plan') or {}).get('definition') or {}).get('preparation') or {}
    previous=confirmed_preparation(state,dataset.id,file.id,file.sha256)
    if not previous and request.selected_chain_component_ids is None:
        raise ValueError('Inspect the target chain evidence and select one or more actual chain component IDs.')
    source=StructureSource(dataset_id=dataset.id,file_id=file.id,sha256=file.sha256,
        model_id=previous.get('source',{}).get('model_id','1'))
    manifest=get_component_manifest(source,deps.db,deps.user_id)
    edits=dict(previous.get('edits',{}))
    for key in ('excluded_component_ids','retained_component_ids','altloc_choices'):
        if key in request.model_fields_set:
            edits[key]=getattr(request,key)
    excluded=set(edits.get('excluded_component_ids',[]))
    if request.selected_chain_component_ids is not None:
        selected=set(request.selected_chain_component_ids)
        known={component.component_id for component in manifest.components
            if component.selection_kind=='chain_records' and component.atoms}
        if not selected or not selected <= known:
            raise ValueError('Choose one or more actual chain component IDs from inspect_session_protein.')
        component_ids={component.component_id for component in manifest.components}
        previous_edits=previous.get('edits',{})
        if 'excluded_component_ids' not in request.model_fields_set and (
                known & set(previous_edits.get('excluded_component_ids',[]))
                or known & set(previous_edits.get('retained_component_ids',[]))):
            previous_selected=known-set(previous_edits.get('excluded_component_ids',[]))
            excluded.difference_update(component_ids-_chain_scope_component_ids(manifest,previous_selected))
        outside=component_ids-_chain_scope_component_ids(manifest,selected)
        excluded.difference_update(known)
        excluded.update(outside)
        retained=set(edits.get('retained_component_ids',[]))
        retained.difference_update(known|outside)
        retained.update(selected)
        edits['retained_component_ids']=sorted(retained)
    edits['excluded_component_ids']=sorted(excluded)
    options={**previous.get('preparation',{}),**request.options.model_dump(exclude_unset=True)}
    spec=PreparedReceptorSpec(version=2,source=source,edits=ComponentEdits(**edits),
        preparation=PreparationChoices.model_validate(options))
    _validate_edits(spec,manifest)
    saved_name=current.get('name') if current.get('prepared_spec') is previous else fields.get('name',{}).get('value')
    result = {'name':request.name or saved_name or f'{dataset.name} prepared'[:255],'prepared_spec':spec.model_dump(mode='json')}
    if request.selected_chain_component_ids:
        result['target_chain_component_id'] = request.target_chain_component_id or request.selected_chain_component_ids[0]
        result['chain_selection_reason'] = request.chain_selection_reason
    else:
        result.update({key: current[key] for key in ('target_chain_component_id', 'chain_selection_reason') if key in current})
    return result


def normalize_stage_request(deps, output, message):
    """Convert a requested goal to the currently actionable stage, without execution."""
    from backend.agent.task_plan import TaskPlan, PlannedWorkflow
    from backend.agent.schemas import ResultSelection
    from backend.agent.language import completion_text
    if output.prefilter_request is not None:
        from tarpass.filters import validate_filters
        validate_filters([rule.model_dump(mode='json') for rule in output.prefilter_request], pre=True)
        if output.task_plan and output.task_plan.workflow:
            output.task_plan.workflow.postprocessing.prefilters = output.prefilter_request
    state=deps.session_context or {}
    assets=state.get('assets') or {}
    if output.site_request and (assets.get('protein_context_id') or assets.get('prepared_receptor_id')) and output.preparation_request is None:
        if output.task_plan and output.task_plan.workflow and output.generation_request is None:
            output.generation_request = output.task_plan.workflow.generation
        output.future_selection = output.future_selection or output.selection
        output.selection = None
        output.operation = 'ask'
        output.quantity_patch = None
        output.task_plan = None
        output.values = {}
        output.assets = {}
        output.missing_requirements = list(dict.fromkeys([*output.missing_requirements, 'site']))
        return output
    if output.operation == 'prepare' and output.preparation_request is None and 'prepared_spec' in output.missing_requirements:
        return output
    selection=output.future_selection or output.selection
    if selection and (output.future_selection or output.preparation_request or output.generation_request):
        from backend.agent.catalog import CATALOG
        metrics=[selection.sort_by,*[rule.metric for rule in selection.filters],*selection.summary_metrics]
        if any(metric and metric!='molecule_id' and not CATALOG.validate_sort_field(metric) for metric in metrics):
            raise ValueError('Use canonical metric identifiers from get_metric_spec for future ranking and filters.')
    if output.future_selection and output.task_plan and output.task_plan.workflow:
        output.task_plan.workflow.selection=ResultSelection(**{key:value for key,value in output.future_selection.model_dump().items()
            if key in ResultSelection.model_fields})
    if output.operation == 'ask' or (output.preparation_request is None and output.generation_request is None):
        return output
    if output.operation not in {'prepare','plan','modify','task_plan'}:
        raise ValueError('Use prepare or plan for preparation_request/generation_request; use ask without requests for explanations.')
    if output.task_plan is not None or output.preparation_request and output.values.get('prepared_spec'):
        raise ValueError('Return preparation_request/generation_request without task_plan or values.prepared_spec. The backend constructs the current stage from these requests.')
    current=(state.get('task_plan') or {}).get('definition') or {}
    preferences=state.get('workflow_preferences') or {}
    saved_values=(state.get('scientific_state') or {}).get('values') or {}
    extras={key:output.values.get(key,current.get(key,saved_values.get(key,default)))
        for key,default in (('key_interactions',[]),('reference_dataset_id',None))}
    choice=output.postprocessing_choice or (preferences.get('postprocessing') or {}).get('choice')
    generation=output.generation_request
    config=generation.model_dump(mode='json') if generation else (current.get('workflow') or {}).get('generation') or preferences.get('generation')
    previous=(state.get('scientific_state') or {}).get('workflow') or {}
    previous=current.get('workflow') or previous.get('plan')
    if generation and previous and previous.get('generator')==generation.engine:
        config={**previous['generation'],**generation.model_dump(mode='json',exclude_unset=True)}
    if config is None and current.get('workflow'):
        config=current['workflow']['generation']
    result_selection=ResultSelection(**{key:value for key,value in selection.model_dump().items()
        if key in ResultSelection.model_fields}) if selection else None
    workflow=None
    if config:
        engine=config['engine']
        data={**(previous if previous and previous.get('generator')==engine else {}),
            'generator':engine,'template':f'{engine}_tarpass_v1','generation':config,
            'protein_context_id':assets.get('protein_context_id')}
        if choice:
            data['postprocessing']={**(previous or {}).get('postprocessing',{}),'enabled':choice=='run'}
        elif previous:
            data['postprocessing']=dict(previous['postprocessing'])
        prefilters = output.prefilter_request
        if prefilters is not None:
            data.setdefault('postprocessing', {})['prefilters'] = [rule.model_dump(mode='json') for rule in prefilters]
        elif 'prefilters' in preferences.get('postprocessing', {}):
            data.setdefault('postprocessing', {})['prefilters'] = preferences['postprocessing']['prefilters']
        if result_selection:
            data['selection']=result_selection
        elif previous:
            data['selection']=previous.get('selection',{})
        data['missing_requirements']=[item for item in data.get('missing_requirements',[]) if item!='ligand_dataset_id']
        workflow=PlannedWorkflow(**data)
        if engine in {'epso','delete'} and not (assets.get('ligand_dataset_id') or assets.get('optimization_seed')
                or workflow.seed_source or saved_values.get('generation_reference')):
            # The stage stays visible but is marked: it cannot run until a second-kind file or a reference ligand is provided.
            workflow.missing_requirements=list(dict.fromkeys([*workflow.missing_requirements,'ligand_dataset_id']))
    if assets.get('protein_context_id') and output.preparation_request is None:
        if workflow is None:
            raise ValueError('A generation goal requires generation_request with the requested engine and count.')
        output.task_plan=TaskPlan(stage='generation',goal=current.get('goal') or state.get('goal') or message,
            completion=completion_text('generation', deps.safety_assessment.get('language', 'en')),workflow=workflow,**extras)
    else:
        if not assets.get('protein_dataset_id'):
            raise ValueError('Confirm the protein input first; return ask with missing_requirements=["protein_dataset_id"].')
        preparation=resolve_preparation(deps,output.preparation_request) if output.preparation_request else (
            current.get('preparation') or resolve_preparation(deps,PreparationRequest()))
        output.values={**output.values,'name':preparation.get('name','Prepared receptor'),'prepared_spec':preparation['prepared_spec']}
        output.task_plan=TaskPlan(stage='preparation',goal=current.get('goal') or state.get('goal') or message,
            completion=completion_text('preparation', deps.safety_assessment.get('language', 'en')),preparation=preparation,workflow=workflow,**extras)
        output.remaining_goal=output.remaining_goal or (message if workflow else '')
    output.operation='task_plan'
    return output


def repair_stage_decision(deps, decision, correction, message):
    from backend.agent.session_schemas import SessionDecision
    data = decision.model_dump(mode='json')
    for field in ('site_request', 'prefilter_request', 'generation_request'):
        if field in correction:
            data[field] = correction[field]
    if correction.get('unresolved_requirements'):
        from backend.agent.clarification import presentation_fields
        fields = presentation_fields(correction['unresolved_requirements'], data.get('clarification_fields', []))
        data.update(operation='ask', task_plan=None, assets={}, values={}, generation_request=None,
            preparation_request=None, future_selection=None, selection=None,
            missing_requirements=correction['unresolved_requirements'],
            clarification_fields=[{'requirement': field['requirement'], 'id': field['id']} for field in fields])
    elif data.get('task_plan') and data['task_plan'].get('workflow'):
        workflow = data['task_plan']['workflow']
        if 'prefilter_request' in correction:
            workflow['postprocessing']['prefilters'] = correction['prefilter_request']
        if correction.get('generation_request'):
            generation = correction['generation_request']
            workflow.update(generator=generation['engine'], generation=generation,
                template=f"{generation['engine']}_tarpass_v1")
    result = SessionDecision.model_validate(data)
    if result.prefilter_request is not None:
        from tarpass.filters import validate_filters
        validate_filters([rule.model_dump(mode='json') for rule in result.prefilter_request], pre=True)
    if result.site_request and not correction.get('unresolved_requirements') and (not result.task_plan or result.task_plan.stage != 'preparation'):
        result = normalize_stage_request(deps, result, message)
    return result
