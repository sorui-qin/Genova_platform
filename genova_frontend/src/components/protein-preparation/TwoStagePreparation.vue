<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch, inject, watchEffect, defineAsyncComponent } from 'vue';
import { useI18n } from 'vue-i18n';
import { saveAs } from 'file-saver';
import { useRoute, useRouter } from 'vue-router';
import { downloadBackendDataset, getBackendDataset, getBackendJob, uploadBackendDataset } from '@/api/genovaBackend';
import ProteinContextSummary from './ProteinContextSummary.vue';
import PreparationErrorDetails from './PreparationErrorDetails.vue';
import type { PreparationErrorInfo } from '@/types/proteinContext';
import { createBindingSite, createPreparedReceptor, ensureProteinFile, getComponentManifest, getPreparedReceptor, getProteinContext, listPreparedReceptors, uploadProteinDataset } from '@/api/proteinContext';
import { cancelWorkflowEditor, type EditSession, getWorkflowEditor, saveWorkflowEditor, saveWorkflowEditorDraft } from '@/api/workflowCommands';
import DataCenterSelector from '@/components/common/dataCenterSelector.vue';
import ProteinViewer from '@/components/molecule/protein3d_molstar.vue';
import { previewCif } from '@/utils/structurePreview';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { type BindingSite, type ComponentManifest, type GenerationReference, isMetalComponent, type PreparedReceptor, type PreparedSpec, type ProteinContext, type ResidueRef, type SourceComponentReference } from '@/types/proteinContext';
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue';
import FeedbackState from '@/components/workbench/FeedbackState.vue';
import { useWorkspaceState, workspaceTaskKey } from '@/composables/useWorkspace';
import { useJobSubmission } from '@/composables/useJobSubmission';
import { useAgentIdentity } from '@/composables/useAgentIdentity';
import DockingBoxEditor from './DockingBoxEditor.vue';
import ResidueSelectionList from './ResidueSelectionList.vue';
import ProteinInputPanel from './ProteinInputPanel.vue';
import ProteinReferenceSelector from './ProteinReferenceSelector.vue';
import { displayErrorMessage, requestErrorKind } from '@/utils/requestError'
const props = defineProps<{
    review?: Record<string, any>;
    selection?: Record<string, any>;
    reviewReadonly?: boolean;
}>();
const emit = defineEmits<{
    reviewState: [
        state: {
            dirty: boolean;
            valid: boolean;
            changes: Record<string, any>;
        }
    ];
}>();
const { locale } = useI18n();
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en;
const route = useRoute();
const router = useRouter();
const embedded = computed(() => Boolean(props.review || props.selection));
const readonly = computed(() => Boolean(props.reviewReadonly));
const step = ref(1);
const name = ref('');
const sourceLabel = ref('');
const modelId = ref('1');
const error = ref('');
const errorInfo = ref<PreparationErrorInfo>();
// The task of a failed record opened here; its details hold the reason.
const failedJob = ref('');
const busy = ref(false);
const { pendingSubmission, confirmedJob, sendJob } = useJobSubmission('protein-preparation');
const dataOpen = ref(false);
const referenceDataOpen = ref(false);
const referenceInput = ref<HTMLInputElement | null>(null);
const manifest = ref<ComponentManifest | null>(null);
const preparedManifest = ref<ComponentManifest | null>(null);
const prepared = ref<PreparedReceptor | null>(null);
const library = ref<Pick<PreparedReceptor, 'id' | 'name' | 'status'>[]>([]);
const sourceText = ref('');
const preparedText = ref('');
const preparationReport = ref<Record<string, any> | null>(null);
const excluded = ref<string[]>([]);
const excludedByChain = ref<string[]>([]);
const hidden = ref<string[]>([]);
const altlocChoices = ref<Record<string, string>>({});
const siteExcluded = ref<string[]>([]);
const repair = ref(true);
const normalization = ref<PreparedSpec['preparation']['nonstandard_policy']>('standardize_supported');
const explicitlyRetained = ref<string[]>([]);
const chainScope = ref<'all' | 'selected'>('all');
const solventNames = new Set(['HOH', 'WAT', 'DOD', 'EDO', 'GOL', 'DMS', 'MPD', 'PEG', 'PG4']);
const waterNames = new Set(['HOH', 'WAT', 'DOD', 'H2O']);
const protonation = ref<'recompute' | 'preserve'>('recompute');
const ph = ref(7.4);
const featurePh = computed(() => prepared.value?.preparation.ph ?? 7.4);
const conditionSeed = ref(42);
let compatibilityTimer: ReturnType<typeof setTimeout> | undefined;
const minimize = ref(false);
const anchorKind = ref<BindingSite['anchor']['kind']>('source_components');
const anchorComponents = ref<string[]>([]);
const anchorResidues = ref<string[]>([]);
const coordinateAnchors = ref<number[][]>([[0, 0, 0]]);
const point = computed({ get: () => coordinateAnchors.value[0], set: (value: number[]) => { coordinateAnchors.value = [value]; } });
const center = ref([0, 0, 0]);
const size = ref([20, 20, 20]);
const boxSizeEdited = ref(false);
const generationReference = ref<GenerationReference | SourceComponentReference | null>(null);
const referenceLabel = ref('');
const savedContext = ref<ProteinContext | null>(null);
const viewer = ref<InstanceType<typeof ProteinViewer> | null>(null);
const previewError = ref('');
const pollError = ref('');
const preparationJobStatus = ref('');
const preparationStage = computed(() => ({ reading_mapping: L('读取结构', 'Reading structure'), diagnosing_planning: L('诊断结构', 'Diagnosing structure'), structure_processing: L('处理结构', 'Processing structure'), output_validation: L('验证产物', 'Validating output'), published: L('发布结果', 'Publishing results') } as Record<string, string>)[prepared.value?.execution?.stage || ''] || '');
const standardizationDetails = computed(() => {
    const operation = prepared.value?.capabilities?.operations?.standardization;
    if (!operation?.requested) return [];
    const name = (row: Record<string, any>) => `${row.residue_name || row.from_residue_name || ''}${row.chain_id ? ` ${row.chain_id}:${row.residue_number}${row.insertion_code || ''}` : ''}`;
    const impact = (row: Record<string, any>) => (row.impact || []).length ? ` · ${L('影响', 'Impact')}: ${row.impact.join(', ')}` : '';
    return [
        ...(operation.converted || []).map((row: Record<string, any>) => `${L('转换', 'Converted')}: ${name(row)} → ${row.to_residue_name}`),
        ...(operation.preserved || []).map((row: Record<string, any>) => `${L('保留', 'Preserved')}: ${name(row)}${row.reason ? ' · ' + row.reason : ''}${impact(row)}`),
        ...(operation.failed || []).map((row: Record<string, any>) => `${L('失败', 'Failed')}: ${name(row)}${row.reason ? ' · ' + row.reason : ''}${impact(row)}`),
    ];
});
const referenceText = ref('');
const referenceFormat = ref('sdf');
const referenceGeometry = ref<{ key: string; coordinates: number[][] } | null>(null);
const edit = ref<EditSession | null>(null);
let draftTimer: ReturnType<typeof setTimeout> | undefined;
let active = true;
let timer: ReturnType<typeof setTimeout> | undefined;
let baseline = '';
let previewRevision = 0;
let previewQueue = Promise.resolve();
let referencePreviewKey = '';
let scenePreviewKey = '';
const agentIdentity = useAgentIdentity();
const InlineAssistant = defineAsyncComponent(() => import('@/pages/agent/components/AgentSessionPanel.vue'));
const assistantMounted = ref(false);
const { panelOpen, panelTab } = useWorkspaceState('protein-workspace', () => String(props.selection?.session_id || props.review?.protein_dataset_id || route.query.edit_session_id || route.query.context_id || route.query.prepared_receptor_id || route.query.protein_dataset_id || 'draft'), { panelOpen: true, panelTab: 'parameters' });
watch(panelTab, tab => { if (tab === 'assistant') assistantMounted.value = true; }, { immediate: true });
const workspaceTask = inject(workspaceTaskKey, null);
watchEffect(() => {
    if (embedded.value || !workspaceTask) return;
    workspaceTask.value = sourceLabel.value ? { name: name.value || sourceLabel.value, draft: !prepared.value, stage: prepared.value ? (step.value === 2 ? L('选择位点', 'Select site') : prepared.value.status === 'processing' ? L('正在准备', 'Preparing') : L('蛋白准备', 'Prepare protein')) : undefined, context: sourceLabel.value, details: () => { panelOpen.value = true; panelTab.value = 'parameters'; } } : null;
});
const showPrepared = computed(() => Boolean(prepared.value?.artifacts && preparedManifest.value && preparedText.value));
const visibleComponents = computed(() => {
    const inventory = showPrepared.value ? step.value === 2 ? prepared.value?.context_receptor_manifest || preparedManifest.value : preparedManifest.value : manifest.value;
    const excludedIds = showPrepared.value ? step.value === 2 ? siteExcluded.value : []
        : chainScope.value === 'selected' && !selectedChains.value.length ? [] : excluded.value;
    return inventory?.components.filter(c => !excludedIds.includes(c.component_id) && !hidden.value.includes(c.component_id)).map(c => ({ ...c, atoms: c.atoms.filter(a => showPrepared.value || !a.altloc || !altlocChoices.value[a.residue_id] || altlocChoices.value[a.residue_id] === a.altloc) })) || [];
});
const proteinComponents = computed(() => manifest.value?.components.filter(c => c.selection_kind === 'chain_records') || []);
const selectedChains = computed(() => proteinComponents.value.filter(c => !excluded.value.includes(c.component_id)));
const retainedComponentIds = computed(() => {
    const proteinIds = new Set(proteinComponents.value.map(c => c.component_id));
    const retained = explicitlyRetained.value.filter(id => !proteinIds.has(id));
    if (chainScope.value === 'selected') retained.push(...selectedChains.value.map(c => c.component_id));
    return [...new Set(retained)].sort();
});
const scopedComponents = computed(() => {
    if (chainScope.value === 'all') return manifest.value?.components || [];
    const ids = new Set(selectedChains.value.flatMap(c => chainMembers(c.component_id)));
    return manifest.value?.components.filter(c => ids.has(c.component_id)) || [];
});
const waterComponents = computed(() => scopedComponents.value.filter(c => c.selection_kind !== 'chain_records' && waterNames.has(c.atoms[0].residue_name)));
const otherComponents = computed(() => scopedComponents.value.filter(c => c.selection_kind !== 'chain_records' && !solventNames.has(c.atoms[0].residue_name) && !waterNames.has(c.atoms[0].residue_name)));
const solventComponents = computed(() => scopedComponents.value.filter(c => c.selection_kind !== 'chain_records' && solventNames.has(c.atoms[0].residue_name) && !waterNames.has(c.atoms[0].residue_name)));
const modelIds = computed(() => [...new Set([...sourceText.value.matchAll(/^MODEL\s+(\S+)/gm)].map(m => m[1]))]);
const referenceCandidates = computed(() => scopedComponents.value.filter(c => c.selection_kind !== 'chain_records' && !solventNames.has(c.atoms[0].residue_name) && !waterNames.has(c.atoms[0].residue_name)));
const previewComponents = computed(() => {
    const inventory = showPrepared.value && step.value === 2
        ? [...(prepared.value?.context_receptor_manifest?.components || preparedManifest.value?.components || []), ...referenceCandidates.value]
        : showPrepared.value ? preparedManifest.value?.components || [] : scopedComponents.value;
    return [...new Map(inventory.map(component => [component.component_id, component])).values()];
});
const availableResidues = computed(() => [...new Map(((prepared.value?.context_receptor_manifest || preparedManifest.value)?.components || []).flatMap(c => c.atoms.filter(a => a.record_type === 'ATOM' && !['DA','DC','DG','DT','DI','DU','A','C','G','U','I'].includes(a.residue_name)).map(a => [a.residue_id, { residue_id: a.residue_id, chain_id: a.author_chain_id, residue_name: a.residue_name, residue_number: a.author_residue_number, insertion_code: a.insertion_code }] as const))).values()]);
const selectedResidueRows = computed(() => availableResidues.value.filter(r => anchorResidues.value.includes(r.residue_id)));
const externalLigandKey = computed(() => {
    const reference = generationReference.value;
    return reference && !('kind' in reference) ? `external:${reference.structure.dataset_id}:${reference.structure.file_id}` : '';
});
const externalCoordinates = computed(() => externalLigandKey.value && referenceGeometry.value?.key === externalLigandKey.value ? referenceGeometry.value.coordinates : []);
const externalSiteSelected = computed(() => anchorKind.value === 'coordinates' && externalCoordinates.value.length > 0 && JSON.stringify(coordinateAnchors.value) === JSON.stringify(externalCoordinates.value));
const referenceMode = computed({ get: () => externalSiteSelected.value ? 'ligand' : ({source_components: 'ligand', prepared_residues: 'residues', coordinates: 'coordinates'})[anchorKind.value], set: (value: string) => {
    if (value === 'ligand' && externalSiteSelected.value) return;
    anchorKind.value = ({ligand: 'source_components', residues: 'prepared_residues', coordinates: 'coordinates'} as const)[value as 'ligand' | 'residues' | 'coordinates'];
    if (value === 'coordinates') coordinateAnchors.value = [[...point.value]];
    selectDefaultLigand();
} });
const siteLigands = computed(() => {
    const ligands = referenceCandidates.value.map(c => ({key: label(c), chain_id: c.atoms[0].author_chain_id, residue_name: c.atoms[0].residue_name, residue_number: c.atoms[0].author_residue_number, insertion_code: c.atoms[0].insertion_code, heavy_atom_count: c.atoms.filter(a => !['H', 'D'].includes(a.element)).length, center: [0, 1, 2].map(i => c.atoms.reduce((n, a) => n + a.coordinates[i], 0) / c.atoms.length)}));
    if (externalCoordinates.value.length) ligands.push({key: externalLigandKey.value, chain_id: '', residue_name: '', residue_number: 0, insertion_code: '', heavy_atom_count: externalCoordinates.value.length, center: [0, 1, 2].map(i => externalCoordinates.value.reduce((n, a) => n + a[i], 0) / externalCoordinates.value.length)});
    return ligands;
});
const ligandKey = computed({ get: () => {
    if (externalSiteSelected.value) return externalLigandKey.value;
    const c = anchorKind.value === 'source_components' && manifest.value?.components.find(c => c.component_id === anchorComponents.value[0]);
    return c ? label(c) : '';
}, set: (value: string) => {
    if (value === externalLigandKey.value && externalCoordinates.value.length) {
        coordinateAnchors.value = externalCoordinates.value.map(point => [...point]);
        anchorKind.value = 'coordinates';
        anchorComponents.value = [];
        recenter();
        return;
    }
    anchorKind.value = 'source_components';
    const c = referenceCandidates.value.find(c => label(c) === value);
    anchorComponents.value = c ? [c.component_id] : [];
    sourceAnchorChanged();
} });

const sourceReferenceSelected = computed({ get: () => Boolean(generationReference.value && 'kind' in generationReference.value && anchorComponents.value.length === 1 && generationReference.value.source_component_id === anchorComponents.value[0]), set: (value: boolean) => { const component = referenceCandidates.value.find(c => c.component_id === anchorComponents.value[0]); generationReference.value = value && anchorComponents.value.length === 1 && component && !isMetalComponent(component) ? { kind: 'source_component', source_component_id: anchorComponents.value[0], coordinate_frame_id: preparedManifest.value!.coordinate_frame_id } : null; } });
const anchorCoordinates = computed(() => anchorKind.value === 'coordinates' ? coordinateAnchors.value : (anchorKind.value === 'source_components' ? manifest.value?.components.filter(c => anchorComponents.value.includes(c.component_id)).flatMap(c => c.atoms).filter(a => !a.altloc || !altlocChoices.value[a.residue_id] || altlocChoices.value[a.residue_id] === a.altloc) : (prepared.value?.context_receptor_manifest || preparedManifest.value)?.components.flatMap(c => c.atoms).filter(a => anchorResidues.value.includes(a.residue_id)))?.filter(a => !['H', 'D'].includes(a.element)).map(a => a.coordinates) || []);
const spec = computed<PreparedSpec | null>(() => !manifest.value ? null : ({ version: 2, source: manifest.value.source, edits: { excluded_component_ids: [...excluded.value].sort(), altloc_choices: {...altlocChoices.value}, retained_component_ids: retainedComponentIds.value }, preparation: { strategy: 'generation_auto_v1', water_policy: 'remove_all', scope_policy: 'supported_protein_v1', receptor_policy: 'protein_metals_v1', mode: 'standard', repair_missing_atoms: repair.value, missing_residue_policy: 'report_only', nonstandard_policy: normalization.value, protonation_policy: protonation.value, ph: protonation.value === 'recompute' ? Number(ph.value) : null, minimization_policy: minimize.value ? 'restrained_if_supported' : 'none' } }));
const site = computed<BindingSite | null>(() => {
    if (!preparedManifest.value || !manifest.value)
        return null;
    const coordinate_frame_id = preparedManifest.value.coordinate_frame_id;
    const anchor: BindingSite['anchor'] = anchorKind.value === 'source_components' ? { kind: 'source_components', source: manifest.value.source, component_ids: anchorComponents.value, coordinate_frame_id } : anchorKind.value === 'prepared_residues' ? { kind: 'prepared_residues', residue_ids: anchorResidues.value, coordinate_frame_id } : { kind: 'coordinates', coordinates: coordinateAnchors.value, coordinate_frame_id };
    return { anchor, box: { center: center.value, size: size.value }, exclude_from_receptor: siteExcluded.value, center_policy: 'manual' };
});
const alternateResidues = computed(() => {
    const rows = new Map<string, {id: string; label: string; choices: string[]}>();
    for (const c of manifest.value?.components || []) {
        if (excluded.value.includes(c.component_id)) continue;
        for (const a of c.atoms) {
            if (!a.altloc) continue;
            const row = rows.get(a.residue_id) || {id: a.residue_id, label: `${a.author_chain_id || '∅'} · ${a.residue_name} ${a.author_residue_number}${a.insertion_code}`, choices: []};
            if (!row.choices.includes(a.altloc)) row.choices.push(a.altloc);
            rows.set(a.residue_id, row);
        }
    }
    return [...rows.values()];
});
const validPreparation = computed(() => Boolean(spec.value && name.value.trim() && (manifest.value?.inventory_error ? chainScope.value === 'all' && !excluded.value.length : manifest.value && excluded.value.length < manifest.value.components.length && (chainScope.value === 'all' || selectedChains.value.length > 0)) && (protonation.value === 'preserve' || Number.isFinite(ph.value) && ph.value >= 0 && ph.value <= 14)));
const validSite = computed(() => Boolean(prepared.value?.artifacts?.context_receptor && site.value && name.value.trim() && anchorCoordinates.value.length && [...center.value, ...size.value, ...point.value].every(Number.isFinite) && size.value.every(v => v > 0) && siteExcluded.value.length < preparedManifest.value!.components.length));
const changes = computed(() => step.value === 1 ? { name: name.value, prepared_spec: spec.value } : { name: name.value, site: site.value, generation_reference: generationReference.value, input_parameters: {version: 1, ph: featurePh.value, condition_seed: conditionSeed.value}, prepared_artifact_sha256: prepared.value?.artifacts?.prepared_complex.sha256 });
watch([changes, validPreparation, validSite], () => emit('reviewState', { dirty: baseline !== JSON.stringify(changes.value), valid: step.value === 1 ? validPreparation.value : validSite.value, changes: changes.value }), { deep: true });
function label(component: ComponentManifest['components'][number]) {
    const atom = component.atoms[0];
    if (component.selection_kind === 'chain_records') {
        const authorChain = atom.author_chain_id || '∅';
        const duplicateAuthorChain = proteinComponents.value.filter(c => (c.atoms[0].author_chain_id || '∅') === authorChain).length > 1;
        const chainIdentity = atom.label_asym_id || atom.chain_instance_id.split(':chain:').pop() || atom.chain_instance_id;
        const disambiguator = duplicateAuthorChain || atom.label_asym_id && atom.label_asym_id !== authorChain ? ` (${chainIdentity})` : '';
        return `${authorChain}${disambiguator} · ${new Set(component.atoms.map(a => a.residue_id)).size} ${L('个残基', 'residues')}`;
    }
    return `${atom.author_chain_id || '∅'} · ${atom.residue_name} · ${atom.author_residue_number}${atom.insertion_code} · ${component.atoms.length} ${L('原子', 'atoms')}`;
}
function toggle(values: string[], id: string) {
    const i = values.indexOf(id);
    if (i < 0)
        values.push(id);
    else
        values.splice(i, 1);
}
function preparedName() {
    const now = new Date();
    const stamp = [now.getFullYear(), ...[now.getMonth() + 1, now.getDate()].map(v => String(v).padStart(2, '0'))].join('') + '_' + [now.getHours(), now.getMinutes(), now.getSeconds()].map(v => String(v).padStart(2, '0')).join('');
    return `${sourceLabel.value.replace(/\.[^.]+$/, '')}_prepared_${stamp}`;
}
async function guarded(action: () => Promise<void>) {
    busy.value = true;
    error.value = '';
    errorInfo.value = undefined;
    failedJob.value = '';
    try {
        await action();
    }
    catch (e: any) {
        error.value = displayErrorMessage(e);
    }
    finally {
        busy.value = false;
    }
}
function polymerMembers(id: string) {
    return manifest.value?.selection_groups?.find(g => g.component_ids.includes(id))?.component_ids || [id];
}
function chainMembers(id: string) {
    const atom = proteinComponents.value.find(c => c.component_id === id)!.atoms[0];
    const uniqueChain = proteinComponents.value.filter(c => c.atoms[0].author_chain_id === atom.author_chain_id).length === 1;
    // TER separates PDB heterogens from their polymer; reuse author chain labels only when unambiguous.
    return [...new Set([...polymerMembers(id), ...manifest.value!.components.filter(c => c.atoms[0].chain_instance_id === atom.chain_instance_id || uniqueChain && atom.author_chain_id && c.atoms[0].author_chain_id === atom.author_chain_id).map(c => c.component_id)])];
}
function clearChainSelection() {
    if (manifest.value?.inventory_error || !proteinComponents.value.length) {
        chainScope.value = 'all';
        excluded.value = [];
        excludedByChain.value = [];
        return;
    }
    const ids = [...new Set(proteinComponents.value.flatMap(c => chainMembers(c.component_id)))];
    chainScope.value = 'selected';
    excludedByChain.value = ids;
    excluded.value = ids;
}
function syncChainScope() {
    if (chainScope.value !== 'selected') return;
    const ids = new Set(scopedComponents.value.map(c => c.component_id));
    const restored = new Set(excludedByChain.value.filter(id => ids.has(id)));
    excluded.value = excluded.value.filter(id => !restored.has(id));
    excludedByChain.value = excludedByChain.value.filter(id => !restored.has(id));
    const outside = manifest.value!.components.filter(c => c.selection_kind !== 'chain_records' && !ids.has(c.component_id) && !excluded.value.includes(c.component_id)).map(c => c.component_id);
    excludedByChain.value = [...new Set([...excludedByChain.value, ...outside])];
    excluded.value = [...new Set([...excluded.value, ...outside])];
}
function selectScope(value: 'all' | 'selected') {
    const previous = chainScope.value;
    chainScope.value = value;
    if (value === 'all') {
        const ids = new Set([...proteinComponents.value.flatMap(c => polymerMembers(c.component_id)), ...excludedByChain.value]);
        excluded.value = excluded.value.filter(id => !ids.has(id));
        excludedByChain.value = [];
        const chainIds = new Set(proteinComponents.value.map(c => c.component_id));
        explicitlyRetained.value = explicitlyRetained.value.filter(id => !chainIds.has(id));
    } else {
        if (previous !== 'selected') {
            const allChainMembers = [...new Set(proteinComponents.value.flatMap(c => chainMembers(c.component_id)))];
            excludedByChain.value = allChainMembers;
            excluded.value = [...new Set([...excluded.value, ...allChainMembers])];
        }
        syncChainScope();
    }
}
function toggleChain(id: string) {
    const ids = chainMembers(id);
    if (excluded.value.includes(id)) {
        const restored = new Set([...(polymerMembers(id)), ...excludedByChain.value.filter(cid => ids.includes(cid))]);
        excluded.value = excluded.value.filter(cid => !restored.has(cid));
        excludedByChain.value = excludedByChain.value.filter(cid => !restored.has(cid));
    } else {
        excludedByChain.value = [...new Set([...excludedByChain.value, ...ids.filter(cid => !excluded.value.includes(cid))])];
        excluded.value = [...new Set([...excluded.value, ...ids])];
    }
    syncChainScope();
    explicitlyRetained.value = explicitlyRetained.value.filter(id => !excluded.value.includes(id));
}
function restoreScope() {
    excludedByChain.value = [];
    const chainIds = new Set(proteinComponents.value.map(c => c.component_id));
    const hasRetainedChain = explicitlyRetained.value.some(id => chainIds.has(id));
    const hasExcludedChain = proteinComponents.value.some(c => excluded.value.includes(c.component_id));
    chainScope.value = hasRetainedChain || hasExcludedChain ? 'selected' : 'all';
    if (chainScope.value === 'selected') {
        const ids = new Set(scopedComponents.value.map(c => c.component_id));
        excludedByChain.value = manifest.value!.components.filter(c => !ids.has(c.component_id)).map(c => c.component_id);
        syncChainScope();
        explicitlyRetained.value = explicitlyRetained.value.filter(id => !excluded.value.includes(id));
    }
}
function setRetained(id: string, retain: boolean) {
    excluded.value = excluded.value.filter(value => value !== id);
    explicitlyRetained.value = explicitlyRetained.value.filter(value => value !== id);
    if (retain) explicitlyRetained.value.push(id);
    else excluded.value.push(id);
}
async function editPreparation() {
    await guarded(async () => {
        prepared.value = null;
        preparationReport.value = null;
        anchorComponents.value = []; anchorResidues.value = []; siteExcluded.value = [];
        generationReference.value = null; savedContext.value = null;
        referenceText.value = '';
        name.value = preparedName();
        step.value = 1;
        explicitlyRetained.value = explicitlyRetained.value.filter(id => !waterComponents.value.some(c => c.component_id === id));
        await preview();
    });
}
function toggleResidue(residue: ResidueRef) {
    const row = availableResidues.value.find(r => r.chain_id === residue.chain_id && r.residue_number === residue.residue_number && r.insertion_code === residue.insertion_code && r.residue_name === residue.residue_name);
    if (row) toggle(anchorResidues.value, row.residue_id);
}
function selectLigand(residue: ResidueRef & { overlay_id?: string }) {
    if (readonly.value || step.value !== 2 || referenceMode.value !== 'ligand') return;
    if (residue.overlay_id === 'reference') {
        ligandKey.value = externalLigandKey.value;
        return;
    }
    const component = referenceCandidates.value.find(c => c.atoms.some(a => a.author_chain_id === residue.chain_id && a.author_residue_number === residue.residue_number && a.insertion_code === residue.insertion_code && a.residue_name === residue.residue_name));
    if (!component) return;
    anchorKind.value = 'source_components';
    anchorComponents.value = [component.component_id];
    sourceAnchorChanged();
}
function sourceAnchorChanged() {
    recenter();
    const component = referenceCandidates.value.find(c => c.component_id === anchorComponents.value[0]);
    if (component && !isMetalComponent(component) && (!generationReference.value || 'kind' in generationReference.value)) sourceReferenceSelected.value = true;
}
function selectDefaultLigand() {
    if (!preparedManifest.value || anchorKind.value !== 'source_components' || anchorComponents.value.length || referenceCandidates.value.length !== 1) return;
    const component = referenceCandidates.value[0];
    if (!component) return;
    anchorComponents.value = [component.component_id];
    sourceAnchorChanged();
}
async function selectSource(value: {
    id: string | number;
    file_id?: string;
}) {
    await guarded(async () => {
        const selected = await ensureProteinFile(String(value.id), value.file_id);
        const file = selected.dataset.files.find(f => f.id === selected.fileId)!;
        const nextManifest = (await getComponentManifest({ dataset_id: selected.dataset.id, file_id: file.id, sha256: file.sha256!, model_id: modelId.value })).data;
        const nextText = await (await downloadBackendDataset(selected.dataset.id, file.id)).data.text();
        sourceText.value = nextText;
        manifest.value = nextManifest;
        sourceLabel.value = file.original_filename;
        name.value = preparedName();
        excluded.value = [];
        excludedByChain.value = [];
        altlocChoices.value = {};
        hidden.value = [];
        prepared.value = null;
        preparationReport.value = null;
        preparedManifest.value = null;
        anchorComponents.value = []; anchorResidues.value = []; siteExcluded.value = [];
        generationReference.value = null; savedContext.value = null;
        referenceText.value = '';
        step.value = 1;
        clearChainSelection();
        explicitlyRetained.value = [];
        dataOpen.value = false;
        await preview();
    });
}
async function upload(file: File) {
    await guarded(async () => {
        const dataset = await uploadProteinDataset(file);
        await selectSource({ id: dataset.id });
    });
}
async function reloadManifest() {
    if (!manifest.value)
        return;
    await guarded(async () => {
        manifest.value = (await getComponentManifest({ ...manifest.value!.source, model_id: modelId.value })).data;
        excluded.value = [];
        explicitlyRetained.value = [];
        altlocChoices.value = {};
        clearChainSelection();
        await preview();
    });
}
async function downloadPreparationReport() {
    const report = prepared.value?.artifacts?.report || prepared.value?.failure_artifacts?.report;
    if (!report) return;
    await guarded(async () => saveAs((await downloadBackendDataset(report.dataset_id, report.file_id)).data, `${name.value}_preparation_report.json`));
}
async function prepare() {
    if (busy.value) return;
    await guarded(async () => {
        if (pendingSubmission.value) { await sendJob(); return; }
        if (!validPreparation.value) throw new Error(L('请检查准备参数。', 'Check the preparation settings.'));
        if (edit.value) {
            await saveWorkflowEditor(edit.value.id, changes.value);
            await router.push({ path: '/agent', query: { session_id: edit.value.session_id } });
            return;
        }
        prepared.value = (await createPreparedReceptor({ ...spec.value!, name: name.value })).data;
        const job = (await sendJob({ job_type: 'protein_preparation', prepared_receptor_id: prepared.value.id, params: {} })).data;
        prepared.value = { ...prepared.value, status: 'processing', execution: { job_id: job.id, status: 'queued' } };
        preparationJobStatus.value = job.status;
        await router.replace({ query: { prepared_receptor_id: prepared.value.id } });
        await poll(prepared.value.id, job.id);
    });
}
async function poll(id: string, jobId: string) {
    if (!active) return;
    pollError.value = '';
    try {
        const resource = (await getPreparedReceptor(id)).data;
        if (!active) return;
        if (resource.status === 'ready') {
            preparationJobStatus.value = 'succeeded';
            await loadPrepared(id);
            if (error.value) {
                pollError.value = L('准备已完成，暂时无法加载结果：', 'Preparation is complete, but results could not be loaded: ') + error.value;
                error.value = '';
                return;
            }
            step.value = 1;
            await preview();
            return;
        }
        prepared.value = resource;
        if (resource.status === 'failed') {
            errorInfo.value = resource.execution?.error_info;
            error.value = resource.execution?.error || L('准备失败，请修改输入后重新准备。', 'Preparation failed. Update the input and prepare again.');
            return;
        }
        const job = (await getBackendJob(jobId)).data;
        if (!active) return;
        preparationJobStatus.value = job.status;
        if (['failed', 'canceled'].includes(job.status)) {
            errorInfo.value = job.tasks?.find(task => task.error_message)?.output_payload?.error_info;
            error.value = job.tasks?.find(task => task.error_message)?.error_message || L('准备任务已停止。', 'The preparation task has stopped.');
            return;
        }
        timer = setTimeout(() => void poll(id, jobId), 1500);
    } catch (e: any) {
        if (active) pollError.value = L('暂时无法获取准备状态：', 'Unable to retrieve preparation status: ') + (displayErrorMessage(e));
    }
}
// ponytail: a fixed limit; a record whose detail takes longer to arrive cannot be opened until the server sends it faster.
const PREPARED_READ_TIMEOUT = 120000;
const preparedLoading = ref(''), preparedRetry = ref('');
function showFailure(jobId: string, reason?: string, info?: PreparationErrorInfo) {
    error.value = L('这次准备失败，原因见任务详情。', 'This preparation failed. See the task details for the reason.') + (reason ? ' ' + reason.split('\n')[0] : '');
    errorInfo.value = info;
    failedJob.value = jobId;
}
// The record list answers in about a second while the record itself can take minutes: a failed record is reported from
// the list and its task while the record is still loading.
async function earlyFailure(id: string) {
    const entry = (await listPreparedReceptors().catch(() => null))?.data.find(r => r.id === id);
    if (entry?.status === 'failed' && preparedLoading.value === id) showFailure(entry.job_id || '');
    if (!entry?.job_id || !['failed', 'processing'].includes(entry.status)) return;
    const job = await getBackendJob(entry.job_id).then(r => r.data, () => null);
    const task = job?.tasks?.find(task => task.error_message);
    if (job && ['failed', 'canceled'].includes(job.status) && preparedLoading.value === id) showFailure(entry.job_id, task?.error_message || undefined, task?.output_payload?.error_info);
}
async function loadPrepared(id: string, reuse = false) {
    if (!id) return;
    preparedLoading.value = id;
    preparedRetry.value = '';
    await guarded(async () => {
        let resource: PreparedReceptor;
        try {
            void earlyFailure(id);
            resource = (await getPreparedReceptor(id, PREPARED_READ_TIMEOUT)).data;
            // A record can stay in processing after its task has stopped: the task is read now, not after the files and another
            // (possibly slow) read of the record, and such a record is shown as failed.
            // ponytail: a fixed 3 s wait for the task; a slower task read leaves this to poll, which reads the record first.
            const jobId = resource.status === 'processing' ? resource.execution?.job_id : undefined;
            const job = jobId ? await Promise.race([getBackendJob(jobId).then(r => r.data, () => null), new Promise<null>(resolve => setTimeout(() => resolve(null), 3000))]) : null;
            if (job && ['failed', 'canceled'].includes(job.status)) {
                const task = job.tasks?.find(task => task.error_message);
                resource = { ...resource, status: 'failed', execution: { ...resource.execution!, status: job.status, error: task?.error_message || undefined, error_info: task?.output_payload?.error_info } };
            }
        }
        catch (e: any) {
            if (requestErrorKind(e) === 'canceled') throw e;
            preparedRetry.value = id;
            // A failure already shown from the list stays: the record's slow detail adds nothing the user needs here.
            if (requestErrorKind(e) === 'timeout' && failedJob.value) return;
            if (requestErrorKind(e) === 'timeout') throw new Error(L('读取已准备结构超时（2 分钟内没有返回）。可以重试，或在「使用已准备结构」里另选。', 'Loading the prepared structure timed out (no response within 2 minutes). Retry, or choose another one under "Use a prepared structure".'));
            throw e;
        }
        finally {
            preparedLoading.value = '';
        }
        // A failed record says so at once and keeps saying so: its files below may be slow to arrive or unreadable.
        const failure = resource.status === 'failed';
        if (failure) showFailure(resource.execution?.job_id || '', resource.execution?.error, resource.execution?.error_info);
        const artifacts = resource.status === 'ready' ? resource.artifacts : undefined;
        const files = await Promise.all([
            downloadBackendDataset(resource.source.dataset_id, resource.source.file_id).then(r => r.data.text()),
            getBackendDataset(resource.source.dataset_id).then(r => r.data),
            artifacts ? downloadBackendDataset(id, artifacts.prepared_complex.file_id).then(r => r.data.text()) : '',
            artifacts ? downloadBackendDataset(id, artifacts.component_manifest.file_id).then(r => r.data.text()) : '',
            artifacts || resource.failure_artifacts ? downloadBackendDataset(id, (artifacts || resource.failure_artifacts)!.report.file_id).then(r => r.data.text()) : '',
        ]).catch((e: any) => { if (failure && requestErrorKind(e) !== 'canceled') return null; throw e; });
        if (!files || !active) return;
        const [source, dataset, complex, inventory, report] = files;
        if (reuse || prepared.value?.id !== resource.id) {
            anchorComponents.value = []; anchorResidues.value = []; siteExcluded.value = [];
            generationReference.value = null; savedContext.value = null;
            referenceText.value = ''; referencePreviewKey = '';
        }
        sourceText.value = source;
        preparedText.value = complex;
        preparedManifest.value = inventory ? JSON.parse(inventory) : null;
        preparationReport.value = report ? JSON.parse(report) : null;
        sourceLabel.value = dataset.files.find(file => file.id === resource.source.file_id)!.original_filename;
        prepared.value = resource;
        manifest.value = resource.component_manifest;
        modelId.value = resource.source.model_id;
        excluded.value = [...resource.edits.excluded_component_ids];
        altlocChoices.value = {...resource.edits.altloc_choices || {}};
        explicitlyRetained.value = [...resource.edits.retained_component_ids || []];
        restoreScope();
        normalization.value = resource.preparation.nonstandard_policy;
        repair.value = resource.preparation.repair_missing_atoms;
        protonation.value = resource.preparation.protonation_policy;
        ph.value = resource.preparation.ph ?? 7.4;
        minimize.value = resource.preparation.minimization_policy !== 'none';
        name.value = reuse ? resource.name : name.value || resource.name;
        preparationJobStatus.value = resource.execution?.status || '';
        step.value = artifacts ? 2 : 1;
        hidden.value = [];
        if (artifacts) selectDefaultLigand();
        await preview();
        if (!artifacts) {
            if (resource.execution?.job_id && resource.status === 'processing') timer = setTimeout(() => void poll(id, resource.execution!.job_id), 1500);
            return;
        }
        if (!embedded.value) await router.replace({ query: reuse ? { prepared_receptor_id: id } : { ...route.query, prepared_receptor_id: id } });
    });
}
function recenter(resizeBox = !boxSizeEdited.value) {
    const points = anchorCoordinates.value;
    if (!points.length)
        return;
    center.value = [0, 1, 2].map(i => (Math.min(...points.map(p => p[i])) + Math.max(...points.map(p => p[i]))) / 2);
    if (!resizeBox) return;
    size.value = [0, 1, 2].map(i => Math.max(8, Math.max(...points.map(p => p[i])) - Math.min(...points.map(p => p[i])) + 8));
}
async function uploadReference(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file)
        return;
    await guarded(async () => {
        const dataset = (await uploadBackendDataset({ name: file.name, kind: 'agent_ligand', file, fileRole: 'ligand_input', inputPolicy: 'generation_auto_v1' })).data;
        const row = dataset.files[0];
        generationReference.value = { structure: { dataset_id: dataset.id, file_id: row.id, sha256: row.sha256! }, coordinate_frame_id: preparedManifest.value!.coordinate_frame_id };
        referenceLabel.value = file.name;
        await selectExternalReferenceSite();
    });
}
async function selectReference(value: { id: string | number; file_id?: string }) {
    await guarded(async () => {
        const dataset = (await getBackendDataset(String(value.id))).data;
        const row = dataset.files.find(file => file.id === value.file_id);
        if (!row || !/\.(sdf|mol|mol2)$/i.test(row.original_filename) || !row.sha256) {
            throw new Error(L('请选择有效的 SDF、MOL 或 MOL2 配体文件。', 'Select a valid SDF, MOL or MOL2 ligand file.'));
        }
        generationReference.value = { structure: { dataset_id: dataset.id, file_id: row.id, sha256: row.sha256 }, coordinate_frame_id: preparedManifest.value!.coordinate_frame_id };
        referenceLabel.value = row.original_filename;
        referenceDataOpen.value = false;
        await selectExternalReferenceSite();
    });
}
async function selectExternalReferenceSite() {
    await nextTick();
    await preview();
    if (externalCoordinates.value.length) ligandKey.value = externalLigandKey.value;
}
async function pollCompatibility(id: string) {
    clearTimeout(compatibilityTimer);
    if (!active) return;
    try {
        const context = (await getProteinContext(id)).data;
        if (!active || savedContext.value?.id !== id) return;
        savedContext.value = context;
        if (Object.values(context.compatibility?.models || {}).some(row => row.status === 'pending')) compatibilityTimer = setTimeout(() => void pollCompatibility(id), 2000);
    } catch (e: any) { error.value = displayErrorMessage(e); }
}
async function saveSite() {
    await guarded(async () => {
        if (edit.value) {
            await saveWorkflowEditor(edit.value.id, changes.value);
            await router.push({ path: '/agent', query: { session_id: edit.value.session_id } });
            return;
        }
        savedContext.value = (await createBindingSite({ version: 4, name: name.value, prepared_receptor_id: prepared.value!.id, prepared_artifact_sha256: prepared.value!.artifacts!.prepared_complex.sha256, site: site.value!, generation_reference: generationReference.value, input_parameters: {version: 1, ph: featurePh.value, condition_seed: conditionSeed.value}, ...(route.query.context_id ? { derived_from_context_id: String(route.query.context_id) } : {}) })).data;
        if (route.query.postprocessing_source_job_id) {
            await router.push({path: '/postprocessing', query: {source_job_id: String(route.query.postprocessing_source_job_id), protein_context_id: savedContext.value.id}});
            return;
        }
        await router.replace({ query: { ...route.query, context_id: savedContext.value.id } });
        void pollCompatibility(savedContext.value.id);
    });
}

function preview() {
    const revision = ++previewRevision;
    const update = previewQueue.then(async () => {
        await nextTick();
        if (!active || revision !== previewRevision || !viewer.value || !visibleComponents.value.length) return;
        const content = showPrepared.value ? preparedText.value : sourceText.value;
        if (!content) return;
        previewError.value = '';
        const rows = content.split(/\r?\n/);
        const native = (showPrepared.value ? step.value === 2 ? prepared.value?.context_receptor_manifest || preparedManifest.value : preparedManifest.value : manifest.value)?.source_format === 'mmcif';
        const text = native ? previewCif(visibleComponents.value) : `${visibleComponents.value.flatMap(c => [...c.atoms.map(a => rows[a.source_record - 1]), 'TER']).join('\n')}\nEND\n`;
        const reference = generationReference.value;
        if (step.value === 2 && reference && !('kind' in reference)) {
            const key = JSON.stringify(reference.structure);
            if (key !== referencePreviewKey) {
                const [response, dataset] = await Promise.all([
                    downloadBackendDataset(reference.structure.dataset_id, reference.structure.file_id),
                    getBackendDataset(reference.structure.dataset_id),
                ]);
                const ligand = await response.data.text();
                if (!active || revision !== previewRevision) return;
                referenceLabel.value = dataset.data.files.find(file => file.id === reference.structure.file_id)!.original_filename;
                referenceFormat.value = referenceLabel.value.split('.').pop()!.toLowerCase();
                referenceText.value = ligand;
                referencePreviewKey = key;
            }
        }
        // Reuse the current scene while queue status or the box changes.
        const sceneKey = `${step.value}:${text}`;
        if (scenePreviewKey !== sceneKey) {
            await viewer.value.loadStructure(text, native ? 'mmcif' : 'pdb');
            scenePreviewKey = sceneKey;
        }
        if (!active || revision !== previewRevision) return;
        if (step.value === 2) {
            const retained = visibleComponents.value;
            const overlays = (referenceCandidates.value || [])
                .filter((c, i, all) => all.findIndex(other => other.component_id === c.component_id) === i)
                .filter(c => !hidden.value.includes(c.component_id) && !retained.some(other => other.atoms.some(a => {
                    const source = c.atoms[0];
                    return a.author_chain_id === source.author_chain_id && a.author_residue_number === source.author_residue_number && a.insertion_code === source.insertion_code && a.residue_name === source.residue_name;
                })));
            const sourceRows = sourceText.value.split(/\r?\n/);
            const overlay = overlays.flatMap(c => c.atoms.filter(a => !a.altloc || !altlocChoices.value[a.residue_id] || altlocChoices.value[a.residue_id] === a.altloc).map(a => sourceRows[a.source_record - 1])).join('\n');
            await viewer.value.overlayStructure(manifest.value?.source_format === 'mmcif' ? previewCif(overlays) : overlay ? overlay + '\nEND\n' : '', manifest.value?.source_format === 'mmcif' ? 'mmcif' : 'pdb', 'source-ligands');
            if (!active || revision !== previewRevision) return;
            const coordinates = await viewer.value.overlayStructure(reference && !('kind' in reference) ? referenceText.value : '', referenceFormat.value, 'reference');
            if (!active || revision !== previewRevision) return;
            if (externalLigandKey.value && referenceGeometry.value?.key !== externalLigandKey.value) referenceGeometry.value = { key: externalLigandKey.value, coordinates: coordinates || [] };
            if (anchorCoordinates.value.length) await viewer.value.add_shape(center.value[0], center.value[1], center.value[2], size.value[0], size.value[1], size.value[2], false);
            else await viewer.value.remove_shape();
        }
    });
    previewQueue = update.catch((e: any) => {
        if (active && revision === previewRevision) previewError.value = displayErrorMessage(e);
    });
    return previewQueue;
}
watch([excluded, hidden, siteExcluded, anchorComponents, anchorKind, altlocChoices, generationReference], () => void preview(), { deep: true });
watch([center, size], () => {
    if (step.value === 2) void preview();
}, { deep: true });
async function restoreValues(values: Record<string, any>) {
    if (values.input_parameters) {
        conditionSeed.value = values.input_parameters.condition_seed;
    }
    const saved = values.prepared_spec;
    if (saved) {
        modelId.value = saved.source.model_id;
        await selectSource({ id: saved.source.dataset_id, file_id: saved.source.file_id });
        excluded.value = [...saved.edits.excluded_component_ids];
        altlocChoices.value = {...saved.edits.altloc_choices || {}};
        explicitlyRetained.value = [...saved.edits.retained_component_ids || []];
        restoreScope();
        normalization.value = saved.preparation.nonstandard_policy;
        repair.value = saved.preparation.repair_missing_atoms;
        protonation.value = saved.preparation.protonation_policy;
        ph.value = saved.preparation.ph ?? 7.4;
        minimize.value = saved.preparation.minimization_policy !== 'none';
    }
    if (values.site) {
        const value = values.site as BindingSite;
        anchorKind.value = value.anchor.kind;
        anchorComponents.value = value.anchor.kind === 'source_components' ? [...value.anchor.component_ids] : [];
        anchorResidues.value = value.anchor.kind === 'prepared_residues' ? [...value.anchor.residue_ids] : [];
        coordinateAnchors.value = value.anchor.kind === 'coordinates' ? value.anchor.coordinates.map(point => [...point]) : [[0, 0, 0]];
        center.value = [...value.box.center];
        size.value = [...value.box.size];
        boxSizeEdited.value = true;
        siteExcluded.value = [...value.exclude_from_receptor];
        generationReference.value = values.generation_reference || null;

    }
    if (values.site_request) {
        anchorKind.value = 'coordinates';
        anchorComponents.value = [];
        anchorResidues.value = [];
        coordinateAnchors.value = [[...values.site_request.center]];
        center.value = [...values.site_request.center];
        if (values.site_request.size) size.value = [...values.site_request.size];
        boxSizeEdited.value = true;
    }
    if (values.name)
        name.value = values.name;
    await preview();
}
onMounted(() => {
    // The list is read on its own: a record opened from the address that is slow or fails must not leave the choice empty.
    if (!embedded.value)
        void listPreparedReceptors().then(r => { library.value = r.data; }, (e: any) => { error.value ||= displayErrorMessage(e); });
    void restoreOnMount();
});
const restoreOnMount = () => guarded(async () => {
    const values = props.review || props.selection;
    if (values?.prepared_receptor_id) {
        await loadPrepared(values.prepared_receptor_id);
        await restoreValues({ ...values, prepared_spec: undefined });
    }
    else if (values?.prepared_spec) {
        await restoreValues(values);
    }
    else if (values?.protein_dataset_id) {
        await selectSource({ id: values.protein_dataset_id, file_id: values.protein_file_id });
    }
    else if (route.query.edit_session_id) {
        edit.value = (await getWorkflowEditor(String(route.query.edit_session_id))).data;
        const state = edit.value.state;
        const id = state.assets.prepared_receptor_id || state.context?.prepared_receptor_id;
        if (id)
            await loadPrepared(id);
        else if (state.assets.protein_dataset_id)
            await selectSource({ id: state.assets.protein_dataset_id, file_id: state.values.protein_file_id });
        await restoreValues({ ...state.context, ...state.values, ...state.draft });
    }
    else if (route.query.restore_job_id) {
        const job = (await getBackendJob(String(route.query.restore_job_id))).data;
        if (job.params.prepared_receptor_id) {
            await loadPrepared(job.params.prepared_receptor_id);
        }
        else if (job.params.protein_context_id) {
            const ctx = (await getProteinContext(job.params.protein_context_id)).data;
            await loadPrepared(String(route.query.prepared_receptor_id || ctx.prepared_receptor_id));
            await restoreValues(ctx);
            savedContext.value = ctx;
        }
    }
    else if (route.query.context_id) {
        const ctx = (await getProteinContext(String(route.query.context_id))).data;
        await loadPrepared(String(route.query.prepared_receptor_id || ctx.prepared_receptor_id));
        await restoreValues(ctx);
        savedContext.value = ctx;
    }
    else if (route.query.prepared_receptor_id) {
        await loadPrepared(String(route.query.prepared_receptor_id));
    }
    else if (route.query.protein_dataset_id) {
        await selectSource({ id: String(route.query.protein_dataset_id), file_id: route.query.protein_file_id ? String(route.query.protein_file_id) : undefined });
    }
    if (savedContext.value) void pollCompatibility(savedContext.value.id);
    const restoredScopeChanged = !readonly.value && step.value === 1 && values?.prepared_spec && JSON.stringify([...values.prepared_spec.edits.excluded_component_ids].sort()) !== JSON.stringify(spec.value?.edits.excluded_component_ids);
    baseline = JSON.stringify(restoredScopeChanged ? { ...changes.value, prepared_spec: values?.prepared_spec } : changes.value);
    emit('reviewState', { dirty: baseline !== JSON.stringify(changes.value), valid: step.value === 1 ? validPreparation.value : validSite.value, changes: changes.value });
});
watch(changes, () => {
    if (!edit.value || busy.value || readonly.value)
        return;
    if (draftTimer)
        clearTimeout(draftTimer);
    draftTimer = setTimeout(() => {
        void saveWorkflowEditorDraft(edit.value!.id, changes.value).catch((e: any) => {
            error.value = displayErrorMessage(e);
        });
    }, 300);
}, { deep: true });
watch([repair, protonation], () => { if (!repair.value || protonation.value === 'preserve') normalization.value = 'preserve'; });
onUnmounted(() => {
    active = false;
    clearTimeout(compatibilityTimer);
    if (timer)
        clearTimeout(timer);
    if (draftTimer)
        clearTimeout(draftTimer);
});
</script>

<template>
  <WorkspaceLayout v-model:open="panelOpen" :title="L('结构操作', 'Structure controls')" :resizable="!embedded">
    <template #auxiliary>
      <div v-show="panelTab === 'parameters'">
    <fieldset class="min-w-0 space-y-4" :disabled="readonly || busy || prepared?.status === 'processing'">
      <ol class="flex gap-2 text-sm font-medium" :aria-label="L('准备流程', 'Preparation steps')">
        <li :class="step === 1 ? 'text-primary' : 'text-slate-500'">1 · {{ L('蛋白准备', 'Prepare protein') }}</li><li aria-hidden="true">→</li>
        <li :class="step === 2 ? 'text-primary' : 'text-slate-500'">2 · {{ L('选择位点', 'Select site') }}</li>
      </ol>
      <p v-if="preparedLoading" role="status" class="text-sm text-muted-foreground">{{ L('正在读取已准备结构…', 'Loading the prepared structure…') }}</p>
      <PreparationErrorDetails v-if="error" :error="errorInfo" :fallback="error" class="rounded border border-red-200 p-2" />
      <RouterLink v-if="error && failedJob && !embedded" :to="{ path: '/results', query: { job_id: failedJob } }" class="block text-sm text-primary underline">{{ L('查看任务详情', 'View task details') }}</RouterLink>
      <Button v-if="preparedRetry && !busy" type="button" variant="outline" size="sm" @click="loadPrepared(preparedRetry)">{{ L('重试读取', 'Retry') }}</Button>
      <Button v-if="edit" variant="outline" @click="guarded(async () => { await cancelWorkflowEditor(edit!.id); await router.push({ path: '/agent', query: { session_id: edit!.session_id } }) })">{{ L('取消并返回会话', 'Cancel and return to session') }}</Button>
      <template v-if="step === 1">
        <ProteinInputPanel v-if="!embedded && !prepared?.artifacts" :label="sourceLabel" :loading="busy" @upload="upload" @choose="dataOpen = true" />
        <p v-else class="text-sm">{{ sourceLabel }}</p>
        <details v-if="!embedded" class="rounded border p-3 text-sm">
          <summary class="cursor-pointer">{{ L('使用已准备结构', 'Use a prepared structure') }}</summary>
          <select class="mt-2 w-full rounded border p-2" :aria-label="L('已准备结构', 'Prepared structure')" value="" @change="loadPrepared(($event.target as HTMLSelectElement).value, true)">
            <option value="">{{ L('选择结构，直接设置位点', 'Choose a structure and define a site') }}</option>
            <option v-for="item in library.filter(item => item.status === 'ready')" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </details>
        <template v-if="manifest">
          <label class="block space-y-2 text-sm">{{ L('结构名称', 'Structure name') }}<Input v-model="name" :aria-label="L('结构名称', 'Structure name')" /></label>
          <p role="status" class="text-sm">{{ chainScope === 'all' ? L('完整蛋白', 'Whole protein') : L('指定链', 'Selected chains') }} · {{ selectedChains.map(c => c.atoms[0].author_chain_id || '∅').join(' + ') || L('未选择蛋白链', 'No protein chain selected') }} · {{ selectedChains.reduce((n, c) => n + new Set(c.atoms.map(a => a.residue_id)).size, 0) }} {{ L('个残基', 'residues') }}</p>
          <template v-if="!prepared?.artifacts">
            <p v-if="manifest.inventory_error" class="text-xs text-amber-700">{{ L('预览清单暂不可用，可按完整结构提交并在任务中解析。', 'Preview inventory is unavailable. Submit the full structure for parsing during the task.') }}</p>
            <p v-if="manifest.external_coordination_connections?.length" role="status" class="text-xs text-amber-700">{{ L('存在晶体邻居的金属配位：继续准备当前输入，未包含晶体邻居的原子或参数。', 'Metal coordination with crystal neighbors is recorded. Preparation uses the current input; crystal-neighbor atoms and parameters are not included.') }}</p>
            <section class="space-y-3 rounded-lg border border-slate-200 bg-white p-3 text-sm">
              <h2 class="font-medium">{{ L('蛋白输入范围', 'Protein input scope') }}</h2>
              <div class="flex flex-wrap gap-2">
                <label class="flex min-w-0 flex-1 basis-36 cursor-pointer items-center gap-2 rounded-lg border p-3" :class="chainScope === 'all' ? 'border-primary bg-primary/5' : 'border-slate-200'">
                  <input type="radio" name="protein-scope" class="shrink-0 accent-primary" :checked="chainScope === 'all'" @change="selectScope('all')"><span>{{ L('全部蛋白链', 'All protein chains') }}</span>
                </label>
                <label class="flex min-w-0 flex-1 basis-36 cursor-pointer items-center gap-2 rounded-lg border p-3" :class="chainScope === 'selected' ? 'border-primary bg-primary/5' : 'border-slate-200'">
                  <input type="radio" name="protein-scope" class="shrink-0 accent-primary" :checked="chainScope === 'selected'" @change="selectScope('selected')"><span>{{ L('指定链', 'Selected chains') }}</span>
                </label>
              </div>
              <div v-if="chainScope === 'selected'" class="max-h-56 space-y-1 overflow-y-auto">
                <label v-for="component in proteinComponents" :key="component.component_id" class="flex min-w-0 cursor-pointer items-start gap-2 rounded-md px-2 py-2 hover:bg-slate-50"><input type="checkbox" class="mt-0.5 shrink-0 accent-primary" :checked="!excluded.includes(component.component_id)" @change="toggleChain(component.component_id)"><span class="min-w-0 break-words">{{ label(component) }}</span></label>
              </div>
              <label v-if="modelIds.length > 1" class="flex items-center justify-between gap-3 border-t pt-3">Model<select v-model="modelId" class="min-w-0 rounded-md border bg-white px-3 py-2" @change="reloadManifest"><option v-for="id in modelIds" :key="id">{{ id }}</option></select></label>
            </section>
            <details open class="rounded-lg border border-slate-200 p-3 text-sm">
              <summary class="cursor-pointer font-medium">{{ L('配体、添加剂与其他组分', 'Ligands, additives and other components') }}</summary>
              <p class="mt-3 text-xs text-slate-600">{{ L('所选组分保留在准备结构中，非蛋白配体和辅因子不进入受体。', 'Selected components remain in the prepared structure; nonprotein ligands and cofactors are excluded from the receptor.') }}</p>
              <p class="mt-2 text-xs">{{ L('水组分：', 'Water components: ') }}{{ waterComponents.length }}</p>
              <div class="mt-2 max-h-56 space-y-1 overflow-y-auto">
                <label v-for="component in [...otherComponents, ...solventComponents]" :key="component.component_id" class="flex min-w-0 cursor-pointer items-start gap-2 rounded-md px-2 py-2 hover:bg-slate-50"><input type="checkbox" class="mt-0.5 shrink-0 accent-primary" :aria-label="L('保留 ', 'Retain ') + label(component)" :checked="!excluded.includes(component.component_id)" @change="setRetained(component.component_id, ($event.target as HTMLInputElement).checked)"><span class="min-w-0 break-words">{{ label(component) }}</span></label>
              </div>
            </details>
            <details class="rounded-lg border border-slate-200 p-3 text-sm">
              <summary class="cursor-pointer font-medium">{{ L('高级设置', 'Advanced settings') }}</summary>
              <div class="mt-3 divide-y divide-slate-100">
                <label class="flex items-center gap-2 py-3"><input type="checkbox" checked disabled class="shrink-0 accent-primary"><span>{{ L('去除全部水', 'Remove all water') }}</span></label>
                <label class="flex cursor-pointer items-start gap-2 py-3"><input v-model="repair" type="checkbox" class="mt-0.5 shrink-0 accent-primary"><span>{{ L('补已有残基缺失原子', 'Repair missing atoms in existing residues') }}</span></label>
                <label class="flex items-start gap-2 py-3" :class="!repair || protonation !== 'recompute' ? 'text-slate-400' : 'cursor-pointer'"><input type="checkbox" class="mt-0.5 shrink-0 accent-primary" :checked="normalization === 'standardize_supported'" :disabled="!repair || protonation !== 'recompute'" @change="normalization = ($event.target as HTMLInputElement).checked ? 'standardize_supported' : 'preserve'"><span>{{ L('将支持的修饰标准化为普通氨基酸', 'Standardize supported modifications') }}</span></label>
                <div class="flex flex-wrap items-center gap-3 py-3">
                  <label class="flex cursor-pointer items-center gap-2"><input type="checkbox" class="shrink-0 accent-primary" :checked="protonation === 'recompute'" @change="protonation = ($event.target as HTMLInputElement).checked ? 'recompute' : 'preserve'">{{ L('质子化', 'Protonation') }}</label>
                  <label v-if="protonation === 'recompute'" class="flex items-center gap-2">pH<Input v-model.number="ph" class="w-24" :aria-label="L('质子化 pH', 'Protonation pH')" type="number" min="0" max="14" step="0.1" /></label>
                </div>
                <label class="flex cursor-pointer items-start gap-2 py-3"><input v-model="minimize" type="checkbox" class="mt-0.5 shrink-0 accent-primary"><span>{{ L('尝试能量最小化（约束原有重原子位置）', 'Attempt energy minimization with restraints on original heavy atoms') }}</span></label>
              </div>
              <details v-if="alternateResidues.length" class="mt-3 rounded-md border p-3 text-xs">
                <summary class="cursor-pointer font-medium">{{ L('替代构象', 'Alternate conformers') }}</summary>
                <label v-for="residue in alternateResidues" :key="residue.id" class="mt-3 block space-y-2"><span>{{ residue.label }}</span><select v-model="altlocChoices[residue.id]" class="block w-full min-w-0 rounded-md border bg-white p-2"><option :value="undefined">{{ L('任务中按占有率自动选择', 'Select by occupancy during preparation') }}</option><option v-for="choice in residue.choices" :key="choice" :value="choice">{{ choice }}</option></select></label>
              </details>
            </details>
            <p v-if="pendingSubmission && !busy" role="status" class="text-sm text-amber-700">{{ $t('platform.submissionUnknown') }}</p>
            <p v-else-if="confirmedJob && !busy && prepared?.status !== 'processing'" role="status" class="text-sm text-green-700">{{ $t('platform.originalSubmissionConfirmed') }}</p>
            <Button v-if="!embedded" class="w-full" :disabled="busy || (!pendingSubmission && (!validPreparation || prepared?.status === 'processing'))" @click="prepare">{{ pendingSubmission ? $t('platform.retryOriginalSubmission') : prepared?.status === 'processing' ? L('正在准备…', 'Preparing…') + (preparationStage ? ' · ' + preparationStage : '') : L('开始准备', 'Start preparation') }}</Button>
            <p v-if="prepared?.status === 'failed'" class="text-xs text-red-700">{{ prepared.execution?.error }}</p>
            <Button v-if="prepared?.failure_artifacts?.report" variant="outline" @click="downloadPreparationReport">{{ L('下载诊断报告', 'Download diagnostic report') }}</Button>
          </template>
          <template v-else>
            <p class="text-sm" :class="prepared.capabilities?.preparation_status === 'partial' ? 'text-amber-700' : 'text-emerald-700'">{{ prepared.capabilities?.preparation_status === 'partial' ? L('该结构仍有处理未完成，请查看处理详情。', 'Some operations are incomplete; inspect the processing details.') : L('蛋白准备完成，可复用于不同位点。', 'Preparation complete. Reuse this structure for different sites.') }}</p>
            <details class="rounded border p-3 text-sm"><summary class="cursor-pointer">{{ L('处理详情', 'Processing details') }}</summary>
              <Button variant="outline" class="mt-2" @click="downloadPreparationReport">{{ L('下载完整报告', 'Download full report') }}</Button>
              <p class="mt-2 text-xs">{{ L('排除组分：', 'Excluded components: ') }}{{ preparationReport?.excluded_component_ids?.length ?? excluded.length }}</p>
              <p v-for="(operation, key) in prepared.capabilities?.operations || {}" :key="key" class="mt-2 text-xs">{{ ({repair: L('结构修复', 'Structure repair'), protonation: L('质子化', 'Protonation'), minimization: L('最小化', 'Minimization'), standardization: L('修饰标准化', 'Modification standardization')} as Record<string, string>)[key] }} · {{ operation.status === 'completed' ? L('已完成', 'Completed') : operation.status === 'not_requested' ? L('未启用', 'Not requested') : operation.status === 'not_applicable' ? L('无需处理', 'Not applicable') : operation.status === 'skipped' ? L('已跳过', 'Skipped') : L('未完成', 'Incomplete') }}<span v-if="operation.requested && operation.reason"> · {{ operation.reason }}</span></p>
              <p v-for="line in standardizationDetails" :key="line" class="mt-1 text-xs text-slate-600">{{ line }}</p>
            </details>
            <Button class="w-full" @click="step = 2; preview()">{{ L('下一步：选择位点', 'Next: select a site') }}</Button>
            <Button v-if="!embedded" variant="outline" @click="editPreparation">{{ L('修改输入并创建新准备', 'Edit input and create a new preparation') }}</Button>
          </template>
        </template>
      </template>
      <template v-else-if="prepared?.artifacts && preparedManifest">
        <p class="text-sm">{{ L('已准备结构：', 'Prepared structure: ') }}{{ prepared.name }}</p>
        <p class="text-xs">{{ L('Context 复用已准备的空受体，保存位点与参考配体。空受体保留蛋白和独立金属。', 'Context reuses the prepared apo receptor and records the site and reference ligand. The apo receptor retains protein and isolated metals.') }}</p>
        <Button size="sm" variant="outline" @click="step = 1; preview()">{{ L('查看准备结构', 'View prepared structure') }}</Button>
        <label class="block space-y-2 text-sm">{{ L('Context 名称', 'Context name') }}<Input v-model="name" :aria-label="L('Context 名称', 'Context name')" /></label>
        <ProteinReferenceSelector v-model:mode="referenceMode" v-model:ligand-key="ligandKey" :ligands="siteLigands" :external-ligand-key="externalLigandKey" :external-ligand-label="referenceLabel" />
        <ResidueSelectionList v-if="anchorKind === 'prepared_residues'" :residues="selectedResidueRows" :available-residues="availableResidues" @toggle="toggleResidue($event); recenter()" @clear="anchorResidues = []" />
        <div v-if="referenceMode === 'coordinates'" class="grid grid-cols-3 gap-2"><Input v-for="(_, i) in point" :key="i" v-model.number="point[i]" type="number" step="0.1" :aria-label="`Anchor ${'XYZ'[i]}`" @change="recenter()" /></div>
        <DockingBoxEditor v-model:center="center" :size="size" @update:size="size = $event; boxSizeEdited = true" :can-recenter="anchorCoordinates.length > 0" @recenter="recenter(true)" @reset="size = [20, 20, 20]; boxSizeEdited = true" />
        <label v-if="anchorComponents.length === 1 && referenceCandidates.some(c => c.component_id === anchorComponents[0] && !isMetalComponent(c))" class="flex gap-2 text-sm"><input v-model="sourceReferenceSelected" type="checkbox">{{ L('用作参考配体', 'Use as reference ligand') }}</label>
        <details class="rounded border p-3 text-sm">
          <summary class="cursor-pointer">{{ L('参考配体', 'Reference ligand') }}</summary>
          <div class="mt-3 flex flex-wrap gap-2">
            <Button type="button" size="sm" variant="outline" :disabled="busy" @click="referenceInput?.click()">{{ L('上传参考配体', 'Upload reference ligand') }}</Button>
            <Button type="button" size="sm" variant="outline" :disabled="busy" @click="referenceDataOpen = true">{{ L('从数据资源选择', 'Choose from data resources') }}</Button>
            <input ref="referenceInput" class="hidden" type="file" accept=".sdf,.mol,.mol2" @change="uploadReference">
          </div>
          <p v-if="generationReference" class="mt-2 text-xs">{{ sourceReferenceSelected ? L('使用所选源配体', 'Using the selected source ligand') : referenceLabel || L('已绑定参考配体', 'Reference ligand bound') }} <button type="button" class="underline" @click="generationReference = null">{{ L('移除', 'Remove') }}</button></p>
          <Button v-if="externalLigandKey" type="button" size="sm" variant="outline" class="mt-2" :disabled="busy || !externalCoordinates.length" @click="ligandKey = externalLigandKey">{{ L('用此配体设置位点', 'Use this ligand to define the site') }}</Button>
        </details>
        <Button v-if="!embedded" class="w-full" :disabled="!validSite" @click="saveSite">{{ L('保存 Context', 'Save context') }}</Button>
        <ProteinContextSummary v-if="savedContext" :context="savedContext" :source-manifest="manifest" :receptor-manifest="prepared.context_receptor_manifest || preparedManifest" :show-actions="!embedded" @updated="savedContext = $event; pollCompatibility($event.id)" />
      </template>
    </fieldset></div>
      <div v-show="panelTab === 'assistant'" class="h-full min-h-[400px]"><slot name="assistant"><InlineAssistant v-if="assistantMounted && agentIdentity" :key="agentIdentity + (manifest?.source.dataset_id || 'draft')" compact :structure-input="manifest ? {datasetId: manifest.source.dataset_id, fileId: manifest.source.file_id, name: sourceLabel, contextId: savedContext?.id} : undefined" /></slot></div>
    </template>
    <template #panel-header><div role="tablist" :aria-label="L('操作面板', 'Controls')" class="flex gap-1"><Button v-for="tab in ['parameters', 'assistant']" :key="tab" role="tab" :aria-selected="panelTab === tab" :variant="panelTab === tab ? 'secondary' : 'ghost'" size="sm" @click="panelTab = tab">{{ tab === 'parameters' ? L('参数', 'Parameters') : L('助手', 'Assistant') }}</Button></div></template>
    <div class="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-white">
      <div class="flex min-h-12 shrink-0 flex-wrap items-center justify-between gap-2 border-b bg-card px-4 py-2">
        <h2 class="shrink-0 text-sm font-semibold">{{ L('结构工作区', 'Structure workspace') }}</h2>
        <Button v-if="!panelOpen" variant="outline" size="sm" @click="panelOpen = true">{{ L('打开操作面板', 'Open controls') }}</Button><span v-else class="max-w-40 truncate text-xs text-muted-foreground">{{ sourceLabel }}</span>
      </div>
      <details v-if="manifest" class="shrink-0 border-b bg-white px-3 py-2 text-xs"><summary class="cursor-pointer">{{ L('预览显示', 'Preview visibility') }}</summary><div class="flex max-h-32 flex-wrap gap-2 overflow-auto pt-2"><button v-for="component in previewComponents.filter(c => c.selection_kind === 'chain_records' || !solventNames.has(c.atoms[0].residue_name))" :key="component.component_id" type="button" class="rounded border px-2 py-1" :aria-pressed="!hidden.includes(component.component_id)" @click="toggle(hidden, component.component_id)">{{ label(component) }} · {{ hidden.includes(component.component_id) ? L('显示', 'Show') : L('隐藏', 'Hide') }}</button></div></details>
      <p v-if="prepared?.status === 'processing'" role="status" class="shrink-0 border-b bg-violet-50 p-3 text-sm text-violet-700">{{ preparationJobStatus === 'succeeded' ? L('准备已完成，正在加载结构。', 'Preparation is complete. Loading the structure.') : preparationJobStatus === 'running' ? L('正在准备蛋白，完成后将显示准备结构。', 'Preparing the protein. The prepared structure will appear when ready.') : L('准备任务已进入队列，正在等待执行。', 'Preparation is queued and waiting to run.') }}</p>
      <div v-if="pollError" role="alert" class="shrink-0 p-3 text-sm text-amber-700">{{ pollError }} <Button size="sm" variant="outline" @click="poll(prepared!.id, prepared!.execution!.job_id)">{{ L('重试获取状态', 'Retry status') }}</Button></div>
      <div v-if="previewError" role="alert" class="shrink-0 p-3 text-sm text-amber-700">{{ L('结构预览失败：', 'Structure preview failed: ') }}{{ previewError }} <Button size="sm" variant="outline" @click="scenePreviewKey = ''; preview()">{{ L('重试预览', 'Retry preview') }}</Button></div>
      <FeedbackState v-if="!visibleComponents.length" class="flex-1" :title="L('选择结构开始准备', 'Choose a structure to prepare')" :description="L('上传结构或打开已有数据，检查组分并定义位点。', 'Upload a structure or open existing data to inspect components and define a site.')"><Button v-if="!panelOpen" variant="outline" @click="panelOpen = true">{{ L('上传结构', 'Upload structure') }}</Button></FeedbackState>
      <ProteinViewer v-show="visibleComponents.length" ref="viewer" class="min-h-0 flex-1" compact :if-show-box="step === 2" :selection-mode="readonly || step !== 2 ? 'none' : referenceMode === 'residues' ? 'residue' : referenceMode === 'coordinates' ? 'point' : 'ligand'" :selected-residues="selectedResidueRows" @ligand-select="selectLigand" @residue-toggle="toggleResidue($event); recenter()" @point-pick="point = [...$event.center]; recenter()" />
      <div v-if="manifest" class="shrink-0 border-t bg-card px-4 py-2 text-xs text-muted-foreground" role="status">{{ visibleComponents.length }} {{ L('个可见组分', 'visible components') }}<span v-if="anchorResidues.length"> · {{ anchorResidues.length }} {{ L('个选中残基', 'selected residues') }}</span><span v-if="step === 2"> · {{ L('位点中心', 'Site center') }} {{ center.map(v => v.toFixed(1)).join(', ') }} Å</span></div>
    </div>
    <Dialog v-model:open="dataOpen"><DialogContent class="max-h-[80vh] max-w-4xl overflow-auto"><DialogTitle>{{ L('选择结构', 'Select structure') }}</DialogTitle><DialogDescription class="sr-only">{{ $t('platform.dialogA11y.chooseData') }}</DialogDescription><DataCenterSelector :filetypes="['pdb', 'cif', 'mmcif']" @select="selectSource" @error="error = $event" /></DialogContent></Dialog>
    <Dialog v-model:open="referenceDataOpen"><DialogContent class="max-h-[80vh] max-w-4xl overflow-auto"><DialogTitle>{{ L('选择参考配体', 'Select reference ligand') }}</DialogTitle><DialogDescription class="sr-only">{{ $t('platform.dialogA11y.chooseData') }}</DialogDescription><DataCenterSelector :filetypes="['sdf', 'mol', 'mol2']" select-file @select="selectReference" @error="error = $event" /></DialogContent></Dialog>
  </WorkspaceLayout>
</template>
