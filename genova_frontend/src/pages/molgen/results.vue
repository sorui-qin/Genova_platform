<template>
  <AppFrame>
    <WorkspaceLayout v-model:open="detailOpen" :title="$t('platform.resultDetails')" class="module-workbench workbench-results" resizable :initial-left="70">
    <div class="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHeader :title="jobName || $t('platform.generationResults')" :help="{ path: '/help', query: { article: 'exports' } }" :help-label="$t('platform.operationGuide')"><Button variant="outline" @click="auxiliaryTab = 'assistant'; assistantOpened = true; detailOpen = true">{{ L('助手', 'Assistant') }}</Button><template #breadcrumb>
          <nav class="flex items-center space-x-1.5 text-xs">
            <router-link to="/molgen" class="font-medium text-blue-600 transition-colors hover:text-blue-700 hover:underline">
              {{ $t('platform.deNovoGeneration') }}
            </router-link>
            <ChevronRight class="h-3 w-3 text-slate-400" />
            <router-link
              to="/results"
              class="font-medium text-blue-600 transition-colors hover:text-blue-700 hover:underline"
            >
              {{ $t('platform.results') }}
            </router-link>
            <ChevronRight class="h-3 w-3 text-slate-400" />
            <span class="max-w-44 truncate font-medium text-slate-700" :title="jobName">{{ jobName }}</span>
          </nav>
      </template></PageHeader>

      <div class="workbench-toolbar justify-between">
        <div class="flex flex-wrap items-center gap-1 text-xs">
          <div class="flex items-center gap-2 px-3 py-2">
            <CheckCircle2 class="h-3.5 w-3.5 shrink-0 text-emerald-600" />
            <span class="font-semibold text-slate-900">{{ total }}</span>
            <span class="text-slate-500">{{ $t('platform.rows') }}</span>
          </div>
          <div class="h-4 w-px bg-slate-200" />
          <div class="flex items-center gap-2 px-3 py-2">
            <Sparkles class="h-3.5 w-3.5 shrink-0 text-blue-600" />
            <span class="font-semibold capitalize text-slate-900">{{ engineLabel }}</span>
            <span class="text-slate-500">{{ $t('platform.engine') }}</span>
          </div>
          <div class="h-4 w-px bg-slate-200" />
          <div class="flex items-center gap-2 px-3 py-2">
            <ArrowDownUp class="h-3.5 w-3.5 shrink-0 text-orange-600" />
            <span class="font-semibold text-slate-900">{{ sortLabelMap[sortKey] }}</span>
            <span class="text-slate-500">{{ $t('platform.sortKey') }}</span>
          </div>
          <div class="h-4 w-px bg-slate-200" />
          <div v-if="contextBadges.length > 0" class="flex items-center gap-2 px-3 py-2">
            <Settings2 class="h-3.5 w-3.5 shrink-0 text-purple-600" />
            <span class="font-semibold text-slate-900">{{ $t('platform.context') }}</span>
            <Badge
              v-for="badge in contextBadges"
              :key="badge"
              variant="outline"
              class="font-mono text-[11px] text-slate-700"
            >
              {{ badge }}
            </Badge>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <Button v-if="canContinue" size="sm" variant="outline" :disabled="continuing" @click="continueGeneration">
            {{ $t('platform.continueGeneration') }}
          </Button>
          <Button size="sm" :disabled="!artifactKey" @click="downloadArtifact">
            {{ artifactKey === 'generated_sdf' ? $t('platform.downloadSdf') : $t('platform.downloadCsv') }}
          </Button>
        </div>
      </div>

      <div class="workbench-result-body">
        <GuestRecoveryBanner :job-id="jobId" />
        <p v-if="generationProgress" role="status" class="px-3 py-2 text-sm text-slate-700">
          {{ $t('platform.generationProgress', generationProgress) }}
        </p>
        <p v-if="quantityWarning" role="status" class="border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{{ quantityWarning }}</p>
        <p v-else-if="deliverySummary" role="status" class="px-3 py-2 text-sm text-slate-700">{{ deliverySummary }}</p>
        <router-link v-if="jobStatus === 'succeeded' && artifactKey" :to="{ path: '/postprocessing', query: { source_job_id: jobId } }" class="inline-block border border-slate-200 px-4 py-2 text-blue-700">{{ $t('platform.openInPostprocessing') }}</router-link>

        <PreparationErrorDetails v-if="preparationError" :error="preparationError" class="border border-red-200 bg-red-50 px-3 py-2" />
        <div v-if="errorMessage" class="border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {{ errorMessage }}
        </div>

        <FeedbackState v-if="loading" class="flex-1" kind="loading" :title="$t('platform.loading')" />
        <FeedbackState v-else-if="filteredRows.length === 0" class="flex-1" :title="$t('platform.noMoleculeGenerationResultsToDisplay')" />
        <div v-else class="workbench-table-area">
          <div class="workbench-table-scroll">
            <table class="min-w-full text-sm">
              <thead class="bg-slate-100 text-slate-600">
                <tr>
                  <th class="w-10 px-2 py-2 text-left font-semibold">#</th>
                  <th class="w-[196px] px-2 py-2 text-left font-semibold">{{ $t('platform.structure') }}</th>
                  <th class="cursor-pointer px-2 py-2 text-left font-semibold" @click="toggleSort('smiles')">
                    SMILES {{ sortMark('smiles') }}
                  </th>
                  <th
                    v-for="metric in visibleMetrics"
                    :key="metric.key"
                    class="cursor-pointer whitespace-nowrap px-2 py-2 text-left font-semibold"
                    @click="toggleSort(metric.key)"
                  >
                    {{ metric.label }} {{ sortMark(metric.key) }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(row, idx) in pagedRows"
                  :key="row.id"
                  class="cursor-pointer border-t border-slate-100 hover:bg-slate-50" :class="{ 'bg-accent': detailOpen && selectedRow?.id === row.id }" tabindex="0" @click="selectedRow = row; auxiliaryTab = 'details'; detailOpen = true" @keydown.enter="selectedRow = row; auxiliaryTab = 'details'; detailOpen = true"
                >
                  <td class="px-2 py-2 text-slate-500">{{ (currentPage - 1) * pageSize + idx + 1 }}</td>
                  <td class="px-2 py-1">
                    <MoleculeViewer :smiles="row.smiles" width="180px" height="130px" />
                  </td>
                  <td class="group max-w-[460px] px-2 py-2 font-mono">
                    <div class="mb-1 flex justify-center">
                      <Button
                        v-if="artifactKey === 'generated_sdf'"
                        variant="outline"
                        size="sm"
                        class="h-8 px-2 text-xs"
                        @click.stop="open3dViewer(row)"
                      >
                        <Box class="mr-1 h-3 w-3" />
                        {{ $t('platform.3dView') }}
                      </Button>
                    </div>
                    <div class="truncate" :title="row.smiles">{{ row.smiles }}</div>
                  </td>
                  <td v-for="metric in visibleMetrics" :key="metric.key" class="whitespace-nowrap px-2 py-2">
                    {{ formatMetric(row[metric.key]) }}
                  </td>
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
              {{ $t('platform.rowsLabel') }}
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
    <template #auxiliary><ModuleAssistantPanel v-if="assistantOpened && assistantJob?.id === jobId" v-show="auxiliaryTab === 'assistant'" :key="jobId" module="molecule_generation" :job-id="jobId" :context="assistantContext" :apply="applyAssistant" /><MoleculeDetails v-show="auxiliaryTab === 'details'" :row="selectedRow" :has3d="artifactKey === 'generated_sdf'" @view3d="show3dDialog = true"><div v-for="metric in visibleMetrics" :key="metric.key" class="flex justify-between gap-3"><dt class="text-muted-foreground">{{ metric.label }}</dt><dd>{{ formatMetric(selectedRow?.[metric.key] ?? null) }}</dd></div></MoleculeDetails></template>
    </WorkspaceLayout>
      <Dialog v-model:open="show3dDialog">
        <DialogContent class="max-w-5xl">
          <DialogHeader>
            <DialogTitle>{{ $t('platform.3dStructure') }}</DialogTitle>
            <DialogDescription class="truncate font-mono text-xs">
              {{ selectedRow?.smiles }}
            </DialogDescription>
          </DialogHeader>
          <div ref="poseContainer" class="h-[70vh] min-h-[420px] overflow-hidden border border-slate-200 bg-white" />
        </DialogContent>
      </Dialog>
      <div class="hidden"><Teleport :to="poseContainer || 'body'" :disabled="!poseContainer">
        <BindingPoseViewer v-if="selectedRow" :visible="show3dDialog" :job-id="jobId" :result-id="selectedRow.id" :smiles="selectedRow.smilesCanonical || selectedRow.smiles" />
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
import type { PreparationErrorInfo } from '@/types/proteinContext'

import { defineAsyncComponent, computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clearMoleculeRenderer } from '@/utils/moleculeRenderer'
import request from '@/utils/request'
import { useRoute } from 'vue-router'
import { ArrowDownUp, Box, CheckCircle2, ChevronRight, Sparkles, Settings2 } from 'lucide-vue-next'
import { toast } from '@/components/ui/toast/use-toast'

import PageHeader from '@/components/workbench/PageHeader.vue'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import MoleculeDetails from '@/components/workbench/MoleculeDetails.vue'
import { useWorkspaceState } from '@/composables/useWorkspace'
import AppFrame from '@/components/Layout/appFrame.vue'
import GuestRecoveryBanner from '@/components/auth/GuestRecoveryBanner.vue'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
const BindingPoseViewer = defineAsyncComponent(() => import('@/components/molecule/BindingPoseViewer.vue'))
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { continueBackendGeneration, downloadBackendJobArtifact, getBackendJob, listBackendJobResults, type BackendSmallMoleculeResult } from '@/api/genovaBackend'
import { displayErrorMessage } from '@/utils/requestError'

type MetricKey = 'qed' | 'logp' | 'sa' | 'tpsa' | 'weight'
type SortKey = 'smiles' | MetricKey

interface MolGenRow {
  id: string
  smiles: string
  smilesCanonical: string
  context: string
  qed: number | null
  logp: number | null
  sa: number | null
  tpsa: number | null
  weight: number | null
}

const METRICS = computed<Array<{ key: MetricKey; label: string }>>(() => [
  { key: 'qed', label: 'QED' },
  { key: 'logp', label: 'LogP' },
  { key: 'sa', label: 'SA' },
  { key: 'tpsa', label: 'TPSA' },
  { key: 'weight', label: translate('platform.weight') },
])

const sortLabelMap = computed<Record<SortKey, string>>(() => ({
  smiles: 'SMILES',
  qed: 'QED',
  logp: 'LogP',
  sa: 'SA',
  tpsa: 'TPSA',
  weight: translate('platform.weight'),
}))

const route = useRoute()

const jobId = computed(() => {
  const value = route.query.job_id
  return Array.isArray(value) ? (value[0] || '') : (value || '')
})

const assistantJob = ref<BackendJobOut | null>(null)
const auxiliaryTab = ref('details'), assistantOpened = ref(false)
const L = (zh: string, en: string) => i18n.global.locale.value.startsWith('zh') ? zh : en
const assistantRouter = useRouter()
const moduleSuggestion = useModuleSuggestion('molecule_generation')
const assistantContext = computed<ModuleContext>(() => ({
  engine: assistantJob.value?.params.molecule_generation?.engine || 'surfgen',
  protein_context_id: assistantJob.value?.params.protein_context_id || undefined,
  form: assistantJob.value?.params.molecule_generation || {},
  selected_ids: selectedRow.value?.id ? [selectedRow.value.id] : [],
}))
async function applyAssistant(suggestion: ModuleSuggestion) { await moduleSuggestion.openDraft(assistantRouter, jobId.value, suggestion) }
const jobName = ref('')
const loading = ref(false)
const errorMessage = ref('')
const preparationError = ref<PreparationErrorInfo>()
const rows = ref<MolGenRow[]>([])
const engineLabel = ref('unknown')
const quantityWarning = ref('')
const deliverySummary = ref('')
const canContinue = ref(false)
const continuing = ref(false)
const generationProgress = ref<{ requested: number; actual: number; rounds: number }>()
const artifactKey = ref('')
const artifactTaskCode = ref('molecule_generation')
const jobStatus = ref('')
const contextBadges = ref<string[]>([])
const show3dDialog = ref(false)
const { selectedRow, detailOpen, sortKey, sortDesc, currentPage, pageSize, searchQuery, appliedSearch } = useWorkspaceState('molgen-results', () => jobId.value, { selectedRow: null as MolGenRow | null, detailOpen: false, sortKey: 'smiles' as SortKey, sortDesc: false, currentPage: 1, pageSize: 20, searchQuery: '', appliedSearch: '' })
const poseContainer = ref<HTMLElement | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | null = null


const total = ref(0)
const averages = ref<Record<string, number | null>>({})
const visibleMetrics = computed(() => METRICS.value.filter(metric => averages.value[metric.key] != null || rows.value.some(row => row[metric.key] !== null)))
const filteredRows = computed(() => rows.value)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const pagedRows = computed(() => rows.value)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
let loadRevision = 0
let metadata: Awaited<ReturnType<typeof getBackendJob>> | undefined

function parseNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function formatMetric(value: number | null): string {
  return value === null ? '-' : value.toFixed(3)
}

function sortMark(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortDesc.value ? '↓' : '↑'
}

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortDesc.value = !sortDesc.value
    return
  }
  sortKey.value = key
  sortDesc.value = key === 'smiles' ? false : true
}


function parseFilenameFromDisposition(value: string | undefined): string | null {
  if (!value) return null
  const match = /filename\\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?/i.exec(value)
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

function normalizeRow(item: BackendSmallMoleculeResult): MolGenRow {
  const extra = item.extra || {}
  const raw = (extra.raw || {}) as Record<string, unknown>
  const proteinPath = String(extra.protein_path || '').trim()

  return {
    id: item.id,
    smiles: item.smiles || item.smiles_canonical,
    smilesCanonical: item.smiles_canonical || item.smiles,
    context: proteinPath,
    qed: parseNumber(raw.QED ?? raw.qed ?? extra.qed),
    logp: parseNumber(raw.LogP ?? raw.logp ?? extra.logp),
    sa: parseNumber(raw.SA ?? raw.sa ?? extra.sa),
    tpsa: parseNumber(raw.TPSA ?? raw.tpsa ?? extra.tpsa),
    weight: parseNumber(raw.Weight ?? raw.weight ?? extra.weight),
  }
}

function open3dViewer(row: MolGenRow) {
  selectedRow.value = row
  show3dDialog.value = true
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const normalized = String(value || '').trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    result.push(normalized)
  }
  return result
}

async function loadResults() {
  if (!jobId.value) {
    errorMessage.value = translate('platform.missingJobIdInRouteQuery')
    return
  }

  loading.value = true
  errorMessage.value = ''
  const revision = ++loadRevision
  controller?.abort()
  controller = new AbortController()

  try {
    const [jobResp, resultsResp] = await Promise.all([
      metadata && metadata.data.id === jobId.value && metadata.data.status === 'succeeded' ? Promise.resolve(metadata) : getBackendJob(jobId.value, { summary: true, signal: controller.signal }),
      listBackendJobResults(jobId.value, { limit: pageSize.value, offset: (currentPage.value - 1) * pageSize.value,
        search: appliedSearch.value, sort_by: sortKey.value, descending: sortDesc.value, signal: controller.signal }),
    ])
    if (revision !== loadRevision) return
    if (!metadata || metadata.data.id !== jobId.value || metadata.data.status !== jobResp.data.status) {
      const summary = await request.get(`/api/v1/jobs/${jobId.value}/results/summary`)
      if (revision !== loadRevision) return
      averages.value = summary.data
    }
    metadata = jobResp
    total.value = Number(resultsResp.headers['x-total-count'] || 0)

    const job = jobResp.data
    assistantJob.value = job
    jobStatus.value = job.status
    jobName.value = String((job.params || {}).job_name || `${job.job_type}_${job.id.slice(0, 8)}`)

    const task = (job.tasks || []).find((item) => item.task_code === 'surfgen_inference')
      || (job.tasks || []).find((item) => item.task_code === 'molecule_generation')
    preparationError.value = task?.output_payload?.error_info
    const inputPayload = (task?.input_payload || {}) as Record<string, any>
    const outputPayload = (task?.output_payload || {}) as Record<string, any>
    const progress = job.summary?.generation_progress
    generationProgress.value = progress ? {
      requested: progress.requested_count, actual: progress.result_count, rounds: progress.completed_rounds,
    } : undefined
    canContinue.value = job.status === 'succeeded' && outputPayload.can_continue_generation === true
    engineLabel.value = String(outputPayload.engine || inputPayload.engine || 'unknown')
    quantityWarning.value = generationQuantityWarning(outputPayload)
    deliverySummary.value = generationDeliverySummary(outputPayload)
    artifactTaskCode.value = task?.task_code || 'molecule_generation'
    artifactKey.value = outputPayload.generated_sdf
      ? 'generated_sdf'
      : (outputPayload.output_csv ? 'output_csv' : '')
    const proteinPath = String(outputPayload.protein_path || inputPayload.protein_pdb || '').trim()
    contextBadges.value = uniqueStrings([
      proteinPath ? (proteinPath.split('/').pop() || proteinPath) : '',
    ])

    rows.value = (resultsResp.data || []).map(normalizeRow)
  } catch (error: any) {
    if (revision !== loadRevision || controller?.signal.aborted) return
    errorMessage.value = displayErrorMessage(error, translate('platform.failedToLoadResults'))
  } finally {
    if (revision === loadRevision) { loading.value = false; schedulePolling() }
  }
}

function schedulePolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
  if (!['pending', 'queued', 'running', 'blocked'].includes(jobStatus.value)) return
  pollTimer = setTimeout(loadResults, 2000)
}

async function continueGeneration() {
  if (!canContinue.value || continuing.value) return
  const currentId = jobId.value
  continuing.value = true
  try {
    await continueBackendGeneration(currentId)
    if (jobId.value === currentId) {
      metadata = undefined
      canContinue.value = false
      await loadResults()
    }
  } catch (error: any) {
    if (jobId.value === currentId) errorMessage.value = displayErrorMessage(error, translate('platform.failedToLoadResults'))
  } finally {
    continuing.value = false
  }
}

async function downloadArtifact() {
  if (!jobId.value || !artifactKey.value) return
  try {
    const response = await downloadBackendJobArtifact(jobId.value, {
      task_code: artifactTaskCode.value,
      key: artifactKey.value,
    })
    const filename = parseFilenameFromDisposition(String(response.headers?.['content-disposition'] || ''))
      || `molecule_generation_${jobId.value}.${artifactKey.value === 'generated_sdf' ? 'sdf' : 'csv'}`
    downloadBlob(response.data, filename)
  } catch (error: any) {
    toast({
      variant: 'destructive',
      title: translate('platform.downloadFailed'),
      description: displayErrorMessage(error, translate('platform.downloadFailed')),
      duration: 5000,
    })
  }
}

watch(searchQuery, value => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { appliedSearch.value = value.trim() }, 250) })
watch(jobId, () => { metadata = undefined; quantityWarning.value = ''; deliverySummary.value = ''; canContinue.value = false; generationProgress.value = undefined; show3dDialog.value = false; averages.value = {}; rows.value = []; total.value = 0 })
watch([jobId, appliedSearch, pageSize, sortKey, sortDesc], (next, previous) => { if (next[0] === previous[0]) currentPage.value = 1 })
watch([jobId, appliedSearch, pageSize, sortKey, sortDesc, currentPage], () => { void loadResults() })

onMounted(() => {
  loadResults()
})

onBeforeUnmount(() => {
  loadRevision++; controller?.abort(); clearTimeout(searchTimer); clearMoleculeRenderer()
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<route lang="yaml">
meta:
  layout: blank
</route>
