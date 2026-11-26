<template>
  <div class="task-summary" role="status">
    <span v-if="task.draft" class="status-badge status-pending">{{ $t('platform.unsubmittedDraft') }}</span>
    <strong class="max-w-[30rem] truncate font-semibold" :title="task.name">{{ task.name }}</strong>
    <span v-if="task.stage" class="text-muted-foreground">· {{ task.stage }}</span>
    <span v-if="task.context" class="truncate text-muted-foreground" :title="task.context">· {{ task.context }}</span>
    <span v-if="task.version != null" class="whitespace-nowrap text-muted-foreground">· {{ $t('platform.summaryVersion', {version: task.version}) }}</span>
    <Button v-if="task.details" variant="ghost" size="sm" class="ml-auto shrink-0 text-primary" @click="task.details()">{{ $t('platform.viewDetails') }}<ChevronRight class="h-4 w-4" aria-hidden="true" /></Button>
  </div>
</template>
<script setup lang="ts">
import { ChevronRight } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import type { WorkspaceTask } from '@/composables/useWorkspace'
defineProps<{ task: WorkspaceTask }>()
</script>
<style scoped>
.task-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-height: 48px; padding: 8px 24px; font-size: 12px; background: var(--surface); border-bottom: 1px solid var(--border-default); }
</style>
