<template>
  <div
    class="border-2 border-dashed rounded-lg p-6 text-center transition-colors"
    :class="isDragging ? 'border-violet-500 bg-violet-50' : 'border-slate-300 hover:border-violet-400'"
    @dragover.prevent="isDragging = true"
    @dragleave.prevent="isDragging = false"
    @drop.prevent="handleDrop"
  >
    <p class="text-slate-600 mb-2 text-sm">{{ isDragging ? (t('common.释放文件') || '释放文件以上传') : (uploadLabel ?? t('task.上传文件')) }}</p>
    <p class="text-xs text-slate-500 mb-3">{{ supportedFormats }}</p>
    <Button
      variant="outline"
      size="sm"
      class="bg-violet-50 hover:bg-violet-100 border-violet-200 text-violet-700"
      :disabled="isUploading"
      @click="fileInput?.click()"
    >
      <Upload v-if="!isUploading" class="w-4 h-4 mr-2" />
      <Loader2 v-else class="w-4 h-4 mr-2 animate-spin" />
      {{ isUploading ? (t('task.上传中') || '上传中...') : (t('task.点击上传') || '点击上传') }}
    </Button>
    <Button v-if="isUploading" variant="ghost" size="sm" class="ml-2" @click="cancelUpload">
      {{ t('platform.uploadCancel.action') }}
    </Button>
    <input ref="fileInput" type="file" multiple :accept="accept" class="hidden" @change="handleFileChange" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Upload, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { uploadBackendDataset } from '@/api/genovaBackend'
import { checkUploadFile, uploadCheckMessage } from '@/utils/uploadFileCheck'
import { requestErrorMessage } from '@/utils/requestError'

const props = defineProps<{ accept: string; uploadLabel?: string }>()
const emit = defineEmits<{
  (e: 'upload-complete', data: { uploaded: number; failed: number; canceled?: boolean }): void
  (e: 'upload-error', error: string): void
}>()

const { t } = useI18n()
const isUploading = ref(false)
const isDragging = ref(false)
const fileInput = ref<HTMLInputElement>()
// Aborts the running upload when canceled or when the uploader is closed (unmounted).
let controller: AbortController | null = null
let uploaded = 0
let failed = 0
const cancelUpload = () => controller?.abort()
// Closing the uploader cancels the upload. Report it now: events emitted after unmount are dropped.
onBeforeUnmount(() => {
  if (!controller) return
  controller.abort()
  controller = null
  emit('upload-complete', { uploaded, failed, canceled: true })
})
const extensions = computed(() => props.accept.split(',').map(s => s.trim().replace(/^\./, '').toLowerCase()).filter(Boolean))
const supportedFormats = computed(() =>
  `${t('common.支持格式') || '支持'} ${extensions.value.map(ext => `.${ext.toUpperCase()}`).join(', ')} ${t('common.格式') || '格式'}`)

async function processFiles(files: File[]) {
  if (isUploading.value || !files.length) return
  isUploading.value = true
  const current = controller = new AbortController()
  uploaded = 0
  failed = 0
  try {
    // Check every selected file before any request is sent.
    const accepted: File[] = []
    for (const file of files) {
      const issue = await checkUploadFile(file, extensions.value)
      if (!issue) { accepted.push(file); continue }
      failed++
      emit('upload-error', `${file.name}: ${issue === 'extension' ? t('common.不支持的文件格式') || 'Unsupported file format' : uploadCheckMessage(issue, file.name)}`)
    }
    for (const file of accepted) {
      if (current.signal.aborted) break
      try {
        await uploadBackendDataset({ name: file.name, kind: 'attachment', file, signal: current.signal })
        uploaded++
      } catch (error: any) {
        if (current.signal.aborted) break
        failed++
        const message = requestErrorMessage(error, t('common.上传失败') || 'Upload failed')
        emit('upload-error', `${file.name}: ${message}`)
      }
    }
  } finally {
    isUploading.value = false
    // Not yet reported (the unmount hook reports and clears it when the uploader is closed mid-upload).
    if (controller === current) {
      controller = null
      emit('upload-complete', { uploaded, failed, canceled: current.signal.aborted })
    }
  }
}

async function handleDrop(event: DragEvent) {
  isDragging.value = false
  await processFiles(Array.from(event.dataTransfer?.files || []))
}

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  await processFiles(files)
}
</script>
