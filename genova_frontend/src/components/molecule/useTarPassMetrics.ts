import { useI18n } from 'vue-i18n'

export type MetricInfo = Record<string, { type?: string; label?: string; unit?: string; descriptions?: Record<string, string> }>
export type MetricFilter = { metric: string; op: 'gt' | 'lt' | 'gte' | 'lte' | 'eq'; value: number }
export type MetricFilterDraft = { metric: string; op: MetricFilter['op'] | 'between'; value: number; upper?: number }

export function expandFilters(rules: MetricFilterDraft[]): MetricFilter[] {
  return rules.flatMap(rule => rule.op === 'between'
    ? [{ metric: rule.metric, op: 'gte' as const, value: rule.value }, { metric: rule.metric, op: 'lte' as const, value: rule.upper! }]
    : [{ metric: rule.metric, op: rule.op, value: rule.value }])
}

export function filterDrafts(rules: MetricFilter[]): MetricFilterDraft[] {
  const drafts: MetricFilterDraft[] = []
  for (let i = 0; i < rules.length; i++) {
    const rule = rules[i], next = rules[i + 1]
    if (rule.op === 'gte' && next?.op === 'lte' && next.metric === rule.metric) {
      drafts.push({ ...rule, op: 'between', upper: next.value }); i++
    } else drafts.push({ ...rule })
  }
  return drafts
}

export function filterIssue(rule: MetricFilterDraft, metrics: MetricInfo): string {
  if (!metrics[rule.metric]) return 'metric'
  if (metrics[rule.metric].type === 'boolean') return rule.op === 'eq' && [0, 1].includes(rule.value) ? '' : 'boolean'
  if (!['gt', 'lt', 'gte', 'lte', 'eq', 'between'].includes(rule.op)) return 'operator'
  if (!Number.isFinite(rule.value) || (rule.op === 'between' && !Number.isFinite(rule.upper))) return 'number'
  if (rule.op === 'between' && rule.value > rule.upper!) return 'range'
  return ''
}

export function validFilters(rules: MetricFilterDraft[], metrics: MetricInfo): boolean {
  const expanded = expandFilters(rules)
  if (expanded.length > 100 || rules.some(rule => filterIssue(rule, metrics))) return false
  const bounds = new Map<string, { lower: number; upper: number; lowerOpen: boolean; upperOpen: boolean }>()
  for (const rule of expanded) {
    if (metrics[rule.metric].type === 'boolean') continue
    const bound = bounds.get(rule.metric) || { lower: -Infinity, upper: Infinity, lowerOpen: false, upperOpen: false }
    if (['gt', 'gte', 'eq'].includes(rule.op) && rule.value >= bound.lower) {
      bound.lowerOpen = rule.op === 'gt' || (rule.value === bound.lower && bound.lowerOpen)
      bound.lower = rule.value
    }
    if (['lt', 'lte', 'eq'].includes(rule.op) && rule.value <= bound.upper) {
      bound.upperOpen = rule.op === 'lt' || (rule.value === bound.upper && bound.upperOpen)
      bound.upper = rule.value
    }
    bounds.set(rule.metric, bound)
    if (bound.lower > bound.upper || (bound.lower === bound.upper && (bound.lowerOpen || bound.upperOpen))) return false
  }
  return true
}

export function useTarPassMetrics(info: () => MetricInfo) {
  const { t, te, locale } = useI18n()
  const metricLabel = (key: string) => {
    if (key === 'molecule_id') return t('platform.moleculeId')
    const [prefix, metric] = key.includes('.') ? key.split('.') : ['', key]
    const label = te('platform.metrics.' + metric) ? t('platform.metrics.' + metric) : info()[key]?.label || key
    return `${prefix && te('platform.' + prefix) ? t('platform.' + prefix) + ' / ' : ''}${label}${info()[key]?.unit ? ` (${info()[key].unit})` : ''}`
  }
  const isBoolean = (key: string) => info()[key]?.type === 'boolean'
  const metricDescription = (key: string) => info()[key]?.descriptions?.[locale.value.startsWith('zh') ? 'zh-CN' : 'en-US'] || ''
  const preferredDescending = (key: string) => ['qed', 'complete', 'all_common', 'reference_similarity', 'scaffold_similarity', 'cnn_score', 'cnn_affinity', 'no_clashes', 'sucos', 'shape_similarity', 'electrostatic_similarity', 'matched_rate', 'fully_matched'].includes(key.split('.').pop() || '')
  const interactionLabel = (kind: string) => {
    const names: Record<string, string> = {
      'H-Bond': '氢键或盐桥', 'H-Bond donor': '氢键（配体为供体）', 'H-Bond acceptor': '氢键（配体为受体）',
      'Halogen bond': '卤键', 'Hydrophobic contact': '疏水接触', 'Pi-cation lAro': '阳离子–π（配体为芳环）',
      'Pi-cation pAro': '阳离子–π（蛋白为芳环）', 'Pi-stacking': 'π–π 堆积',
      'Salt Bridge lneg': '盐桥（配体带负电）', 'Salt Bridge pneg': '盐桥（蛋白带负电）',
    }
    return locale.value.startsWith('zh') ? names[kind] || kind : kind === 'H-Bond' ? 'Hydrogen bond or salt bridge' : kind
  }
  return { metricLabel, metricDescription, isBoolean, preferredDescending, interactionLabel }
}
