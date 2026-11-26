<template>
  <div class="range-slider-container" ref="containerRef">
    <div class="range-slider-track" @mousedown="handleTrackClick">
      <!-- Track background -->
      <div class="range-track-bg"></div>
      
      <!-- Active range -->
      <div 
        class="range-track-active"
        :style="{
          left: `${leftPercent}%`,
          width: `${rightPercent - leftPercent}%`
        }"
      ></div>
      
      <!-- Left thumb -->
      <div 
        class="range-thumb range-thumb-left"
        :style="{ left: `${leftPercent}%` }"
        @mousedown="(e) => handleThumbMouseDown(e, 'left')"
        @touchstart="(e) => handleThumbTouchStart(e, 'left')"
      >
        <div class="range-thumb-inner"></div>
      </div>
      
      <!-- Right thumb -->
      <div 
        class="range-thumb range-thumb-right"
        :style="{ left: `${rightPercent}%` }"
        @mousedown="(e) => handleThumbMouseDown(e, 'right')"
        @touchstart="(e) => handleThumbTouchStart(e, 'right')"
      >
        <div class="range-thumb-inner"></div>
      </div>
    </div>
    
    <!-- Value labels (optional) -->
    <div v-if="showLabels" class="range-labels">
      <span class="range-label-left">{{ formatValue(leftValue) }}</span>
      <span class="range-label-right">{{ formatValue(rightValue) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'

interface Props {
  modelValue: [number, number]
  min?: number
  max?: number
  step?: number
  disabled?: boolean
  showLabels?: boolean
  formatValue?: (value: number) => string
}

const props = withDefaults(defineProps<Props>(), {
  min: 0,
  max: 100,
  step: 1,
  disabled: false,
  showLabels: false,
  formatValue: (value: number) => value.toString()
})

const emit = defineEmits<{
  'update:modelValue': [value: [number, number]]
  'change': [value: [number, number]]
}>()

const containerRef = ref<HTMLElement>()
const isDragging = ref<'left' | 'right' | null>(null)
const dragStartX = ref(0)
const dragStartValue = ref(0)

// Computed values
const leftValue = computed(() => props.modelValue[0])
const rightValue = computed(() => props.modelValue[1])

const leftPercent = computed(() => {
  return ((leftValue.value - props.min) / (props.max - props.min)) * 100
})

const rightPercent = computed(() => {
  return ((rightValue.value - props.min) / (props.max - props.min)) * 100
})

// Helper functions
const clamp = (value: number, min: number, max: number) => {
  return Math.max(min, Math.min(max, value))
}

const snapToStep = (value: number) => {
  return Math.round(value / props.step) * props.step
}

const getValueFromPosition = (clientX: number) => {
  if (!containerRef.value) return props.min
  
  const rect = containerRef.value.getBoundingClientRect()
  const percent = (clientX - rect.left) / rect.width
  const value = props.min + percent * (props.max - props.min)
  
  return clamp(snapToStep(value), props.min, props.max)
}

// Event handlers
const handleTrackClick = (e: MouseEvent) => {
  if (props.disabled || isDragging.value) return
  
  const clickValue = getValueFromPosition(e.clientX)
  const leftDistance = Math.abs(clickValue - leftValue.value)
  const rightDistance = Math.abs(clickValue - rightValue.value)
  
  // Move the closer thumb
  if (leftDistance < rightDistance) {
    updateValue('left', clickValue)
  } else {
    updateValue('right', clickValue)
  }
}

const handleThumbMouseDown = (e: MouseEvent, thumb: 'left' | 'right') => {
  if (props.disabled) return
  
  e.preventDefault()
  e.stopPropagation()
  
  isDragging.value = thumb
  dragStartX.value = e.clientX
  dragStartValue.value = thumb === 'left' ? leftValue.value : rightValue.value
  
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', handleMouseUp)
}

const handleThumbTouchStart = (e: TouchEvent, thumb: 'left' | 'right') => {
  if (props.disabled) return
  
  e.preventDefault()
  
  const touch = e.touches[0]
  isDragging.value = thumb
  dragStartX.value = touch.clientX
  dragStartValue.value = thumb === 'left' ? leftValue.value : rightValue.value
  
  document.addEventListener('touchmove', handleTouchMove, { passive: false })
  document.addEventListener('touchend', handleTouchEnd)
}

const handleMouseMove = (e: MouseEvent) => {
  if (!isDragging.value) return
  
  const newValue = getValueFromPosition(e.clientX)
  updateValue(isDragging.value, newValue)
}

const handleTouchMove = (e: TouchEvent) => {
  if (!isDragging.value) return
  
  e.preventDefault()
  const touch = e.touches[0]
  const newValue = getValueFromPosition(touch.clientX)
  updateValue(isDragging.value, newValue)
}

const handleMouseUp = () => {
  if (isDragging.value) {
    emit('change', props.modelValue)
    isDragging.value = null
  }
  
  document.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('mouseup', handleMouseUp)
}

const handleTouchEnd = () => {
  if (isDragging.value) {
    emit('change', props.modelValue)
    isDragging.value = null
  }
  
  document.removeEventListener('touchmove', handleTouchMove)
  document.removeEventListener('touchend', handleTouchEnd)
}

const updateValue = (thumb: 'left' | 'right', newValue: number) => {
  const currentLeft = leftValue.value
  const currentRight = rightValue.value
  
  if (thumb === 'left') {
    // Ensure left thumb doesn't go past right thumb
    const clampedValue = clamp(newValue, props.min, currentRight)
    emit('update:modelValue', [clampedValue, currentRight])
  } else {
    // Ensure right thumb doesn't go past left thumb
    const clampedValue = clamp(newValue, currentLeft, props.max)
    emit('update:modelValue', [currentLeft, clampedValue])
  }
}

// Cleanup on unmount
onUnmounted(() => {
  document.removeEventListener('mousemove', handleMouseMove)
  document.removeEventListener('mouseup', handleMouseUp)
  document.removeEventListener('touchmove', handleTouchMove)
  document.removeEventListener('touchend', handleTouchEnd)
})
</script>

<style scoped>
.range-slider-container {
  @apply relative w-full py-2;
}

.range-slider-track {
  @apply relative h-2 cursor-pointer;
}

.range-track-bg {
  @apply absolute inset-0 bg-gray-200 rounded-full;
}

.range-track-active {
  @apply absolute top-0 h-full bg-violet-500 rounded-full;
}

.range-thumb {
  @apply absolute top-1/2 w-5 h-5 -translate-y-1/2 -translate-x-1/2 cursor-grab;
}

.range-thumb:active {
  @apply cursor-grabbing;
}

.range-thumb.range-thumb-left {
  @apply z-10;
}

.range-thumb.range-thumb-right {
  @apply z-10;
}

.range-thumb-inner {
  @apply w-full h-full bg-white border-2 border-violet-500 rounded-full shadow-sm;
  transition: all 0.15s ease;
}

.range-thumb:hover .range-thumb-inner {
  @apply scale-110 shadow-md;
}

.range-thumb:active .range-thumb-inner {
  @apply scale-125 shadow-lg border-violet-600;
}

.range-labels {
  @apply flex justify-between mt-2 text-xs text-gray-500;
}

.range-label-left,
.range-label-right {
  @apply px-1;
}

/* Disabled state */
.range-slider-container:has(.range-slider-track[disabled]) {
  @apply opacity-50 pointer-events-none;
}
</style>
