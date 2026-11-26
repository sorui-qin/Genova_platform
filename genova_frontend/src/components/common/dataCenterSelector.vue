<template>
  <Tabs v-model="source">
    <TabsList class="mb-3 grid w-full grid-cols-2">
      <TabsTrigger value="mydata">{{ t('data.我的数据') }}</TabsTrigger>
      <TabsTrigger value="builtin">{{ t('platform.builtinExamples') }}</TabsTrigger>
    </TabsList>
    <TabsContent :value="source">
      <ScrollArea class="max-h-[70vh]">
        <div class="mb-3 flex items-center justify-between gap-3">
          <div class="text-sm text-slate-500">
            <span class="font-medium text-slate-700">{{ t('task.数据集') || 'Datasets' }}</span>
            <span class="ml-2" aria-live="polite">{{ listing.loaded ? filteredList.length : '—' }}</span>
            <span v-if="listing.loaded && listing.fetching" role="status" class="ml-2 text-slate-400">{{ $t('platform.refreshing') }}</span>
            <span class="ml-2 text-slate-400">{{ t('task.筛选') || 'filter' }}: {{ filterKey }}</span>
          </div>
          <ResourceSort v-model="sortOrder" />
        </div>

        <div v-if="errorMsg" role="alert" class="mb-3 p-3 border rounded-md bg-red-50 border-red-200 text-red-600 flex items-center justify-between">
          <span class="text-sm truncate">{{ errorMsg }}</span>
          <Button size="sm" variant="outline" class="ml-3" :disabled="listing.fetching" @click="retryLoad">{{ $t('platform.retryLoad') }}</Button>
        </div>

        <div v-if="previewName" class="mb-3 rounded-md border border-slate-200 bg-white p-3">
          <div class="mb-2 flex items-center justify-between gap-2">
            <span class="truncate text-sm font-medium text-slate-700">{{ previewName }}</span>
            <Button variant="ghost" size="sm" class="h-7 px-2" @click="clearPreview">{{ $t('platform.close') }}</Button>
          </div>
          <div class="flex h-48 items-center justify-center overflow-hidden bg-slate-50">
            <Loader2 v-if="previewLoading" class="h-5 w-5 animate-spin text-slate-500" />
            <span v-else-if="previewError" class="px-4 text-center text-sm text-red-600">{{ previewError }}</span>
            <MoleculeViewer v-else :smiles="previewInput" width="100%" height="100%" />
          </div>
        </div>

        <div v-if="isLoading">
          <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            <Skeleton v-for="i in 9" :key="i" class="h-10 w-full" />
          </div>
        </div>

        <div v-else-if="listing.loaded">
          <div v-if="filteredList.length" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            <div
              v-for="item in filteredList"
              :key="item.id"
              class="flex h-10 w-full items-center rounded-md border border-input bg-background"
              :title="item.name"
            >
              <button
                type="button"
                class="flex h-full min-w-0 flex-1 items-center justify-between px-3 text-sm"
                :disabled="loadingItemId !== null || (requiresFileSelection && selectionFiles(item).length > 1 && !selectedFiles[item.id])"
                @click="selectItem(item)"
              >
                <span class="flex min-w-0 items-center overflow-hidden">
                  <Loader2 v-if="loadingItemId === item.id" class="mr-2 h-4 w-4 animate-spin shrink-0" />
                  <span class="truncate" style="max-width: 12rem;">{{ baseName(item.name) }}</span>
                </span>
                <Badge variant="outline" :class="['ml-2 shrink-0', extBadgeClass(primaryExt(item))]">{{ primaryExt(item) }}</Badge>
              </button>
              <select v-if="requiresFileSelection && selectionFiles(item).length > 1" v-model="selectedFiles[item.id]" class="max-w-40 border-l bg-background p-1 text-xs" :aria-label="proteinSelection ? $t('platform.selectProteinFile') : $t('task.选择文件')">
                <option value="">{{ proteinSelection ? $t('platform.selectProteinFile') : $t('task.选择文件') }}</option>
                <option v-for="file in selectionFiles(item)" :key="file.id" :value="file.id">{{ file.original_filename }}</option>
              </select>
              <Button
                v-if="previewFile(item)"
                variant="ghost"
                size="sm"
                class="h-full w-9 shrink-0 rounded-l-none border-l px-0"
                :title="$t('platform.previewMolecule')"
                :disabled="previewLoading"
                @click="previewItem(item)"
              >
                <Eye class="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div v-else class="min-h-[40vh] flex items-center justify-center text-slate-500 text-sm">
            {{ dataList.length ? $t('platform.noMatchingFiles') : t('data.数据中心为空') }}
          </div>
        </div>
      </ScrollArea>
    </TabsContent>
  </Tabs>
</template>

<script setup lang="ts">
import { proteinSourceFiles } from '@/api/proteinContext'
import { translate } from '@/i18n'

import { onBeforeUnmount, computed, ref, watch } from 'vue'
import { isCancelledError } from '@tanstack/vue-query'
import { datacenterIdentity, queryClient } from '@/plugins/tanstack-vue-query'
import { useI18n } from 'vue-i18n'
import { downloadBackendDataset, listAllBackendDatasets, listBuiltinBackendDatasets } from '@/api/genovaBackend'
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import ResourceSort from '@/components/common/ResourceSort.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { Eye, Loader2 } from 'lucide-vue-next'
import { useToast } from '@/components/ui/toast'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getFirstMoleculeInput } from '@/utils/rdkit'
import { displayErrorMessage } from '@/utils/requestError'

interface DatasetItem {
  id: string
  name: string
  kind: string
  created_at: string
  files: Array<{ id: string; original_filename: string }>
  meta?: Record<string, any>
}

interface SelectPayload {
  id: string | number
  name: string
  file_id?: string
  osskey?: string
  count: number
  smilesColumns: Array<{ value: string; label: string }>
}

const selectedFiles = ref<Record<string, string>>({})
const props = defineProps<{ filetypes?: string[]; selectFile?: boolean }>()
const emit = defineEmits<{ 
  (e: 'select', payload: SelectPayload): void
  (e: 'error', error: string): void
}>()

const { t } = useI18n()
const { toast } = useToast()

type DataSource = 'mydata' | 'builtin'
const source = ref<DataSource>('mydata')
const sources = ref({
  mydata: { items: [] as DatasetItem[], loaded: false, fetching: false, error: '' },
  builtin: { items: [] as DatasetItem[], loaded: false, fetching: false, error: '' },
})
const listing = computed(() => sources.value[source.value])
const isLoading = computed(() => listing.value.fetching && !listing.value.loaded)
const errorMsg = computed(() => listing.value.error)
const dataList = computed(() => listing.value.items)
const requests = { mydata: 0, builtin: 0 }
let active = true
let previewRequest = 0
const searchQuery = ref('')
const sortOrder = ref<'time' | 'name'>('time')
const loadingItemId = ref<string | number | null>(null)
const previewLoading = ref(false)
const previewName = ref('')
const previewInput = ref('')
const previewError = ref('')

const normalizedRequestedExts = computed(() => {
  const raw = props.filetypes || []
  const expanded = raw.flatMap((type) => {
    const lower = String(type || '').toLowerCase()
    if (lower === 'smiles') return ['smi', 'csv', 'txt']
    return [lower]
  })
  return Array.from(new Set(expanded.filter(Boolean)))
})

const proteinSelection = computed(() => normalizedRequestedExts.value.includes('cif'))
const requiresFileSelection = computed(() => proteinSelection.value || props.selectFile)

function selectionFiles(item: DatasetItem) {
  if (proteinSelection.value) return proteinSourceFiles(item)
  return item.files.filter(file => !normalizedRequestedExts.value.length || normalizedRequestedExts.value.includes(extName(file.original_filename).toLowerCase()))
}

const filterKey = computed(() => {
  if (normalizedRequestedExts.value.length === 0) return 'all'
  return normalizedRequestedExts.value.join(',')
})

function getDatasetExts(item: DatasetItem): string[] {
  const exts = (item.files || [])
    .map((f) => String(f.original_filename || '').toLowerCase().split('.').pop() || '')
    .filter(Boolean)
  return Array.from(new Set(exts))
}

function matchesRequestedTypes(item: DatasetItem): boolean {
  if (['protein_context', 'prepared_receptor'].includes(item.kind)) return false
  if (normalizedRequestedExts.value.length === 0) return true
  const exts = getDatasetExts(item)
  return exts.some((ext) => normalizedRequestedExts.value.includes(ext))
}

const filteredList = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return (dataList.value || [])
    .filter((item) => matchesRequestedTypes(item))
    .filter(item => (query ? String(item.name || '').toLowerCase().includes(query) : true))
    .sort((a, b) => sortOrder.value === 'name' ? a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }) : b.created_at.localeCompare(a.created_at))
})

function baseName(name: string) {
  if (!name) return ''
  const parts = name.split('.')
  return parts.length > 1 ? parts.slice(0, -1).join('.') : name
}

function extName(name: string) {
  if (!name) return ''
  const parts = name.split('.')
  return parts.length > 1 ? (parts.pop() || '') : ''
}

function primaryExt(item: DatasetItem): string {
  const fromName = extName(item.name).toLowerCase()
  if (fromName) return fromName
  return getDatasetExts(item)[0] || ''
}

function extBadgeClass(extRaw: string) {
  const ext = (extRaw || '').toLowerCase()
  // map groups
  if (['sdf'].includes(ext)) return 'bg-emerald-100 text-emerald-800 border-emerald-200'
  if (['csv', 'tsv'].includes(ext)) return 'bg-sky-100 text-sky-800 border-sky-200'
  if (['pdf'].includes(ext)) return 'bg-rose-100 text-rose-800 border-rose-200'
  if (['pdb', 'ent', 'cif', 'mmcif'].includes(ext)) return 'bg-indigo-100 text-indigo-800 border-indigo-200'
  if (['txt', 'log'].includes(ext)) return 'bg-slate-100 text-slate-800 border-slate-200'
  if (['png'].includes(ext)) return 'bg-purple-100 text-purple-800 border-purple-200'
  if (['jpg', 'jpeg'].includes(ext)) return 'bg-fuchsia-100 text-fuchsia-800 border-fuchsia-200'
  // default
  return 'bg-secondary text-secondary-foreground border-secondary'
}

function previewFile(item: DatasetItem) {
  const requested = (props.filetypes || []).map((type) => String(type).toLowerCase())
  if (requested.length && !requested.some((type) => ['mol', 'sdf', 'smi', 'smiles', 'csv', 'tsv', 'txt'].includes(type))) return
  return item.files.find((file) => ['sdf', 'mol', 'smi', 'csv', 'tsv', 'txt'].includes(extName(file.original_filename).toLowerCase()))
}

function clearPreview() {
  previewRequest++
  previewLoading.value = false
  previewName.value = ''
  previewInput.value = ''
  previewError.value = ''
}

async function previewItem(item: DatasetItem) {
  const file = previewFile(item)
  if (!file) return
  const request = ++previewRequest
  previewLoading.value = true
  previewName.value = file.original_filename
  previewInput.value = ''
  previewError.value = ''
  try {
    const response = await downloadBackendDataset(item.id, file.id)
    const content = await response.data.text()
    if (!active || request !== previewRequest) return
    previewInput.value = getFirstMoleculeInput(content, file.original_filename)
    if (!previewInput.value) previewError.value = translate('platform.noSmilesOrMoleculeStructureFound')
  } catch (error: any) {
    if (!active || request !== previewRequest) return
    previewError.value = displayErrorMessage(error, translate('platform.failedToLoadMoleculePreview'))
  } finally {
    if (active && request === previewRequest) previewLoading.value = false
  }
}

async function loadData(target: DataSource = source.value) {
  const identity = datacenterIdentity.value
  const request = ++requests[target]
  const state = sources.value[target]
  const queryKey = ['datacenter', ...identity, 'selector', target, 'selectable']
  const cached = queryClient.getQueryData<DatasetItem[]>(queryKey)
  if (cached) { state.items = cached; state.loaded = true }
  state.fetching = true
  state.error = ''
  try {
    const items = await queryClient.fetchQuery({
      queryKey, staleTime: 60_000, gcTime: 300_000, retry: false,
      queryFn: ({ signal }) => target === 'mydata'
        ? listAllBackendDatasets({ summary: true, selectable: true, signal })
        : listBuiltinBackendDatasets({ summary: true, selectable: true, signal }).then(response => response.data),
    })
    if (!active || request !== requests[target] || identity !== datacenterIdentity.value) return
    state.items = items
    state.loaded = true
  } catch (err: any) {
    if (!active || request !== requests[target] || identity !== datacenterIdentity.value || isCancelledError(err)) return
    state.error = `${translate('platform.loadFailed')}: ${displayErrorMessage(err, translate('platform.unknownError'))}`
  } finally {
    if (active && request === requests[target] && identity === datacenterIdentity.value) state.fetching = false
  }
}

function retryLoad() {
  void loadData()
}

async function selectItem(item: DatasetItem) {
  const id = item.id
  const name = item.name
  
  if (!id || !name) return
  
  // Set loading state for this item
  loadingItemId.value = id
  
  try {
    const datasetExts = getDatasetExts(item)
    const smilesColumns = datasetExts.some((ext) => ['sdf', 'smi', 'csv', 'txt'].includes(ext))
      ? [{ value: 'smiles', label: 'SMILES' }]
      : []
    
    // Emit success with all data
    emit('select', {
      id,
      name,
      file_id: requiresFileSelection.value ? selectedFiles.value[item.id] || selectionFiles(item)[0]?.id : undefined,
      count: (item.files || []).length || 1,
      smilesColumns,
    })
  } catch (err: any) {
    console.error('Failed to load dataset details:', err)
    const errorMessage = displayErrorMessage(err, t('task.加载失败'))
    
    toast({
      variant: 'destructive',
      title: t('common.error') || 'Error',
      description: errorMessage,
      duration: 5000
    })
    
    emit('error', errorMessage)
  } finally {
    loadingItemId.value = null
  }
}

watch(source, clearPreview)

watch([datacenterIdentity, source], ([identity], previous) => {
  if (previous && identity !== previous[0]) {
    for (const key of ['mydata', 'builtin'] as const) {
      requests[key]++
      Object.assign(sources.value[key], { items: [], loaded: false, fetching: false, error: '' })
    }
    selectedFiles.value = {}
    loadingItemId.value = null
    clearPreview()
  }
  if (identity[0]) void loadData()
}, { immediate: true })

onBeforeUnmount(() => { active = false; previewRequest++ })
</script>

<style scoped>
/***** keep styles minimal, rely on utility classes *****/
</style>
