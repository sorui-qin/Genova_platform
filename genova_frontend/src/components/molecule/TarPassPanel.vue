<template>
  <WorkspaceLayout v-model:open="detailOpen" :title="auxiliaryTab === 'assistant' ? L('助手', 'Assistant') : $t('platform.resultDetails')" :class="mode === 'submit' ? 'submit-workspace' : 'workbench-results'" :resizable="mode === 'results'" :initial-left="70">
  <section class="tarpass-panel min-w-0 text-sm" :class="mode === 'submit' ? 'submit-panel space-y-4' : 'tarpass-results'">
    <p v-if="error" role="alert" class="whitespace-pre-wrap text-red-700">{{ error }}</p>
    <p v-if="restoreJob" role="status" class="text-blue-700">{{ $t(restoring ? 'platform.loading' : restoreFailed ? 'platform.restoreTaskUnavailable' : 'platform.restoredTaskHint') }}</p>
    <p v-if="mode === 'submit' && !options && !error" role="status" class="text-slate-500">{{ $t('platform.loading') }}</p>
    <div v-if="options && mode === 'submit'" class="workbench-form" :inert="restoring">
      <section class="input-section space-y-3">
        <h2>{{ $t('platform.ppEvaluationContent') }}</h2>
        <p v-if="!options.reference_available" class="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">{{ $t('platform.missingReferenceMetrics') }}</p>
      <div class="space-y-2 border-t border-slate-100 pt-3">
        <label class="flex items-center gap-2"><input v-model="useReference" type="checkbox"> {{ $t('platform.compareAgainstAReferenceMoleculeDatasetOptional') }}</label>
        <div v-if="useReference" class="flex flex-wrap items-center gap-3">
          <ReferenceDatasetPicker v-model="referenceId" class="w-full" :disabled="busy" @busy="busy = $event" />
        </div>
        <p class="text-xs text-slate-500">{{ $t('platform.referenceSimilarityDescription') }}</p>
      </div>
      <section class="space-y-3 border-t border-slate-100 pt-3">
        <h2>{{ $t('platform.keyInteractions') }}</h2>
        <p class="text-xs text-slate-500">{{ $t('platform.interactionRulesHint') }}</p>
        <article v-for="(rule, index) in interactions" :key="index" class="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="font-medium text-slate-800">{{ interactionLabel(rule.interaction_type) }} · {{ $t(rule.match_mode === 'any' ? 'platform.anyResidue' : 'platform.allResidues') }}</p>
            <div class="flex gap-3 text-xs"><button :disabled="busy || Boolean(interactionDraft)" class="text-blue-700" @click="editInteraction(index)">{{ $t('platform.edit') }}</button><button :disabled="busy || Boolean(interactionDraft)" class="text-slate-500 hover:text-red-700" @click="interactions.splice(index, 1)">{{ $t('platform.remove') }}</button></div>
          </div>
          <div class="flex max-h-32 flex-wrap gap-2 overflow-y-auto">
            <span v-for="i in rule.residueIndices" :key="i" class="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-800">{{ residueLabel(options.residues[i]) }}</span>
          </div>
        </article>
        <div v-if="interactionDraft" class="space-y-3 rounded-lg border border-blue-200 p-3">
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="space-y-1 text-xs text-slate-600"><span>{{ $t('platform.interactionType') }}</span><select v-model="interactionDraft.interaction_type" class="block w-full border"><option v-for="type in options.interaction_types" :key="type" :value="type">{{ interactionLabel(type) }}</option></select></label>
            <label class="space-y-1 text-xs text-slate-600"><span>{{ $t('platform.residueMatchingMode') }}</span><select v-model="interactionDraft.match_mode" class="block w-full border"><option value="any">{{ $t('platform.anyResidue') }}</option><option value="all">{{ $t('platform.allResidues') }}</option></select></label>
          </div>
          <ResidueSelectionList :residues="interactionDraft.residueIndices.map(i => options.residues[i])" :available-residues="options.residues" :hint="$t('platform.ppSelectInteractionResidues')" @toggle="toggleInteractionResidue" @clear="interactionDraft.residueIndices = []" />
          <div class="flex gap-2"><Button size="sm" :disabled="!interactionDraft.residueIndices.length" @click="saveInteraction">{{ $t('platform.ppConfirmRule') }}</Button><Button size="sm" variant="outline" @click="interactionDraft = null">{{ $t('common.cancel') }}</Button></div>
        </div>
        <Button v-else variant="outline" size="sm" :disabled="busy" @click="editInteraction()">{{ $t('platform.addInteractionRule') }}</Button>
      </section>
      </section>
      <section class="input-section space-y-3">
        <h2>{{ $t('platform.propertyPrefilters') }}</h2>
        <p v-if="JSON.stringify(prefilters) === JSON.stringify(defaultPrefilters())">{{ $t('platform.defaultPrefilters') }}</p>
        <p v-if="!prefilters.length" class="rounded-lg border border-dashed border-slate-200 p-3 text-slate-500">{{ $t('platform.ppNoPrefilters') }}</p>
        <TarPassFilterEditor v-model="prefilters" :metrics="prefilterMetrics" :disabled="busy" />
        <p v-if="referenceFiltersMissing" role="alert" class="text-xs text-red-700">{{ L('相似度筛选需要选择用于比较的参考分子集。', 'Similarity filters require a reference molecule dataset.') }}</p>
      </section>
      <section class="space-y-3 border-t pt-4">
            <label class="block">{{ $t('platform.taskName') }} <Input v-model="taskName" maxlength="200" :placeholder="$t('platform.tarpassPostprocessing')" /></label>
      <ProteinContextSelector v-if="contextNeedsReselect" :key="contextRefresh" :model-value="explicitContextId" @select="contextOverride = $event; error = ''" @error="error = $event"><template #actions><span /></template></ProteinContextSelector>
      <p v-if="pendingSubmission && !busy" role="status" class="text-sm text-amber-700">{{ $t('platform.submissionUnknown') }}</p>
      <p v-else-if="confirmedJob && !busy" role="status" class="text-sm text-green-700">{{ $t('platform.originalSubmissionConfirmed') }}</p>
      <Button class="w-full" :disabled="busy || (!pendingSubmission && ((contextNeedsReselect && !explicitContextId) || restoring || restoreFailed || !prefiltersValid || Boolean(interactionDraft) || (useReference && !referenceId)))" @click="start">{{ busy ? $t('platform.submitting') : pendingSubmission ? $t('platform.retryOriginalSubmission') : $t('platform.runEvaluation') }}</Button>
      </section>
    </div>

    <template v-if="mode === 'results'">
    <div class="workbench-toolbar">
      <label class="flex min-w-0 flex-wrap items-center gap-2 text-xs">{{ $t('platform.evaluationHistory') }}
        <select v-model="selectedId" :disabled="Boolean(candidateSetId)" class="h-9 max-w-full border text-sm" @change="selectRun">
          <option value="">{{ $t('platform.selectEvaluation') }}</option>
          <option v-for="run in runs" :key="run.id" :value="run.id">{{ new Date(run.created_at).toLocaleString($i18n.locale) }} — {{ statusLabel(run.status) }} — {{ run.id.slice(0, 8) }}</option>
        </select>
      </label>
      <span v-if="selectedJob" class="status-badge" :class="statusColor(selectedJob.status)">{{ statusLabel(selectedJob.status) }}</span>
      <RouterLink to="/help?article=tarpass" class="text-xs text-primary hover:underline">{{ $t('platform.metricHelp') }}</RouterLink>
      <div v-if="!embedded && !candidateSetId" class="ml-auto flex gap-2"><Button size="sm" variant="outline" @click="auxiliaryTab = 'assistant'; assistantOpened = true; detailOpen = true">{{ L('助手', 'Assistant') }}</Button><Button v-if="detailRow" size="sm" variant="ghost" @click="detailRow = null">{{ L('清除选中分子', 'Clear selected molecule') }}</Button></div>
    </div>
    <p v-if="selectedJob?.tasks?.[0]?.error_message" role="alert" class="whitespace-pre-wrap text-destructive">{{ message({ message: selectedJob.tasks[0].error_message }) }}</p>
    <div v-if="selectedJob?.status === 'succeeded'" class="tarpass-result-content">
      <div class="tarpass-options">
      <details v-if="!candidateSetId" class="workbench-section">
        <summary class="cursor-pointer font-semibold">{{ $t('platform.ppEvaluationSummary') }}<span class="ml-2 font-normal tabular-nums text-muted-foreground">{{ output.result_count ?? '—' }} {{ $t('platform.ppTotalRecords') }}</span></summary>
        <div class="mt-3 grid gap-4 lg:grid-cols-2">
        <div class="space-y-3">
          <div class="flex h-4 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
            <div v-for="item in summaryCards" :key="item.key" class="h-full" :class="item.color" :title="`${item.label}: ${item.count ?? '—'}`" :style="{ width: `${output.result_count > 0 ? (item.count ?? 0) / output.result_count * 100 : 0}%` }" />
          </div>
          <div class="flex flex-wrap gap-x-5 gap-y-2 text-xs">
            <span v-for="item in summaryCards" :key="item.key" class="inline-flex items-center gap-2 text-slate-500"><span class="h-2.5 w-2.5 rounded-sm" :class="item.color" aria-hidden="true" />{{ item.key === 'prefiltered' ? $t('platform.propertyPrefilters') : item.label }} <strong class="tabular-nums text-slate-800">{{ item.count ?? '—' }}</strong></span>
          </div>
          <div class="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-xs">
            <span v-for="(rule, index) in filterDrafts(selectedJob.params?.postprocessing?.prefilters || [])" :key="index" class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">{{ metricLabel(rule.metric) }} <span class="font-medium text-slate-800">{{ filterText(rule) }}</span></span>
            <span v-if="!selectedJob.params?.postprocessing?.prefilters?.length" class="text-slate-400">{{ $t('platform.ppNoPrefilters') }}</span>
          </div>
        </div>
        <div><h3 class="mb-3 font-semibold">{{ $t('platform.ppTimings') }}</h3><dl class="grid grid-cols-2 gap-x-5 gap-y-2 text-xs"><template v-for="key in timingKeys" :key="key"><div v-if="output.timings?.[key] != null" class="flex justify-between gap-3"><dt class="text-slate-500">{{ $t(`platform.pp_${key}`) }}</dt><dd class="whitespace-nowrap font-medium tabular-nums">{{ Number(output.timings[key]).toFixed(2) }} s</dd></div></template></dl></div>
        </div>
      </details>
      <div v-else class="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">
        <h3 class="font-semibold">{{ $t('platform.candidate') }}</h3>
        <p class="mt-1">{{ scopeSummary?.result_count ?? total }} {{ $t('platform.ppTotalRecords') }}</p>
        <div v-if="scopeStatuses.length" class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span v-for="item in scopeStatuses" :key="item[0]">{{ statusLabel(item[0]) }} <strong>{{ item[1] }}</strong></span>
        </div>
      </div>
      <details class="workbench-section space-y-3">
      <summary class="cursor-pointer font-semibold">{{ $t('platform.ppResultFilters') }} <span class="ml-2 text-xs font-normal text-slate-500">{{ filterDrafts(appliedFilters).length }}</span></summary>
      <TarPassFilterEditor v-model="filters" :metrics="options?.metric_info || {}" :disabled="busy" />
      <div class="flex flex-wrap items-center gap-3">
        <Button size="sm" :disabled="busy || !filtersValid" @click="applyFilters">{{ $t('platform.applyFilters') }}</Button>
        <Button size="sm" variant="outline" :disabled="busy || (!filters.length && !appliedFilters.length)" @click="filters = []; applyFilters()">{{ $t('platform.ppClearFilters') }}</Button>
        <span v-if="filtersDirty" class="text-xs text-amber-700">{{ $t('platform.ppUnapplied') }}</span>
      </div>
      </details>
      <details class="workbench-section">
        <summary class="cursor-pointer font-semibold">{{ $t('platform.ppClustering') }}<span v-if="clusterSummary" class="ml-2 font-normal text-primary">{{ $t('platform.ppApplied') }}</span></summary>
      <form class="mt-3 space-y-3" @submit.prevent="applyClustering">
        <label class="flex items-center gap-2 font-semibold"><input v-model="clusterEnabled" type="checkbox" :disabled="busy">{{ $t('platform.ppClustering') }}</label>
        <p class="text-xs text-slate-500">{{ $t('platform.ppClusteringHint') }}</p>
        <fieldset :disabled="busy || !clusterEnabled" class="flex flex-wrap items-end gap-4 disabled:opacity-50">
          <label class="space-y-1 text-xs"><span class="block">{{ $t('platform.ppClusterBasis') }}</span><select v-model="clusterDraft.basis" class="border p-1"><option value="molecule">{{ $t('platform.ppWholeMolecule') }}</option><option value="scaffold">{{ $t('platform.ppScaffold') }}</option></select></label>
          <label class="space-y-1 text-xs"><span class="block">{{ $t('platform.ppClusterThreshold') }}</span><input v-model.number="clusterDraft.similarity_threshold" type="number" min="0" max="1" step="any" required class="w-24 border p-1"></label>
          <label class="space-y-1 text-xs"><span class="block">{{ $t('platform.ppRepresentativesPerCluster') }}</span><input v-model.number="clusterDraft.representatives_per_cluster" type="number" min="1" max="20" step="1" required class="w-20 border p-1"></label>
          <label class="flex items-center gap-2 text-xs"><input v-model="clusterDraft.representatives_only" type="checkbox">{{ $t('platform.ppRepresentativesOnly') }}</label>
        </fieldset>
        <div class="flex flex-wrap items-center gap-3"><Button type="submit" size="sm" :disabled="busy">{{ $t('platform.applyFilters') }}</Button><span v-if="clusteringDirty" class="text-xs text-amber-700">{{ $t('platform.ppUnapplied') }}</span></div>
        <p v-if="clusterSummary" class="text-xs text-blue-800">{{ $t('platform.ppClusterSummary', { clusters: clusterSummary.cluster_count, structures: clusterSummary.structure_count, representatives: clusterSummary.representative_count, unclustered: clusterSummary.unclustered_count }) }}</p>
        <p v-if="clusterSummary" class="text-xs text-slate-600">{{ $t('platform.ppRepresentativeRanking', { metric: sortBy === 'molecule_id' ? $t('platform.moleculeId') : metricLabel(sortBy), direction: $t(descending ? 'platform.descending' : 'platform.ppAscending') }) }}</p>
      </form>
      </details>
      <details v-if="editContext" class="workbench-section space-y-3">
        <summary class="cursor-pointer font-semibold">{{ $t('platform.ppEditComparison') }}</summary>
        <template v-if="editContext.status === 'available'">
          <p class="text-xs text-slate-600">{{ $t('platform.ppEditLegend') }}</p>
          <MoleculeViewer :smiles="editContext.molfile" width="320px" height="180px" :highlight-atom-colors="comparisonColors(editContext, true)" />
          <p class="text-xs">{{ $t('platform.ppReferenceAtoms', { retained: editContext.retained_atom_indices.length, changed: editContext.changed_atom_indices.length }) }}</p>
        </template>
        <p v-else class="text-xs text-slate-500">{{ $t('platform.ppEditUnavailable') }}</p>
      </details>
      </div>
      <div v-if="appliedFilters.length" class="flex flex-wrap items-center gap-2 text-xs"><span class="text-slate-500">{{ $t('platform.ppApplied') }}</span><span v-for="(rule, index) in filterDrafts(appliedFilters)" :key="index" class="bg-blue-50 px-2 py-1 text-blue-800">{{ metricLabel(rule.metric) }} {{ filterText(rule) }}</span></div>
      <div class="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <label class="flex items-center gap-2"><input v-model="includePrefiltered" type="checkbox" :disabled="busy" class="h-4 w-4 accent-blue-700" @change="page = 0; loadRows()">{{ $t('platform.ppShowPrefiltered') }}</label>
        <label class="flex items-center gap-2"><input v-model="includeFailed" type="checkbox" :disabled="busy" class="h-4 w-4 accent-blue-700" @change="page = 0; loadRows()">{{ $t('platform.ppShowFailed') }}</label>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 py-3">
        <span class="font-medium tabular-nums">{{ total }} <span class="font-normal text-slate-500">{{ $t('platform.matchingRows') }}</span></span>
        <div class="flex flex-wrap items-center gap-3">
        <Popover><PopoverTrigger as-child><Button variant="outline" size="sm"><SlidersHorizontal class="mr-2 h-4 w-4" />{{ $t('platform.visibleMetrics') }} · {{ columns.length }}</Button></PopoverTrigger>
          <PopoverContent align="end" class="w-80 max-w-[calc(100vw-2rem)]">
            <div class="mb-3 flex items-center justify-between gap-2"><h3 class="text-sm font-semibold">{{ $t('platform.visibleMetrics') }}</h3><button class="text-xs text-blue-700" @click="columns = [...defaultColumns]">{{ $t('platform.ppRestoreColumns') }}</button></div>
            <Input v-model="metricSearch" :placeholder="$t('platform.ppSearchMetrics')" :aria-label="$t('platform.ppSearchMetrics')" />
            <div class="mt-3 max-h-72 space-y-3 overflow-y-auto"><div v-for="group in searchedMetricGroups" :key="group.key"><h4 class="mb-1 text-xs font-semibold text-slate-500">{{ group.label }}</h4><label v-for="key in group.keys" :key="key" class="flex cursor-pointer items-center gap-2 px-1 py-2 text-xs hover:bg-slate-50"><input v-model="columns" type="checkbox" :value="key" class="accent-blue-700">{{ metricLabel(key) }}</label></div><p v-if="!searchedMetricGroups.length" class="text-xs text-slate-500">{{ $t('platform.ppNoMetrics') }}</p></div>
          </PopoverContent>
        </Popover>
        <Button variant="outline" size="sm" :disabled="busy" @click="download('csv')">{{ $t('platform.exportFilteredCsv') }}</Button>
        <Popover><PopoverTrigger as-child><Button variant="outline" size="sm" :disabled="busy">{{ $t('platform.exportFilteredSdf') }}</Button></PopoverTrigger><PopoverContent class="w-48"><button v-for="item in ['original', 'docked'] as const" :key="item" class="block w-full p-2 text-left hover:bg-slate-50" :disabled="busy" @click="download('sdf', item)">{{ $t(`platform.${item}`) }}</button></PopoverContent></Popover>
        </div>
      </div>
      <p v-if="exportMessage" role="status">{{ exportMessage }}</p>
      <p v-if="busy" role="status" class="text-xs text-slate-500">{{ $t('platform.loading') }}</p>
      <div ref="resultTable" class="workbench-table-scroll">
        <table class="w-full text-xs" :aria-busy="busy">
          <thead><tr class="bg-slate-50"><th v-for="key in ['molecule_id', 'structure', ...columns, 'details']" :key="key" class="whitespace-nowrap px-3 py-3 text-left font-medium text-slate-600" :title="key" :aria-sort="sortBy === key ? (descending ? 'descending' : 'ascending') : undefined"><span class="inline-flex items-center gap-2">{{ key === 'molecule_id' ? $t('platform.moleculeStatus') : key === 'structure' || key === 'details' ? $t(`platform.${key}`) : metricLabel(key) }}<span v-if="key === 'molecule_id' || columns.includes(key)" class="sort-controls"><button v-for="desc in [false, true]" :key="String(desc)" class="sort-arrow" :class="sortBy === key && descending === desc ? 'sort-active' : ''" :disabled="busy" :aria-label="`${key === 'molecule_id' ? $t('platform.moleculeId') : metricLabel(key)}: ${$t(desc ? 'platform.descending' : 'platform.ppAscending')}`" :aria-pressed="sortBy === key && descending === desc" @click="setSort(key, desc)"><span aria-hidden="true" class="sort-triangle" :class="{ 'sort-triangle-down': desc }" /></button></span></span></th></tr></thead>
          <tbody><tr v-if="!busy && !rows.length"><td :colspan="columns.length + 3" class="p-10 text-center text-slate-500">{{ $t('platform.ppNoResults') }}</td></tr><tr v-for="row in rows" :key="row.molecule_id" class="border-t border-slate-100 hover:bg-slate-50/60">
            <td class="whitespace-nowrap px-3 py-3"><button class="font-medium text-blue-700 hover:underline" :disabled="!sourceJob" @click="showPose(row, true)">{{ row.molecule_id }}</button><button class="mt-1 block text-blue-700 hover:underline disabled:text-slate-400" :disabled="!sourceJob" @click="showPose(row, false)">{{ $t('platform.3dView') }}</button><button v-if="!readOnly" class="mt-1 block rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-700 hover:bg-blue-100" :disabled="!row.smiles" @click.stop="continueOptimization(row)">{{ $t('platform.continue') }} · {{ $t('platform.leadOptimization') }}</button><span class="mt-2 inline-block px-2 py-1 text-[11px]" :class="statusColor(row.status)">{{ statusLabel(row.status) }}</span><div v-if="clusterSummary" class="mt-2 space-y-1 text-xs"><template v-if="row.cluster_id != null"><p>{{ $t('platform.ppClusterNumber', { id: row.cluster_id }) }}</p><p class="text-slate-500">{{ $t('platform.ppClusterSize', { structures: row.cluster_size, records: row.cluster_record_count }) }}</p><span v-if="row.is_representative" class="inline-block bg-blue-50 px-2 py-1 text-blue-800">{{ $t('platform.ppRepresentative') }}</span></template><span v-else class="text-slate-400">{{ $t('platform.ppUnclustered') }}</span></div></td>
            <td class="min-w-40 px-3 py-2"><MoleculeViewer v-if="row.smiles" :smiles="row.edit_preview?.molfile || row.smiles" width="180px" height="130px" :highlight-atom-colors="comparisonColors(row.edit_preview)" :loading-text="$t('platform.loading')" :error-text="$t('platform.failedToRenderCandidate')" /><p v-if="row.edit_preview" class="text-xs text-slate-500">{{ $t('platform.ppCandidateAtoms', { retained: row.edit_preview.retained_atom_indices.length, changed: row.edit_preview.changed_atom_indices.length }) }}</p><p v-else-if="editContext" class="text-xs text-slate-500">{{ $t('platform.ppEditUnavailable') }}</p><details v-if="row.smiles" class="mt-1"><summary class="cursor-pointer text-slate-500">SMILES</summary><p class="max-w-60 break-all py-2 font-mono">{{ row.smiles }}</p></details><span v-else class="text-slate-400">{{ $t('platform.unreadableSdfRecord') }}</span></td>
            <td v-for="key in columns" :key="key" class="px-3 py-3 text-right tabular-nums" :class="value(row, key) == null ? 'text-slate-400' : 'text-slate-800'" :title="value(row, key) == null ? $t('platform.notCalculatedUnavailable') : undefined">{{ value(row, key) == null ? '—' : formatMetric(value(row, key)) }}</td>
            <td class="p-3 align-top"><Button variant="ghost" size="sm" @click="detailRow = row; auxiliaryTab = 'details'; detailOpen = true">{{ $t('platform.interactionsErrors') }}</Button></td>
          </tr></tbody>
        </table>
      </div>
      <div class="workbench-pagination"><span class="tabular-nums" aria-live="polite">{{ page + 1 }} / {{ Math.max(1, Math.ceil(total / pageSize)) }}</span><div class="flex gap-2"><Button size="sm" variant="outline" :disabled="busy || page === 0" @click="changePage(page - 1)">{{ $t('platform.previous') }}</Button><Button size="sm" variant="outline" :disabled="busy || (page + 1) * pageSize >= total" @click="changePage(page + 1)">{{ $t('platform.next') }}</Button></div></div>
    </div>
    </template>
    <Dialog v-model:open="showViewer"><DialogContent class="max-w-5xl"><DialogHeader><DialogTitle>{{ $t(ligandOnly ? 'platform.moleculeSdfPreview' : 'platform.bindingPosePreview') }} — {{ viewerId }}</DialogTitle><DialogDescription>{{ $t(ligandOnly ? 'platform.moleculeOnlyHint' : 'platform.evaluatedMoleculeInThePreparedReceptorCoordinateSystem') }}</DialogDescription></DialogHeader>
      <div class="flex flex-wrap items-center gap-3 text-sm">
        <label>{{ $t('platform.pose') }} <select v-model="viewMode" class="border p-1"><option v-if="viewerRow?.has_original_pose !== false && (ligandOnly || isInSitu)" value="original" :disabled="availability.original === false">{{ $t('platform.original') }}</option><option value="docked" :disabled="availability.docked === false">{{ $t('platform.docked') }}</option><option v-if="viewerRow?.has_original_pose !== false && !ligandOnly && isInSitu" value="compare" :disabled="availability.original === false || availability.docked === false">{{ $t('platform.poseOverlay') }}</option></select></label>
        <label v-if="viewMode === 'compare'">{{ $t('platform.bindingPlip') }} <select v-model="comparisonPose" class="border p-1"><option value="original">{{ $t('platform.original') }}</option><option value="docked">{{ $t('platform.docked') }}</option></select></label>
      </div>
      <div ref="poseContainer" class="h-[65vh]" />
    </DialogContent></Dialog>
    <div class="hidden"><Teleport :to="poseContainer || 'body'" :disabled="!poseContainer">
      <BindingPoseViewer v-if="viewerRow" :visible="showViewer" :job-id="selectedId" :molecule-id="viewerId" :pose="pose" :compare="viewMode === 'compare'" :ligand-only="ligandOnly" @availability="availability = { ...availability, ...$event }" :interactions="viewerRow.metrics?.[pose]?.detected_interactions" :interaction-error="viewerRow.metrics?.[pose]?.errors?.interactions" />
    </Teleport></div>
    <Dialog v-model:open="conformerPickerOpen"><DialogContent class="max-w-md"><DialogHeader><DialogTitle>{{ $t('platform.bindingConformer') }}</DialogTitle><DialogDescription>{{ pendingOptimization?.smiles }}</DialogDescription></DialogHeader><p class="text-sm text-slate-600">{{ $t('platform.bindingConformer') }} · {{ conformerOptions.length }}</p><select v-model.number="selectedSourceIndex" class="w-full rounded border border-slate-300 p-2" :disabled="conformerLoading"><option v-for="record in conformerOptions" :key="record.source_index" :value="record.source_index">{{ record.source_index + 1 }}</option></select><div class="flex justify-end gap-2"><Button variant="outline" :disabled="conformerLoading" @click="conformerPickerOpen = false">{{ $t('common.cancel') }}</Button><Button :disabled="conformerLoading || selectedSourceIndex == null" @click="confirmOptimization">{{ $t('platform.continue') }}</Button></div></DialogContent></Dialog>
  </section>
  <template #panel-header><WorkspacePanelTabs v-model="auxiliaryTab" :label="$t('platform.resultDetails')" :tabs="[{ value: 'details', label: L('详情', 'Details') }, ...(!embedded && !candidateSetId && mode === 'results' ? [{ value: 'assistant', label: L('助手', 'Assistant') }] : [])]" @update:model-value="value => { if (value === 'assistant') assistantOpened = true }" /></template>
  <template #auxiliary><ModuleAssistantPanel v-if="assistantOpened && mode === 'results' && selectedJob && !embedded && !candidateSetId" v-show="auxiliaryTab === 'assistant'" :key="selectedId" module="tarpass" :job-id="selectedId" :context="assistantContext" :apply="applyAssistant" /><div v-if="detailRow && auxiliaryTab === 'details'" class="space-y-4"><MoleculeDetails :row="detailRow" :has3d="Boolean(sourceJob)" @view3d="showPose(detailRow, false)" /><div class="space-y-3"><p v-if="detailRow.has_original_pose === false" class="text-slate-500">{{ $t('platform.ppNoOriginalPose') }}</p><div v-if="detailRow.prefilter_reasons?.length" class="flex flex-wrap gap-1"><span v-for="reason in detailRow.prefilter_reasons" :key="reason" class="bg-amber-50 px-2 py-1 text-amber-800">{{ metricLabel(reason) }}</span></div><section v-for="group in detailGroups(detailRow)" :key="group.label" class="border border-slate-200 p-3"><h4 class="mb-2 font-semibold">{{ group.label }}</h4><dl class="max-h-56 space-y-2 overflow-auto"><div v-for="entry in group.entries" :key="entry[0]" class="flex justify-between gap-3"><dt class="break-words text-slate-500">{{ entry[0] }}</dt><dd class="max-w-48 break-words text-right">{{ entry[1] }}</dd></div></dl></section><details><summary class="cursor-pointer text-slate-500">{{ $t('platform.ppRawData') }}</summary><pre class="mt-2 max-h-64 overflow-auto bg-slate-50 p-2">{{ JSON.stringify(detailRow, null, 2) }}</pre></details></div></div></template>
  </WorkspaceLayout>
</template>

<script setup lang="ts">
import '@/assets/module-workbench.css'
import WorkspacePanelTabs from '@/components/workbench/WorkspacePanelTabs.vue'

import { defaultPrefilters } from '@/utils/tarpassDefaults'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import MoleculeDetails from '@/components/workbench/MoleculeDetails.vue'
import { useWorkspaceState } from '@/composables/useWorkspace'
import { statusTone } from '@/utils/taskPresentation'
import i18n, { translate, statusLabel } from '@/i18n'

import { defineAsyncComponent, computed, onBeforeUnmount, ref, watch } from 'vue'
import { clearMoleculeRenderer } from '@/utils/moleculeRenderer'
import request from '@/utils/request'
import { useRoute, useRouter } from 'vue-router'
import ModuleAssistantPanel from '@/pages/agent/components/ModuleAssistantPanel.vue'
import { useModuleSuggestion } from '@/composables/useModuleSuggestion'
import type { ModuleContext, ModuleSuggestion } from '@/api/moduleAssistant'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getBackendJob, getBackendDataset, listBackendJobs, type BackendJobOut, type BackendJobListOut } from '@/api/genovaBackend'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
const BindingPoseViewer = defineAsyncComponent(() => import('@/components/molecule/BindingPoseViewer.vue'))
import MoleculeViewer from '@/components/common/MoleculeViewer.vue'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import TarPassFilterEditor from './TarPassFilterEditor.vue'
import ReferenceDatasetPicker from './ReferenceDatasetPicker.vue'
import ProteinContextSelector from '@/components/protein-preparation/ProteinContextSelector.vue'
import { useTarPassMetrics, expandFilters, filterDrafts, validFilters, type MetricFilter, type MetricFilterDraft } from './useTarPassMetrics'
import ResidueSelectionList from '@/components/protein-preparation/ResidueSelectionList.vue'
import type { ResidueRef } from '@/types/proteinContext'
import { SlidersHorizontal } from 'lucide-vue-next'
import { displayErrorMessage } from '@/utils/requestError'

const props = withDefaults(defineProps<{ sourceJobId: string; sourceJob?: BackendJobOut | null; sourceJobName?: string; initialJobId?: string; restoreJob?: BackendJobOut; proteinContextId?: string; candidateSetId?: string; mode?: 'submit' | 'results'; embedded?: boolean; readOnly?: boolean; bindAssistant?: (jobId: string) => Promise<void> }>(), { mode: 'results', candidateSetId: '', embedded: false })
const emit = defineEmits<{
  referenceAvailability: [available: boolean]
  continueOptimization: [payload: { jobId: string; resultId?: string; moleculeId?: string; sourceIndex?: number; pose?: 'original' | 'docked'; smiles?: string }]
  submitted: [jobId: string]
  preparePostprocessing: [payload: Record<string, any>]
}>()
import { useJobSubmission } from '@/composables/useJobSubmission'
const router = useRouter()
const route = useRoute()
const L = (zh: string, en: string) => i18n.global.locale.value.startsWith('zh') ? zh : en
const auxiliaryTab = ref('details'), assistantOpened = ref(false)
const moduleSuggestion = useModuleSuggestion('tarpass')
const taskName = ref(`${translate('platform.postprocessing')} ${props.sourceJobName || props.sourceJobId.slice(0, 8)}`.slice(0, 200))
type Filter = MetricFilter
const options = ref<any>(null)
const error = ref('')
const busy = ref(false)
const { pendingSubmission, confirmedJob, sendJob } = useJobSubmission('postprocessing:' + props.sourceJobId)
const contextOverride = ref<string | null>(null), contextNeedsReselect = ref(false), contextRefresh = ref(0)
const explicitContextId = computed(() => contextOverride.value ?? (props.proteinContextId || props.restoreJob?.params.postprocessing?.protein_context_id || ''))
const restoring = ref(Boolean(props.restoreJob))
const restoreFailed = ref(false)
const useReference = ref(false)
const referenceId = ref('')
const prefilters = ref<MetricFilterDraft[]>(defaultPrefilters())
const selectedId = ref(props.initialJobId || '')
const pageSize = 25
const resultTable = ref<HTMLDivElement | null>(null)
const { filters, appliedFilters, page, sortBy, descending, includePrefiltered, includeFailed, detailRow, detailOpen, columns, clusterEnabled, clusterDraft, appliedClustering } = useWorkspaceState('tarpass-results', () => `${props.sourceJobId}:${selectedId.value}`, { filters: [] as MetricFilterDraft[], appliedFilters: [] as Filter[], page: 0, sortBy: 'molecule_id', descending: false, includePrefiltered: false, includeFailed: false, detailRow: null as any, detailOpen: false, columns: ['qed', 'sa_score', 'original.affinity', 'docked.affinity', 'docked.no_clashes', 'docked.matched_rate'], clusterEnabled: false, clusterDraft: { basis: 'molecule', similarity_threshold: 0.6, representatives_per_cluster: 1, representatives_only: false } as Clustering, appliedClustering: null as Clustering | null })
type Clustering = { basis: 'molecule' | 'scaffold'; similarity_threshold: number; representatives_per_cluster: number; representatives_only: boolean }
const clusterSummary = ref<any>(null)
const editContext = ref<any>(null)
const clusteringDirty = computed(() => JSON.stringify(clusterEnabled.value ? clusterDraft.value : null) !== JSON.stringify(appliedClustering.value))
onBeforeUnmount(clearMoleculeRenderer)
let resultsController: AbortController | undefined
const poseContainer = ref<HTMLElement | null>(null)
onBeforeUnmount(() => resultsController?.abort())
type Interaction = { interaction_type: string; match_mode: string; residueIndices: number[] }
const interactions = ref<Interaction[]>([])
const interactionDraft = ref<Interaction | null>(null)
const editingInteraction = ref<number | null>(null)
function editInteraction(index: number | null = null) {
  editingInteraction.value = index
  const rule = index === null ? { interaction_type: 'H-Bond', match_mode: 'any', residueIndices: [] } : interactions.value[index]
  interactionDraft.value = { ...rule, residueIndices: [...rule.residueIndices] }
}
function toggleInteractionResidue(residue: ResidueRef) {
  const indices = interactionDraft.value!.residueIndices
  const index = options.value.residues.indexOf(residue)
  const selected = indices.indexOf(index)
  if (selected < 0) indices.push(index)
  else indices.splice(selected, 1)
}
function saveInteraction() {
  if (!interactionDraft.value?.residueIndices.length) return
  if (editingInteraction.value === null) interactions.value.push(interactionDraft.value)
  else interactions.value[editingInteraction.value] = interactionDraft.value
  interactionDraft.value = null
}
function residueLabel(residue: ResidueRef) {
  return `${residue.chain_id || translate('platform.blank')}:${residue.residue_name}${residue.residue_number}${residue.insertion_code || ''}`
}
const runs = ref<BackendJobListOut[]>([])
const selectedJob = ref<BackendJobOut | null>(null)
const rows = ref<any[]>([])
const total = ref(0)
const scopeSummary = ref<{ result_count: number; status_counts: Record<string, number> } | null>(null)
const viewMode = ref<'original' | 'docked' | 'compare'>('original')
const comparisonPose = ref<'original' | 'docked'>('original')
const ligandOnly = ref(false)
const availability = ref<{ original?: boolean; docked?: boolean }>({})
const isInSitu = computed(() => {
  const task = props.sourceJob?.tasks?.find(task => ['molecule_generation', 'property_optimization', 'surfgen_inference'].includes(task.task_code))
  const engine = task?.output_payload?.engine || props.sourceJob?.params?.molecule_generation?.engine || props.sourceJob?.params?.property_optimization?.engine
  return ['surfgen', 'delete'].includes(String(engine).toLowerCase())
})
const pose = computed(() => viewMode.value === 'compare' ? comparisonPose.value : viewMode.value)
const defaultColumns = ['qed', 'sa_score', 'original.affinity', 'docked.affinity', 'docked.no_clashes', 'docked.matched_rate']
const { interactionLabel } = useTarPassMetrics(() => options.value?.metric_info || {})
const prefilterMetrics = computed(() => Object.fromEntries((options.value?.prefilter_metrics || []).map((key: string) => [key, options.value.metric_info[key]])))
const referenceFiltersMissing = computed(() => prefilters.value.some(rule => ['reference_similarity', 'scaffold_similarity'].includes(rule.metric)) && !(useReference.value && referenceId.value))
const prefiltersValid = computed(() => Boolean(options.value) && !referenceFiltersMissing.value && validFilters(prefilters.value, prefilterMetrics.value))
const filtersValid = computed(() => Boolean(options.value) && validFilters(filters.value, options.value.metric_info))
const metricSearch = ref('')
const metrics = computed<string[]>(() => options.value?.metrics || [])
const output = computed(() => selectedJob.value?.tasks?.[0]?.output_payload || {})
const timingKeys = ['read_seconds', 'properties_seconds', 'preparation_original_seconds', 'docking_seconds', 'docked_evaluation_seconds', 'total_seconds']
const filtersDirty = computed(() => JSON.stringify(expandFilters(filters.value)) !== JSON.stringify(appliedFilters.value))
const summaryCards = computed(() => Object.entries({ prefiltered: 'bg-slate-400', succeeded: 'bg-teal-600', partial: 'bg-amber-500', failed: 'bg-rose-500', invalid: 'bg-violet-500' }).map(([key, color]) => ({ key, label: statusLabel(key), count: output.value.counts?.[key], color })))
const scopeStatuses = computed(() => Object.entries(scopeSummary.value?.status_counts || {}).filter(([, count]) => count > 0))
const metricGroups = computed(() => ['properties', 'original', 'docked'].map(key => ({
  key, label: translate(key === 'properties' ? 'platform.ppProperties' : `platform.${key}`),
  keys: metrics.value.filter(metric => key === 'properties' ? !metric.includes('.') : metric.startsWith(`${key}.`)),
})).filter(group => group.keys.length))
const searchedMetricGroups = computed(() => metricGroups.value.map(group => ({
  ...group, keys: group.keys.filter(metric => `${metric} ${metricLabel(metric)}`.toLowerCase().includes(metricSearch.value.trim().toLowerCase())),
})).filter(group => group.keys.length))
const exportMessage = ref('')
const showViewer = ref(false)
const viewerRow = ref<any>(null)
const viewerId = ref('')
const conformerPickerOpen = ref(false)
const conformerOptions = ref<Array<{ source_index: number }>>([])
const selectedSourceIndex = ref<number | null>(null)
const pendingOptimization = ref<{ jobId: string; resultId?: string; moleculeId?: string; pose?: 'original' | 'docked'; smiles?: string } | null>(null)
const conformerLoading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let resultsRequest = 0

function comparisonColors(preview: any, reference = false): Record<number, [number, number, number]> {
  const colors: Record<number, [number, number, number]> = {}
  for (const index of preview?.retained_atom_indices || []) colors[index] = [0.3, 0.8, 0.5]
  for (const index of preview?.changed_atom_indices || []) colors[index] = reference ? [1, 0.55, 0.45] : [0.4, 0.65, 1]
  return colors
}

function applyClustering() {
  if (clusterEnabled.value && !appliedClustering.value) {
    sortBy.value = 'docked.affinity'; descending.value = false
    if (!columns.value.includes(sortBy.value)) columns.value.push(sortBy.value)
  }
  appliedClustering.value = clusterEnabled.value ? { ...clusterDraft.value } : null
  page.value = 0
  loadRows()
}

function message(exc: any) {
  const detail = exc?.response?.data?.detail
  if (typeof detail === 'string' && detail.startsWith('Clustering supports at most 2000')) return translate('platform.ppClusterTooLarge')
  return displayErrorMessage(exc)
}
function value(row: any, key: string) { return key.split('.').reduce((obj, part) => obj?.[part], row.metrics) }
function formatMetric(v: any) { return v == null ? translate('platform.notCalculatedUnavailable') : typeof v === 'number' ? v.toFixed(3) : typeof v === 'boolean' ? translate(v ? 'platform.yes' : 'platform.no') : String(v) }
function isBoolean(key: string) { return options.value?.metric_info?.[key]?.type === 'boolean' }
function metricLabel(key: string) {
  const info = options.value?.metric_info?.[key]
  const [prefix, metric] = key.includes('.') ? key.split('.') : ['', key]
  const label = translate(`platform.metrics.${metric}`)
  return `${prefix ? translate(`platform.${prefix}`) + ' / ' : ''}${label}${info?.unit ? ` (${info.unit})` : ''}`
}
function operatorLabel(op: string) { return ({ gt: '>', lt: '<', gte: '≥', lte: '≤', eq: '=' } as Record<string, string>)[op] || op }
function filterText(rule: MetricFilterDraft) { return isBoolean(rule.metric) ? translate(rule.value ? 'platform.yes' : 'platform.no') : rule.op === 'between' ? `${rule.value}–${rule.upper}` : `${operatorLabel(rule.op)} ${rule.value}` }
const statusColor = (status: string) => `status-badge ${statusTone(status)}`
function setSort(key: string, desc: boolean) { sortBy.value = key; descending.value = desc; page.value = 0; loadRows() }
function detailEntries(data: any, prefix = ''): [string, string][] {
  return Object.entries(data || {}).flatMap(([key, v]) => {
    const label = `${prefix}${/^\d+$/.test(key) ? Number(key) + 1 : i18n.global.te(`platform.metrics.${key}`) ? translate(`platform.metrics.${key}`) : key.replace(/_/g, ' ')}`
    return v === undefined ? [] : v !== null && typeof v === 'object' ? detailEntries(v, `${label} / `) : [[label, formatMetric(v)] as [string, string]]
  })
}
function detailGroups(row: any) {
  return [
    { label: translate('platform.ppErrors'), entries: detailEntries(row.errors) },
    { label: translate('platform.original'), entries: detailEntries(row.metrics.original) },
    { label: translate('platform.docked'), entries: detailEntries(row.metrics.docked) },
    { label: translate('platform.referenceMolecules'), entries: detailEntries({ reference: row.metrics.reference_similarity_match, scaffold: row.metrics.scaffold_similarity_match }) },
  ].filter(group => group.entries.length)
}
function query() { return { include_prefiltered: includePrefiltered.value, include_failed: includeFailed.value, filters: appliedFilters.value, sort_by: sortBy.value, descending: descending.value, clustering: appliedClustering.value, candidate_set_id: props.candidateSetId || undefined } }
function applyFilters() { if (!filtersValid.value) return; appliedFilters.value = expandFilters(filters.value); page.value = 0; loadRows() }
async function changePage(next: number) {
  page.value = next
  await loadRows()
  if (!error.value) resultTable.value?.scrollIntoView({ block: 'start', inline: 'nearest' })
}

function formValues() {
  return { prefilters: expandFilters(prefilters.value), reference_dataset_id: useReference.value ? referenceId.value || null : null, key_interactions: interactions.value.map(rule => ({ interaction_type: rule.interaction_type, match_mode: rule.match_mode, residues: rule.residueIndices.map(i => options.value?.residues[i]) })) }
}
const assistantContext = computed<ModuleContext>(() => ({
  engine: 'tarpass', source_job_id: props.sourceJobId || undefined,
  protein_context_id: props.proteinContextId || props.restoreJob?.params.postprocessing?.protein_context_id || selectedJob.value?.params.postprocessing?.protein_context_id || selectedJob.value?.params.protein_context_id || undefined,
  form: props.mode === 'results' ? selectedJob.value?.params.postprocessing || {} : formValues(),
  view: { filters: appliedFilters.value, sort_by: sortBy.value, descending: descending.value, include_prefiltered: includePrefiltered.value, include_failed: includeFailed.value, clustering: appliedClustering.value },
  view_draft: { filters: expandFilters(filters.value), sort_by: sortBy.value, descending: descending.value, include_prefiltered: includePrefiltered.value, include_failed: includeFailed.value, clustering: appliedClustering.value },
  selected_ids: detailRow.value?.molecule_id ? [detailRow.value.molecule_id] : [],
}))
function applyDraftChanges(changes: Record<string, any>) {
  let mapped: Interaction[] | undefined
  if ('key_interactions' in changes) {
    mapped = changes.key_interactions.map((rule: any) => ({ ...rule, residueIndices: rule.residues.map((residue: any) => options.value.residues.findIndex((candidate: any) => ['chain_id', 'residue_name', 'residue_number', 'insertion_code'].every(key => (candidate[key] ?? '') === (residue[key] ?? '')))) }))
    if (mapped!.some((rule: any) => rule.residueIndices.some((index: number) => index < 0))) throw new Error(L('相互作用残基已变化，请重新生成建议。', 'Interaction residues changed; request a new suggestion.'))
  }
  if ('prefilters' in changes) prefilters.value = filterDrafts(changes.prefilters)
  if (mapped) interactions.value = mapped
}
async function applyAssistant(suggestion: ModuleSuggestion) {
  if (busy.value || restoring.value || interactionDraft.value) throw new Error(L('请先完成当前编辑或等待加载。', 'Finish editing or wait for loading.'))
  const changes = Object.fromEntries(suggestion.changes.map(change => [change.field, change.after]))
  if (suggestion.target === 'draft') {
    if (props.mode === 'results') await moduleSuggestion.openDraft(router, selectedId.value, suggestion)
    else applyDraftChanges(changes)
    return
  }
  if ('filters' in changes) { filters.value = filterDrafts(changes.filters); appliedFilters.value = JSON.parse(JSON.stringify(changes.filters)) }
  if ('sort_by' in changes) { if (changes.sort_by !== 'molecule_id' && !columns.value.includes(changes.sort_by)) columns.value = [...columns.value, changes.sort_by]; sortBy.value = changes.sort_by }
  if ('descending' in changes) descending.value = changes.descending
  if ('include_prefiltered' in changes) includePrefiltered.value = changes.include_prefiltered
  if ('include_failed' in changes) includeFailed.value = changes.include_failed
  page.value = 0
  await loadRows()
  if (error.value) throw new Error(error.value)
}
defineExpose({ assistantContext, applyAssistant })


async function refresh() {
  if (timer) clearTimeout(timer)
  const sourceId = props.sourceJobId
  const runId = selectedId.value
  try {
    const history = (await listBackendJobs({ source_job_id: sourceId, limit: 200 })).data
    if (sourceId !== props.sourceJobId || runId !== selectedId.value || disposed) return
    runs.value = history
    if (runId) {
      const job = (await getBackendJob(runId, { summary: true })).data
      if (sourceId !== props.sourceJobId || runId !== selectedId.value || disposed) return
      selectedJob.value = job
      if (selectedJob.value.status === 'succeeded') await loadRows()
      if (!disposed && ['pending', 'queued', 'running'].includes(selectedJob.value.status)) timer = setTimeout(refresh, 4000)
    }
  } catch (exc) { if (sourceId === props.sourceJobId && runId === selectedId.value && !disposed) error.value = message(exc) }
}
async function selectRun() { resultsRequest++; busy.value = false; rows.value = []; total.value = 0; clusterSummary.value = null; editContext.value = null; selectedJob.value = null; await refresh() }
async function start() {
  if (busy.value || (!pendingSubmission.value && ((contextNeedsReselect.value && !explicitContextId.value) || restoring.value || restoreFailed.value || !prefiltersValid.value || interactionDraft.value || !options.value || (useReference.value && !referenceId.value)))) return
  busy.value = true; error.value = ''
  try {
    if (pendingSubmission.value) { await sendJob(); return }
    const postprocessing = {
      source_job_id: props.sourceJobId, prefilters: expandFilters(prefilters.value),
      protein_context_id: explicitContextId.value || undefined,
      key_interactions: interactions.value.map(rule => ({ interaction_type: rule.interaction_type, match_mode: rule.match_mode, residues: rule.residueIndices.map(i => options.value.residues[i]) })),
      reference_dataset_id: useReference.value ? referenceId.value : null,
    }
    if (props.embedded) {
      emit('preparePostprocessing', { job_name: taskName.value.trim(), postprocessing })
      return
    }
    const response = await sendJob({ job_type: 'molecule_postprocessing', params: { job_name: taskName.value.trim(), postprocessing } })
    emit('submitted', response.data.id)
    if (props.bindAssistant) await props.bindAssistant(response.data.id)
    await router.push({ path: '/postprocessing/results', query: { job_id: response.data.id } })
  } catch (exc: any) {
    const detail = exc?.response?.data?.detail
    if (detail?.error_code === 'PROTEIN_CONTEXT_STALE') {
      if (explicitContextId.value === detail.protein_context_id) {
        contextOverride.value = ''; contextNeedsReselect.value = true; contextRefresh.value++
      }
      error.value = L('所选 Protein Context 已失效，请重新选择。其他参数已保留。', 'The selected Protein Context is no longer available. Select another one; other parameters have been kept.')
    } else error.value = message(exc)
  }
  finally { busy.value = false }
}
async function loadRows() {
  if (!selectedId.value) return
  const requestId = ++resultsRequest
  resultsController?.abort(); resultsController = new AbortController()
  const runId = selectedId.value
  busy.value = true; error.value = ''; exportMessage.value = ''
  rows.value = []; total.value = 0; scopeSummary.value = null; clusterSummary.value = null; editContext.value = null
  try {
    const response = await request.post(`/api/v1/jobs/${runId}/postprocessing/results`, { ...query(), offset: page.value * pageSize, limit: pageSize }, { signal: resultsController.signal })
    if (requestId !== resultsRequest || runId !== selectedId.value || disposed) return
    rows.value = response.data.rows; total.value = response.data.total; scopeSummary.value = response.data.scope_summary || null
    clusterSummary.value = response.data.clustering || null; editContext.value = response.data.edit_context || null
  } catch (exc) { if (requestId === resultsRequest && runId === selectedId.value && !disposed && !resultsController?.signal.aborted) error.value = message(exc) }
  finally { if (requestId === resultsRequest) busy.value = false }
}
async function download(format: 'csv' | 'sdf', exportPose: 'original' | 'docked' = 'docked') {
  busy.value = true; error.value = ''; exportMessage.value = ''
  try {
    const response = await request.post(`/api/v1/jobs/${selectedId.value}/postprocessing/export`, { ...query(), format, pose: exportPose }, { responseType: 'blob' })
    const url = URL.createObjectURL(response.data)
    const a = document.createElement('a'); a.href = url; a.download = format === 'sdf' ? `tarpass-${exportPose}.sdf` : 'tarpass.csv'; a.click(); URL.revokeObjectURL(url)
    exportMessage.value = translate('platform.exportSummary', { count: response.headers['x-exported-count'] ?? total.value, skipped: response.headers['x-skipped-count'] ?? 0 })
  } catch (exc) { error.value = message(exc) }
  finally { busy.value = false }
}
function showPose(row: any, moleculeOnly: boolean) {
  ligandOnly.value = moleculeOnly
  viewMode.value = isInSitu.value && row.has_original_pose !== false ? 'original' : 'docked'
  comparisonPose.value = 'original'
  availability.value = {}
  viewerRow.value = row
  viewerId.value = row.molecule_id
  showViewer.value = true
}
async function continueOptimization(row: any) {
  if (props.readOnly) return
  const pose: 'original' | 'docked' = row.has_original_pose !== false && isInSitu.value ? 'original' : 'docked'
  const payload: { jobId: string; resultId?: string; moleculeId?: string; pose?: 'original' | 'docked'; smiles?: string } = { jobId: selectedId.value, resultId: row.result_id || row.id, moleculeId: row.molecule_id, pose, smiles: row.smiles }
  if (!payload.resultId && !payload.moleculeId) return
  const outputPayload = selectedJob.value?.tasks?.[0]?.output_payload || {}
  const poseArtifact = pose === 'original' ? outputPayload.original_sdf : outputPayload.docked_sdf
  if (!poseArtifact) {
    emit('continueOptimization', { ...payload, sourceIndex: undefined, pose: undefined })
    return
  }
  conformerLoading.value = true
  error.value = ''
  try {
    const response = await request.get(`/api/v1/jobs/${selectedId.value}/structures`, { params: { result_id: payload.resultId, molecule_id: payload.moleculeId, pose, limit: 100 } })
    const records = (response.data?.records || []) as Array<{ source_index: number }>
    if (!records.length) {
      error.value = translate('platform.failedToLoadResults')
      return
    }
    if (records.length === 1) {
      emit('continueOptimization', { ...payload, sourceIndex: records[0]?.source_index })
      return
    }
    pendingOptimization.value = payload
    conformerOptions.value = records
    selectedSourceIndex.value = null
    conformerPickerOpen.value = true
  } catch (exc) {
    error.value = message(exc)
  } finally {
    conformerLoading.value = false
  }
}
function confirmOptimization() {
  if (!pendingOptimization.value || selectedSourceIndex.value == null) return
  emit('continueOptimization', { ...pendingOptimization.value, sourceIndex: selectedSourceIndex.value })
  pendingOptimization.value = null
  conformerPickerOpen.value = false
}
watch(selectedId, () => { showViewer.value = false; viewerRow.value = null })
watch(() => props.candidateSetId, () => { page.value=0; void loadRows() })

watch(() => props.sourceJobId, async (id, _previous, onCleanup) => {
  let stale = false
  onCleanup(() => { stale = true })
  options.value = null; error.value = ''
  if (!id) return
  try {
    const response = await request.get(`/api/v1/jobs/${id}/postprocessing/options`, {params: {protein_context_id: props.proteinContextId || props.restoreJob?.params.postprocessing?.protein_context_id || undefined}})
    if (stale) return
    options.value = response.data
    emit('referenceAvailability', Boolean(options.value.reference_available))
    if (props.mode === 'submit' && props.restoreJob) {
      const params = props.restoreJob.params.postprocessing
      const restoredInteractions = params.key_interactions.map((rule: any) => ({
        interaction_type: rule.interaction_type,
        match_mode: rule.match_mode,
        residueIndices: rule.residues.map((residue: any) => options.value.residues.findIndex((candidate: any) =>
          ['chain_id', 'residue_name', 'residue_number', 'insertion_code'].every(key => (candidate[key] ?? '') === (residue[key] ?? '')),
        )),
      }))
      if (!validFilters(params.prefilters, prefilterMetrics.value)
        || restoredInteractions.some((rule: any) => !options.value.interaction_types.includes(rule.interaction_type)
          || !['any', 'all'].includes(rule.match_mode) || rule.residueIndices.some((index: number) => index < 0))) {
        throw new Error(translate('platform.restoreTaskUnavailable'))
      }
      if (params.reference_dataset_id) await getBackendDataset(params.reference_dataset_id)
      if (stale) return
      taskName.value = props.restoreJob.params.job_name || props.restoreJob.params.name || ''
      prefilters.value = filterDrafts(params.prefilters)
      interactions.value = restoredInteractions
      referenceId.value = params.reference_dataset_id || ''
      useReference.value = Boolean(referenceId.value)
    }
    if (props.mode === 'submit') moduleSuggestion.consume(route, formValues(), applyDraftChanges)
  } catch (exc) {
    if (stale) return
    restoreFailed.value = Boolean(props.restoreJob)
    error.value = message(exc)
  } finally { if (!stale) restoring.value = false }
  if (props.mode === 'results') await refresh()
}, { immediate: true })
watch(columns, keys => { if (sortBy.value !== 'molecule_id' && !keys.includes(sortBy.value)) setSort('molecule_id', false) }, { deep: true })
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<style scoped>
.tarpass-panel { container-type: inline-size; }
.submit-workspace { display: block; height: auto; overflow: visible; }
.submit-workspace :deep(.workspace-main) { overflow: visible; }
.submit-workspace :deep(.workspace-auxiliary) { display: none; }
.tarpass-results { display: flex; height: 100%; min-height: 0; flex-direction: column; gap: 12px; overflow: hidden; padding: 16px; background: white; }
.tarpass-results > * { flex-shrink: 0; }
.tarpass-results > .workbench-toolbar { margin: -16px -16px 0; }
.tarpass-results > .tarpass-result-content { display: flex; flex: 1 1 0%; min-height: 0; flex-direction: column; gap: 12px; }
.tarpass-result-content > * { flex-shrink: 0; }
.tarpass-result-content > .workbench-table-scroll { flex: 1 1 0%; min-height: 160px; }
.tarpass-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: start; gap: 8px; flex: 0 1 auto; max-height: 38vh; overflow: auto; }
.tarpass-options > details[open], .tarpass-options > div { grid-column: 1 / -1; }
@container (max-width: 650px) { .tarpass-options { grid-template-columns: minmax(0, 1fr); } }
.tarpass-panel :is(select, input[type='number']) { min-height: 36px; border-color: var(--border-default); background: var(--surface); border-radius: 8px; padding: 0.25rem 0.5rem; }
.tarpass-panel button:disabled { cursor: not-allowed; opacity: 0.5; }
.tarpass-panel :is(button, summary, input, select):focus-visible { outline: 2px solid var(--action-primary); outline-offset: 2px; }
.sort-controls { display: inline-flex; gap: 0.2rem; }
.sort-arrow { display: grid; place-items: center; width: 1.5rem; height: 1.5rem; border: 1px solid var(--border-default); border-radius: 0.3rem; background: white; color: var(--text-secondary);  }
.sort-arrow:hover:not(:disabled) { border-color: var(--border-emphasis); color: var(--action-primary); }
.sort-arrow.sort-active { border-color: var(--action-primary); background: var(--selection-bg); color: var(--action-primary); }
.sort-triangle { width: 0; height: 0; border-left: 0.3rem solid transparent; border-right: 0.3rem solid transparent; border-bottom: 0.4rem solid currentColor; }
.sort-triangle-down { transform: rotate(180deg); }
.tarpass-panel th > span { max-width: 10rem; white-space: normal; }
.tarpass-panel th > span > span { flex-shrink: 0; }
.input-section { border: 1px solid var(--border-default); border-radius: 0.5rem; background: white; padding: 0.75rem; }
.input-section h2 { font-size: 0.875rem; font-weight: 600; color: var(--text-primary); }
.submit-panel :is(select, input[type='number']) { min-height: 36px; max-width: 100%; }
.prefilter-row { display: grid; grid-template-columns: minmax(0, 1fr) 4rem minmax(4rem, 6rem) auto auto; align-items: center; gap: 0.5rem; }
@media (max-width: 480px) {
  .prefilter-row { grid-template-columns: minmax(0, 1fr) 4rem; }
  .input-section { padding: 1rem; }
}
</style>
