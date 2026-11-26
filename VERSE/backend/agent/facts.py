"""Runtime parameter and metric facts, separate from reviewed explanations."""
from backend.agent.schemas import WorkflowPlan, SurfGenConfig, DeleteConfig, DeleteEditConfig, ECloudGenConfig, EPSOConfig
from backend.structure_contracts import PreparationOptions
from genova_runtime.generation_settings import DEFAULTS
from genova_runtime.epso_objectives import DEFAULT_OPTIMIZER, DEFAULT_OBJECTIVES, FIXED_PARAMETERS, OPTIMIZER_LIMITS
from tarpass.filters import METRIC_INFO, PROPERTY_METRICS


def parameter_specs():
    return {
        "generation": {"defaults": DEFAULTS, "source": "genova_runtime/generation_settings.py::generation_settings"},
        "epso": {"defaults": DEFAULT_OPTIMIZER, "objectives": DEFAULT_OBJECTIVES, "fixed": FIXED_PARAMETERS,
                 "limits": OPTIMIZER_LIMITS, "budget": "num_particles * (num_steps + 1) must not exceed limits.evaluations",
                 "source": "genova_runtime/epso_objectives.py::validate_parameters"},
        "protein_preparation": {"defaults": PreparationOptions(strategy="generation_auto_v1", water_policy="remove_all", scope_policy="supported_protein_v1", receptor_policy="protein_metals_v1").model_dump(mode="json"),
                                "source": "backend/structure_contracts.py::PreparationOptions"},
        "agent_editable_schema": WorkflowPlan.model_json_schema(),
        "scope": "Runtime defaults describe platform capabilities; agent_editable_schema describes the narrower Agent plan inputs.",
    }


def metric_specs():
    from backend.agent.knowledge.help_catalog import load_catalog
    descriptions = {key: {language: text['summary'] for language, text in entry['translations'].items()}
        for entry in load_catalog()['entries'] for key in entry['keys']}
    return {key: {**value, "stage": "property" if key in PROPERTY_METRICS else key.split(".")[0],
        "descriptions": descriptions.get(key, {}),
        "requires": (["original_pose"] if key.startswith("original.") else ["docked_pose"] if key.startswith("docked.") else [])
        + (["reference_dataset"] if key in {"reference_similarity", "scaffold_similarity"} else [])
        + (["reference_ligand"] if key.split(".")[-1] in {"sucos", "shape_similarity", "electrostatic_similarity", "centroid_shift"} else [])
        + (["key_interactions"] if key.endswith(("matched_rate", "fully_matched")) else []),
        "source": "tarpass/filters.py::METRIC_INFO"} for key, value in sorted(METRIC_INFO.items())}


def model_parameter_specs(module="generation", fields=None):
    from backend.agent.preparation import PreparationRequest
    specs = {
        "generation": {"defaults": DEFAULTS},
        "epso": {"defaults": DEFAULT_OPTIMIZER, "objectives": DEFAULT_OBJECTIVES, "fixed": FIXED_PARAMETERS, "limits": OPTIMIZER_LIMITS},
        "protein_preparation": {"defaults": PreparationRequest().options.model_dump(mode='json'),
            "request_schema": PreparationRequest.model_json_schema()},
    }
    if module == "tarpass":
        from tarpass.contracts import INTERACTION_TYPES
        from tarpass.filters import DEFAULT_PREFILTERS, FILTER_OPS
        defaults = {"prefilters": DEFAULT_PREFILTERS, "key_interactions": []}
        editable = {
            "prefilters": {"item": {"metric": sorted(PROPERTY_METRICS), "op": sorted(FILTER_OPS), "value": "finite number"},
                           "boolean_metrics": "eq with 0 or 1", "max_items": 100},
            "key_interactions": {"item": {"interaction_type": sorted(INTERACTION_TYPES), "match_mode": ["any", "all"],
                                          "residues": "selected residues of the source receptor"}, "max_items": 100},
        }
        return {"defaults": {k: v for k, v in defaults.items() if not fields or k in fields},
                "editable_fields": {k: v for k, v in editable.items() if not fields or k in fields}}
    if module in DEFAULTS or module == "epso":
        model = {"surfgen": SurfGenConfig, "delete": DeleteConfig, "ecloudgen": ECloudGenConfig, "epso": EPSOConfig}[module]
        properties = model.model_json_schema()["properties"]
        result = {"defaults": DEFAULTS.get(module, DEFAULT_OPTIMIZER),
                  "editable_fields": {k: v for k, v in properties.items() if not fields or k in fields}}
        if module == "delete" and (not fields or "edit" in fields):
            result["editable_fields"]["edit"] = DeleteEditConfig.model_json_schema()
            result["session_constraints"] = {"required_edit_field": "edit_spec_id", "confirmation": "visual_editor", "inline_supported": False}
        if module == "epso" and not fields:
            result.update(specs["epso"])
        return {**result, "defaults": {k: v for k, v in result["defaults"].items() if not fields or k in fields}}
    if module not in {"generation", "epso", "protein_preparation"}:
        return {"error": "UNKNOWN_MODULE"}
    result = specs[module]
    if fields:
        result = {**result, "defaults": {k: v for k, v in result["defaults"].items() if k in fields}}
    return result
