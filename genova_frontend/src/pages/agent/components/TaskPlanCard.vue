<template>
  <section class="space-y-3" data-testid="task-plan">
    <header class="flex items-center justify-between gap-3"><h3 class="font-semibold">{{ stageLabel }}</h3><span class="text-xs text-slate-500">{{ stateLabel }}</span></header>
    <p class="text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{{ draft.goal }}</p>
    <p class="text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{{ draft.completion }}</p>
    <div v-if="stale" role="alert" class="space-y-2 text-sm text-amber-800"><p>{{ L('方案已更新，当前编辑内容已保留。请载入最新方案后核对。', 'The plan changed. Your edits are preserved. Load the latest plan to review.') }}</p><Button variant="outline" @click="loadLatest">{{ L('载入最新方案', 'Load latest plan') }}</Button></div>
    <fieldset :disabled="!editable || busy" class="min-w-0 space-y-3 disabled:opacity-70">
      <WorkflowParameters ref="parameters" v-if="draft.workflow && stage === 'generation'" :key="localVersion" :proposal="workflowProposal" :generators="generators" :busy="busy" :show-actions="false" :edit-spec="editSpec" :edit-mode="editMode" @draft="updateGeneration" @valid="parametersValid = $event" @edit-delete="emit('editDelete')" />
      <PostprocessingDraftCard v-else-if="draft.workflow && stage === 'postprocessing'" :key="localVersion" :initial="postInitial" :context-id="draft.workflow.protein_context_id || ''" :metrics="metrics" :datasets="datasets" :interaction-types="interactionTypes" :residues="residues" :busy="busy" :show-actions="false" @draft="updatePostprocessing" @valid="parametersValid = $event" />
      <PreparationSummary v-else-if="draft.preparation" :payload="draft.preparation" :pending="editable" />
      <details v-if="stage === 'generation' && draft.sampling"><summary class="cursor-pointer text-sm">{{ L('数量补采样', 'Quantity resampling') }}</summary><div class="mt-3 space-y-3 text-sm"><label class="flex gap-2"><input v-model="draft.sampling.enabled" type="checkbox" />{{ L('数量不足时补采样', 'Resample a quantity shortfall') }}</label><label v-if="draft.sampling.enabled" class="flex items-center gap-2">{{ L('最多补采样次数', 'Maximum additional batches') }}<input v-model.number="draft.sampling.max_rounds" type="number" min="0" max="10" class="w-20 rounded border p-2" /></label></div></details>
    </fieldset>
    <div v-if="stage === 'generation' && draft.workflow?.generator === 'delete' && !editSpec" role="status" class="space-y-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
      <p>{{ contextPreparing ? L('正在准备模型输入，完成后可编辑片段。','Model inputs are being prepared. Fragment editing will be available when ready.') : L('请在结构编辑器中选择并保存 DELETE 片段，之后才能批准方案。','Choose and save DELETE fragments in the structure editor before approving this plan.') }}</p>
      <Button size="sm" variant="outline" :disabled="busy" @click="emit('editDelete')">{{ L('编辑片段','Edit fragments') }}</Button>
    </div>
    <div v-if="plan.run.error" role="alert" class="space-y-2 text-sm text-red-700"><p>{{ L('阶段执行失败，已有结果已保留。可修改方案后重新批准。','This stage failed. Existing results are preserved. Revise the plan and approve it again.') }}</p><details><summary class="cursor-pointer">{{ L('错误详情','Error details') }}</summary><pre class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words">{{ plan.run.error }}</pre></details></div>
    <div class="flex flex-wrap gap-2">
      <Button v-if="editable && stage === 'preparation'" :disabled="busy || stale" @click="$emit('reviewPreparation')">{{ L('预览结构与准备方案', 'Review structure and preparation') }}</Button>
      <template v-else-if="editable"><Button variant="outline" :disabled="busy || !valid" @click="saveCurrent">{{ L('保存方案', 'Save plan') }}</Button><Button :disabled="busy || !valid" @click="approveCurrent">{{ stage === 'postprocessing' ? L('批准并开始评价', 'Approve and Run Evaluation') : L('批准并执行生成 / 优化', 'Approve and run generation / optimization') }}</Button></template>
      <Button v-if="editable && stage === 'postprocessing'" variant="outline" :disabled="busy" @click="$emit('skip')">{{ L('跳过评价', 'Skip evaluation') }}</Button>
      <Button v-if="['running','analyzing'].includes(plan.state)" variant="outline" :disabled="busy" @click="$emit('pause')">{{ L('暂停后修订', 'Pause to revise') }}</Button>
      <Button v-if="plan.state === 'paused'" variant="outline" :disabled="busy" @click="$emit('resume')">{{ L('继续执行', 'Resume') }}</Button>
    </div>
    <details v-if="plan.history && plan.history.length > 1" class="text-sm text-slate-500"><summary class="cursor-pointer">{{ L('方案历史', 'Plan history') }}</summary><ol class="mt-2 space-y-2"><li v-for="version in plan.history" :key="version.version">v{{ version.version }} · {{ version.created_at.slice(0,16).replace('T',' ') }}</li></ol></details>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import type { AgentTaskPlan, AgentTaskPlanDefinition } from '@/api/genovaBackend'
import type { ResidueRef } from '@/types/proteinContext'
import WorkflowParameters from './WorkflowParameters.vue'
import PostprocessingDraftCard from './PostprocessingDraftCard.vue'
import PreparationSummary from './PreparationSummary.vue'
const props = defineProps<{ plan: AgentTaskPlan; busy: boolean; contextPreparing?: boolean; generators: Record<string, any>; metrics?: Record<string, any>; editSpec?: string; editMode?: string; datasets?: Array<Record<string, any>>; interactionTypes?: string[]; residues?: ResidueRef[] }>()
const emit = defineEmits<{ approve: [definition: AgentTaskPlanDefinition]; save: [definition: AgentTaskPlanDefinition]; draft: [definition: AgentTaskPlanDefinition]; reviewPreparation: []; pause: []; resume: []; skip: []; editDelete: [] }>()
const { locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const draft = ref<AgentTaskPlanDefinition>(JSON.parse(JSON.stringify(props.plan.definition)))
watch(draft, value => emit('draft', value), { deep: true, immediate: true })
const initial = ref(JSON.parse(JSON.stringify(props.plan.definition))), localVersion = ref(props.plan.version), stale = ref(false)
function loadLatest() { initial.value = JSON.parse(JSON.stringify(props.plan.definition)); draft.value = JSON.parse(JSON.stringify(initial.value)); localVersion.value = props.plan.version; stale.value = false }
watch(() => JSON.stringify([props.plan.version, props.plan.definition]), () => { if (JSON.stringify(draft.value) === JSON.stringify(initial.value) || JSON.stringify(draft.value) === JSON.stringify(props.plan.definition)) loadLatest(); else stale.value = true })
const parameters = ref<InstanceType<typeof WorkflowParameters> | null>(null)
const parametersValid = ref(true)
function approveCurrent() {
  if (!valid.value || parameters.value?.validate() === false) return
  emit('approve', draft.value)
}
function saveCurrent() {
  if (!valid.value || parameters.value?.validate() === false) return
  emit('save', draft.value)
}
const stage = computed(() => draft.value.stage || (props.plan.run.source_workflow_id ? 'postprocessing' : draft.value.workflow ? 'generation' : 'preparation'))
const stageLabel = computed(() => ({ preparation: L('蛋白准备方案','Protein preparation plan'), generation: L('生成 / 优化方案','Generation / optimization plan'), postprocessing: L('评价与筛选方案','Evaluation Plan') }[stage.value]))
const editable = computed(() => ['awaiting_approval','paused','blocked'].includes(props.plan.state))
const valid = computed(() => !stale.value && parametersValid.value && !(stage.value === 'generation' && draft.value.workflow?.generator === 'delete' && !props.editSpec) && (!draft.value.sampling || Number.isInteger(draft.value.sampling.max_rounds) && draft.value.sampling.max_rounds >= 0 && draft.value.sampling.max_rounds <= 10))
const workflowProposal = computed(() => ({payload: {plan: initial.value.workflow, plan_version: localVersion.value}}))
const postInitial = computed(() => ({ ...initial.value.workflow?.postprocessing, selection: initial.value.workflow?.selection, key_interactions: initial.value.key_interactions, reference_dataset_id: initial.value.reference_dataset_id }))
function updateGeneration(value: Record<string, any>) { if (draft.value.workflow) draft.value.workflow = { ...draft.value.workflow, ...value.plan } }
function updatePostprocessing(value: Record<string, any>) {
  if (!draft.value.workflow) return
  draft.value.workflow.postprocessing = { enabled: true, prefilters: value.prefilters }
  draft.value.workflow.selection = value.selection
  draft.value.key_interactions = value.key_interactions
  draft.value.reference_dataset_id = value.reference_dataset_id
}
const stateLabel = computed(() => ({awaiting_approval:L('待批准','Awaiting approval'),running:L('执行中','Running'),pause_requested:L('暂停中','Pausing'),paused:L('已暂停','Paused'),analyzing:L('分析中','Analyzing'),completed:L('已完成','Completed'),partial:L('部分完成','Partial'),canceled:L('已取消','Canceled'),blocked:L('执行失败','Failed')}[props.plan.state] || props.plan.state))
</script>
