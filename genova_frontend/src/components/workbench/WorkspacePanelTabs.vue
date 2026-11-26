<template>
  <div role="tablist" :aria-label="label" class="flex min-w-0 flex-wrap gap-1">
    <Button v-for="(tab, index) in tabs" :key="tab.value" :ref="element => buttons[index] = element" role="tab" :aria-selected="model === tab.value" :tabindex="model === tab.value ? 0 : -1" :variant="model === tab.value ? 'secondary' : 'ghost'" size="sm" @click="model = tab.value" @keydown="move($event, index)">{{ tab.label }}</Button>
  </div>
</template>
<script setup lang="ts">
import { nextTick } from 'vue'
import { Button } from '@/components/ui/button'
const props = defineProps<{ tabs: Array<{ value: string; label: string }>; label: string }>()
const model = defineModel<string>({ required: true })
const buttons: any[] = []
async function move(event: KeyboardEvent, index: number) {
  const count = props.tabs.length
  const next = { ArrowLeft: (index + count - 1) % count, ArrowRight: (index + 1) % count, Home: 0, End: count - 1 }[event.key]
  if (next === undefined) return
  event.preventDefault()
  model.value = props.tabs[next].value
  await nextTick()
  buttons[next]?.$el?.focus()
}
</script>
