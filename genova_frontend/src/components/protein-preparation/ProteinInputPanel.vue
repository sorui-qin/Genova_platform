<template>
  <div class="space-y-3">
    <div class="text-sm font-semibold text-slate-900">{{ $t('platform.proteinInput') }}</div>
    <div class="rounded-lg border-2 border-dashed border-slate-300 p-4 text-center">
      <p class="mb-3 text-xs text-slate-500">{{ label || $t('platform.selectOrUploadAPdbFile') }}</p>
      <div class="flex justify-center gap-2">
        <Button size="sm" variant="outline" :disabled="loading" @click="input?.click()">{{ $t('platform.uploadPdb') }}</Button>
        <Button size="sm" variant="outline" :disabled="loading" @click="$emit('choose')">{{ $t('platform.dataCenter') }}</Button>
      </div>
      <input ref="input" class="hidden" type="file" accept=".pdb,.cif,.mmcif" @change="onChange">
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '@/components/ui/button'

defineProps<{ label?: string; loading?: boolean }>()
const emit = defineEmits<{ upload: [file: File]; choose: [] }>()
const input = ref<HTMLInputElement | null>(null)

function onChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (file) emit('upload', file)
}
</script>
