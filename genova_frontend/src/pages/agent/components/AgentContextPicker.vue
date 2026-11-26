<template>
  <Popover :open="open" @update:open="emit('update:open', $event)">
    <PopoverTrigger as-child>
      <Button type="button" variant="outline" size="sm" :disabled="disabled" :aria-expanded="open" class="h-10 min-w-0 max-w-full flex-1 basis-40 justify-start gap-2 bg-slate-50/50 px-3 text-slate-700 hover:bg-slate-100">
        <Layers3 class="text-slate-500" aria-hidden="true" />
        <span class="truncate">{{ selectedContext?.name || t('agent.session.chooseContext') }}</span>
        <ChevronsUpDown class="ml-auto h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="start" :aria-label="t('agent.session.chooseContext')" class="flex max-h-[var(--radix-popover-content-available-height)] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden p-0">
      <div class="flex shrink-0 items-center justify-between border-b px-3 py-2">
        <span class="text-sm font-medium">Protein Context</span>
        <PopoverClose as-child><Button type="button" variant="ghost" size="icon" class="h-7 w-7" :aria-label="t('agent.contextPicker.close')"><X class="h-4 w-4" aria-hidden="true" /></Button></PopoverClose>
      </div>
      <Command :model-value="modelValue" :display-value="() => ''" v-model:search-term="search" :filter-function="items => items" :reset-search-term-on-blur="false" class="min-h-0">
        <CommandInput maxlength="200" :aria-label="t('agent.contextPicker.search')" :placeholder="t('agent.contextPicker.search')" />
        <div v-if="loading" role="status" class="flex h-28 items-center justify-center gap-2 text-sm text-slate-500"><LoaderCircle class="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />{{ t('platform.loading') }}</div>
        <div v-else-if="loadError" class="space-y-2 p-4 text-center"><p role="alert" class="text-sm text-red-700">{{ loadError }}</p><Button type="button" size="sm" variant="outline" @click="load">{{ t('platform.retry') }}</Button></div>
        <p v-else-if="!contexts.length" role="status" class="p-6 text-center text-sm text-slate-500">{{ t('agent.contextPicker.empty') }}</p>
        <CommandList v-else class="max-h-60 p-1">
          <CommandItem v-for="item in contexts" :key="item.id" :value="item.id" :disabled="!item.ready || disabled" class="gap-2 px-2 py-2.5" @select.prevent="selectContext(item)">
            <Check class="h-4 w-4 shrink-0" :class="item.id === modelValue ? 'opacity-100' : 'opacity-0'" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate" :title="item.name">{{ item.name }}</span>
            <span v-if="!item.ready" class="shrink-0 text-xs text-slate-500">{{ t('platform.structureNotReady') }}</span>
          </CommandItem>
        </CommandList>
      </Command>
      <div v-if="page || hasMore" class="flex shrink-0 items-center justify-between gap-2 border-t p-2">
        <Button type="button" size="sm" variant="outline" :disabled="loading || page === 0" @click="changePage(page - 1)">{{ t('platform.previous') }}</Button>
        <span class="text-xs text-slate-500">{{ page + 1 }}</span>
        <Button type="button" size="sm" variant="outline" :disabled="loading || !hasMore" @click="changePage(page + 1)">{{ t('platform.next') }}</Button>
      </div>
    </PopoverContent>
  </Popover>
</template>

<script setup lang="ts">
import { displayErrorMessage } from '@/utils/requestError'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronsUpDown, Layers3, LoaderCircle, X } from 'lucide-vue-next'
import { PopoverClose } from 'radix-vue'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Command, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Button } from '@/components/ui/button'
import { listProteinContexts } from '@/api/proteinContext'
import type { ProteinContextListItem } from '@/types/proteinContext'

const props = defineProps<{ open: boolean; modelValue: string; selectedContext?: ProteinContextListItem; disabled: boolean }>()
const emit = defineEmits<{ 'update:open': [open: boolean]; select: [id: string, context: ProteinContextListItem] }>()
const { t } = useI18n()
const contexts = ref<ProteinContextListItem[]>([]), search = ref(''), page = ref(0), hasMore = ref(false)
const loading = ref(false), loadError = ref('')
let controller: AbortController | undefined, revision = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined

function selectContext(context: ProteinContextListItem) {
  emit('select', context.id, context)
  emit('update:open', false)
}
async function load() {
  const current = ++revision
  controller?.abort(); controller = new AbortController()
  loading.value = true; loadError.value = ''
  try {
    const { data } = await listProteinContexts({ limit: 21, offset: page.value * 20, search: search.value.trim() || undefined, signal: controller.signal })
    if (current !== revision) return
    hasMore.value = data.length > 20
    contexts.value = data.slice(0, 20)
  } catch (error: any) {
    if (current !== revision) return
    loadError.value = displayErrorMessage(error, t('platform.failedToLoadProteinContexts'))
  } finally {
    if (current === revision) loading.value = false
  }
}
function changePage(value: number) { page.value = value; void load() }
watch(search, () => {
  if (!props.open) return
  revision++; controller?.abort(); clearTimeout(searchTimer)
  loading.value = true; page.value = 0
  searchTimer = setTimeout(load, 250)
})
watch(() => props.open, open => {
  if (open) void load()
  else { revision++; controller?.abort(); clearTimeout(searchTimer); search.value = ''; page.value = 0 }
}, { immediate: true })
watch(() => props.disabled, disabled => { if (disabled) emit('update:open', false) })
onBeforeUnmount(() => { revision++; controller?.abort(); clearTimeout(searchTimer) })
</script>
