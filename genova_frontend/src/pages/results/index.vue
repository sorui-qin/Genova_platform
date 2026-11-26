<template>
  <AppFrame :task="summary"><div class="flex h-full min-h-0 flex-col">
    <PageHeader :title="$t('platform.allTasksResults')" :help="{ path: '/help', query: { article: 'tasks-results' } }" :help-label="$t('platform.operationGuide')"><Button variant="outline" :disabled="loading || deleting" @click="load">{{ $t('platform.refresh') }}</Button></PageHeader>
    <WorkspaceLayout v-model:open="detailsOpen" :title="$t('platform.taskStatus')">
      <div class="workbench-page flex min-h-full flex-col gap-4">
        <div class="workbench-panel overflow-hidden">
          <div class="workbench-toolbar">
            <label>{{ $t('platform.module') }}<select v-model="jobType" :disabled="deleting" @change="reset"><option value="">{{ $t('platform.allModules') }}</option><option v-for="(label, key) in modules" :key="key" :value="key">{{ label }}</option></select></label>
            <label>{{ $t('platform.status') }}<select v-model="status" :disabled="deleting" @change="reset"><option value="">{{ $t('platform.allStatuses') }}</option><option v-for="item in statuses" :key="item" :value="item">{{ statusLabel(item) }}</option></select></label>
            <label class="min-w-40 flex-1">{{ $t('platform.searchTasks') }}<input v-model="search" type="search" class="h-9 rounded-lg border bg-card px-3" /></label>
            <Button variant="outline" class="text-destructive" :disabled="loading || deleting || !selectedIds.length" @click="deleteJobs(selectedIds)">{{ $t('task.批量删除') }} ({{ selectedIds.length }})</Button>
          </div>
          <FeedbackState v-if="error" kind="error" :title="$t('platform.taskLoadError')" :description="error"><Button variant="outline" @click="load">{{ $t('platform.retry') }}</Button></FeedbackState>
          <FeedbackState v-if="loading && !jobs.length" kind="loading" :title="$t('platform.loading')" />
          <div v-else-if="filteredJobs.length" class="overflow-x-auto"><table class="w-full min-w-[900px] text-left text-sm">
            <thead class="bg-secondary text-xs text-muted-foreground"><tr><th class="p-4"><input v-model="allSelected" type="checkbox" :indeterminate="selectedIds.length > 0 && !allSelected" :disabled="loading || deleting || !selectableJobs.length" :aria-label="$t('platform.selectCurrentPage')" class="h-4 w-4"></th><th class="p-4">{{ $t('platform.task') }}</th><th class="p-4">{{ $t('platform.module') }}</th><th class="p-4">{{ $t('platform.status') }}</th><th class="p-4">{{ $t('platform.updated') }}</th><th class="p-4">{{ $t('platform.details') }}</th></tr></thead>
            <tbody><tr v-for="job in filteredJobs" :key="job.id" class="border-t hover:bg-secondary" :class="{ 'bg-accent': selectedId === job.id && detailsOpen }">
              <td class="p-4"><input v-model="selectedIds" type="checkbox" :value="job.id" :disabled="loading || deleting || !canDelete(job)" :aria-label="jobTitle(job)" class="h-4 w-4"></td>
              <td class="p-4"><button class="max-w-72 truncate text-left font-medium text-primary hover:underline" @click="showDetails(job.id)">{{ jobTitle(job) }}</button><p class="mt-1 font-mono text-xs text-muted-foreground">{{ job.id.slice(0, 8) }}</p></td>
              <td class="min-w-40 p-4">{{ modules[job.job_type] || job.job_type }}</td><td class="p-4"><span class="status-badge" :class="statusTone(job.status)">{{ statusLabel(job.status) }}</span></td><td class="whitespace-nowrap p-4 text-xs text-muted-foreground">{{ new Date(job.updated_at).toLocaleString($i18n.locale) }}</td>
              <td class="p-4"><div class="flex flex-wrap items-center gap-x-3 gap-y-2"><RouterLink v-if="routes[job.job_type] && ['succeeded', 'partial_succeeded'].includes(job.status)" :to="{ path: routes[job.job_type], query: { job_id: job.id } }" class="whitespace-nowrap text-primary hover:underline">{{ $t('platform.viewResults') }}</RouterLink><button class="whitespace-nowrap text-primary hover:underline" @click="showDetails(job.id)">{{ $t('platform.viewDetails') }}</button><button v-if="canDelete(job)" :disabled="loading || deleting" class="text-destructive disabled:opacity-50" @click="deleteJobs([job.id])">{{ $t('platform.delete') }}</button></div></td>
            </tr></tbody>
          </table></div>
          <FeedbackState v-else-if="!error" :title="$t(search ? 'platform.noMatchingTasks' : 'platform.noTasksFound')" :description="$t('platform.noCompletedHint')"><Button variant="outline" as-child><RouterLink to="/protein-preparation">{{ $t('platform.newTask') }}</RouterLink></Button></FeedbackState>
        </div>
        <div class="mt-auto flex items-center justify-end gap-3"><Button variant="outline" :disabled="loading || deleting || page === 0" @click="changePage(page - 1)">{{ $t('platform.previous') }}</Button><span class="text-xs text-muted-foreground">{{ $t('platform.page') }} {{ page + 1 }}</span><Button variant="outline" :disabled="loading || deleting || !hasMore" @click="changePage(page + 1)">{{ $t('platform.next') }}</Button></div>
      </div>
      <template #auxiliary>
        <FeedbackState v-if="detailLoading" kind="loading" :title="$t('platform.loading')" />
        <div v-else-if="selected" class="space-y-4">
          <h2 class="break-words">{{ jobTitle(selected) }}</h2><span class="status-badge" :class="statusTone(selected.status)">{{ statusLabel(selected.status) }}</span>
          <dl class="space-y-3 text-sm"><div><dt class="text-xs text-muted-foreground">{{ $t('platform.module') }}</dt><dd class="mt-1">{{ jobTypeLabel(selected.job_type) }}</dd></div><div><dt class="text-xs text-muted-foreground">{{ $t('platform.task') }} ID</dt><dd class="mt-1 break-all font-mono text-xs">{{ selected.id }}</dd></div></dl>
          <Button v-if="routes[selected.job_type] && ['succeeded', 'partial_succeeded'].includes(selected.status)" as-child class="w-full"><RouterLink :to="{path: routes[selected.job_type], query: {job_id: selected.id}}">{{ $t('platform.viewResults') }}</RouterLink></Button>
          <Button v-if="restoreRoutes[selected.job_type]" variant="outline" as-child class="w-full"><RouterLink :to="{ path: restoreRoutes[selected.job_type], query: { restore_job_id: selected.id } }">{{ $t('platform.restoreTaskParameters') }}</RouterLink></Button>
          <button v-if="selected.params.postprocessing?.source_job_id" class="text-sm text-primary" @click="showSource(selected.params.postprocessing.source_job_id)">{{ $t('platform.sourceGeneration') }}</button>
          <div v-for="task in selected.tasks || []" :key="task.id" class="space-y-2 border-t pt-4 text-sm"><p>{{ jobTypeLabel(task.task_code) }}</p><span class="status-badge" :class="statusTone(task.status)">{{ statusLabel(task.status) }}</span><pre v-if="task.error_message" class="max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs text-destructive">{{ task.error_message }}</pre></div>
        </div>
      </template>
    </WorkspaceLayout>
    <Dialog v-model:open="deletionOpen">
      <DialogContent class="max-h-[85vh] max-w-3xl overflow-y-auto" @interact-outside="event => { if (deleting) event.preventDefault() }" @escape-key-down="event => { if (deleting) event.preventDefault() }">
        <DialogHeader><DialogTitle>{{ $t('platform.deletionTitle') }}</DialogTitle><DialogDescription>{{ $t('platform.deletionDescription') }}</DialogDescription></DialogHeader>
        <FeedbackState v-if="deletionError" kind="error" :title="$t('platform.deleteFailed')" :description="deletionError" />
        <template v-if="deletionPreview">
          <div v-for="group in deletionGroups" :key="group.kind" class="space-y-2"><h3 class="font-medium">{{ group.label }} ({{ group.items.length }})</h3><ul class="max-h-36 overflow-auto text-sm"><li v-for="item in group.items" :key="item.id" class="break-all py-1">{{ item.name }} <span class="font-mono text-xs text-muted-foreground">{{ item.id }}</span></li></ul></div>
          <div class="space-y-2"><h3 class="font-medium">{{ $t('platform.deletionFiles') }} ({{ deletionPreview.files.length }}) · {{ formatBytes(deletionPreview.reclaimable_bytes) }}</h3><ul class="max-h-48 overflow-auto text-xs"><li v-for="file in deletionPreview.files.slice(filePage * 50, (filePage + 1) * 50)" :key="`${file.kind}/${file.object_id}/${file.name}`" class="break-all py-1">{{ file.kind }}/{{ file.object_id }}/{{ file.name }} · {{ formatBytes(file.size_bytes) }}</li></ul><div v-if="deletionPreview.files.length > 50" class="flex items-center gap-3"><Button variant="outline" :disabled="filePage === 0" @click="filePage--">{{ $t('platform.previous') }}</Button><span>{{ filePage + 1 }} / {{ Math.ceil(deletionPreview.files.length / 50) }}</span><Button variant="outline" :disabled="(filePage + 1) * 50 >= deletionPreview.files.length" @click="filePage++">{{ $t('platform.next') }}</Button></div></div>
          <div v-if="deletionPreview.retained.length"><h3 class="font-medium">{{ $t('platform.deletionRetained') }}</h3><ul class="max-h-36 overflow-auto text-sm"><li v-for="item in deletionPreview.retained" :key="item.id" class="break-all py-1">{{ item.name }} <span class="font-mono text-xs">{{ item.id }}</span><p v-for="file in item.files" :key="file.name" class="pl-3 text-xs text-muted-foreground">{{ file.name }} · {{ formatBytes(file.size_bytes) }}</p></li></ul></div>
          <div v-if="deletionPreview.blocked.length" class="text-sm text-destructive"><p>{{ $t('platform.deletionBlocked') }}</p><ul><li v-for="(item, index) in deletionPreview.blocked" :key="index" class="break-all">{{ item.kind }} · {{ item.id }}</li></ul></div>
        </template>
        <DialogFooter><Button variant="outline" :disabled="deleting" @click="deletionOpen = false">{{ $t('platform.deletionCancel') }}</Button><Button variant="destructive" :disabled="deleting || !deletionPreview || !!deletionPreview.blocked.length" @click="confirmDelete">{{ $t('platform.deletionConfirm') }}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div></AppFrame>
</template>
<script setup lang="ts">
import { translate, statusLabel } from '@/i18n'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { nonEmptyQueryValue, useQueryCleanup } from '@/utils/routeQuery'
import AppFrame from '@/components/Layout/appFrame.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import PageHeader from '@/components/workbench/PageHeader.vue'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import FeedbackState from '@/components/workbench/FeedbackState.vue'
import { useWorkspaceState } from '@/composables/useWorkspace'
import { jobTitle, jobTypeLabel, jobContextLabel, resultRoutes, toolRoutes, statusTone } from '@/utils/taskPresentation'
import { listBackendJobs, getBackendJob, previewBackendJobDeletion, confirmBackendJobDeletion, type JobDeletionPreview, type BackendJobOut, type BackendJobListOut } from '@/api/genovaBackend'
import { toast } from '@/components/ui/toast/use-toast'
import { displayErrorMessage } from '@/utils/requestError'
import { jobPollDelay } from '@/utils/jobListPoller'
import { readStoredUserInfo } from '@/utils/guestSession'
const router = useRouter(), route = useRoute()
// Unknown or empty query parameters are removed from the address bar.
useQueryCleanup(route, router, { job_id: nonEmptyQueryValue })
const modules = computed<Record<string, string>>(() => ({ molecule_generation: translate('platform.deNovoGeneration'), molecule_postprocessing: translate('platform.postprocessing'), protein_preparation: translate('platform.proteinPreparation'), property_optimization: translate('platform.leadOptimization') }))
const routes = resultRoutes, restoreRoutes = toolRoutes
const statuses = ['pending', 'queued', 'running', 'blocked', 'succeeded', 'partial_succeeded', 'failed', 'canceled']
const jobs = ref<BackendJobListOut[]>([]), selected = ref<BackendJobOut | null>(null)
const { jobType, status, page, selectedIds, selectedId, detailsOpen, search } = useWorkspaceState('tasks', () => '', { jobType: '', status: '', page: 0, selectedIds: [] as string[], selectedId: '', detailsOpen: false, search: '' })
const error = ref(''), loading = ref(false), hasMore = ref(false), deleting = ref(false), detailLoading = ref(false)
const filteredJobs = computed(() => jobs.value)
const summary = computed(() => selected.value ? { name: jobTitle(selected.value), stage: statusLabel(selected.value.status), context: jobContextLabel(selected.value), details: () => { detailsOpen.value = true } } : null)
const canDelete = (job: BackendJobListOut) => !['pending', 'queued', 'running', 'blocked'].includes(job.status)
const selectableJobs = computed(() => jobs.value.filter(canDelete))
const allSelected = computed({
  get: () => selectableJobs.value.length > 0 && selectableJobs.value.every(job => selectedIds.value.includes(job.id)),
  set: (checked: boolean) => { selectedIds.value = checked ? selectableJobs.value.map(job => job.id) : [] },
})
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(search, () => { clearTimeout(searchTimer); searchTimer = setTimeout(reset, 250) })
let timer: ReturnType<typeof setTimeout> | undefined, disposed = false, requestId = 0
let detailRequestId = 0, failures = 0
let controller: AbortController | undefined
async function load() {
  const id = ++requestId
  const owner = readStoredUserInfo()?.id
  const detailRevision = ++detailRequestId
  controller?.abort(); controller = new AbortController()
  if (timer) clearTimeout(timer)
  loading.value = true; error.value = ''
  try {
    const result = (await listBackendJobs({ job_type: jobType.value || undefined, status: status.value || undefined,
      search: search.value.trim() || undefined, limit: 51, offset: page.value * 50, signal: controller.signal })).data
    if (disposed || id !== requestId || readStoredUserInfo()?.id !== owner) return
    failures = 0
    hasMore.value = result.length > 50; jobs.value = result.slice(0, 50)
    selectedIds.value = selectedIds.value.filter(id => selectableJobs.value.some(job => job.id === id))
    loading.value = false
    if (detailsOpen.value && selected.value) {
      const selectedJobId = selected.value.id
      const detail = (await getBackendJob(selectedJobId, { summary: true, signal: controller.signal })).data
      if (disposed || id !== requestId || readStoredUserInfo()?.id !== owner) return
      if (detailRevision === detailRequestId && selected.value?.id === selectedJobId) selected.value = detail
    }
    if (!deleting.value && jobs.value.some(job => !canDelete(job))) timer = setTimeout(load, 5000)
  } catch (exc: any) {
    if (!disposed && id === requestId && readStoredUserInfo()?.id === owner) {
      error.value = displayErrorMessage(exc)
      failures++
      if (!deleting.value) timer = setTimeout(load, jobPollDelay(failures))
    }
  }
  finally { if (id === requestId) loading.value = false }
}
function changePage(value: number) { selectedIds.value = []; page.value = value; load() }
function reset() { changePage(0) }
const deletionOpen = ref(false), deletionPreview = ref<JobDeletionPreview | null>(null), deletionError = ref(''), filePage = ref(0)
let deletionIds: string[] = []
const deletionGroups = computed(() => [...new Set(deletionPreview.value?.objects.map(item => item.kind) || [])].map(kind => ({
  kind, label: translate(`platform.deletionKind_${kind}`), items: deletionPreview.value!.objects.filter(item => item.kind === kind),
})))
function formatBytes(bytes: number) { return `${(bytes / 1024 / 1024).toFixed(2)} MB` }
function deletionMessage(exc: any) {
  return displayErrorMessage(exc)
}
async function deleteJobs(selection: string[]) {
  if (loading.value || deleting.value) return
  deletionIds = selectableJobs.value.filter(job => selection.includes(job.id)).map(job => job.id)
  if (!deletionIds.length) return
  deletionOpen.value = true; deletionPreview.value = null; deletionError.value = ''; filePage.value = 0; deleting.value = true
  try { deletionPreview.value = (await previewBackendJobDeletion(deletionIds)).data }
  catch (exc: any) { deletionError.value = deletionMessage(exc) }
  finally { deleting.value = false }
}
async function confirmDelete() {
  if (!deletionPreview.value || deleting.value) return
  deleting.value = true; deletionError.value = ''
  try {
    const result = (await confirmBackendJobDeletion(deletionIds, deletionPreview.value.confirmation_token)).data
    const removed = result.deleted_job_ids
    selectedIds.value = selectedIds.value.filter(id => !removed.includes(id))
    if (selected.value && removed.includes(selected.value.id)) { detailsOpen.value = false; selected.value = null; selectedId.value = '' }
    deletionOpen.value = false
    toast({ title: translate('message.批量删除成功'), description: result.cleanup_status === 'pending' ? translate('platform.deletionPending') : String(removed.length) })
    await load()
    if (!error.value && !jobs.value.length && page.value > 0) { page.value--; await load() }
  } catch (exc: any) {
    deletionError.value = deletionMessage(exc)
    if (exc?.response?.data?.detail?.error_code === 'DELETE_PREVIEW_CHANGED') {
      deletionPreview.value = null
      try { deletionPreview.value = (await previewBackendJobDeletion(deletionIds)).data; filePage.value = 0; deletionError.value = translate('platform.deletionChanged') }
      catch (refreshError: any) { deletionError.value = deletionMessage(refreshError) }
    }
  } finally { deleting.value = false }
}
async function showSource(id: string) {
  try {
    const source = (await getBackendJob(id, { summary: true })).data
    await router.push({ path: routes[source.job_type], query: { job_id: id } })
  } catch (exc: any) { error.value = displayErrorMessage(exc) }
}
async function showDetails(id: string) {
  const revision = ++detailRequestId, owner = readStoredUserInfo()?.id
  selectedId.value = id; detailsOpen.value = true; detailLoading.value = true
  try { const result = (await getBackendJob(id, { summary: true })).data; if (!disposed && revision === detailRequestId && selectedId.value === id && readStoredUserInfo()?.id === owner) selected.value = result }
  catch (exc: any) { if (!disposed && revision === detailRequestId) error.value = displayErrorMessage(exc) }
  finally { detailLoading.value = false }
}
watch(() => route.query.job_id, id => { if (id) void showDetails(String(id)) })
function refreshOnConnection() { if (!disposed && !deleting.value) void load() }
onMounted(() => { window.addEventListener('online', refreshOnConnection); window.addEventListener('genova:connection-restored', refreshOnConnection); void load(); const id = String(route.query.job_id || selectedId.value); if (id && (route.query.job_id || detailsOpen.value)) void showDetails(id) })
onBeforeUnmount(() => { window.removeEventListener('online', refreshOnConnection); window.removeEventListener('genova:connection-restored', refreshOnConnection); disposed = true; requestId++; controller?.abort(); clearTimeout(searchTimer); if (timer) clearTimeout(timer) })
</script>
<route lang="yaml">
meta:
  layout: blank
</route>
