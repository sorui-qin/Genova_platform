<template>
  <AppFrame>
    <div class="module-workbench flex flex-col">
      <PageHeader :title="$t('platform.tarpassPostprocessing')" :help="{ path: '/help', query: { article: 'tarpass' } }" :help-label="$t('platform.operationGuide')"><Button v-if="!panelOpen" variant="outline" @click="panelOpen = true">{{ $t('platform.openPanel') }}</Button></PageHeader>
      <p v-if="restoring" role="status" class="shrink-0 border-b px-4 py-2 text-sm text-primary">{{ $t('platform.loading') }}</p>
      <WorkspaceLayout v-model:open="panelOpen" :title="$t('platform.parameters')" resizable>
        <template #panel-header><WorkspacePanelTabs v-model="auxiliaryTab" :label="L('操作面板', 'Controls')" :tabs="[{ value: 'parameters', label: $t('platform.parameters') }, { value: 'assistant', label: L('助手', 'Assistant') }]" @update:model-value="value => { if (value === 'assistant') assistantOpened = true }" /></template>
        <div class="flex h-full min-h-0 flex-col">
          <div class="workbench-toolbar justify-between">
            <h2>{{ $t('platform.sourceMolecules') }}<span v-if="ready" class="ml-2 font-normal tabular-nums text-muted-foreground">{{ total }}</span></h2>
            <Input v-model="search" class="w-64 max-w-full" :disabled="!ready || resultsLoading || Boolean(resultsError)" :placeholder="$t('platform.ppSearchSource')" :aria-label="$t('platform.ppSearchSource')" />
          </div>
          <FeedbackState v-if="resultsError" class="flex-1" kind="error" :title="$t('platform.ppSourceLoadFailed')" :description="resultsError" />
          <FeedbackState v-else-if="!ready" class="flex-1" :title="$t('platform.selectACompletedGeneration')" />
          <FeedbackState v-else-if="resultsLoading" class="flex-1" kind="loading" :title="$t('platform.loading')" />
          <div v-else class="workbench-result-body">
            <div class="workbench-table-area">
              <div class="workbench-table-scroll">
                <table>
                  <thead><tr><th>#</th><th>{{ $t('platform.structure') }}</th><th>SMILES</th><th v-for="key in sourceColumns" :key="key">{{ key }}</th></tr></thead>
                  <tbody>
                    <tr v-if="!filteredRows.length"><td :colspan="sourceColumns.length + 3" class="text-center text-muted-foreground">{{ $t('platform.ppNoResults') }}</td></tr>
                    <tr v-for="row in pagedRows" :key="row.id" class="hover:bg-slate-50">
                      <td>{{ row.index }}</td>
                      <td><MoleculeViewer :smiles="row.smiles" width="180px" height="130px" :loading-text="$t('platform.loading')" :error-text="$t('platform.failedToRenderCandidate')" /></td>
                      <td><p class="max-w-72 truncate font-mono" :title="row.smiles">{{ row.smiles }}</p></td>
                      <td v-for="key in sourceColumns" :key="key" class="whitespace-nowrap text-right">{{ row.metrics[key] ?? '—' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="workbench-pagination">
                <span class="tabular-nums">{{ page + 1 }} / {{ Math.max(1, Math.ceil(total / 20)) }}</span>
                <div class="flex gap-2"><Button size="sm" variant="outline" :disabled="page === 0" @click="page--">{{ $t('platform.previous') }}</Button><Button size="sm" variant="outline" :disabled="(page + 1) * 20 >= total" @click="page++">{{ $t('platform.next') }}</Button></div>
              </div>
            </div>
          </div>
        </div>
        <template #auxiliary>
          <ModuleAssistantPanel v-if="assistantOpened" v-show="auxiliaryTab === 'assistant'" ref="assistantPanel" module="tarpass" :context="assistantContext" :apply="applyAssistant" />
          <div v-show="auxiliaryTab === 'parameters'" class="workbench-form">
            <section class="workbench-section">
              <h2>{{ $t('platform.ppSourceContext') }}</h2>
              <label class="block text-sm">{{ $t('platform.sourceGenerationTask') }}
                <select v-model="sourceId" :disabled="restoring" class="mt-2 h-9 w-full rounded-md border border-input bg-background px-3 text-sm" @change="chooseSource">
                  <option value="">{{ $t('platform.selectACompletedGeneration') }}</option>
                  <option v-for="job in sources" :key="job.id" :value="job.id">{{ job.params.job_name || job.params.name || job.id.slice(0, 8) }} · {{ $t(job.job_type === 'property_optimization' ? 'platform.leadOptimization' : 'platform.deNovoGeneration') }} · {{ new Date(job.created_at).toLocaleString($i18n.locale) }}</option>
                </select>
              </label>
              <Button v-if="hasMore" variant="outline" size="sm" :disabled="loading" @click="loadSources">{{ $t('platform.loadMoreTasks') }}</Button>
              <p v-if="!sources.length && !loading" class="text-sm text-muted-foreground">{{ $t('platform.noCompletedGenerationTasks') }} <router-link to="/molgen" class="text-primary">{{ $t('platform.generateMolecules') }}</router-link></p>
              <p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
              <dl v-if="task" class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-t pt-2 text-xs">
                <dt class="text-muted-foreground">{{ $t('platform.sourceMolecules') }}</dt><dd class="tabular-nums">{{ task.output_payload.result_count ?? '—' }}</dd>
                <dt class="text-muted-foreground">{{ $t('platform.proteinContext') }}</dt><dd class="break-words">{{ revisedContext?.name || task.input_payload.structure_context?.name || task.input_payload.structure_context?.id || '—' }}</dd>
                <dt class="text-muted-foreground">{{ $t('platform.referenceLigandLabel') }}</dt><dd>{{ referenceAvailable === null ? '—' : $t(referenceAvailable ? 'platform.available' : 'platform.unavailable') }}</dd>
              </dl>
            </section>
            <TarPassPanel v-if="ready && !restoring" ref="tarpassPanel" :key="`${sourceId}:${restoreJob?.id || ''}`" :source-job-id="sourceId" :source-job-name="selectedSource?.params.job_name || selectedSource?.params.name" :restore-job="restoreJob || undefined" :source-job="selectedSource" :protein-context-id="String(route.query.protein_context_id || '') || undefined" mode="submit" :bind-assistant="bindAssistant" @reference-availability="referenceAvailable = $event" />
          </div>
        </template>
      </WorkspaceLayout>
    </div>
  </AppFrame>
</template>
<script setup lang="ts">
import '@/assets/module-workbench.css'
import WorkspacePanelTabs from '@/components/workbench/WorkspacePanelTabs.vue'
import FeedbackState from '@/components/workbench/FeedbackState.vue'

import PageHeader from '@/components/workbench/PageHeader.vue'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import ModuleAssistantPanel from '@/pages/agent/components/ModuleAssistantPanel.vue'
import type { ModuleSuggestion, ModuleContext } from '@/api/moduleAssistant'
import { defaultPrefilters } from '@/utils/tarpassDefaults'
import i18n, { translate } from '@/i18n'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { clearMoleculeRenderer } from '@/utils/moleculeRenderer'
import { useRoute, useRouter } from 'vue-router'
import AppFrame from '@/components/Layout/appFrame.vue'
import TarPassPanel from '@/components/molecule/TarPassPanel.vue'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import { Input } from '@/components/ui/input'
import { getProteinContext } from '@/api/proteinContext'
import type { ProteinContext } from '@/types/proteinContext'
import { Button } from '@/components/ui/button'
import { listBackendJobs, getBackendJob, listBackendJobResults, type BackendJobListOut, type BackendJobOut, type BackendJobTask } from '@/api/genovaBackend'
import { displayErrorMessage } from '@/utils/requestError'
const route = useRoute(), router = useRouter()
const L = (zh: string, en: string) => i18n.global.locale.value.startsWith('zh') ? zh : en
const auxiliaryTab = ref('parameters'), assistantOpened = ref(false)
const tarpassPanel = ref<InstanceType<typeof TarPassPanel>>()
const assistantPanel = ref<InstanceType<typeof ModuleAssistantPanel>>()
const assistantContext = computed<ModuleContext>(() => tarpassPanel.value?.assistantContext || { engine: 'tarpass', source_job_id: sourceId.value || undefined, form: { prefilters: defaultPrefilters(), key_interactions: [] } })
async function applyAssistant(suggestion: ModuleSuggestion) {
  if (!tarpassPanel.value || restoring.value) throw new Error(L('请先选择源任务并等待表单加载。', 'Select a source task and wait for the form.'))
  await tarpassPanel.value.applyAssistant(suggestion)
}
async function bindAssistant(jobId: string) { await assistantPanel.value?.bindToJob(jobId) }
const panelOpen = ref(true)
const sources = ref<BackendJobListOut[]>([])
const sourceId = ref(route.query.restore_job_id ? '' : String(route.query.source_job_id || ''))
const restoreJob = ref<BackendJobOut | null>(null)
const restoring = ref(Boolean(route.query.restore_job_id))
const task = ref<BackendJobTask | null>(null)
const revisedContext = ref<ProteinContext | null>(null)
const referenceAvailable = ref<boolean | null>(null)
const selectedSource = ref<BackendJobOut | null>(null)
const sourceRows = ref<Array<{ id: string; index: number; smiles: string; metrics: Record<string, string | number | boolean> }>>([])
const resultsLoading = ref(false), resultsError = ref('')
const search = ref(''), page = ref(0)
const sourceColumns = computed(() => [...new Set(sourceRows.value.flatMap(row => Object.keys(row.metrics)))])
const total = ref(0), appliedSearch = ref('')
const filteredRows = computed(() => sourceRows.value)
const pagedRows = computed(() => sourceRows.value)
let searchTimer: ReturnType<typeof setTimeout> | undefined
let rowRevision = 0
let rowController: AbortController | undefined
watch(search, value => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { appliedSearch.value = value.trim() }, 250) })
watch(appliedSearch, () => { page.value = 0 })
watch([page, appliedSearch], () => { void loadSourceRows() })
const ready = ref(false), loading = ref(false), hasMore = ref(true)
const error = ref('')
let selection = 0
let active = true
const sourcePages = ['molecule_generation', 'property_optimization'].map(job_type => ({ job_type, offset: 0, hasMore: true }))
async function loadSources() {
  if (loading.value) return
  loading.value = true; error.value = ''
  const results = await Promise.allSettled(sourcePages.filter(page => page.hasMore).map(async page => {
    const jobs = (await listBackendJobs({ job_type: page.job_type, status: 'succeeded', offset: page.offset, limit: 50 })).data
    page.offset += jobs.length; page.hasMore = jobs.length === 50
    sources.value.push(...jobs.filter(job => !sources.value.some(existing => existing.id === job.id)))
  }))
  for (const result of results) {
    if (result.status === 'rejected') error.value = displayErrorMessage(result.reason)
  }
  sources.value.sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
  hasMore.value = sourcePages.some(page => page.hasMore)
  loading.value = false
}
function chooseSource() { restoreJob.value = null; router.replace({ path: '/postprocessing', query: sourceId.value ? { source_job_id: sourceId.value } : {} }) }
watch(sourceId, async value => {
  const token = ++selection
  rowRevision++; rowController?.abort(); clearTimeout(searchTimer); appliedSearch.value = ''; total.value = 0
  const id = String(value || '')
  task.value = null; selectedSource.value = null; revisedContext.value = null; ready.value = false; referenceAvailable.value = null; error.value = ''
  sourceRows.value = []; search.value = ''; page.value = 0; resultsError.value = ''; resultsLoading.value = false
  if (!id) return
  try {
    const job = (await getBackendJob(id)).data
    if (token !== selection) return
    if (route.query.protein_context_id) {
      const context = (await getProteinContext(String(route.query.protein_context_id))).data
      if (token !== selection) return
      revisedContext.value = context
    }
    if (!['molecule_generation', 'property_optimization'].includes(job.job_type) || job.status !== 'succeeded') throw new Error(translate('platform.aCompletedGenerationWithMoleculesIsRequired'))
    const generated = job.tasks.find(item => item.task_code === job.job_type && item.status === 'succeeded')
    if (!generated?.output_payload?.generated_sdf && !generated?.output_payload?.output_csv) throw new Error(translate('platform.aCompletedGenerationWithMoleculesIsRequired'))
    if (!sources.value.some(item => item.id === id)) sources.value.unshift(job)
    selectedSource.value = job; task.value = generated; ready.value = true
    await loadSourceRows()
  } catch (exc: any) { if (token === selection) error.value = displayErrorMessage(exc) }
}, { immediate: true, flush: 'sync' })
async function loadSourceRows() {
  if (!task.value || !sourceId.value) return
  const current = ++rowRevision, source = sourceId.value
  rowController?.abort(); rowController = new AbortController()
  resultsLoading.value = true; resultsError.value = ''
  try {
    const response = await listBackendJobResults(source, { task_code: task.value.task_code, limit: 20, offset: page.value * 20,
      search: appliedSearch.value, signal: rowController.signal })
    if (current !== rowRevision || source !== sourceId.value || !active) return
    total.value = Number(response.headers['x-total-count'] || 0)
    sourceRows.value = response.data.map((row, index) => ({
      id: row.id, index: page.value * 20 + index + 1, smiles: row.smiles,
      metrics: Object.fromEntries(Object.entries({ ...row.extra, ...row.extra?.raw }).filter(([key, value]) =>
        !/^(id|.*_id|.*_index|target[123])$/i.test(key) &&
        (typeof value === 'number' || typeof value === 'boolean' || (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))))
      )) as Record<string, string | number | boolean>,
    }))
  } catch (exc: any) {
    if (current === rowRevision && !rowController?.signal.aborted) resultsError.value = displayErrorMessage(exc)
  } finally { if (current === rowRevision) resultsLoading.value = false }
}
onBeforeUnmount(() => { active = false; selection++; rowRevision++; rowController?.abort(); clearTimeout(searchTimer); clearMoleculeRenderer() })
async function initialize() {
  await loadSources()
  if (!active) return
  const id = String(route.query.restore_job_id || '')
  if (!id) return
  try {
    const job = (await getBackendJob(id)).data
    if (!active) return
    if (job.job_type !== 'molecule_postprocessing' || !job.params.postprocessing?.source_job_id) {
      throw new Error(translate('platform.restoreTaskUnavailable'))
    }
    restoreJob.value = job
    sourceId.value = job.params.postprocessing.source_job_id
  } catch (exc: any) {
    error.value = `${translate('platform.restoreTaskUnavailable')} ${displayErrorMessage(exc)}`
  } finally {
    restoring.value = false
  }
}
onMounted(initialize)
</script>
<route lang="yaml">
meta:
  layout: blank
</route>
