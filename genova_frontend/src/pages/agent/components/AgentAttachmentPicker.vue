<template>
  <Dialog :open="true" @update:open="!$event && emit('close')">
    <DialogContent class="flex max-h-[90dvh] w-[calc(100vw-2rem)] max-w-2xl flex-col gap-0 overflow-hidden p-0" :aria-describedby="undefined">
      <header class="shrink-0 space-y-4 border-b px-5 pb-4 pt-5">
        <DialogTitle class="pr-8">{{ t('agent.session.fromDataCenter') }}</DialogTitle>
        <div class="relative">
          <Search class="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" aria-hidden="true" />
          <input v-model="search" type="search" maxlength="200" :aria-label="t('agent.attachmentPicker.search')" :placeholder="t('agent.attachmentPicker.search')" class="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
        </div>
        <ResourceSort v-model="sortOrder" />
      </header>
      <div class="min-h-0 flex-1 overflow-y-auto px-3 py-2" :aria-busy="loading">
        <div v-if="loading" role="status" class="flex min-h-64 items-center justify-center gap-2 text-sm text-slate-500">
          <LoaderCircle class="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />{{ t('platform.loading') }}
        </div>
        <div v-else-if="loadError" class="flex min-h-64 flex-col items-center justify-center gap-3 px-3">
          <p role="alert" class="text-sm text-red-700">{{ loadError }}</p>
          <Button variant="outline" size="sm" @click="load">{{ t('platform.retry') }}</Button>
        </div>
        <p v-else-if="!rows.length" role="status" class="flex min-h-64 items-center justify-center px-3 text-center text-sm text-slate-500">{{ t('agent.attachmentPicker.empty') }}</p>
        <ul v-else class="divide-y divide-slate-100">
          <li v-for="{ dataset, file } in pageRows" :key="file.id" class="px-2 py-1">
            <div class="flex items-center gap-3 rounded-lg py-2">
              <button type="button" class="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400" :aria-label="t('agent.attachmentPicker.details', { name: file.original_filename })" :aria-expanded="details?.file.id === file.id" @click="details = details?.file.id === file.id ? null : { dataset, file }">
                <span class="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500 sm:flex"><FileText class="h-4 w-4" aria-hidden="true" /></span>
                <span class="min-w-0 flex-1"><span class="block truncate text-sm font-medium text-slate-800" :title="file.original_filename">{{ file.original_filename }}</span><span class="block truncate text-xs text-slate-500" :title="dataset.name">{{ dataset.name }}</span></span>
                <ChevronDown class="h-3.5 w-3.5 shrink-0 text-slate-400" :class="{ 'rotate-180': details?.file.id === file.id }" aria-hidden="true" />
              </button>
              <span class="shrink-0 rounded bg-slate-100 px-2 py-1 text-[11px] font-medium uppercase text-slate-600">{{ file.original_filename.split('.').pop() }}</span>
              <Button type="button" size="sm" variant="outline" :aria-label="t('agent.attachmentPicker.selectFile', { name: file.original_filename })" @click="emit('select', dataset, file)">{{ t('agent.attachmentPicker.select') }}</Button>
            </div>
            <dl v-if="details?.file.id === file.id" class="mb-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 rounded-lg bg-slate-50 p-3 text-xs">
              <dt class="text-slate-500">{{ t('agent.attachmentPicker.dataset') }}</dt><dd class="break-all">{{ dataset.name }}</dd>
              <dt class="text-slate-500">{{ t('agent.attachmentPicker.size') }}</dt><dd>{{ file.size_bytes < 1024 ? `${file.size_bytes} B` : file.size_bytes < 1048576 ? `${(file.size_bytes / 1024).toFixed(1)} KB` : `${(file.size_bytes / 1048576).toFixed(1)} MB` }}</dd>
              <dt class="text-slate-500">{{ t('agent.attachmentPicker.uploaded') }}</dt><dd>{{ new Date(file.created_at).toLocaleDateString(locale) }}</dd>
            </dl>
          </li>
        </ul>
      </div>
      <footer class="flex shrink-0 items-center justify-between gap-2 border-t px-5 py-3">
        <span class="text-xs text-slate-500">{{ t('agent.attachmentPicker.page', { page: page + 1 }) }}</span>
        <div class="flex gap-2">
          <Button type="button" size="sm" variant="outline" :disabled="loading || page === 0" @click="changePage(page - 1)">{{ t('platform.previous') }}</Button>
          <Button type="button" size="sm" variant="outline" :disabled="loading || !hasMore" @click="changePage(page + 1)">{{ t('platform.next') }}</Button>
        </div>
      </footer>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { displayErrorMessage } from '@/utils/requestError'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, FileText, LoaderCircle, Search } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import ResourceSort from '@/components/common/ResourceSort.vue'
import { listAllBackendDatasets, type BackendDataset, type BackendDatasetFile } from '@/api/genovaBackend'

const emit = defineEmits<{ close: []; select: [dataset: BackendDataset, file: BackendDatasetFile] }>()
const { t, locale } = useI18n()
const datasets = ref<BackendDataset[]>([]), search = ref(''), page = ref(0)
const sortOrder = ref<'time' | 'name'>('time')
const loading = ref(true), loadError = ref('')
const details = ref<{ dataset: BackendDataset; file: BackendDatasetFile } | null>(null)
const rows = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return datasets.value.flatMap(dataset => dataset.files
    .filter(file => /\.(pdb|cif|mmcif)$/i.test(file.original_filename) || (dataset.files.length === 1 && /\.(sdf|mol|mol2)$/i.test(file.original_filename)))
    .filter(file => !keyword || dataset.name.toLowerCase().includes(keyword) || file.original_filename.toLowerCase().includes(keyword))
    .map(file => ({ dataset, file })))
    .sort((a, b) => sortOrder.value === 'name' ? a.file.original_filename.localeCompare(b.file.original_filename, undefined, { numeric: true, sensitivity: 'base' }) : b.file.created_at.localeCompare(a.file.created_at))
})
const pageRows = computed(() => rows.value.slice(page.value * 20, page.value * 20 + 20))
const hasMore = computed(() => (page.value + 1) * 20 < rows.value.length)
let controller: AbortController | undefined, revision = 0

async function load() {
  const current = ++revision
  controller?.abort(); controller = new AbortController()
  loading.value = true; loadError.value = ''; details.value = null
  try {
    const data = await listAllBackendDatasets({ selectable: true, attachment: true, signal: controller.signal })
    if (current !== revision) return
    datasets.value = data
  } catch (error: any) {
    if (current !== revision) return
    loadError.value = displayErrorMessage(error, t('agent.attachmentPicker.loadFailed'))
  } finally {
    if (current === revision) loading.value = false
  }
}
function changePage(value: number) { page.value = value }
watch([search, sortOrder], () => { page.value = 0 })
onMounted(load)
onBeforeUnmount(() => { revision++; controller?.abort() })
</script>
