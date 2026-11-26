<template>
  <DropdownMenu><DropdownMenuTrigger as-child><Button variant="ghost" size="icon" class="relative h-8 w-8" :aria-label="t('platform.taskNotifications')" :title="t('platform.taskNotifications')"><Bell class="h-4 w-4" aria-hidden="true" /><span v-if="activeCount" class="absolute -right-1 -top-1 min-w-4 rounded-full bg-primary px-1 text-[10px] text-white">{{ activeCount > 99 ? '99+' : activeCount }}</span></Button></DropdownMenuTrigger>
    <DropdownMenuContent align="end" class="w-[360px] max-w-[calc(100vw-32px)] p-0">
      <div class="flex items-center justify-between border-b p-4"><h2 class="text-sm font-semibold">{{ t('platform.taskNotifications') }}</h2><RouterLink to="/results" class="text-xs text-primary">{{ t('platform.allTasksResults') }}</RouterLink></div>
      <div class="max-h-96 overflow-auto p-2">
        <p v-if="error" role="alert" class="p-3 text-sm text-destructive">{{ error }}<Button variant="ghost" size="sm" @click="refresh">{{ t('platform.retry') }}</Button></p>
        <FeedbackState v-else-if="!jobs.length" :title="t('platform.emptyNotifications')" :description="t('platform.noRunningHint')" />
        <RouterLink v-for="job in jobs" :key="job.id" :to="jobDestination(job)" class="block space-y-2 rounded-lg p-3 hover:bg-secondary"><p class="truncate text-sm font-medium">{{ jobTitle(job) }}</p><div class="flex items-center justify-between gap-3"><span class="status-badge" :class="statusTone(job.status)">{{ statusLabel(job.status) }}</span><span class="text-xs text-muted-foreground">{{ new Date(job.updated_at).toLocaleTimeString(locale) }}</span></div></RouterLink>
      </div>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bell } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import FeedbackState from '@/components/workbench/FeedbackState.vue'
import type { BackendJobListOut } from '@/api/genovaBackend'
import { subscribeJobList } from '@/utils/jobListPoller'
import { requestErrorMessage } from '@/utils/requestError'
import { activeJobStatuses, jobTitle, resultRoutes, statusTone } from '@/utils/taskPresentation'
import { statusLabel } from '@/i18n'
import { toast } from '@/components/ui/toast'
const props = withDefaults(defineProps<{taskType?: string}>(), {taskType:'all'})
const { t, locale } = useI18n()
const jobs = ref<BackendJobListOut[]>([]), error = ref('')
const activeCount = ref(0)
const previous = new Map<string, string>()
let subscription: ReturnType<typeof subscribeJobList> | undefined, disposed = false
function jobDestination(job: BackendJobListOut) { return ['succeeded', 'partial_succeeded'].includes(job.status) && resultRoutes[job.job_type] ? {path: resultRoutes[job.job_type], query:{job_id:job.id}} : {path:'/results', query:{job_id:job.id}} }
// The job list comes from the poll shared with the dashboard (paused in hidden tabs, slower after errors).
function applyJobs(result: BackendJobListOut[]) {
  if (disposed) return
  error.value = ''
  const visible = result.filter(job => !['virtual_screening','clip','micro'].includes(job.job_type) && !job.params.system_tags?.hidden_in_dashboard && (props.taskType === 'all' || job.job_type === props.taskType))
  activeCount.value = visible.filter(job => activeJobStatuses.includes(job.status)).length
  for (const job of visible) {
    if (activeJobStatuses.includes(previous.get(job.id) || '') && ['succeeded','partial_succeeded','failed'].includes(job.status)) toast({title:jobTitle(job), description:statusLabel(job.status)})
    previous.set(job.id, job.status)
  }
  jobs.value = visible.sort((a,b) => b.updated_at.localeCompare(a.updated_at)).slice(0,10)
}
const refresh = () => subscription?.refresh()
onMounted(() => { subscription = subscribeJobList({ update: applyJobs, error: e => { if (!disposed) error.value = requestErrorMessage(e) } }) })
onUnmounted(() => { disposed = true; subscription?.stop() })
</script>
