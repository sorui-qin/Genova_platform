from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, StringConstraints,
    field_validator, model_validator, model_serializer,
)


Identifier = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Vector3 = tuple[Number, Number, Number]
PositiveNumber = Annotated[Number, Field(gt=0)]


class StructureContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("version", mode="before", check_fields=False)
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("version must be an integer")
        return value


class FileIdentity(StructureContract):
    dataset_id: UUID
    file_id: UUID
    sha256: Sha256


class StructureSource(FileIdentity):
    model_id: Identifier


class ComponentEdits(StructureContract):
    altloc_choices: dict[Identifier, Annotated[str, StringConstraints(min_length=1, max_length=1)]] = Field(default_factory=dict)
    excluded_component_ids: list[Identifier] = Field(default_factory=list)
    retained_component_ids: list[Identifier] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def explicit_retention(self, handler):
        value = handler(self)
        if not self.retained_component_ids:
            value.pop("retained_component_ids", None)
        return value

    @model_validator(mode="after")
    def conflicting_selections(self):
        if set(self.retained_component_ids) & set(self.excluded_component_ids):
            raise ValueError("Conflicting retained and excluded components")
        if len(self.retained_component_ids) != len(set(self.retained_component_ids)):
            raise ValueError("Duplicate retained component IDs")
        return self

    @field_validator("excluded_component_ids")
    @classmethod
    def canonical_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate component IDs")
        return sorted(value)




class PreparationOptions(StructureContract):
    strategy: Literal["generation_auto_v1"]
    water_policy: Literal["remove_all"]
    scope_policy: Literal["supported_protein_v1"]
    receptor_policy: Literal["protein_metals_v1"]
    mode: Literal["standard"] = "standard"
    repair_missing_atoms: StrictBool = True
    missing_residue_policy: Literal["report_only"] = "report_only"
    nonstandard_policy: Literal["preserve", "standardize_supported"] = "standardize_supported"
    protonation_policy: Literal["recompute", "preserve"] = "recompute"
    ph: Annotated[Number, Field(ge=0, le=14)] | None = 7.4
    minimization_policy: Literal["restrained_if_supported", "none"] = "none"

    @model_validator(mode="after")
    def consistent_operations(self):
        if self.nonstandard_policy == "standardize_supported" and (not self.repair_missing_atoms or self.protonation_policy != "recompute" or self.mode != "standard"):
            raise ValueError("Standardization requires standard preparation, atom repair and recomputed protonation")
        if (self.protonation_policy == "recompute") != (self.ph is not None):
            raise ValueError("ph is required only when recomputing protonation")
        return self


class PreparedReceptorSpec(StructureContract):
    version: Literal[2]
    source: StructureSource
    edits: ComponentEdits = Field(default_factory=ComponentEdits)
    preparation: PreparationOptions



class PreparedReceptorCreate(PreparedReceptorSpec):
    name: Annotated[Identifier, Field(max_length=255)]


class SourceAtom(StructureContract):
    @model_serializer(mode="wrap")
    def source_fields(self, handler):
        value = handler(self)
        for key in ("label_asym_id", "label_seq_id"):
            if value.get(key) is None:
                value.pop(key, None)
        return value

    label_asym_id: str | None = None
    label_seq_id: str | None = None
    occupancy: Annotated[Number, Field(ge=0)]
    atom_id: Identifier
    residue_id: Identifier
    chain_instance_id: Identifier
    source_record: Annotated[int, Field(strict=True, gt=0)]
    record_type: Literal["ATOM", "HETATM"]
    author_chain_id: str
    author_residue_number: Annotated[int, Field(strict=True)]
    insertion_code: str
    residue_name: Identifier
    atom_name: Identifier
    altloc: str
    element: Identifier
    coordinates: Vector3


class ComponentInstance(StructureContract):
    component_id: Identifier
    selection_kind: Literal["chain_records", "heterogen_residue_records"]
    atoms: Annotated[list[SourceAtom], Field(min_length=1)]


class ComponentSelectionGroup(StructureContract):
    group_id: Identifier
    component_ids: Annotated[list[Identifier], Field(min_length=2)]
    kind: Literal['polymer_with_caps']


class CifAtomIdentity(StructureContract):
    source_atom_id: Identifier
    cif_atom_site_id: Identifier
    label_asym_id: str
    auth_asym_id: str
    label_seq_id: str
    auth_seq_id: str
    label_atom_id: str
    auth_atom_id: str


class ComponentConnection(StructureContract):
    atom_ids: tuple[Identifier, Identifier]
    component_ids: tuple[Identifier, Identifier]
    evidence: Identifier


class ExternalCoordinationConnection(ComponentConnection):
    evidence: Literal['LINK', 'CIF:metalc']
    symmetry_operations: tuple[Identifier, Identifier]

    @model_validator(mode='after')
    def external_partner(self):
        if all(value.replace('_', '') == '1555' for value in self.symmetry_operations):
            raise ValueError('External coordination requires a crystallographic partner')
        return self


class ComponentManifest(StructureContract):
    @model_serializer(mode="wrap")
    def inventory_fields(self, handler):
        value = handler(self)
        for key in ("inventory_policy", "source_format", "inventory_error"):
            if value.get(key) is None:
                value.pop(key, None)
        return value

    version: Literal[2] = 2
    source: StructureSource
    coordinate_frame_id: Identifier
    coordinate_unit: Literal["angstrom"] = "angstrom"
    chemistry_status: Literal["not_evaluated"] = "not_evaluated"
    components: list[ComponentInstance]
    inventory_policy: Literal["generation_auto_v1"] | None = None
    source_format: Literal["pdb", "mmcif"] | None = None
    inventory_error: str | None = None
    selection_groups: list[ComponentSelectionGroup] = Field(default_factory=list)
    original_structure: FileIdentity | None = None
    author_label_mapping: list[CifAtomIdentity] = Field(default_factory=list)
    declared_connections: list[ComponentConnection] = Field(default_factory=list)
    external_coordination_connections: list[ExternalCoordinationConnection] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_identities(self):
        if self.inventory_policy != "generation_auto_v1" and any(atom.occupancy > 1 for component in self.components for atom in component.atoms):
            raise ValueError("Occupancy exceeds one")
        if not self.components and not self.inventory_error:
            raise ValueError("Structure contains no atoms")
        components = [item.component_id for item in self.components]
        atoms = [atom.atom_id for item in self.components for atom in item.atoms]
        records = [atom.source_record for item in self.components for atom in item.atoms]
        if len(components) != len(set(components)) or len(atoms) != len(set(atoms)) or len(records) != len(set(records)):
            raise ValueError("Duplicate source identities")
        return self



class PreparedReceptorSummary(StructureContract):
    id: UUID
    name: str
    status: Literal["draft", "processing", "ready", "failed"]
    job_id: UUID | None = None


class PreparedReceptorOut(PreparedReceptorCreate):
    id: UUID
    status: Literal["draft", "processing", "ready", "failed"]
    component_manifest: ComponentManifest
    context_receptor_manifest: ComponentManifest | None = None
    execution: dict | None = None
    artifacts: "PreparedArtifacts | None" = None
    capabilities: dict | None = None
    failure_artifacts: dict | None = None
    created_at: datetime
    updated_at: datetime


class AtomMappingEntry(StructureContract):
    change: Literal["retained", "added", "deleted", "renamed", "replaced"]
    source_atom_id: Identifier | None
    output_atom_id: Identifier | None
    source_residue_id: Identifier | None
    output_residue_id: Identifier | None

    @model_validator(mode="after")
    def endpoints(self):
        source = self.source_atom_id is not None and self.source_residue_id is not None
        output = self.output_atom_id is not None and self.output_residue_id is not None
        if self.change == "added":
            valid = output and self.source_atom_id is None and self.source_residue_id is None
        elif self.change == "deleted":
            valid = source and self.output_atom_id is None and self.output_residue_id is None
        else:
            valid = source and output
        if not valid:
            raise ValueError("Mapping endpoints do not match change")
        return self


class SourceMapping(StructureContract):
    @model_serializer(mode="wrap")
    def tool_fields(self, handler):
        value = handler(self)
        if self.tool_mapping is None:
            value.pop("tool_mapping", None)
        return value

    version: Literal[1] = 1
    source: StructureSource
    output: FileIdentity
    source_coordinate_frame_id: Identifier
    output_coordinate_frame_id: Identifier
    entries: Annotated[list[AtomMappingEntry], Field(min_length=1)]
    tool_mapping: dict | None = None
    @model_validator(mode="after")
    def one_coordinate_frame(self):
        if self.source_coordinate_frame_id != self.output_coordinate_frame_id:
            raise ValueError("Coordinate transforms are not supported by mapping version 1")
        for field in ("source_atom_id", "output_atom_id"):
            ids = [getattr(item, field) for item in self.entries if getattr(item, field) is not None]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate mapping endpoint")
        return self


class PreparedArtifacts(StructureContract):
    prepared_complex: FileIdentity
    atom_map: FileIdentity
    component_manifest: FileIdentity
    report: FileIdentity
    context_receptor: FileIdentity
    context_receptor_map: FileIdentity



class SourceComponentsAnchor(StructureContract):
    kind: Literal["source_components"]
    source: StructureSource
    component_ids: Annotated[list[Identifier], Field(min_length=1)]
    coordinate_frame_id: Identifier


class PreparedResiduesAnchor(StructureContract):
    kind: Literal["prepared_residues"]
    residue_ids: Annotated[list[Identifier], Field(min_length=1)]
    coordinate_frame_id: Identifier


class CoordinatesAnchor(StructureContract):
    kind: Literal["coordinates"]
    coordinates: Annotated[list[Vector3], Field(min_length=1)]
    coordinate_frame_id: Identifier


class SiteBox(StructureContract):
    center: Vector3
    size: tuple[PositiveNumber, PositiveNumber, PositiveNumber]


class BindingSite(StructureContract):
    anchor: Annotated[SourceComponentsAnchor | PreparedResiduesAnchor | CoordinatesAnchor, Field(discriminator="kind")]
    box: SiteBox
    exclude_from_receptor: list[Identifier] = Field(default_factory=list)
    center_policy: Literal["manual", "anchor_bounds"]

    @model_validator(mode="after")
    def unique_selections(self):
        for values in (self.exclude_from_receptor, getattr(self.anchor, "component_ids", []), getattr(self.anchor, "residue_ids", [])):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate site selection")
        return self


class GenerationReference(StructureContract):
    structure: FileIdentity
    chemical_mapping: FileIdentity | None = None
    coordinate_frame_id: Identifier
    source_structure: FileIdentity | None = None


class SourceComponentReference(StructureContract):
    kind: Literal['source_component']
    source_component_id: Identifier
    coordinate_frame_id: Identifier



class ModelInputParameters(StructureContract):
    version: Literal[1] = 1
    ph: Annotated[Number, Field(ge=0, le=14)] = 7.4
    condition_seed: Annotated[int, Field(strict=True, ge=0, le=4294967295)] = 42


class ProteinContextV4(StructureContract):
    version: Literal[4]
    input_parameters: ModelInputParameters | None = None
    prepared_receptor_id: UUID
    prepared_artifact_sha256: Sha256
    site: BindingSite
    generation_reference: GenerationReference | SourceComponentReference | None = None
    derived_from_context_id: UUID | None = None

    @model_validator(mode="after")
    def reference_frame(self):
        if self.generation_reference and self.generation_reference.coordinate_frame_id != self.site.anchor.coordinate_frame_id:
            raise ValueError("Reference coordinate frame mismatch")
        return self




class ProteinContextV4Create(ProteinContextV4):
    generation_reference: GenerationReference | SourceComponentReference | None = None
    name: Annotated[Identifier, Field(max_length=255)]


class SiteArtifacts(StructureContract):
    effective_receptor: FileIdentity
    anchor_coordinates: FileIdentity


class ProteinContextV4Record(ProteinContextV4):
    @model_validator(mode="after")
    def current_preparation(self):
        required = {"preparation_strategy": "generation_auto_v1", "receptor_policy": "protein_metals_v1", "input_preparation": "context_features_v1"}
        if any(self.capabilities.get(key) != value for key, value in required.items()):
            raise ValueError("Unsupported Protein Context preparation contract")
        return self

    input_parameters: ModelInputParameters
    artifacts: SiteArtifacts
    capabilities: dict
    compatibility: dict = Field(default_factory=dict)
