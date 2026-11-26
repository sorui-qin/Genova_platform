import { getProteinContext } from '@/api/proteinContext'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { type ProteinAnalysis, type ProteinContext } from '@/types/proteinContext'

export const useProteinContextStore = defineStore(
  'protein-context',
  () => {
    const proteinDatasetId = ref('')
    const proteinFileId = ref('')
    const contextId = ref('')
    const analysis = ref<ProteinAnalysis | null>(null)
    const context = ref<ProteinContext | null>(null)
    const returnPath = ref('/molgen')
    let pollTimer: ReturnType<typeof setTimeout> | undefined

    function setContext(value: ProteinContext) {
      clearTimeout(pollTimer)
      if (value.version !== 4 || value.status === 'archived') { clear(); return }
      context.value = value
      contextId.value = value.id
      proteinDatasetId.value = value.artifacts.effective_receptor.dataset_id
      proteinFileId.value = value.artifacts.effective_receptor.file_id
      if (Object.values(value.compatibility?.models || {}).some(row => row.status === 'pending')) pollTimer = setTimeout(async () => {
        try { const result = await getProteinContext(value.id); if (contextId.value === value.id) setContext(result.data) }
        catch { if (context.value?.id === value.id) pollTimer = setTimeout(() => { if (context.value?.id === value.id) setContext(context.value) }, 5000) }
      }, 2000)
    }

    function clear() {
      clearTimeout(pollTimer)
      proteinDatasetId.value = ''
      proteinFileId.value = ''
      contextId.value = ''
      analysis.value = null
      context.value = null
    }

    return {
      proteinDatasetId,
      proteinFileId,
      contextId,
      analysis,
      context,
      returnPath,
      setContext,
      clear,
    }
  },
  { persist: true },
)
