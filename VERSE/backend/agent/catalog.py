"""Capability Catalog — the single source of truth for what the agent can plan.

All generator availability, allowed parameters, workflow templates, and
TarPass metrics are registered here.  The agent must never infer capabilities
from README files, model knowledge, or any source other than this catalog.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from genova_runtime.epso_objectives import AFFINITY_COUNT_LIMIT
from genova_runtime.generation_settings import COUNT_LIMITS, DEFAULT_GENERATION_COUNT


# ---------------------------------------------------------------------------
# Generator registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeneratorSpec:
    name: str
    enabled: bool
    phase: str  # e.g. "p1", "phase_2", "phase_3"
    description: str
    required_context: list[str] = field(default_factory=list)
    allowed_params: dict[str, Any] = field(default_factory=dict)


GENERATORS: dict[str, GeneratorSpec] = {
    "surfgen": GeneratorSpec("surfgen", True, "production", "SurfGen generation from a local protein surface. A reference ligand can locate the surface region; otherwise the selected site's anchor coordinates locate it. Outputs SMILES CSV and original three-dimensional SDF poses", ["protein_context_id", "prepared_protein", "docking_box"], {"num_molecules": {"type": "int", "min": 1, "max": COUNT_LIMITS["surfgen"], "default": DEFAULT_GENERATION_COUNT}}),
    "ecloudgen": GeneratorSpec("ecloudgen", True, "production", "ECloudGen protein-pocket-conditioned generation; reference ligand optional, using the saved site center when absent; outputs SMILES CSV without original three-dimensional poses. TarPass can subsequently generate conformations and dock them", ["protein_context_id", "prepared_protein", "docking_box"], {"target_num_molecules": {"type": "int", "min": 1, "max": COUNT_LIMITS["ecloudgen"], "default": DEFAULT_GENERATION_COUNT}, "noise": {"type": "fixed", "value": 0.1}}),
    "delete": GeneratorSpec("delete", True, "production", "DELETE lead optimization from an explicit molecular edit; outputs SMILES CSV and original three-dimensional SDF poses", ["protein_context_id", "prepared_protein", "reference_ligand", "docking_box"], {"num_molecules": {"type": "int", "min": 1, "max": COUNT_LIMITS["delete"], "default": DEFAULT_GENERATION_COUNT}, "edit_modes": ["r_group", "side_chain", "linker", "scaffold_hopping", "custom", "derivation_site"]}),
    "epso": GeneratorSpec("epso", True, "production", "EPSO latent-space optimization from a seed ligand, optionally guided by Gnina docking energy; outputs SMILES CSV, trajectory and metadata for two-dimensional molecule display, without original three-dimensional poses. TarPass can subsequently generate conformations and dock them", ["protein_context_id", "prepared_protein", "reference_ligand", "docking_box"], {"num_molecules": {"type": "int", "min": 1, "max": COUNT_LIMITS["epso"], "max_with_gnina_affinity": AFFINITY_COUNT_LIMIT, "default": 100}, "objective_metrics": ["qed", "sa", "mw", "logp", "lipinski", "hba", "hbd", "heavy_atom_count", "similarity", "gnina_affinity"], "objective_modes": ["lower_bound", "upper_bound", "range", "target", "maximize", "minimize", "seed_relative"], "default_optimizer": {"num_particles": 200, "num_swarms": 1, "num_steps": 20, "seed": 2024}, "optimizer_limits": {"num_particles": 1000, "num_steps": 1000, "evaluations": 20000}}),
}


# ---------------------------------------------------------------------------
# Workflow templates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowTemplate:
    key: str
    enabled: bool
    generator: str
    description: str


WORKFLOW_TEMPLATES: dict[str, WorkflowTemplate] = {
    "surfgen_tarpass_v1": WorkflowTemplate("surfgen_tarpass_v1", True, "surfgen", "SurfGen followed by TarPass"),
    "ecloudgen_tarpass_v1": WorkflowTemplate("ecloudgen_tarpass_v1", True, "ecloudgen", "ECloudGen followed by TarPass"),
    "delete_tarpass_v1": WorkflowTemplate("delete_tarpass_v1", True, "delete", "DELETE lead optimization followed by TarPass"),
    "epso_tarpass_v1": WorkflowTemplate("epso_tarpass_v1", True, "epso", "EPSO property optimization followed by TarPass"),
}


# ---------------------------------------------------------------------------
# TarPass metrics (canonical runtime definitions)
# ---------------------------------------------------------------------------

from tarpass.filters import METRICS as _ALL_METRICS
from tarpass.filters import METRIC_INFO as _METRIC_INFO
from tarpass.filters import PROPERTY_METRICS as _PROPERTY_METRICS

TARPASS_PREFILTER_METRICS: set[str] = set(_PROPERTY_METRICS)
TARPASS_SORT_FIELDS: set[str] = set(_ALL_METRICS)
TARPASS_FILTER_OPS: set[str] = {"gt", "lt", "gte", "lte", "eq"}
TARPASS_METRIC_INFO: dict[str, Any] = dict(_METRIC_INFO)


# ---------------------------------------------------------------------------
# Protocol version
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "generation-2026-09"


# ---------------------------------------------------------------------------
# Catalog facade
# ---------------------------------------------------------------------------

class CapabilityCatalog:
    """Read-only view of platform capabilities for the agent."""

    def is_generator_enabled(self, name: str) -> bool:
        spec = GENERATORS.get(name)
        return spec is not None and spec.enabled

    def get_generator(self, name: str) -> GeneratorSpec | None:
        return GENERATORS.get(name)

    def get_enabled_generators(self) -> list[GeneratorSpec]:
        return [g for g in GENERATORS.values() if g.enabled]

    def get_template(self, key: str) -> WorkflowTemplate | None:
        return WORKFLOW_TEMPLATES.get(key)

    def is_template_enabled(self, key: str) -> bool:
        tmpl = WORKFLOW_TEMPLATES.get(key)
        return tmpl is not None and tmpl.enabled

    def validate_prefilter_metric(self, metric: str) -> bool:
        return metric in TARPASS_PREFILTER_METRICS

    def validate_sort_field(self, field: str) -> bool:
        return field in TARPASS_SORT_FIELDS

    def validate_filter_op(self, op: str) -> bool:
        return op in TARPASS_FILTER_OPS

    def to_dict(self) -> dict[str, Any]:
        """Serialize catalog for the get_capabilities tool."""
        return {
            "protocol_version": PROTOCOL_VERSION,
            "generators": {
                name: {
                    "enabled": spec.enabled,
                    "phase": spec.phase,
                    "description": spec.description,
                    "required_context": spec.required_context,
                    "allowed_params": spec.allowed_params,
                }
                for name, spec in GENERATORS.items()
            },
            "workflow_templates": {
                key: {
                    "enabled": tmpl.enabled,
                    "generator": tmpl.generator,
                    "description": tmpl.description,
                }
                for key, tmpl in WORKFLOW_TEMPLATES.items()
            },
            "tarpass": {
                "prefilter_metrics": sorted(TARPASS_PREFILTER_METRICS),
                "sort_fields": sorted(TARPASS_SORT_FIELDS),
                "filter_ops": sorted(TARPASS_FILTER_OPS),
            },
        }


# Module-level singleton
CATALOG = CapabilityCatalog()
