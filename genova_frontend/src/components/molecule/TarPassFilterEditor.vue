<template>
  <fieldset :disabled="disabled" class="filter-editor min-w-0 space-y-2">
    <div v-for="(rule, index) in model" :key="index" class="filter-row" :class="{ 'boolean-row': isBoolean(rule.metric), 'range-row': rule.op === 'between' }">
      <select v-model="rule.metric" :aria-label="L('指标', 'Metric')" class="metric-input filter-metric" @change="resetRule(rule)"><optgroup v-for="group in groups" :key="group.key" :label="group.label"><option v-for="key in group.keys" :key="key" :value="key">{{ metricLabel(key) }}</option></optgroup></select>
      <select v-if="!isBoolean(rule.metric)" v-model="rule.op" :aria-label="L('比较方式', 'Comparison')" class="metric-input filter-comparison" @change="changeOperator(rule)"><option value="gt">&gt;</option><option value="lt">&lt;</option><option value="gte">≥</option><option value="lte">≤</option><option value="eq">=</option><option value="between">{{ L('区间', 'Range') }}</option></select>
      <select v-if="isBoolean(rule.metric)" v-model.number="rule.value" :aria-label="L('取值', 'Value')" class="metric-input filter-value"><option :value="1">{{ L('是', 'Yes') }}</option><option :value="0">{{ L('否', 'No') }}</option></select>
      <div v-else class="filter-value filter-values">
        <input v-model.number="rule.value" type="number" step="any" :aria-label="rule.op === 'between' ? L('下限', 'Lower bound') : L('阈值', 'Threshold')" :aria-invalid="Boolean(filterIssue(rule, metrics))" class="metric-input" />
        <template v-if="rule.op === 'between'"><span class="text-slate-400">–</span><input v-model.number="rule.upper" type="number" step="any" :aria-label="L('上限', 'Upper bound')" :aria-invalid="Boolean(filterIssue(rule, metrics))" class="metric-input" /></template>
      </div>
      <button type="button" class="filter-remove whitespace-nowrap text-xs text-slate-500 hover:text-red-700" @click="model.splice(index, 1)">{{ L('移除', 'Remove') }}</button>
      <span class="filter-help"><MetricHelp :metric="rule.metric" :label="metricLabel(rule.metric)" /></span>
      <p v-if="filterIssue(rule, metrics)" role="alert" class="col-span-full text-xs text-red-700">{{ issueText(filterIssue(rule, metrics)) }}</p>
    </div>
    <p v-if="expandFilters(model).length > 100" role="alert" class="text-xs text-red-700">{{ L('筛选最多支持 100 个比较条件；一个区间占两个条件。', 'Use at most 100 comparisons; each range uses two.') }}</p>
    <p v-else-if="model.every(rule => !filterIssue(rule, metrics)) && !validFilters(model, metrics)" role="alert" class="text-xs text-red-700">{{ L('同一指标的筛选条件互相冲突，请调整上下限。', 'Conditions for the same metric conflict; adjust the bounds.') }}</p>
    <button type="button" class="text-sm text-blue-700" @click="addRule">{{ L('添加筛选条件', 'Add filter') }}</button>
  </fieldset>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MetricHelp from './MetricHelp.vue'
import { useTarPassMetrics, filterIssue, expandFilters, validFilters, type MetricFilterDraft, type MetricInfo } from './useTarPassMetrics'
const props = defineProps<{ metrics: MetricInfo; disabled?: boolean }>()
const model = defineModel<MetricFilterDraft[]>({ required: true })
const { locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const { metricLabel, isBoolean } = useTarPassMetrics(() => props.metrics)
const groups = computed(() => ['properties', 'original', 'docked'].map(key => ({ key, label: key === 'properties' ? L('分子性质', 'Molecular properties') : L(key === 'original' ? '原始姿态' : '对接姿态', key === 'original' ? 'Original pose' : 'Docked pose'), keys: Object.keys(props.metrics).filter(metric => key === 'properties' ? !metric.includes('.') : metric.startsWith(key + '.')) })).filter(group => group.keys.length))
function resetRule(rule: MetricFilterDraft) { delete rule.upper; rule.op = isBoolean(rule.metric) ? 'eq' : 'gte'; rule.value = 0 }
function changeOperator(rule: MetricFilterDraft) { if (rule.op !== 'between') delete rule.upper }
function addRule() { const metric = props.metrics.qed ? 'qed' : Object.keys(props.metrics)[0]; if (metric) model.value.push({ metric, op: isBoolean(metric) ? 'eq' : 'gt', value: isBoolean(metric) ? 0 : 0.4 }) }
function issueText(issue: string) {
  return ({ metric: L('请重新选择可用指标。', 'Select an available metric.'), operator: L('请选择有效的比较方式。', 'Select a valid comparison.'), boolean: L('请选择是或否。', 'Select Yes or No.'), number: L('请输入有效数值，区间两端均不能为空。', 'Enter valid numbers; both range bounds are required.'), range: L('下限不能大于上限。', 'The lower bound cannot exceed the upper bound.') } as Record<string, string>)[issue]
}
</script>
<style scoped>
.filter-editor { container-type: inline-size; }
.filter-row { display: grid; grid-template-columns: minmax(10rem, 1.4fr) 6.5rem minmax(7rem, 1fr) auto 1.5rem; grid-template-areas: "metric comparison value remove help"; gap: .5rem; align-items: center; }
.range-row { grid-template-columns: minmax(10rem, 1.2fr) 6.5rem minmax(12rem, 1fr) auto 1.5rem; }
.boolean-row { grid-template-columns: minmax(10rem, 1.4fr) minmax(7rem, 1fr) auto 1.5rem; grid-template-areas: "metric value remove help"; }
.filter-metric { grid-area: metric; }
.filter-comparison { grid-area: comparison; }
.filter-value { grid-area: value; }
.filter-remove { grid-area: remove; }
.filter-help { grid-area: help; }
.filter-values { display: flex; min-width: 0; align-items: center; gap: .375rem; }
.range-row .filter-values { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); }
.metric-input { width: 100%; min-width: 0; border: 1px solid var(--border-default); border-radius: .375rem; background: white; padding: .3rem; font-size: .8125rem; }
@container (max-width: 640px) {
  .filter-row { grid-template-columns: 6.5rem minmax(0, 1fr) auto 1.5rem; grid-template-areas: "metric metric remove help" "comparison value value value"; }
  .boolean-row { grid-template-columns: minmax(0, 1fr) minmax(5rem, .4fr) auto 1.5rem; grid-template-areas: "metric value remove help"; }
}
@container (max-width: 360px) {
  .filter-row:not(.boolean-row) { grid-template-areas: "metric metric remove help" "comparison comparison comparison comparison" "value value value value"; }
  .boolean-row { grid-template-areas: "metric metric remove help" "value value value value"; }
}
</style>
