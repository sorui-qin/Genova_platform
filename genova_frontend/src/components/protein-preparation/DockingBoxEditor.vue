<template>
  <div class="space-y-3">
    <div class="text-sm font-semibold text-slate-900">{{ $t('platform.dockingBox') }} (Å)</div>
    <p class="text-xs text-muted-foreground">{{ $i18n.locale.startsWith('zh') ? '用于后续分子对接。' : 'Used for subsequent molecular docking.' }}</p>
    <div class="grid grid-cols-3 gap-2">
      <div v-for="(label, index) in [$t('platform.centerX'), $t('platform.centerY'), $t('platform.centerZ')]" :key="label" class="space-y-1">
        <Label class="text-xs">{{ label }}</Label>
        <Input type="number" step="0.001" :model-value="display(center[index], `center-${index}`)" @focus="beginEdit(center[index], `center-${index}`)" @blur="endEdit(`center-${index}`)" @update:model-value="update(center, index, $event, 'center')" />
      </div>
      <div v-for="(label, index) in [$t('platform.sizeX'), $t('platform.sizeY'), $t('platform.sizeZ')]" :key="label" class="space-y-1">
        <Label class="text-xs">{{ label }}</Label>
        <Input type="number" min="0.1" step="0.001" :model-value="display(size[index], `size-${index}`)" @focus="beginEdit(size[index], `size-${index}`)" @blur="endEdit(`size-${index}`)" @update:model-value="update(size, index, $event, 'size')" />
      </div>
    </div>
    <div class="flex gap-2">
      <Button size="sm" variant="outline" @click="$emit('reset')">{{ $t('platform.resetTo20') }}</Button>
      <Button size="sm" variant="outline" :disabled="!canRecenter" @click="$emit('recenter')">{{ $t('platform.centerOnSelection') }}</Button>
    </div>
  </div>
</template>

<script setup lang="ts">

import { nextTick, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

defineProps<{ center: number[]; size: number[]; canRecenter: boolean }>()
const emit = defineEmits<{
  'update:center': [value: number[]]
  'update:size': [value: number[]]
  reset: []
  recenter: []
}>()
const activeField = ref<string | null>(null)
const draft = ref('')

function update(source: number[], index: number, value: string | number, field: 'center' | 'size') {
  activeField.value = `${field}-${index}`
  draft.value = String(value)
  const next = [...source]
  next[index] = Number(value)
  if (field === 'center') emit('update:center', next)
  else emit('update:size', next)
}

function format(value: number) {
  return Number.isFinite(value) ? value.toFixed(3) : value
}

function display(value: number, key: string) {
  return activeField.value === key ? draft.value : format(value)
}

function beginEdit(value: number, key: string) {
  activeField.value = key
  draft.value = String(format(value))
}

// The input corrects an out-of-range number on blur and emits it on the next tick; wait for it so the corrected
// value does not reopen the draft after editing ended.
async function endEdit(key: string) {
  await nextTick()
  if (activeField.value !== key) return
  activeField.value = null
  draft.value = ''
}
</script>
