<template>
  <Card id="agent-proxy" class="mb-4 p-4 shadow-none sm:p-5">
    <h2 class="mb-4 text-lg font-semibold text-slate-900">{{ t('settings.proxy_title') }}</h2>
    <form class="space-y-4" @submit.prevent="save">
      <p class="text-sm text-slate-500">{{ t('settings.proxy_hint') }}</p>
      <div class="flex items-center gap-2">
        <Switch id="agent-proxy-enabled" v-model:checked="enabled" :disabled="busy || !loaded || (!enabled && !allowed.length)" />
        <Label for="agent-proxy-enabled">{{ t('settings.proxy_enabled') }}</Label>
      </div>
      <div v-if="enabled">
        <Label for="agent-proxy-url">{{ t('settings.proxy_address') }}</Label>
        <Input
          id="agent-proxy-url"
          v-model="selected"
          type="url"
          list="agent-proxy-addresses"
          placeholder="http://host.docker.internal:7897"
          required
          :disabled="busy || !loaded"
        />
        <datalist id="agent-proxy-addresses">
          <option v-for="url in allowed" :key="url" :value="url" />
        </datalist>
      </div>
      <p v-if="loaded && !allowed.length" class="text-sm text-gray-500">{{ t('settings.proxy_no_addresses') }}</p>
      <Button type="submit" :disabled="busy || !loaded">{{ t('settings.agent_save') }}</Button>
      <p v-if="message" role="status" class="text-sm text-green-700">{{ message }}</p>
      <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
    </form>
  </Card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { getAgentProxySettings, saveAgentProxySettings } from '@/api/genovaBackend'
import type { AgentProxySettingsOut } from '@/api/genovaBackend'

const { t } = useI18n()
const enabled = ref(false)
const selected = ref('')
const allowed = ref<string[]>([])
const busy = ref(true)
const loaded = ref(false)
const message = ref('')
const error = ref('')

function apply(data: AgentProxySettingsOut) {
  enabled.value = Boolean(data.proxy_url)
  selected.value = data.proxy_url || selected.value || data.allowed_proxy_urls[0] || ''
  allowed.value = data.allowed_proxy_urls
  loaded.value = true
}

function displayError(e: any) {
  const code = e.response?.data?.detail?.error_code
  error.value = code && t(`settings.${code}`) !== `settings.${code}` ? t(`settings.${code}`) : t('settings.proxy_failed')
}

onMounted(async () => {
  try { apply((await getAgentProxySettings()).data) }
  catch (e) { displayError(e) }
  finally { busy.value = false }
})

async function save() {
  if (busy.value || !loaded.value) return
  busy.value = true
  message.value = error.value = ''
  try {
    apply((await saveAgentProxySettings({ proxy_url: enabled.value ? selected.value.trim() : null })).data)
    message.value = t('settings.proxy_saved')
  } catch (e) { displayError(e) }
  finally { busy.value = false }
}
</script>
