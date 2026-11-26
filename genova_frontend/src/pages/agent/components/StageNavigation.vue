<template>
  <nav class="stage-navigation shrink-0 space-y-2" :aria-label="L('当前任务进度','Current task progress')">
    <div class="flex min-w-0 gap-1 overflow-x-auto pb-1"><button v-for="(stage, index) in stages" :key="stage.key" type="button" class="stage-button" :class="{ 'stage-current': stage.current, 'stage-complete': ['succeeded','ready','skipped'].includes(stage.status) }" :aria-current="stage.current ? 'step' : undefined" @click="$emit('select', stage)"><span class="stage-index" aria-hidden="true">{{ ['succeeded','ready','skipped'].includes(stage.status) ? '✓' : index + 1 }}</span><span class="min-w-0 text-left"><span class="block whitespace-nowrap font-medium">{{ label(stage.key) }}</span><span class="stage-state">{{ state(stage.status) }}</span></span></button></div>
    <p v-if="blocker" role="status" class="rounded-lg bg-blue-50/60 px-3 py-2 text-xs leading-relaxed text-blue-800">{{ blocker }}</p>
  </nav>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
defineProps<{stages:Array<{key:string;status:string;current?:boolean;job_id?:string}>;blocker?:string}>()
defineEmits<{select:[stage:{key:string;status:string;job_id?:string}]}>()
const { locale } = useI18n()
const L=(zh:string,en:string)=>locale.value.startsWith('zh')?zh:en
const label=(key:string)=>({input:L('输入','Input'),preparation:L('蛋白准备','Protein'),site:L('位点与输入','Site and inputs'),generation:L('生成 / 优化','Generate / optimize'),postprocessing:L('评价与筛选','Evaluation'),selection:L('结果与候选','Results')}[key]||key)
const state=(value:string)=>({pending:L('待开始','Pending'),waiting:L('待处理','Needs input'),awaiting_approval:L('待批准','Approval'),awaiting_postprocessing_approval:L('待批准评价','Evaluation approval'),authorized:L('已授权','Authorized'),running:L('执行中','Running'),queued:L('排队中','Queued'),succeeded:L('已完成','Complete'),ready:L('已就绪','Ready'),failed:L('失败','Failed'),skipped:L('已跳过','Skipped'),partial_succeeded:L('部分完成','Partial'),blocked:L('等待前置步骤','Blocked'),canceled:L('已取消','Canceled')}[value]||value)
</script>
<style scoped>
.stage-navigation { border-bottom: 1px solid #edf1f6; padding-bottom: 12px; }
.stage-button { display: flex; flex: 1 0 auto; align-items: center; gap: 7px; border: 1px solid transparent; border-radius: 9px; padding: 8px; color: #7d8b9f; font-size: 12px; transition: background 150ms; }
.stage-button:hover { background: #f6f8fc; }
.stage-index { display: grid; width: 23px; height: 23px; flex-shrink: 0; place-items: center; border: 1px solid #e1e7f0; border-radius: 50%; font-size: 11px; }
.stage-state { display: block; margin-top: 2px; color: #8b99ac; font-size: 11px; white-space: nowrap; }
.stage-current { border-color: #dce6f5; background: #f0f5fd; color: var(--action-primary); }
.stage-current .stage-index { border-color: var(--action-primary); background: var(--action-primary); color: #fff; }
.stage-current .stage-state { color: #536f99; }
.stage-complete .stage-index { border-color: #d3e8df; background: #eff8f3; color: #26845c; }
</style>
