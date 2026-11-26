<template>
  <div class="flex h-full min-h-0 flex-col gap-2 bg-white p-3 text-slate-800">
    <p v-if="status === 'pending' || status === 'queued' || status === 'running'" role="status" class="p-4 text-sm">{{ t('platform.binding2dComputing') }}</p>
    <div v-else-if="error || renderError || status === 'failed'" role="alert" class="p-4 text-sm text-red-700">
      <p>{{ error || renderError }}</p>
      <button class="mt-2 rounded border px-3 py-1" @click="$emit('retry')">{{ t('common.retry') }}</button>
    </div>
    <template v-else-if="diagram">
      <p class="text-xs text-slate-600">{{ t('platform.binding2dHelp') }}</p>
      <div ref="drawingArea" class="min-h-0 flex-1">
        <svg :id="svgId" class="h-full w-full rounded border" :aria-label="t('platform.binding2d')" />
      </div>
      <p v-if="!diagram.interactions.length" class="text-sm">{{ t('platform.bindingNoInteractions') }}</p>
      <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span v-for="type in types" :key="type" class="flex items-center gap-1">
          <svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" :stroke="styleFor(type).color" :stroke-dasharray="styleFor(type).dash" stroke-width="2" /></svg>{{ type }}
        </span>
      </div>
    </template>
  </div>
</template>

<script lang="ts">
import { withAppBase } from '@/utils/appBase'

let libraryPromise: Promise<void> | undefined
function loadLibrary(): Promise<void> {
  if ((window as any).InteractionDrawer?.Drawer) return Promise.resolve()
  return libraryPromise ||= new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = withAppBase('static/file/interaction-drawer.standalone.js')
    script.async = true
    script.onload = () => { script.remove(); resolve() }
    script.onerror = () => { script.remove(); libraryPromise = undefined; reject(new Error('InteractionDrawer failed to load')) }
    document.head.appendChild(script)
  })
}
</script>

<script setup lang="ts">
import { randomUUID } from '@/utils/uuid'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { displayErrorMessage } from '@/utils/requestError'

const props = defineProps<{ diagram?: any; status?: string; error?: string }>()
const emit = defineEmits(['retry', 'residue-select'])
const { t } = useI18n()
const svgId = `interaction-2d-${randomUUID()}`
const drawingArea = ref<HTMLElement>()
const renderError = ref('')
const types = computed(() => [...new Set<string>((props.diagram?.interactions || []).map((item: any) => item.type))])
const styleFor = (type: string) => {
  if (type.startsWith('H-Bond')) return { color: '#2563eb', dash: '3 2' }
  if (type.startsWith('Salt Bridge')) return { color: '#db2777', dash: '5 2' }
  if (type.startsWith('Pi-cation')) return { color: '#9333ea', dash: '3 2' }
  if (type === 'Pi-stacking') return { color: '#0891b2', dash: '3 2' }
  if (type === 'Halogen bond') return { color: '#b45309', dash: '2 2' }
  return { color: '#15803d', dash: '1 2' }
}
let drawer: any
let observer: ResizeObserver | undefined
let revision = 0
function dispose() {
  observer?.disconnect()
  if (!drawer) return
  const handler = drawer.userInteractionHandler
  window.removeEventListener('resize', handler.resizeHandler)
  for (const { target, type, fn } of handler.subscribedFunctions) {
    if (type) (target || document).removeEventListener(type, fn)
  }
  drawer = undefined
}
watch(() => props.diagram, async (diagram) => {
  const current = ++revision
  dispose()
  renderError.value = ''
  if (!diagram) return
  await nextTick()
  if (current !== revision) return
  try {
    await loadLibrary()
    if (current !== revision) return
    const library = (window as any).InteractionDrawer
    if (!library?.Drawer) throw new Error(t('platform.binding2dLibraryUnavailable'))
    const svg = document.getElementById(svgId)!
    svg.replaceChildren()
    drawer = new library.Drawer(svgId, {
      textSize: 6.5, sceneMinScale: 0.1, sceneMaxScale: 5,
      allowedInteraction: ['globalMovement', 'clickSelect', 'zoomIn', 'zoomOut', 'center'],
      defaultInteraction: 'clickSelect',
      buttons: { mouse: { clickSelect: [{ key: 0, modifiers: [] }], globalMovement: [{ key: 2, modifiers: [] }] } },
      structureCircleOpts: { default: { circleCss: { stroke: '#94a3b8', fill: '#f1f5f9', opacity: '1' }, textColor: '#334155', rad: 20 } },
      colors: { BACKGROUND: '#ffffff', HOVER: '#bfdbfe', SELECTION: '#93c5fd' },
    })
    drawer.setCallbacks({ selectionCallback: (info: any) => {
      if (info.type !== 'structureCircle' || info.selectionType !== 'select') return
      const structure = diagram.scene.structures.find((item: any) => item.id === info.structureId)
      if (structure?.additionalInformation?.residue_id) emit('residue-select', structure.additionalInformation.residue_id)
    } })
    drawer.addByJSON(JSON.stringify({ scene: diagram.scene }))
    if (Object.keys(drawer.sceneData.structuresData.structures).length !== diagram.scene.structures.length) throw new Error(t('platform.binding2dFailed'))
    const view = document.getElementById(`${svgId}_view`)!
    const ns = 'http://www.w3.org/2000/svg'
    const lines = document.createElementNS(ns, 'g')
    lines.setAttribute('data-plip-interactions', '')
    view.prepend(lines)
    for (const interaction of diagram.interactions) {
      const group = document.createElementNS(ns, 'g')
      const style = styleFor(interaction.type)
      const line = document.createElementNS(ns, 'line')
      for (const [key, value] of Object.entries({ x1: interaction.start.x, y1: interaction.start.y, x2: interaction.end.x, y2: interaction.end.y,
        stroke: style.color, 'stroke-width': 1, 'stroke-dasharray': style.dash })) line.setAttribute(key, String(value))
      const title = document.createElementNS(ns, 'title')
      const [chain, name, number, insertion] = interaction.residue_id.split('|')
      title.textContent = `${interaction.type} · ${chain || '∅'}:${name}${number}${insertion} · ${interaction.distance.toFixed(2)} Å`
      group.append(title, line)
      if (interaction.ligand_atom_ids.length > 1) {
        const circle = document.createElementNS(ns, 'circle')
        for (const [key, value] of Object.entries({ cx: interaction.start.x, cy: interaction.start.y, r: 2, fill: 'white', stroke: style.color })) circle.setAttribute(key, String(value))
        group.append(circle)
      }
      lines.append(group)
    }
    for (const structure of diagram.scene.structures.slice(1)) {
      const circle = document.getElementById(`${svgId}_s_${structure.id}_sc`)
      circle?.setAttribute('role', 'button')
      circle?.setAttribute('tabindex', '0')
      circle?.setAttribute('aria-label', structure.structureLabel)
      circle?.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); emit('residue-select', structure.additionalInformation.residue_id) }
      })
    }
    observer = new ResizeObserver(() => drawer?.svgDrawer.viewerDrawer.resize())
    if (drawingArea.value) observer.observe(drawingArea.value)
  } catch (exc: any) {
    if (current !== revision) return
    dispose()
    renderError.value = displayErrorMessage(exc, t('platform.failedToRenderThe3dStructure'))
  }
}, { immediate: true })
onBeforeUnmount(() => { revision++; dispose() })
</script>
