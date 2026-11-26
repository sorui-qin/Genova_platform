<template>
  <Card id="agent-preferences" class="mb-4 p-4 shadow-none sm:p-5">
    <h2 class="mb-2 text-lg font-semibold text-slate-900">{{ t('settings.work_preferences_title') }}</h2>
    <p class="mb-4 text-sm text-slate-500">{{ t('settings.work_preferences_hint') }}</p>
    <p v-if="loaded && !items.length" class="text-sm text-gray-500">{{ t('settings.work_preferences_empty') }}</p>
    <ul v-else class="space-y-2">
      <li v-for="item in items" :key="item.id" class="flex items-start justify-between gap-3 rounded-md border bg-gray-50 px-3 py-2">
        <span class="min-w-0 break-words text-sm text-gray-900">{{ item.text }}</span>
        <Button type="button" variant="outline" size="sm" :disabled="busy" :aria-label="`${t('settings.work_preferences_delete')}: ${item.text}`" @click="remove(item.id)">
          {{ t('settings.work_preferences_delete') }}
        </Button>
      </li>
    </ul>
    <p v-if="error" role="alert" class="mt-3 text-sm text-red-700">{{ error }}</p>
  </Card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { deleteAgentWorkPreference, getAgentWorkPreferences } from '@/api/genovaBackend'
import type { AgentWorkPreference } from '@/api/genovaBackend'

const { t } = useI18n()
const items = ref<AgentWorkPreference[]>([])
const busy = ref(true)
const loaded = ref(false)
const error = ref('')

async function load() {
  error.value = ''
  try {
    items.value = (await getAgentWorkPreferences()).data
    loaded.value = true
  } catch (e) { error.value = t('settings.work_preferences_failed') }
  finally { busy.value = false }
}

async function remove(id: string) {
  if (busy.value) return
  busy.value = true
  let failed = false
  try { await deleteAgentWorkPreference(id) } catch (e) { failed = true }
  await load()
  if (failed) error.value = t('settings.work_preferences_failed')
}

onMounted(load)
</script>
