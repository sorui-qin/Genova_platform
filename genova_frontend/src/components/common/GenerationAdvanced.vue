<template>
  <TooltipProvider>
  <details ref="details" :open="open" @toggle="open = ($event.target as HTMLDetailsElement).open" class="rounded-lg border border-slate-200 p-3">
    <summary class="cursor-pointer text-sm font-semibold text-slate-700">{{ $t('platform.generationAdvanced') }}</summary>
    <div class="generation-fields mt-3 grid gap-3">
      <label v-for="field in fields" :key="field.key" :for="`${engine}-${field.key}`" class="block text-sm text-slate-700">
        {{ $t('platform.generation_' + field.key) }}
        <Tooltip v-if="['num_clouds', 'decodes_per_cloud'].includes(field.key)" :delay-duration="100">
          <TooltipTrigger as-child><button type="button" class="ml-1 inline-flex align-middle text-slate-500" :aria-label="$t('platform.generationSamplingWarning')"><CircleHelp class="h-4 w-4" /></button></TooltipTrigger>
          <TooltipContent class="max-w-64">{{ $t('platform.generationSamplingWarning') }}</TooltipContent>
        </Tooltip>
        <input :id="`${engine}-${field.key}`" v-model.number="settings[field.key]" class="mt-2 h-9 w-full rounded-md border border-input bg-background px-3 py-2 text-sm read-only:bg-slate-50 read-only:text-slate-500 disabled:bg-slate-50 disabled:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" type="number" :min="field.min" :max="field.max" :step="field.step" :readonly="field.key.endsWith('_threshold')" :disabled="(field.key === 'seed' && platformSeeds) || (planning && engine === 'ecloudgen' && ['num_clouds', 'decodes_per_cloud'].includes(field.key))" :required="field.key !== 'num_clouds'" :placeholder="field.key === 'num_clouds' && cloudEstimate ? String(cloudEstimate) : undefined">
        <span v-if="field.key !== 'seed' || !platformSeeds" class="mt-1 block text-xs leading-relaxed text-slate-500">{{ $t('platform.generationHint_' + field.key + (field.key === 'seed' && engine === 'ecloudgen' ? '_ecloudgen' : '')) }}</span>
        <span v-if="field.key === 'num_clouds'" class="mt-1 block text-xs text-slate-500">{{ $t('platform.generationAutomaticClouds') }}</span>
      </label>
    </div>
    <p v-if="engine === 'ecloudgen' && (settings.noise !== 0.1 || settings.inv_temp !== 2)" class="mt-3 text-xs text-amber-700">{{ $t('platform.generationCalibrationHint') }}</p>
  </details>
  </TooltipProvider>
</template>

<script setup lang="ts">
import { useWorkspaceState } from '@/composables/useWorkspace'
import { useRoute } from 'vue-router'
import { computed, ref } from 'vue'
import { CircleHelp } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

const props = defineProps<{ engine: 'surfgen' | 'delete' | 'ecloudgen'; planning?: boolean; platformSeeds?: boolean; cloudEstimate?: number }>()
const route = useRoute()
const { open } = useWorkspaceState('generation-advanced', () => `${route.path}:${props.engine}`, { open: false })
const settings = defineModel<Record<string, number | string>>({ required: true })
const details = ref<HTMLDetailsElement | null>(null)
const fields = computed(() => [
  ...(props.engine === 'ecloudgen'
    ? [
        { key: 'noise', min: 0, max: undefined, step: 'any' },
        { key: 'inv_temp', min: Number.MIN_VALUE, max: undefined, step: 'any' },
        { key: 'num_clouds', min: 4, max: 256, step: '4' },
        { key: 'decodes_per_cloud', min: 1, max: 1024, step: '1' },
      ]
    : [
        { key: 'beam_size', min: 1, max: 5000, step: '1' },
        { key: 'max_steps', min: 1, max: 500, step: '1' },
        { key: 'element_threshold', min: Number.MIN_VALUE, max: 1, step: 'any' },
        { key: 'bond_threshold', min: Number.MIN_VALUE, max: 1, step: 'any' },
      ]),
  { key: 'seed', min: 0, max: 4294967295, step: '1' },
])

function validate() {
  for (const input of details.value?.querySelectorAll('input') || []) {
    if (!input.checkValidity()) {
      details.value!.open = true
      input.reportValidity()
      return false
    }
  }
  return true
}
defineExpose({ validate })
</script>

<style scoped>
.generation-fields { grid-template-columns: repeat(auto-fit, minmax(min(100%, 210px), 1fr)); align-items: start; }
.generation-fields > label { min-width: 0; line-height: 20px; }
</style>
