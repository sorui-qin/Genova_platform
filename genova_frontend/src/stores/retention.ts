import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getDataRetentionPolicy, type DataRetentionPolicy } from '@/api/genovaBackend'

export const useRetentionStore = defineStore('retention', () => {
  const policy = ref<DataRetentionPolicy | null>(null)
  let pending: Promise<void> | null = null

  async function load() {
    if (!pending) {
      pending = getDataRetentionPolicy().then(response => { policy.value = response.data })
        .finally(() => { pending = null })
    }
    await pending
  }

  function cacheExpired(savedAt = 0) {
    if (!policy.value?.enabled || !policy.value.first_enabled_at) return false
    return Math.max(Number.isFinite(savedAt) ? savedAt : 0, Date.parse(policy.value.first_enabled_at))
      + policy.value.retention_days * 86400000 <= Date.now()
  }

  return { policy, load, cacheExpired }
})
