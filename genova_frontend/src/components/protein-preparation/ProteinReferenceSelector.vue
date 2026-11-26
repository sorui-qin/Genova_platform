<template>
  <div class="space-y-3">
    <div class="text-sm font-semibold text-slate-900">{{ $t('platform.referenceMethod') }}</div>
    <Select :model-value="mode" @update:model-value="$emit('update:mode', String($event))">
      <SelectTrigger><SelectValue :placeholder="$t('platform.referenceMethod')" /></SelectTrigger>
      <SelectContent>
        <SelectItem value="ligand">{{ $t('platform.referenceLigand') }}</SelectItem>
        <SelectItem value="residues">{{ $t('platform.residueSelection') }}</SelectItem>
        <SelectItem value="coordinates">{{ $t('platform.manualCoordinates') }}</SelectItem>
      </SelectContent>
    </Select>
    <Select
      v-if="mode === 'ligand' && ligands.length"
      :model-value="ligandKey"
      @update:model-value="$emit('update:ligandKey', String($event))"
    >
      <SelectTrigger><SelectValue :placeholder="$t('platform.selectLigand')" /></SelectTrigger>
      <SelectContent>
        <SelectItem v-for="ligand in ligands" :key="ligand.key" :value="ligand.key">
          {{ ligand.key === externalLigandKey ? externalLigandLabel : ligand.key }} · {{ ligand.heavy_atom_count }} {{ $t('platform.heavyAtoms') }}
        </SelectItem>
      </SelectContent>
    </Select>
    <p v-if="mode === 'ligand' && !ligands.length" class="text-xs text-amber-700">
      {{ $t('platform.noDetectedLigand') }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ProteinAnalysis } from '@/types/proteinContext'

defineProps<{
  mode: string
  ligandKey: string
  ligands: ProteinAnalysis['ligands']
  externalLigandKey?: string
  externalLigandLabel?: string
}>()
defineEmits<{
  'update:mode': [value: string]
  'update:ligandKey': [value: string]
}>()
</script>
