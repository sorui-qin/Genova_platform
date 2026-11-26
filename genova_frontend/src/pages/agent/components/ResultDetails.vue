<template>
  <section class="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50/40 p-4 text-sm">
    <h3 class="font-semibold">{{ t('agent.ui.querySummary') }}</h3>
    <dl class="grid grid-cols-2 gap-3 sm:grid-cols-4"><div v-for="(label, key) in counts" :key="key"><dt class="text-xs text-slate-500">{{ t('agent.ui.' + label) }}</dt><dd class="text-xl font-semibold tabular-nums">{{ result[key] ?? '—' }}</dd></div></dl>
    <p v-if="result.requested_count != null && result.total_count != null && result.total_count < result.requested_count" role="alert" class="text-amber-800">{{ t('agent.ui.shortfall', {requested:result.requested_count,actual:result.total_count,gap:result.requested_count-result.total_count}) }}</p>
    <p v-if="['partial','failed','invalid','prefiltered'].some(key => result.status_counts?.[key] > 0)" role="alert" class="text-amber-800">{{ t('agent.ui.partial') }}</p>
    <p v-if="result.returned_count === 0" class="text-amber-800">{{ t('agent.ui.noRows') }}</p>
    <p class="text-xs text-slate-600">{{ t('agent.ui.queryScope') }} · {{ result.filters?.length ? result.filters.map((f:any) => `${f.metric} ${f.op} ${f.value}`).join(' · ') : t('agent.ui.none') }} · {{ t('agent.ui.missingMetrics') }}</p>
    <p v-for="warning in result.warnings || []" :key="warning" class="text-amber-800">{{ warning }}</p>
    <template v-if="Object.keys(result.summary?.metric_summaries || {}).length">
      <p class="text-xs text-slate-500">{{ t('agent.ui.summaryScope') }} · {{ scopeLabel }}</p>
      <div class="overflow-x-auto"><table class="w-full text-left text-xs"><thead><tr><th>{{ t('agent.ui.metric') }}</th><th>{{ t('agent.ui.count') }}</th><th>{{ t('agent.ui.missing') }}</th><th>{{ t('agent.ui.mean') }}</th></tr></thead><tbody><tr v-for="(value, key) in result.summary.metric_summaries" :key="key" class="border-t"><th class="py-2 pr-2 font-normal">{{ metricLabel(String(key)) }}</th><td>{{ value.count ?? '—' }}</td><td :class="value.missing > 0 ? 'text-amber-800' : ''">{{ value.missing ?? '—' }}</td><td>{{ format(value.mean) }} {{ specs?.[key]?.unit }}</td></tr></tbody></table></div>
    </template>
    <div v-if="result.rows?.length === 1" class="rounded-lg bg-white p-3"><p class="mb-2 text-xs text-slate-500">{{ result.rows[0].molecule_id }} · {{ t('agent.ui.returnedScope') }}</p><dl class="flex flex-wrap gap-4"><div v-for="[key,value] in metricEntries(result.rows[0].metrics || {}).filter(([key]) => ['qed','sa_score','docked.affinity'].includes(key))" :key="key"><dt class="text-xs text-slate-500">{{ metricLabel(key) }}</dt><dd>{{ format(value) }} {{ specs?.[key]?.unit }}</dd></div></dl></div>
    <RouterLink v-if="result.postprocessing_job_id" class="inline-block text-blue-700 underline" :to="{path:'/postprocessing/results',query:{job_id:result.postprocessing_job_id}}">{{ t('agent.ui.viewResults') }}</RouterLink>
    <details><summary class="cursor-pointer text-slate-500">{{ t('agent.ui.metricsDetails') }}</summary><div class="max-h-80 overflow-auto"><table class="w-full text-left text-xs"><tbody v-for="row in result.rows || []" :key="row.molecule_id"><tr class="bg-slate-100"><th colspan="2" class="p-2">{{ row.molecule_id }} · {{ row.status }}</th></tr><tr v-for="[key, value] in metricEntries(row.metrics || {})" :key="key" class="border-t"><td class="p-1">{{ metricLabel(key) }}</td><td>{{ format(value) }} {{ specs?.[key]?.unit }}</td></tr></tbody></table></div></details>
    <details><summary class="cursor-pointer text-slate-500">{{ t('agent.ui.advanced') }}</summary><pre class="max-h-80 overflow-auto whitespace-pre-wrap break-all p-2 text-xs">{{ JSON.stringify(result, null, 2) }}</pre></details>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
const props = defineProps<{result:Record<string,any>;specs?:Record<string,any>}>()
const {t,te} = useI18n()
const counts = {requested_count:'requested',total_count:'total',matched_count:'matched',returned_count:'returned'}
const scopeLabel = computed(() => t((props.result.summary_scope || props.result.summary?.scope) === 'matched' ? 'agent.ui.matchedScope' : (props.result.summary_scope || props.result.summary?.scope) === 'returned' ? 'agent.ui.returnedScope' : 'agent.ui.unknownScope'))
function metricLabel(key:string) {
  const [prefix, metric] = key.includes('.') ? key.split('.') : ['', key]
  const label = te('platform.metrics.' + metric) ? t('platform.metrics.' + metric) : props.specs?.[key]?.label || key
  return `${prefix && te('platform.' + prefix) ? t('platform.' + prefix) + ' / ' : ''}${label}`
}
const format = (value:any) => value == null ? '—' : typeof value === 'boolean' ? t(value ? 'agent.ui.on' : 'agent.ui.off') : typeof value === 'number' ? Number(value.toPrecision(6)).toString() : String(value)
function metricEntries(metrics:Record<string,any>, prefix=''):Array<[string,any]> {
  return Object.entries(metrics).flatMap(([key,value]) => value && typeof value === 'object' ? metricEntries(value, prefix+key+'.') : [[prefix+key,value] as [string,any]])
}
</script>
