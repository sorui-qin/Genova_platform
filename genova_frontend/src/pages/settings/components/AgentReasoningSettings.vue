<template>
  <div class="space-y-3 rounded-lg border border-slate-200 p-3 sm:col-span-2">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <Label>{{ t('settings.reasoning_title') }}</Label>
      <Button type="button" variant="outline" size="sm" :disabled="disabled || loading || !model.trim()" @click="refresh">
        {{ t(loading ? 'settings.reasoning_loading' : 'settings.reasoning_refresh') }}
      </Button>
    </div>
    <p class="text-xs text-slate-500">
      {{ capability ? t(`settings.reasoning_source_${capability.source}`) : t('settings.reasoning_source_unknown') }}
      <span v-if="capability"> · {{ capability.protocol === 'responses' ? 'Responses' : 'Chat Completions' }}</span>
    </p>
    <p v-if="capability?.warning" role="status" class="text-sm text-amber-700">{{ t('settings.reasoning_lookup_warning') }} {{ t(`settings.${capability.warning}`) }}</p>
    <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
    <div v-if="capability?.effort_parameter" class="space-y-1.5">
      <Label for="agent-reasoning-effort">{{ t('settings.reasoning_effort') }}</Label>
      <Select :model-value="selection.effort ?? 'default'" :disabled="disabled || loading || (capability.exclusive_effort_budget && selection.budget_tokens !== null)" @update:model-value="setSelection('effort', $event === 'default' ? null : String($event))">
        <SelectTrigger id="agent-reasoning-effort"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="default">{{ defaultLabel }}</SelectItem>
          <SelectItem v-for="level in capability.effort_levels" :key="level" :value="level">{{ effortLabel(level) }}</SelectItem>
        </SelectContent>
      </Select>
    </div>
    <div v-if="capability?.thinking_parameter" class="space-y-1.5">
      <Label for="agent-reasoning-thinking">{{ t('settings.reasoning_thinking') }}</Label>
      <Select :model-value="selection.thinking === null ? 'default' : String(selection.thinking)" :disabled="disabled || loading" @update:model-value="setSelection('thinking', $event === 'default' ? null : $event === 'true')">
        <SelectTrigger id="agent-reasoning-thinking"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="default">{{ t('settings.reasoning_default') }}</SelectItem>
          <SelectItem value="true">{{ t('settings.reasoning_enabled') }}</SelectItem>
          <SelectItem v-if="capability.can_disable" value="false">{{ t('settings.reasoning_disabled') }}</SelectItem>
        </SelectContent>
      </Select>
    </div>
    <div v-if="capability?.budget_parameter" class="space-y-1.5">
      <Label for="agent-reasoning-budget">{{ t('settings.reasoning_budget') }}</Label>
      <Input id="agent-reasoning-budget" type="number" step="1" :min="capability.budget_min" :max="capability.budget_max ?? 1000000"
        :model-value="selection.budget_tokens ?? ''" :placeholder="t('settings.reasoning_default')"
        :disabled="disabled || loading || selection.thinking === false || (capability.exclusive_effort_budget && selection.effort !== null)"
        @update:model-value="setSelection('budget_tokens', $event === '' ? null : Number($event))" />
    </div>
    <details>
      <summary class="cursor-pointer text-sm text-slate-600">{{ t('settings.reasoning_advanced') }}</summary>
      <div class="mt-3 grid gap-3 sm:grid-cols-2">
        <div class="space-y-1.5 sm:col-span-2">
          <Label for="agent-api-protocol">{{ t('settings.reasoning_protocol') }}</Label>
          <Select :model-value="config.api_protocol" :disabled="disabled || loading" @update:model-value="changeProtocol">
            <SelectTrigger id="agent-api-protocol"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">{{ t('settings.reasoning_auto') }}</SelectItem>
              <SelectItem value="chat_completions" :disabled="authType === 'chatgpt' || capability?.supported_protocols.includes('chat_completions') === false">Chat Completions</SelectItem>
              <SelectItem value="responses" :disabled="capability?.supported_protocols.includes('responses') === false">Responses</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="flex items-center gap-2 sm:col-span-2">
          <Switch id="agent-reasoning-manual" v-model:checked="manualEnabled" :disabled="disabled || loading || capability?.manual_allowed === false" />
          <Label for="agent-reasoning-manual">{{ t('settings.reasoning_manual') }}</Label>
        </div>
        <template v-if="manualEnabled">
          <p class="text-xs text-slate-500 sm:col-span-2">{{ t('settings.reasoning_manual_hint') }}</p>
          <div class="space-y-1.5">
            <Label for="agent-effort-parameter">{{ t('settings.reasoning_effort_parameter') }}</Label>
            <Select v-model="effortParameter" :disabled="disabled || loading">
              <SelectTrigger id="agent-effort-parameter"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="none">{{ t('settings.reasoning_not_supported') }}</SelectItem><SelectItem value="reasoning_effort" :disabled="authType === 'chatgpt' || config.api_protocol === 'responses'">reasoning_effort</SelectItem><SelectItem value="reasoning.effort" :disabled="config.api_protocol === 'chat_completions'">reasoning.effort</SelectItem></SelectContent>
            </Select>
          </div>
          <div v-if="effortParameter !== 'none'" class="space-y-1.5">
            <Label for="agent-effort-values">{{ t('settings.reasoning_values') }}</Label>
            <Input id="agent-effort-values" v-model="levels" required maxlength="1040" placeholder="low, high, max" :disabled="disabled || loading" />
          </div>
          <div v-if="effortParameter !== 'none'" class="space-y-1.5">
            <Label for="agent-effort-default">{{ t('settings.reasoning_declared_default') }}</Label>
            <Input id="agent-effort-default" v-model="declaredDefault" maxlength="64" :disabled="disabled || loading" />
          </div>
          <div class="space-y-1.5">
            <Label for="agent-thinking-parameter">{{ t('settings.reasoning_thinking_parameter') }}</Label>
            <Select v-model="thinkingParameter" :disabled="disabled || loading">
              <SelectTrigger id="agent-thinking-parameter"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="none">{{ t('settings.reasoning_not_supported') }}</SelectItem><SelectItem value="thinking.type">thinking.type</SelectItem><SelectItem value="enable_thinking">enable_thinking</SelectItem></SelectContent>
            </Select>
          </div>
          <div class="flex items-center gap-2">
            <Switch id="agent-thinking-can-disable" v-model:checked="canDisable" :disabled="disabled || loading" /><Label for="agent-thinking-can-disable">{{ t('settings.reasoning_can_disable') }}</Label>
          </div>
          <div class="flex items-center gap-2">
            <Switch id="agent-thinking-budget-supported" v-model:checked="budgetSupported" :disabled="disabled || loading" /><Label for="agent-thinking-budget-supported">{{ t('settings.reasoning_budget_supported') }}</Label>
          </div>
          <template v-if="budgetSupported">
            <div class="space-y-1.5"><Label for="agent-budget-min">{{ t('settings.reasoning_budget_min') }}</Label><Input id="agent-budget-min" v-model="budgetMin" type="number" min="1" max="1000000" step="1" required :disabled="disabled || loading" /></div>
            <div class="space-y-1.5"><Label for="agent-budget-max">{{ t('settings.reasoning_budget_max') }}</Label><Input id="agent-budget-max" v-model="budgetMax" type="number" :min="Number(budgetMin)" max="1000000" step="1" :disabled="disabled || loading" /></div>
            <div class="flex items-center gap-2 sm:col-span-2"><Switch id="agent-budget-exclusive" v-model:checked="exclusive" :disabled="disabled || loading" /><Label for="agent-budget-exclusive">{{ t('settings.reasoning_exclusive') }}</Label></div>
          </template>
        </template>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getAgentReasoningCapability } from '@/api/genovaBackend'
import type { AgentReasoningConfig, AgentReasoningDeclaration, AgentReasoningSelection } from '@/api/genovaBackend'
import { displayErrorMessage } from '@/utils/requestError'

const props = defineProps<{ modelValue: AgentReasoningConfig | null; baseUrl: string; model: string; profileId: string | null; apiKey: string; disabled: boolean; authType: 'api_key' | 'chatgpt' }>()
const emit = defineEmits<{ 'update:modelValue': [value: AgentReasoningConfig | null] }>()
const { t } = useI18n()
const defaults = (): AgentReasoningSelection => ({ effort: null, thinking: null, budget_tokens: null })
const config = computed<AgentReasoningConfig>(() => props.modelValue ?? { api_protocol: 'auto', selection: defaults(), manual: null, capability: null })
const capability = computed(() => config.value.capability)
const selection = computed(() => config.value.selection)
const defaultLabel = computed(() => t('settings.reasoning_default') + (capability.value?.default_effort ? ` (${capability.value.default_effort})` : ''))
const loading = ref(false)
const error = ref('')
let alive = true
onBeforeUnmount(() => { alive = false })
const manual = props.modelValue?.manual
const manualEnabled = ref(Boolean(manual))
const effortParameter = ref(manual?.effort_parameter ?? 'none')
const levels = ref(manual?.effort_levels.join(', ') ?? '')
const declaredDefault = ref(manual?.default_effort ?? '')
const thinkingParameter = ref(manual?.thinking_parameter ?? 'none')
const canDisable = ref(manual?.can_disable ?? true)
const budgetSupported = ref(Boolean(manual?.budget_parameter))
const budgetMin = ref<string | number>(manual?.budget_min ?? 1)
const budgetMax = ref<string | number>(manual?.budget_max ?? '')
const exclusive = ref(manual?.exclusive_effort_budget ?? true)
const declaration = computed<AgentReasoningDeclaration | null>(() => manualEnabled.value ? {
  effort_parameter: effortParameter.value === 'none' ? null : effortParameter.value as AgentReasoningDeclaration['effort_parameter'],
  effort_levels: effortParameter.value === 'none' ? [] : levels.value.split(',').map(s => s.trim()).filter(Boolean),
  default_effort: effortParameter.value === 'none' ? null : declaredDefault.value.trim() || null,
  thinking_parameter: thinkingParameter.value === 'none' ? null : thinkingParameter.value as AgentReasoningDeclaration['thinking_parameter'],
  can_disable: canDisable.value, budget_parameter: budgetSupported.value ? 'thinking_budget' : null,
  budget_min: Number(budgetMin.value), budget_max: budgetMax.value === '' ? null : Number(budgetMax.value),
  exclusive_effort_budget: exclusive.value,
} : null)

watch(declaration, value => {
  const protocol = props.authType === 'chatgpt' ? 'responses' : config.value.api_protocol === 'auto' ? (value?.effort_parameter === 'reasoning.effort' ? 'responses' : 'chat_completions') : config.value.api_protocol
  emit('update:modelValue', { ...config.value, selection: defaults(), manual: value,
    capability: value ? { ...value, protocol, source: 'user', warning: null, manual_allowed: true, supported_protocols: props.authType === 'chatgpt' ? ['responses'] : ['chat_completions', 'responses'] } : null })
})

function effortLabel(level: string) {
  const key = `settings.reasoning_level_${level}`
  return t(key) === key ? level : `${t(key)} · ${level}`
}
function setSelection(key: keyof AgentReasoningSelection, value: string | number | boolean | null) {
  const next = { ...selection.value, [key]: value }
  if ((key === 'thinking' && value === false) || (key === 'effort' && value === 'none')) {
    next.budget_tokens = null
    if (key === 'thinking') next.effort = null
    else next.thinking = null
  }
  emit('update:modelValue', { ...config.value, selection: next })
}
function changeProtocol(value: string) {
  manualEnabled.value = false
  emit('update:modelValue', { api_protocol: value as AgentReasoningConfig['api_protocol'], selection: defaults(), manual: null, capability: null })
}
async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await getAgentReasoningCapability({ auth_type: props.authType, base_url: props.baseUrl.trim(), model: props.model.trim(), profile_id: props.profileId,
      ...(props.apiKey.trim() ? { api_key: props.apiKey.trim() } : {}), reasoning: config.value })
    if (alive) emit('update:modelValue', { ...config.value, capability: data })
  } catch (e: any) {
    if (!alive) return
    error.value = displayErrorMessage(e, t('settings.reasoning_lookup_failed'))
  } finally { loading.value = false }
}
</script>
