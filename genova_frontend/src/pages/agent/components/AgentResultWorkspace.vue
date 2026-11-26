<template>
  <div class="agent-result-workspace flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white">
    <template v-if="isPostprocessing">
      <TarPassPanel
        v-if="resolvedSourceJobId"
        :key="`${jobId}:${resolvedSourceJobId}`"
        class="min-h-0 flex-1"
        :source-job-id="resolvedSourceJobId"
        :source-job="sourceJob"
        :initial-job-id="jobId"
        :candidate-set-id="candidateSetId || undefined"
        mode="results"
        :read-only="readOnly"
        :embedded="readOnly"
        @continue-optimization="forwardOptimization"
      />
      <div v-else-if="loading" class="p-6 text-sm text-slate-500">{{ $t('platform.loading') }}</div>
      <div v-else class="p-6 text-sm text-red-700">{{ errorMessage || $t('platform.failedToLoadResults') }}</div>
    </template>

    <template v-else>
      <header class="shrink-0 border-b border-slate-200 bg-white px-4 py-3 sm:px-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">
              {{ candidateSetId ? $t('platform.candidate') : kindLabel }}
            </p>
            <h2 class="truncate text-base font-semibold text-slate-900">{{ title }}</h2>
            <p v-if="candidateSetId" class="mt-1 text-xs text-slate-500">
              {{ $t('platform.molecules') }} · {{ displayTotal }}
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <span class="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600">
              {{ statusText }}
            </span>
            <template v-if="!candidateSetId">
              <button
                v-if="artifactKeys.includes('output_csv')"
                type="button"
                class="rounded border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loading"
                @click="downloadArtifact('output_csv', 'results.csv')"
              >
                {{ $t('platform.downloadCsv') }}
              </button>
              <button
                v-if="artifactKeys.includes('generated_sdf')"
                type="button"
                class="rounded border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loading"
                @click="downloadArtifact('generated_sdf', 'generated.sdf')"
              >
                {{ $t('platform.downloadSdf') }}
              </button>
              <button
                v-if="artifactKeys.includes('trajectory_csv')"
                type="button"
                class="rounded border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loading"
                @click="downloadArtifact('trajectory_csv', 'trajectory.csv')"
              >
                {{ $t('platform.epsoTrajectory') }}
              </button>
              <button
                v-if="artifactKeys.includes('trajectory_csv')"
                type="button"
                class="rounded border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loading"
                @click="openTrajectory"
              >
                {{ $i18n.locale === 'zh-CN' ? '查看优化轨迹' : 'View optimization trajectory' }}
              </button>
              <button
                v-if="!readOnly && !postprocessingOpen"
                type="button"
                class="rounded border border-blue-200 bg-blue-50 px-2 py-1.5 text-xs text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                :disabled="loading || !metadata"
                @click="postprocessingOpen = true"
              >
                {{ $t('platform.openInPostprocessing') }}
              </button>
            </template>
          </div>
        </div>

        <div v-if="!candidateSetId && !postprocessingOpen" class="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
          <div class="rounded border border-slate-200 bg-slate-50 px-3 py-2">
            <span class="block text-slate-500">{{ $t('platform.rows') }}</span>
            <strong class="text-sm text-slate-900">{{ displayTotal }}</strong>
          </div>
          <div class="rounded border border-slate-200 bg-slate-50 px-3 py-2">
            <span class="block text-slate-500">{{ $t('platform.engine') }}</span>
            <strong class="text-sm capitalize text-slate-900">{{ engine }}</strong>
          </div>
          <div class="rounded border border-slate-200 bg-slate-50 px-3 py-2">
            <span class="block text-slate-500">{{ $t('platform.page') }}</span>
            <strong class="text-sm text-slate-900">{{ currentPage }} / {{ totalPages }}</strong>
          </div>
          <div v-if="fitnessSummary" class="rounded border border-blue-200 bg-blue-50 px-3 py-2 text-blue-900 sm:col-span-3">
            <span class="block text-xs text-blue-700">{{ $i18n.locale === 'zh-CN' ? '当前页 Fitness' : 'Current page Fitness' }}</span>
            <strong class="text-sm">{{ fitnessSummary }}</strong>
          </div>
        </div>
      </header>

      <div v-if="postprocessingOpen && !readOnly" class="min-h-0 flex-1 overflow-auto p-4 sm:p-5">
        <div class="mb-3 flex items-center justify-between gap-3">
          <h3 class="font-semibold text-slate-900">{{ $t('platform.tarpassPostprocessing') }}</h3>
          <button type="button" class="text-sm text-blue-700 hover:underline" @click="postprocessingOpen = false">
            {{ $t('platform.backToGenerationResults') }}
          </button>
        </div>
        <TarPassPanel
          :source-job-id="props.jobId"
          :source-job="metadata"
          :source-job-name="title"
          mode="submit"
          embedded
          @submitted="forwardSubmitted"
          @prepare-postprocessing="forwardPostprocessing"
        />
      </div>

      <div v-else class="min-h-0 flex-1 overflow-auto p-4 sm:p-5">
        <div v-if="errorMessage" role="alert" class="mb-3 border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {{ errorMessage }}
        </div>
        <div v-if="quantityWarning" role="status" class="mb-3 border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {{ quantityWarning }}
        </div>

        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <label class="flex min-w-48 flex-1 items-center gap-2 text-xs text-slate-600">
            <span class="shrink-0">{{ $t('platform.search') }}</span>
            <input
              v-model="searchQuery"
              type="search"
              class="h-8 min-w-0 flex-1 rounded border border-slate-300 px-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              :placeholder="searchPlaceholder"
            >
          </label>
          <div class="flex items-center gap-2 text-xs text-slate-600">
            <span>{{ $t('platform.perPage') }}</span>
            <select v-model.number="pageSize" class="h-8 rounded border border-slate-300 px-2">
              <option :value="20">20</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select>
          </div>
        </div>

        <div v-if="loading && !displayRows.length" class="border border-slate-200 px-3 py-10 text-center text-sm text-slate-500">
          {{ $t('platform.loading') }}
        </div>
        <div v-else-if="!displayRows.length" class="border border-slate-200 px-3 py-10 text-center text-sm text-slate-500">
          {{ emptyLabel }}
        </div>
        <div v-else class="overflow-x-auto border border-slate-200">
          <table class="min-w-full text-sm">
            <thead class="bg-slate-50 text-left text-xs text-slate-600">
              <tr>
                <th class="w-10 px-3 py-2 font-semibold">#</th>
                <th class="w-[150px] px-3 py-2 font-semibold">{{ $t('platform.structure') }}</th>
                <th class="min-w-[260px] px-3 py-2 font-semibold">SMILES</th>
                <th v-for="column in metricColumns" :key="column" class="whitespace-nowrap px-3 py-2 text-right font-semibold">
                  {{ metricLabel(column) }}
                </th>
                <th class="w-44 px-3 py-2 font-semibold">{{ $t('platform.continue') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, index) in displayRows"
                :key="rowKey(row)"
                class="border-t border-slate-100 align-top hover:bg-slate-50"
                :class="{ 'bg-blue-50/50': selectedRowKey === rowKey(row) }"
                @click="selectRow(row)"
              >
                <td class="px-3 py-3 text-slate-500">{{ (currentPage - 1) * pageSize + index + 1 }}</td>
                <td class="px-3 py-2">
                  <MoleculeViewer v-if="row.smiles" :smiles="row.edit_preview?.molfile || row.smiles" width="130px" height="95px" :highlight-atom-colors="highlightColors(row.edit_preview)" />
                  <span v-else class="text-xs text-slate-400">{{ $t('platform.unreadableSdfRecord') }}</span>
                  <button
                    v-if="rowHas3d(row)"
                    type="button"
                    class="mt-1 block text-xs text-blue-700 hover:underline"
                    @click.stop="open3d(row)"
                  >
                    {{ $t('platform.3dView') }}
                  </button>
                </td>
                <td class="max-w-[520px] px-3 py-3 font-mono text-xs">
                  <span class="break-all">{{ row.smiles || '—' }}</span>
                  <span v-if="row.status && row.status !== 'succeeded'" class="mt-1 block text-[11px] text-amber-700">{{ row.status }}</span>
                </td>
                <td v-for="column in metricColumns" :key="column" class="whitespace-nowrap px-3 py-3 text-right tabular-nums text-slate-700">
                  {{ formatMetric(metricValue(row, column)) }}
                </td>
                <td class="px-3 py-3">
                  <button
                    type="button"
                    class="rounded border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                    v-if="!readOnly"
                    :disabled="!row.smiles"
                    @click.stop="requestOptimization(row)"
                  >
                    {{ $t('platform.continue') }} · {{ $t('platform.leadOptimization') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-3 flex items-center justify-between gap-3 text-xs text-slate-600">
          <span>{{ displayTotal }} {{ $t('platform.rowsLabel') }}</span>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="rounded border border-slate-300 px-2.5 py-1.5 hover:bg-slate-50 disabled:opacity-50"
              :disabled="loading || currentPage <= 1"
              @click="currentPage -= 1"
            >
              {{ $t('platform.previous') }}
            </button>
            <span>{{ currentPage }} / {{ totalPages }}</span>
            <button
              type="button"
              class="rounded border border-slate-300 px-2.5 py-1.5 hover:bg-slate-50 disabled:opacity-50"
              :disabled="loading || currentPage >= totalPages"
              @click="currentPage += 1"
            >
              {{ $t('platform.next') }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <Dialog v-model:open="show3dDialog">
      <DialogContent class="max-w-5xl">
        <DialogHeader>
          <DialogTitle>{{ $t('platform.3dStructure') }}</DialogTitle>
          <DialogDescription class="truncate font-mono text-xs">{{ selectedRow?.smiles }}</DialogDescription>
        </DialogHeader>
        <div ref="poseContainer" class="h-[65vh] min-h-[400px] overflow-hidden border border-slate-200 bg-white" />
      </DialogContent>
    </Dialog>
    <Dialog v-model:open="conformerDialog">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>{{ $t('platform.bindingConformer') }}</DialogTitle>
          <DialogDescription>{{ selectedRow?.smiles }}</DialogDescription>
        </DialogHeader>
        <p class="text-sm text-slate-600">{{ $t('platform.bindingConformer') }} · {{ conformerOptions.length }}</p>
        <select v-model.number="selectedSourceIndex" class="w-full rounded border border-slate-300 p-2" :disabled="optimizationLoading">
          <option v-for="record in conformerOptions" :key="record.source_index" :value="record.source_index">{{ record.source_index + 1 }}</option>
        </select>
        <div class="flex justify-end gap-2">
          <button type="button" class="rounded border border-slate-300 px-3 py-2 text-sm" @click="conformerDialog = false">{{ $t('common.cancel') }}</button>
          <button type="button" class="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50" :disabled="readOnly || optimizationLoading || selectedSourceIndex == null" @click="confirmOptimization">{{ $t('platform.continue') }}</button>
        </div>
      </DialogContent>
    </Dialog>
    <Dialog v-model:open="trajectoryDialog">
      <DialogContent class="max-w-5xl">
        <DialogHeader>
          <DialogTitle>{{ $i18n.locale === 'zh-CN' ? '优化轨迹' : 'Optimization trajectory' }}</DialogTitle>
          <DialogDescription>{{ trajectoryRows.length }} {{ $t('platform.rowsLabel') }}</DialogDescription>
        </DialogHeader>
        <div v-if="trajectoryPoints" class="overflow-x-auto rounded border border-slate-200 bg-slate-50 p-3">
          <svg viewBox="0 0 640 220" class="h-56 min-w-[600px] w-full" role="img" aria-label="Fitness trajectory">
            <line x1="40" y1="15" x2="40" y2="205" stroke="#94a3b8" stroke-width="1" />
            <line x1="40" y1="205" x2="630" y2="205" stroke="#94a3b8" stroke-width="1" />
            <polyline :points="trajectoryPoints" fill="none" stroke="#2563eb" stroke-width="3" vector-effect="non-scaling-stroke" />
            <text x="4" y="22" class="fill-slate-500 text-[10px]">{{ trajectoryBounds ? formatTrajectoryValue(trajectoryBounds.yMax) : '' }}</text>
            <text x="4" y="205" class="fill-slate-500 text-[10px]">{{ trajectoryBounds ? formatTrajectoryValue(trajectoryBounds.yMin) : '' }}</text>
            <text x="40" y="218" class="fill-slate-500 text-[10px]">{{ trajectoryBounds ? formatTrajectoryValue(trajectoryBounds.xMin) : '' }}</text>
            <text x="605" y="218" class="fill-slate-500 text-[10px]">{{ trajectoryBounds ? formatTrajectoryValue(trajectoryBounds.xMax) : '' }}</text>
            <text x="44" y="14" class="fill-slate-500 text-[10px]">Fitness</text>
            <text x="595" y="218" class="fill-slate-500 text-[10px]">step</text>
          </svg>
          <div v-if="trajectoryBounds" class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
            <span>{{ $i18n.locale === 'zh-CN' ? '首步' : 'First step' }} {{ formatTrajectoryValue(trajectoryBounds.firstX) }}: {{ formatTrajectoryValue(trajectoryBounds.firstY) }}</span>
            <span>{{ $i18n.locale === 'zh-CN' ? '末步' : 'Last step' }} {{ formatTrajectoryValue(trajectoryBounds.lastX) }}: {{ formatTrajectoryValue(trajectoryBounds.lastY) }}</span>
            <span>{{ $i18n.locale === 'zh-CN' ? '最低' : 'Min' }} {{ formatTrajectoryValue(trajectoryBounds.yMin) }}</span>
            <span>{{ $i18n.locale === 'zh-CN' ? '最高' : 'Max' }} {{ formatTrajectoryValue(trajectoryBounds.yMax) }}</span>
          </div>
        </div>
        <div class="max-h-72 overflow-auto border border-slate-200">
          <table class="min-w-full text-xs">
            <thead class="bg-slate-50 text-left text-slate-600"><tr><th v-for="column in trajectoryColumns" :key="column" class="px-3 py-2 font-semibold">{{ column }}</th></tr></thead>
            <tbody><tr v-for="(row, index) in trajectoryRows" :key="index" class="border-t border-slate-100"><td v-for="column in trajectoryColumns" :key="column" class="whitespace-nowrap px-3 py-2">{{ row[column] }}</td></tr></tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
    <div class="hidden">
      <Teleport :to="poseContainer || 'body'" :disabled="!poseContainer">
        <BindingPoseViewer
          v-if="selectedRow && candidateSetId"
          :visible="show3dDialog"
          :job-id="viewerJobId"
          :result-id="viewerResultId"
          :molecule-id="viewerMoleculeId"
          :smiles="selectedRow.smiles"
          pose="docked"
        />
        <BindingPoseViewer
          v-else-if="selectedRow"
          :visible="show3dDialog"
          :job-id="viewerJobId"
          :result-id="viewerResultId"
          :molecule-id="viewerMoleculeId"
          :smiles="selectedRow.smiles"
        />
      </Teleport>
    </div>
  </div>
</template>

<script setup lang="ts">
import { generationQuantityWarning } from '@/utils/taskPresentation'
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import request from '@/utils/request'
import { translate, statusLabel } from '@/i18n'
import { displayErrorMessage } from '@/utils/requestError'
import { getBackendJob, listBackendJobResults, downloadBackendJobArtifact, type BackendJobOut, type BackendSmallMoleculeResult } from '@/api/genovaBackend'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import TarPassPanel from '@/components/molecule/TarPassPanel.vue'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
const BindingPoseViewer = defineAsyncComponent(() => import('@/components/molecule/BindingPoseViewer.vue'))

type ResultKind = 'molecule_generation' | 'property_optimization' | 'molecule_postprocessing'
type Pose = 'generated' | 'original' | 'docked'
type ResultRow = {
  id?: string
  result_id?: string
  molecule_id?: string
  source_index?: number
  smiles: string
  smiles_canonical?: string
  status?: string
  metrics?: Record<string, any>
  extra?: Record<string, any>
  edit_preview?: Record<string, any>
}
type OptimizationPayload = {
  jobId: string
  resultId?: string
  moleculeId?: string
  sourceIndex?: number
  pose?: Pose
  smiles?: string
}
type StructureRecord = { source_index: number }

const props = withDefaults(defineProps<{
  jobId: string
  jobType: ResultKind
  candidateSetId?: string
  sessionId?: string
  sourceJobId?: string
  title?: string
  readOnly?: boolean
}>(), { candidateSetId: '', sessionId: '', sourceJobId: '', title: '' })
const emit = defineEmits<{
  optimize: [payload: OptimizationPayload]
  submitted: [jobId: string]
  preparePostprocessing: [payload: Record<string, any>]
}>()

const isPostprocessing = computed(() => props.jobType === 'molecule_postprocessing')
const kindLabel = computed(() => props.jobType === 'property_optimization' ? translate('platform.leadOptimization') : translate('platform.deNovoGeneration'))
const title = computed(() => props.title || (props.candidateSetId ? translate('platform.candidate') : props.jobType === 'property_optimization' ? translate('platform.leadOptimizationResults') : translate('platform.generationResults')))
const searchPlaceholder = computed(() => props.candidateSetId ? `${translate('platform.search')} SMILES / ID` : `${translate('platform.search')} SMILES`)
const emptyLabel = computed(() => props.jobType === 'property_optimization' ? translate('platform.noLeadOptimizationResultsToDisplay') : translate('platform.noMoleculeGenerationResultsToDisplay'))
const rows = ref<ResultRow[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchQuery = ref('')
const loading = ref(false)
const errorMessage = ref('')
const quantityWarning = ref('')
const jobStatus = ref('')
const engine = ref('—')
const artifactKeys = ref<string[]>([])
const metadata = ref<BackendJobOut | null>(null)
const sourceJob = ref<BackendJobOut | null>(null)
const resolvedSourceJobId = ref(props.sourceJobId)
const selectedRow = ref<ResultRow | null>(null)
const postprocessingOpen = ref(false)
const show3dDialog = ref(false)
const poseContainer = ref<HTMLElement | null>(null)
const conformerDialog = ref(false)
const conformerOptions = ref<StructureRecord[]>([])
const selectedSourceIndex = ref<number | null>(null)
const pendingOptimization = ref<OptimizationPayload | null>(null)
const optimizationLoading = ref(false)
const trajectoryDialog = ref(false)
const trajectoryRows = ref<Array<Record<string, string>>>([])
const requestRevision = ref(0)
let controller: AbortController | undefined
let pollTimer: ReturnType<typeof setTimeout> | undefined
let searchTimer: ReturnType<typeof setTimeout> | undefined

const statusText = computed(() => jobStatus.value ? statusLabel(jobStatus.value) : translate('platform.loading'))
const selectedRowKey = computed(() => selectedRow.value ? rowKey(selectedRow.value) : '')
const displayRows = computed(() => rows.value)
const displayTotal = computed(() => total.value)
const totalPages = computed(() => Math.max(1, Math.ceil(displayTotal.value / pageSize.value)))
const viewerJobId = computed(() => props.jobId)
const viewerResultId = computed(() => selectedRow.value?.result_id || selectedRow.value?.id)
const viewerMoleculeId = computed(() => selectedRow.value?.molecule_id)
const metricColumns = computed(() => {
  if (props.candidateSetId) return ['qed', 'sa_score', 'docked.affinity']
  const keys = new Set<string>()
  for (const row of rows.value) {
    const extra = row.extra || {}
    const raw = extra.raw || {}
    for (const key of ['qed', 'logp', 'sa', 'tpsa', 'weight']) if (raw[key] != null || extra[key] != null) keys.add(key)
    if (extra.fitness != null) keys.add('fitness')
    for (const key of Object.keys(extra.metrics || {})) if (!key.includes('.') && ['qed', 'logp', 'sa', 'tpsa', 'weight', 'fitness'].includes(key)) keys.add(key)
  }
  return [...keys]
})
const fitnessSummary = computed(() => {
  if (props.jobType !== 'property_optimization' || engine.value.toLowerCase() !== 'epso') return ''
  const values = rows.value.map(row => Number(row.extra?.fitness)).filter(Number.isFinite)
  if (!values.length) return ''
  const best = Math.max(...values)
  const average = values.reduce((sum, value) => sum + value, 0) / values.length
  return `best ${best.toFixed(3)} · avg ${average.toFixed(3)}`
})
const trajectoryColumns = computed(() => Object.keys(trajectoryRows.value[0] || {}))
const trajectoryColumn = computed(() => trajectoryColumns.value.find(key => /fitness|score|objective/i.test(key)) || '')
const trajectoryNumericRows = computed(() => trajectoryRows.value.map((row, index) => ({
  x: Number(row.step ?? row.iteration ?? index),
  y: Number(row[trajectoryColumn.value]),
})).filter(point => Number.isFinite(point.x) && Number.isFinite(point.y)))
const trajectoryBounds = computed(() => {
  const points = trajectoryNumericRows.value
  if (!points.length) return null
  const yValues = points.map(point => point.y)
  const xValues = points.map(point => point.x)
  return {
    xMin: Math.min(...xValues),
    xMax: Math.max(...xValues),
    yMin: Math.min(...yValues),
    yMax: Math.max(...yValues),
    firstX: points[0].x,
    firstY: points[0].y,
    lastX: points[points.length - 1].x,
    lastY: points[points.length - 1].y,
  }
})
const trajectoryPoints = computed(() => {
  const bounds = trajectoryBounds.value
  const points = trajectoryNumericRows.value
  if (!bounds || points.length < 2) return ''
  const xSpan = bounds.xMax - bounds.xMin || 1
  const ySpan = bounds.yMax - bounds.yMin || 1
  return points.map(point => {
    const x = ((point.x - bounds.xMin) / xSpan) * 580 + 40
    const y = 205 - ((point.y - bounds.yMin) / ySpan) * 190
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})
function formatTrajectoryValue(value: number) { return Number.isInteger(value) ? String(value) : value.toFixed(3) }

function rowKey(row: ResultRow) { return row.result_id || row.id || row.molecule_id || row.smiles }
function metricLabel(key: string) {
  if (key === 'fitness') return 'Fitness'
  if (key === 'docked.affinity') return `${translate('platform.docked')} / Affinity`
  if (key === 'sa_score') return 'SA'
  return key.toUpperCase()
}
function metricValue(row: ResultRow, key: string): unknown {
  if (props.candidateSetId) return key.split('.').reduce((value: any, part) => value?.[part], row.metrics)
  const extra = row.extra || {}
  const raw = extra.raw || {}
  return extra[key] ?? extra.metrics?.[key] ?? raw[key] ?? raw[key.toUpperCase()] ?? null
}
function formatMetric(value: unknown) {
  if (value == null || value === '') return '—'
  return typeof value === 'number' ? value.toFixed(3) : String(value)
}
function highlightColors(preview: Record<string, any> | undefined): Record<number, [number, number, number]> {
  const colors: Record<number, [number, number, number]> = {}
  for (const index of preview?.retained_atom_indices || []) colors[index] = [0.3, 0.8, 0.5]
  for (const index of preview?.changed_atom_indices || []) colors[index] = [0.4, 0.65, 1]
  return colors
}
function rowHas3d(row: ResultRow) {
  return artifactKeys.value.includes('generated_sdf') && Boolean(row.id || row.result_id)
}
function selectRow(row: ResultRow) {
  selectedRow.value = row
}
function open3d(row: ResultRow) {
  selectedRow.value = row
  show3dDialog.value = true
}
function optimizationPayload(row: ResultRow): OptimizationPayload {
  return {
    jobId: props.jobId,
    resultId: row.result_id || row.id,
    moleculeId: row.molecule_id,
    sourceIndex: row.source_index,
    pose: 'generated',
    smiles: row.smiles,
  }
}
function forwardOptimization(payload: OptimizationPayload) { if (!props.readOnly) emit('optimize', payload) }
function forwardSubmitted(jobId: string) { emit('submitted', jobId) }
function forwardPostprocessing(payload: Record<string, any>) { emit('preparePostprocessing', payload) }
async function requestOptimization(row: ResultRow) {
  if (props.readOnly) return
  const payload = optimizationPayload(row)
  if (!rowHas3d(row)) {
    forwardOptimization({ ...payload, sourceIndex: undefined, pose: undefined })
    return
  }
  optimizationLoading.value = true
  errorMessage.value = ''
  try {
    const response = await request.get(`/api/v1/jobs/${payload.jobId}/structures`, {
      params: { result_id: payload.resultId, molecule_id: payload.moleculeId, pose: payload.pose === 'generated' ? 'generated' : payload.pose, limit: 100 },
    })
    const records = (response.data?.records || []) as StructureRecord[]
    if (!records.length) {
      errorMessage.value = translate('platform.failedToLoadResults')
      return
    }
    if (records.length === 1) {
      forwardOptimization({ ...payload, sourceIndex: records[0].source_index })
      return
    }
    selectedRow.value = row
    pendingOptimization.value = payload
    conformerOptions.value = records
    selectedSourceIndex.value = null
    conformerDialog.value = true
  } catch (error: any) {
    errorMessage.value = displayErrorMessage(error, translate('platform.failedToLoadResults'))
  } finally {
    optimizationLoading.value = false
  }
}
function confirmOptimization() {
  if (!pendingOptimization.value || selectedSourceIndex.value == null) return
  forwardOptimization({ ...pendingOptimization.value, sourceIndex: selectedSourceIndex.value })
  pendingOptimization.value = null
  conformerDialog.value = false
}
function parseFilename(value: string | undefined) {
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
async function downloadArtifact(key: string, fallback: string) {
  try {
    const response = await downloadBackendJobArtifact(props.jobId, { task_code: taskCode.value, key })
    downloadBlob(response.data, parseFilename(String(response.headers?.['content-disposition'] || '')) || fallback)
  } catch (error: any) {
    errorMessage.value = displayErrorMessage(error, translate('platform.downloadFailed'))
  }
}
function parseCsv(text: string): Array<Record<string, string>> {
  const lines = text.split(/\r?\n/).filter(line => line.trim())
  if (lines.length < 2) return []
  const parseLine = (line: string) => {
    const values: string[] = []
    let value = '', quoted = false
    for (let index = 0; index < line.length; index += 1) {
      const char = line[index]
      if (char === '"' && line[index + 1] === '"' && quoted) { value += '"'; index += 1 }
      else if (char === '"') quoted = !quoted
      else if (char === ',' && !quoted) { values.push(value); value = '' }
      else value += char
    }
    values.push(value)
    return values
  }
  const headers = parseLine(lines[0])
  return lines.slice(1).map(line => {
    const values = parseLine(line)
    return Object.fromEntries(headers.map((header, index) => [header, values[index] || '']))
  })
}
async function openTrajectory() {
  if (!artifactKeys.value.includes('trajectory_csv')) return
  try {
    const response = await downloadBackendJobArtifact(props.jobId, { task_code: taskCode.value, key: 'trajectory_csv' })
    trajectoryRows.value = parseCsv(await response.data.text())
    trajectoryDialog.value = true
  } catch (error: any) {
    errorMessage.value = displayErrorMessage(error, translate('platform.failedToLoadResults'))
  }
}
const taskCode = computed(() => {
  const tasks = metadata.value?.tasks || []
  return tasks.find(task => task.task_code === 'surfgen_inference')?.task_code
    || tasks.find(task => task.task_code === props.jobType)?.task_code
    || (props.jobType === 'property_optimization' ? 'property_optimization' : 'molecule_generation')
})
function schedulePolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = undefined
  if (!['pending', 'queued', 'running', 'blocked'].includes(jobStatus.value)) return
  pollTimer = setTimeout(() => { void load() }, 2000)
}
function normalizeResult(item: BackendSmallMoleculeResult): ResultRow {
  return { id: item.id, result_id: item.id, source_index: item.extra?.source_index, smiles: item.smiles || item.smiles_canonical, smiles_canonical: item.smiles_canonical, edit_preview: item.extra?.edit_preview, extra: item.extra || {} }
}
async function loadPostprocessing() {
  if (!props.jobId) return
  const response = await getBackendJob(props.jobId, { summary: true })
  metadata.value = response.data
  jobStatus.value = response.data.status
  const sourceId = props.sourceJobId || response.data.params?.postprocessing?.source_job_id || ''
  resolvedSourceJobId.value = sourceId
  if (sourceId) sourceJob.value = (await getBackendJob(sourceId, { summary: true })).data
}
async function load() {
  if (!props.jobId) return
  const revision = ++requestRevision.value
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  errorMessage.value = ''
  try {
    if (isPostprocessing.value) {
      await loadPostprocessing()
      return
    }
    const [jobResponse, resultResponse] = await Promise.all([
      getBackendJob(props.jobId, { summary: true, signal: controller.signal }),
      listBackendJobResults(props.jobId, { limit: pageSize.value, offset: (currentPage.value - 1) * pageSize.value, search: searchQuery.value.trim(), sort_by: 'smiles', descending: false, signal: controller.signal }),
    ])
    if (revision !== requestRevision.value) return
    metadata.value = jobResponse.data
    jobStatus.value = jobResponse.data.status
    const task = (jobResponse.data.tasks || []).find(item => item.task_code === 'surfgen_inference') || (jobResponse.data.tasks || []).find(item => item.task_code === props.jobType)
    const payload = task?.output_payload || {}
    engine.value = String(payload.engine || task?.input_payload?.engine || jobResponse.data.params?.[props.jobType]?.engine || '—')
    artifactKeys.value = Object.keys(payload).filter(key => Boolean(payload[key]))
    quantityWarning.value = generationQuantityWarning(payload)
    total.value = Number(resultResponse.headers['x-total-count'] || 0)
    rows.value = (resultResponse.data || []).map(normalizeResult)
  } catch (error: any) {
    if (revision !== requestRevision.value || controller?.signal.aborted) return
    errorMessage.value = displayErrorMessage(error, translate('platform.failedToLoadResults'))
  } finally {
    if (revision === requestRevision.value) {
      loading.value = false
      schedulePolling()
    }
  }
}

watch(() => [props.jobId, props.jobType, props.candidateSetId, props.sessionId, props.sourceJobId], () => {
  currentPage.value = 1
  rows.value = []
  metadata.value = null
  sourceJob.value = null
  postprocessingOpen.value = false
  resolvedSourceJobId.value = props.sourceJobId
  void load()
}, { immediate: true })
watch([pageSize, currentPage], () => { if (!isPostprocessing.value) void load() })
watch(searchQuery, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    if (!isPostprocessing.value) void load()
  }, 250)
})
onBeforeUnmount(() => {
  requestRevision.value++
  controller?.abort()
  clearTimeout(pollTimer)
  clearTimeout(searchTimer)
})
</script>

<style scoped>
.agent-result-workspace :is(button, input, select):focus-visible { outline: 2px solid var(--action-primary); outline-offset: 2px; }
</style>
