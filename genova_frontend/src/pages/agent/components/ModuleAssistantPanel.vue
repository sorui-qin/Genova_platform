<template>
  <div class="flex min-h-full flex-col gap-4 text-sm">
    <p v-if="context.selected_ids?.length" class="break-all font-mono text-xs">{{ L('选中分子', 'Selected molecule') }}: {{ context.selected_ids.join(', ') }}</p>
    <p v-if="loading" role="status">{{ L('加载对话…', 'Loading conversation…') }}</p>
    <Button v-if="error && !session" variant="outline" @click="initialize">{{ L('重新加载', 'Reload') }}</Button>
    <article v-for="turn in session?.turns || []" :key="turn.id" class="space-y-3 border-b pb-4">
      <p class="whitespace-pre-wrap rounded-lg bg-slate-100 p-3 [overflow-wrap:anywhere]">{{ turn.message }}</p>
      <p v-if="turn.response.safety_decision === 'refuse'" role="status" class="font-semibold text-slate-700" data-testid="safety-refused">{{ L('已拒绝', 'Refused') }}</p>
      <div v-if="turn.response.message" class="prose prose-sm max-w-none break-words" v-html="markdown.render(turn.response.message)" />
      <p v-if="['queued', 'running'].includes(turn.status)" role="status">{{ L('正在分析…', 'Analyzing…') }}</p>
      <p v-if="['failed', 'interrupted'].includes(turn.status)" role="alert" class="text-red-700">{{ systemErrorMessage(turn.response, L('回答未完成', 'Reply incomplete')) }}</p>
      <details v-if="['failed', 'interrupted'].includes(turn.status) && (turn.response.error_message || turn.response.error_code)" class="text-xs text-slate-500"><summary>{{ t('agent.session.errorDetails') }}</summary><p class="whitespace-pre-wrap break-words">{{ turn.response.error_message || turn.response.error_code }}</p><p v-if="turn.response.trace_id">Trace: {{ turn.response.trace_id }}</p></details>
      <Button v-if="['failed', 'interrupted'].includes(turn.status) && (session?.research_task_state !== 'blocked' || turn.response.error_code === 'SAFETY_CHECK_UNAVAILABLE')" size="sm" variant="outline" :disabled="working" @click="retry(turn)">{{ L('重试', 'Retry') }}</Button>
      <section v-for="(suggestion, index) in suggestions(turn)" :key="index" class="space-y-3 rounded-lg border p-3">
        <p class="font-medium">{{ actionLabel(suggestion) }}</p>
        <p>{{ suggestion.reason }}</p>
        <dl class="space-y-2">
          <div v-for="change in suggestion.changes" :key="change.field">
            <dt class="font-mono text-xs">{{ change.field }}</dt>
            <dd class="mt-1 space-y-1 break-all font-mono text-xs"><p>{{ display(change.before) }} → {{ display(change.after) }}</p></dd>
          </div>
        </dl>
        <p v-if="conflict === `${turn.id}:${index}`" role="alert" class="text-amber-800">{{ L('相关字段已被修改。保留当前值，或明确选择使用建议值。', 'These fields changed. Keep your values or explicitly use the suggestion.') }}</p>
        <div class="flex flex-wrap gap-2">
          <Button size="sm" :disabled="working || applied.includes(`${turn.id}:${index}`)" @click="applySuggestion(suggestion, `${turn.id}:${index}`, conflict === `${turn.id}:${index}`)">{{ applied.includes(`${turn.id}:${index}`) ? L('已应用', 'Applied') : conflict === `${turn.id}:${index}` ? L('使用建议值', 'Use suggested values') : actionLabel(suggestion) }}</Button>
          <Button v-if="conflict === `${turn.id}:${index}`" size="sm" variant="outline" @click="conflict = ''">{{ L('保留当前值', 'Keep current values') }}</Button>
        </div>
      </section>
      <div v-if="turn.response.evidence_details?.length" class="flex flex-wrap gap-2 text-xs">
        <span v-for="source in turn.response.evidence_details" :key="source.chunk_id">{{ source.source_id }} · {{ source.section }}</span>
      </div>
    </article>
    <p v-if="error" role="alert" class="whitespace-pre-wrap text-red-700">{{ error }}</p>
    <p v-if="session?.research_task_state === 'blocked'" role="status" class="text-slate-600">{{ L('当前研究任务已阻断。若要开展独立的正常研究，请在主会话中发起新任务。', 'This research task is blocked. Start a new task in the main conversation for independent legitimate research.') }}</p>
    <Button v-if="pending" variant="outline" :disabled="working" @click="sendPending">{{ L('重试发送', 'Retry sending') }}</Button>
    <form class="sticky bottom-0 mt-auto space-y-2 bg-white pt-3" @submit.prevent="submit">
      <textarea v-model="message" rows="3" maxlength="4000" class="w-full resize-y rounded-lg border p-3" :aria-label="L('向智能体提问', 'Ask the assistant')" :placeholder="L('解释结果、比较指标或建议参数…', 'Explain results, compare metrics or suggest parameters…')" :disabled="Boolean(pending)" />
      <div class="flex gap-2"><Button type="submit" :disabled="!session || working || Boolean(pending) || !message.trim()">{{ L('发送', 'Send') }}</Button><Button v-if="running" type="button" variant="outline" @click="stop">{{ L('停止', 'Stop') }}</Button></div>
    </form>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import MarkdownIt from 'markdown-it'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast/use-toast'
import { getAgentSession, sendAgentSessionTurn, stopAgentSessionTurn, type AgentSessionState, type AgentSessionTurn } from '@/api/genovaBackend'
import { bindModuleSession, openModuleSession, sameValue, type AssistantModule, type ModuleContext, type ModuleSuggestion } from '@/api/moduleAssistant'
import { useWorkspaceState } from '@/composables/useWorkspace'
import { randomUUID } from '@/utils/uuid'
import { displayErrorMessage, systemErrorMessage } from '@/utils/requestError'

const props = defineProps<{ module: AssistantModule; jobId?: string; context: ModuleContext; apply: (suggestion: ModuleSuggestion) => Promise<void> | void }>()
const { locale, t } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const markdown = new MarkdownIt({ html: false, linkify: false })
const session = ref<AgentSessionState | null>(null), loading = ref(false), sending = ref(false), applying = ref(false)
const error = ref(''), message = ref(''), conflict = ref('')
const { applied } = useWorkspaceState('module-assistant', () => `${props.module}:${props.jobId || 'draft'}`, { applied: [] as string[] })
const pending = ref<Record<string, any> | null>(null)
const running = computed(() => session.value?.turns.find(turn => ['queued', 'running'].includes(turn.status)))
const working = computed(() => loading.value || sending.value || applying.value || Boolean(running.value))
let revision = 0, timer: ReturnType<typeof setTimeout> | undefined, disposed = false
function failure(exc: any) { return displayErrorMessage(exc, L('请求失败', 'Request failed')) }
function display(value: any) { return value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value) }
function suggestions(turn: AgentSessionTurn): ModuleSuggestion[] {
  return session.value?.research_task_state === 'allowed' && turn.research_task_id === session.value?.research_task_id &&
    turn.response.safety_decision !== 'refuse' && turn.status === 'completed' ? turn.response.module_suggestions || [] : []
}
function actionLabel(suggestion: ModuleSuggestion) { return suggestion.target === 'view' ? L('应用到当前结果', 'Apply to current results') : props.jobId ? L('填入新任务草稿', 'Fill a new task draft') : L('填入当前草稿', 'Fill current draft') }
async function initialize() {
  const current = ++revision
  clearTimeout(timer); loading.value = true; sending.value = false; applying.value = false; session.value = null; pending.value = null; error.value = ''; conflict.value = ''
  try {
    const response = await openModuleSession(props.module, props.jobId)
    if (current !== revision || disposed) return
    session.value = response.data
    schedule()
  } catch (exc) { if (current === revision && !disposed) error.value = failure(exc) }
  finally { if (current === revision) loading.value = false }
}
function schedule() { clearTimeout(timer); if (running.value && !disposed) timer = setTimeout(refresh, 1500) }
async function refresh() {
  const id = session.value?.id, current = revision
  if (!id) return
  try {
    const response = await getAgentSession(id)
    if (current !== revision || disposed) return
    session.value = response.data
  } catch (exc) { if (current === revision && !disposed) error.value = failure(exc) }
  finally { if (current === revision) schedule() }
}
async function submit() {
  if (working.value || pending.value || !message.value.trim()) return
  try {
    // crypto.randomUUID is missing on plain-HTTP deployments; the shared helper falls back to getRandomValues.
    pending.value = { client_request_id: randomUUID(), intent: 'ask', message: message.value.trim(), module_context: JSON.parse(JSON.stringify(props.context)) }
  } catch (exc) {
    // Preparing the request must not fail silently: the text stays in the box and the reason is shown.
    console.error(exc)
    pending.value = null
    error.value = t('platform.assistantErrors.sendFailed')
    return
  }
  await sendPending()
}
async function sendPending() {
  if (!session.value || !pending.value || working.value) return
  const current = revision, id = session.value.id
  sending.value = true; error.value = ''
  try {
    await sendAgentSessionTurn(id, pending.value)
    if (current !== revision || disposed) return
    pending.value = null; message.value = ''
    await refresh()
  } catch (exc) { if (current === revision && !disposed) error.value = failure(exc) }
  finally { if (current === revision) sending.value = false }
}
async function retry(turn: AgentSessionTurn) {
  message.value = turn.message
  await submit()
}
async function stop() {
  if (!session.value || !running.value) return
  try { await stopAgentSessionTurn(session.value.id, running.value.id); await refresh() }
  catch (exc) { error.value = failure(exc) }
}
async function applySuggestion(suggestion: ModuleSuggestion, key: string, force = false) {
  error.value = ''
  const current = revision
  // The checks are inside try as well, so an unexpected exception is reported instead of being lost.
  try {
    applying.value = true
    await refresh()
    const turn = session.value?.turns.find(item => key.startsWith(item.id + ':'))
    if (current !== revision || disposed || error.value || !turn || !suggestions(turn).length) return
    const inputs = { protein_context_id: props.context.protein_context_id, ligand_dataset_id: props.context.ligand_dataset_id, reference_dataset_id: props.context.form.reference_dataset_id }
    if (suggestion.engine !== props.context.engine || (suggestion.job_id || '') !== (props.jobId || '') || (suggestion.source_job_id || '') !== (props.context.source_job_id || '') || !sameValue(inputs, suggestion.input_binding)) {
      error.value = L('当前任务或输入已变化，请重新生成建议。', 'The task or inputs changed. Request a new suggestion.'); return
    }
    const baseline = suggestion.target === 'view' ? props.context.view_draft || props.context.view || {} : props.context.form
    if (!force && suggestion.changes.some(change => !sameValue(baseline[change.field], change.before))) { conflict.value = key; return }
    await props.apply(suggestion); if (current === revision && !disposed) { applied.value = [...applied.value, key]; conflict.value = '' }
  }
  catch (exc) { console.error(exc); error.value = failure(exc) }
  finally { if (current === revision) applying.value = false }
}
async function bindToJob(jobId: string) {
  if (!session.value?.turns.length || props.jobId) return
  try { await bindModuleSession(session.value.id, props.module, jobId) }
  catch (exc) { toast({ title: L('任务已提交，对话关联失败', 'Task submitted; conversation could not be linked'), description: failure(exc), variant: 'destructive' }) }
}
defineExpose({ bindToJob })
watch(() => `${props.module}:${props.jobId || ''}`, initialize, { immediate: true })
onBeforeUnmount(() => { disposed = true; revision++; clearTimeout(timer) })
</script>
