<template>
  <AppFrame :task="store.context && !route.query.restore_job_id ? { name: taskName || defaultTaskName, context: store.context.name, draft: !route.query.restore_job_id } : undefined">
    <div class="module-workbench flex flex-col">
      <PageHeader :title="$t('platform.leadOptimization')" :help="{path: '/help', query: {article: 'lead-optimization'}}" :help-label="$t('platform.operationGuide')"><Button v-if="!panelOpen" variant="outline" @click="panelOpen = true">{{ $t('platform.openPanel') }}</Button></PageHeader>
      <p v-if="route.query.restore_job_id" role="status" class="shrink-0 border-b bg-accent px-6 py-2 text-xs text-primary">{{ $t(restoring ? 'platform.loading' : restoreFailed ? 'platform.restoreTaskUnavailable' : 'platform.restoredTaskHint') }}</p>

      <WorkspaceLayout v-model:open="panelOpen" :title="$t('platform.parameters')" resizable>
        <template #panel-header><WorkspacePanelTabs v-model="auxiliaryTab" :label="L('操作面板', 'Controls')" :tabs="[{ value: 'parameters', label: $t('platform.parameters') }, ...(!linkedEditor ? [{ value: 'assistant', label: L('助手', 'Assistant') }] : [])]" @update:model-value="value => { if (value === 'assistant') assistantOpened = true }" /></template>
        <template #auxiliary>
        <ModuleAssistantPanel v-if="assistantOpened && !linkedEditor" v-show="auxiliaryTab === 'assistant'" ref="assistantPanel" module="property_optimization" :context="assistantContext" :apply="applyAssistant" />
        <div v-show="auxiliaryTab === 'parameters'" class="min-w-0">
          <div class="workbench-form" :inert="restoring">
            <ProteinContextSelector
              :key="contextRefresh"
              :model-value="store.contextId"
              :context="store.context"
              @select="selectContext"
              @create="createContext"
              @edit="editContext"
              @error="error = $event"
            >
              <ProteinContextSummary :context="store.context" :engine="engine" compact editable @edit="editContext" @updated="store.setContext($event)" />
            </ProteinContextSelector>

            <label class="block text-sm">{{ $t('platform.epsoEngine') }}
              <select v-model="engine" class="mt-2 h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" :disabled="restoring || linkedEditor">
                <option value="delete">DELETE</option><option value="epso">ECloud EPSO</option>
              </select>
            </label>

            <div v-if="store.context" class="space-y-3">
              <div>
                <div class="text-sm font-semibold text-slate-900">{{ $t('platform.referenceLigand') }}</div>
                <p class="mt-1 text-xs text-slate-500">{{ ligandLabel }}</p>
              </div>
              <p v-if="!hasReferenceLigand" class="text-sm text-amber-700">
                {{ $t('platform.missingContextLigand') }}
              </p>
              <FileDatasetInput
                v-if="engine === 'epso'"
                accept=".sdf"
                :label="ligandLabel"
                @upload="uploadLigand"
                @choose="selectorOpen = true"
              />
              <Button variant="outline" @click="editContext">{{ $t('platform.editSiteReference') }}</Button>
              <Button v-if="engine === 'epso' && ligandDatasetId && hasContextLigand" variant="outline" @click="ligandDatasetId = ''; ligandOverrideLabel = ''; refreshReferencePreview()">{{ $t('platform.epsoUseContextSeed') }}</Button>
            </div>

            <div class="space-y-2">
              <Label>{{ $t('platform.maximumValidMoleculesToReturn') }}</Label>
              <Input v-model.number="numMolecules" type="number" min="1" :max="moleculeLimit" step="1" />
              <p class="text-xs text-slate-500">{{ $t('platform.numberInput.range', { range: $t('platform.numberInput.between', { min: 1, max: moleculeLimit }) }) }}</p>
              <p v-if="moleculeLimit === 500 && Number(numMolecules) > moleculeLimit" role="alert" class="text-xs text-rose-700">{{ $t('platform.epsoAffinityCountLimit') }}</p>
              <p v-if="engine === 'epso'" class="text-xs leading-relaxed text-slate-500">{{ $t('platform.epsoCountHint') }}</p>
            </div>
            <div class="space-y-2">
              <Label>{{ $t('platform.taskName') }}</Label>
              <Input v-model="taskName" :placeholder="defaultTaskName" :maxlength="NAME_MAX_LENGTH" />
              <p class="text-xs" :class="nameTooLong(taskName) ? 'text-rose-700' : 'text-slate-500'">{{ nameLengthHint(taskName) }}</p>
            </div>
            <section v-if="engine === 'epso'" class="objective-section" aria-labelledby="objectives-title">
              <div class="flex items-center gap-3">
                <h2 id="objectives-title" class="flex-1 text-sm font-semibold text-slate-900">{{ $t('platform.epsoObjectives') }}</h2>
                <span class="text-xs tabular-nums text-muted-foreground">{{ objectives.length }} / {{ epsoMetrics.length }}</span>
              </div>
              <div class="mt-3 space-y-2">
                <article v-for="(objective, index) in objectives" :key="index" class="objective-card p-3">
                  <div class="flex items-start gap-2">
                    <div class="objective-fields">
                      <label class="objective-field">{{ $t('platform.epsoMetric') }}
                        <select v-model="objective.metric" @change="resetObjective(objective)">
                          <option v-for="metric in epsoMetrics" :key="metric" :value="metric" :disabled="objectives.some((item, i) => i !== index && item.metric === metric)">{{ $t('platform.epsoMetric_' + metric) }}</option>
                        </select>
                      </label>
                      <label v-if="objective.metric !== 'gnina_affinity'" class="objective-field">{{ $t('platform.epsoMode') }}
                        <select v-model="objective.mode" @change="resetObjective(objective)">
                          <option v-for="mode in epsoModes" :key="mode" :value="mode">{{ $t('platform.epsoMode_' + mode) }}</option>
                        </select>
                      </label>
                      <label v-for="field in objectiveFields[objective.mode]" :key="field" class="objective-field">{{ $t('platform.epsoField_' + field) }}
                        <Input v-model.number="objective[field]" type="number" step="any" />
                      </label>
                      <p v-if="objectiveProblem(objective)" role="alert" class="col-span-full text-xs text-rose-700">{{ objectiveProblem(objective) }}</p>
                    </div>
                    <Button size="icon" variant="ghost" class="mt-5 h-9 w-8 shrink-0 text-slate-400 hover:bg-rose-50 hover:text-rose-600" :aria-label="$t('platform.epsoRemove') + ' ' + $t('platform.epsoMetric_' + objective.metric)" :title="$t('platform.epsoRemove')" :disabled="objectives.length === 1" @click="objectives.splice(index, 1)"><Trash2 class="h-4 w-4" aria-hidden="true" /></Button>
                  </div>
                  <details class="mt-2">
                    <summary class="cursor-pointer text-xs font-medium text-slate-500">{{ L('更多设置', 'More settings') }}</summary>
                    <div class="mt-2 grid grid-cols-2 gap-2">
                      <label class="objective-field">{{ $t('platform.epsoWeight') }}<Input v-model.number="objective.weight" type="number" min="0.000001" step="any" /></label>
                      <label v-if="!['maximize', 'minimize', 'seed_relative'].includes(objective.mode)" class="objective-field">{{ $t('platform.epsoSoftness') }}<Input v-model.number="objective.softness" type="number" min="0.000001" step="any" /></label>
                    </div>
                  </details>
                </article>
              </div>
              <p v-if="affinityDockingLimit" class="mt-2 text-xs text-slate-600">{{ $t('platform.epsoAffinityBudget', { count: affinityDockingLimit }) }}</p>
              <details class="mt-2 space-y-2 text-xs text-slate-500">
                <summary class="cursor-pointer">{{ L('指标说明', 'Metric notes') }}</summary>
                <p class="leading-relaxed">{{ $t('platform.epsoMetricHint') }}</p>
                <p class="leading-relaxed">{{ $t('platform.epsoAffinityHelp') }}</p>
              </details>
              <Button variant="outline" class="mt-3 h-9 w-full gap-2 border-dashed" :disabled="objectives.length === epsoMetrics.length" @click="addObjective"><Plus class="h-4 w-4" aria-hidden="true" />{{ $t('platform.epsoAddObjective') }}</Button>
            </section>
            <details v-if="engine === 'epso'" :open="epsoAdvancedOpen" @toggle="epsoAdvancedOpen = ($event.target as HTMLDetailsElement).open" class="rounded-lg border border-slate-200 p-3">
              <summary class="cursor-pointer text-sm font-semibold text-slate-700">{{ $t('platform.epsoAdvanced') }}</summary>
              <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <label class="objective-field">{{ $t('platform.epsoParticles') }}<Input v-model.number="optimizer.num_particles" type="number" min="1" max="1000" step="1" /><span class="text-xs font-normal leading-relaxed text-slate-500">{{ $t('platform.epsoParticlesHint') }}</span></label>
                <label class="objective-field">{{ $t('platform.epsoSteps') }}<Input v-model.number="optimizer.num_steps" type="number" min="1" max="1000" step="1" /><span class="text-xs font-normal leading-relaxed text-slate-500">{{ $t('platform.epsoStepsHint') }}</span></label>
                <label class="objective-field">{{ $t('platform.epsoSeed') }}<Input v-model.number="optimizer.seed" type="number" min="0" max="4294967295" step="1" /><span class="text-xs font-normal leading-relaxed text-slate-500">{{ $t('platform.epsoSeedHint') }}</span></label>
              </div>
            </details>
            <GenerationAdvanced v-if="engine === 'delete'" ref="advanced" v-model="sampling" engine="delete" />
            <Button v-if="editSession" variant="outline" @click="cancelEdit">{{ L('取消并返回', 'Cancel and return') }}</Button>
            <p v-if="pendingSubmission && !submitting" role="status" class="text-sm text-amber-700">{{ L('暂未确认任务是否创建，请重试原提交；当前参数改动仍保留。', 'Task creation is not confirmed. Retry the original submission; your edits are preserved.') }}</p>
            <p v-else-if="confirmedJob && !submitting" role="status" class="text-sm text-green-700">{{ L('原任务已确认，可明确发起新任务。', 'Original task confirmed. You may submit a new task.') }} <RouterLink :to="{path:'/dashboard',query:{job_id:confirmedJob}}" class="underline">{{ L('查看任务', 'View task') }}</RouterLink></p>
            <Button class="w-full" :disabled="submitting || (!pendingSubmission && !canSubmit)" @click="submit">
              {{ linkedEditor ? L('确认编辑并返回', 'Confirm edit and return') : submitting ? $t('platform.submitting') : pendingSubmission ? L('重试原提交', 'Retry original submission') : $t('platform.submitTask') }}
            </Button>
            <p v-if="error" class="text-sm text-rose-700">{{ error }}</p>
          </div>
        </div>

        </template>
        <div class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-white">
          <div class="workbench-toolbar"><h2>{{ $t('platform.structureWorkspace') }}</h2></div>
          <div class="relative isolate flex min-h-0 flex-1 flex-col overflow-hidden">
          <FeedbackState v-if="!store.context" class="absolute inset-0 z-[60] bg-white" :title="$t('platform.selectAProteinContextAndReferenceLigand')" />
            <div class="workbench-toolbar"><WorkspacePanelTabs v-model="activeView" :label="$t('platform.structureWorkspace')" :tabs="engine === 'epso' ? [{ value: 'protein', label: $t('platform.proteinContext3d') }, { value: 'ligand', label: $t('platform.referenceLigand2d') }] : [{ value: 'ligand', label: $t('platform.referenceLigand2d') }, { value: 'protein', label: $t('platform.proteinContext3d') }]" /></div>
            <div v-if="engine === 'epso'" v-show="activeView === 'ligand'" class="relative min-h-0 flex-1 bg-slate-50">
              <div v-if="!hasReferenceLigand" class="flex h-full items-center justify-center text-sm text-slate-500">
                {{ $t('platform.selectAProteinContextAndReferenceLigand') }}
              </div>
              <div v-else class="flex h-full flex-col p-4 sm:p-6">
                <div class="flex min-h-[380px] flex-1 flex-col rounded-lg border border-slate-200 bg-white">
                  <div class="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
                    <div class="min-w-0">
                      <h2 class="text-sm font-semibold text-slate-900">{{ $t('platform.referenceLigand') }}</h2>
                      <p class="mt-1 break-words text-xs text-slate-500">{{ ligandLabel }}</p>
                    </div>
                    <span class="shrink-0 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">2D</span>
                  </div>
                  <div class="flex min-h-[300px] flex-1 items-center justify-center p-4">
                    <p v-if="previewLoading" role="status" class="text-sm text-slate-500">{{ $t('platform.loading') }}</p>
                    <MoleculeViewer v-else-if="referenceMolfile" :smiles="referenceMolfile" regenerate-coords width="480px" height="360px" class="max-w-full" :error-text="$t('platform.failedToPrepareReferenceLigand')" />
                    <p v-else class="text-sm text-slate-500">{{ $t('platform.failedToPrepareReferenceLigand') }}</p>
                  </div>
                </div>
              </div>
            </div>
            <div v-show="activeView === 'protein'" class="relative min-h-0 flex-1">
              <protein3d_molstar
                ref="viewer"
                compact
                :if-show-box="false"
                :if-click-event="false"
                :wait-molstar-init="true"
                class="h-full min-h-0"
              />
            </div>
          <DeleteEditorWorkspace
            v-if="deleteEditorOpened"
            v-show="engine === 'delete' && activeView === 'ligand'"
            ref="deleteEditor"
            :context-id="store.contextId"
            :edit-session="editSession"
            :initial-edit="initialDeleteEdit?.contextId === store.contextId ? initialDeleteEdit?.edit : null"
            :embedded="linkedEditor"
            @state="syncDeleteState"
            @error="error = $event"
          />
          </div>
        </div>
      </WorkspaceLayout>
    </div>

    <Dialog v-model:open="selectorOpen">
      <DialogContent class="max-h-[80vh] max-w-4xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>{{ $t('platform.selectReferenceLigand') }}</DialogTitle>
          <DialogDescription>{{ $t('platform.chooseAnSdfDataset') }}</DialogDescription>
        </DialogHeader>
        <DataCenterSelector :filetypes="['sdf']" @select="selectDataset" @error="error = $event" />
      </DialogContent>
    </Dialog>
  </AppFrame>
</template>

<script setup lang="ts">
import '@/assets/module-workbench.css'
import WorkspacePanelTabs from '@/components/workbench/WorkspacePanelTabs.vue'
import FeedbackState from '@/components/workbench/FeedbackState.vue'

import ModuleAssistantPanel from '@/pages/agent/components/ModuleAssistantPanel.vue'
import { useModuleSuggestion } from '@/composables/useModuleSuggestion'
import type { ModuleContext, ModuleSuggestion } from '@/api/moduleAssistant'
import { cancelWorkflowEditor, getWorkflowEditor, type EditSession } from "@/api/workflowCommands"
import i18n, { translate } from '@/i18n'
import { NAME_MAX_LENGTH, nameLengthHint, nameTooLong } from '@/utils/nameLength'

import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Trash2 } from 'lucide-vue-next'
import { isProteinContextReady, contextReceptorFile, matchesSavedReference, savedEpsoSeed, sourceReferenceId } from '@/types/proteinContext'
import { getProteinContext } from '@/api/proteinContext'
import {
  getBackendJob,
  getBackendDataset,
  downloadBackendDataset,
  uploadBackendDataset,
} from '@/api/genovaBackend'
import PageHeader from '@/components/workbench/PageHeader.vue'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import { useWorkspaceState } from '@/composables/useWorkspace'
import AppFrame from '@/components/Layout/appFrame.vue'
import DataCenterSelector from '@/components/common/dataCenterSelector.vue'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import DeleteEditorWorkspace, { type DeleteEditChanges, type DeleteEditState } from './components/DeleteEditorWorkspace.vue'
import protein3d_molstar from '@/components/molecule/protein3d_molstar.vue'
import ProteinContextSummary from '@/components/protein-preparation/ProteinContextSummary.vue'
import ProteinContextSelector from '@/components/protein-preparation/ProteinContextSelector.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import GenerationAdvanced from '@/components/common/GenerationAdvanced.vue'
import { useProteinContextStore } from '@/stores/proteinContext'
import { displayErrorMessage } from '@/utils/requestError'
import { generationCountLimit } from '@/utils/generationForm'

const FileDatasetInput = defineComponent({
  props: { accept: String, label: String },
  emits: ['upload', 'choose'],
  setup(props, { emit }) {
    return () => h('div', { class: 'rounded-lg border-2 border-dashed border-slate-300 p-4 text-center' }, [
      h('p', { class: 'mb-3 text-xs text-slate-500' }, props.label || translate('platform.notSelected')),
      h('div', { class: 'flex justify-center gap-2' }, [
        h('label', { class: 'inline-flex h-8 w-28 cursor-pointer items-center justify-center rounded-md border border-input bg-background px-3 text-xs font-medium shadow-sm' }, [
          translate('platform.uploadSdf'),
          h('input', {
            class: 'hidden',
            type: 'file',
            accept: props.accept,
            onChange: (event: Event) => {
              const target = event.target as HTMLInputElement
              const file = target.files?.[0]
              target.value = ''
              if (file) emit('upload', file)
            },
          }),
        ]),
        h(Button, { class: 'w-28', size: 'sm', variant: 'outline', onClick: () => emit('choose') }, () => translate('platform.dataCenter')),
      ]),
    ])
  },
})

import { useJobSubmission } from '@/composables/useJobSubmission'
const route = useRoute()
const { pendingSubmission, confirmedJob, sendJob } = useJobSubmission(route.query.edit_session_id ? 'molopt-editor:' + String(route.query.edit_session_id) : 'molopt')
const { panelOpen, epsoAdvancedOpen } = useWorkspaceState('molopt-workspace', () => String(route.query.restore_job_id || route.query.edit_session_id || 'draft'), { panelOpen: true, epsoAdvancedOpen: false })
const router = useRouter()
const store = useProteinContextStore()
store.clear()
const viewer = ref<InstanceType<typeof protein3d_molstar> | null>(null)
const ligandDatasetId = ref('')
const ligandOverrideLabel = ref('')
const selectorOpen = ref(false)
const engine = ref<'delete' | 'epso'>(route.query.engine === 'epso' ? 'epso' : 'delete')
const deleteEditorOpened = ref(engine.value === 'delete')
const L = (zh: string, en: string) => i18n.global.locale.value.startsWith('zh') ? zh : en
const auxiliaryTab = ref('parameters'), assistantOpened = ref(false)
const assistantPanel = ref<InstanceType<typeof ModuleAssistantPanel>>()
const moduleSuggestion = useModuleSuggestion('property_optimization')
const advanced = ref<InstanceType<typeof GenerationAdvanced> | null>(null)
const sampling = ref<Record<string, number | string>>({ beam_size: 500, max_steps: 50, element_threshold: 0.3, bond_threshold: 0.4, seed: 2023 })
type Objective = { metric: string; mode: string; weight: number; lower?: number; upper?: number; target?: number; softness?: number }
const epsoMetrics = ['qed', 'sa', 'mw', 'logp', 'lipinski', 'hba', 'hbd', 'heavy_atom_count', 'similarity', 'gnina_affinity']
const epsoModes = ['lower_bound', 'upper_bound', 'range', 'target', 'maximize', 'minimize']
const objectiveFields: Record<string, Array<'lower' | 'upper' | 'target'>> = { lower_bound: ['lower'], upper_bound: ['upper'], range: ['lower', 'upper'], target: ['target'], maximize: ['lower', 'upper'], minimize: ['lower', 'upper'], seed_relative: [] }
const objectives = ref<Objective[]>([
  { metric: 'qed', mode: 'lower_bound', lower: 0.6, softness: 0.1, weight: 1 },
  { metric: 'sa', mode: 'lower_bound', lower: 0.6, softness: 0.1, weight: 1 },
  { metric: 'mw', mode: 'range', lower: 250, upper: 500, softness: 50, weight: 1 },
])
const optimizer = ref({ num_particles: 200, num_swarms: 1, num_steps: 20, seed: 2024 })
const affinityDockingLimit = computed(() => {
  const { num_particles: particles, num_steps: steps } = optimizer.value
  if (!objectives.value.some(item => item.metric === 'gnina_affinity')) return 0
  return Number.isInteger(particles) && particles > 0 && Number.isInteger(steps) && steps > 0 ? 1 + particles * steps : 0
})
const assistantContext = computed<ModuleContext>(() => ({ engine: engine.value, protein_context_id: store.contextId || undefined, ligand_dataset_id: engine.value === 'epso' ? ligandDatasetId.value || undefined : undefined,
  form: { engine: engine.value, num_molecules: Number(numMolecules.value), ...(engine.value === 'epso' ? { objectives: objectives.value, optimizer: optimizer.value } : { ...sampling.value, ...(editorState.value ? { editor_state: editorState.value } : {}) }) } }))
function applyAssistantChanges(changes: Record<string, any>) {
  if ('num_molecules' in changes) numMolecules.value = changes.num_molecules
  if (engine.value === 'epso') {
    if ('objectives' in changes) objectives.value = JSON.parse(JSON.stringify(changes.objectives))
    if ('optimizer' in changes) optimizer.value = JSON.parse(JSON.stringify(changes.optimizer))
  } else for (const [key, value] of Object.entries(changes)) if (key in sampling.value) sampling.value[key] = value
}
function applyAssistant(suggestion: ModuleSuggestion) {
  if (restoring.value || submitting.value) throw new Error(L('请等待当前操作完成。', 'Wait for the current operation.'))
  applyAssistantChanges(Object.fromEntries(suggestion.changes.map(change => [change.field, change.after])))
}
function resetObjective(objective: Objective) {
  delete objective.lower; delete objective.upper; delete objective.target; delete objective.softness
  if (objective.metric === 'gnina_affinity') {
    objective.mode = 'seed_relative'
    return
  }
  if (objective.mode === 'seed_relative') objective.mode = 'lower_bound'
  const high = objective.metric === 'lipinski' ? 5 : objective.metric === 'mw' ? 500 : 1
  for (const field of objectiveFields[objective.mode]) objective[field] = field === 'lower' ? 0 : high
  if (!['maximize', 'minimize'].includes(objective.mode)) objective.softness = ['qed', 'sa', 'similarity'].includes(objective.metric) ? 0.1 : objective.metric === 'mw' ? 50 : objective.metric === 'logp' ? 0.5 : 1
}
// Same rules the server applies (genova_runtime/epso_objectives.py): every value given a finite number, weight and softness
// above 0, values inside each metric's natural range, lower < upper. A key left out (an assistant change may do that) gets the
// server's default.
const metricBounds: Record<string, [number, number | null]> = { qed: [0, 1], sa: [0, 1], mw: [0, null], lipinski: [0, 5], hba: [0, null], hbd: [0, null], heavy_atom_count: [0, null], similarity: [0, 1] }
const objectiveLabels = { lower: 'platform.epsoField_lower', upper: 'platform.epsoField_upper', target: 'platform.epsoField_target', weight: 'platform.epsoWeight', softness: 'platform.epsoSoftness' }
function objectiveProblem(objective: Objective) {
  const bounds = metricBounds[objective.metric]
  // An empty or unreadable number box leaves '' in the model (v-model.number).
  const empty = (Object.keys(objectiveLabels) as Array<keyof typeof objectiveLabels>).filter(field => objective[field] !== undefined && !Number.isFinite(objective[field]))
  if (empty.length) {
    const names = empty.map(field => translate(objectiveLabels[field]))
    return L(`请填写有效数字：${names.join('、')}`, `Enter a number for: ${names.join(', ')}`)
  }
  if (objective.weight <= 0 || (objective.softness !== undefined && objective.softness <= 0)) return L('权重和过渡宽度需大于 0', 'Weight and softness must be greater than 0')
  const values = objectiveFields[objective.mode]?.map(field => objective[field]).filter((value): value is number => typeof value === 'number') || []
  if (bounds && values.some(value => value < bounds[0] || (bounds[1] !== null && value > bounds[1]))) {
    return bounds[1] === null ? L(`取值不能小于 ${bounds[0]}`, `Values must be at least ${bounds[0]}`) : L(`取值需在 ${bounds[0]}～${bounds[1]} 之间`, `Values must be between ${bounds[0]} and ${bounds[1]}`)
  }
  if (typeof objective.lower === 'number' && typeof objective.upper === 'number' && objective.lower >= objective.upper) return L('下限必须小于上限', 'Lower must be less than upper')
  return ''
}
function addObjective() {
  const metric = epsoMetrics.find(metric => !objectives.value.some(item => item.metric === metric))
  if (!metric) return
  const objective: Objective = { metric, mode: 'lower_bound', weight: 1 }
  resetObjective(objective); objectives.value.push(objective)
}
const referenceMolfile = ref('')
// The editor's unsent state, passed to the side assistant as form.editor_state (first engine only).
const editorState = ref<Record<string, any> | null>(null)
const previewLoading = ref(false)
const moleculeCounts = ref({ delete: 1000, epso: 100 })
const numMolecules = computed({ get: () => moleculeCounts.value[engine.value], set: value => { moleculeCounts.value[engine.value] = value } })
const moleculeLimit = computed(() => generationCountLimit(engine.value, objectives.value))
const taskName = ref('')
const editSession = ref<EditSession | null>(null)
const linkedEditor = computed(() => Boolean(route.query.edit_session_id))
const submitting = ref(false)
const error = ref('')
const contextRefresh = ref(0)
const restoring = ref(Boolean(route.query.restore_job_id))
const restoreFailed = ref(false)
let active = true
const activeView = ref<'ligand' | 'protein'>(engine.value === 'epso' ? 'protein' : 'ligand')
const deleteEditor = ref<InstanceType<typeof DeleteEditorWorkspace> | null>(null)
const initialDeleteEdit = ref<{ contextId: string; edit: DeleteEditChanges } | null>(null)
const defaultTaskName = `LEADOPT_${new Date().toISOString().slice(0, 19).replace('T', '_').replace(/:/g, '')}`
const hasContextLigand = computed(() => Boolean(store.context?.generation_reference))
const hasReferenceLigand = computed(() => Boolean(hasContextLigand.value || (engine.value === 'epso' && ligandDatasetId.value)))
const ligandLabel = computed(() => {
  if (engine.value === 'epso' && ligandOverrideLabel.value) return ligandOverrideLabel.value
  return hasContextLigand.value ? translate('platform.usingReferenceLigandFromProteinContext') : translate('platform.referenceLigandIsRequired')
})
const canSubmit = computed(() =>
  Boolean(
    !restoring.value && !restoreFailed.value && !nameTooLong(taskName.value) && store.context
    && isProteinContextReady(store.context, engine.value === 'epso' && ligandDatasetId.value ? undefined : engine.value)
    && hasReferenceLigand.value
    && (engine.value !== 'epso' || objectives.value.every(objective => !objectiveProblem(objective)))
    && (engine.value === 'epso' || deleteEditor.value?.getState().canSubmit)
    && Number.isInteger(Number(numMolecules.value))
    && Number(numMolecules.value) > 0
    && Number(numMolecules.value) <= moleculeLimit.value,
  ),
)

function syncDeleteState(next: DeleteEditState) {
  editorState.value = { strategy: next.mode, selected_node_count: Object.values<number>(next.selectedNodes).reduce((sum, count) => sum + count, 0), selected_node_elements: next.selectedNodes, deleted_node_count: next.deletedNodeCount, has_unsaved_edit: next.dirty }
}

async function loadContext(contextId = String(route.query.protein_context_id || ''), ligandId = '') {
  if (!contextId) return
  if (linkedEditor.value && contextId !== editSession.value?.state.assets.protein_context_id) { error.value = L('请返回会话更换 Context。', 'Return to the conversation to change the Context.'); return false }
  try {
    const context = (await getProteinContext(contextId)).data
    if (!active) return false
    store.setContext(context)
    if (!isProteinContextReady(context) || !contextReceptorFile(context)) {
      error.value = translate('platform.structureNotReady')
      return false
    }
    ligandDatasetId.value = ligandId
    ligandOverrideLabel.value = ''
    await nextTick()
    if (!active) return false
    await viewer.value?.loadContext(context)
    if (!active) return false
    if (engine.value === 'epso' && hasReferenceLigand.value && !await refreshReferencePreview()) return false
    return true
  } catch (exception: any) {
    if (!active) return false
    store.clear()
    error.value = displayErrorMessage(exception, translate('platform.failedToLoadProteinContext'))
  }
}

async function selectContext(contextId: string) {
  if (contextId === store.contextId) return
  error.value = ''
  if (!contextId) store.clear()
  else await loadContext(contextId, ligandDatasetId.value)
  await router.replace({ path: '/molopt', query: { ...route.query, protein_context_id: contextId || undefined, engine: engine.value } })
}
watch(() => route.query.protein_context_id, value => {
  const id = String(value || '')
  if (id === store.contextId) return
  if (!id) store.clear()
  else void loadContext(id)
})
async function handleStaleContext(exception: any) {
  const detail = exception?.response?.data?.detail
  if (detail?.error_code !== 'PROTEIN_CONTEXT_STALE') return false
  if (store.contextId === detail.protein_context_id) {
    store.clear()
    contextRefresh.value++
    await router.replace({ query: { ...route.query, protein_context_id: undefined } })
  }
  error.value = L('所选 Protein Context 已失效，请重新选择。其他参数已保留。', 'The selected Protein Context is no longer available. Select another one; other parameters have been kept.')
  return true
}

function createContext() {
  router.push({ path: '/protein-preparation', query: { next: '/molopt', module: engine.value } })
}

async function uploadLigand(file: File) {
  try {
    const response = await uploadBackendDataset({
      name: file.name,
      kind: 'ligand_sdf',
      file,
      fileRole: 'ligand_input',
    })
    ligandDatasetId.value = response.data.id
    ligandOverrideLabel.value = response.data.name
    if (engine.value === 'epso') await refreshReferencePreview()
  } catch (exception: any) {
    error.value = displayErrorMessage(exception, translate('platform.uploadFailed'))
  }
}

async function selectDataset(payload: { id: string | number; name: string }) {
  ligandDatasetId.value = String(payload.id)
  ligandOverrideLabel.value = payload.name
  selectorOpen.value = false
  if (engine.value === 'epso') await refreshReferencePreview()
}

function editContext() {
  router.push({
    path: '/protein-preparation',
    query: {
      next: '/molopt',
      context_id: store.contextId,
    },
  })
}

let referencePreviewRequest = 0
async function refreshReferencePreview() {
  if (!store.contextId || !hasReferenceLigand.value) return false
  const request = ++referencePreviewRequest
  const ligandId = ligandDatasetId.value
  previewLoading.value = true
  error.value = ''
  try {
    let datasetId: string, fileId: string
    if (ligandId) {
      const dataset = (await getBackendDataset(ligandId)).data
      const file = dataset.files.length === 1 ? dataset.files[0] : undefined
      if (!file || !file.original_filename.toLowerCase().endsWith('.sdf')) throw new Error(translate('platform.bindingReferenceUnavailable'))
      datasetId = ligandId
      fileId = file.id
    } else {
      const reference = store.context?.generation_reference
      const preparedReference = store.context?.compatibility?.models.epso?.artifacts?.reference_ligand
      const identity = preparedReference || (reference && !('kind' in reference) ? reference.structure : undefined)
      if (!identity) throw new Error(translate('platform.bindingReferenceUnavailable'))
      datasetId = identity.dataset_id
      fileId = identity.file_id
    }
    const text = await (await downloadBackendDataset(datasetId, fileId)).data.text()
    if (!active || request !== referencePreviewRequest) return false
    referenceMolfile.value = text
    return true
  } catch (exception: any) {
    if (!active || request !== referencePreviewRequest) return false
    referenceMolfile.value = ''
    error.value = displayErrorMessage(exception, translate('platform.failedToPrepareReferenceLigand'))
    return false
  } finally {
    if (active && request === referencePreviewRequest) previewLoading.value = false
  }
}

async function submit() {
  if (submitting.value) return
  if (!pendingSubmission.value && ((engine.value === 'delete' && !advanced.value?.validate()) || !canSubmit.value)) return
  submitting.value = true
  error.value = ''
  try {
    if (pendingSubmission.value) { await sendJob(); return }
    if (linkedEditor.value) {
      if (!editSession.value || editSession.value.status !== 'open' || engine.value !== 'delete' || ligandDatasetId.value || store.contextId !== editSession.value.state.assets.protein_context_id) throw new Error(translate('platform.editorMessages.expired'))
      if (!await deleteEditor.value?.save()) throw new Error(translate('platform.editorMessages.saveFailed'))
      await router.push({ path: '/agent', query: { session_id: editSession.value.session_id } })
      return
    }
    const contextId = store.contextId
    let edit: Partial<DeleteEditChanges> | undefined
    if (engine.value === 'delete') {
      const changes = await deleteEditor.value?.getChanges()
      if (!changes || contextId !== store.contextId || engine.value !== 'delete') return
      edit = changes
    }
    const response = await sendJob({
      job_type: 'property_optimization',
      protein_context_id: contextId,
      ...(engine.value === 'epso' && ligandDatasetId.value ? { ligand_dataset_id: ligandDatasetId.value } : {}),
      params: {
        job_name: taskName.value.trim() || defaultTaskName,
        property_optimization: {
          engine: engine.value,
          ...(engine.value === 'epso' ? { objectives: objectives.value, optimizer: optimizer.value } : { edit, ...sampling.value }),
          num_molecules: Number(numMolecules.value),
        },
      },
    })
    deleteEditor.value?.markSubmitted()
    await assistantPanel.value?.bindToJob(response.data.id)
    await router.push({ path: '/dashboard', query: { job_id: response.data.id } })
  } catch (exception: any) {
    if (!await handleStaleContext(exception)) error.value = displayErrorMessage(exception, translate('platform.submitFailed'))
  } finally {
    submitting.value = false
  }
}

async function initialize() {
  const id = String(route.query.restore_job_id || '')
  if (!id) { engine.value = route.query.engine === 'epso' ? 'epso' : 'delete'; await loadContext(); return }
  store.clear()
  try {
    const job = (await getBackendJob(id)).data
    if (!active) return
    const params = job.params.property_optimization
    const contextId = job.params.protein_context_id
    const edit = params?.edit
    if (job.job_type === 'property_optimization' && params?.engine === 'epso' && contextId) {
      engine.value = 'epso'
      objectives.value = params.objectives
      optimizer.value = params.optimizer
      numMolecules.value = params.num_molecules
      taskName.value = job.params.job_name || ''
      const source = savedEpsoSeed(job.params)
      if (!source || !await loadContext(contextId, source.datasetId)) throw new Error(translate('platform.restoreTaskUnavailable'))
      if (!source.datasetId && (!matchesSavedReference(store.context, job.params.structure_context)
        || source.fileId !== sourceReferenceId(store.context?.generation_reference))) throw new Error(translate('platform.restoreTaskUnavailable'))
      if (job.params.structure_context?.protein_file_id !== contextReceptorFile(store.context)) throw new Error(translate('platform.restoreTaskUnavailable'))
      const inputs = job.tasks.find(task => task.runtime_task === 'epso')?.input_payload
      const affinity = inputs?.affinity_inputs
      if (affinity) {
        const models = store.context?.compatibility?.models
        const receptorEngine = ['ecloudgen', 'surfgen', 'delete'].find(name => ['full', 'limited'].includes(models?.[name]?.status ?? ''))
        const box = store.context?.site.box
        if (!receptorEngine || receptorEngine !== affinity.receptor.engine
          || models?.[receptorEngine]?.artifacts?.cache?.sha256 !== affinity.receptor.manifest_sha256
          || store.context?.input_parameters?.ph !== affinity.ph
          || box?.center.some((value, index) => value !== affinity.box.center[index])
          || box?.size.some((value, index) => value !== affinity.box.size[index])) {
          throw new Error(translate('platform.restoreTaskUnavailable'))
        }
      }
      if (source.datasetId) {
        const ligand = (await getBackendDataset(source.datasetId)).data
        const seed = inputs?.seed_reference?.structure
        if (ligand.files.length !== 1 || ligand.files[0].id !== source.fileId
          || (seed && (seed.dataset_id !== source.datasetId || seed.file_id !== source.fileId || seed.sha256 !== ligand.files[0].sha256))) {
          throw new Error(translate('platform.restoreTaskUnavailable'))
        }
        ligandOverrideLabel.value = ligand.name
      }
      moduleSuggestion.consume(route, assistantContext.value.form, applyAssistantChanges)
      return
    }
    if (job.job_type !== 'property_optimization' || params?.engine !== 'delete' || !contextId
      || !Number.isInteger(params.num_molecules) || params.num_molecules <= 0
      || !['r_group', 'side_chain', 'linker', 'scaffold_hopping', 'custom', 'derivation_site'].includes(edit?.mode)) {
      throw new Error(translate('platform.restoreTaskUnavailable'))
    }
    const ligandId = job.input_dataset_id !== contextId ? job.input_dataset_id || '' : ''
    const ligand = ligandId ? (await getBackendDataset(ligandId)).data : null
    if (!active) return
    engine.value = 'delete'
    initialDeleteEdit.value = { contextId, edit }
    for (const key of Object.keys(sampling.value)) {
      if (!key.endsWith('_threshold') && params[key] != null) sampling.value[key] = params[key]
    }
    taskName.value = job.params.job_name || job.params.name || ''
    numMolecules.value = params.num_molecules
    if (!await loadContext(contextId, ligandId)) throw new Error(error.value)
    if (!active) return
    if (job.params.structure_context?.protein_file_id !== contextReceptorFile(store.context)) {
      throw new Error(translate('platform.restoreTaskUnavailable'))
    }
    ligandOverrideLabel.value = ligand?.name || ''
    moduleSuggestion.consume(route, assistantContext.value.form, applyAssistantChanges)
  } catch (exception: any) {
    restoreFailed.value = true
    error.value = displayErrorMessage(exception, translate('platform.restoreTaskUnavailable'))
  } finally {
    restoring.value = false
  }
}

async function cancelEdit() {
  if (!editSession.value) return
  if (deleteEditor.value) await deleteEditor.value.discard()
  else await cancelWorkflowEditor(editSession.value.id)
  await router.push({ path: '/agent', query: { session_id: editSession.value.session_id } })
}
watch(() => route.query.engine, value => {
  if (!linkedEditor.value) engine.value = value === 'epso' ? 'epso' : 'delete'
})
watch(engine, value => {
  referencePreviewRequest++
  previewLoading.value = false
  error.value = ''
  activeView.value = value === 'epso' ? 'protein' : 'ligand'
  if (value === 'delete') deleteEditorOpened.value = true
  if (!restoring.value && !linkedEditor.value) void router.replace({ query: { ...route.query, engine: value } })
  if (value === 'epso' && store.context) void refreshReferencePreview()
})
onMounted(async () => {
  if (!linkedEditor.value) {
    await initialize()
    if (!restoreFailed.value && ['delete', 'epso'].includes(String(route.query.engine))) engine.value = route.query.engine as 'delete' | 'epso'
    return
  }
  try {
    editSession.value = (await getWorkflowEditor(String(route.query.edit_session_id))).data
    if (editSession.value.kind !== 'delete' || editSession.value.status !== 'open') throw new Error(translate('platform.editorMessages.closed'))
    engine.value = 'delete'
    await loadContext(editSession.value.state.assets.protein_context_id)
  } catch (exception: any) { error.value = displayErrorMessage(exception, translate('platform.editorMessages.loadFailed')); restoreFailed.value = true }
})
onBeforeUnmount(() => { active = false })
</script>

<style scoped>
.objective-section {
  @apply rounded-lg border border-slate-200 bg-white p-3;
}

.objective-card {
  @apply overflow-hidden rounded-lg border border-slate-200 bg-white focus-within:border-blue-300;
}

.objective-field {
  @apply flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-slate-500;
}

.objective-fields {
  display: grid;
  flex: 1;
  min-width: 0;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 130px), 1fr));
  align-items: end;
  gap: 8px;
}

.objective-field select,
.objective-field :deep(input) {
  @apply h-9 w-full min-w-0 rounded-md border border-slate-200 bg-white px-3 text-sm font-normal tabular-nums text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500;
}
</style>

<route lang="yaml">
meta:
  layout: blank
</route>
