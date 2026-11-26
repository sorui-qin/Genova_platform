<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuery } from '@tanstack/vue-query'
import { CircleHelp } from 'lucide-vue-next'
import { getHelpCatalog } from '@/api/help'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

const props = defineProps<{ metric: string; label: string }>()
const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const { data, isError } = useQuery({ queryKey: ['help-catalog'], queryFn: async () => (await getHelpCatalog()).data, staleTime: Infinity })
const text = computed(() => data.value?.entries.find(entry => entry.id === props.metric.split('.').pop() || entry.keys.includes(props.metric))?.translations[zh.value ? 'zh-CN' : 'en-US'])
</script>

<template>
  <TooltipProvider :delay-duration="150">
    <Tooltip>
      <TooltipTrigger as-child><button type="button" class="shrink-0 rounded p-1 text-blue-700" :aria-label="`${label} · ${zh ? '指标说明' : 'Metric help'}`"><CircleHelp class="h-4 w-4" /></button></TooltipTrigger>
      <TooltipContent class="max-h-[70vh] w-80 max-w-[calc(100vw-2rem)] space-y-2 overflow-auto p-4 text-xs leading-5">
        <h3 class="text-sm font-semibold">{{ label }}</h3>
        <template v-if="text"><p>{{ text.summary }}</p><p v-if="text.details">{{ text.details }}</p><p v-if="text.guidance">{{ text.guidance }}</p><p v-if="text.range">{{ zh ? '范围：' : 'Range: ' }}{{ text.range }}</p></template>
        <p v-else>{{ isError ? (zh ? '说明暂时无法加载。' : 'Help could not be loaded.') : (zh ? '加载说明…' : 'Loading help…') }}</p>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
