<template>
  <div class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-white" data-testid="delete-editor-workspace">
    <div v-if="showProtein" class="flex min-h-12 shrink-0 flex-wrap items-center gap-3 border-b bg-card px-4 py-2">
      <WorkspacePanelTabs v-model="activeView" :label="translate('platform.structureWorkspace')" :tabs="[{ value: 'ligand', label: translate('platform.referenceLigand2d') }, { value: 'protein', label: translate('platform.proteinContext3d') }]" />
    </div>

    <div v-show="activeView === 'ligand'" class="min-h-0 flex-1 bg-slate-50">
      <div class="grid h-full min-h-0 grid-cols-[minmax(230px,300px)_minmax(0,1fr)] max-lg:grid-cols-1">
        <aside class="min-h-0 overflow-y-auto border-r border-slate-200 bg-white p-4">
          <div class="space-y-4">
            <div class="space-y-2">
              <label for="delete-edit-mode" class="text-sm font-semibold text-slate-900">{{ translate('platform.editStrategy') }}</label>
              <select
                id="delete-edit-mode"
                v-model="editMode"
                class="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                :disabled="readOnly || !referenceMolfile || previewLoading"
                @change="changeMode"
              >
                <option value="r_group">{{ translate('platform.rGroupGeneration') }}</option>
                <option value="side_chain">{{ translate('platform.sideChainGeneration') }}</option>
                <option value="linker">{{ translate('platform.linkerGeneration') }}</option>
                <option value="scaffold_hopping">{{ translate('platform.scaffoldHopping') }}</option>
                <option value="derivation_site">{{ translate('platform.growFromSelectedSite') }}</option>
                <option value="custom">{{ translate('platform.customDeletion') }}</option>
              </select>
            </div>

            <div v-if="autoMode" class="space-y-3">
              <div class="flex items-center justify-between">
                <h2 class="text-sm font-semibold text-slate-900">{{ translate('platform.generatedEditCandidates') }}</h2>
                <span class="text-xs text-slate-500">{{ candidates.length }}</span>
              </div>
              <p v-if="previewLoading" role="status" class="text-xs text-slate-500">{{ translate('platform.generatingCandidates') }}</p>
              <p v-else-if="!candidates.length" class="text-xs text-amber-700">{{ translate('platform.noValidCandidateWasFoundForThisStrategy') }}</p>
              <template v-else>
                <div class="flex gap-4 text-xs text-slate-600">
                  <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-emerald-500" />{{ translate('platform.retained') }}</span>
                  <span class="inline-flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full bg-rose-500" />{{ translate('platform.deletedRegenerated') }}</span>
                </div>
                <div class="max-h-[min(52vh,420px)] space-y-2 overflow-y-auto pr-1">
                  <button
                    v-for="(candidate, index) in candidates"
                    :key="candidate.id"
                    type="button"
                    class="w-full rounded-md border p-2 text-left text-xs transition-colors"
                    :class="candidate.id === selectedCandidateId ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:bg-slate-50'"
                    :disabled="readOnly || previewLoading || editorLoading"
                    @click="selectCandidate(candidate)"
                  >
                    <span class="font-medium">{{ translate('platform.candidate') }} {{ index + 1 }}</span>
                    <MoleculeViewer
                      :smiles="referenceMolfile"
                      width="100%"
                      height="130px"
                      :highlight-atom-colors="candidateHighlightColors(candidate)"
                      :error-text="translate('platform.failedToRenderCandidate')"
                    />
                  </button>
                </div>
              </template>
            </div>

            <p v-if="editMode === 'custom'" class="rounded-md bg-slate-50 p-3 text-xs text-slate-600">{{ translate('platform.customDeletionHint') }}</p>
            <p v-if="autoMode && customEdit" role="status" class="text-xs text-slate-600">{{ translate('platform.manualCandidateSubmission') }}</p>
            <p v-if="customEdit && editorDirty && graphParts > 1" role="status" class="text-xs text-slate-600">{{ translate('platform.editedGraphParts', { count: graphParts }) }}</p>
            <p v-if="customEdit && graphProblem" role="alert" class="text-sm text-rose-700">{{ graphProblem }}</p>
            <p v-else-if="customEdit && editorDirty && !deletedNodes" role="alert" class="text-sm text-rose-700">{{ translate('platform.structureErrors.DELETE_EDIT_UNCHANGED') }}</p>
            <p v-else-if="customEdit && editorDirty && graphNodes < FEW_GRAPH_NODES" role="status" class="text-sm text-amber-700">{{ translate('platform.editedGraphFewNodes', { count: graphNodes }) }}</p>
            <div v-if="editMode === 'derivation_site'" class="space-y-2 rounded-md bg-slate-50 p-3 text-xs text-slate-600">
              <p>{{ translate('platform.anchorSelectionHint') }}</p>
              <Button size="sm" variant="outline" class="w-full" :disabled="readOnly || !referenceMolfile" @click="captureAnchor">
                {{ anchorAtomIndex === null ? translate('platform.useSelectedAtom') : translate('platform.selectionConfirmed') }}
              </Button>
            </div>
            <p v-if="error" role="alert" class="text-sm text-rose-700">{{ error }}</p>
          </div>
        </aside>

        <section class="relative min-h-0 min-w-0 bg-slate-50">
          <div v-if="!referenceMolfile && !previewLoading" class="flex h-full items-center justify-center px-6 text-center text-sm text-slate-500">
            {{ translate('platform.selectAProteinContextAndReferenceLigand') }}
          </div>
          <p v-if="previewLoading" role="status" class="absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-full bg-white/90 px-3 py-1 text-xs text-slate-500 shadow-sm">{{ translate('platform.loading') }}</p>
          <iframe
            :id="editorId"
            :src="ketcherUrl"
            class="h-full min-h-[360px] w-full border-0"
            :class="referenceMolfile ? '' : 'invisible'"
            :title="translate('platform.customDeletion')"
            @load="loadCurrentEditorMolecule"
          />
          <!-- While a graph is loading the canvas takes no input: an edit made then would be taken for part of the loaded graph or overwritten by it. -->
          <div v-if="previewLoading || editorLoading" class="absolute inset-0 cursor-wait" aria-hidden="true" />
          <div class="absolute bottom-4 right-4 flex gap-2">
            <Button size="sm" variant="outline" :disabled="readOnly || !referenceMolfile || previewLoading || editorLoading" @click="showReference">{{ translate('platform.showReference') }}</Button>
          </div>
        </section>
      </div>
    </div>

    <div v-if="showProtein" v-show="activeView === 'protein'" class="min-h-0 flex-1">
      <slot name="protein">
        <div class="flex min-h-0 h-full flex-col">
          <div class="flex min-h-12 shrink-0 flex-wrap items-center gap-3 border-b bg-card px-4 py-2">
            <h2 class="shrink-0 text-sm font-semibold">{{ translate('platform.structureWorkspace') }}</h2>
          </div>
          <protein3d_molstar
            ref="contextViewer"
            compact
            :if-show-box="false"
            :if-click-event="false"
            :wait-molstar-init="true"
            class="min-h-0 flex-1"
          />
        </div>
      </slot>
    </div>

    <footer v-if="showActions" class="flex shrink-0 flex-wrap justify-end gap-2 border-t border-slate-200 bg-white px-4 py-3">
      <Button variant="outline" :disabled="saving" @click="requestClose">{{ closeLabel ?? translate('platform.close') }}</Button>
      <Button variant="outline" :disabled="saving || !editSessionValue" @click="discard">{{ discardLabel ?? translate('platform.editorMessages.discard') }}</Button>
      <Button :disabled="saving || !canSubmit || !editSessionValue" @click="save">{{ saving ? (savingLabel ?? translate('platform.editorMessages.saving')) : (saveLabel ?? translate('platform.editorMessages.saveAndReturn')) }}</Button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import WorkspacePanelTabs from '@/components/workbench/WorkspacePanelTabs.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useSlots, watch } from 'vue'
import { translate } from '@/i18n'
import { onBeforeRouteLeave } from 'vue-router'
import { cancelWorkflowEditor, getWorkflowEditor, saveWorkflowEditor, saveWorkflowEditorDraft, type EditSession } from '@/api/workflowCommands'
import { downloadBackendDataset, getBackendDataset, previewPropertyOptimizationEdits, type PropertyOptimizationEditCandidate } from '@/api/genovaBackend'
import { getProteinContext } from '@/api/proteinContext'
import { contextReferenceFile, contextReceptorFile, type ProteinContext } from '@/types/proteinContext'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import protein3d_molstar from '@/components/molecule/protein3d_molstar.vue'
import { Button } from '@/components/ui/button'
import { withAppBase } from '@/utils/appBase'
import { displayErrorMessage } from '@/utils/requestError'

export type DeleteEditMode = 'r_group' | 'side_chain' | 'linker' | 'scaffold_hopping' | 'custom' | 'derivation_site'
export type DeleteEditChanges = { mode: DeleteEditMode; candidate_id?: string; edited_molfile?: string; anchor_atom_index?: number }

export type DeleteEditState = {
  mode: DeleteEditMode
  candidateId: string
  anchorAtomIndex: number | null
  referenceMolfile: string
  referenceAtomCount: number
  candidates: PropertyOptimizationEditCandidate[]
  dirty: boolean
  editorDirty: boolean
  loading: boolean
  ready: boolean
  canSubmit: boolean
  graphValid: boolean
  selectedNodes: Record<string, number>
  deletedNodeCount: number
}

const props = withDefaults(defineProps<{
  contextId?: string
  context?: ProteinContext | null
  ligandDatasetId?: string
  editSession?: EditSession | null
  editSessionId?: string
  initialEdit?: Partial<DeleteEditChanges> | null
  embedded?: boolean
  showProtein?: boolean
  showActions?: boolean
  readOnly?: boolean
  saveLabel?: string
  savingLabel?: string
  closeLabel?: string
  discardLabel?: string
}>(), {
  contextId: '',
  context: null,
  ligandDatasetId: '',
  editSession: null,
  editSessionId: '',
  initialEdit: null,
  embedded: false,
  showProtein: false,
  showActions: false,
  readOnly: false,
})
const slots = useSlots()

const emit = defineEmits<{
  state: [state: DeleteEditState]
  preview: [payload: { text: string; format: 'sdf' } | null]
  error: [message: string]
  saved: [result: Record<string, any>]
  cancelled: []
  close: [payload: { dirty: boolean }]
  draft: [payload: { status: 'saving' | 'saved' | 'error'; changes?: Partial<DeleteEditChanges>; error?: string }]
}>()

const editSessionValue = ref<EditSession | null>(props.editSession)
const editMode = ref<DeleteEditMode>((props.initialEdit?.mode || props.editSession?.state.draft?.mode || 'r_group') as DeleteEditMode)
const candidates = ref<PropertyOptimizationEditCandidate[]>([])
const selectedCandidateId = ref('')
const referenceMolfile = ref('')
const referenceAtomCount = ref(0)
const editorDirty = ref(false)
const draftDirty = ref(false)
const editorLoading = ref(false)
const editorSubscribed = ref(false)
const anchorAtomIndex = ref<number | null>(null)
const previewLoading = ref(false)
const error = ref('')
const saving = ref(false)
const activeView = ref<'ligand' | 'protein'>('ligand')
const contextViewer = ref<InstanceType<typeof protein3d_molstar> | null>(null)
const localPreview = ref<{ text: string; format: 'sdf' } | null>(null)
let viewerContextId = ''
const editorId = `delete-ketcher-${Math.random().toString(36).slice(2)}`
const ketcherUrl = withAppBase('static/file/standalone/index.html')
const retainedColor: [number, number, number] = [0.2, 0.75, 0.35]
const deletedColor: [number, number, number] = [0.9, 0.2, 0.25]
const autoMode = computed(() => ['r_group', 'side_chain', 'linker', 'scaffold_hopping'].includes(editMode.value))
const resolvedContextId = computed(() => props.contextId || editSessionValue.value?.state.assets.protein_context_id || '')
const resolvedContext = computed(() => props.context || editSessionValue.value?.state.context as ProteinContext | undefined || null)
const resolvedInitialEdit = computed(() => props.initialEdit || editSessionValue.value?.state.draft || null)
const graphProblem = ref('')
const customEdit = computed(() => editMode.value === 'custom' || (autoMode.value && editorDirty.value))
const ready = computed(() => Boolean(referenceMolfile.value && !previewLoading.value && !editorLoading.value))
const canSubmit = computed(() => {
  if (!ready.value || props.readOnly) return false
  if (customEdit.value) return editorDirty.value && deletedNodes.value > 0 && !graphProblem.value
  if (editMode.value === 'derivation_site') return anchorAtomIndex.value !== null
  return Boolean(selectedCandidateId.value)
})
type CanvasMolecule = { molfile: string; candidateId?: string; custom?: boolean }
let currentMolecule: CanvasMolecule | null = null
let moleculeLoad = Promise.resolve(false)
let active = true
let frameLoaded = false
let previewRequest = 0
let draftTimer: ReturnType<typeof setTimeout> | undefined
let draftRequest = 0
let hydratedKey = ''
let previewKey = ''
let applyingDraft = false
let loadedGraph = '', referenceGraph = ''
const canvasGraph = ref('')
let viewerLoadingContextId = ''
let viewerPromise: Promise<void> | null = null

function candidateHighlightColors(candidate: PropertyOptimizationEditCandidate) {
  const retained = new Set(candidate.retained_atom_indices)
  return Object.fromEntries(Array.from({ length: referenceAtomCount.value }, (_, index) => [index, retained.has(index) ? retainedColor : deletedColor]))
}

function state(): DeleteEditState {
  return {
    mode: customEdit.value ? 'custom' : editMode.value,
    candidateId: selectedCandidateId.value,
    anchorAtomIndex: anchorAtomIndex.value,
    referenceMolfile: referenceMolfile.value,
    referenceAtomCount: referenceAtomCount.value,
    candidates: candidates.value,
    dirty: draftDirty.value,
    editorDirty: editorDirty.value,
    loading: previewLoading.value || editorLoading.value,
    ready: ready.value,
    canSubmit: canSubmit.value,
    graphValid: !graphProblem.value,
    selectedNodes: selectedNodes.value,
    deletedNodeCount: deletedNodes.value,
  }
}

// For the side assistant: the selected nodes counted by element (the canvas shows no node numbers, so none are passed) and
// how many initial nodes are gone.
const selectedNodes = ref<Record<string, number>>({}), deletedNodes = ref(0)
function readCanvasState(editor: any) {
  const struct = editor.editor.struct()
  const counts: Record<string, number> = {}
  for (const id of editor.editor.selection()?.atoms || []) {
    const label = struct.atoms.get(id)?.label
    if (label) counts[label] = (counts[label] || 0) + 1
  }
  selectedNodes.value = counts
  const kept = new Set([...struct.atoms.values()].map((node: any) => node.aam).filter((number: number) => number >= 1 && number <= referenceAtomCount.value))
  deletedNodes.value = referenceAtomCount.value - kept.size
}

// What is on the canvas: node count, connected parts, and a key of its topology (mapped nodes keep their number across edits).
function readGraph(editor: any) {
  const struct = editor.editor.struct()
  const ids: number[] = [...struct.atoms.keys()]
  const bonds: any[] = [...struct.bonds.values()]
  const name = (id: number) => String(struct.atoms.get(id)?.aam || `new${id}`)
  const root = new Map(ids.map(id => [id, id]))
  const find = (id: number): number => { while (root.get(id) !== id) id = root.get(id)!; return id }
  for (const bond of bonds) root.set(find(bond.begin), find(bond.end))
  return {
    nodes: ids.length,
    heavy: ids.filter(id => !['H', 'D', 'T'].includes(struct.atoms.get(id)?.label)).length,
    parts: new Set(ids.map(find)).size,
    key: ids.map(id => {
      const atom = struct.atoms.get(id)
      return `${name(id)}:${atom.label}:${atom.charge || 0}:${atom.isotope || 0}`
    }).sort().join() + '|' + bonds.map(bond => `${[name(bond.begin), name(bond.end)].sort().join('-')}:${bond.type}:${bond.stereo || 0}`).sort().join(),
  }
}

const MIN_GRAPH_NODES = 3
// Below this the engine often finds nothing new; the page only says so, since it cannot predict the engine's result.
const FEW_GRAPH_NODES = 10
const graphNodes = ref(0)
const graphParts = ref(0)
function graphIssue(graph: ReturnType<typeof readGraph>) {
  if (graph.nodes < MIN_GRAPH_NODES) return translate('platform.editedGraphTooSmall', { count: MIN_GRAPH_NODES })
  if (!graph.heavy) return translate('platform.editedGraphOnlyHydrogen')
  return ''
}

function emitState() {
  emit('state', state())
}

function reportError(exception: any, fallback: string) {
  error.value = displayErrorMessage(exception, fallback)
  emit('error', error.value)
}

async function publishPreview(payload: { text: string; format: 'sdf' } | null) {
  localPreview.value = payload
  emit('preview', payload)
  if (slots.protein || !contextViewer.value) return
  await contextViewer.value.overlayStructure(payload?.text || '', payload?.format || 'sdf')
}

async function loadViewerContext() {
  const contextId = resolvedContextId.value
  if (!props.showProtein || slots.protein || activeView.value !== 'protein' || !contextId || !contextViewer.value || viewerContextId === contextId) return
  if (viewerPromise && viewerLoadingContextId === contextId) {
    await viewerPromise
    return
  }
  viewerLoadingContextId = contextId
  const promise = (async () => {
    try {
      const cachedContext = resolvedContext.value
      const context = cachedContext && contextReceptorFile(cachedContext) ? cachedContext : (await getProteinContext(contextId)).data
      if (!contextReceptorFile(context)) throw new Error(translate('platform.structureNotReady'))
      if (!contextReferenceFile(context) && !context.generation_reference) throw new Error(translate('platform.missingContextLigand'))
      await contextViewer.value!.loadContext(context)
      if (resolvedContextId.value !== contextId) return
      viewerContextId = contextId
      if (localPreview.value) await contextViewer.value!.overlayStructure(localPreview.value.text, localPreview.value.format)
    } catch (exception: any) {
      reportError(exception, translate('platform.failedToLoadProteinContext'))
    }
  })()
  viewerPromise = promise
  try {
    await promise
  } finally {
    if (viewerPromise === promise) viewerPromise = null
  }
}

async function loadEditSession() {
  if (!props.editSessionId || editSessionValue.value) return
  try {
    editSessionValue.value = (await getWorkflowEditor(props.editSessionId)).data
    if (editSessionValue.value.kind !== 'delete' || editSessionValue.value.status !== 'open') throw new Error(translate('platform.editorMessages.closed'))
  } catch (exception: any) {
    reportError(exception, translate('platform.editorMessages.loadFailed'))
  }
}

function resetPreview() {
  candidates.value = []
  selectedCandidateId.value = ''
  referenceMolfile.value = ''
  referenceAtomCount.value = 0
  currentMolecule = null
  editorLoading.value = false
  loadedGraph = ''
  referenceGraph = ''
  canvasGraph.value = ''
  editorDirty.value = false
  graphNodes.value = 0
  graphParts.value = 0
  graphProblem.value = ''
  selectedNodes.value = {}
  deletedNodes.value = 0
  anchorAtomIndex.value = null
  draftDirty.value = false
  void publishPreview(null)
  emitState()
}

async function refreshEditPreview(markDirty = false) {
  const contextId = resolvedContextId.value
  if (!contextId) {
    previewRequest++
    previewKey = ''
    hydratedKey = ''
    previewLoading.value = false
    resetPreview()
    return false
  }
  void loadViewerContext()
  if (!previewKey && resolvedInitialEdit.value?.mode) editMode.value = resolvedInitialEdit.value.mode as DeleteEditMode
  const key = `${contextId}:${props.ligandDatasetId}:${editMode.value}`
  if (!markDirty && previewKey === key && (previewLoading.value || referenceMolfile.value)) return true
  previewKey = key
  const request = ++previewRequest
  const ligandId = props.ligandDatasetId
  previewLoading.value = true
  error.value = ''
  resetPreview()
  try {
    const response = await previewPropertyOptimizationEdits({
      protein_context_id: contextId,
      ...(ligandId ? { ligand_dataset_id: ligandId } : {}),
      mode: editMode.value,
    })
    if (!active || request !== previewRequest) return false
    referenceMolfile.value = response.data.reference_molfile
    referenceAtomCount.value = response.data.atom_count
    candidates.value = response.data.candidates
    if (ligandId) {
      const dataset = (await getBackendDataset(ligandId)).data
      const files = dataset.files.filter(file => file.original_filename.toLowerCase().endsWith('.sdf'))
      const file = files.find(item => item.file_role === 'ligand_input') || files.find(item => item.file_role === 'attachment') || files[0]
      if (!file) throw new Error(translate('platform.bindingReferenceUnavailable'))
      const text = await (await downloadBackendDataset(dataset.id, file.id)).data.text()
      if (!active || request !== previewRequest) return false
      await publishPreview({ text, format: 'sdf' })
    } else {
      await publishPreview(null)
    }
    if (!active || request !== previewRequest) return false
    if (!await setEditorMolecule({ molfile: referenceMolfile.value }) || !active || request !== previewRequest) return false
    const key = `${contextId}:${ligandId}:${JSON.stringify(resolvedInitialEdit.value || {})}`
    if (key !== hydratedKey) {
      hydratedKey = key
      await applyInitialEdit(resolvedInitialEdit.value)
    }
    if (!active || request !== previewRequest) return false
    if (markDirty) draftDirty.value = true
    emitState()
    return true
  } catch (exception: any) {
    if (!active || request !== previewRequest) return false
    resetPreview()
    if (markDirty) draftDirty.value = true
    reportError(exception, translate('platform.failedToPrepareReferenceLigand'))
    return false
  } finally {
    if (active && request === previewRequest) {
      previewLoading.value = false
      emitState()
    }
  }
}

// On a slow link the canvas page itself takes long to arrive: the short wait for its editor object starts once the page has loaded.
async function waitForEditor(): Promise<any> {
  for (let sinceLoad = 0; active && sinceLoad < 10000; sinceLoad += frameLoaded ? 50 : 0) {
    const frame = document.getElementById(editorId) as HTMLIFrameElement | null
    const editor = (frame?.contentWindow as any)?.ketcher
    if (editor) {
      if (!editorSubscribed.value && editor.editor.subscribe) {
        editor.editor.subscribe('change', () => {
          if (editorLoading.value || previewLoading.value || applyingDraft || !currentMolecule) return
          const graph = readGraph(editor)
          graphProblem.value = graphIssue(graph)
          graphNodes.value = graph.nodes
          graphParts.value = graph.parts
          readCanvasState(editor)
          const atLoadedGraph = graph.key === loadedGraph
          editorDirty.value = graph.key !== referenceGraph && (!atLoadedGraph || Boolean(currentMolecule.custom))
          selectedCandidateId.value = atLoadedGraph ? currentMolecule.candidateId || '' : ''
          if (graph.key !== canvasGraph.value) {
            canvasGraph.value = graph.key
            draftDirty.value = true
            anchorAtomIndex.value = null
            error.value = ''
          }
          emitState()
        })
        let selectionTimer: ReturnType<typeof setTimeout> | undefined
        editor.editor.subscribe('selectionChange', () => {
          clearTimeout(selectionTimer)
          selectionTimer = setTimeout(() => {
            if (!active || !ready.value) return
            readCanvasState(editor)
            emitState()
          }, 200)
        })
        editorSubscribed.value = true
      }
      return editor
    }
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  throw new Error(translate('platform.moleculeEditorFailedToInitialize'))
}

// The editor's load call returns before the graph is on the canvas; the load ends with the change events that leave the graph's node count on it.
// On a cold start a change event comes well before the graph does, so a quiet spell alone is not enough.
function loadLanded(editor: any, molfile: string) {
  const expected = Number(molfile.match(/^M {2}V30 COUNTS (\d+)/m)?.[1] ?? molfile.split('\n')[3]?.slice(0, 3))
  return new Promise<void>(resolve => {
    let quiet: ReturnType<typeof setTimeout> | undefined
    const finish = () => { clearTimeout(limit); clearTimeout(quiet); editor.editor.unsubscribe?.('change', subscriber); resolve() }
    let limit = setTimeout(finish, 10000)
    let holdsGraph = false
    const subscriber = editor.editor.subscribe('change', () => {
      clearTimeout(quiet)
      if (expected > 0 && editor.editor.struct().atoms.size !== expected) return
      quiet = setTimeout(finish, 100)
      if (!holdsGraph) { holdsGraph = true; clearTimeout(limit); limit = setTimeout(finish, 3000) }
    })
  })
}

function setEditorMolecule(molecule: CanvasMolecule): Promise<boolean> {
  currentMolecule = molecule
  editorLoading.value = true
  // The iframe has one canvas. Let an earlier load finish before replacing it.
  const load = moleculeLoad.catch(() => false).then(async () => {
    await nextTick()
    if (!active || currentMolecule !== molecule || !document.getElementById(editorId)) return false
    const editor = await waitForEditor()
    if (!active || currentMolecule !== molecule) return false
    editor.editor.setOptions?.(JSON.stringify({ showAtomIds: false }))
    const landed = loadLanded(editor, molecule.molfile)
    await editor.setMolecule(molecule.molfile)
    await landed
    if (!active || currentMolecule !== molecule) return false
    const graph = readGraph(editor)
    loadedGraph = graph.key
    canvasGraph.value = graph.key
    if (molecule.molfile === referenceMolfile.value) referenceGraph = graph.key
    editorDirty.value = Boolean(molecule.custom) && graph.key !== referenceGraph
    selectedCandidateId.value = molecule.candidateId || ''
    graphProblem.value = graphIssue(graph)
    graphNodes.value = graph.nodes
    graphParts.value = graph.parts
    readCanvasState(editor)
    // Undo stops at the loaded graph instead of emptying the canvas. The editor has no public call to clear its history.
    if (Array.isArray(editor.editor.historyStack)) { editor.editor.historyStack.length = 0; editor.editor.historyPtr = 0 }
    return true
  }).finally(() => {
    if (currentMolecule === molecule) editorLoading.value = false
  })
  moleculeLoad = load
  return load
}

async function loadCurrentEditorMolecule() {
  frameLoaded = true
  // A load already in progress is waiting for this page and puts the graph on it.
  if (!currentMolecule || editorLoading.value) return
  editorSubscribed.value = false
  await setEditorMolecule(currentMolecule)
  emitState()
}

async function selectCandidate(candidate: PropertyOptimizationEditCandidate, markDirty = true) {
  if (props.readOnly) return
  anchorAtomIndex.value = null
  if (!await setEditorMolecule({ molfile: candidate.retained_molfile, candidateId: candidate.id })) return
  if (markDirty) draftDirty.value = true
  emitState()
}

function changeMode() {
  if (props.readOnly) return
  void refreshEditPreview(true)
}

async function showReference() {
  if (!referenceMolfile.value || props.readOnly) return
  selectedCandidateId.value = ''
  anchorAtomIndex.value = null
  if (!await setEditorMolecule({ molfile: referenceMolfile.value })) return
  draftDirty.value = true
  emitState()
}

async function captureAnchor() {
  if (props.readOnly) return
  try {
    const editor = await waitForEditor()
    const selection = editor.editor.selection()
    const atoms = selection?.atoms || []
    if (atoms.length !== 1) throw new Error(translate('platform.selectExactlyOneAtom'))
    const mapped = editor.editor.struct().atoms.get(atoms[0])?.aam
    if (typeof mapped !== 'number' || !Number.isInteger(mapped) || mapped < 1) throw new Error(translate('platform.editorMessages.mappingMissing'))
    anchorAtomIndex.value = mapped - 1
    selectedCandidateId.value = ''
    draftDirty.value = true
    emitState()
  } catch (exception: any) {
    reportError(exception, translate('platform.failedToReadSelectedAtom'))
  }
}

async function getChanges(requireValid = true): Promise<DeleteEditChanges | Partial<DeleteEditChanges> | null> {
  if (requireValid && !canSubmit.value) return null
  if (editMode.value === 'derivation_site') return { mode: editMode.value, ...(anchorAtomIndex.value === null ? {} : { anchor_atom_index: anchorAtomIndex.value }) }
  if (customEdit.value) {
    if (!editorDirty.value) return { mode: 'custom' }
    const molecule = currentMolecule
    const graph = canvasGraph.value
    const molfile = await (await waitForEditor()).getMolfile('v3000')
    if (molecule !== currentMolecule || graph !== canvasGraph.value || (requireValid && !canSubmit.value)) return null
    return { mode: 'custom', edited_molfile: molfile }
  }
  return { mode: editMode.value, ...(selectedCandidateId.value ? { candidate_id: selectedCandidateId.value } : {}) }
}

async function persistDraft(): Promise<boolean> {
  const session = editSessionValue.value
  if (!session || session.status !== 'open' || !draftDirty.value || !ready.value || applyingDraft || saving.value) return true
  let changes: DeleteEditChanges | Partial<DeleteEditChanges> | null
  try {
    changes = await getChanges(false)
  } catch (exception: any) {
    const message = displayErrorMessage(exception, translate('platform.editorMessages.draftSaveFailed'))
    emit('draft', { status: 'error', error: message })
    reportError(exception, message)
    return false
  }
  if (!changes) return true
  const request = ++draftRequest
  emit('draft', { status: 'saving', changes })
  try {
    await saveWorkflowEditorDraft(session.id, changes)
    if (active && request === draftRequest) emit('draft', { status: 'saved', changes })
    return true
  } catch (exception: any) {
    if (active && request === draftRequest) {
      const message = displayErrorMessage(exception, translate('platform.editorMessages.draftSaveFailed'))
      emit('draft', { status: 'error', changes, error: message })
      reportError(exception, message)
    }
    return false
  }
}

async function save() {
  const session = editSessionValue.value
  if (!session || session.status !== 'open' || saving.value || props.readOnly) return false
  saving.value = true
  error.value = ''
  if (draftTimer) clearTimeout(draftTimer)
  draftRequest++
  try {
    const changes = await getChanges()
    if (!changes) return false
    await saveWorkflowEditorDraft(session.id, changes)
    const result = (await saveWorkflowEditor(session.id, changes)).data
    draftDirty.value = false
    editorDirty.value = false
    editSessionValue.value = { ...session, status: 'saved', state: { ...session.state, draft: changes } }
    emitState()
    emit('saved', result)
    return true
  } catch (exception: any) {
    reportError(exception, translate('platform.editorMessages.saveFailed'))
    return false
  } finally {
    saving.value = false
  }
}

async function discard() {
  const session = editSessionValue.value
  if (!session || saving.value) return false
  saving.value = true
  try {
    await cancelWorkflowEditor(session.id)
    emit('cancelled')
    return true
  } catch (exception: any) {
    reportError(exception, translate('platform.editorMessages.closeFailed'))
    return false
  } finally {
    saving.value = false
  }
}

function requestClose() {
  emit('close', { dirty: draftDirty.value })
}

async function applyInitialEdit(edit: Partial<DeleteEditChanges> | null | undefined) {
  if (!edit?.mode) return
  // A draft saved before anything was picked or edited holds only the strategy, which is already applied.
  if (!props.initialEdit && !edit.edited_molfile && edit.anchor_atom_index === undefined && !edit.candidate_id) return
  applyingDraft = true
  try {
    editMode.value = edit.mode
    if (edit.mode === 'custom') {
      if (!edit.edited_molfile) throw new Error(translate('platform.restoreTaskUnavailable'))
      await setEditorMolecule({ molfile: edit.edited_molfile, custom: true })
    } else if (edit.mode === 'derivation_site') {
      if (!Number.isInteger(edit.anchor_atom_index) || edit.anchor_atom_index! < 0 || edit.anchor_atom_index! >= referenceAtomCount.value) throw new Error(translate('platform.restoreTaskUnavailable'))
      anchorAtomIndex.value = edit.anchor_atom_index!
    } else {
      const candidate = candidates.value.find(item => item.id === edit.candidate_id)
      if (!candidate) throw new Error(translate('platform.restoreTaskUnavailable'))
      await selectCandidate(candidate, false)
    }
    draftDirty.value = false
  } finally {
    await nextTick()
    await new Promise(resolve => setTimeout(resolve, 0))
    if (edit.mode !== 'custom') editorDirty.value = false
    applyingDraft = false
    draftDirty.value = false
    emitState()
  }
}

watch(() => props.editSession, value => {
  editSessionValue.value = value
}, { deep: true })
watch(resolvedInitialEdit, value => {
  if (value?.mode && !draftDirty.value && value.mode !== editMode.value) {
    editMode.value = value.mode as DeleteEditMode
    if (!referenceMolfile.value || previewLoading.value) return
    void refreshEditPreview()
    return
  }
  if (!referenceMolfile.value || previewLoading.value) return
  const key = `${resolvedContextId.value}:${props.ligandDatasetId}:${JSON.stringify(value || {})}`
  if (key === hydratedKey) return
  hydratedKey = key
  void applyInitialEdit(value)
}, { deep: true })
watch([resolvedContextId, resolvedContext], () => { void loadViewerContext() })
watch(activeView, value => { if (value === 'protein') void nextTick(() => loadViewerContext()) })
watch([resolvedContextId, () => props.ligandDatasetId], ([contextId, ligandId], previous) => {
  if (contextId === previous?.[0] && ligandId === previous?.[1]) return
  void refreshEditPreview()
})
watch([draftDirty, editMode, selectedCandidateId, anchorAtomIndex, canvasGraph], () => {
  emitState()
  if (!editSessionValue.value || applyingDraft || !draftDirty.value) return
  if (draftTimer) clearTimeout(draftTimer)
  draftTimer = setTimeout(() => { void persistDraft() }, 300)
})

// Changes not saved yet ask before the page is closed, reloaded or left; a forced sign-in redirect is not blocked.
function confirmUnload(event: BeforeUnloadEvent) { if (draftDirty.value && !props.readOnly) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(to => to.path === '/login' || !draftDirty.value || props.readOnly || window.confirm(translate('platform.unsavedChanges.leave')))

onMounted(async () => {
  window.addEventListener('beforeunload', confirmUnload)
  await loadEditSession()
  if (editSessionValue.value && (editSessionValue.value.kind !== 'delete' || editSessionValue.value.status !== 'open')) {
    reportError(new Error(translate('platform.editorMessages.closed')), translate('platform.editorMessages.closed'))
    return
  }
  await loadViewerContext()
  if (resolvedContextId.value) await refreshEditPreview()
})

onBeforeUnmount(() => {
  active = false
  window.removeEventListener('beforeunload', confirmUnload)
  if (draftTimer) clearTimeout(draftTimer)
})

defineExpose({
  getChanges: () => getChanges(true),
  getDraftChanges: () => getChanges(false),
  refresh: () => refreshEditPreview(),
  save,
  discard,
  saveDraft: persistDraft,
  getState: state,
  // The page's own navigation after a successful submit is not leaving with unsent changes.
  markSubmitted: () => { draftDirty.value = false },
})
</script>
