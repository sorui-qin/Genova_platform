<template>
  <div class="flex h-full min-h-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" :disabled="zoom >= 3" :aria-label="$t('platform.zoomIn')" @click="zoom = Math.min(3, zoom + 0.25)"><ZoomIn class="h-4 w-4" /></Button>
      <Button variant="outline" size="sm" :disabled="zoom <= 0.5" :aria-label="$t('platform.zoomOut')" @click="zoom = Math.max(0.5, zoom - 0.25)"><ZoomOut class="h-4 w-4" /></Button>
      <span class="w-12 text-center text-xs text-slate-500">{{ Math.round(zoom * 100) }}%</span>
      <Button variant="outline" size="sm" :aria-label="$t('platform.rotateView')" @click="rotation = (rotation + 30) % 360"><RotateCw class="h-4 w-4" /></Button>
      <Button variant="outline" size="sm" @click="resetView"><Focus class="mr-1 h-4 w-4" />{{ $t('platform.resetView') }}</Button>
      <span class="text-xs text-slate-500">{{ caption || $t('platform.firstMoleculePreview') }}</span>
    </div>
    <div class="relative min-h-[120px] flex-1 touch-none overflow-hidden border border-slate-200 bg-white outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      :class="dragging ? 'cursor-grabbing' : 'cursor-grab'" tabindex="0" role="group" :aria-label="$t('platform.panMoleculeHint')"
      @pointerdown="startPan" @pointermove="movePan" @pointerup="endPan" @pointercancel="endPan" @lostpointercapture="endPan" @keydown="panWithKeyboard">
      <MoleculeViewer :smiles="input" width="100%" height="100%" :bond-width="1" :max-font-size="16" :regenerate-coords="true" :remove-hs="true"
        :rotation="rotation" :style="{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }"
        :loading-text="$t('platform.loading')" :error-text="$t('platform.moleculePreviewFailed')" />
    </div>
    <p class="text-xs text-slate-500">{{ $t('platform.panMoleculeHint') }}</p>
    <div class="max-h-[35%] shrink-0 overflow-auto border border-slate-200 bg-slate-50 p-3 text-sm" aria-live="polite">
      <div v-if="propertiesLoading">{{ $t('platform.loading') }}</div>
      <dl v-else-if="properties" class="grid gap-x-4 gap-y-2 sm:grid-cols-[auto_1fr_auto_1fr]">
        <dt class="text-slate-500">{{ $t('platform.moleculeFormula') }}</dt><dd>{{ properties.formula }}</dd>
        <dt class="text-slate-500">{{ $t('platform.moleculeWeight') }}</dt><dd>{{ properties.weight.toFixed(3) }} g/mol</dd>
        <dt class="text-slate-500">{{ $t('platform.formalCharge') }}</dt><dd>{{ properties.charge }}</dd>
        <dt class="text-slate-500">SMILES</dt><dd class="break-all font-mono text-xs">{{ properties.smiles }}</dd>
      </dl>
      <p v-else>{{ $t('platform.moleculePropertiesUnavailable') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { Focus, RotateCw, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import MoleculeViewer from './MoleculeViewer.vue'
import { getMoleculeProperties } from '@/utils/moleculeProperties'

const props = defineProps<{ input: string; caption?: string }>()
const zoom = ref(1), rotation = ref(0)
const pan = ref({ x: 0, y: 0 }), dragging = ref(false)
let pointer: { id: number; x: number; y: number; panX: number; panY: number; target: HTMLElement } | null = null
function releasePan() {
  const active = pointer
  pointer = null
  dragging.value = false
  if (active?.target.hasPointerCapture(active.id)) active.target.releasePointerCapture(active.id)
}
function startPan(event: PointerEvent) {
  if (event.button !== 0 || pointer) return
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, panX: pan.value.x, panY: pan.value.y, target }
  dragging.value = true
  target.focus()
  event.preventDefault()
}
function movePan(event: PointerEvent) {
  if (!pointer || pointer.id !== event.pointerId) return
  pan.value = { x: pointer.panX + event.clientX - pointer.x, y: pointer.panY + event.clientY - pointer.y }
}
function endPan(event: PointerEvent) { if (pointer?.id === event.pointerId) releasePan() }
function panWithKeyboard(event: KeyboardEvent) {
  const shifts: Record<string, [number, number]> = { ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] }
  if (event.key === 'Home') { event.preventDefault(); resetView(); return }
  const shift = shifts[event.key]
  if (!shift) return
  event.preventDefault()
  releasePan()
  pan.value = { x: pan.value.x + shift[0], y: pan.value.y + shift[1] }
}
const properties = ref<Awaited<ReturnType<typeof getMoleculeProperties>> | null>(null)
const propertiesLoading = ref(false)
function resetView() { releasePan(); zoom.value = 1; rotation.value = 0; pan.value = { x: 0, y: 0 } }
onBeforeUnmount(releasePan)
watch(() => props.input, async (input, _, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  resetView()
  properties.value = null
  propertiesLoading.value = true
  try {
    const result = await getMoleculeProperties(input)
    if (active) properties.value = result
  } catch {
    // Keep the structure visible if properties are unavailable for this input.
  } finally { if (active) propertiesLoading.value = false }
}, { immediate: true })
</script>
