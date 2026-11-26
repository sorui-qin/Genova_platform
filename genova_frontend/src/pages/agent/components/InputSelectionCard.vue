<template>
  <section class="overflow-hidden rounded-xl border border-slate-200 bg-white" data-testid="input-selection-card">
    <header class="flex items-center gap-2 border-b border-slate-100 px-4 py-3"><Files class="h-4 w-4 text-blue-600" aria-hidden="true" /><h3 class="text-sm font-semibold text-slate-800">{{ t(files.length ? 'agent.inputSelection.confirm' : 'agent.inputSelection.empty') }}</h3><ResourceSort v-if="files.length > 1" v-model="sortOrder" default-order class="ml-auto" /></header>
    <ul v-if="files.length" class="max-h-72 divide-y divide-slate-100 overflow-y-auto px-4">
      <li v-for="{ dataset, file } in files" :key="file.id" class="flex items-center gap-3 py-3">
        <FileText class="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
        <div class="min-w-0 flex-1"><p class="truncate text-sm font-medium text-slate-800" :title="file.name">{{ file.name }}</p><p class="truncate text-xs text-slate-500" :title="dataset.name">{{ dataset.name }} · {{ file.name.split('.').pop()?.toUpperCase() }}</p></div>
        <Button type="button" size="sm" :disabled="disabled" :aria-label="t('agent.inputSelection.useFile', { name: file.name, dataset: dataset.name })" @click="emit('select', dataset.id, file.id)">{{ t('agent.inputSelection.use') }}</Button>
      </li>
    </ul>
    <footer class="flex flex-wrap items-center gap-2 bg-slate-50 px-3 py-2" :class="{ 'border-t border-slate-100': files.length }">
      <Button type="button" size="sm" variant="ghost" :disabled="disabled" class="text-slate-600" @click="emit('upload')"><Upload class="h-4 w-4" aria-hidden="true" />{{ t('agent.session.uploadLocalFile') }}</Button>
      <Button type="button" size="sm" variant="ghost" :disabled="disabled" class="text-slate-600" @click="emit('choose')"><FolderOpen class="h-4 w-4" aria-hidden="true" />{{ t('agent.inputSelection.choose') }}</Button>
    </footer>
  </section>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import ResourceSort from '@/components/common/ResourceSort.vue'
import { useI18n } from 'vue-i18n'
import { Files, FileText, FolderOpen, Upload } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import type { AgentSessionState } from '@/api/genovaBackend'
const props = defineProps<{ selection: NonNullable<AgentSessionState['input_selection']>; disabled: boolean }>()
const emit = defineEmits<{ select: [datasetId: string, fileId: string]; upload: []; choose: [] }>()
const { t } = useI18n()
const sortOrder = ref<'time' | 'name'>('time')
const files = computed(() => props.selection.candidates.flatMap(dataset => [...dataset.files]
  .sort((a, b) => Number(b.role === 'source_structure') - Number(a.role === 'source_structure'))
  .map(file => ({ dataset, file })))
  .sort((a, b) => sortOrder.value === 'name' ? a.file.name.localeCompare(b.file.name, undefined, { numeric: true, sensitivity: 'base' }) : 0))
</script>
