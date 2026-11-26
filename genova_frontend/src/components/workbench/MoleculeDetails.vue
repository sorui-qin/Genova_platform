<template>
  <div v-if="row" class="space-y-4">
    <MoleculeViewer :smiles="row.smiles" width="260px" height="180px" />
    <dl class="space-y-4 text-sm"><div><dt class="mb-2 text-xs text-muted-foreground">SMILES</dt><dd class="break-all rounded-lg bg-secondary p-3 font-mono text-xs">{{ row.smiles }}</dd></div><div><dt class="text-xs text-muted-foreground">ID</dt><dd class="mt-1 break-all font-mono text-xs">{{ row.id || row.molecule_id }}</dd></div><slot /></dl>
    <Button v-if="has3d" variant="outline" class="w-full" @click="$emit('view3d')">{{ $t('platform.3dView') }}</Button>
  </div>
</template>
<script setup lang="ts">
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import { Button } from '@/components/ui/button'
defineProps<{ row: { id?: string; molecule_id?: string; smiles: string } | null; has3d?: boolean }>()
defineEmits<{ view3d: [] }>()
</script>
