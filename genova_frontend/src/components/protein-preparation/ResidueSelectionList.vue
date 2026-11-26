<template>
  <details class="rounded-md border border-slate-200 p-3">
    <summary class="cursor-pointer text-xs font-medium text-slate-700">
      {{ $t('platform.residueSelection') }}
      <span class="ml-2 font-normal text-slate-500">{{ $t('platform.selectedResidues') }} ({{ residues.length }})</span>
    </summary>
    <div class="mt-3 space-y-2">
      <p class="text-xs text-slate-500">{{ hint ?? $t('platform.residueSelectionHint') }}</p>
      <Input v-model="search" :placeholder="$t('platform.searchResidues')" :aria-label="$t('platform.searchResidues')" />
      <div class="max-h-48 overflow-y-auto rounded-md border border-slate-200">
        <label
          v-for="residue in filteredResidues"
          :key="residueKey(residue)"
          class="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs hover:bg-slate-50"
          :class="selectedKeys.has(residueKey(residue)) ? 'bg-blue-50 text-blue-800' : 'text-slate-700'"
        >
          <input type="checkbox" :checked="selectedKeys.has(residueKey(residue))" @change="$emit('toggle', residue)">
          {{ residue.chain_id || $t('platform.blank') }}:{{ residue.residue_name }}{{ residue.residue_number }}{{ residue.insertion_code }}
        </label>
        <p v-if="!filteredResidues.length" class="p-3 text-xs text-slate-500">{{ $t('platform.noMatchingResidues') }}</p>
      </div>
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs font-medium text-slate-700">{{ $t('platform.selectedResidues') }} ({{ residues.length }})</span>
        <Button type="button" size="sm" variant="ghost" :disabled="!residues.length" @click="$emit('clear')">{{ $t('platform.clearResidues') }}</Button>
      </div>
      <div v-if="residues.length" class="flex max-h-32 flex-wrap gap-2 overflow-y-auto">
        <button
          v-for="residue in residues"
          :key="residueKey(residue)"
          type="button"
          class="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-800"
          :aria-label="$t('platform.removeResidue', { residue: `${residue.chain_id}:${residue.residue_name}${residue.residue_number}${residue.insertion_code}` })"
          @click="$emit('toggle', residue)"
        >
          {{ residue.chain_id || $t('platform.blank') }}:{{ residue.residue_name }}{{ residue.residue_number }}{{ residue.insertion_code }} ×
        </button>
      </div>
    </div>
  </details>
  <p v-if="error" role="alert" class="text-xs text-rose-700">{{ error }}</p>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { ResidueRef } from '@/types/proteinContext'

const props = defineProps<{ residues: ResidueRef[]; availableResidues: ResidueRef[]; error?: string; hint?: string }>()
defineEmits<{ toggle: [residue: ResidueRef]; clear: [] }>()
const search = ref('')
const residueKey = (residue: ResidueRef) => `${residue.chain_id}:${residue.residue_number}:${residue.insertion_code}:${residue.residue_name}`
const selectedKeys = computed(() => new Set(props.residues.map(residueKey)))
const filteredResidues = computed(() => {
  const query = search.value.trim().toUpperCase()
  return props.availableResidues.filter(residue =>
    `${residue.residue_name}${residue.residue_number}${residue.insertion_code}`.toUpperCase().includes(query),
  )
})
</script>
