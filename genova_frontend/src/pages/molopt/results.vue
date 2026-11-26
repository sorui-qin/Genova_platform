<template>
  <AppFrame>
    <WorkspaceLayout v-model:open="detailOpen" :title="$t('platform.resultDetails')" class="module-workbench workbench-results" resizable :initial-left="70">
    <div class="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHeader :title="jobName || $t('platform.leadOptimizationResults')" :help="{ path: '/help', query: { article: 'exports' } }" :help-label="$t('platform.operationGuide')"><Button variant="outline" @click="auxiliaryTab = 'assistant'; assistantOpened = true; detailOpen = true">{{ L('助手', 'Assistant') }}</Button><template #breadcrumb>
        <nav class="flex items-center space-x-1.5 text-xs">
          <router-link to="/molopt" class="font-medium text-blue-600 hover:underline">{{ $t('platform.leadOptimization') }}</router-link>
          <ChevronRight class="h-3 w-3 text-slate-400" />
          <RouterLink to="/results" class="font-medium text-primary hover:underline">{{ $t('platform.allTasksResults') }}</RouterLink>
        </nav>
      </template></PageHeader>

      <div class="workbench-toolbar justify-between">
        <div class="flex items-center gap-2 text-xs">
          <CheckCircle2 class="h-3.5 w-3.5 text-emerald-600" />
          <span class="font-semibold text-slate-900">{{ total }}</span>
          <span class="text-slate-500">{{ $t('platform.molecules') }}</span>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button v-if="canPostprocess" size="sm" variant="outline" as-child><router-link :to="{ path: '/postprocessing', query: { source_job_id: jobId } }">{{ $t('platform.openInPostprocessing') }}</router-link></Button>
          <Button size="sm" :disabled="loading || !hasCsv" @click="downloadArtifact('output_csv', 'results.csv')">
            {{ $t('platform.downloadCsv') }}
          </Button>
          <Button v-if="!isEpso" variant="outline" size="sm" :disabled="loading || !hasSdf" @click="downloadArtifact('generated_sdf', 'generated.sdf')">
            {{ $t('platform.downloadSdf') }}
          </Button>
          <Button v-if="isEpso" variant="outline" size="sm" :disabled="!hasTrajectory" @click="downloadArtifact('trajectory_csv', 'trajectory.csv')">{{ $t('platform.epsoTrajectory') }}</Button>
          <Button v-if="isEpso" variant="outline" size="sm" :disabled="!hasMetadata" @click="downloadArtifact('metadata_json', 'metadata.json')">{{ $t('platform.epsoMetadata') }}</Button>
        </div>
      </div>

      <div class="workbench-result-body">
        <GuestRecoveryBanner :job-id="jobId" />

        <p v-if="quantityWarning" role="status" class="border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{{ quantityWarning }}</p>
        <p v-else-if="deliverySummary" role="status" class="px-3 py-2 text-sm text-slate-700">{{ deliverySummary }}</p>
        <PreparationErrorDetails v-if="preparationError" :error="preparationError" class="border border-red-200 bg-red-50 px-3 py-2" />
        <div v-if="errorMessage" class="border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {{ errorMessage }}
        </div>
        <FeedbackState v-else-if="loading" class="flex-1" kind="loading" :title="$t('platform.loading')" />
        <FeedbackState v-else-if="rows.length === 0" class="flex-1" :title="$t('platform.noLeadOptimizationResultsToDisplay')" />
        <div v-else class="workbench-table-area">
          <p v-if="!isEpso" class="text-xs text-slate-600">{{ $t('platform.leadEditLegend') }}</p>
          <template v-else>
            <p class="text-xs text-slate-600">{{ $t('platform.epsoMetricHint') }} {{ $t('platform.epsoResultHint') }}</p>
            <p v-if="metricColumns.includes('gnina_affinity')" class="text-xs text-slate-600">{{ $t('platform.epsoAffinityResultHelp') }}</p>
            <p v-if="noNewMolecules" class="text-sm text-amber-700">{{ $t('platform.epsoNoNewMolecules') }}</p>
            <p v-if="noImprovement" class="text-sm text-amber-700">{{ $t('platform.epsoNoImprovement') }}</p>
          </template>
          <div class="workbench-table-scroll">
            <table class="min-w-full text-sm">
              <thead class="bg-slate-100 text-slate-600">
                <tr>
                  <th class="w-10 px-2 py-2 text-left font-semibold">#</th>
                  <th class="w-28 px-2 py-2 text-left font-semibold">{{ $t('platform.structure') }}</th>
                  <th class="px-2 py-2 text-left font-semibold">SMILES</th>
                  <template v-if="isEpso"><th class="px-2 py-2">Fitness</th><th class="px-2 py-2">{{ $t('platform.epsoGeneration') }}</th><th v-for="metric in metricColumns" :key="metric" class="px-2 py-2">{{ $t('platform.epsoMetric_' + metric) }}</th></template>
                  <th v-else class="px-2 py-2 text-left font-semibold">{{ $t('platform.3dStructure') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, idx) in pagedRows" :key="row.id" class="cursor-pointer border-t border-slate-100 hover:bg-slate-50" :class="{ 'bg-accent': detailOpen && selectedRow?.id === row.id }" tabindex="0" @click="selectedRow = row; auxiliaryTab = 'details'; detailOpen = true" @keydown.enter="selectedRow = row; auxiliaryTab = 'details'; detailOpen = true">
                  <td class="px-2 py-2 text-slate-500">{{ (currentPage - 1) * pageSize + idx + 1 }}</td>
                  <td class="px-2 py-1">
                    <MoleculeViewer :smiles="row.edit_preview?.molfile || row.smiles" width="180px" height="130px" :highlight-atom-colors="comparisonColors(row.edit_preview)" />
                    <p v-if="row.edit_preview" class="text-xs text-slate-500">{{ $t('platform.ppCandidateAtoms', { retained: row.edit_preview.retained_atom_indices.length, changed: row.edit_preview.changed_atom_indices.length }) }}</p>
                    <p v-else-if="!isEpso" class="text-xs text-slate-500">{{ $t('platform.ppEditUnavailable') }}</p>
                  </td>
                  <td class="max-w-[640px] truncate px-2 py-2 font-mono" :title="row.smiles">{{ row.smiles }}</td>
                  <template v-if="isEpso"><td class="px-2 py-2">{{ row.extra.fitness?.toFixed(4) }}</td><td class="px-2 py-2">{{ row.extra.generation }}</td><td v-for="metric in metricColumns" :key="metric" class="px-2 py-2">{{ row.extra.metrics?.[metric]?.toFixed(3) ?? '—' }}</td></template>
                  <td v-else class="px-2 py-2"><Button size="sm" variant="outline" :disabled="!hasSdf" @click="selectedRow = row; showViewer = true">{{ $t('platform.3dStructure') }}</Button></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="workbench-pagination">
            <div class="flex items-center gap-2 text-slate-600">
              {{ $t('platform.perPage') }}
              <select v-model.number="pageSize" class="h-7 rounded border border-slate-300 px-1">
                <option :value="20">20</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
              </select>
            </div>
            <div class="flex items-center gap-2">
              <Button variant="outline" size="sm" :disabled="currentPage <= 1" @click="currentPage -= 1">{{ $t('platform.previous') }}</Button>
              <span class="text-slate-600">{{ currentPage }} / {{ totalPages }}</span>
              <Button variant="outline" size="sm" :disabled="currentPage >= totalPages" @click="currentPage += 1">{{ $t('platform.next') }}</Button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <template #panel-header><WorkspacePanelTabs v-model="auxiliaryTab" :label="$t('platform.resultDetails')" :tabs="[{ value: 'details', label: L('详情', 'Details') }, { value: 'assistant', label: L('助手', 'Assistant') }]" @update:model-value="value => { if (value === 'assistant') assistantOpened = true }" /></template>
    <template #auxiliary><ModuleAssistantPanel v-if="assistantOpened && assistantJob?.id === jobId" v-show="auxiliaryTab === 'assistant'" :key="jobId" module="property_optimization" :job-id="jobId" :context="assistantContext" :apply="applyAssistant" /><MoleculeDetails v-show="auxiliaryTab === 'details'" :row="selectedRow" :has3d="hasSdf" @view3d="showViewer = true" /></template>
    </WorkspaceLayout>
    <Dialog v-model:open="showViewer"><DialogContent class="max-w-5xl"><DialogHeader><DialogTitle>{{ $t('platform.3dStructure') }}</DialogTitle><DialogDescription class="truncate">{{ selectedRow?.smiles }}</DialogDescription></DialogHeader>
      <div ref="poseContainer" class="h-[70vh]" />
    </DialogContent></Dialog>
    <div class="hidden"><Teleport :to="poseContainer || 'body'" :disabled="!poseContainer">
      <BindingPoseViewer v-if="selectedRow" :visible="showViewer" :job-id="jobId" :result-id="selectedRow.id" :smiles="selectedRow.smiles" />
    </Teleport></div>
  </AppFrame>
</template>

<script setup lang="ts">
import { generationDeliverySummary, generationQuantityWarning } from '@/utils/taskPresentation'
import '@/assets/module-workbench.css'
import WorkspacePanelTabs from '@/components/workbench/WorkspacePanelTabs.vue'
import FeedbackState from '@/components/workbench/FeedbackState.vue'

import ModuleAssistantPanel from '@/pages/agent/components/ModuleAssistantPanel.vue'
import { useModuleSuggestion } from '@/composables/useModuleSuggestion'
import type { ModuleContext, ModuleSuggestion } from '@/api/moduleAssistant'
import type { BackendJobOut } from '@/api/genovaBackend'
import { useRouter } from 'vue-router'

import i18n, { translate } from '@/i18n'
import PreparationErrorDetails from '@/components/protein-preparation/PreparationErrorDetails.vue'
import { savedEpsoSeed, type PreparationErrorInfo } from '@/types/proteinContext'

import { defineAsyncComponent, computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clearMoleculeRenderer } from '@/utils/moleculeRenderer'
import { useRoute } from 'vue-router'
import { CheckCircle2, ChevronRight } from 'lucide-vue-next'

import { downloadBackendJobArtifact, getBackendJob, listBackendJobResults } from '@/api/genovaBackend'
import PageHeader from '@/components/workbench/PageHeader.vue'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import MoleculeDetails from '@/components/workbench/MoleculeDetails.vue'
import { useWorkspaceState } from '@/composables/useWorkspace'
import AppFrame from '@/components/Layout/appFrame.vue'
import GuestRecoveryBanner from '@/components/auth/GuestRecoveryBanner.vue'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
const BindingPoseViewer = defineAsyncComponent(() => import('@/components/molecule/BindingPoseViewer.vue'))
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast/use-toast'
import { displayErrorMessage } from '@/utils/requestError'

const route = useRoute()
const jobId = computed(() => {
  const value = route.query.job_id
  return Array.isArray(value) ? (value[0] || '') : (value || '')
})

const showViewer = ref(false)
const { selectedRow, detailOpen, currentPage, pageSize } = useWorkspaceState('molopt-results', () => jobId.value, { selectedRow: null as {id: string; smiles: string} | null, detailOpen: false, currentPage: 1, pageSize: 20 })
const poseContainer = ref<HTMLElement | null>(null)
const assistantJob = ref<BackendJobOut | null>(null)
const auxiliaryTab = ref('details'), assistantOpened = ref(false)
const L = (zh: string, en: string) => i18n.global.locale.value.startsWith('zh') ? zh : en
const assistantRouter = useRouter()
const moduleSuggestion = useModuleSuggestion('property_optimization')
const assistantContext = computed<ModuleContext>(() => ({
  engine: assistantJob.value?.params.property_optimization?.engine || 'delete',
  protein_context_id: assistantJob.value?.params.protein_context_id || undefined,
  ligand_dataset_id: assistantJob.value && savedEpsoSeed(assistantJob.value.params)?.datasetId || undefined,
  form: assistantJob.value?.params.property_optimization || {},
  selected_ids: selectedRow.value?.id ? [selectedRow.value.id] : [],
}))
async function applyAssistant(suggestion: ModuleSuggestion) { await moduleSuggestion.openDraft(assistantRouter, jobId.value, suggestion) }
const jobName = ref('')
const loading = ref(false)
const errorMessage = ref('')
const preparationError = ref<PreparationErrorInfo>()
const rows = ref<Array<{ id: string; smiles: string; edit_preview: any; extra: Record<string, any> }>>([])
const isEpso = ref(false)
const hasTrajectory = ref(false)
const hasMetadata = ref(false)
const quantityWarning = ref('')
const deliverySummary = ref('')
const noNewMolecules = ref(false)
const noImprovement = ref(false)
const metricColumns = computed(() => Object.keys(rows.value[0]?.extra.metrics || {}))
const hasCsv = ref(false)
const hasSdf = ref(false)
const canPostprocess = ref(false)
const total = ref(0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const pagedRows = computed(() => rows.value)
let controller: AbortController | undefined
let revision = 0
let metadata: Awaited<ReturnType<typeof getBackendJob>> | undefined

function comparisonColors(preview: any): Record<number, [number, number, number]> {
  const colors: Record<number, [number, number, number]> = {}
  for (const index of preview?.retained_atom_indices || []) colors[index] = [0.3, 0.8, 0.5]
  for (const index of preview?.changed_atom_indices || []) colors[index] = [0.4, 0.65, 1]
  return colors
}

function filenameFromDisposition(value: string | undefined): string | null {
  if (!value) return null
  const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(value)
  const raw = match?.[1] || match?.[2]
  return raw ? decodeURIComponent(raw) : null
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function loadResults() {
  if (!jobId.value) {
    errorMessage.value = translate('platform.missingJobIdInRouteQuery')
    return
  }
  loading.value = true
  const current = ++revision
  controller?.abort(); controller = new AbortController()
  canPostprocess.value = false
  errorMessage.value = ''
  try {
    const [jobResponse, resultsResponse] = await Promise.all([
      metadata && metadata.data.id === jobId.value && metadata.data.status === 'succeeded' ? Promise.resolve(metadata) : getBackendJob(jobId.value, { summary: true, signal: controller.signal }),
      listBackendJobResults(jobId.value, { limit: pageSize.value, offset: (currentPage.value - 1) * pageSize.value, signal: controller.signal }),
    ])
    if (current !== revision) return
    metadata = jobResponse
    total.value = Number(resultsResponse.headers['x-total-count'] || 0)
    const job = jobResponse.data
    assistantJob.value = job
    jobName.value = String(job.params?.job_name || `${job.job_type}_${job.id.slice(0, 8)}`)
    const task = (job.tasks || []).find((item) => item.task_code === 'property_optimization')
    preparationError.value = task?.output_payload?.error_info
    isEpso.value = job.params?.property_optimization?.engine === 'epso'
    hasTrajectory.value = Boolean(task?.output_payload?.trajectory_csv)
    hasMetadata.value = Boolean(task?.output_payload?.metadata_json)
    quantityWarning.value = generationQuantityWarning(task?.output_payload || {})
    deliverySummary.value = generationDeliverySummary(task?.output_payload || {})
    noNewMolecules.value = Boolean(task?.output_payload?.no_new_molecules)
    noImprovement.value = Boolean(task?.output_payload?.no_fitness_improvement)
    hasCsv.value = Boolean(task?.output_payload?.output_csv)
    hasSdf.value = Boolean(task?.output_payload?.generated_sdf)
    canPostprocess.value = job.status === 'succeeded' && task?.status === 'succeeded' && (isEpso.value ? hasCsv.value : hasSdf.value)
    rows.value = (resultsResponse.data || []).map((item) => ({
      id: item.id,
      smiles: item.smiles || item.smiles_canonical,
      edit_preview: item.extra.edit_preview,
      extra: item.extra,
    }))
  } catch (error: any) {
    if (current !== revision || controller?.signal.aborted) return
    errorMessage.value = displayErrorMessage(error, translate('platform.failedToLoadResults'))
  } finally {
    if (current === revision) loading.value = false
  }
}

async function downloadArtifact(key: string, fallbackName: string) {
  if (!jobId.value) return
  try {
    const response = await downloadBackendJobArtifact(jobId.value, {
      task_code: 'property_optimization',
      key,
    })
    downloadBlob(
      response.data,
      filenameFromDisposition(String(response.headers?.['content-disposition'] || '')) || fallbackName,
    )
  } catch (error: any) {
    toast({
      variant: 'destructive',
      title: translate('platform.downloadFailed'),
      description: displayErrorMessage(error, translate('platform.downloadFailed')),
      duration: 5000,
    })
  }
}

watch(jobId, () => { metadata = undefined; showViewer.value = false; rows.value = []; total.value = 0 })
watch([jobId, pageSize], (next, previous) => { if (next[0] === previous[0]) currentPage.value = 1 })
watch([jobId, pageSize, currentPage], () => { void loadResults() })
onBeforeUnmount(() => { revision++; controller?.abort(); clearMoleculeRenderer() })

onMounted(loadResults)
</script>

<route lang="yaml">
meta:
  layout: blank
</route>
