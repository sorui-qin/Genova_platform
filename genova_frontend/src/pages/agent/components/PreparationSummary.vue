<template>
  <div class="space-y-3 text-sm">
    <p v-if="pending" class="text-amber-800">{{ t('agent.ui.proposed') }}</p>
    <dl class="grid gap-x-4 gap-y-2 sm:grid-cols-2">
      <div>
        <dt class="text-xs text-slate-500">{{ t('agent.ui.structureFields.prepared_spec') }}</dt>
        <dd class="mt-1">{{ payload.name || t('agent.ui.unavailable') }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ t('agent.ui.structureFields.protein_file_id') }}</dt>
        <dd class="mt-1 break-all">{{ filename || source.file_name || source.original_filename || source.model_id || source.file_id || t('agent.ui.unavailable') }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ t('agent.ui.structureFields.preparation') }}</dt>
        <dd class="mt-1">{{ preparationSummary }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ t('agent.ui.protonationPolicy') }}</dt>
        <dd class="mt-1">{{ protonationSummary }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ t('agent.ui.structureFields.prepared_receptor_id') }}</dt>
        <dd class="mt-1">{{ excludedCount }} {{ t('agent.ui.excludedComponents') }}</dd>
      </div>
      <div v-if="chainSelection">
        <dt class="text-xs text-slate-500">{{ L('蛋白链', 'Protein chains') }}</dt>
        <dd class="mt-1 break-words">{{ chainSelection }}</dd>
      </div>
    </dl>
    <p v-if="payload.chain_selection_reason" class="whitespace-pre-wrap">{{ payload.chain_selection_reason }}</p>
    <p v-for="warning in payload.warnings || []" :key="warning" class="text-amber-800">{{ warning }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getComponentManifest } from '@/api/proteinContext'
import type { ComponentManifest } from '@/types/proteinContext'

const props = defineProps<{ payload: Record<string, any>; pending: boolean; filename?: string }>()
const { t, locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const preparedSpec = computed(() => props.payload?.prepared_spec || props.payload || {})
const source = computed(() => preparedSpec.value.source || {})
const preparation = computed(() => preparedSpec.value.preparation || {})
const excludedCount = computed(() => Array.isArray(preparedSpec.value.edits?.excluded_component_ids) ? preparedSpec.value.edits.excluded_component_ids.length : 0)
const manifest = ref<ComponentManifest | null>(null)
watch(source, async value => {
  manifest.value = null
  if (!value.dataset_id || !value.file_id || !value.sha256 || !value.model_id) return
  try { manifest.value = (await getComponentManifest(value)).data } catch { /* The editable structure view remains available. */ }
}, { immediate: true })
const chainSelection = computed(() => {
  const proteins = manifest.value?.components.filter(component => component.selection_kind === 'chain_records') || []
  if (!proteins.length) return ''
  const edits = preparedSpec.value.edits || {}
  const excluded = new Set(edits.excluded_component_ids || [])
  const retained = new Set(edits.retained_component_ids || [])
  const retainedChains = proteins.filter(component => retained.has(component.component_id))
  const hasExplicitSelection = retainedChains.length > 0 || proteins.some(component => excluded.has(component.component_id))
  if (!hasExplicitSelection) return L('全部蛋白链', 'All protein chains')
  const selected = retainedChains.length ? retainedChains : proteins.filter(component => !excluded.has(component.component_id))
  if (!selected.length) return L('未选择蛋白链', 'No protein chain selected')
  const target = proteins.find(component => component.component_id === props.payload.target_chain_component_id)
  const scope = `${props.pending ? L('建议保留：', 'Suggested: ') : L('保留：', 'Selected: ')}${selected.map(chainLabel).join('、')}`
  return target ? `${L('目标链：', 'Target chain: ')}${chainLabel(target)} · ${scope}` : scope
})
function chainLabel(component: ComponentManifest['components'][number]) {
  const atom = component.atoms[0]
  const authorChain = atom.author_chain_id || '∅'
  const duplicates = manifest.value!.components.filter(item => item.selection_kind === 'chain_records' && (item.atoms[0].author_chain_id || '∅') === authorChain).length > 1
  const identity = atom.label_asym_id || atom.chain_instance_id.split(':chain:').pop() || atom.chain_instance_id
  return `${authorChain}${duplicates || atom.label_asym_id && atom.label_asym_id !== authorChain ? ` (${identity})` : ''}`
}
const preparationSummary = computed(() => [
  preparation.value.receptor_policy === 'protein_metals_v1' ? L('保留蛋白与金属','Keep protein and metals') : '',
  preparation.value.water_policy === 'remove_all' ? L('移除水','Remove water') : '',
  preparation.value.repair_missing_atoms ? L('修复缺失原子','Repair missing atoms') : '',
  preparation.value.nonstandard_policy === 'standardize_supported' ? L('标准化支持的残基','Standardize supported residues') : '',
].filter(Boolean).join(' · ') || t('agent.ui.unavailable'))
const protonationSummary = computed(() => {
  const policy = preparation.value.protonation_policy === 'recompute' ? L('重新计算质子化','Recompute protonation') : preparation.value.protonation_policy === 'preserve' ? L('保留质子化状态','Preserve protonation') : t('agent.ui.unavailable')
  return preparation.value.ph == null ? policy : `${policy} · pH ${preparation.value.ph}`
})
</script>
