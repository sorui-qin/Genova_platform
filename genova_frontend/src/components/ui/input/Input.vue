<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'
import { useVModel } from '@vueuse/core'
import { toast } from '@/components/ui/toast/use-toast'
import { translate } from '@/i18n'

const props = defineProps<{
  defaultValue?: string | number
  modelValue?: string | number
  class?: HTMLAttributes['class']
}>()

const emits = defineEmits<{
  (e: 'update:modelValue', payload: string | number): void
}>()

const modelValue = useVModel(props, 'modelValue', emits, {
  passive: true,
  defaultValue: props.defaultValue,
})

const parseLimit = (value: string): number | undefined => {
  if (value === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

// While typing only the maximum is enforced: rounding and the minimum would rewrite a number that is still being
// typed (typing "-100" or "3.14" passes through "-1" and "3."). Both are applied once the field loses focus.
const clampNumberByInput = (input: HTMLInputElement, typing: boolean): string | undefined => {
  if (input.type !== 'number' || input.value === '') return undefined

  const current = Number(input.value)
  if (!Number.isFinite(current)) return undefined

  const min = parseLimit(input.min)
  const max = parseLimit(input.max)

  let next = input.step === '1' && !typing ? Math.trunc(current) : current
  if (min !== undefined && next < min && !typing) next = min
  if (max !== undefined && next > max) next = max

  return String(next)
}

// Set when a typed number had to be corrected; reported once the field loses focus.
let adjusted = false
// Whether the last typed text was not a number. Recorded per keystroke because on blur the framework's change
// handler writes the (empty) value back, which erases the typed text and resets validity.badInput.
let unreadable = false

const syncNumberValue = (event: Event) => {
  const input = event.target as HTMLInputElement | null
  if (!input) return
  const typing = event.type === 'input'
  if (typing) unreadable = input.validity.badInput

  const clamped = clampNumberByInput(input, typing)
  if (clamped === undefined) return

  // Compare numbers, not text: "3.0" or "1.50" are being typed and must not be rewritten to "3" / "1.5".
  if (Number(clamped) !== Number(input.value)) {
    input.value = clamped
    adjusted = true
  }
  if (clamped !== String(modelValue.value ?? '')) modelValue.value = clamped
}

const rangeText = (input: HTMLInputElement) => {
  const min = parseLimit(input.min), max = parseLimit(input.max)
  if (min !== undefined && max !== undefined) return translate('platform.numberInput.between', { min, max })
  if (min !== undefined) return translate('platform.numberInput.atLeast', { min })
  return max !== undefined ? translate('platform.numberInput.atMost', { max }) : ''
}

// A corrected or unreadable number is not changed silently: say what happened and which range is allowed.
const reportNumberValue = (event: Event) => {
  syncNumberValue(event)
  const input = event.target as HTMLInputElement | null
  if (!input || input.type !== 'number') return
  const range = rangeText(input)
  if (input.validity.badInput || unreadable) toast({ title: translate('platform.numberInput.invalid'), description: range ? translate('platform.numberInput.range', { range }) : undefined, variant: 'destructive' })
  else if (adjusted) toast({ title: translate('platform.numberInput.adjusted', { value: input.value }), description: range ? translate('platform.numberInput.range', { range }) : undefined })
  adjusted = unreadable = false
}
</script>

<template>
  <input
    v-model="modelValue"
    @input="syncNumberValue"
    @blur="reportNumberValue"
    :class="cn('flex h-9 w-full rounded-lg border border-input bg-card px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50', props.class)"
  >
</template>
