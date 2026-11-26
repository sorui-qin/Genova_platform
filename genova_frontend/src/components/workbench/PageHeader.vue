<template>
  <Teleport :to="header.target.value || 'body'" :disabled="!header.target.value">
  <div class="page-header">
    <div class="page-header-copy">
      <h1>{{ title }}</h1>
      <RouterLink v-if="help" :to="help" class="inline-flex items-center gap-1 text-xs text-primary hover:underline"><CircleHelp class="h-4 w-4" aria-hidden="true" />{{ helpLabel || $t('platform.modelHelp') }}</RouterLink>
      <div v-if="$slots.breadcrumb" class="page-header-breadcrumb text-muted-foreground"><slot name="breadcrumb" /></div>
    </div>
    <div v-if="$slots.default" class="flex max-w-full flex-wrap items-center gap-2"><slot /></div>
  </div>
  </Teleport>
</template>
<script setup lang="ts">
import { CircleHelp } from 'lucide-vue-next'
import { inject, onBeforeUnmount, onMounted } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import { workspaceHeaderKey } from '@/composables/useWorkspace'
defineProps<{ title: string; help?: RouteLocationRaw; helpLabel?: string }>()
const header = inject(workspaceHeaderKey)!
onMounted(() => { header.active.value = true })
onBeforeUnmount(() => { header.active.value = false })
</script>
<style scoped>
.page-header { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; }
.page-header-copy { display: flex; flex: 1 1 auto; min-width: 0; flex-wrap: wrap; align-items: center; gap: 4px 12px; }
.page-header-breadcrumb { flex: 1 1 240px; min-width: 0; font-size: 12px; line-height: 18px; }
h1 { max-width: 100%; font-size: 20px; font-weight: 600; line-height: 28px; overflow-wrap: break-word; text-wrap: balance; }
</style>
