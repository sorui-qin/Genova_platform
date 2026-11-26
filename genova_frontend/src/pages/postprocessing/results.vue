<template>
  <AppFrame><div ref="page" class="module-workbench tarpass-results-page flex flex-col" :style="{ '--tarpass-results-viewport': `${viewportHeight}px`, '--tarpass-results-panel-height': `${viewportHeight - navigationHeight}px` }">
    <PageHeader :title="$t('platform.postprocessingResults')" :help="{ path: '/help', query: { article: 'exports' } }" :help-label="$t('platform.operationGuide')" />
    <div ref="navigation" class="workbench-toolbar text-sm text-primary"><router-link to="/results">{{ $t('platform.allResults') }}</router-link><router-link v-if="sourceId" :to="{ path: '/postprocessing', query: { source_job_id: sourceId, protein_context_id: proteinContextId || undefined } }">{{ $t('platform.newEvaluation') }}</router-link><router-link v-if="sourceId && sourcePath" :to="{ path: sourcePath, query: { job_id: sourceId } }">{{ $t('platform.sourceGeneration') }}</router-link></div>
    <p v-if="error" role="alert" class="text-red-700">{{ error }}</p>
    <TarPassPanel v-if="sourceId" class="tarpass-page-workspace" :key="jobId" :source-job-id="sourceId" :initial-job-id="jobId" :source-job="sourceJob" mode="results" />
  </div></AppFrame>
</template>
<script setup lang="ts">
import '@/assets/module-workbench.css'
import PageHeader from '@/components/workbench/PageHeader.vue'
import { translate } from '@/i18n'

import { computed, ref, watch } from 'vue'
import { useElementSize } from '@vueuse/core'
import { useRoute } from 'vue-router'
import AppFrame from '@/components/Layout/appFrame.vue'
import TarPassPanel from '@/components/molecule/TarPassPanel.vue'
import { getBackendJob, type BackendJobOut } from '@/api/genovaBackend'
import { displayErrorMessage } from '@/utils/requestError'
const route = useRoute()
const page = ref<HTMLDivElement | null>(null)
const navigation = ref<HTMLDivElement | null>(null)
const { height: viewportHeight } = useElementSize(() => page.value?.parentElement)
const { height: navigationHeight } = useElementSize(navigation, undefined, { box: 'border-box' })
const jobId = computed(() => String(route.query.job_id || ''))
const sourceId = ref('')
const proteinContextId = ref('')
const sourcePath = ref('')
const sourceJob = ref<BackendJobOut | null>(null)
const error = ref('')
watch(jobId, async (id, _previous, onCleanup) => {
  let stale = false
  onCleanup(() => { stale = true })
  sourceId.value = ''; proteinContextId.value = ''; sourcePath.value = ''; sourceJob.value = null; error.value = ''
  try {
    const job = (await getBackendJob(id, { summary: true })).data
    if (stale) return
    sourceId.value = job.params?.postprocessing?.source_job_id || ''
    proteinContextId.value = job.params?.postprocessing?.protein_context_id || job.params?.protein_context_id || ''
    if (!sourceId.value) throw new Error(translate('platform.missingSourceGenerationJob'))
    const source = (await getBackendJob(sourceId.value, { summary: true })).data
    if (stale) return
    sourceJob.value = source
    sourcePath.value = source.job_type === 'property_optimization' ? '/molopt/results' : '/molgen/results'
  } catch (exc: any) { if (!stale) error.value = displayErrorMessage(exc, translate('platform.unableToLoadJob')) }
}, { immediate: true })
</script>
<style scoped>
.tarpass-results-page { height: auto; min-height: 100%; overflow: visible; }
.tarpass-page-workspace { height: auto; overflow: visible; align-items: start; }
.tarpass-page-workspace :deep(.workspace-main) { overflow: visible; }
.tarpass-page-workspace :deep(.workspace-auxiliary) { position: sticky; top: 0; height: var(--tarpass-results-panel-height); align-self: start; }
.tarpass-page-workspace :deep(.tarpass-results) { height: auto; overflow: visible; }
.tarpass-page-workspace :deep(.tarpass-result-content) { flex: none; }
.tarpass-page-workspace :deep(.tarpass-result-content > .workbench-table-scroll) { flex: none; min-height: 0; overflow-x: auto; }
.tarpass-page-workspace :deep(.tarpass-options) { max-height: none; overflow: visible; }
.tarpass-page-workspace.panel-drawer :deep(.workspace-auxiliary) { position: fixed; top: calc(100dvh - var(--tarpass-results-viewport)); height: var(--tarpass-results-viewport); }
.tarpass-page-workspace.panel-drawer :deep(.workspace-scrim) { position: fixed; top: calc(100dvh - var(--tarpass-results-viewport)); }
</style>
<route lang="yaml">
meta:
  layout: blank
</route>
