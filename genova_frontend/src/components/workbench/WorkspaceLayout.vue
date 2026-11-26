<template>
  <div ref="layout" class="workspace-layout" :class="{ 'panel-open': open, 'panel-drawer': narrow, 'panel-resizable': resizable && open && !narrow, 'panel-resizing': dragging }" :style="resizable ? { '--workspace-left': `${leftSize}fr`, '--workspace-right': `${100 - leftSize}fr` } : undefined">
    <div class="workspace-main" :inert="open && narrow"><slot /></div>
    <div v-if="resizable && open && !narrow" role="separator" tabindex="0" aria-orientation="vertical" :aria-label="$t('platform.resizePanels')" :aria-valuenow="Math.round(leftSize)" :aria-valuemin="25" :aria-valuemax="75" class="workspace-divider" @pointerdown="startResize" @pointermove="resize" @pointerup="dragging = false" @pointercancel="dragging = false" @lostpointercapture="dragging = false" @keydown="resizeWithKeyboard" @dblclick="leftSize = 50"></div>
    <button v-if="open && narrow" class="workspace-scrim" type="button" :aria-label="$t('platform.closePanel')" @click="$emit('update:open', false)" />
    <FocusScope as-child :trapped="open && narrow" :loop="open && narrow" @mount-auto-focus.prevent @unmount-auto-focus.prevent>
      <aside ref="panel" tabindex="-1" v-show="open" class="workspace-auxiliary" :role="narrow ? 'dialog' : 'complementary'" :aria-modal="narrow ? true : undefined" :aria-label="title" @keydown.esc.stop="$emit('update:open', false)">
        <header class="flex shrink-0 items-center justify-between gap-3 border-b p-4">
          <slot name="panel-header"><h2 class="text-base font-semibold">{{ title }}</h2></slot>
          <Button v-if="!persistent || narrow" variant="ghost" size="icon" :aria-label="$t('platform.closePanel')" @click="$emit('update:open', false)"><X class="h-4 w-4" aria-hidden="true" /></Button>
        </header>
        <div class="min-h-0 flex-1 overflow-auto overscroll-contain p-4"><slot name="auxiliary" /></div>
      </aside>
    </FocusScope>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useElementSize } from '@vueuse/core'
import { FocusScope } from 'radix-vue'
import { X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
const props = defineProps<{ open: boolean; title: string; resizable?: boolean; initialLeft?: number; storageKey?: string; persistent?: boolean }>()
defineEmits<{ 'update:open': [value: boolean] }>()
const layout = ref<HTMLElement | null>(null)
const { width } = useElementSize(layout)
const narrow = computed(() => width.value > 0 && width.value < (props.resizable ? 768 : 1100))
const savedSize = props.storageKey ? Number(localStorage.getItem(props.storageKey)) : 0
const leftSize = ref(savedSize >= 25 && savedSize <= 75 ? savedSize : props.initialLeft || 50), dragging = ref(false)
watch(leftSize, value => { if (props.storageKey) localStorage.setItem(props.storageKey, String(value)) })
function resize(event: PointerEvent) {
  if (!dragging.value || !layout.value) return
  const bounds = layout.value.getBoundingClientRect()
  leftSize.value = Math.max(25, Math.min(75, (event.clientX - bounds.left - 3) / (bounds.width - 6) * 100))
}
function startResize(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  dragging.value = true
  resize(event)
}
function resizeWithKeyboard(event: KeyboardEvent) {
  const step = event.shiftKey ? 10 : 2
  const values: Record<string, number> = { ArrowLeft: leftSize.value - step, ArrowRight: leftSize.value + step, Home: 25, End: 75 }
  if (!(event.key in values)) return
  event.preventDefault()
  leftSize.value = Math.max(25, Math.min(75, values[event.key]))
}
const panel = ref<HTMLElement | null>(null)
let opener: HTMLElement | null = null
watch(() => props.open, async open => {
  if (open) { opener = document.activeElement as HTMLElement; await nextTick(); if (narrow.value) panel.value?.focus() }
  else if (panel.value?.contains(document.activeElement)) { await nextTick(); opener?.focus() }
})
</script>
<style scoped>
.workspace-layout { display: flex; position: relative; height: 100%; min-height: 0; min-width: 0; overflow: hidden; }
.workspace-main { flex: 1; min-width: 0; min-height: 0; overflow: auto; overscroll-behavior: contain; }
.workspace-auxiliary { display: flex; flex-direction: column; width: 336px; flex-shrink: 0; min-height: 0; border-left: 1px solid var(--border-default); background: var(--surface); }
.panel-resizable { display: grid; grid-template-columns: minmax(0, var(--workspace-left)) 6px minmax(0, var(--workspace-right)); }
.panel-resizable .workspace-auxiliary { width: auto; min-width: 0; border-left: 0; }
.workspace-divider { touch-action: none; cursor: col-resize; background: linear-gradient(to right, transparent 2px, var(--border-default) 2px, var(--border-default) 3px, transparent 3px); }
.workspace-divider:hover, .workspace-divider:focus-visible, .panel-resizing .workspace-divider { background: linear-gradient(to right, transparent 2px, hsl(var(--primary)) 2px, hsl(var(--primary)) 3px, transparent 3px); }
.workspace-divider:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: -2px; }
.panel-resizing { user-select: none; cursor: col-resize; }
.panel-resizing .workspace-main, .panel-resizing .workspace-auxiliary { pointer-events: none; }
.workspace-scrim { position: absolute; inset: 0; z-index: 30; background: rgb(23 43 77 / 24%); }
.panel-drawer .workspace-auxiliary { position: absolute; inset: 0 0 0 auto; z-index: 31; width: min(360px, 100%); box-shadow: -8px 0 32px rgb(23 43 77 / 10%); }
</style>
