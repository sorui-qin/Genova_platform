<template>
  <section class="postprocessing-draft min-w-0 space-y-3 rounded-lg border border-violet-200 bg-violet-50/30 p-3" data-testid="postprocessing-draft-card">
    <header v-if="showActions !== false" class="space-y-1"><h3 class="font-semibold">{{ L('评价与筛选方案', 'Evaluation Plan') }}</h3><p class="text-sm">{{ L('先计算分子性质并预筛，再对入选分子进行对接与评估。', 'Calculate molecular properties, prefilter, then dock and evaluate passing molecules.') }}</p></header>
    <div v-if="remoteChanged" role="alert" class="space-y-2 text-sm text-amber-800"><p>{{ L('方案已更新，当前编辑内容已保留。请核对最新方案。', 'The plan changed. Your edits are preserved. Review the latest plan.') }}</p><Button size="sm" variant="outline" @click="loadLatest">{{ L('载入最新方案', 'Load latest plan') }}</Button></div>
    <section class="space-y-2"><h4 class="text-sm font-medium">{{ L('性质预筛', 'Property prefilters') }}</h4><p v-if="JSON.stringify(prefilters) === JSON.stringify(defaultPrefilters())" class="text-xs text-slate-600">{{ L('默认保留 QED > 0.4、SA Score < 5 的分子，并排除含三个及以上相连稠环的分子。', 'Keep QED > 0.4 and SA Score < 5; exclude highly fused ring systems.') }}</p><TarPassFilterEditor v-model="prefilters" :metrics="propertyMetrics" :disabled="busy" /></section>
    <ReferenceDatasetPicker v-model="referenceDatasetId" :disabled="busy" @busy="uploading = $event" />
    <details :open="Boolean(interactionDraft)" class="rounded border bg-white px-2 py-1">
      <summary class="cursor-pointer text-sm font-medium">{{ L('关键相互作用', 'Key interactions') }} · {{ interactions.length }}</summary>
      <section class="mt-2 space-y-2">
      <p class="text-xs text-slate-600">{{ L('指定希望与哪些残基形成作用；这里记录匹配情况，需要时可在结果中据此筛选。', 'Specify interactions with receptor residues. Match results can be used to filter completed results.') }}</p>
      <article v-for="(rule, index) in interactions" :key="index" class="space-y-2 rounded border p-2">
        <div class="flex flex-wrap justify-between gap-2 text-sm"><span>{{ interactionLabel(rule.interaction_type) }} · {{ rule.match_mode === 'all' ? L('全部残基', 'All residues') : L('任一残基', 'Any residue') }}</span><div class="flex gap-3"><button type="button" :disabled="Boolean(interactionDraft)" class="text-blue-700" @click="editInteraction(index)">{{ L('编辑', 'Edit') }}</button><button type="button" @click="interactions.splice(index, 1)">{{ L('移除', 'Remove') }}</button></div></div>
        <div class="flex flex-wrap gap-2"><span v-for="residue in rule.residues" :key="residueKey(residue)" class="rounded bg-blue-50 px-2 py-1 text-sm">{{ residueLabel(residue) }}</span></div>
      </article>
      <div v-if="interactionDraft" class="space-y-2 rounded border border-blue-200 bg-white p-2">
        <label class="block space-y-1 text-sm"><span>{{ L('相互作用类型', 'Interaction type') }}</span><select v-model="interactionDraft.interaction_type" class="block w-full min-w-0 rounded border p-2"><option v-for="kind in interactionTypes" :key="kind" :value="kind">{{ interactionLabel(kind) }}</option></select></label>
        <label class="block space-y-1 text-sm"><span>{{ L('所选残基如何匹配', 'Match selected residues') }}</span><select v-model="interactionDraft.match_mode" class="block w-full rounded border p-2"><option value="any">{{ L('至少一个残基形成作用', 'At least one residue interacts') }}</option><option value="all">{{ L('每个残基都形成作用', 'Every residue interacts') }}</option></select></label>
        <ResidueSelectionList :residues="interactionDraft.residues" :available-residues="residues" :hint="L('选择参与匹配的残基', 'Select residues for matching')" @toggle="toggleResidue" @clear="interactionDraft.residues = []" />
        <div class="flex flex-wrap gap-2"><Button size="sm" :disabled="!interactionDraft.residues.length" @click="saveInteraction">{{ L('确认规则', 'Confirm rule') }}</Button><Button size="sm" variant="outline" @click="interactionDraft = null">{{ L('取消', 'Cancel') }}</Button></div>
      </div>
      <Button v-else size="sm" variant="outline" :disabled="busy || !interactionTypes.length" @click="editInteraction()">{{ L('添加相互作用规则', 'Add interaction rule') }}</Button>
      <p v-if="interactionDraft" role="status" class="text-sm text-amber-800">{{ L('请先确认或取消正在编辑的规则，再批准。', 'Confirm or cancel the rule being edited before approval.') }}</p>
      </section>
    </details>
    <div v-if="showActions !== false" class="sticky bottom-0 flex flex-wrap justify-end gap-2 border-t bg-white/95 pt-2"><Button :disabled="busy || !valid" @click="emit('save', payload())">{{ L('批准并执行', 'Approve and execute') }}</Button><Button variant="outline" :disabled="busy" @click="emit('skip')">{{ L('跳过评价', 'Skip evaluation') }}</Button></div>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { defaultPrefilters } from '@/utils/tarpassDefaults'
import TarPassFilterEditor from '@/components/molecule/TarPassFilterEditor.vue'
import ReferenceDatasetPicker from '@/components/molecule/ReferenceDatasetPicker.vue'
import { useTarPassMetrics, expandFilters, filterDrafts, validFilters, type MetricFilterDraft, type MetricInfo } from '@/components/molecule/useTarPassMetrics'
import ResidueSelectionList from '@/components/protein-preparation/ResidueSelectionList.vue'
import type { ResidueRef } from '@/types/proteinContext'
type Interaction = { interaction_type: string; match_mode: 'any' | 'all'; residues: ResidueRef[] }
const props = withDefaults(defineProps<{ initial?: Record<string, any> | null; sourceJobId?: string; contextId?: string; datasets?: Array<Record<string, any>>; metrics?: MetricInfo; interactionTypes?: string[]; residues?: ResidueRef[]; busy: boolean; showActions?: boolean }>(), { initial: null, sourceJobId: '', contextId: '', datasets: () => [], metrics: () => ({}), interactionTypes: () => [], residues: () => [] })
const emit = defineEmits<{ save: [payload: Record<string, any>]; skip: []; dirty: [value: boolean]; valid: [value: boolean]; draft: [payload: Record<string, any>] }>()
const { locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const { interactionLabel } = useTarPassMetrics(() => props.metrics)
const propertyMetrics = computed(() => Object.fromEntries(Object.entries(props.metrics).filter(([key]) => !key.includes('.'))))
const source = computed(() => { const initial = props.initial || {}; return initial.postprocessing ? { ...initial, ...initial.postprocessing, ...(initial.selection !== undefined ? { selection: initial.selection } : {}) } : initial })
const prefilters = ref<MetricFilterDraft[]>(defaultPrefilters()), referenceDatasetId = ref(''), interactions = ref<Interaction[]>([])
const interactionDraft = ref<Interaction | null>(null), editingInteraction = ref<number | null>(null)
const uploading = ref(false), remoteChanged = ref(false), initialSnapshot = ref('')
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value))
function payload() { return { enabled: true, ...(props.sourceJobId ? { source_job_id: props.sourceJobId } : {}), prefilters: expandFilters(prefilters.value), reference_dataset_id: referenceDatasetId.value || null, key_interactions: clone(interactions.value), selection: clone(source.value.selection || {sort_by:'molecule_id',descending:false,top_k:null}) } }
function loadLatest() {
  prefilters.value = filterDrafts(source.value.prefilters ?? defaultPrefilters())
  referenceDatasetId.value = source.value.reference_dataset_id || ''
  interactions.value = clone(source.value.key_interactions || [])
  interactionDraft.value = null; remoteChanged.value = false
  initialSnapshot.value = JSON.stringify(payload())
}
loadLatest()
const dirty = computed(() => Boolean(interactionDraft.value) || JSON.stringify(payload()) !== initialSnapshot.value)
watch(() => JSON.stringify(source.value), () => { if (dirty.value) remoteChanged.value = true; else loadLatest() })
const valid = computed(() => !interactionDraft.value && !uploading.value && !remoteChanged.value && validFilters(prefilters.value, propertyMetrics.value) && prefilters.value.every(rule => (!['reference_similarity','scaffold_similarity'].includes(rule.metric) || referenceDatasetId.value)) && interactions.value.every(rule => props.interactionTypes.includes(rule.interaction_type) && rule.residues.length))
watch(valid, value => emit('valid', Boolean(value)), { immediate: true })
watch(dirty, value => emit('dirty', value), { immediate: true })
watch([prefilters, referenceDatasetId, interactions], () => emit('draft', payload()), { deep: true, immediate: true })
function editInteraction(index: number | null = null) { editingInteraction.value = index; interactionDraft.value = index === null ? {interaction_type:props.interactionTypes[0] || 'H-Bond',match_mode:'any',residues:[]} : clone(interactions.value[index]) }
function residueKey(residue: ResidueRef) { return JSON.stringify(residue) }
function residueLabel(residue: ResidueRef) { return `${residue.chain_id || ''}:${residue.residue_name || ''}${residue.residue_number}${residue.insertion_code || ''}` }
function toggleResidue(residue: ResidueRef) { if (!interactionDraft.value) return; const index = interactionDraft.value.residues.findIndex(item => residueKey(item) === residueKey(residue)); if (index >= 0) interactionDraft.value.residues.splice(index, 1); else interactionDraft.value.residues.push(residue) }
function saveInteraction() { if (!interactionDraft.value?.residues.length) return; if (editingInteraction.value === null) interactions.value.push(clone(interactionDraft.value)); else interactions.value[editingInteraction.value] = clone(interactionDraft.value); interactionDraft.value = null }
</script>
<style scoped>.postprocessing-draft { container-type: inline-size; }</style>
