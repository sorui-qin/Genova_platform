<template>
  <div class="space-y-2">
    <label class="block space-y-1 text-sm"><span>{{ L('参考分子集（相似性比较）', 'Reference molecule set (similarity)') }}</span><select v-model="model" :disabled="disabled || loading" class="w-full min-w-0 rounded border bg-white p-2"><option value="">{{ L('不使用', 'Not used') }}</option><option v-for="dataset in choices" :key="dataset.id" :value="dataset.id">{{ dataset.name }} · {{ dataset.files?.map(file => file.original_filename).join(', ') }}</option></select></label>
    <div class="flex flex-wrap items-center gap-2"><ResourceSort v-model="sortOrder" /><input v-model="search" type="search" :aria-label="L('查找参考分子集', 'Search reference sets')" :placeholder="L('按名称或文件名查找', 'Search by name or filename')" class="min-w-0 flex-1 rounded border p-2 text-sm" /><label class="cursor-pointer rounded border bg-white px-3 py-2 text-sm">{{ loading ? L('上传中…', 'Uploading…') : L('上传分子集', 'Upload set') }}<input type="file" accept=".sdf,.smi,.txt" class="sr-only" :disabled="disabled || loading" @change="upload" /></label></div>
    <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ResourceSort from '@/components/common/ResourceSort.vue'
import { listAllBackendDatasets, uploadBackendDataset, type BackendDataset } from '@/api/genovaBackend'
import { displayErrorMessage } from '@/utils/requestError'
const props = defineProps<{ disabled?: boolean }>()
const model = defineModel<string>({ required: true })
const emit = defineEmits<{ busy: [value: boolean] }>()
const { locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const rows = ref<BackendDataset[]>([]), search = ref(''), loading = ref(false), error = ref('')
const sortOrder = ref<'time' | 'name'>('time')
const choices = computed(() => rows.value.filter(dataset => dataset.id === model.value || (dataset.files?.some(file => /\.(sdf|smi|txt)$/i.test(file.original_filename)) && `${dataset.name} ${dataset.files.map(file => file.original_filename).join(' ')}`.toLowerCase().includes(search.value.toLowerCase()))).sort((a, b) => sortOrder.value === 'name' ? a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }) : b.created_at.localeCompare(a.created_at)))
onMounted(async () => { try { rows.value = await listAllBackendDatasets({ selectable: true }) } catch { error.value = L('读取参考分子集失败，请重新打开此面板。', 'Could not load reference sets. Reopen this panel.') } })
async function upload(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  input.value = ''
  if (!file || props.disabled || loading.value) return
  if (!/\.(sdf|smi|txt)$/i.test(file.name)) { error.value = L('请选择 SDF 或 SMILES 文本文件。', 'Choose SDF or SMILES text.'); return }
  loading.value = true; emit('busy', true); error.value = ''
  try {
    const dataset = (await uploadBackendDataset({ name: file.name, kind: 'ligand', file, fileRole: 'attachment' })).data
    rows.value = [dataset, ...rows.value.filter(row => row.id !== dataset.id)]
    search.value = ''; model.value = dataset.id
  } catch (exc: any) { error.value = displayErrorMessage(exc, L('上传失败，请重试。', 'Upload failed. Please retry.')) }
  finally { loading.value = false; emit('busy', false) }
}
</script>
