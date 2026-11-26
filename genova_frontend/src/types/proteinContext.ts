export interface ResidueRef {
  chain_id: string
  residue_number: number
  insertion_code: string
  residue_name: string
  center?: number[]
  heavy_atom_count?: number
}

export interface LigandRef extends ResidueRef {
  source?: 'pdb'
  key?: string
  atom_count?: number
  heavy_atom_count?: number
  bounds?: { min: number[]; max: number[] }
  box?: { center: number[]; size: number[] }
}

export interface UploadedLigandRef {
  source: 'uploaded'
  dataset_id: string
  file_id: string
}

export interface ProteinAnalysis {
  version: number
  source_file_id: string
  source_sha256: string | null
  chains: Array<{ chain_id: string; residue_count: number }>
  residues: ResidueRef[]
  ligands: Array<LigandRef & { key: string; heavy_atom_count: number; center: number[] }>
}

export interface FileIdentity { dataset_id: string; file_id: string; sha256: string }
export interface SourceIdentity extends FileIdentity { model_id: string }
export interface PreparationErrorInfo {
  error_code: string; error_category: 'input' | 'runtime' | 'cache' | 'canceled'
  message: string; stage: string; objects: string[]; recovery_action: string
}
export interface SourceAtom {
  atom_id: string; residue_id: string; chain_instance_id: string; source_record: number
  label_asym_id?: string | null
  record_type: 'ATOM' | 'HETATM'; author_chain_id: string; author_residue_number: number
  insertion_code: string; residue_name: string; atom_name: string; altloc: string; element: string
  coordinates: number[]; occupancy: number
}
export interface ComponentManifest {
  version: 2; source: SourceIdentity; coordinate_frame_id: string
  inventory_policy?: 'generation_auto_v1'; source_format?: 'pdb' | 'mmcif'; inventory_error?: string | null
  components: Array<{ component_id: string; selection_kind: string; atoms: SourceAtom[] }>
  selection_groups?: Array<{ group_id: string; kind: 'polymer_with_caps'; component_ids: string[] }>
  declared_connections?: Array<{ atom_ids: string[]; component_ids: string[]; evidence: string }>
  external_coordination_connections?: Array<{ atom_ids: string[]; component_ids: string[]; evidence: 'LINK' | 'CIF:metalc'; symmetry_operations: [string, string] }>
}
export interface PreparedSpec {
  version: 2; source: SourceIdentity; edits: { excluded_component_ids: string[]; altloc_choices?: Record<string, string>; retained_component_ids?: string[] }
  preparation: {
    receptor_policy: 'protein_metals_v1'; scope_policy: 'supported_protein_v1'; strategy: 'generation_auto_v1'; water_policy: 'remove_all'
    mode: 'standard'; repair_missing_atoms: boolean
    missing_residue_policy: 'report_only'; nonstandard_policy: 'preserve' | 'standardize_supported'
    protonation_policy: 'recompute' | 'preserve'; ph: number | null
    minimization_policy: 'restrained_if_supported' | 'none'
  }
}
export interface PreparedReceptor extends PreparedSpec {
  id: string; name: string; status: 'draft' | 'processing' | 'ready' | 'failed'
  component_manifest: ComponentManifest; execution?: { status: string; job_id: string; error?: string; error_info?: PreparationErrorInfo; stage?: string }
  artifacts?: Record<'prepared_complex' | 'atom_map' | 'component_manifest' | 'report' | 'context_receptor' | 'context_receptor_map', FileIdentity>
  context_receptor_manifest?: ComponentManifest | null
  capabilities?: Record<string, any>
  failure_artifacts?: { report: FileIdentity }
}
export interface BindingSite {
  anchor: { kind: 'source_components'; source: SourceIdentity; component_ids: string[]; coordinate_frame_id: string }
    | { kind: 'prepared_residues'; residue_ids: string[]; coordinate_frame_id: string }
    | { kind: 'coordinates'; coordinates: number[][]; coordinate_frame_id: string }
  box: { center: number[]; size: number[] }; exclude_from_receptor: string[]; center_policy: 'manual' | 'anchor_bounds'
}
export interface GenerationReference {
  structure: FileIdentity; chemical_mapping?: FileIdentity | null; coordinate_frame_id: string; source_structure?: FileIdentity
}
export interface SourceComponentReference {
  kind: 'source_component'; source_component_id: string; coordinate_frame_id: string
}
export interface ProteinContextV4 {
  version: 4; id: string; name: string; status: string; prepared_receptor_id: string; prepared_artifact_sha256: string
  site: BindingSite; generation_reference: GenerationReference | SourceComponentReference | null
  artifacts: { effective_receptor: FileIdentity; anchor_coordinates: FileIdentity }; capabilities: Record<string, any>
  input_parameters?: { version: 1; ph: number; condition_seed: number }
  compatibility?: { version: 1; job_id: string; models: Record<string, { status: string; artifacts?: Record<string,FileIdentity>; error?: string; error_info?: PreparationErrorInfo; reason?: string; model_scope?: { condition_missing?: boolean; ignored_components?: Array<{residue_names: string[]; near_site: boolean}> } }> }
  created_at: string; updated_at: string
}
const metalElements = new Set('LI BE NA MG AL K CA SC TI V CR MN FE CO NI CU ZN GA RB SR Y ZR NB MO TC RU RH PD AG CD IN SN CS BA LA CE PR ND PM SM EU GD TB DY HO ER TM YB LU HF TA W RE OS IR PT AU HG TL PB BI PO FR RA AC TH PA U NP PU AM CM BK CF ES FM MD NO LR RF DB SG BH HS MT DS RG CN NH FL MC LV'.split(' '))
export function isMetalComponent(component: ComponentManifest['components'][number]) {
  const atoms = component.atoms.filter(a => !['H', 'D'].includes(a.element))
  return atoms.length > 0 && new Set(atoms.map(a => a.atom_name)).size === 1 && atoms.every(a => metalElements.has(a.element))
}
export type ProteinContext = ProteinContextV4
export interface ProteinContextListItem {
  id: string
  name: string
  status: string
  ready: boolean
}
export const contextBox = (context: ProteinContext) => context.site.box
export const contextReceptorFile = (context: ProteinContext | null | undefined) => context?.artifacts?.effective_receptor.file_id
export const contextReferenceFile = (context: ProteinContext | null | undefined, engine = 'delete') => {
  const prepared = context?.compatibility?.models[engine]?.artifacts?.reference_ligand || Object.values(context?.compatibility?.models || {}).find(row => ['full','limited'].includes(row.status) && row.artifacts?.reference_ligand)?.artifacts?.reference_ligand
  if (prepared) return prepared.file_id
  const ref = context?.generation_reference
  return ref && !('kind' in ref) ? ref.structure.file_id : undefined
}
type GenerationReferenceSource = ProteinContext['generation_reference']
interface SavedReference {
  generation_reference?: GenerationReferenceSource
  reference_ligand_file_id?: string | null
}

export function sourceReferenceId(source: GenerationReferenceSource | undefined) {
  return source ? ('kind' in source ? source.source_component_id : source.structure.file_id) : undefined
}

// Job snapshots bind the original structure or component. Model-specific preview files have their own IDs.
export function matchesSavedReference(context: ProteinContext | null | undefined, snapshot: SavedReference | undefined) {
  if (!context || !snapshot) return false
  const current = context.generation_reference
  const saved = snapshot.generation_reference
  if (saved === undefined) {
    return 'reference_ligand_file_id' in snapshot && !(current && 'kind' in current)
      && (snapshot.reference_ligand_file_id ?? undefined) === sourceReferenceId(current)
  }
  if (!current || !saved) return saved === current && !snapshot.reference_ligand_file_id
  if (saved.coordinate_frame_id !== current.coordinate_frame_id) return false
  if ('kind' in saved || 'kind' in current) {
    return 'kind' in saved && 'kind' in current && saved.source_component_id === current.source_component_id
  }
  return saved.structure.dataset_id === current.structure.dataset_id && saved.structure.file_id === current.structure.file_id
    && saved.structure.sha256 === current.structure.sha256
    && (!snapshot.reference_ligand_file_id || snapshot.reference_ligand_file_id === current.structure.file_id)
}

export function savedEpsoSeed(params: Record<string, any>) {
  const settings = params.property_optimization
  if (settings?.engine !== 'epso') return
  // Workflow jobs record the same input metadata in property_optimization.
  const source = params.seed_source ?? settings
  if (!('reference_ligand_file_id' in source)) return
  const reference = params.structure_context?.generation_reference
  const fileId = source.reference_ligand_file_id ?? (!params.seed_source && !source.ligand_dataset_id
    && reference?.kind === 'source_component' ? reference.source_component_id : undefined)
  if (fileId) return { fileId, datasetId: source.ligand_dataset_id || '' }
}

export function isProteinContextReady(context: ProteinContext | null | undefined, engine?: string) {
  if (!context || context.version !== 4 || context.status !== 'ready' || !context.artifacts?.effective_receptor) return false
  if (context.capabilities.receptor_policy !== 'protein_metals_v1' || context.capabilities.input_preparation !== 'context_features_v1') return false
  if (engine === 'tarpass') return context.capabilities.structure_validation === 'passed'
  if (engine) return context.capabilities.structure_validation === 'passed' && ['full', 'limited'].includes(context.compatibility?.models[engine]?.status || '')
  return context.capabilities.structure_validation === 'passed'
}
