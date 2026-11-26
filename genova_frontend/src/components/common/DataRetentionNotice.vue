<template>
  <template v-if="relevant && retention.policy?.enabled">
    <div v-if="!bannerClosed" role="note" class="flex items-start gap-3 border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
      <div class="min-w-0 flex-1">
        <p>{{ t('platform.retentionNotice') }}</p>
        <p v-if="graceEnd" class="mt-1">{{ t('platform.retentionGrace', { date: graceEnd }) }}</p>
      </div>
      <Button type="button" variant="ghost" size="icon" class="h-7 w-7 shrink-0 hover:bg-amber-100" :aria-label="t('platform.close')" :title="t('platform.close')" @click="closeBanner">
        <X class="h-4 w-4" />
      </Button>
    </div>
    <Dialog :open="showDialog" @update:open="value => { if (!value) dismiss() }">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{{ t('platform.retentionTitle') }}</DialogTitle>
          <DialogDescription class="pt-2 leading-relaxed">{{ t('platform.retentionNotice') }}</DialogDescription>
        </DialogHeader>
        <p v-if="graceEnd" class="text-sm">{{ t('platform.retentionGrace', { date: graceEnd }) }}</p>
        <DialogFooter><Button @click="dismiss">{{ t('platform.retentionAcknowledge') }}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </template>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useRetentionStore } from '@/stores/retention'
import { readStoredUserInfo } from '@/utils/guestSession'

const route = useRoute()
const { t, locale } = useI18n()
const retention = useRetentionStore()
const showDialog = ref(false)
const bannerClosed = ref(true)
const relevant = computed(() => /^\/(datacenter|protein-preparation|molgen|molopt|postprocessing|results|agent)(\/|$)/.test(route.path))
const acknowledgmentKey = computed(() => `genova:retention:${import.meta.env.BASE_URL}:${readStoredUserInfo()?.id || ''}:${retention.policy?.first_enabled_at}`)
const graceEnd = computed(() => {
  if (!retention.policy?.first_enabled_at) return ''
  const end = Date.parse(retention.policy.first_enabled_at) + retention.policy.retention_days * 86400000
  return end > Date.now() ? new Date(end).toLocaleString(locale.value) : ''
})

function dismiss() {
  showDialog.value = false
  try { localStorage.setItem(acknowledgmentKey.value, '1') } catch { /* Storage may be disabled. */ }
}

function closeBanner() {
  bannerClosed.value = true
  try { localStorage.setItem(`${acknowledgmentKey.value}:banner-closed`, '1') } catch { /* Storage may be disabled. */ }
}

watch(() => route.path, async () => {
  showDialog.value = false
  bannerClosed.value = true
  if (!relevant.value) return
  try {
    await retention.load()
    if (!relevant.value || !retention.policy?.enabled) return
    try {
      showDialog.value = localStorage.getItem(acknowledgmentKey.value) !== '1'
      bannerClosed.value = localStorage.getItem(`${acknowledgmentKey.value}:banner-closed`) === '1'
    } catch { showDialog.value = true; bannerClosed.value = false }
  } catch (error) { console.error('Failed to load data retention policy:', error) }
}, { immediate: true })
</script>
