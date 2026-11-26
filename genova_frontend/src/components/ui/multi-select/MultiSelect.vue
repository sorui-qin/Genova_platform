<template>
  <Popover>
    <PopoverTrigger asChild>
      <Button variant="outline" class="w-full justify-start min-h-9 h-auto py-1">
        <div class="flex flex-wrap gap-1 items-center">
          <template v-if="selectedItems.length">
            <Badge
              v-for="item in selectedItems"
              :key="item.value"
              variant="secondary"
              class="flex items-center gap-1 px-1.5 py-0.5"
            >
              <span class="text-xs">{{ item.label }}</span>
              <button
                class="inline-flex items-center justify-center text-slate-500 hover:text-slate-700"
                @click.stop="remove(item.value)"
                aria-label="remove"
              >
                <X class="w-3 h-3" />
              </button>
            </Badge>
          </template>
          <span v-else class="text-muted-foreground text-xs">{{ placeholder }}</span>
        </div>
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-[320px] p-0">
      <Command>
        <CommandInput :placeholder="searchPlaceholder" v-model="query" />
        <CommandEmpty>{{ emptyText }}</CommandEmpty>
        <CommandList>
          <template v-for="group in filteredGroups" :key="group.label">
            <CommandGroup :heading="group.label">
              <CommandItem
                v-for="opt in group.options"
                :key="opt.value"
                :value="opt.value"
                @select="toggle(opt.value)"
                class="flex items-center gap-2"
              >
                <Checkbox :checked="modelValueSet.has(opt.value)" class="pointer-events-none" />
                <span>{{ opt.label }}</span>
              </CommandItem>
            </CommandGroup>
          </template>
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'

type Option = { label: string; value: string }
type Group = { label: string; options: Option[] }

const props = defineProps<{
  modelValue: string[]
  groups: Group[]
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  maxSelected?: number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const placeholder = computed(() => props.placeholder ?? 'Select...')
const searchPlaceholder = computed(() => props.searchPlaceholder ?? 'Search...')
const emptyText = computed(() => props.emptyText ?? 'No results')

const modelValueSet = computed(() => new Set(props.modelValue ?? []))

const flatOptions = computed<Option[]>(() => props.groups.flatMap(g => g.options))
const valueToLabel = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const opt of flatOptions.value) map[opt.value] = opt.label
  return map
})

const selectedItems = computed<Option[]>(() => (props.modelValue ?? []).map(v => ({ value: v, label: valueToLabel.value[v] ?? v })))

const query = ref('')
const filteredGroups = computed<Group[]>(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.groups
  return props.groups
    .map(g => ({
      label: g.label,
      options: g.options.filter(o => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
    }))
    .filter(g => g.options.length > 0)
})

const toggle = (value: string) => {
  const set = new Set(props.modelValue ?? [])
  if (set.has(value)) set.delete(value)
  else if (!props.maxSelected || set.size < props.maxSelected) set.add(value)
  emit('update:modelValue', Array.from(set))
}

const remove = (value: string) => {
  const set = new Set(props.modelValue ?? [])
  if (set.delete(value)) emit('update:modelValue', Array.from(set))
}
</script>

<style scoped></style>

