<template>
  <AppFrame>
    <div class="flex h-full flex-col overflow-hidden bg-white">
      <div class="shrink-0">
        <div class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-end sm:justify-between">
          <div class="min-w-0">
            <h1 class="text-xl font-semibold text-slate-900">{{ $t('platform.adminMonitor') }}</h1>
          </div>
        </div>
      </div>

      <div class="shrink-0 bg-white px-4 mt-2">
        <div class="grid gap-3 md:grid-cols-3">
          <div
            v-for="card in statCards"
            :key="card.key"
            class="border border-slate-200 bg-slate-50 px-4 py-2"
          >
            <div class="flex items-center justify-between gap-3">
              <div>
                <div class="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">{{ card.label }}</div>
                <div class="mt-2 text-xl font-semibold text-slate-900">{{ card.value }}</div>
              </div>
              <div class="flex h-10 w-10 items-center justify-center border border-slate-200 bg-white text-slate-600">
                <component :is="card.icon" class="h-4 w-4" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="shrink-0 border-b border-slate-200 bg-white px-4 py-2 pb-4">
        <div class="grid gap-3 lg:grid-cols-[minmax(0,1.5fr)_220px_auto]">
          <div class="space-y-1.5">
            <Label class="text-xs font-medium text-slate-500">{{ $t('platform.userEmail') }}</Label>
            <Input
              v-model.trim="emailFilter"
              class="h-9 rounded-none"
              :placeholder="$t('platform.filterByEmailEGZjuEduCn')"
              @keydown.enter="applyFilters"
            />
          </div>

          <div class="space-y-1.5">
            <Label class="text-xs font-medium text-slate-500">{{ $t('platform.jobStatus') }}</Label>
            <Select v-model="statusFilter">
              <SelectTrigger class="h-9 rounded-none">
                <SelectValue :placeholder="$t('platform.allStatuses')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="option in statusOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div class="flex items-end gap-2">
            <Button class="h-9 rounded-none px-4" :disabled="isLoading" @click="applyFilters">
              {{ $t('platform.search') }}
            </Button>
            <Button variant="outline" class="h-9 rounded-none px-4" :disabled="isLoading" @click="resetFilters">
              {{ $t('platform.reset') }}
            </Button>
          </div>
        </div>
      </div>

      <div class="min-h-0 flex-1 overflow-hidden p-4">
        <div v-if="errorMessage" class="border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {{ errorMessage }}
        </div>

        <div v-else-if="!hasVerifiedAccess" class="border border-slate-200 bg-white px-3 py-6 text-sm text-slate-500">
          {{ $t('platform.checkingAdministratorAccess') }}
        </div>

        <div v-else class="flex h-full min-h-0 flex-col space-y-3">
          <div class="flex items-center justify-between border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <div class="flex items-center gap-2">
              <span class="font-medium text-slate-900">{{ totalMatched }}</span>
              <span>{{ $t('platform.matchedJobs') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span>{{ isLoading ? $t('platform.refreshing') : $t('platform.lastUpdated') }}</span>
              <span class="font-medium text-slate-900">{{ lastUpdatedText }}</span>
            </div>
          </div>

          <div class="min-h-0 overflow-hidden border border-slate-200 bg-white">
            <div v-if="isLoading && rows.length === 0" class="px-3 py-6 text-sm text-slate-500">
              {{ $t('platform.loadingMonitorData') }}
            </div>
            <div v-else-if="rows.length === 0" class="px-3 py-6 text-sm text-slate-500">
              {{ $t('platform.noJobsMatchedTheCurrentFilters') }}
            </div>
            <div v-else class="h-full overflow-auto">
              <table class="min-w-full text-xs">
                <thead class="sticky top-0 bg-slate-100 text-slate-600">
                  <tr>
                    <th class="px-3 py-2 text-left font-semibold">{{ $t('platform.user') }}</th>
                    <th class="px-3 py-2 text-left font-semibold">{{ $t('platform.taskName') }}</th>
                    <th class="px-3 py-2 text-left font-semibold">{{ $t('platform.jobType') }}</th>
                    <th class="px-3 py-2 text-left font-semibold">{{ $t('platform.status') }}</th>
                    <th class="px-3 py-2 text-left font-semibold">{{ $t('platform.created') }}</th>
                    <th class="px-3 py-2 text-left font-semibold">{{ $t('platform.updated') }}</th>
                    <th class="px-3 py-2 text-left font-semibold">{{ $t('platform.summary') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in rows"
                    :key="row.id"
                    class="border-t border-slate-100 hover:bg-slate-50"
                  >
                    <td class="px-3 py-3 align-top">
                      <div class="font-medium text-slate-900">{{ row.owner_email }}</div>
                      <div class="mt-1 text-[11px] text-slate-500">{{ row.owner_username }}</div>
                    </td>
                    <td class="px-3 py-3 align-top">
                      <div class="font-medium text-slate-900">{{ getTaskName(row) }}</div>
                      <div class="mt-1 font-mono text-[11px] text-slate-500">{{ row.id }}</div>
                    </td>
                    <td class="px-3 py-3 align-top">
                      <span class="inline-flex border border-slate-200 bg-slate-50 px-2 py-1 font-medium text-slate-700">
                        {{ formatJobType(row.job_type) }}
                      </span>
                    </td>
                    <td class="px-3 py-3 align-top">
                      <div class="flex flex-wrap items-center gap-1.5">
                        <span
                          class="inline-flex px-2 py-1 font-medium"
                          :class="statusClass(row.status, row.is_deleted)"
                        >
                          {{ statusLabel(row.status) }}
                        </span>
                        <span
                          v-if="row.is_deleted"
                          class="inline-flex border border-rose-200 bg-rose-50 px-2 py-1 font-medium text-rose-700"
                        >
                          {{ $t('platform.deleted') }}
                        </span>
                      </div>
                    </td>
                    <td class="px-3 py-3 align-top text-slate-600">{{ formatTime(row.created_at) }}</td>
                    <td class="px-3 py-3 align-top text-slate-600">{{ formatTime(row.updated_at) }}</td>
                    <td class="px-3 py-3 align-top text-slate-600">
                      <div class="space-y-1">
                        <div v-if="row.summary?.task_counts" class="text-[11px]">
                          {{ summarizeTaskCounts(row.summary.task_counts) }}
                        </div>
                        <div v-if="row.started_at" class="text-[11px] text-slate-500">
                          {{ $t('platform.started') }} {{ formatTime(row.started_at) }}
                        </div>
                        <div v-if="row.finished_at" class="text-[11px] text-slate-500">
                          {{ $t('platform.finished') }} {{ formatTime(row.finished_at) }}
                        </div>
                        <div v-if="row.deleted_at" class="text-[11px] text-rose-600">
                          {{ $t('platform.deletedLabel') }} {{ formatTime(row.deleted_at) }}
                        </div>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppFrame>
</template>

<script setup lang="ts">
import i18n, { translate, statusLabel } from '@/i18n'

import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, ListChecks, Users } from 'lucide-vue-next'
import AppFrame from '@/components/Layout/appFrame.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { getAdminMonitor, type AdminMonitorJob, type AdminMonitorStats } from '@/api/adminMonitor'
import { getCurrentUserApi } from '@/api/user'
import type { WebSocketManager } from '@/utils/websocket'
import { displayErrorMessage } from '@/utils/requestError'

const router = useRouter()
const websocket = inject<WebSocketManager>('websocket')

const rows = ref<AdminMonitorJob[]>([])
const stats = ref<AdminMonitorStats>({
  current_jobs: 0,
  total_jobs: 0,
  total_users: 0,
})
const totalMatched = ref(0)
const emailFilter = ref('')
const statusFilter = ref('all')
const isLoading = ref(false)
const errorMessage = ref('')
const hasVerifiedAccess = ref(false)
const lastUpdatedAt = ref('')
let refreshTimer: ReturnType<typeof setTimeout> | null = null

const statusOptions = computed(() => [
  { value: 'all', label: translate('platform.allStatuses') },
  { value: 'deleted', label: translate('platform.deletedMarker') },
  { value: 'pending', label: translate('platform.pending') },
  { value: 'queued', label: translate('platform.queued') },
  { value: 'running', label: translate('platform.running') },
  { value: 'blocked', label: translate('platform.blocked') },
  { value: 'succeeded', label: translate('platform.succeeded') },
  { value: 'partial_succeeded', label: translate('platform.partialSucceeded') },
  { value: 'failed', label: translate('platform.failed') },
  { value: 'canceled', label: translate('platform.canceled') },
  { value: 'skipped', label: translate('platform.skipped') },
])

const statCards = computed(() => [
  {
    key: 'current',
    label: translate('platform.currentTasks'),
    value: stats.value.current_jobs,
    icon: Activity,
  },
  {
    key: 'total',
    label: translate('platform.totalTasks'),
    value: stats.value.total_jobs,
    icon: ListChecks,
  },
  {
    key: 'users',
    label: translate('platform.totalUsers'),
    value: stats.value.total_users,
    icon: Users,
  },
])


const lastUpdatedText = computed(() => {
  return lastUpdatedAt.value ? formatTime(lastUpdatedAt.value) : '--'
})

function getTaskName(row: AdminMonitorJob): string {
  const jobName = String(row.params?.job_name || row.params?.name || '').trim()
  return jobName || `${row.job_type}_${row.id.slice(0, 8)}`
}

function formatJobType(jobType: string): string {
  const labels: Record<string, string> = {
    molecule_generation: translate('platform.deNovoGeneration'),
    molecule_postprocessing: translate('platform.postprocessing'),
    protein_preparation: translate('platform.proteinPreparation'),
    property_optimization: translate('platform.leadOptimization'),
  }
  return labels[jobType] || jobType
}

function formatTime(value?: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(i18n.global.locale.value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function statusClass(status: string, isDeleted: boolean): string {
  if (isDeleted) {
    return 'border border-rose-200 bg-rose-50 text-rose-700'
  }
  if (['pending', 'queued', 'running', 'blocked'].includes(status)) {
    return 'border border-amber-200 bg-amber-50 text-amber-700'
  }
  if (status === 'succeeded') {
    return 'border border-emerald-200 bg-emerald-50 text-emerald-700'
  }
  if (status === 'partial_succeeded') {
    return 'border border-sky-200 bg-sky-50 text-sky-700'
  }
  if (status === 'failed') {
    return 'border border-red-200 bg-red-50 text-red-700'
  }
  return 'border border-slate-200 bg-slate-100 text-slate-700'
}

function summarizeTaskCounts(taskCounts: Record<string, any>): string {
  const parts = Object.entries(taskCounts || {})
    .filter(([key]) => key !== 'total')
    .filter(([, value]) => Number(value) > 0)
    .map(([key, value]) => `${statusLabel(key)}: ${value}`)
  return parts.length > 0 ? parts.join(' / ') : translate('platform.noTaskSummary')
}

async function loadMonitor() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const response = await getAdminMonitor({
      email: emailFilter.value,
      status: statusFilter.value,
      limit: 200,
      offset: 0,
    })
    rows.value = response.data.items || []
    stats.value = response.data.stats || stats.value
    totalMatched.value = response.data.total_matched || 0
    lastUpdatedAt.value = new Date().toISOString()
  } catch (error: any) {
    if (error?.response?.status === 403) {
      router.replace('/dashboard')
      return
    }
    rows.value = []
    totalMatched.value = 0
    errorMessage.value = displayErrorMessage(error, translate('platform.failedToLoadAdminMonitorData'))
  } finally {
    isLoading.value = false
  }
}

function applyFilters() {
  loadMonitor()
}

function resetFilters() {
  emailFilter.value = ''
  statusFilter.value = 'all'
  loadMonitor()
}

function scheduleRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
  }
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    loadMonitor()
  }, 150)
}

function handleWsMessage(event: MessageEvent) {
  try {
    const data = JSON.parse(event.data)
    if (data?.object) {
      scheduleRefresh()
    }
  } catch (error) {
    console.error('Failed to parse admin monitor WebSocket message:', error)
  }
}

async function verifyAdminAccess() {
  try {
    const response = await getCurrentUserApi()
    if (!response.data?.is_admin) {
      router.replace('/dashboard')
      return false
    }
    hasVerifiedAccess.value = true
    return true
  } catch (error) {
    router.replace('/login')
    return false
  }
}

onMounted(async () => {
  const ok = await verifyAdminAccess()
  if (!ok) {
    return
  }
  await loadMonitor()
  websocket?.addFunc('task_state', handleWsMessage)
})

onUnmounted(() => {
  websocket?.removeFunc('task_state', handleWsMessage)
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
})
</script>

<route lang="yaml">
meta:
  layout: blank
</route>
