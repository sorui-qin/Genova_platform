<template>
  <AppFrame>
    <PageHeader :title="t('platform.continueWork')" :help="{ path: '/help', query: { article: 'workflow-overview' } }" :help-label="t('platform.operationGuide')">
      <Button variant="outline" as-child><RouterLink to="/agent"><Bot class="h-4 w-4" aria-hidden="true" />{{ t('platform.openAssistant') }}</RouterLink></Button>
      <DropdownMenu><DropdownMenuTrigger as-child><Button><Plus class="h-4 w-4" aria-hidden="true" />{{ t('platform.newTask') }}<ChevronDown class="h-4 w-4" aria-hidden="true" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" class="w-60"><DropdownMenuItem v-for="(path, type) in toolRoutes" :key="type" as-child><RouterLink :to="path">{{ jobTypeLabel(type) }}</RouterLink></DropdownMenuItem></DropdownMenuContent></DropdownMenu>
    </PageHeader>
    <div class="workbench-page mx-auto flex max-w-[1600px] flex-col gap-6">
      <section class="workbench-panel overflow-hidden" :aria-label="t('platform.taskList')">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b px-4 pt-4">
          <div class="flex flex-wrap gap-4" role="tablist" :aria-label="t('platform.taskList')">
            <button v-for="item in tabs" :id="`tab-${item.key}`" :key="item.key" type="button" role="tab" :aria-selected="tab === item.key" aria-controls="dashboard-tasks" class="task-tab" :class="{ selected: tab === item.key }" @click="tab = item.key" @keydown.right.prevent="moveTab(1)" @keydown.left.prevent="moveTab(-1)">{{ item.label }}<span class="ml-2 rounded-md bg-secondary px-2 py-0.5 text-xs tabular-nums">{{ item.count }}</span></button>
          </div>
          <div class="mb-3 flex gap-2"><Button variant="ghost" size="icon" :disabled="loading" :aria-label="t('platform.refresh')" @click="load"><RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" /></Button><Button variant="ghost" size="sm" as-child><RouterLink to="/results">{{ t('platform.allTasksResults') }}<ArrowRight class="h-4 w-4" aria-hidden="true" /></RouterLink></Button></div>
        </div>
        <div id="dashboard-tasks" role="tabpanel" :aria-labelledby="`tab-${tab}`" class="min-h-[320px]">
          <FeedbackState v-if="error" kind="error" :title="t('platform.taskLoadError')" :description="error"><Button variant="outline" @click="load">{{ t('platform.retry') }}</Button></FeedbackState>
          <FeedbackState v-else-if="loading && !jobs.length && !sessions.length" kind="loading" :title="t('platform.loading')" />
          <FeedbackState v-else-if="!items.length" :title="tab === 'attention' ? t('platform.noAttention') : t('platform.noTasks')" :description="t(tab === 'attention' ? 'platform.noAttentionHint' : tab === 'running' ? 'platform.noRunningHint' : 'platform.noCompletedHint')"><Button variant="outline" as-child><RouterLink :to="tab === 'completed' ? '/results' : '/protein-preparation'">{{ t(tab === 'completed' ? 'platform.chooseTask' : 'platform.newTask') }}</RouterLink></Button></FeedbackState>
          <div v-else class="overflow-x-auto">
            <table class="w-full min-w-[620px] text-left text-sm"><thead class="bg-secondary text-xs text-muted-foreground"><tr><th class="w-[45%] px-6 py-3">{{ t('platform.task') }}</th><th class="px-4 py-3">{{ t('platform.stage') }}</th><th class="px-4 py-3">{{ t('platform.updated') }}</th><th class="px-6 py-3 text-right">{{ t('platform.details') }}</th></tr></thead>
              <tbody><tr v-for="item in items" :key="item.id" class="border-t hover:bg-secondary"><td class="px-6 py-4"><div class="max-w-[560px] truncate font-medium" :title="item.name">{{ item.name }}</div><div class="mt-1 text-xs text-muted-foreground">{{ item.module }}</div></td><td class="px-4 py-4"><span class="status-badge" :class="statusTone(item.status)">{{ item.stage }}</span></td><td class="whitespace-nowrap px-4 py-4 text-xs text-muted-foreground">{{ item.updated ? new Date(item.updated).toLocaleString(locale) : '—' }}</td><td class="px-6 py-4 text-right"><Button variant="outline" size="sm" as-child><RouterLink :to="item.to">{{ item.action }}<ArrowUpRight class="h-4 w-4" aria-hidden="true" /></RouterLink></Button></td></tr></tbody>
            </table>
          </div>
        </div>
      </section>
      <section class="workbench-panel p-4">
        <header class="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2>{{ t('platform.recentResources') }}</h2><p class="mt-1 text-xs text-muted-foreground">{{ t('platform.recentResourcesHint') }}</p></div><Button variant="ghost" size="sm" as-child><RouterLink to="/datacenter">{{ t('platform.dataCenter') }}<ArrowRight class="h-4 w-4" aria-hidden="true" /></RouterLink></Button></header>
        <FeedbackState v-if="resourceError" kind="error" :title="t('platform.resourceError')" :description="resourceError"><Button variant="outline" @click="loadResources">{{ t('platform.retry') }}</Button></FeedbackState>
        <FeedbackState v-else-if="resourcesLoading" kind="loading" :title="t('platform.loading')" />
        <p v-else-if="!resources.length" class="py-3 text-sm text-muted-foreground">{{ t('platform.noResourcesHint') }}</p>
        <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><article v-for="resource in resources" :key="resource.id" class="flex min-w-0 items-center gap-3 rounded-lg border p-3"><FileBox class="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" /><div class="min-w-0 flex-1"><p class="truncate text-sm font-medium" :title="resource.name">{{ resource.name }}</p><p class="mt-1 text-xs text-muted-foreground">{{ new Date(resource.updated_at).toLocaleDateString(locale) }}</p></div><Button variant="ghost" size="sm" as-child><RouterLink :to="resource.to">{{ resource.reusable ? t('platform.reuseResource') : t('platform.openResource') }}</RouterLink></Button></article></div>
      </section>
      <RouterLink to="/help" class="flex items-center gap-2 self-start text-sm text-muted-foreground hover:text-primary"><BookOpen class="h-4 w-4" aria-hidden="true" />{{ t('platform.usageGuide') }}<ArrowRight class="h-4 w-4" aria-hidden="true" /></RouterLink>
    </div>
  </AppFrame>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, ArrowUpRight, Bot, BookOpen, ChevronDown, FileBox, Plus, RefreshCw } from 'lucide-vue-next'
import AppFrame from '@/components/Layout/appFrame.vue'
import PageHeader from '@/components/workbench/PageHeader.vue'
import FeedbackState from '@/components/workbench/FeedbackState.vue'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { listAgentSessions, listBackendDatasets, type BackendJobListOut, type BackendDataset } from '@/api/genovaBackend'
import { subscribeJobList } from '@/utils/jobListPoller'
import { requestErrorMessage, displayErrorMessage } from '@/utils/requestError'
import { activeJobStatuses, resultRoutes, toolRoutes, jobTitle, jobTypeLabel, statusTone, sessionPhaseLabel } from '@/utils/taskPresentation'
import { useWorkspaceState } from '@/composables/useWorkspace'
import { statusLabel } from '@/i18n'
const { t, locale } = useI18n()
const { tab } = useWorkspaceState('dashboard', () => '', { tab: 'attention' })
const jobs = ref<BackendJobListOut[]>([]), sessions = ref<Array<{id: string; goal: string; phase: string}>>([]), datasets = ref<BackendDataset[]>([])
const loading = ref(false), error = ref(''), resourcesLoading = ref(false), resourceError = ref('')
const attentionPhases = ['awaiting_upload', 'awaiting_selection', 'awaiting_site', 'awaiting_preparation_approval', 'ready_for_planning', 'awaiting_workflow_approval', 'failed']
const attention = computed(() => [
  ...sessions.value.filter(s => attentionPhases.includes(s.phase)).map(s => ({ id: s.id, name: s.goal || t('agent.session.newSession'), module: t('agent.title'), status: s.phase, stage: sessionPhaseLabel(s.phase), updated: '', action: t(s.phase.includes('_approval') ? 'platform.review' : 'platform.continue'), to: { path: '/agent', query: { session_id: s.id } } })),
  ...jobs.value.filter(j => ['failed', 'partial_succeeded', 'blocked'].includes(j.status)).map(j => itemForJob(j)),
])
function itemForJob(job: BackendJobListOut) {
  const ready = ['succeeded', 'partial_succeeded'].includes(job.status)
  return { id: job.id, name: jobTitle(job), module: jobTypeLabel(job.job_type), status: job.status, stage: job.summary?.execution_stage ? t(`platform.execution_${job.summary.execution_stage}`, statusLabel(job.status)) : statusLabel(job.status), updated: job.updated_at, action: t(ready ? 'platform.viewResults' : 'platform.viewDetails'), to: ready && resultRoutes[job.job_type] ? { path: resultRoutes[job.job_type], query: { job_id: job.id } } : job.job_type === 'protein_preparation' && ready ? { path: '/protein-preparation', query: { restore_job_id: job.id } } : { path: '/results', query: { job_id: job.id } } }
}
const running = computed(() => jobs.value.filter(j => activeJobStatuses.includes(j.status) && j.status !== 'blocked').map(itemForJob))
const completed = computed(() => jobs.value.filter(j => ['succeeded', 'partial_succeeded'].includes(j.status)).map(itemForJob))
const tabs = computed(() => [{ key: 'attention', label: t('platform.needsAttention'), count: attention.value.length }, { key: 'running', label: t('platform.running'), count: running.value.length }, { key: 'completed', label: t('platform.recentlyCompleted'), count: completed.value.length }])
const items = computed(() => (tab.value === 'attention' ? attention.value : tab.value === 'running' ? running.value : completed.value).slice(0, 12))
const resources = computed(() => datasets.value.slice(0, 6).map(d => {
  const reusable = d.files.some(f => /\.(pdb|cif|mmcif)$/i.test(f.original_filename))
  return { ...d, reusable, to: reusable ? { path: '/protein-preparation', query: { protein_dataset_id: d.id } } : { path: '/datacenter', query: { dataset_id: d.id } } }
}))
let subscription: ReturnType<typeof subscribeJobList> | undefined, disposed = false
async function moveTab(delta: number) { tab.value = tabs.value[(tabs.value.findIndex(item => item.key === tab.value) + delta + tabs.value.length) % tabs.value.length].key; await nextTick(); document.getElementById(`tab-${tab.value}`)?.focus() }
// Jobs come from the poll shared with the layout notifications; sessions are refreshed with each job update.
function applyJobs(data: BackendJobListOut[]) {
  if (disposed) return
  loading.value = false; error.value = ''
  jobs.value = data.filter(j => !j.params.system_tags?.hidden_in_dashboard && !['virtual_screening', 'clip', 'micro'].includes(j.job_type)).sort((a,b) => b.updated_at.localeCompare(a.updated_at))
  void loadSessions()
}
async function loadSessions() {
  try { const result = await listAgentSessions(); if (!disposed) sessions.value = result.data }
  catch (e: any) { if (!disposed) error.value = requestErrorMessage(e) }
}
async function load() {
  loading.value = true; error.value = ''
  try { await subscription?.refresh() } finally { loading.value = false }
}
async function loadResources() {
  resourcesLoading.value = true; resourceError.value = ''
  try { const result = await listBackendDatasets({ limit: 200, summary: true }); if (!disposed) datasets.value = result.data.sort((a,b) => b.updated_at.localeCompare(a.updated_at)) }
  catch (e: any) { resourceError.value = displayErrorMessage(e) }
  finally { resourcesLoading.value = false }
}
onMounted(() => {
  loading.value = true
  subscription = subscribeJobList({ update: applyJobs, error: e => { if (!disposed) { loading.value = false; error.value = requestErrorMessage(e) } } })
  void loadResources()
})
onUnmounted(() => { disposed = true; subscription?.stop() })
</script>
<style scoped>
.task-tab { padding: 0 0 14px; min-height: 36px; border-bottom: 2px solid transparent; color: var(--text-secondary); }
.task-tab.selected { border-bottom-color: var(--action-primary); color: var(--action-primary); font-weight: 600; }
</style>
<route lang="yaml">
meta:
  layout: blank
</route>
