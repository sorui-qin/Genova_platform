<template>
  <Card id="agent-api" class="mb-4 overflow-hidden shadow-none">
    <Collapsible v-model:open="open">
      <h2>
        <CollapsibleTrigger class="group flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-violet-500 sm:p-5">
          <span class="min-w-0 flex-1">
            <span class="block text-lg font-semibold text-slate-900">{{ t('settings.agent_api') }}</span>
            <span class="mt-1 block truncate text-sm font-normal text-slate-500" :title="activeProfile ? `${activeProfile.name} · ${activeProfile.model}` : undefined">
              {{ activeProfile ? `${activeProfile.name} · ${activeProfile.model}` : t('settings.not_set') }}
            </span>
          </span>
          <ChevronDown class="h-4 w-4 shrink-0 text-slate-400 transition-transform group-data-[state=open]:rotate-180" aria-hidden="true" />
        </CollapsibleTrigger>
      </h2>
      <CollapsibleContent v-show="open" force-mount>
        <form ref="form" class="grid gap-4 border-t border-slate-100 p-4 sm:grid-cols-2 sm:p-5" @submit.prevent="submit('save')">
          <p class="text-sm leading-relaxed text-slate-500 sm:col-span-2">{{ t('settings.agent_api_protocol') }}</p>
          <div class="min-w-0 space-y-1.5 sm:col-span-2">
            <Label for="agent-profile">{{ t('settings.api_saved_profiles') }}</Label>
            <Select :model-value="selectedId" :disabled="busy" @update:model-value="chooseProfile">
              <SelectTrigger id="agent-profile"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="new">{{ t('settings.api_new_profile') }}</SelectItem>
                <SelectItem v-for="p in profiles" :key="p.id" :value="p.id">{{ p.name }} · {{ p.auth_type === 'chatgpt' ? 'ChatGPT' : p.base_url }}{{ p.id === activeId ? ` (${t('settings.api_active_profile')})` : '' }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="min-w-0 space-y-1.5 sm:col-span-2">
            <Label for="agent-auth-type">{{ t('settings.agent_auth_type') }}</Label>
            <Select v-model="authType" :disabled="busy || selectedId !== 'new'">
              <SelectTrigger id="agent-auth-type"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="api_key">API Key</SelectItem>
                <SelectItem value="chatgpt">ChatGPT OAuth</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div v-if="isChatGPT" class="space-y-3 sm:col-span-2">
            <p v-if="selectedProfile" class="text-sm text-slate-600">
              {{ selectedProfile.account_label }} · {{ t(`settings.chatgpt_${selectedProfile.connection_status || 'disconnected'}`) }}
            </p>
            <div class="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                class="h-11 w-full gap-3 rounded-xl bg-slate-900 px-4 text-white shadow-sm hover:bg-slate-800 focus-visible:ring-slate-900 active:bg-slate-950 sm:w-auto sm:px-5"
                :disabled="busy"
                :aria-busy="loginPending"
                @click="loginChatGPT"
              >
                <LoaderCircle v-if="loginPending" class="!size-5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                <OpenAiIcon v-else class="!size-5 fill-current" aria-hidden="true" />
                <span>{{ t(loginPending ? 'settings.chatgpt_button_waiting' : 'settings.chatgpt_continue') }}</span>
                <ArrowUpRight class="hidden opacity-70 sm:block" aria-hidden="true" />
              </Button>
              <Button v-if="selectedProfile?.connection_status === 'connected' || selectedProfile?.connection_status === 'plan_required'"
                type="button" variant="outline" :disabled="busy" @click="logoutChatGPT">{{ t('settings.chatgpt_disconnect') }}</Button>
            </div>
            <p v-if="loginPending" role="status" class="text-sm text-slate-600">{{ t('settings.chatgpt_waiting') }}</p>
            <p class="text-sm text-slate-500">{{ t('settings.chatgpt_plan_usage') }}</p>
            <a href="https://chatgpt.com/#settings/Usage" target="_blank" rel="noopener noreferrer" class="text-sm text-violet-600 underline">
              {{ t('settings.chatgpt_manage_usage') }}
            </a>
          </div>
          <div class="min-w-0 space-y-1.5">
            <Label for="agent-profile-name">{{ t('settings.api_profile_name') }}</Label>
            <Input id="agent-profile-name" v-model="profileName" required maxlength="80" :disabled="busy" />
          </div>
          <div class="min-w-0 space-y-1.5">
            <Label for="agent-model">{{ t('settings.agent_model') }}</Label>
            <Select v-if="isChatGPT" :model-value="model" @update:model-value="changeModel" :disabled="busy || loadingModels || !models.length">
              <SelectTrigger id="agent-model"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="item in models" :key="item.slug" :value="item.slug">{{ item.display_name }}</SelectItem>
              </SelectContent>
            </Select>
            <Input v-else id="agent-model" :model-value="model" @update:model-value="changeModel" required maxlength="256" :disabled="busy" />
          </div>
          <div v-if="!isChatGPT" class="min-w-0 space-y-1.5 sm:col-span-2">
            <Label for="agent-base-url">Base URL</Label>
            <Input id="agent-base-url" :model-value="baseUrl" @update:model-value="changeUrl" type="url" required maxlength="2048" :disabled="busy" />
          </div>
          <div v-if="!isChatGPT" class="min-w-0 space-y-1.5 sm:col-span-2">
            <Label for="agent-api-key">API Key</Label>
            <Input id="agent-api-key" :model-value="keyEditing ? apiKey : !needsKey ? '********' : ''"
              @focus="keyEditing = true" @blur="keyEditing = !!apiKey" @update:model-value="apiKey = String($event)"
              type="password" autocomplete="new-password"
              :required="needsKey" maxlength="8192" :disabled="busy" />
            <p v-if="hasKey" class="mt-1 text-sm text-gray-600">
              {{ t(needsKey ? 'settings.agent_key_new_url' : 'settings.agent_key_keep') }}
            </p>
          </div>
          <AgentReasoningSettings :key="`${selectedId}:${baseUrl}:${model}:${authType}`" v-model="reasoning" :base-url="baseUrl" :model="model"
            :profile-id="selectedId === 'new' ? null : selectedId" :api-key="apiKey" :auth-type="authType" :disabled="busy" />
          <div class="space-y-1.5 sm:col-span-2">
            <Label for="agent-context-window">{{ t('settings.agent_context_window') }}</Label>
            <Input id="agent-context-window" :model-value="reasoning?.capability?.context_window || contextWindow" @update:model-value="contextWindow = $event" type="number" min="16384" max="16777216" step="1" :disabled="busy || !!reasoning?.capability?.context_window" />
            <p class="text-sm text-slate-500">{{ t('settings.agent_context_window_hint') }}</p>
          </div>
          <div class="flex flex-wrap gap-2 border-t border-slate-100 pt-4 sm:col-span-2">
            <Button type="submit" :disabled="busy || !canSubmit">{{ t('settings.agent_save') }}</Button>
            <Button type="button" variant="outline" :disabled="busy || !canSubmit" @click="submit('test')">{{ t('settings.agent_test') }}</Button>
            <Button type="button" variant="outline" :disabled="busy || selectedId === 'new'" @click="clearConfig">{{ t('settings.agent_clear') }}</Button>
          </div>
          <p class="text-xs leading-relaxed text-slate-500 sm:col-span-2">{{ t('settings.agent_test_cost') }}</p>
        </form>
      </CollapsibleContent>
    </Collapsible>
    <div v-if="message || error" class="space-y-2 border-t border-slate-100 px-4 py-3 sm:px-5">
      <p v-if="message" role="status" class="text-sm text-green-700">{{ message }}</p>
      <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
    </div>
  </Card>
  <Dialog :open="manualLoginOpen" @update:open="value => { if (!value) cancelLogin() }">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{{ t('settings.chatgpt_manual_title') }}</DialogTitle>
        <DialogDescription>{{ t('settings.chatgpt_manual_description') }}</DialogDescription>
      </DialogHeader>
      <form class="space-y-4" @submit.prevent="completeManualLogin">
        <Label for="chatgpt-callback-url">{{ t('settings.chatgpt_callback_url') }}</Label>
        <Textarea id="chatgpt-callback-url" v-model="callbackUrl" required maxlength="16384"
          autocomplete="off" autocapitalize="off" :spellcheck="false" :disabled="completingLogin"
          class="min-h-28 break-all" />
        <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
        <DialogFooter>
          <Button type="button" variant="outline" @click="cancelLogin">{{ t('settings.chatgpt_manual_cancel') }}</Button>
          <Button type="submit" :disabled="completingLogin || !callbackUrl.trim()" :aria-busy="completingLogin">
            {{ t(completingLogin ? 'settings.chatgpt_manual_submitting' : 'settings.chatgpt_manual_complete') }}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, ChevronDown, LoaderCircle } from 'lucide-vue-next'
import { OpenAiIcon } from 'vue3-simple-icons'
import AgentReasoningSettings from './AgentReasoningSettings.vue'
import { Card } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { AgentAPIProfile, AgentSettingsOut, AgentReasoningConfig } from '@/api/genovaBackend'
import { getAgentSettings, saveAgentSettings, testAgentSettings, deleteAgentSettings, startChatGPTLogin, completeChatGPTLogin, getChatGPTLoginStatus, getChatGPTModels, disconnectChatGPT } from '@/api/genovaBackend'

const { t } = useI18n()
const open = ref(true)
const form = ref<HTMLFormElement | null>(null)
const baseUrl = ref('https://api.openai.com/v1')
const model = ref('')
const reasoning = ref<AgentReasoningConfig | null>(null)
const contextWindow = ref<number | string>('')
const apiKey = ref('')
const keyEditing = ref(false)
const profiles = ref<AgentAPIProfile[]>([])
const selectedId = ref('new')
const authType = ref<'api_key' | 'chatgpt'>('api_key')
const isChatGPT = computed(() => authType.value === 'chatgpt')
const selectedProfile = computed(() => profiles.value.find(p => p.id === selectedId.value))
const models = ref<Array<{ slug: string; display_name: string }>>([])
const loadingModels = ref(false)
const loginPending = ref(false)
const manualLoginOpen = ref(false)
const callbackUrl = ref('')
const loginAttemptId = ref<string | null>(null)
const completingLogin = ref(false)
let loginSequence = 0
let loginWindow: Window | null = null
const canSubmit = computed(() => !isChatGPT.value || (selectedProfile.value?.connection_status === 'connected'
  && models.value.some(item => item.slug === model.value) && !loadingModels.value))
let alive = true
onBeforeUnmount(() => { alive = false; cancelLogin() })
const activeId = ref<string | null>(null)
const activeProfile = computed(() => profiles.value.find(p => p.id === activeId.value))
const profileName = ref('')
const hasKey = ref(false)
const savedUrl = ref('')
const busy = ref(true)
const message = ref('')
const error = ref('')
// Saving and the change check use the same form: trimmed, without trailing slashes.
const normalizeBaseUrl = (value: string) => value.trim().replace(/\/+$/, '')
const needsKey = computed(() => !hasKey.value || normalizeBaseUrl(baseUrl.value) !== savedUrl.value)

function displayError(e: any) {
  const detail = e.response?.data?.detail
  const code = detail?.error_code
  const source = detail?.error_source
  const recovery = detail?.recovery_action
  const translated = code && t(`settings.${code}`) !== `settings.${code}`
    ? t(`settings.${code}`) : t('settings.agent_request_failed')
  const sourceKey = source ? `settings.agent_error_source_${source}` : ''
  const sourceLabel = sourceKey && t(sourceKey) !== sourceKey ? t(sourceKey) : ''
  const diagnostics = [sourceLabel, code, e.response?.status ? `HTTP ${e.response.status}` : '', detail?.upstream_error_code]
    .filter(Boolean)
  const recoveryKey = recovery ? `settings.agent_recovery_${recovery}` : ''
  const recoveryHint = recoveryKey && t(recoveryKey) !== recoveryKey ? t(recoveryKey) : ''
  const base = diagnostics.length ? `[${diagnostics.join(' / ')}] ${translated}` : translated
  const withMessage = detail?.message && detail.message !== translated ? `${base} · ${detail.message}` : base
  error.value = recoveryHint ? `${withMessage} ${t('settings.agent_try_this')}: ${recoveryHint}` : withMessage
}

function chooseProfile(id: string) {
  selectedId.value = id
  const p = profiles.value.find(p => p.id === id)
  authType.value = p?.auth_type || 'api_key'
  models.value = []
  loadingModels.value = false
  profileName.value = p?.name || ''
  baseUrl.value = savedUrl.value = p?.base_url || 'https://api.openai.com/v1'
  model.value = p?.model || ''
  reasoning.value = p?.reasoning ? JSON.parse(JSON.stringify(p.reasoning)) : null
  contextWindow.value = p?.context_window || ''
  hasKey.value = p?.has_api_key || false
  apiKey.value = ''
  keyEditing.value = false
  message.value = error.value = ''
  if (p?.auth_type === 'chatgpt' && p.connection_status === 'connected') void loadModels(p.id)
}

function apply(data: AgentSettingsOut) {
  profiles.value = data.profiles
  activeId.value = data.active_profile_id
  chooseProfile(data.active_profile_id || 'new')
}

function changeUrl(value: string | number) {
  baseUrl.value = String(value)
  reasoning.value = null
  contextWindow.value = ''
  apiKey.value = ''
  keyEditing.value = false
}

function changeModel(value: string | number) {
  model.value = String(value)
  reasoning.value = null
  contextWindow.value = ''
}

onMounted(async () => {
  try {
    apply((await getAgentSettings()).data)
    open.value = !activeProfile.value
  }
  catch (e) { displayError(e) }
  finally { busy.value = false }
})

async function submit(action: 'save' | 'test') {
  if (busy.value || !canSubmit.value || !form.value?.reportValidity()) return
  busy.value = true
  error.value = message.value = ''
  const payload = { auth_type: authType.value, profile_id: selectedId.value === 'new' ? null : selectedId.value, profile_name: profileName.value.trim(), base_url: normalizeBaseUrl(baseUrl.value), model: model.value.trim(), reasoning: reasoning.value,
    context_window: reasoning.value?.capability?.context_window || (contextWindow.value ? Number(contextWindow.value) : null),
    ...(!isChatGPT.value && apiKey.value.trim() ? { api_key: apiKey.value.trim() } : {}) }
  try {
    if (action === 'save') {
      const { data } = await saveAgentSettings(payload)
      apply(data)
      message.value = t('settings.agent_saved')
    } else {
      await testAgentSettings(payload)
      message.value = t('settings.agent_test_ok')
    }
  } catch (e) {
    displayError(e)
  } finally {
    busy.value = false
  }
}

async function loadModels(id: string) {
  loadingModels.value = true
  try {
    const { data } = await getChatGPTModels(id)
    if (!alive || selectedId.value !== id) return
    models.value = data.models
    if (!model.value) model.value = data.models[0]?.slug || ''
  } catch (e) {
    if (alive && selectedId.value === id) displayError(e)
  } finally {
    if (selectedId.value === id) loadingModels.value = false
  }
}

async function loginChatGPT() {
  const manual = !['127.0.0.1', 'localhost'].includes(window.location.hostname)
  const popup = window.open('about:blank', '_blank')
  if (!popup) { error.value = t('settings.chatgpt_popup_blocked'); return }
  popup.opener = null
  loginWindow = popup
  const sequence = ++loginSequence
  busy.value = loginPending.value = true
  error.value = message.value = ''
  try {
    const { data } = await startChatGPTLogin(selectedId.value === 'new' ? undefined : selectedId.value, manual ? 'manual' : 'local')
    if (!alive || sequence !== loginSequence) return
    loginAttemptId.value = data.attempt_id
    manualLoginOpen.value = manual
    popup.location.href = data.authorization_url
    const deadline = Date.now() + 600000
    while (alive && sequence === loginSequence && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 1500))
      if (!alive || sequence !== loginSequence) return
      const { data: status } = await getChatGPTLoginStatus(data.attempt_id)
      if (!alive || sequence !== loginSequence) return
      if (status.status === 'succeeded') {
        const settings = (await getAgentSettings()).data
        if (!alive || sequence !== loginSequence) return
        profiles.value = settings.profiles
        activeId.value = settings.active_profile_id
        chooseProfile(status.profile_id!)
        popup.close()
        message.value = t('settings.chatgpt_authorized')
        return
      }
      if (status.status !== 'pending') {
        displayError({ response: { data: { detail: { error_code: status.error_code || 'AGENT_CHATGPT_OAUTH_INVALID' } } } })
        return
      }
    }
    if (alive && sequence === loginSequence) error.value = t('settings.chatgpt_canceled')
  } catch (e) {
    if (alive && sequence === loginSequence) displayError(e)
  } finally {
    popup.close()
    if (sequence === loginSequence) {
      loginWindow = null
      manualLoginOpen.value = false
      callbackUrl.value = ''
      loginAttemptId.value = null
      completingLogin.value = false
      busy.value = loginPending.value = false
    }
  }
}

function cancelLogin() {
  loginSequence++
  loginWindow?.close()
  loginWindow = null
  manualLoginOpen.value = false
  callbackUrl.value = ''
  loginAttemptId.value = null
  completingLogin.value = false
  busy.value = loginPending.value = false
}

async function completeManualLogin() {
  if (!loginAttemptId.value || completingLogin.value || !callbackUrl.value.trim()) return
  const sequence = loginSequence
  completingLogin.value = true
  error.value = ''
  try {
    await completeChatGPTLogin(loginAttemptId.value, callbackUrl.value.trim())
    if (alive && sequence === loginSequence) callbackUrl.value = ''
  } catch (e) {
    if (alive && sequence === loginSequence) displayError(e)
  } finally {
    if (sequence === loginSequence) completingLogin.value = false
  }
}

async function logoutChatGPT() {
  busy.value = true
  error.value = message.value = ''
  try {
    const id = selectedId.value
    const { data } = await disconnectChatGPT(id)
    const settings = (await getAgentSettings()).data
    profiles.value = settings.profiles
    chooseProfile(id)
    if (data.revocation_confirmed) message.value = t('settings.chatgpt_disconnected')
    else error.value = t('settings.chatgpt_revocation_unconfirmed')
  } catch (e) { displayError(e) }
  finally { busy.value = false }
}

async function clearConfig() {
  if (busy.value || selectedId.value === 'new' || !window.confirm(t('settings.api_delete_profile_confirm', { name: profileName.value, active: selectedId.value === activeId.value ? t('settings.api_active_profile') : '' }))) return
  busy.value = true
  error.value = message.value = ''
  try {
    await deleteAgentSettings(selectedId.value)
    apply((await getAgentSettings()).data)
    message.value = t('settings.agent_cleared')
  } catch (e) {
    displayError(e)
  } finally {
    busy.value = false
  }
}
</script>
