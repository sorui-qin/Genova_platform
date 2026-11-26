<template>
  <AppFrame :task="store.context && !route.query.restore_job_id ? { name: taskName || defaultTaskName, context: store.context.name, draft: !route.query.restore_job_id } : undefined">
    <div class="module-workbench flex flex-col">
      <PageHeader :title="$t('platform.deNovoGeneration')" :help="{path: '/help', query: {article: 'molecule-generation'}}" :help-label="$t('platform.operationGuide')"><Button v-if="!panelOpen" variant="outline" @click="panelOpen = true">{{ $t('platform.openPanel') }}</Button></PageHeader>
      <p v-if="route.query.restore_job_id" role="status" class="shrink-0 border-b bg-accent px-6 py-2 text-xs text-primary">{{ $t(restoring ? 'platform.loading' : restoreFailed ? 'platform.restoreTaskUnavailable' : 'platform.restoredTaskHint') }}</p>

      <WorkspaceLayout v-model:open="panelOpen" :title="$t('platform.parameters')" resizable>
        <template #panel-header><WorkspacePanelTabs v-model="auxiliaryTab" :label="L('操作面板', 'Controls')" :tabs="[{ value: 'parameters', label: $t('platform.parameters') }, ...(true ? [{ value: 'assistant', label: L('助手', 'Assistant') }] : [])]" @update:model-value="value => { if (value === 'assistant') assistantOpened = true }" /></template>
        <template #auxiliary>
        <ModuleAssistantPanel v-if="assistantOpened" v-show="auxiliaryTab === 'assistant'" ref="assistantPanel" module="molecule_generation" :context="assistantContext" :apply="applyAssistant" />
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

            <div class="space-y-2">
              <Label for="generation-engine">{{ $t('platform.engine') }}</Label>
              <select id="generation-engine" v-model="engine" class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm">
                <option value="surfgen">SurfGen</option>
                <option value="ecloudgen">ECloudGen</option>
              </select>
            </div>
            <div class="space-y-2">
              <Label>{{ $t(engine === 'ecloudgen' ? 'platform.ecloudgenTargetCount' : 'platform.maximumValidMoleculesToReturn') }}</Label>
              <Input v-model.number="numMolecules" type="number" min="1" max="50000" step="1" />
              <p class="text-xs text-slate-500">{{ $t('platform.numberInput.range', { range: $t('platform.numberInput.between', { min: 1, max: 50000 }) }) }}</p>
              <p v-if="platformSeeds" class="text-xs text-slate-500">{{ $t('platform.generationPlatformSeeds') }}</p>
            </div>
            <div class="space-y-2">
              <Label>{{ $t('platform.taskName') }}</Label>
              <Input v-model="taskName" :placeholder="defaultTaskName" :maxlength="NAME_MAX_LENGTH" />
              <p class="text-xs" :class="nameTooLong(taskName) ? 'text-rose-700' : 'text-slate-500'">{{ nameLengthHint(taskName) }}</p>
            </div>
            <GenerationAdvanced ref="advanced" v-model="sampling[engine]" :engine="engine" :planning="samplingLoading" :platform-seeds="platformSeeds" :cloud-estimate="cloudEstimate" />
            <p v-if="engine === 'ecloudgen' && samplingError" class="text-sm text-rose-700">{{ samplingError }}</p>
            <p v-if="pendingSubmission && !submitting" role="status" class="text-sm text-amber-700">{{ L('暂未确认任务是否创建，请重试原提交；当前参数改动仍保留。', 'Task creation is not confirmed. Retry the original submission; your edits are preserved.') }}</p>
            <p v-else-if="confirmedJob && !submitting" role="status" class="text-sm text-green-700">{{ L('原任务已确认，可明确发起新任务。', 'Original task confirmed. You may submit a new task.') }} <RouterLink :to="{path:'/dashboard',query:{job_id:confirmedJob}}" class="underline">{{ L('查看任务', 'View task') }}</RouterLink></p>
            <Button class="w-full" :disabled="submitting || (!pendingSubmission && !canSubmit)" @click="submit">
              {{ submitting ? $t('platform.submitting') : pendingSubmission ? L('重试原提交', 'Retry original submission') : $t('platform.submitTask') }}
            </Button>
            <p v-if="error" class="text-sm text-rose-700">{{ error }}</p>
          </div>
        </div>

        </template>
        <div class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          <div class="flex min-h-12 shrink-0 flex-wrap items-center gap-3 border-b bg-card px-4 py-2">
            <h2 class="shrink-0 text-sm font-semibold">{{ $t('platform.structureWorkspace') }}</h2>
          </div>
          <div class="relative isolate min-h-0 flex-1">
          <protein3d_molstar
            ref="viewer"
            compact
            :if-show-box="Boolean(store.context)"
            :if-click-event="false"
            :wait-molstar-init="true"
            :l1="(store.context ? contextBox(store.context).size : [20,20,20])[0] || 20"
            :l2="(store.context ? contextBox(store.context).size : [20,20,20])[1] || 20"
            :l3="(store.context ? contextBox(store.context).size : [20,20,20])[2] || 20"
            class="h-full min-h-0"
          />
          <FeedbackState v-if="!store.context" class="absolute inset-0 z-[60] bg-white" :title="$t('platform.noProteinStructureData')" />
          </div>
        </div>
      </WorkspaceLayout>
    </div>

  </AppFrame>
</template>

<script setup lang="ts">
import '@/assets/module-workbench.css'
import WorkspacePanelTabs from '@/components/workbench/WorkspacePanelTabs.vue'
import FeedbackState from '@/components/workbench/FeedbackState.vue'

import i18n, { translate } from '@/i18n'
import { NAME_MAX_LENGTH, nameLengthHint, nameTooLong } from '@/utils/nameLength'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isProteinContextReady, contextBox, contextReceptorFile, matchesSavedReference } from '@/types/proteinContext'
import { getProteinContext } from '@/api/proteinContext'
import { getBackendJob, getEcloudSamplingPlan } from '@/api/genovaBackend'
import PageHeader from '@/components/workbench/PageHeader.vue'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import { useWorkspaceState } from '@/composables/useWorkspace'
import AppFrame from '@/components/Layout/appFrame.vue'
import protein3d_molstar from '@/components/molecule/protein3d_molstar.vue'
import ProteinContextSummary from '@/components/protein-preparation/ProteinContextSummary.vue'
import ProteinContextSelector from '@/components/protein-preparation/ProteinContextSelector.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { effectiveGenerationSampling, SURFGEN_ROUND_TARGET } from '@/utils/generationForm'
import GenerationAdvanced from '@/components/common/GenerationAdvanced.vue'
import ModuleAssistantPanel from '@/pages/agent/components/ModuleAssistantPanel.vue'
import { useModuleSuggestion } from '@/composables/useModuleSuggestion'
import type { ModuleContext, ModuleSuggestion } from '@/api/moduleAssistant'
import { useProteinContextStore } from '@/stores/proteinContext'
import { displayErrorMessage } from '@/utils/requestError'

import { useJobSubmission } from '@/composables/useJobSubmission'
const { pendingSubmission, confirmedJob, sendJob } = useJobSubmission('molgen')
const route = useRoute()
const { panelOpen } = useWorkspaceState('molgen-workspace', () => String(route.query.restore_job_id || route.query.edit_session_id || 'draft'), { panelOpen: true })
const router = useRouter()
const store = useProteinContextStore()
store.clear()
const viewer = ref<InstanceType<typeof protein3d_molstar> | null>(null)
const engine = ref<'surfgen' | 'ecloudgen'>('surfgen')
const L = (zh: string, en: string) => i18n.global.locale.value.startsWith('zh') ? zh : en
const auxiliaryTab = ref('parameters'), assistantOpened = ref(false)
const assistantPanel = ref<InstanceType<typeof ModuleAssistantPanel>>()
const moduleSuggestion = useModuleSuggestion('molecule_generation')
let applyingSuggestion = false
const numMolecules = ref(1000)
const platformSeeds = computed(() => engine.value === 'surfgen' && Number(numMolecules.value) > SURFGEN_ROUND_TARGET)
const cloudEstimate = ref<number>()
const advanced = ref<InstanceType<typeof GenerationAdvanced> | null>(null)
const sampling = ref<Record<'surfgen' | 'ecloudgen', Record<string, number | string>>>({
  surfgen: { beam_size: 500, max_steps: 50, element_threshold: 0.3, bond_threshold: 0.4, seed: 2020 },
  ecloudgen: { noise: 0.1, inv_temp: 2, budget_multiplier: 3, seed: 42, num_clouds: '', decodes_per_cloud: 100 },
})
const samplingLoading = ref(false)
const samplingError = ref('')
let samplingRequest = 0
const taskName = ref('')
const submitting = ref(false)
const error = ref('')
const contextRefresh = ref(0)
const restoring = ref(Boolean(route.query.restore_job_id))
const restoreFailed = ref(false)
let active = true
const timestamp = new Date().toISOString().slice(0, 19).replace('T', '_').replace(/:/g, '')
const defaultTaskName = computed(() => `${engine.value.toUpperCase()}_${timestamp}`)
const canSubmit = computed(() =>
  Boolean(
    !restoring.value && !restoreFailed.value && !nameTooLong(taskName.value) && isProteinContextReady(store.context, engine.value)
    && Number.isInteger(Number(numMolecules.value))
    && Number(numMolecules.value) > 0
    && Number(numMolecules.value) <= 50000
    && (engine.value !== 'ecloudgen' || (!samplingLoading.value && !samplingError.value)),
  ),
)

async function refreshSamplingPlan() {
  const request = ++samplingRequest
  samplingError.value = ''
  if (engine.value !== 'ecloudgen' || sampling.value.ecloudgen.num_clouds !== '') {
    samplingLoading.value = false
    return
  }
  if (!Number.isInteger(Number(numMolecules.value)) || Number(numMolecules.value) <= 0 || Number(numMolecules.value) > 50000) {
    samplingLoading.value = false
    return
  }
  samplingLoading.value = true
  try {
    const { data } = await getEcloudSamplingPlan(Number(numMolecules.value), sampling.value.ecloudgen)
    if (!active || request !== samplingRequest) return
    cloudEstimate.value = data.num_clouds
  } catch (exception: any) {
    if (active && request === samplingRequest) samplingError.value = displayErrorMessage(exception, translate('platform.submitFailed'))
  } finally {
    if (request === samplingRequest) samplingLoading.value = false
  }
}

watch(() => [engine.value, numMolecules.value, sampling.value.ecloudgen.num_clouds,
  sampling.value.ecloudgen.decodes_per_cloud, sampling.value.ecloudgen.noise, sampling.value.ecloudgen.inv_temp],
  () => { if (!restoring.value && !applyingSuggestion) void refreshSamplingPlan() })

const assistantContext = computed<ModuleContext>(() => ({ engine: engine.value, protein_context_id: store.contextId || undefined,
  form: { engine: engine.value, ...effectiveGenerationSampling(engine.value, Number(numMolecules.value), sampling.value[engine.value]), [engine.value === 'ecloudgen' ? 'target_num_molecules' : 'num_molecules']: Number(numMolecules.value) } }))
function applyAssistantChanges(changes: Record<string, any>) {
  applyingSuggestion = true
  try {
    if ('target_num_molecules' in changes) numMolecules.value = changes.target_num_molecules
    if ('num_molecules' in changes) numMolecules.value = changes.num_molecules
    for (const [key, value] of Object.entries(changes)) if (key in sampling.value[engine.value]) sampling.value[engine.value][key] = value
  } finally { applyingSuggestion = false }
  void refreshSamplingPlan()
}
function applyAssistant(suggestion: ModuleSuggestion) {
  if (restoring.value || submitting.value || samplingLoading.value) throw new Error(L('请等待当前操作完成。', 'Wait for the current operation.'))
  applyAssistantChanges(Object.fromEntries(suggestion.changes.map(change => [change.field, change.after])))
}

async function loadContext(contextId = String(route.query.protein_context_id || '')) {
  if (!contextId) return false
  try {
    const context = (await getProteinContext(contextId)).data
    if (!active) return false
    store.setContext(context)
    if (!isProteinContextReady(context) || !contextReceptorFile(context)) {
      error.value = translate('platform.structureNotReady')
      return false
    }
    await nextTick()
    if (!active) return false
    await viewer.value?.loadContext(context)
    if (!active) return false
    viewer.value?.add_shape(
      contextBox(context).center[0],
      contextBox(context).center[1],
      contextBox(context).center[2],
      contextBox(context).size[0],
      contextBox(context).size[1],
      contextBox(context).size[2],
      false,
    )
    return true
  } catch (exception: any) {
    if (!active) return false
    store.clear()
    error.value = displayErrorMessage(exception, translate('platform.failedToLoadProteinContext'))
    return false
  }
}

async function selectContext(contextId: string) {
  if (contextId === store.contextId) return
  error.value = ''
  if (!contextId) store.clear()
  else await loadContext(contextId)
  await router.replace({ path: '/molgen', query: { ...route.query, protein_context_id: contextId || undefined, engine: engine.value } })
}
watch(() => route.query.engine, value => {
  if ((value === 'surfgen' || value === 'ecloudgen') && value !== engine.value) engine.value = value
})
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
  router.push({ path: '/protein-preparation', query: { next: '/molgen', module: engine.value } })
}

function editContext() {
  router.push({
    path: '/protein-preparation',
    query: {
      next: '/molgen',
      module: engine.value,
      context_id: store.contextId,
    },
  })
}

async function submit() {
  if (submitting.value) return
  if (!pendingSubmission.value && (!canSubmit.value || !advanced.value?.validate())) return
  submitting.value = true
  error.value = ''
  try {
    if (pendingSubmission.value) { await sendJob(); return }
    const response = await sendJob({
      job_type: 'molecule_generation',
      protein_context_id: store.contextId,
      params: {
        job_name: taskName.value.trim() || defaultTaskName.value,
        molecule_generation: {
          engine: engine.value,
          ...effectiveGenerationSampling(engine.value, Number(numMolecules.value), sampling.value[engine.value]),
          ...(engine.value === 'ecloudgen'
            ? { target_num_molecules: Number(numMolecules.value) }
            : { num_molecules: Number(numMolecules.value) }),
        },
      },
    })
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
  if (!id) { engine.value = route.query.engine === 'ecloudgen' ? 'ecloudgen' : 'surfgen'; await Promise.all([loadContext(), refreshSamplingPlan()]); return }
  store.clear()
  try {
    const job = (await getBackendJob(id)).data
    if (!active) return
    const params = job.params.molecule_generation
    const task = job.tasks.find(task => task.task_code === 'molecule_generation' || task.task_code === 'surfgen_inference')
    const contextId = job.params.protein_context_id
    if (params?.engine === 'ecloudgen' && params.target_num_molecules == null) {
      error.value = translate('platform.restoreSamplingUnavailable')
      throw new Error(error.value)
    }
    const count = params?.engine === 'ecloudgen' ? params.target_num_molecules : (params?.num_molecules ?? task?.input_payload.num_molecules)
    if (job.job_type !== 'molecule_generation' || !['surfgen', 'ecloudgen'].includes(params?.engine) || !contextId || !Number.isInteger(count) || count <= 0) {
      throw new Error(translate('platform.restoreTaskUnavailable'))
    }
    taskName.value = job.params.job_name || job.params.name || ''
    numMolecules.value = count
    if (!await loadContext(contextId)) throw new Error(error.value)
    if (!active) return
    engine.value = params.engine
    for (const key of Object.keys(sampling.value[engine.value])) {
      if (!key.endsWith('_threshold') && params[key] != null) sampling.value[engine.value][key] = params[key]
    }
    if (engine.value === 'ecloudgen') {
      if (params.num_clouds == null) sampling.value.ecloudgen.num_clouds = ''
      await refreshSamplingPlan()
    }
    const snapshot = job.params.structure_context
    if (snapshot?.protein_file_id !== contextReceptorFile(store.context)
      || (task?.input_payload.reference_ligand && task.input_payload.reference_ligand !== snapshot?.reference_ligand_path)
      || (engine.value === 'ecloudgen' && !matchesSavedReference(store.context, snapshot))) {
      throw new Error(translate('platform.restoreTaskUnavailable'))
    }
    moduleSuggestion.consume(route, assistantContext.value.form, applyAssistantChanges)
  } catch (exception: any) {
    restoreFailed.value = true
    error.value = displayErrorMessage(exception, translate('platform.restoreTaskUnavailable'))
  } finally {
    restoring.value = false
  }
}

onMounted(initialize)
onBeforeUnmount(() => { active = false })
</script>

<route lang="yaml">
meta:
  layout: blank
</route>
