<template>
  <div class="workbench relative flex h-dvh overflow-hidden">
    <button v-if="isMobile && mobileSidebarOpen" type="button" tabindex="-1" aria-hidden="true" class="fixed inset-0 z-[49] bg-slate-900/30" @click="closeMobileSidebar" />
    <div class="h-full shrink-0 transition-[width] duration-200 motion-reduce:transition-none" :class="isMobile ? 'w-0' : isSidebarExpanded ? 'sidebar-expanded w-56' : 'w-16'">
      <FocusScope as-child :trapped="isMobile && mobileSidebarOpen" :loop="isMobile && mobileSidebarOpen" @mount-auto-focus.prevent @unmount-auto-focus.prevent>
        <aside id="app-sidebar" :role="isMobile && mobileSidebarOpen ? 'dialog' : undefined" :aria-modal="isMobile && mobileSidebarOpen ? true : undefined" :aria-label="t('platform.appNavigation')" class="app-sidebar" :class="isMobile ? mobileSidebarOpen ? 'fixed inset-y-0 left-0 z-50 w-56' : 'hidden' : 'relative h-full w-full'">
          <div class="flex h-14 shrink-0 items-center gap-2 px-4">
            <RouterLink to="/" :aria-label="t('platform.home')" :title="t('platform.home')" class="flex min-w-0 flex-1 items-center gap-3">
              <img :src="genovaIcon" alt="Genova" class="h-8 w-8 shrink-0 object-contain" />
              <span v-if="isSidebarExpanded" class="truncate text-lg font-semibold tracking-tight">Genova</span>
            </RouterLink>
            <button v-if="isMobile" ref="sidebarClose" type="button" :aria-label="t('platform.closeNavigation')" class="nav-icon" @click="closeMobileSidebar"><X class="h-4 w-4" /></button>
          </div>
          <nav class="flex min-h-0 flex-1 flex-col gap-1 px-2 py-5">
            <template v-for="item in primaryNav" :key="item.key">
              <DropdownMenu v-if="item.key === 'tools' && !isSidebarExpanded">
                <DropdownMenuTrigger as-child><button type="button" class="nav-link" :class="{ active: toolActive }" :aria-label="item.title" :title="item.title"><span class="nav-icon"><Wrench class="h-5 w-5" aria-hidden="true" /></span></button></DropdownMenuTrigger>
                <DropdownMenuContent side="right" align="start" :side-offset="8" class="w-60">
                  <DropdownMenuLabel>{{ item.title }}</DropdownMenuLabel>
                  <DropdownMenuItem v-for="tool in moduleNav" :key="tool.to" as-child><RouterLink :to="tool.to" :aria-current="isActive(tool) ? 'page' : undefined"><component :is="tool.icon" class="h-4 w-4" aria-hidden="true" />{{ tool.title }}</RouterLink></DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <template v-else-if="item.key === 'tools'">
                <button type="button" class="nav-link" :class="{ active: toolActive }" :aria-expanded="toolsOpen" aria-controls="design-tools" @click="toolsOpen = !toolsOpen"><span class="nav-icon"><Wrench class="h-5 w-5" aria-hidden="true" /></span><span class="flex-1 text-left">{{ item.title }}</span><ChevronDown class="mr-2 h-4 w-4 transition-transform duration-150" :class="{ 'rotate-180': toolsOpen }" /></button>
                <div id="design-tools" v-show="toolsOpen" class="ml-6 space-y-1 border-l pl-2">
                  <RouterLink v-for="tool in moduleNav" :key="tool.to" :to="tool.to" class="nav-link tool-link" :class="{ active: isActive(tool) }" :aria-current="isActive(tool) ? 'page' : undefined"><component :is="tool.icon" class="h-4 w-4 shrink-0" aria-hidden="true" /><span>{{ tool.title }}</span></RouterLink>
                </div>
              </template>
              <Tooltip v-else><TooltipTrigger as-child><RouterLink :to="item.to" class="nav-link" :class="{ active: isActive(item) }" :aria-current="isActive(item) ? 'page' : undefined" :aria-label="item.title" :title="!isSidebarExpanded ? item.title : undefined"><span class="nav-icon"><component :is="item.icon" class="h-5 w-5" aria-hidden="true" /></span><span v-if="isSidebarExpanded" class="truncate">{{ item.title }}</span></RouterLink></TooltipTrigger><TooltipContent v-if="!isSidebarExpanded" side="right">{{ item.title }}</TooltipContent></Tooltip>
            </template>
            <div class="min-h-4 flex-1" />
            <Tooltip v-for="item in settingsNav" :key="item.to"><TooltipTrigger as-child><RouterLink :to="item.to" class="nav-link" :class="{ active: isActive(item) }" :aria-current="isActive(item) ? 'page' : undefined" :aria-label="item.title" :title="!isSidebarExpanded ? item.title : undefined"><span class="nav-icon"><component :is="item.icon" class="h-5 w-5" aria-hidden="true" /></span><span v-if="isSidebarExpanded" class="truncate">{{ item.title }}</span></RouterLink></TooltipTrigger><TooltipContent v-if="!isSidebarExpanded" side="right">{{ item.title }}</TooltipContent></Tooltip>
            <div class="mt-2 border-t pt-3" :class="isSidebarExpanded ? 'px-2' : 'account-collapsed'"><AccountMenu /></div>
          </nav>
        </aside>
      </FocusScope>
    </div>
    <div class="flex min-w-0 flex-1 flex-col" :inert="isMobile && mobileSidebarOpen">
      <header class="z-40 flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-4 py-2">
        <button ref="sidebarToggle" type="button" :aria-label="t(isSidebarExpanded ? 'platform.collapseNavigation' : 'platform.expandNavigation')" :aria-expanded="isSidebarExpanded" aria-controls="app-sidebar" class="nav-icon hover:bg-secondary" @click="toggleSidebar"><component :is="isSidebarExpanded ? PanelLeftClose : PanelLeftOpen" class="h-4 w-4" aria-hidden="true" /></button>
        <div ref="headerTarget" class="order-3 w-full min-w-0 sm:order-none sm:w-auto sm:flex-1">
          <nav v-if="!hasPageHeader" :aria-label="t('platform.navigationPath')" class="flex min-w-0 items-center gap-2 text-sm text-muted-foreground"><span v-if="toolActive" class="max-sm:hidden">{{ t('platform.designTools') }}</span><ChevronRight v-if="toolActive" class="h-3 w-3 shrink-0 max-sm:hidden" aria-hidden="true" /><span class="truncate font-medium text-foreground">{{ currentTitle }}</span><template v-if="resultPage"><ChevronRight class="h-3 w-3 shrink-0" aria-hidden="true" /><span class="truncate">{{ t('platform.results') }}</span></template></nav>
        </div>
        <div class="ml-auto flex shrink-0 items-center gap-3"><TaskNotify task-type="all" /><LanguageSwitcher /><div class="mx-1 h-5 border-l max-sm:hidden" /><AccountMenu /></div>
      </header>
      <TaskSummary v-if="summary" :task="summary" />
      <DataRetentionNotice />
      <main class="min-h-0 flex-1 overflow-auto overscroll-contain"><slot /></main>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, provide, onMounted, watch, nextTick } from 'vue'
import { useEventListener, useMediaQuery, useStorage } from '@vueuse/core'
import { FocusScope } from 'radix-vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Bot, PanelLeftClose, PanelLeftOpen, X, Database, FlaskConical, LayoutDashboard, ListChecks, Sparkles, SlidersHorizontal, Funnel, Shield, BookOpen, Wrench, ChevronDown, ChevronRight } from 'lucide-vue-next'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel } from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'
import DataRetentionNotice from '@/components/common/DataRetentionNotice.vue'
import AccountMenu from '@/components/auth/AccountMenu.vue'
import TaskSummary from '@/components/workbench/TaskSummary.vue'
import { workspaceHeaderKey, workspaceTaskKey, type WorkspaceTask } from '@/composables/useWorkspace'
import { jobTitle, jobContextLabel, toolRoutes } from '@/utils/taskPresentation'
import { statusLabel } from '@/i18n'
import AlphaHelixIcon from './AlphaHelixIcon.vue'
import TaskNotify from './task_notify.vue'
import websocket from '@/utils/websocket'
import { getCurrentUserApi } from '@/api/user'
import { getBackendJob, type BackendJobOut } from '@/api/genovaBackend'

const props = defineProps<{ task?: WorkspaceTask | null }>()
const genovaIcon = `${import.meta.env.BASE_URL}genova-icon.svg`
const { t } = useI18n()
const route = useRoute(), router = useRouter()
const isAdmin = ref(false)
const headerTarget = ref<HTMLElement | null>(null), hasPageHeader = ref(false)
provide(workspaceHeaderKey, { target: headerTarget, active: hasPageHeader })
const childTask = ref<WorkspaceTask | null>(null), routeJob = ref<BackendJobOut | null>(null)
const routeTask = computed<WorkspaceTask | null>(() => routeJob.value ? { name: jobTitle(routeJob.value), stage: statusLabel(routeJob.value.status), context: jobContextLabel(routeJob.value), version: routeJob.value.params.plan_version, details: () => router.push({ path: '/results', query: { job_id: routeJob.value!.id } }) } : null)
provide(workspaceTaskKey, childTask)
provide('websocket', websocket)
const summary = computed(() => props.task === undefined ? childTask.value || routeTask.value : props.task)
watch(() => String(route.query.job_id || route.query.restore_job_id || ''), async (id, _, cleanup) => {
  let stale = false
  routeJob.value = null
  if (!id) return
  let timer: ReturnType<typeof setTimeout> | undefined
  cleanup(() => { stale = true; clearTimeout(timer) })
  async function refresh() {
    try {
      const job = (await getBackendJob(id, { summary: true })).data
      if (stale) return
      routeJob.value = job
      if (['pending', 'queued', 'running', 'blocked'].includes(job.status)) timer = setTimeout(refresh, 5000)
    } catch { /* The page owns job-load errors. */ }
  }
  await refresh()
}, { immediate: true })
const isMobile = useMediaQuery('(max-width: 767px)')
const mobileSidebarOpen = ref(false), sidebarToggle = ref<HTMLButtonElement | null>(null), sidebarClose = ref<HTMLButtonElement | null>(null)
const sidebarPreferences = useStorage<Record<string, boolean>>('genova:sidebar-expanded', {})
const sidebarModule = computed(() => route.path.split('/')[1])
const desktopSidebarExpanded = computed(() => sidebarPreferences.value[sidebarModule.value] ?? true)
const isSidebarExpanded = computed(() => isMobile.value ? mobileSidebarOpen.value : desktopSidebarExpanded.value)
function toggleSidebar() { if (isMobile.value) mobileSidebarOpen.value = !mobileSidebarOpen.value; else sidebarPreferences.value = { ...sidebarPreferences.value, [sidebarModule.value]: !desktopSidebarExpanded.value } }
function closeMobileSidebar() { mobileSidebarOpen.value = false; nextTick(() => sidebarToggle.value?.focus()) }
watch(mobileSidebarOpen, async open => { if (open) { await nextTick(); sidebarClose.value?.focus() } })
watch([() => route.fullPath, isMobile], () => { mobileSidebarOpen.value = false })
useEventListener('keydown', event => { if (event.key === 'Escape' && isMobile.value && mobileSidebarOpen.value) { event.preventDefault(); closeMobileSidebar() } })
const moduleNav = computed(() => [
  { title: t('platform.proteinPreparation'), to: '/protein-preparation', icon: AlphaHelixIcon },
  { title: t('platform.deNovoGeneration'), to: '/molgen', icon: Sparkles },
  { title: t('platform.leadOptimization'), to: '/molopt', icon: FlaskConical },
  { title: t('platform.postprocessingNav'), to: '/postprocessing', icon: Funnel },
])
const primaryNav = computed(() => [
  { key: 'dashboard', title: t('platform.dashboard'), to: '/dashboard', icon: LayoutDashboard },
  { key: 'agent', title: t('agent.title'), to: '/agent', icon: Bot },
  { key: 'tools', title: t('platform.designTools'), to: '', icon: Wrench },
  { key: 'results', title: t('platform.allTasksResults'), to: '/results', icon: ListChecks },
  { key: 'data', title: t('platform.dataCenter'), to: '/datacenter', icon: Database },
])
const settingsNav = computed(() => [
  { title: t('platform.helpCenter'), to: '/help', icon: BookOpen },
  { title: t('platform.settings'), to: '/settings', icon: SlidersHorizontal },
  ...(isAdmin.value ? [{ title: t('platform.adminMonitor'), to: '/admin-monitor', icon: Shield }] : []),
])
const resultPage = computed(() => route.path !== '/results' && route.path.endsWith('/results'))
const isActive = (item: { to: string }) => item.to === '/results' ? route.path === '/results' || resultPage.value : route.path === item.to || route.path.startsWith(item.to + '/')
const toolActive = computed(() => !resultPage.value && Object.values(toolRoutes).some(to => isActive({ to })))
const toolsOpen = ref(true)
watch(() => route.path, () => { if (toolActive.value) toolsOpen.value = true })
const currentTitle = computed(() => (resultPage.value ? moduleNav.value : [...primaryNav.value.filter(item => item.key !== 'tools'), ...moduleNav.value, ...settingsNav.value]).find(isActive)?.title || t('platform.home'))
onMounted(async () => {
  websocket.setWs()
  try { isAdmin.value = Boolean((await getCurrentUserApi()).data?.is_admin) } catch (error) { console.error('Failed to load user data:', error) }
})
</script>
<style scoped>
.app-sidebar { display: flex; flex-direction: column; overflow-y: auto; border-right: 1px solid var(--border-default); background: var(--surface); }
.nav-link { display: flex; align-items: center; gap: 8px; min-height: 40px; border-radius: 8px; color: var(--text-secondary); font-size: 14px; transition: background 150ms, color 150ms; }
.nav-link:hover { background: var(--surface-secondary); color: var(--text-primary); }
.nav-link.active { background: var(--selection-bg); color: var(--action-primary); font-weight: 600; }
.nav-icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; margin: 0 8px; flex-shrink: 0; border-radius: 8px; }
.tool-link { line-height: 20px; padding: 8px; gap: 8px; min-height: 36px; }
@media (min-width: 768px) {
  .sidebar-expanded:lang(en) { width: 256px; }
}
.account-collapsed :deep(button > span:not(:first-child)), .account-collapsed :deep(button > svg) { display: none; }
.account-collapsed :deep(button) { justify-content: center; width: 100%; }
</style>
