<template>
  <AppFrame>
    <div class="flex h-full flex-col overflow-hidden bg-white">
      <PageHeader :title="$t('platform.proteinPreparation')" :help="{ path: '/help', query: { article: 'protein-preparation' } }" :help-label="$t('platform.operationGuide')" />
      <div class="min-h-0 flex-1">
        <ProteinPreparation />
      </div>
    </div>
  </AppFrame>
</template>

<script setup lang="ts">
import PageHeader from '@/components/workbench/PageHeader.vue'
import AppFrame from '@/components/Layout/appFrame.vue'
import ProteinPreparation from '@/components/protein-preparation/ProteinPreparation.vue'
</script>

<route lang="yaml">
meta:
  layout: blank
</route>
