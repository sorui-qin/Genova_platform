<template>
  <div ref="root" class="molecule-viewer" :style="{ width: width, height: height }">
    <div v-if="loading && !svgContent" class="flex flex-col items-center justify-center h-full w-full bg-slate-50 p-4 space-y-3 overflow-hidden">
      <!-- Molecule structure skeleton -->
      <div class="flex items-center justify-center w-full flex-1">
        <div class="relative">
          <!-- Central node -->
          <Skeleton class="w-3 h-3 rounded-full" />
          <!-- Surrounding nodes in a hexagonal pattern -->
          <Skeleton class="w-2 h-2 rounded-full absolute -top-8 left-1/2 transform -translate-x-1/2" />
          <Skeleton class="w-2 h-2 rounded-full absolute -top-4 -right-6" />
          <Skeleton class="w-2 h-2 rounded-full absolute top-4 -right-6" />
          <Skeleton class="w-2 h-2 rounded-full absolute top-8 left-1/2 transform -translate-x-1/2" />
          <Skeleton class="w-2 h-2 rounded-full absolute top-4 -left-6" />
          <Skeleton class="w-2 h-2 rounded-full absolute -top-4 -left-6" />
          <!-- Connection lines -->
          <Skeleton class="w-8 h-0.5 absolute -top-6 left-1/2 transform -translate-x-1/2 rotate-45" />
          <Skeleton class="w-8 h-0.5 absolute -right-4 top-0 transform -translate-y-1/2 rotate-90" />
          <Skeleton class="w-8 h-0.5 absolute -right-4 top-4 transform -translate-y-1/2 rotate-45" />
          <Skeleton class="w-8 h-0.5 absolute top-6 left-1/2 transform -translate-x-1/2 -rotate-45" />
          <Skeleton class="w-8 h-0.5 absolute -left-4 top-4 transform -translate-y-1/2 -rotate-45" />
          <Skeleton class="w-8 h-0.5 absolute -left-4 top-0 transform -translate-y-1/2 rotate-90" />
        </div>
      </div>
      <!-- SMILES text skeleton -->
      <Skeleton class="h-3 w-32 rounded" />
      <!-- Loading text -->
      <span class="text-xs text-slate-500">{{ loadingText ?? t('platform.loading') }}</span>
    </div>
    
    <div v-else-if="error" class="flex items-center justify-center h-full border border-red-200 rounded-lg bg-red-50">
      <div class="flex flex-col items-center space-y-2">
        <AlertCircle class="w-4 h-4 text-red-500" />
        <span class="text-xs text-red-600 text-center px-2">{{ errorText ?? t('platform.moleculePreviewFailed') }}</span>
      </div>
    </div>
    
    <div 
      v-else-if="svgContent" 
      class="w-full h-full bg-transparent overflow-hidden"
      v-html="svgContent"
    />
    
    <div v-else class="flex items-center justify-center h-full border border-slate-200 rounded-lg bg-slate-50">
      <div class="flex flex-col items-center space-y-2">
        <Beaker class="w-4 h-4 text-slate-400" />
        <span class="text-xs text-slate-500 text-center px-2">{{ placeholder ?? t('platform.moleculePreviewWaiting') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, Beaker } from 'lucide-vue-next'
import { Skeleton } from '@/components/ui/skeleton'
import { renderMolecule } from '@/utils/moleculeRenderer'

interface Props {
  smiles?: string; width?: string; height?: string; smarts?: string
  showAtomIndex?: boolean; bondWidth?: number; maxFontSize?: number; highlightAtoms?: number[]; regenerateCoords?: boolean; removeHs?: boolean; rotation?: number
  highlightAtomColors?: Record<number, [number, number, number]>
  loadingText?: string; errorText?: string; placeholder?: string
}
const props = withDefaults(defineProps<Props>(), {
  smiles: '', width: 'auto', height: 'auto', smarts: '', showAtomIndex: false,
  bondWidth: 2, rotation: 0, removeHs: false, highlightAtoms: () => [], highlightAtomColors: () => ({}),
})
const { t } = useI18n()
const root = ref<HTMLElement>()
const visible = ref(false)
const svgContent = ref('')
let drawingInput = ''
const loading = ref(false), error = ref(false)
let observer: IntersectionObserver | undefined
let resizeObserver: ResizeObserver | undefined
const drawingSize = ref({ width: 250, height: 200 })
onMounted(() => {
  observer = new IntersectionObserver(([entry]) => { visible.value = entry.isIntersecting }, { rootMargin: '200px' })
  if (root.value) {
    observer.observe(root.value)
    resizeObserver = new ResizeObserver(([entry]) => {
      const width = Math.max(1, Math.round(entry.contentRect.width) || 250)
      const height = Math.max(1, Math.round(entry.contentRect.height) || 200)
      if (drawingSize.value.width !== width || drawingSize.value.height !== height) drawingSize.value = { width, height }
    })
    resizeObserver.observe(root.value)
  }
})
watch(() => [visible.value, props.smiles, props.smarts, drawingSize.value.width, drawingSize.value.height, props.showAtomIndex, props.bondWidth, props.maxFontSize, props.regenerateCoords, props.removeHs, props.rotation,
  JSON.stringify(props.highlightAtoms), JSON.stringify(props.highlightAtomColors)], async (_, __, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  error.value = false
  if (drawingInput !== props.smiles) { svgContent.value = ''; drawingInput = props.smiles }
  if (!props.smiles.trim()) { loading.value = false; return }
  loading.value = true
  if (!visible.value) return
  if (!/V[23]000|M\s+END/i.test(props.smiles) && props.smiles.split('.').length > 3) {
    svgContent.value = ''; error.value = true; loading.value = false; return
  }
  const work = renderMolecule({
    input: props.smiles, smarts: props.smarts, width: drawingSize.value.width, height: drawingSize.value.height,
    atoms: [...props.highlightAtoms].sort((a, b) => a - b), colors: props.highlightAtomColors,
    showAtomIndex: props.showAtomIndex, bondWidth: props.bondWidth,
    regenerateCoords: props.regenerateCoords,
    removeHs: props.removeHs,
    maxFontSize: props.maxFontSize,
    rotation: props.rotation,
  })
  onCleanup(() => { active = false; work.cancel() })
  try { const svg = await work.promise; if (active) svgContent.value = svg }
  catch { if (active) { svgContent.value = ''; error.value = true } }
  finally { if (active) loading.value = false }
}, { immediate: true })
onBeforeUnmount(() => { observer?.disconnect(); resizeObserver?.disconnect() })
</script>

<style scoped>
.molecule-viewer {
  @apply relative;
}

:deep(svg) {
  @apply w-full h-full block;
}
</style> 
