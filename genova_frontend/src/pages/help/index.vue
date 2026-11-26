<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, ArrowRight, BookOpen, ChevronDown, ChevronRight, ExternalLink, FlaskConical, Search, Sparkles, X } from 'lucide-vue-next'
import AppFrame from '@/components/Layout/appFrame.vue'
import HelpEntryCard from '@/components/help/HelpEntryCard.vue'
import { getHelpCatalog, type HelpCatalog, type HelpEntry, type HelpLanguage } from '@/api/help'
import { metricSections } from './data/metricSections'
import { copyText } from '@/utils/clipboard'

const route = useRoute()
const router = useRouter()
const { locale } = useI18n({ useScope: 'global' })
const narrow = useMediaQuery('(max-width: 768px)')
const catalog = ref<HelpCatalog | null>(null)
const loading = ref(true)
const failed = ref(false)
const copied = ref('')
const navigationOpen = ref(false)
const pageTop = ref<HTMLElement | null>(null)
const pageHeading = ref<HTMLElement | null>(null)
const language = computed<HelpLanguage>(() => locale.value === 'zh-CN' ? 'zh-CN' : 'en-US')
const zh = computed(() => language.value === 'zh-CN')
const copy = computed(() => zh.value ? {
  search: '搜索操作、模型、参数或指标…', navigation: '帮助目录',
  all: '概览', guides: '操作指南', models: '模型与参数', parameters: '模型参数', metrics: 'TarPass 指标', properties: '分子性质', poses: '姿态指标', references: '参考文献',
  basics: '通用操作', modules: '模块操作说明', guideHint: '准备输入、运行任务、筛选候选并导出结果。', steps: '查看操作步骤',
  modelIntro: '模型与参数参考', modelHint: '查看各模型的用途、采样设置和参数含义。',
  deNovo: '从头生成', optimize: '先导优化', browse: '查看模型参数', explore: '分子评价与筛选',
  metricHint: '分子性质、结构特征、对接评分与相互作用。',
  start: '从输入到结果',
  results: '个匹配条目', empty: '没有找到匹配内容', emptyHint: '试试 QED、随机种子、相似度，或清除搜索词。', clear: '清除搜索',
  back: '返回目录', related: '继续阅读', load: '正在加载帮助内容…', error: '帮助内容加载失败。', retry: '重试',
  count: '个可筛选字段', noArticle: '没有找到该条目',
  poseNote: 'Original 评估输入的三维姿态，Docked 评估重新对接姿态；二维输入只有 Docked 结果。',
} : {
  search: 'Search operations, models, parameters or metrics…', navigation: 'Help navigation',
  all: 'Overview', guides: 'User guides', models: 'Models & parameters', parameters: 'Model parameters', metrics: 'TarPass metrics', properties: 'Molecular properties', poses: 'Pose metrics', references: 'References',
  basics: 'Getting started', modules: 'Module guides', guideHint: 'Prepare inputs, run tasks, filter candidates and export results.', steps: 'View user guide',
  modelIntro: 'Model and parameter reference', modelHint: 'Find model purposes, sampling settings and parameter definitions.',
  deNovo: 'DE NOVO DESIGN', optimize: 'LEAD OPTIMIZATION', browse: 'View model parameters', explore: 'Evaluation & Screening',
  metricHint: 'Molecular properties, structural features, docking scores and interactions.',
  start: 'From inputs to results',
  results: 'matching entries', empty: 'No matching entries', emptyHint: 'Try QED, seed or similarity, or clear your search.', clear: 'Clear search',
  back: 'Back to contents', related: 'Continue reading', load: 'Loading help…', error: 'Help could not be loaded.', retry: 'Try again',
  count: 'filterable fields', noArticle: 'This entry could not be found',
  poseNote: 'Original evaluates the supplied 3D pose; Docked evaluates the redocked pose. 2D inputs have Docked results only.',
})
const groups = ['guides', 'models', 'metrics'] as const
const groupLabel = (group: string) => copy.value[group as keyof typeof copy.value] || group
const entries = computed(() => catalog.value?.entries || [])
const requested = computed(() => entries.value.find(entry => entry.id === route.query.article || entry.keys.includes(String(route.query.article || ''))))
const selected = computed(() => requested.value?.group === 'parameters'
  ? entries.value.find(model => model.group === 'models' && model.model === requested.value?.model)
  : requested.value)
const modelParameters = computed(() => selected.value?.group === 'models'
  ? entries.value.filter(entry => entry.group === 'parameters' && entry.model === selected.value?.model)
  : [])
const group = computed(() => {
  const value = selected.value?.group || String(route.query.group || 'all')
  return ['properties', 'poses'].includes(value) ? 'metrics' : ['inputs', 'screening'].includes(value) ? 'guides' : value
})
const query = computed({
  get: () => String(route.query.q || ''),
  set: (value: string) => router.replace({ path: '/help', query: { q: value || undefined } }),
})
const matches = computed(() => {
  const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return entries.value.filter(entry => {
    if (entry.group === 'parameters') return false
    if (!words.length) return group.value === 'all' || entry.group === group.value
    const content = entry.group === 'models'
      ? [entry, ...entries.value.filter(parameter => parameter.group === 'parameters' && parameter.model === entry.model)]
      : [entry]
    const text = content.flatMap(item => [item.id, item.model, ...item.keys, ...item.aliases, ...Object.values(item.translations).flatMap(value => [value.title, value.summary, value.details, value.guidance, value.range, ...(value.sections || []).flatMap(section => [section.title, ...section.items])])]).join(' ').toLowerCase()
    return words.every(word => text.includes(word))
  }).sort((a, b) => {
    const exact = query.value.trim().toLowerCase()
    const rank = (entry: HelpEntry) => [...entry.keys, entry.id, ...entry.aliases, ...Object.values(entry.translations).map(t => t.title)].some(value => value.toLowerCase() === exact) ? 0 : 1
    return rank(a) - rank(b)
  })
})
const sections = computed(() => metricSections.map(section => ({
  ...section,
  title: zh.value ? section.zh : section.en,
  entries: section.ids.map(id => entries.value.find(entry => entry.id === id)!).filter(Boolean),
})))
const activeSection = computed(() => metricSections.find(section => section.ids.includes(requested.value?.id || ''))?.id || route.query.section)
const modelEntries = computed(() => entries.value.filter(entry => entry.group === 'models'))
const guideSections = computed(() => [
  { id: 'basics', title: copy.value.basics, ids: ['workflow-overview', 'inputs', 'filtering', 'pose-stages', 'interactions', 'clustering', 'exports'] },
  { id: 'modules', title: copy.value.modules, ids: ['protein-preparation', 'molecule-generation', 'lead-optimization', 'tarpass', 'assistant-workflow', 'datasets-workflow', 'tasks-results'] },
].map(section => ({ ...section, entries: section.ids.map(id => entries.value.find(entry => entry.id === id)!).filter(Boolean) })))
const quickGuides = computed(() => ['inputs', 'filtering', 'exports'].map(id => entries.value.find(entry => entry.id === id)!).filter(Boolean))
const operationGuide = computed(() => selected.value?.group === 'models'
  ? entries.value.find(entry => selected.value?.related?.includes(entry.id) && entry.group === 'guides')
  : undefined)
const related = computed(() => {
  if (!selected.value || selected.value.group === 'models') return []
  return (selected.value.related || ['tarpass', 'filtering', 'clustering']).map(id => entries.value.find(entry => entry.id === id)!).filter(entry => entry && entry.id !== selected.value?.id)
})
const showHome = computed(() => !route.query.article && !query.value.trim() && group.value === 'all')
const showMetrics = computed(() => group.value === 'metrics' && !query.value.trim())
const showGuides = computed(() => group.value === 'guides' && !query.value.trim() && !selected.value)
const textFor = (entry: HelpEntry) => entry.translations[language.value]
const linkTo = (id: string) => ({ path: '/help', query: { article: id } })
const sectionLink = (id: string) => ({ path: '/help', query: { group: 'metrics', section: id } })

function selectGroup(value: string) {
  navigationOpen.value = false
  router.push({ path: '/help', query: { group: value === 'all' ? undefined : value } })
}
async function load() {
  failed.value = false
  loading.value = true
  try { catalog.value = (await getHelpCatalog()).data }
  catch { failed.value = true }
  finally { loading.value = false }
}
async function copyLink(id: string) {
  try {
    await copyText(new URL(router.resolve(linkTo(id)).href, window.location.origin).href)
    copied.value = id
  } catch { copied.value = '' }
}
async function scrollToContent() {
  if (loading.value || failed.value || query.value.trim()) return
  navigationOpen.value = false
  await nextTick()
  const id = requested.value?.id || (showMetrics.value && activeSection.value ? `section-${activeSection.value}` : '')
  const target = id ? document.getElementById(id) : null
  ;(target || pageHeading.value)?.focus({ preventScroll: true })
  ;(target || pageTop.value)?.scrollIntoView({ block: 'start', behavior: 'instant' })
}
watch([() => route.fullPath, loading], () => {
  copied.value = ''
  navigationOpen.value = false
  scrollToContent()
}, { flush: 'post' })
onMounted(load)
</script>

<template>
  <AppFrame>
    <div ref="pageTop" class="help-page min-h-full" :lang="language">
      <header class="px-4 pt-4 md:px-6">
        <div class="relative max-w-2xl">
          <Search class="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" aria-hidden="true" />
          <input v-model="query" type="search" :placeholder="copy.search" :aria-label="copy.search" class="help-search h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-10 text-sm placeholder:text-slate-400 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100">
          <button v-if="query" type="button" :aria-label="copy.clear" class="absolute right-1 top-1 rounded-md p-2 text-slate-500 hover:bg-slate-100" @click="query = ''"><X class="h-4 w-4" /></button>
        </div>
      </header>

      <div class="help-layout">
        <aside class="help-sidebar min-w-0">
          <button v-if="narrow" type="button" class="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700" :aria-expanded="navigationOpen" aria-controls="help-navigation" @click="navigationOpen = !navigationOpen">{{ copy.navigation }}<ChevronDown class="h-4 w-4" :class="navigationOpen ? 'rotate-180' : ''" /></button>
          <nav v-show="!narrow || navigationOpen" id="help-navigation" class="help-nav space-y-1" :aria-label="copy.navigation">
            <template v-for="item in ['all', ...groups, 'references']" :key="item">
              <button type="button" class="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm" :class="group === item && !query ? 'bg-blue-50 font-semibold text-blue-700' : 'text-slate-600 hover:bg-slate-100'" :aria-current="group === item && !query ? 'page' : undefined" @click="selectGroup(item)">{{ groupLabel(item) }}</button>
              <div v-if="item === 'guides' && group === 'guides' && !query" class="ml-3 space-y-3 border-l border-slate-200 pl-2">
                <div v-for="section in guideSections" :key="section.id">
                  <p class="px-2 pt-1 text-xs font-semibold text-slate-700">{{ section.title }}</p>
                  <RouterLink v-for="entry in section.entries" :key="entry.id" :to="linkTo(entry.id)" class="mt-1 block rounded px-2 py-1.5 text-xs leading-5" :class="selected?.id === entry.id ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-500 hover:bg-slate-100'" :aria-current="selected?.id === entry.id ? 'page' : undefined">{{ textFor(entry).title }}</RouterLink>
                </div>
              </div>
              <div v-if="item === 'metrics' && showMetrics" class="ml-3 space-y-0.5 border-l border-slate-200 pl-2">
                <RouterLink v-for="section in sections" :key="section.id" :to="sectionLink(section.id)" class="block rounded px-2 py-1.5 text-xs leading-5" :class="activeSection === section.id ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'" :aria-current="activeSection === section.id ? 'location' : undefined" @click="scrollToContent">{{ section.title }}</RouterLink>
              </div>
            </template>
          </nav>
        </aside>

        <main class="min-w-0">
          <div v-if="loading" role="status" class="space-y-4 py-8 text-slate-500"><p>{{ copy.load }}</p><div v-for="n in 3" :key="n" class="h-24 animate-pulse rounded-xl bg-slate-100 motion-reduce:animate-none" /></div>
          <div v-else-if="failed" role="alert" class="rounded-xl border border-rose-100 bg-rose-50 p-6 text-sm text-rose-800"><p>{{ copy.error }}</p><button class="mt-3 underline underline-offset-4" type="button" @click="load">{{ copy.retry }}</button></div>
          <template v-else-if="showHome">
            <section class="mb-10">
              <div class="flex flex-wrap items-center justify-between gap-3"><h1 ref="pageHeading" tabindex="-1" class="text-xl font-semibold tracking-tight text-slate-900 outline-none">{{ copy.guides }}</h1><RouterLink :to="linkTo('workflow-overview')" class="inline-flex items-center gap-2 text-sm font-medium text-blue-700">{{ copy.start }}<ArrowRight class="h-4 w-4" aria-hidden="true" /></RouterLink></div>
              <p class="mt-2 text-sm text-slate-500">{{ copy.guideHint }}</p>
              <div class="mt-5 grid gap-3 sm:grid-cols-3"><RouterLink v-for="entry in quickGuides" :key="entry.id" :to="linkTo(entry.id)" class="rounded-xl border border-blue-100 bg-blue-50/50 p-4 hover:border-blue-300"><BookOpen class="mb-3 h-5 w-5 text-blue-600" aria-hidden="true" /><h2 class="text-sm font-semibold text-slate-900">{{ textFor(entry).title }}</h2><p class="mt-2 text-xs leading-5 text-slate-600">{{ textFor(entry).summary }}</p></RouterLink></div>
              <h2 class="mt-7 text-base font-semibold text-slate-900">{{ copy.modules }}</h2>
              <div class="mt-3 grid gap-2 sm:grid-cols-2"><RouterLink v-for="entry in guideSections[1].entries" :key="entry.id" :to="linkTo(entry.id)" class="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 hover:border-blue-300 hover:text-blue-700">{{ textFor(entry).title }}<ChevronRight class="h-4 w-4 shrink-0" aria-hidden="true" /></RouterLink></div>
            </section>
            <section>
              <h2 class="text-xl font-semibold tracking-tight text-slate-900">{{ copy.modelIntro }}</h2>
              <p class="mt-2 text-sm text-slate-500">{{ copy.modelHint }}</p>
              <div class="mt-5 grid gap-4 sm:grid-cols-2">
                <RouterLink v-for="(entry, index) in modelEntries" :key="entry.id" :to="linkTo(entry.id)" class="model-card group rounded-2xl border border-slate-200 bg-white p-5 transition-all hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md motion-reduce:transform-none">
                  <div class="mb-5 flex items-center justify-between"><span class="rounded-xl p-2.5" :class="index < 2 ? 'bg-blue-50 text-blue-600' : 'bg-teal-50 text-teal-700'"><Sparkles v-if="index < 2" class="h-5 w-5" aria-hidden="true" /><FlaskConical v-else class="h-5 w-5" aria-hidden="true" /></span><span class="text-[10px] font-semibold tracking-widest text-slate-400">{{ index < 2 ? copy.deNovo : copy.optimize }}</span></div>
                  <h3 class="text-lg font-semibold text-slate-900">{{ textFor(entry).title }}</h3>
                  <p class="mt-2 text-sm leading-6 text-slate-600">{{ textFor(entry).summary }}</p>
                  <span class="mt-5 inline-flex items-center gap-2 text-xs font-semibold text-blue-700">{{ copy.browse }}<ArrowRight class="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" aria-hidden="true" /></span>
                </RouterLink>
              </div>
            </section>
            <section class="mt-10">
              <div class="flex flex-wrap items-center gap-3"><h2 class="text-xl font-semibold tracking-tight text-slate-900">{{ copy.explore }}</h2><span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-500">{{ catalog?.metric_count }} {{ copy.count }}</span></div>
              <div class="mt-5 divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white">
                <button type="button" class="flex w-full items-center gap-4 p-5 text-left hover:bg-slate-50" @click="selectGroup('metrics')">
                  <FlaskConical class="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" /><div class="flex-1"><h3 class="text-sm font-semibold text-slate-800">{{ copy.metrics }}</h3><p class="mt-1 text-xs leading-5 text-slate-500">{{ copy.metricHint }}</p></div><ChevronRight class="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
                </button>
              </div>
            </section>
          </template>

          <section v-else-if="showGuides">
            <h1 ref="pageHeading" tabindex="-1" class="text-xl font-semibold text-slate-900 outline-none">{{ copy.guides }}</h1>
            <p class="mt-2 text-sm text-slate-500">{{ copy.guideHint }}</p>
            <section v-for="section in guideSections" :key="section.id" class="mt-7">
              <h2 class="mb-3 text-base font-semibold text-slate-900">{{ section.title }}</h2>
              <div class="grid gap-3 sm:grid-cols-2"><RouterLink v-for="entry in section.entries" :key="entry.id" :to="linkTo(entry.id)" class="rounded-xl border border-slate-200 bg-white p-4 hover:border-blue-300"><h3 class="text-sm font-semibold text-slate-900">{{ textFor(entry).title }}</h3><p class="mt-2 text-sm leading-6 text-slate-600">{{ textFor(entry).summary }}</p></RouterLink></div>
            </section>
          </section>

          <section v-else-if="showMetrics">
            <div class="mb-2 flex flex-wrap items-center gap-3"><h1 ref="pageHeading" tabindex="-1" class="text-xl font-semibold text-slate-900 outline-none">{{ copy.metrics }}</h1><span class="text-xs text-slate-400">{{ catalog?.metric_count }} {{ copy.count }}</span></div>
            <p class="mb-6 text-xs leading-5 text-slate-500">{{ copy.poseNote }}</p>
            <section v-for="section in sections" :key="section.id" class="mb-8">
              <h2 :id="`section-${section.id}`" tabindex="-1" class="mb-3 scroll-mt-4 text-base font-semibold text-slate-800 outline-none">{{ section.title }}</h2>
              <div class="space-y-3"><HelpEntryCard v-for="entry in section.entries" :key="entry.id" :entry="entry" :language="language" :references="catalog!.references" :copied="copied" @copy="copyLink" /></div>
            </section>
          </section>

          <section v-else-if="selected && !query" class="help-article">
            <button type="button" class="mb-4 inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-blue-700" @click="selectGroup(selected.group)"><ArrowLeft class="h-3.5 w-3.5" aria-hidden="true" />{{ copy.back }}</button>
            <RouterLink v-if="operationGuide" :to="linkTo(operationGuide.id)" class="mb-4 ml-4 inline-flex items-center gap-2 text-sm font-medium text-blue-700 hover:underline"><BookOpen class="h-4 w-4" aria-hidden="true" />{{ copy.steps }}</RouterLink>
            <HelpEntryCard :entry="selected" heading="h2" :language="language" :references="catalog!.references" :copied="copied" @copy="copyLink" />
            <section v-if="modelParameters.length" class="mt-6"><h2 class="mb-3 text-base font-semibold text-slate-800">{{ copy.parameters }}</h2><div class="space-y-3"><HelpEntryCard v-for="entry in modelParameters" :key="entry.id" :entry="entry" :language="language" :references="catalog!.references" :copied="copied" @copy="copyLink" /></div></section>
            <section v-if="related.length" class="mt-6 border-t border-slate-200 pt-5"><h3 class="text-sm font-semibold text-slate-800">{{ copy.related }}</h3><div class="mt-3 flex flex-wrap gap-2"><RouterLink v-for="entry in related" :key="entry.id" :to="linkTo(entry.id)" class="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 hover:border-blue-300 hover:text-blue-700">{{ textFor(entry).title }}</RouterLink></div></section>
          </section>

          <section v-else-if="group === 'references' && !query">
            <h1 ref="pageHeading" tabindex="-1" class="text-xl font-semibold text-slate-900 outline-none">{{ copy.references }}</h1>
            <ol class="mt-5 space-y-3"><li v-for="(reference, id, index) in catalog?.references" :key="id" class="rounded-xl border border-slate-200 bg-white p-4"><a :href="reference.url" target="_blank" rel="noopener noreferrer" class="text-sm font-medium leading-6 text-blue-700 hover:underline">[{{ index + 1 }}] {{ reference.title }}<ExternalLink class="ml-2 inline h-3.5 w-3.5" aria-hidden="true" /></a><p class="mt-1 text-xs leading-5 text-slate-500">{{ reference.citation }}</p></li></ol>
          </section>

          <section v-else>
            <h1 ref="pageHeading" tabindex="-1" class="text-xl font-semibold text-slate-900 outline-none">{{ query ? `${matches.length} ${copy.results}` : route.query.article ? copy.noArticle : groupLabel(group) }}</h1>
            <div v-if="!matches.length" class="py-12 text-center"><Search class="mx-auto h-8 w-8 text-slate-300" aria-hidden="true" /><h2 class="mt-4 font-medium text-slate-800">{{ copy.empty }}</h2><p class="mt-2 text-sm text-slate-500">{{ copy.emptyHint }}</p><button type="button" class="mt-4 text-sm text-blue-700 underline underline-offset-4" @click="selectGroup('all')">{{ copy.clear }}</button></div>
            <div class="mt-4 grid gap-3">
              <RouterLink v-for="entry in matches" :key="entry.id" :to="linkTo(entry.id)" class="group flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-4 hover:border-blue-300">
                <div class="min-w-0 flex-1"><div class="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ entry.group === 'guides' ? copy[entry.guide_section || 'basics'] : entry.model }} · {{ groupLabel(entry.group) }}</div><h2 class="text-sm font-semibold text-slate-800 group-hover:text-blue-700">{{ textFor(entry).title }}</h2><p class="mt-1 text-sm leading-6 text-slate-500">{{ textFor(entry).summary }}</p></div><ChevronRight class="mt-4 h-4 w-4 shrink-0 text-slate-300 group-hover:text-blue-500" aria-hidden="true" />
              </RouterLink>
            </div>
          </section>
        </main>
      </div>
    </div>
  </AppFrame>
</template>

<style scoped>
.help-page { background: #fafbfd; }
.help-layout { display: grid; grid-template-columns: 176px minmax(0, 960px); align-items: start; gap: 24px; padding: 24px; }
.help-page[lang="en-US"] .help-layout { grid-template-columns: 208px minmax(0, 900px); gap: 32px; }
.help-article { max-width: 840px; }
.help-sidebar { position: sticky; top: 16px; }
.help-nav { max-height: calc(100dvh - 100px); overflow-y: auto; }
.help-search::-webkit-search-cancel-button { display: none; }
.help-page :is(button, a):focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
@media (max-width: 768px) {
  .help-layout, .help-page[lang="en-US"] .help-layout { grid-template-columns: minmax(0, 1fr); gap: 16px; padding: 16px; }
  .help-sidebar { top: 0; z-index: 10; padding: 8px 0; background: #fafbfd; }
  .help-nav { max-height: 55dvh; margin-top: 8px; }
  .help-page :deep(.help-entry), .help-page h2[id] { scroll-margin-top: 68px; }
}
</style>

<route lang="yaml">
meta:
  layout: blank
</route>
