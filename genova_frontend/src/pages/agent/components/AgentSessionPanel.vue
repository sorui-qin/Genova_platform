<template>
  <main class="agent-session relative flex h-full min-h-0 flex-1 gap-3 overflow-hidden" :class="compact ? 'compact-assistant' : 'p-2 sm:p-4'" @keydown.esc.capture="navigationOpen = false">
    <button v-if="!compact && navigationOpen" type="button" class="absolute inset-0 z-20 bg-slate-900/10" :aria-label="L('关闭会话历史', 'Close session history')" @click="navigationOpen = false" />
    <SessionNavigation v-if="!compact && navigationOpen" class="absolute inset-y-3 left-3 z-30 w-[260px] shadow-xl" :history="history" :current="session?.id" :busy="busy" :switching="switchingSession" @create="create" @restore="restore" @collapse="navigationOpen = false" />
    <WorkspaceLayout ref="workspaceLayout" v-model:open="detailsOpen" resizable :persistent="!compact" :initial-left="58" storage-key="genova-agent-panel-width" :title="t('agent.ui.details')" class="agent-workspace min-w-0 flex-1">
    <section class="agent-conversation flex h-full min-h-0 min-w-0 flex-1 flex-col gap-3 bg-white" :class="compact ? 'p-0' : 'rounded-xl border border-slate-200 p-3 sm:p-5'">
      <header class="conversation-header flex shrink-0 flex-wrap items-center justify-between gap-2 border-b pb-3">
        <div class="flex min-w-0 flex-1 items-center gap-2"><Button v-if="!compact" size="icon" variant="ghost" :aria-label="t('agent.ui.history')" :aria-expanded="navigationOpen" @click="toggleNavigation"><PanelLeft class="h-4 w-4" aria-hidden="true" /></Button><div class="min-w-0"><p class="truncate text-sm font-semibold" :title="session?.goal">{{ session?.goal || t('agent.session.newSession') }}</p><p v-if="session" class="mt-0.5 text-xs text-slate-500">{{ phaseLabel(session.phase) }}</p></div></div>
        <div v-if="!compact" class="flex shrink-0 gap-2"><Button v-if="!taskBlocked && (session?.assets.protein_dataset_id || session?.assets.protein_context_id || session?.assets.prepared_receptor_id)" size="sm" variant="outline" @click="openStructureSelection">{{ t('platform.openStructureWorkspace') }}</Button><Button v-if="!desktopDetails" size="sm" variant="outline" @click="detailsOpen = !detailsOpen"><PanelRight class="h-4 w-4" aria-hidden="true" />{{ t('agent.ui.details') }}</Button><Button size="icon" variant="ghost" :disabled="busy" :aria-label="t('agent.session.newSession')" :title="t('agent.session.newSession')" @click="create"><SquarePen class="h-4 w-4" aria-hidden="true" /></Button></div>
        <Button v-if="compact" variant="ghost" size="sm" :disabled="busy" @click="create">{{ t('agent.session.newSession') }}</Button>
        <Button v-if="session" variant="ghost" size="icon" class="shrink-0 text-slate-400 hover:text-red-700" :aria-label="t('agent.session.deleteSession')" :title="t('agent.session.deleteSession')" :disabled="busy || computing || Boolean(turnRunning)" @click="removeSession"><Trash2 class="h-4 w-4" aria-hidden="true" /></Button>
      </header>
      <StageNavigation v-if="session && !taskBlocked" :stages="stages" :blocker="stageBlocker" @select="selectStage" />


      <div ref="conversation" class="conversation-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain" aria-live="polite" @scroll="onScroll">
        <div class="mx-auto max-w-[880px] space-y-7 pb-5 text-[15px] leading-relaxed">
        <div v-if="!session?.turns.length" class="conversation-empty"><div class="assistant-mark"><Sparkles class="h-6 w-6" aria-hidden="true" /></div><h2>{{ L('从一个研究目标开始', 'Start with a research goal') }}</h2><p>{{ t('agent.session.empty') }}</p></div>
        <Button v-if="session && session.turns.length >= 50" :disabled="busy" variant="outline" @click="loadHistory">{{ t('agent.session.loadEarlier') }}</Button>
        <article v-for="turn in session?.turns || []" :key="turn.id" :data-turn-id="turn.id" class="space-y-3">
          <div v-if="!turn.trigger && (!turn.source || turn.source === 'chat')" class="user-message ml-auto max-w-[85%] rounded-2xl bg-slate-100 px-4 py-3">
            <p class="whitespace-pre-wrap [overflow-wrap:anywhere]">{{ turn.request.display_message || turn.message || intentLabel(turn.intent) }}</p>
            <p v-if="turn.request.attachments?.protein_dataset_id && currentStructureName" class="text-xs text-slate-500">{{ currentStructureName }}</p><details v-if="Object.keys(turn.request.attachments || {}).length" class="text-xs text-slate-500"><summary>{{ t('agent.ui.attachments') }}</summary><p v-for="(id, role) in turn.request.attachments || {}" :key="role">{{ attachmentLabel(String(role)) }} · {{ id }}</p></details>
          </div>
          <p v-else-if="turn.response.error_code" class="text-xs text-slate-500">{{ turn.source === 'visual_editor' ? t('agent.session.visualEditorReturn') : turn.source === 'card' ? t('agent.session.cardAction') : t('agent.session.progress') }}</p>
          <p v-if="turn.response.safety_decision === 'refuse'" role="status" class="text-sm font-semibold text-slate-700" data-testid="safety-refused">{{ L('已拒绝', 'Refused') }}</p>
          <details v-if="['failed', 'interrupted'].includes(turn.status) && turn.response.message" class="text-sm text-slate-500">
            <summary>{{ t('agent.session.incompleteReply') }}</summary><div class="assistant-response prose prose-sm max-w-none break-words" v-html="markdown.render(turn.response.message)" />
          </details>
          <div v-else-if="['task_plan','reading','completion'].includes(turn.trigger || '') && turn.response.message" class="assistant-response prose prose-sm max-w-none break-words" v-html="markdown.render(turn.response.message)" />
          <details v-else-if="turn.response.results && !turn.response.result_presentation"><summary class="cursor-pointer text-sm">{{ t('agent.ui.historyPlan') }} · {{ t('agent.ui.advanced') }}</summary><div class="assistant-response prose prose-sm max-w-none break-words" v-html="markdown.render(turn.response.message || '')" /></details>

          <p v-else-if="turn.response.stopped_by_user" role="status" class="text-sm text-slate-500">{{ L('已停止回复', 'Response stopped') }}</p>
          <p v-else-if="turn.response.investigation_status === 'paused'" class="text-sm">{{ t('agent.session.investigationPaused') }}</p>
          <div v-else-if="turn.response.message" class="assistant-response prose prose-sm max-w-none break-words" v-html="markdown.render(turn.response.message || statusLabel(turn.status))" />
          <template v-if="turn.response.safety_decision !== 'refuse'">
          <section v-if="showStructureActions(turn)" class="turn-action-card" data-testid="structure-actions"><header class="action-card-header"><span class="action-card-icon"><Layers3 class="h-4 w-4" aria-hidden="true" /></span><h3>{{ L('当前结构与位点', 'Current structure and site') }}</h3><span class="action-state">{{ L('相关操作', 'Related actions') }}</span></header><div class="action-card-body flex flex-wrap gap-2"><Button size="sm" variant="outline" :disabled="busy || computing || Boolean(turnRunning)" @click="openStructureSelection">{{ t('platform.openStructureWorkspace') }}</Button><Button size="sm" :disabled="busy || computing || Boolean(turnRunning) || !session?.assets.protein_context_id" @click="showGenerationPlan">{{ L('使用当前输入创建方案', 'Create a plan with current inputs') }}</Button></div></section>
          <section v-if="turn.id === nextActionTurnId" class="turn-action-card action-pending" data-testid="next-step-action"><header class="action-card-header"><span class="action-card-icon"><SquarePen class="h-4 w-4" aria-hidden="true" /></span><h3>{{ L('下一步', 'Next step') }}</h3><span class="action-state needs-action">{{ L('待处理', 'Needs action') }}</span></header><div class="action-card-body flex flex-wrap gap-2"><Button v-if="session?.phase === 'ready_for_planning'" size="sm" :disabled="busy || Boolean(turnRunning)" @click="showGenerationPlan">{{ L('创建生成 / 优化方案', 'Create a generation / optimization plan') }}</Button><Button v-else size="sm" :disabled="busy || computing || Boolean(turnRunning)" @click="openStructureSelection">{{ t('platform.openStructureWorkspace') }}</Button></div></section>
          <section v-for="proposal in proposalsForTurn(turn.id)" :key="proposal.id" :id="`action-${proposal.id}-${turn.id}`" tabindex="-1" class="turn-action-card" :class="{ 'action-pending': proposalNeedsAction(proposal) }" data-testid="turn-action-card" :data-proposal-id="proposal.id">
            <header class="action-card-header"><span class="action-card-icon"><ClipboardCheck class="h-4 w-4" aria-hidden="true" /></span><h3>{{ proposalTitle(proposal) }}</h3><span class="action-state" :class="{ 'needs-action': proposalNeedsAction(proposal) }">{{ proposalStateLabel(proposal) }}</span></header>
            <div v-if="proposal.id === session?.task_plan?.proposal_id && activeTaskPlan && !draftOpen && proposalAnchors[proposal.id] === turn.id" :ref="el => setProposalTarget(proposal.id, turn.id, el)" class="action-card-body" />
            <div v-else-if="inlineProposal(proposal) && proposalAnchors[proposal.id] === turn.id" :ref="el => setProposalTarget(proposal.id, turn.id, el)" class="action-card-body" />
            <div v-else class="action-card-body space-y-3">
              <dl v-if="proposalGeneration(proposal)" class="action-summary"><div><dt>{{ t('agent.session.model') }}</dt><dd class="uppercase">{{ proposalGeneration(proposal).engine || proposal.payload.task_plan?.workflow?.generator }}</dd></div><div v-if="proposalGeneration(proposal).num_molecules || proposalGeneration(proposal).target_num_molecules"><dt>{{ t('agent.session.generationCount') }}</dt><dd>{{ proposalGeneration(proposal).target_num_molecules || proposalGeneration(proposal).num_molecules }}</dd></div></dl>
              <dl v-else-if="proposal.payload.task_plan?.stage === 'postprocessing'" class="action-summary"><div><dt>{{ L('评价与筛选', 'Evaluation & Screening') }}</dt><dd>TarPass</dd></div><div><dt>{{ L('前筛条件', 'Prefilters') }}</dt><dd>{{ proposal.payload.task_plan.workflow?.postprocessing?.prefilters?.length || L('无', 'None') }}</dd></div></dl>
              <div class="flex flex-wrap gap-2"><Button v-if="proposalNeedsAction(proposal)" size="sm" @click="locateProposal(proposal)">{{ L('前往当前操作卡片', 'Go to current action card') }}</Button><Button v-if="proposal.workflow?.generation?.job_id" size="sm" variant="outline" @click="openResults(proposal.workflow.generation.job_id)">{{ t('agent.session.viewGeneration') }}</Button><Button v-if="proposal.workflow?.postprocessing?.job_id || proposal.kind === 'retry_postprocessing' && proposal.execution.job_id" size="sm" variant="outline" @click="openResults(proposal.workflow?.postprocessing?.job_id || proposal.execution.job_id)">{{ t('agent.session.viewTarpass') }}</Button></div>
            </div>
          </section>
          <section v-if="!taskBlocked && draftOpen && turn.id === draftActionTurnId" tabindex="-1" class="turn-action-card action-pending" data-testid="workflow-draft-action"><header class="action-card-header"><span class="action-card-icon"><SquarePen class="h-4 w-4" aria-hidden="true" /></span><h3>{{ L('编辑生成 / 优化方案', 'Edit generation / optimization plan') }}</h3></header><div :ref="setDraftTarget" class="action-card-body" /></section>
          <ResultDetails v-for="(result, index) in turn.response.result_queries?.length ? turn.response.result_queries : turn.response.results ? [turn.response.results] : []" :key="index" :result="result" :specs="spec?.metrics" />
          <div v-for="card in resultCardsForTurn(turn.id)" :key="card.jobId" class="space-y-2"><JobResultCard :job-id="card.jobId" :title="card.postprocessing ? t('agent.session.viewTarpass') : t('agent.session.viewGeneration')" :postprocessing="card.postprocessing" :recovery="syncRecovery" @open="openResults(card.jobId)" /><div v-if="card.postprocessing && canActOnTurn(turn)" class="flex flex-wrap gap-2"><Button variant="outline" :disabled="busy || Boolean(turnRunning)" @click="analyzeResults">{{ L('分析此评价任务', 'Analyze this evaluation run') }}</Button><Button variant="outline" @click="openResults(card.jobId)">{{ L('选择分子继续优化', 'Select molecules for optimization') }}</Button></div></div>
          <DiagnosticEvidence v-if="turn.response.diagnostic_evidence || turn.response.diagnostic_notes" :evidence="turn.response.diagnostic_evidence || {}" :notes="turn.response.diagnostic_notes" />
          <p v-if="turn.response.warnings?.includes('provider_usage_mismatch')" class="text-sm text-amber-800">{{ t('agent.warningMessages.provider_usage_mismatch') }}</p>
          <p v-if="turn.response.warnings?.includes('budget_exceeded_after_completion')" class="text-sm text-amber-800">{{ t('agent.warningMessages.budget_exceeded_after_completion') }}</p>
          <div v-if="turn.response.error_code" role="alert" class="assistant-response rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <p>{{ errorText(turn.response) }}</p>
            <p v-if="turn.response.status_code">HTTP {{ turn.response.status_code }}</p>
            <p v-if="turn.response.recovery_action">{{ recoveryText(turn.response) }}</p>
            <details class="mt-2 text-xs"><summary>{{ t('agent.session.errorDetails') }}</summary><p>Trace: {{ turn.response.trace_id || turn.id }}</p><p>{{ t('agent.errorCode') }}: {{ turn.response.error_code }}</p><p>{{ t('agent.session.turnId') }}: {{ turn.id }}</p><p v-if="turn.response.error_message && turn.response.error_message !== errorText(turn.response)" class="whitespace-pre-wrap break-words">{{ turn.response.error_message }}</p><p v-if="turn.response.error_stage">{{ t('agent.session.failureStage') }}: {{ stageLabel(turn.response.error_stage) }}</p><p v-if="turn.response.error_source">{{ t('agent.errorSource') }}: {{ t('agent.errorSources.' + turn.response.error_source) }}</p></details>
          </div>
          <details v-if="turn.id === latestTurn?.id && (turn.response.tools?.length || turn.response.diff?.length || turn.response.evidence_details?.length)" class="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-xs text-slate-600">
            <summary class="cursor-pointer font-medium">{{ t('agent.session.toolProgress') }}<span v-if="turn.response.tools?.length" class="ml-2 text-slate-400">{{ turn.response.tools.length }}</span></summary>
            <div class="mt-3 space-y-3 border-t border-slate-200 pt-3">
              <div v-for="(step, index) in turn.response.tools || []" :key="index" class="border-l-2 pl-3" :class="step.status === 'failed' ? 'border-red-300 text-red-700' : 'border-slate-300'"><p>{{ toolLabel(step.tool) }} · {{ statusLabel(step.status) }}</p><p v-if="step.error_code || step.warning_code">{{ errorText(step) }}</p><p v-if="step.recovery_action">{{ recoveryText(step) }}</p><span v-if="step.error_code">{{ step.error_code }}</span></div>
              <details v-if="turn.response.diff?.length"><summary class="cursor-pointer">{{ t('agent.session.changeDetails') }}</summary><pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2">{{ JSON.stringify(turn.response.diff, null, 2) }}</pre></details>
              <div v-if="turn.response.evidence_details?.length" class="space-y-1"><p class="font-medium">{{ t('agent.session.sourceReferences') }}</p><p v-for="evidence in turn.response.evidence_details" :key="evidence.chunk_id" class="break-all text-slate-500">{{ evidence.source_id }} · {{ evidence.section }} · {{ evidence.protocol_version }}</p></div>
            </div>
          </details>
          <p v-if="turn.response.missing_requirements?.length && turn.id === clarificationActionTurnId && pendingRequirements.length && !session?.input_selection" class="text-sm text-amber-800">{{ structuralRequirements.length ? t('agent.ui.structureCardHint') : requirements.length ? `${t('agent.session.needsInput')} · ${t('agent.session.clarificationHint')}` : t('agent.session.missing') + pendingRequirements.join(', ') }}</p>
          <section v-if="canContinueTurn(turn) && (turn.can_resume || canRetry(turn)) && turn.response.error_code !== 'INPUT_CHANGED'" class="turn-action-card action-pending"><header class="action-card-header"><RotateCcw class="h-4 w-4 text-blue-600" aria-hidden="true" /><h3>{{ L('继续这次请求', 'Continue this request') }}</h3></header><div class="action-card-body"><Button v-if="turn.can_resume" :disabled="busy || turnRunning" size="sm" @click="resume(turn)">{{ turn.response.committed_effects?.length ? L('继续剩余步骤','Continue remaining steps') : L('重试这次请求','Retry this request') }}</Button><Button v-else :disabled="busy || turnRunning" size="sm" @click="retry(turn)">{{ turn.response.review_pending ? L('重试检查','Retry check') : t('agent.session.retryTurn') }}</Button></div></section>
          <section v-if="turn.response.error_code === 'INPUT_CHANGED' && turn.response.committed_effects?.length" class="turn-action-card"><div class="action-card-body"><Button variant="outline" size="sm" @click="focusCurrentPlan">{{ L('查看当前方案','View current plan') }}</Button></div></section>
          <template v-if="turn.id === clarificationActionTurnId">
            <InputSelectionCard v-if="session?.input_selection && !Object.keys(pendingFiles).length && !draftContext" :selection="session.input_selection" :disabled="busy || Boolean(turnRunning) || computing || Boolean(pendingRequest)" @select="confirmInputFile" @upload="uploadRequestedInput" @choose="loadAttachments" />
            <section v-if="structuralRequirements.length && !session?.input_selection" class="space-y-3 rounded-xl border border-blue-200 bg-blue-50/60 p-4 sm:p-5" data-testid="structure-input-card">
              <h3 class="font-semibold">{{ t('agent.ui.completeStructure') }}</h3>
              <p v-if="currentStructureName" class="text-sm">{{ currentStructureName }}</p>
              <p v-if="session?.confirmed_fields.reference_mode" class="text-sm">{{ t('agent.session.referenceMode') }} · {{ t('platform.' + (referenceModeLabels[session.confirmed_fields.reference_mode.value] || 'referenceMethod')) }}</p>
              <p class="text-sm text-slate-600">{{ t('agent.ui.structureNeeded') }}{{ structureLabels.join('、') }}</p>
              <p class="text-xs text-slate-500">{{ t('agent.ui.structureScope') }}</p>
              <div class="flex flex-wrap gap-2"><Button :disabled="busy || turnRunning || computing" @click="openStructureSelection">{{ session?.assets.protein_dataset_id || session?.assets.protein_context_id || session?.assets.prepared_receptor_id ? t('agent.ui.openStructure') : t('agent.session.uploadFile') }}</Button><Button variant="outline" :disabled="busy || turnRunning || computing" @click="addOpen = true; loadContexts()">{{ t('agent.session.chooseContext') }}</Button></div>
            </section>
            <ClarificationForm v-if="requirements.length" v-model:answers="clarificationAnswers" :requirements="requirements" :fields="clarificationFields" :generators="availableGenerators" :busy="busy" :turn-running="Boolean(turnRunning)" :pending-request="Boolean(pendingRequest)" :can-submit-clarification="canSubmitClarification" :context-ready="Boolean(session?.assets.protein_context_id)" :confirmed-delete-edit="confirmedDeleteEdit" @submit="submitClarification" @open-delete="openEditor('delete')" />
          </template>
          <section v-if="turn.status === 'needs_input' && turn.response.missing_requirements?.length && (turn.id !== clarificationActionTurnId || !pendingRequirements.length)" class="turn-action-card action-history"><header class="action-card-header"><Check class="h-4 w-4 text-slate-400" aria-hidden="true" /><h3>{{ t('agent.session.completeInformation') }}</h3><span class="action-state">{{ pendingRequirements.length ? L('已更新', 'Superseded') : L('已结束', 'Closed') }}</span></header></section>

          </template>
        </article>
        <section v-if="session?.workflow?.error" role="alert" class="space-y-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm"><p>{{ errorText(session.workflow.error) }}</p><details v-if="session.workflow.error.message || session.workflow.error.error_message"><summary>{{ t('agent.session.errorDetails') }}</summary><p class="whitespace-pre-wrap break-words">{{ session.workflow.error.message || session.workflow.error.error_message }}</p></details><Button v-if="session.workflow.generation?.status === 'succeeded' && session.workflow.postprocessing?.status === 'failed'" size="sm" variant="outline" :disabled="busy" @click="sendCommand('retry_postprocessing')">{{ L('复用生成结果，重试评价','Retry evaluation with existing generation') }}</Button><Button v-else size="sm" variant="outline" :disabled="busy" @click="openNewDraft">{{ L('修改方案并重新运行','Revise plan and run again') }}</Button></section>
        <section v-if="newWorkflowPlan?.generator === 'delete' && !session?.workflow && !draftOpen" class="space-y-2 rounded-lg border p-3"><h3 class="text-sm font-semibold">{{ L('所选分子的片段优化','Fragment optimization of the selected molecule') }}</h3><p v-if="computing" role="status" class="text-sm">{{ L('正在准备模型输入，完成后可编辑片段。','Model inputs are being prepared. Fragment editing will be available when ready.') }}</p><Button v-else size="sm" variant="outline" :disabled="busy" @click="openEditor('delete')">{{ t('agent.session.deleteVisualEdit') }}</Button></section>
        <section v-if="!taskBlocked && (pendingPose || session?.pose_preparation)" class="space-y-3 rounded-xl border border-blue-200 bg-blue-50/30 p-4">
          <h3 class="font-semibold">{{ L('为所选分子准备 DELETE 姿态','Prepare the selected molecule for DELETE') }}</h3>
          <PosePreparationCard v-if="pendingPose" :draft="pendingPose" :context-id="session?.assets.protein_context_id" :busy="busy" @approve="approvePosePreparation" @recheck="recheckPosePreparation" />
          <template v-else-if="session?.pose_preparation"><p role="status" class="text-sm">TarPass · {{ statusLabel(session.pose_preparation.status) }}</p><Button v-if="session.pose_preparation.status === 'succeeded'" :disabled="busy" @click="continuePoseEditing">{{ L('继续片段编辑','Continue fragment editing') }}</Button><Button variant="outline" :disabled="busy" @click="openResults(session.pose_preparation.job_id)">{{ L('查看姿态任务','View pose preparation') }}</Button></template>
        </section>

        <section v-if="!turnRunning && (taskBlocked || session?.phase === 'cancel_requested')" role="status" class="rounded-lg bg-slate-100 px-3 py-2">
          <div class="flex items-center gap-2 text-sm font-semibold text-slate-700"><CircleStop class="h-4 w-4" aria-hidden="true" />{{ taskBlocked ? L('后续步骤已阻断', 'Further steps blocked') : computationLabel }}</div>
        </section>
        <section v-else-if="computing || turnRunning" role="status" class="rounded-lg bg-blue-50 px-3 py-2">
          <div class="flex items-center gap-2 text-sm font-semibold text-blue-900"><LoaderCircle class="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />{{ turnRunning ? t(session?.turns.some(turn => turn.status === 'running') ? 'agent.session.processingRequest' : 'agent.session.requestQueued') : computationLabel }}</div>
        </section>
        </div>
      </div>
      <Button v-if="hasNewMessages" size="sm" variant="outline" @click="scrollToLatestReply">{{ t('agent.session.newMessages') }}</Button>
      <form class="agent-composer mx-auto w-full max-w-[880px] shrink-0 space-y-2 rounded-xl border bg-slate-50 p-3" @submit.prevent="submitMessage()">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <Button v-if="!taskBlocked" type="button" variant="outline" size="sm" :disabled="busy || computing || turnRunning" :aria-expanded="addOpen" :class="addOpen ? 'border-blue-200 bg-blue-50 text-blue-700' : 'bg-white text-slate-600'" @click="addOpen = !addOpen"><Paperclip aria-hidden="true" />{{ t('agent.session.add') }}</Button>
          <span v-for="(file, role) in pendingFiles" :key="role" class="inline-flex max-w-full items-center gap-2 rounded-lg border border-slate-200 bg-white py-1 pl-2.5 pr-1 text-slate-700">
            <FileText class="h-4 w-4 shrink-0 text-blue-600" aria-hidden="true" />
            <span class="min-w-0"><span class="block max-w-[min(20rem,55vw)] truncate text-xs font-medium" :title="file.name">{{ file.name }}</span><span v-if="!file.datasetId" class="block text-[11px] text-slate-500">{{ L('待上传', 'Pending upload') }}</span><span v-if="/\.(cif|mmcif)$/i.test(file.name)" class="block text-[11px] text-slate-500">{{ t('agent.session.cifConversion') }}</span></span>
            <button type="button" class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:opacity-50" :aria-label="`${t('agent.session.remove')} ${file.name}`" :disabled="busy" @click="editFailedRequest(); delete pendingFiles[role]"><X class="h-3.5 w-3.5" aria-hidden="true" /></button>
          </span>
          <span v-if="draftContext" class="inline-flex max-w-full items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 py-1 pl-2.5 pr-1 text-blue-800">
            <Layers3 class="h-4 w-4 shrink-0" aria-hidden="true" />
            <span class="min-w-0 max-w-[min(20rem,55vw)] truncate text-xs font-medium" :title="contexts.find(c => c.id === draftContext)?.name">{{ contexts.find(c => c.id === draftContext)?.name || t('agent.session.contextSelected') }}</span>
            <button type="button" class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-blue-400 hover:bg-blue-100 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 disabled:opacity-50" :aria-label="`${t('agent.session.remove')} ${contexts.find(c => c.id === draftContext)?.name || t('agent.session.contextSelected')}`" :disabled="busy" @click="editFailedRequest(); draftContext = ''"><X class="h-3.5 w-3.5" aria-hidden="true" /></button>
          </span>
        </div>
        <fieldset v-if="addOpen && !taskBlocked" :aria-label="t('agent.session.uploadFile')" class="space-y-3 rounded-xl border border-slate-200 bg-white p-3 text-sm" :disabled="busy || computing || turnRunning">
          <div class="flex items-center justify-between gap-2">
            <span class="flex items-center gap-2 font-medium text-slate-700"><Paperclip class="h-4 w-4 text-slate-400" aria-hidden="true" />{{ t('agent.session.uploadFile') }}</span>
            <Button type="button" variant="ghost" size="icon" class="h-6 w-6 text-slate-400 hover:text-slate-700" :aria-label="t('agent.session.closeAttachments')" @click="addOpen = false"><X aria-hidden="true" /></Button>
          </div>
          <div class="flex flex-wrap gap-2">
            <input ref="attachmentInput" type="file" accept=".pdb,.cif,.mmcif,.sdf,.mol,.mol2" class="hidden" @change="stageFile" />
            <Button type="button" size="sm" variant="outline" class="h-10 min-w-0 flex-1 basis-40 justify-start bg-slate-50/50 px-3 text-slate-700 hover:bg-slate-100" @click="attachmentInput?.click()"><Upload class="text-slate-500" aria-hidden="true" /><span class="truncate">{{ t('agent.session.uploadLocalFile') }}</span></Button>
            <Button type="button" size="sm" variant="outline" class="h-10 min-w-0 flex-1 basis-40 justify-start bg-slate-50/50 px-3 text-slate-700 hover:bg-slate-100" @click="loadAttachments"><Files class="text-slate-500" aria-hidden="true" /><span class="truncate">{{ t('agent.session.fromDataCenter') }}</span></Button>
            <AgentContextPicker v-model:open="contextPickerOpen" :model-value="draftContext" :selected-context="contexts.find(c => c.id === draftContext)" :disabled="busy || computing || Boolean(turnRunning)" @select="selectListedContext" />
          </div>
        </fieldset>
        <Button v-if="session && !taskBlocked && Object.keys(pendingFiles).length" type="button" variant="outline" @click="saveStructuredInputs">{{ t('agent.session.saveInputs') }}</Button>
        <Button v-if="session && !taskBlocked && draftContext" type="button" variant="outline" @click="sendCommand('bind', {protein_context_id:draftContext})">{{ t('agent.session.saveContextBinding') }}</Button>
        <div v-if="uploadingAttachments" role="status" class="flex items-center justify-between gap-2 text-sm">
          <span>{{ cancelingAttachments ? L('正在确认上传结果…', 'Confirming upload result…') : L('正在上传附件…', 'Uploading attachments…') }}</span>
          <Button type="button" variant="outline" size="sm" :disabled="cancelingAttachments" @click="cancelAttachmentPreparation">{{ L('取消上传', 'Cancel upload') }}</Button>
        </div>
        <p v-if="uploadNotice" role="status" class="text-sm text-slate-600">{{ uploadNotice }}</p>
        <p v-if="error" role="alert" class="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{{ error }}</p>
        <p v-if="taskBlocked" class="text-xs text-slate-600">{{ compact ? L('若要开展独立的正常研究，请在主会话中发起新任务。', 'Start a new task in the main conversation for independent legitimate research.') : L('当前研究任务已阻断。可以咨询安全问题，或输入独立的正常研究目标并新建任务。', 'This research task is blocked. Ask a safety question, or enter a distinct legitimate goal and start a new task.') }}</p>
        <textarea ref="composer" v-model="message" :disabled="draftLoading" :aria-label="t('agent.session.message')" class="max-h-40 !min-h-0 h-14 w-full resize-none rounded-lg border-0 bg-transparent p-2 text-sm focus:ring-0" rows="2" @input="editFailedRequest(); resizeComposer()" @keydown="composerKeydown" :placeholder="t('agent.session.placeholder')" maxlength="4000" />
        <div class="flex items-center justify-between gap-2"><span class="text-xs text-slate-500">{{ turnRunning ? t('agent.ui.replyBusy') : '' }}</span><Button v-if="turnRunning" type="button" variant="outline" :disabled="stoppingTurn" @click="stopCurrentTurn">{{ stoppingTurn ? L('正在停止', 'Stopping') : L('停止回复', 'Stop response') }}</Button><Button v-if="!turnRunning && taskBlocked && !compact" type="button" variant="outline" :disabled="busy || draftLoading || Boolean(pendingRequest) || !message.trim()" @click="submitMessage(undefined, undefined, 'new_task')">{{ L('以此目标新建研究任务', 'Start a new research task') }}</Button><Button v-if="!turnRunning" type="submit" :disabled="initializing || draftLoading || busy || (!message.trim() && !Object.keys(pendingFiles).length && !draftContext && !pendingRequest)">{{ pendingRequest ? t('agent.session.retrySend') : t('agent.session.send') }}</Button></div>
      </form>
      <p v-if="exportNote" role="status" class="text-sm">{{ exportNote }}</p>

    </section>
    <template #auxiliary><div class="agent-details space-y-4">
      <section v-if="!session" class="details-empty"><Layers3 class="h-8 w-8" aria-hidden="true" /><h3>{{ L('任务工作区', 'Task workspace') }}</h3><p>{{ L('输入、方案与运行结果会显示在这里。', 'Inputs, plans and results appear here.') }}</p></section>
      <section v-else class="task-overview"><div class="flex items-center justify-between gap-3"><span class="text-xs font-medium text-slate-500">{{ L('当前任务', 'Current task') }}</span><span class="status-badge status-active">{{ phaseLabel(session.phase) }}</span></div><p class="mt-3 text-sm font-medium leading-relaxed text-slate-800 [overflow-wrap:anywhere]">{{ session.goal }}</p></section>
      <div v-if="session?.last_error === 'SESSION_RECONCILIATION_FAILED'" role="alert" class="space-y-2 rounded border p-3 text-sm"><p>{{ L('状态同步失败，已有任务和结果已保留。','State synchronization failed. Existing tasks and results are preserved.') }}</p><Button :disabled="busy || Boolean(turnRunning)" @click="sendCommand('retry_session')">{{ L('重试状态同步','Retry synchronization') }}</Button></div>
      <div v-if="!taskBlocked && session?.last_error === 'SAFETY_ASSESSMENT_REQUIRED'" role="alert" class="rounded border p-3 text-sm">{{ L('此历史任务需要明确研究目标后才能继续。请在对话中补充目标，已有任务和结果已保留。','Clarify the research goal in the conversation before continuing this historical task. Existing tasks and results are preserved.') }}</div>
      <div v-if="specLoadError" role="alert" class="space-y-2 text-sm text-red-700"><p>{{ specLoadError }}</p><Button variant="outline" :disabled="busy" @click="retrySpecs">{{ L('重新加载参数','Reload parameters') }}</Button></div>
      <ContextResultCard v-if="!taskBlocked && (session?.context_spec || session?.prepared_receptor)" :context="session.context_spec" :prepared="session.prepared_receptor" :filename="currentStructureName" :disabled="busy || computing || Boolean(turnRunning)" @open="openStructureSelection" @plan="showGenerationPlan" />
      <div v-if="!taskBlocked && draftOpen && taskPlanChangedDuringDraft && session?.task_plan" role="alert" class="space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
        <p>{{ L('服务端已进入新的方案阶段，你未保存的编辑仍保留。','The server has moved to a new plan stage. Your unsaved edits are preserved.') }}</p>
        <Button size="sm" variant="outline" :disabled="busy" @click="showLatestTaskPlan">{{ L('查看最新阶段','Show latest stage') }}</Button>
      </div>
      <section v-if="!taskBlocked && (draftOpen && draftActionTarget || activeTaskPlan && taskPlanActionTarget)" class="current-plan-summary space-y-3"><div class="flex items-center justify-between gap-2"><h3 class="text-sm font-semibold">{{ L('当前方案', 'Current plan') }}</h3><span class="text-xs text-slate-500">{{ draftOpen ? L('编辑中', 'Editing') : taskPlanStateLabel(session!.task_plan!.state) }}</span></div><dl v-if="summaryPlan?.workflow" class="action-summary"><div><dt>{{ t('agent.session.model') }}</dt><dd class="uppercase">{{ summaryPlan.workflow.generator }}</dd></div><div v-if="summaryPlan.workflow.generation?.num_molecules || summaryPlan.workflow.generation?.target_num_molecules"><dt>{{ t('agent.session.generationCount') }}</dt><dd>{{ summaryPlan.workflow.generation.target_num_molecules || summaryPlan.workflow.generation.num_molecules }}</dd></div></dl><Button size="sm" variant="outline" class="w-full" @click="focusCurrentPlan"><ArrowLeft class="h-4 w-4" aria-hidden="true" />{{ L('在对话卡片中编辑', 'Edit in conversation card') }}</Button></section>
      <Teleport :to="draftActionTarget || 'body'" :disabled="!draftActionTarget"><WorkflowDraftCard v-if="!taskBlocked && draftOpen" :key="session?.id + String(draftRevision)" :plan="newWorkflowPlan" :context-id="session?.assets.protein_context_id || ''" :version="draftRevision" :generators="availableGenerators" :busy="busy" :context-preparing="computing" :edit-spec="session?.confirmed_fields.delete_edit_spec_id?.value" :edit-mode="session?.delete_edit?.mode" @dirty="newDraftDirty = $event" @draft="newWorkflowDraft = $event" @save="saveNewDraft" @edit-delete="openEditor('delete')" @open-context="openStructureSelection" /></Teleport>
      <Teleport :to="taskPlanActionTarget || 'body'" :disabled="!taskPlanActionTarget"><TaskPlanCard v-if="!draftOpen && session?.task_plan && activeTaskPlan" :key="session.id + String(session.research_task_id)" :plan="session.task_plan" :generators="availableGenerators" :datasets="datasets" :metrics="spec?.metrics || {}" :interaction-types="spec?.interaction_types || []" :residues="spec?.residues || []" :edit-spec="session.confirmed_fields.delete_edit_spec_id?.value" :edit-mode="session.delete_edit?.mode" :busy="busy || computing || (Boolean(turnRunning) && !['paused','blocked'].includes(session.task_plan.state))" :context-preparing="session.phase === 'preparing'" @draft="taskPlanDraft = $event" @approve="approveTaskPlan" @save="saveTaskPlan" @review-preparation="reviewTaskPreparation" @pause="sendCommand('pause_task')" @resume="sendCommand('resume_task')" @skip="skipPostprocessing" @edit-delete="openEditor('delete')" /></Teleport>
      <template v-for="proposal in [...(session?.proposals || [])].reverse().filter(p => p.kind !== 'task_plan' && isCurrentProposal(p) && (!session?.task_plan || p.kind === 'prepare'))" :key="proposal.id">
      <Button v-if="proposalActionTargets[proposal.id]" variant="outline" class="w-full justify-between" @click="locateProposal(proposal)">{{ proposalTitle(proposal) }}<ArrowLeft class="h-4 w-4" aria-hidden="true" /></Button>
      <Teleport :to="proposalActionTargets[proposal.id] || 'body'" :disabled="!proposalActionTargets[proposal.id]">
      <article :id="`proposal-${proposal.id}`" class="proposal-content space-y-3" :class="{ 'rounded-xl border bg-white p-4': !proposalActionTargets[proposal.id] }">
        <details :open="proposal.status === 'pending'" class="space-y-3"><summary class="cursor-pointer">
        <h3 v-if="proposal.kind === 'prepare'" class="font-semibold">{{ intentLabel(proposal.kind) }} · {{ statusLabel(proposal.status) }}</h3>
        <h3 v-else class="flex flex-wrap items-center justify-between gap-2 font-semibold">{{ intentLabel(proposal.kind) }}<span class="rounded-full px-2.5 py-1 text-xs font-medium" :class="proposal.status === 'approved' ? 'bg-emerald-50 text-emerald-700' : proposal.status === 'pending' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-600'">{{ statusLabel(proposal.status) }}</span></h3>
        </summary>
        <PreparationSummary v-if="proposal.kind === 'prepare'" :payload="proposal.payload" :pending="proposal.status === 'pending'" :filename="fileNames[proposal.payload.protein_file_id]" />
        <Button v-if="proposal.kind === 'prepare'" variant="outline" :disabled="proposal.job_status === 'succeeded' && (busy || Boolean(turnRunning) || computing)" @click="openPreparation(proposal)">{{ t(proposal.job_status === 'succeeded' && proposal.execution.prepared_receptor_id ? 'agent.session.defineSite' : 'agent.ui.reviewPreparation') }}</Button>
        <dl v-if="proposal.kind === 'workflow'" class="grid gap-3 rounded-lg bg-slate-50 p-3 text-sm sm:grid-cols-2"><div><dt class="text-xs text-slate-500">{{ t('agent.session.model') }}</dt><dd class="mt-1 font-semibold uppercase text-slate-800">{{ proposal.payload.effective_generation.engine }}</dd></div><div><dt class="text-xs text-slate-500">{{ t('agent.session.generationCount') }}</dt><dd class="mt-1 font-semibold text-slate-800">{{ proposal.payload.effective_generation.num_molecules || proposal.payload.effective_generation.target_num_molecules }} {{ t('agent.session.candidates') }}</dd></div></dl>
        <PostprocessingDraftCard v-if="proposal.kind === 'postprocessing'" :initial="proposal.payload" :source-job-id="proposal.payload.postprocessing?.source_job_id || postprocessingSourceJobId" :context-id="session?.assets.protein_context_id" :datasets="datasets" :metrics="spec?.metrics || {}" :interaction-types="spec?.interaction_types || []" :residues="spec?.residues || []" :busy="busy" @dirty="inlineDirty[proposal.id] = $event" @save="savePostprocessingDraft" @skip="skipPostprocessing" />
        <div v-if="proposal.kind === 'workflow'" class="flex flex-wrap items-center gap-3 text-sm"><span>{{ t('agent.ui.planVersion', {version:proposal.payload.plan_version}) }}</span><details v-if="isCurrentProposal(proposal)" class="w-full rounded-lg border p-3"><summary class="cursor-pointer font-medium">{{ t('agent.ui.editPlan') }}</summary><WorkflowParameters :key="proposal.action_hash" class="mt-3" :proposal="proposal" :filters="proposal.workflow?.prefilter_conditions || session?.workflow?.prefilter_conditions || []" :generators="availableGenerators" :edit-spec="session?.confirmed_fields.delete_edit_spec_id?.value" :edit-mode="session?.delete_edit?.mode" :busy="busy || Boolean(turnRunning)" :show-actions="true" :initial-draft="editorDrafts.workflow?.proposalId === proposal.id ? editorDrafts.workflow?.changes : undefined" @dirty="inlineDirty[proposal.id] = $event" @draft="workflowLocalDraft = $event" @save="(patch, version) => saveWorkflow(patch, version, proposal)" /><Button size="sm" variant="ghost" :disabled="busy" @click="saveParameterDraft(proposal)">{{ L('保存参数草稿','Save parameter draft') }}</Button></details><Button v-if="proposal.payload.effective_generation?.engine === 'delete' && isCurrentProposal(proposal)" variant="outline" :disabled="busy || turnRunning" @click="openEditor('delete')">{{ t('agent.session.deleteVisualEdit') }}</Button></div>
        <details><summary class="cursor-pointer text-sm">{{ t('agent.ui.advanced') }}</summary><pre class="max-h-60 overflow-auto whitespace-pre-wrap text-xs">{{ JSON.stringify({proposal_id:proposal.id,input_revision:proposal.input_revision,payload:proposal.payload,action_hash:proposal.action_hash}, null, 2) }}</pre></details>
        <p v-if="inlineDirty[proposal.id]" class="text-sm text-amber-800">{{ t('agent.ui.dirtyApproval') }}</p><Button v-if="proposal.kind !== 'prepare' && isCurrentProposal(proposal) && !session?.task_plan" :disabled="busy || turnRunning || Boolean(editorProposal) || inlineDirty[proposal.id]" @click="approve(proposal)">{{ t('agent.session.approve') }}</Button>
        </details>
        <p v-if="proposal.job_status" class="text-sm" role="status">{{ proposal.kind === 'prepare' ? t('agent.session.preparationStatus') : 'TarPass: ' }}{{ statusLabel(proposal.job_status) }}</p>
        <p v-if="proposal.workflow" class="rounded-lg bg-blue-50 p-3 text-sm text-blue-800" role="status">{{ t('agent.session.generationStatus') }}{{ generationStepLabel(proposal.workflow.generation?.status) }}<span v-if="proposal.workflow.postprocessing?.status !== 'skipped'"> · TarPass: {{ workflowStepLabel(proposal.workflow.postprocessing?.status, proposal.workflow.generation?.status) }}</span></p>
        <div class="flex flex-wrap gap-3 text-sm text-blue-700">


          <Button v-if="proposal.workflow?.generation?.job_id" size="sm" variant="outline" @click="openResults(proposal.workflow.generation.job_id)">{{ t('agent.session.viewGeneration') }}</Button>
          <Button v-if="proposal.workflow?.postprocessing?.job_id" size="sm" variant="outline" @click="openResults(proposal.workflow.postprocessing.job_id)">{{ t('agent.session.viewTarpass') }}</Button>
          <Button v-if="!hasCandidateResults(proposal.id) && proposal.kind === 'retry_postprocessing' && proposal.job_status === 'succeeded' && proposal.execution.job_id" size="sm" variant="outline" @click="openResults(proposal.execution.job_id)">{{ t('agent.session.viewTarpass') }}</Button>
        </div>
      <div v-if="proposal.workflow?.error" role="alert" class="rounded-lg bg-red-50 p-3 text-sm text-red-800"><p>{{ errorText(proposal.workflow.error) }}</p><details v-if="proposal.workflow.error.message || proposal.workflow.error.error_message"><summary>{{ t('agent.session.errorDetails') }}</summary><p class="whitespace-pre-wrap break-words">{{ proposal.workflow.error.message || proposal.workflow.error.error_message }}</p></details></div>

      </article>
      </Teleport></template>
      <section v-if="currentResultLinks.length" class="space-y-2 border-t pt-3"><h3 class="font-semibold">{{ L('当前结果', 'Current results') }}</h3><div class="flex flex-wrap gap-2"><Button v-for="card in currentResultLinks" :key="card.jobId" variant="outline" size="sm" @click="openResults(card.jobId)">{{ card.postprocessing ? t('agent.session.viewTarpass') : t('agent.session.viewGeneration') }}</Button></div></section>
      <details v-if="session?.candidate_sets.length" class="space-y-3 border-t pt-3" open><summary class="cursor-pointer font-semibold">{{ L('已保存的候选集合', 'Saved candidate sets') }}</summary><div class="mt-3 space-y-3">      <article v-for="set in session?.candidate_sets || []" :key="set.id" class="space-y-3 rounded-lg border border-emerald-100 bg-emerald-50/50 p-4">
        <h4 class="text-sm font-semibold text-slate-800">{{ set.summary.name || t('agent.session.candidateCollection') }}</h4>
        <dl class="grid grid-cols-3 gap-2"><div v-for="(count, key) in { selected: set.summary.selected_count, matched: set.summary.matched_count, total: set.summary.total_count }" :key="key"><dt class="text-xs text-slate-500">{{ t('agent.session.resultCounts.' + key) }}</dt><dd class="mt-1 text-xl font-semibold tabular-nums text-slate-800">{{ count ?? '—' }}</dd></div></dl>
        <p class="text-xs leading-relaxed text-slate-500">{{ t('agent.session.resultScopeHint') }}</p>
        <div class="flex flex-wrap items-center gap-2"><Button v-if="candidateResultRoute(set)" as-child size="sm"><button type="button" @click="openResults(set.postprocessing_job_id!, set.id)">{{ L('查看此候选集合', 'View this candidate set') }}</button></Button><span v-else class="text-xs text-slate-500">{{ t('agent.session.resultUnavailable') }}</span><select :value="exportPoses[set.id] || 'docked'" @change="exportPoses[set.id] = ($event.target as HTMLSelectElement).value" :aria-label="L('导出姿态','Export pose')" class="rounded border bg-white p-1 text-xs"><option value="docked">Docked</option><option v-if="set.summary.artifacts?.original_sdf" value="original">Original</option></select><details class="relative"><summary class="cursor-pointer rounded border bg-white px-3 py-2 text-xs">{{ t('agent.ui.export') }}</summary><div class="flex flex-wrap gap-2 py-2"><Button v-for="format in ['csv', 'sdf', 'json']" :key="format" size="sm" variant="outline" :disabled="busy" @click="download(set.id, format)">{{ format.toUpperCase() }}</Button></div></details><Button v-if="!taskBlocked && session?.phase === 'results_ready'" size="sm" variant="outline" @click="resetSelection">{{ t('agent.ui.selectionAction') }}</Button></div>
      </article></div></details>
      <details v-if="relatedPostprocessing.length" class="border-t pt-3"><summary class="cursor-pointer text-sm">{{ L('评价历史', 'Evaluation History') }}</summary><div class="mt-3 space-y-2"><Button v-for="job in relatedPostprocessing" :key="job.id" size="sm" variant="outline" @click="openResults(job.id)">TarPass · {{ statusLabel(job.status) }}</Button></div></details>
      <details v-if="session?.proposals.length" class="border-t pt-3 text-sm"><summary class="cursor-pointer text-slate-500">{{ L('历史方案与结果', 'Previous plans and results') }}</summary><div class="mt-3 space-y-3"><details v-for="proposal in session.proposals.filter(p => p.status !== 'pending')" :key="proposal.id" class="rounded border p-3"><summary class="cursor-pointer">{{ proposal.kind === 'task_plan' ? L('阶段方案', 'Stage plan') : intentLabel(proposal.kind) }} · {{ proposal.payload.task_plan?.workflow?.generator || proposal.payload.effective_generation?.engine || '' }} · v{{ proposal.payload.task_plan_version || proposal.payload.plan_version || 1 }} · {{ statusLabel(proposal.status) }}</summary><dl class="mt-3 space-y-2"><div v-for="(value,key) in proposal.payload.task_plan?.workflow?.generation || proposal.payload.effective_generation || {}" :key="key" class="flex flex-wrap justify-between gap-2"><dt>{{ key }}</dt><dd class="max-w-full break-words">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd></div></dl><div class="mt-3 flex flex-wrap gap-2"><Button v-if="proposal.workflow?.generation?.job_id" size="sm" variant="outline" @click="openResults(proposal.workflow.generation.job_id)">{{ t('agent.session.viewGeneration') }}</Button><Button v-if="proposal.workflow?.postprocessing?.job_id" size="sm" variant="outline" @click="openResults(proposal.workflow.postprocessing.job_id)">{{ t('agent.session.viewTarpass') }}</Button></div></details><Button v-for="draft in savedDrafts" :key="draft.id" size="sm" variant="outline" @click="restoreEditorDraft(draft.kind, draft)">{{ L('恢复草稿', 'Restore draft') }} · {{ draftLabel(draft.kind) }}</Button></div></details>
      <Button v-if="computing" variant="outline" :disabled="busy" @click="cancel">{{ t('agent.session.stop') }}</Button>
      <details v-if="!taskBlocked && !session?.task_plan && !(currentPostprocessingProposal && inlineProposal(currentPostprocessingProposal)) && session?.assets.protein_context_id && (session.workflow || session.presentation?.research_plan) && ['awaiting_workflow_approval', 'awaiting_postprocessing_approval', 'executing', 'results_ready'].includes(session.phase)" class="space-y-2 border-t pt-3" @toggle="loadDatasetsOnDetails">
        <summary>{{ L('评价设置','Evaluation Settings') }}</summary>
        <PostprocessingDraftCard :initial="postprocessingDraftInitial" :source-job-id="postprocessingSourceJobId" :context-id="session?.assets.protein_context_id" :datasets="datasets" :metrics="spec?.metrics || {}" :interaction-types="spec?.interaction_types || []" :residues="spec?.residues || []" :busy="busy" @save="savePostprocessingDraft" @skip="skipPostprocessing" />
      </details>
      <section v-if="!taskBlocked && postprocessingResultJobId" class="candidate-selection space-y-3 border-t pt-3">
        <h3 class="font-semibold">{{ L('筛选并保存候选集合', 'Filter and save candidates') }}</h3>
        <p class="text-sm">{{ L('从当前评价任务的完整结果中筛选分子，保存后可重新查看、导出或继续优化。', 'Select from the full results of the current evaluation run to review, export or optimize later.') }}</p>
        <TarPassFilterEditor v-model="filters" :metrics="candidateMetrics" :disabled="busy" />
        <label class="block space-y-1 text-sm"><span>{{ L('排序指标', 'Sort metric') }}</span><select v-model="sortBy" class="block w-full min-w-0 rounded border bg-white p-2" @change="descending = preferredDescending(sortBy)"><option value="molecule_id">{{ t('platform.moleculeId') }}</option><optgroup v-for="group in candidateMetricGroups" :key="group.key" :label="group.label"><option v-for="key in group.keys" :key="key" :value="key">{{ metricLabel(key) }}</option></optgroup></select></label>
        <p v-if="metricDescription(sortBy)" class="text-sm text-slate-600">{{ metricDescription(sortBy) }}</p>
        <div class="selection-options"><label class="space-y-1 text-sm"><span>{{ L('排序方向', 'Order') }}</span><select v-model="descending" class="block w-full rounded border p-2"><option :value="false">{{ L('从低到高', 'Low to high') }}</option><option :value="true">{{ L('从高到低', 'High to low') }}</option></select></label><label class="space-y-1 text-sm"><span>{{ L('保留数量', 'Keep count') }}</span><input v-model="topK" type="number" min="1" max="10000" :placeholder="L('全部', 'All')" class="block w-full min-w-0 rounded border p-2" /></label></div>
        <Button variant="outline" :disabled="busy || !selectionValid" @click="previewCandidates">{{ L('预览筛选结果', 'Preview selection') }}</Button>
        <div v-if="selectionPreview" class="space-y-3 rounded-lg border bg-slate-50 p-3"><p role="status">{{ L('符合条件', 'Matching') }} {{ selectionPreview.total }} · {{ L('将保存', 'To save') }} {{ selectionPreview.count }}</p><p v-if="selectionPreview.rows.length" class="break-words text-sm">{{ selectionPreview.rows.map(row => row.molecule_id).join(', ') }}</p><label class="block space-y-1 text-sm"><span>{{ L('集合名称', 'Collection name') }}</span><input v-model="candidateName" maxlength="120" class="block w-full rounded border p-2" /></label><Button :disabled="busy || !selectionPreview.count || !candidateName.trim()" @click="selectCandidates">{{ L('保存候选集合', 'Save candidate set') }}</Button></div>
      </section>
      <p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p>
    </div></template></WorkspaceLayout>
    <Dialog :open="!taskBlocked && Boolean(editorProposal)" @update:open="closeWorkflow"><DialogContent @close-auto-focus.prevent="workflowFocus?.focus()" class="max-h-[90dvh] w-[95vw] max-w-3xl overflow-y-auto" :aria-describedby="undefined"><DialogTitle>{{ t('agent.ui.editPlan') }}</DialogTitle><p class="text-xs text-slate-500">{{ t('agent.ui.draftChanged') }}</p><WorkflowParameters v-if="editorProposal" :key="editorProposal.id" :proposal="editorProposal" :filters="editorFilters" :generators="availableGenerators" :edit-spec="session?.confirmed_fields.delete_edit_spec_id?.value" :edit-mode="session?.delete_edit?.mode" :busy="busy || !isCurrentProposal(editorProposal)" :show-actions="true" @dirty="editorDirty = $event" @draft="workflowLocalDraft = $event" :initial-draft="editorDrafts.workflow?.revision === session?.input_revision ? editorDrafts.workflow?.changes : undefined" @save="saveWorkflow" /><p v-if="editorProposal && !isCurrentProposal(editorProposal)" role="alert" class="text-amber-800">{{ t('agent.ui.invalidEditor') }}</p><p v-if="error" role="alert" class="text-red-700">{{ error }}</p></DialogContent></Dialog>
    <Dialog :open="!taskBlocked && Boolean(reviewProposal || structureSelection)" @update:open="closePreparation"><DialogContent @close-auto-focus.prevent="restorePreparationFocus" class="flex flex-col gap-2 overflow-hidden p-4" :class="workspaceExpanded ? 'h-dvh w-screen max-w-none rounded-none sm:rounded-none' : 'h-[88dvh] w-[94vw] max-w-[1320px]'" :aria-describedby="undefined"><div class="flex shrink-0 flex-wrap items-center justify-between gap-3 pr-10"><DialogTitle>{{ t(structureSelection ? 'agent.ui.completeStructure' : 'agent.ui.reviewMode') }}</DialogTitle><Button variant="outline" size="sm" @click="workspaceExpanded = !workspaceExpanded">{{ t(workspaceExpanded ? 'platform.collapseWorkspace' : 'platform.expandWorkspace') }}</Button></div><p class="text-xs text-slate-500">{{ t('agent.ui.inputVersion', {version:reviewRevision ?? t('agent.ui.unavailable')}) }} · {{ reviewState.dirty ? t('agent.ui.localDraft') : reviewReadonly ? t(structureSelection ? 'agent.ui.structureChanged' : 'agent.ui.readonly') : t('agent.ui.noChanges') }}</p>
      <ProteinPreparation v-if="reviewProposal || structureSelection" :key="(reviewProposal?.id || structureSelection?.session_id) + String(reviewRevision)" :review="reviewProposal?.payload" :selection="structureSelection || undefined" :review-readonly="reviewReadonly" @review-state="reviewState = $event"><template #assistant><p class="text-sm font-semibold">{{ session?.goal }}</p><p v-if="session" class="text-xs text-muted-foreground">{{ phaseLabel(session.phase) }}</p><textarea v-model="message" :aria-label="t('agent.session.message')" :placeholder="t('agent.session.placeholder')" :readonly="Boolean(pendingRequest)" class="min-h-32 w-full resize-y border p-3 text-sm" maxlength="4000" @keydown="composerKeydown" /><Button :disabled="busy || turnRunning || !message.trim()" @click="submitMessage()">{{ t('agent.session.send') }}</Button><p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p></template></ProteinPreparation>
      <footer class="shrink-0 space-y-2 border-t pt-2 text-sm"><p v-if="reviewState.dirty" class="text-amber-800">{{ t('agent.ui.dirtyApproval') }}</p><p v-if="reviewSaved" class="text-emerald-800">{{ t('agent.ui.savedProposal') }}</p><p v-if="error" role="alert" class="text-red-700">{{ error }}</p><div class="flex flex-wrap justify-end gap-2"><Button variant="outline" :disabled="busy" @click="closePreparation(false)">{{ t('platform.returnConversation') }}</Button><Button v-if="reviewReadonly && (structureSelection || pendingProposal)" variant="outline" @click="showLatestPreparation">{{ t(structureSelection ? 'agent.ui.reloadStructure' : 'agent.ui.latest') }}</Button><Button v-if="!reviewReadonly && !structureSelection?.site" variant="outline" :disabled="busy || Boolean(turnRunning) || !reviewState.valid" @click="savePreparation(false)">{{ L('保存准备方案','Save preparation plan') }}</Button><Button v-if="!reviewReadonly" :disabled="busy || Boolean(turnRunning) || !reviewState.valid" @click="savePreparation(!structureSelection?.site)">{{ structureSelection?.site ? L('保存位点','Save site') : L('批准并执行蛋白准备','Approve and run protein preparation') }}</Button></div></footer>
    </DialogContent></Dialog>
    <Dialog :open="Boolean(resultTarget)" @update:open="!$event && (resultTarget = null)"><DialogContent class="flex flex-col overflow-hidden p-4" :class="workspaceExpanded ? 'h-dvh w-screen max-w-none rounded-none sm:rounded-none' : 'h-[92dvh] w-[96vw] max-w-[1440px]'" :aria-describedby="undefined"><div class="flex items-center justify-between pr-10"><DialogTitle>{{ resultTarget?.candidateSetId ? L('候选集合', 'Candidate set') + ' · ' + (session?.candidate_sets.find(set => set.id === resultTarget?.candidateSetId)?.summary.name || '') : L('完整任务结果', 'Full run results') }}</DialogTitle><Button variant="outline" size="sm" @click="workspaceExpanded = !workspaceExpanded">{{ t(workspaceExpanded ? 'platform.collapseWorkspace' : 'platform.expandWorkspace') }}</Button></div><AgentResultWorkspace v-if="resultTarget" class="min-h-0 flex-1 overflow-auto" :job-id="resultTarget.jobId" :job-type="resultTarget.jobType as any" :session-id="session?.id" :candidate-set-id="resultTarget.candidateSetId" :read-only="resultReadOnly" @optimize="beginOptimization" @submitted="supplementarySubmitted" @prepare-postprocessing="preparePostprocessing" /></DialogContent></Dialog>
    <Dialog :open="!taskBlocked && Boolean(optimizationSource)" @update:open="!$event && (optimizationSource = null)"><DialogContent :aria-describedby="undefined"><DialogTitle>{{ L('基于所选分子继续优化','Optimize selected molecule') }}</DialogTitle><p class="truncate font-mono text-sm">{{ optimizationSource?.smiles || optimizationSource?.moleculeId || optimizationSource?.resultId }}</p><label class="text-sm">{{ t('agent.session.model') }}<select v-model="optimizationEngine" class="ml-3 rounded border p-2"><option value="epso">EPSO</option><option value="delete">DELETE</option></select></label><p class="text-sm text-slate-600">{{ optimizationEngine === 'epso' ? L('使用完整分子进行二维性质优化。','Optimize properties using the complete molecular seed.') : L('使用所选三维姿态编辑片段；缺少姿态时先准备对接输入。','Edit fragments using the selected 3D pose; prepare docking inputs first when needed.') }}</p><Button :disabled="busy || computing || Boolean(turnRunning)" @click="deriveOptimization">{{ L('建立优化草案','Create optimization draft') }}</Button><p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p></DialogContent></Dialog>
    <Dialog :open="!taskBlocked && Boolean(staleDraft)" @update:open="!$event && (staleDraft = null)"><DialogContent class="max-h-[85dvh] overflow-auto" :aria-describedby="undefined"><DialogTitle>{{ L('草稿需要重新核对','Review draft changes') }}</DialogTitle><p>{{ L('输入或方案已更新，请对照当前结构重新核对草稿。','Inputs or the plan changed. Review the draft against the current structure.') }}</p><pre class="max-h-80 overflow-auto whitespace-pre-wrap text-xs">{{ JSON.stringify(staleDraft?.changes, null, 2) }}</pre><Button :disabled="busy" @click="reviewStaleDraft">{{ L('打开当前版本核对','Review current version') }}</Button></DialogContent></Dialog>
    <Dialog :open="!taskBlocked && Boolean(deleteEditId)" @update:open="closeDelete"><DialogContent class="flex flex-col overflow-hidden p-4" :class="workspaceExpanded ? 'h-dvh w-screen max-w-none rounded-none sm:rounded-none' : 'h-[92dvh] w-[96vw] max-w-[1440px]'" :aria-describedby="undefined"><div class="flex items-center justify-between pr-10"><DialogTitle>{{ t('agent.session.deleteVisualEdit') }}</DialogTitle><Button variant="outline" size="sm" @click="workspaceExpanded = !workspaceExpanded">{{ t(workspaceExpanded ? 'platform.collapseWorkspace' : 'platform.expandWorkspace') }}</Button></div><DeleteEditorWorkspace v-if="deleteEditId" ref="deleteEditor" class="min-h-0 flex-1" :edit-session-id="deleteEditId" embedded show-actions show-protein :save-label="L('保存并返回对话','Save and return to conversation')" :close-label="t('platform.returnConversation')" @state="deleteDirty = $event.dirty" @saved="deleteSaved" @cancelled="deleteEditId = ''; deleteDirty = false" @close="closeDelete(false)" @error="error = $event" /><p v-if="error" role="alert" class="text-sm text-red-700">{{ error }}</p></DialogContent></Dialog>
    <Dialog v-if="closeIntent" :open="true" @update:open="!$event && (closeIntent = null)"><DialogContent class="z-[70]" :aria-describedby="undefined"><DialogTitle>{{ L('有未保存的改动','Unsaved changes') }}</DialogTitle><div class="flex flex-wrap gap-2"><Button :disabled="busy" @click="finishEditorClose(true)">{{ L('保存草稿并关闭','Save draft and close') }}</Button><Button variant="outline" :disabled="busy" @click="finishEditorClose(false)">{{ L('放弃改动','Discard changes') }}</Button><Button variant="ghost" @click="closeIntent = null">{{ L('继续编辑','Keep editing') }}</Button></div><p v-if="error" role="alert">{{ error }}</p></DialogContent></Dialog>
    <AgentAttachmentPicker v-if="attachmentPickerOpen" @close="attachmentPickerOpen = false" @select="bindFile" />
  </main>
</template>

<script setup lang="ts">
import { defaultPrefilters } from '@/utils/tarpassDefaults'
import WorkspaceLayout from '@/components/workbench/WorkspaceLayout.vue'
import { useElementSize } from '@vueuse/core'
import { useWorkspaceState } from '@/composables/useWorkspace'
import request from '@/utils/request'
import { sessionPhaseLabel } from '@/utils/taskPresentation'
import ClarificationForm from './ClarificationForm.vue'
import SessionNavigation from './SessionNavigation.vue'
import AgentAttachmentPicker from './AgentAttachmentPicker.vue'
import AgentContextPicker from './AgentContextPicker.vue'
import ContextResultCard from './ContextResultCard.vue'
import StageNavigation from './StageNavigation.vue'
import JobResultCard from './JobResultCard.vue'
import InputSelectionCard from './InputSelectionCard.vue'
import PostprocessingDraftCard from './PostprocessingDraftCard.vue'
import PosePreparationCard from './PosePreparationCard.vue'
import PreparationSummary from './PreparationSummary.vue'
import ResultDetails from './ResultDetails.vue'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import WorkflowDraftCard from './WorkflowDraftCard.vue'
import DiagnosticEvidence from './DiagnosticEvidence.vue'
import WorkflowParameters from './WorkflowParameters.vue'
import TaskPlanCard from './TaskPlanCard.vue'
import TarPassFilterEditor from '@/components/molecule/TarPassFilterEditor.vue'
import { useTarPassMetrics, expandFilters, filterDrafts, validFilters, type MetricFilterDraft } from '@/components/molecule/useTarPassMetrics'
import { candidateResultRoute, clarificationMessage, clarificationRequirements, isStructuralRequirement, proposalTurnId, requirementKind, validRequirementAnswer } from './sessionPresentation'
import { ArrowLeft, Check, CircleStop, ClipboardCheck, Files, FileText, Layers3, LoaderCircle, PanelLeft, PanelRight, Paperclip, RotateCcw, Sparkles, SquarePen, Trash2, Upload, X } from 'lucide-vue-next'
import { workflowCommand, openWorkflowEditor, saveWorkflowEditor, saveWorkflowEditorDraft, getWorkflowEditor, cancelWorkflowEditor } from "@/api/workflowCommands"
import { uploadProteinDataset, ensureProteinFile, getProteinContext } from '@/api/proteinContext'
import { useI18n } from 'vue-i18n'
import { randomUUID } from '@/utils/uuid'
import { checkUploadFile, uploadCheckMessage } from '@/utils/uploadFileCheck'
import { requestErrorKind, requestErrorMessage, systemErrorMessage } from '@/utils/requestError'
import { unsentRemainder } from '@/utils/composerDraft'
import { agentDraftKey, readAgentDraft, saveAgentDraft, type DraftAttachment, type AgentDraft } from '@/utils/agentDraft'
import { useRetentionStore } from '@/stores/retention'
import { defineAsyncComponent, computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { readStoredUserInfo } from '@/utils/guestSession'
import type { WebSocketManager } from '@/utils/websocket'
import { Button } from '@/components/ui/button'
import type { ProteinContextListItem } from '@/types/proteinContext'
import { stopAgentSessionTurn, resumeAgentSessionTurn, getAgentSessionHistory, deleteAgentSession, getAgentSessionSpecs, startAgentSession, listAgentSessions, getAgentSession, sendAgentSessionTurn, exportAgentCandidateSet, uploadBackendDataset, cancelDatasetUpload, listAllBackendDatasets, type AgentSessionState, type AgentSessionTurn, type AgentTaskPlanDefinition, getBackendDataset, getBackendJob, deriveAgentOptimization, approveAgentOptimizationPose, type BackendDataset, type BackendDatasetFile } from '@/api/genovaBackend'

const props = defineProps<{ compact?: boolean; structureInput?: { datasetId: string; fileId: string; name: string; contextId?: string } }>()
const { t, te, locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const route = useRoute(), router = useRouter()
const retention = useRetentionStore()
const websocket = inject<WebSocketManager>('websocket')
const session = ref<AgentSessionState | null>(null), history = ref<Array<{id: string; goal: string; phase: string}>>([])
const taskBlocked = computed(() => session.value?.research_task_state === 'blocked')
function canActOnTurn(turn: AgentSessionTurn) {
  return !taskBlocked.value && (turn.research_task_id || null) === (session.value?.research_task_id || null) && turn.response.safety_decision !== 'refuse'
}
function canContinueTurn(turn: AgentSessionTurn) {
  return canActOnTurn(turn) || turn.intent === 'new_task' && turn.response.error_code === 'SAFETY_CHECK_UNAVAILABLE' && turn.request.base_revision === session.value?.input_revision
}
const spec = ref<any>(null)
const specLoadError = ref('')
let specAttempts = 0, specRetryAt = 0
async function retrySpecs() { specAttempts = 0; await guarded(hydrate) }
const DeleteEditorWorkspace = defineAsyncComponent(() => import('@/pages/molopt/components/DeleteEditorWorkspace.vue'))
const AgentResultWorkspace = defineAsyncComponent(() => import('./AgentResultWorkspace.vue'))
const ProteinPreparation = defineAsyncComponent(() => import('@/components/protein-preparation/ProteinPreparation.vue'))
type Proposal = AgentSessionState['proposals'][number]
const { attachedSessionId } = useWorkspaceState('structure-assistant', () => props.structureInput?.contextId || props.structureInput?.datasetId || 'draft', { attachedSessionId: '' })
const message = ref('')
const { conversationTop } = useWorkspaceState(props.compact ? 'structure-agent' : 'agent', () => String(session.value?.id || (props.compact ? attachedSessionId.value : route.query.session_id) || (props.compact ? `draft:${props.structureInput?.contextId || props.structureInput?.datasetId || 'structure'}` : 'draft')), { conversationTop: -1 })
const navigationOpen = ref(false), workspaceLayout = ref<InstanceType<typeof WorkspaceLayout> | null>(null)
const { detailsOpen: savedDetailsOpen } = useWorkspaceState('agent-stage-details', () => String(session.value?.id || route.query.session_id || attachedSessionId.value || 'draft'), { detailsOpen: false })
const { width: workspaceWidth } = useElementSize(() => workspaceLayout.value?.$el)
const desktopDetails = computed(() => !props.compact && workspaceWidth.value >= 768)
const detailsOpen = computed({ get: () => desktopDetails.value || savedDetailsOpen.value, set: open => { savedDetailsOpen.value = open } })
function toggleNavigation() {
  navigationOpen.value = !navigationOpen.value
  if (navigationOpen.value && !desktopDetails.value) detailsOpen.value = false
}
watch(detailsOpen, open => { if (open) navigationOpen.value = false }, { flush: 'sync' })
const deleteEditId=ref(''), deleteDirty=ref(false), deleteEditor=ref<any>(null)
function closeDelete(open: boolean) { if(open || busy.value) return; if(deleteDirty.value){closeIntent.value='delete';return};deleteEditId.value='' }
async function deleteSaved() {
  deleteEditId.value='';deleteDirty.value=false
  const next={...editorDrafts.value};delete next.delete;editorDrafts.value=next
  await refresh()
  if (pendingProposal.value) locateProposal(pendingProposal.value)
  else if (newWorkflowPlan.value?.generator === 'delete') openNewDraft()
}
const optimizationSource = ref<Record<string, any> | null>(null), optimizationEngine = ref('epso')
const pendingPose = ref<Record<string,any> | null>(null)
function beginOptimization(source: Record<string, any>) { if (!resultReadOnly.value) optimizationSource.value = source }
async function deriveOptimization() {
  if (!optimizationSource.value || !session.value || busy.value || computing.value || turnRunning.value) return
  const source=optimizationSource.value, engine=optimizationEngine.value
  let response: Record<string,any> | undefined
  await guarded(async () => { response=(await deriveAgentOptimization(session.value!.id,{command_id:randomUUID(),expected_version:session.value!.input_revision,engine,source_job_id:source.jobId,result_id:source.resultId,molecule_id:source.moleculeId,source_index:source.sourceIndex,pose:source.pose,candidate_set_id:source.candidateSetId || resultTarget.value?.candidateSetId})).data; await refresh() })
  if (!response) return
  optimizationSource.value=null;resultTarget.value=null
  if(response.requires_pose){pendingPose.value=response.next_step;error.value=''}
  else {
    newWorkflowPlan.value={generator:engine,template:engine === 'epso' ? 'ecloud_epso' : 'delete',seed_source:response.seed_source,protein_context_id:response.protein_context_id,generation:{engine},postprocessing:{enabled:false,prefilters:[]}}
    if(engine === 'delete' && !computing.value) await openEditor('delete')
    else openNewDraft()
  }
}
async function approvePosePreparation() {
  if (!pendingPose.value?.approval_hash || !session.value || busy.value) return
  const next=pendingPose.value
  await guarded(async () => {
    await approveAgentOptimizationPose(session.value!.id,{command_id:randomUUID(),expected_version:session.value!.input_revision,source_job_id:next.source_job_id,result_id:next.result_id,molecule_id:next.molecule_id,source_index:next.source_index,candidate_set_id:next.candidate_set_id,seed_dataset_id:next.seed_dataset_id,pose:next.pose || 'docked',approval_hash:next.approval_hash})
    pendingPose.value=null
    await refresh()
  })
}
async function recheckPosePreparation() {
  if (!pendingPose.value || !session.value || busy.value) return
  const next = pendingPose.value
  let response: Record<string, any> | undefined
  await guarded(async () => {
    response = (await deriveAgentOptimization(session.value!.id, { command_id: randomUUID(), expected_version: session.value!.input_revision, engine: 'delete', source_job_id: next.source_job_id, result_id: next.result_id, molecule_id: next.molecule_id, source_index: next.source_index, pose: next.pose || 'docked', candidate_set_id: next.candidate_set_id })).data
    await refresh()
  })
  if (!response) return
  if (response.requires_pose) {
    pendingPose.value = response.next_step || response.pose_preparation_draft
    error.value = ''
    return
  }
  pendingPose.value = null
  newWorkflowPlan.value = { generator: 'delete', template: 'delete', seed_source: response.seed_source, protein_context_id: response.protein_context_id, generation: { engine: 'delete' }, postprocessing: { enabled: false, prefilters: [] } }
  await openEditor('delete')
}
async function continuePoseEditing() {
  if (!session.value?.pose_preparation || busy.value) return
  const jobId=session.value.pose_preparation.job_id
  let row: any
  await guarded(async () => {
    const {data}=await request.post(`/api/v1/jobs/${jobId}/postprocessing/results`,{limit:2,offset:0})
    if(data.rows.length === 1 && data.total === 1) row=data.rows[0]
    else error.value=L('请在结果中选择需要使用的分子与姿态。','Select the molecule and pose in the results.')
  })
  if (!row) {await openResults(jobId);return}
  const target=session.value.pose_preparation.provenance?.target || {}
  optimizationSource.value={jobId,resultId:row.result_id,moleculeId:row.molecule_id,smiles:row.smiles,pose:'docked',candidateSetId:target.candidate_set_id,sourceIndex:target.source_index}
  optimizationEngine.value='delete'
  await deriveOptimization()
}

const resultTarget = ref<{ jobId: string; jobType: string; candidateSetId?: string } | null>(null)
const resultReadOnly = computed(() => {
  if (taskBlocked.value) return true
  const jobId = resultTarget.value?.jobId
  return Boolean(jobId && session.value?.proposals.some(p =>
    (p.research_task_id || null) !== (session.value?.research_task_id || null) &&
    [p.execution.job_id, p.workflow?.generation?.job_id, p.workflow?.postprocessing?.job_id].includes(jobId)))
})
const draftOpen = ref(false), draftRevision = ref(0), workspaceExpanded = ref(false)
const draftActionTurnId = ref(''), draftActionTarget = ref<HTMLElement | null>(null)
const actionTargets = ref<Record<string, HTMLElement>>({})
const proposalActionTargets = computed(() => Object.fromEntries((session.value?.proposals || []).map(proposal => [proposal.id, actionTargets.value[`${proposal.id}-${proposalAnchors.value[proposal.id]}`]])))
const taskPlanActionTarget = computed(() => proposalActionTargets.value[session.value?.task_plan?.proposal_id || ''] || null)
const taskPlanDraft = ref<AgentTaskPlanDefinition | null>(null)
const activeTaskPlan = computed(() => Boolean(!taskBlocked.value && session.value?.task_plan && !['completed','partial','canceled'].includes(session.value.task_plan.state)))
const summaryPlan = computed(() => draftOpen.value ? { workflow: newWorkflowDraft.value.plan || newWorkflowPlan.value } : taskPlanDraft.value || session.value?.task_plan?.definition)
function setDraftTarget(el: unknown) { draftActionTarget.value = el instanceof HTMLElement ? el : null }
function setProposalTarget(proposalId: string, turnId: string, el: unknown) {
  const key = `${proposalId}-${turnId}`
  if (el instanceof HTMLElement) { if (actionTargets.value[key] !== el) actionTargets.value[key] = el }
  else delete actionTargets.value[key]
}
const newWorkflowPlan = ref<Record<string, any> | null>(null)
const newWorkflowDraft = ref<Record<string,any>>({}), newDraftDirty = ref(false)
const taskPlanChangedDuringDraft = ref(false)
const inlineDirty = ref<Record<string,boolean>>({})
const editorProposal = ref<Proposal | null>(null), editorFilters = ref<any[]>([]), editorDirty = ref(false)
const reviewProposal = ref<Proposal | null>(null), reviewRevision = ref<number | null>(null), reviewSaved = ref(false)
const structureSelection = ref<Record<string, any> | null>(null)
const reviewState = ref({dirty:false,valid:false,changes:{} as Record<string,any>})
const fileNames = ref<Record<string,string>>({})
const referenceModeLabels: Record<string,string> = {ligand:'referenceLigand',residues:'residueSelection',coordinates:'manualCoordinates'}
const currentStructureName = computed(() => fileNames.value[session.value?.confirmed_fields.protein_file_id?.value || session.value?.prepared_receptor?.source?.file_id] || '')
const availableGenerators = computed(() => Object.fromEntries(Object.entries<any>(spec.value?.capabilities?.generators || {}).map(([engine, capability]) => {
  const context = session.value?.context_spec
  const status = context?.compatibility?.models?.[engine]?.status
  const hasSeed = Boolean(context?.generation_reference || context?.reference_ligand_path || session.value?.assets.optimization_seed)
  const compatible = !status || ['full','limited','unchecked'].includes(status)
  return [engine, { ...capability, enabled: capability.enabled && compatible && (!['epso','delete'].includes(engine) || hasSeed) }]
})))
async function analyzeResults() {
  message.value = L('请帮助分析刚完成的评价结果，比较主要指标并说明候选分子的优缺点。','Analyze the completed evaluation results, compare the main metrics and explain the candidates’ strengths and weaknesses.')
  await submitMessage()
}
const currentWorkflowProposal = computed(() => [...(session.value?.proposals || [])].reverse().find(p => p.kind === 'workflow'))
const currentPostprocessingProposal = computed(() => {
  const workflowId = session.value?.workflow?.id || session.value?.presentation?.research_plan?.workflow_id
  return [...(session.value?.proposals || [])].reverse().find(p => p.kind === 'postprocessing' && (!workflowId || p.workflow?.id === workflowId || (p as any).workflow_id === workflowId || p.payload?.source_workflow_id === workflowId))
})
const postprocessingSourceJobId = computed(() => session.value?.workflow?.generation?.job_id || currentWorkflowProposal.value?.workflow?.generation?.job_id || '')
const postprocessingDraftInitial = computed(() => currentPostprocessingProposal.value?.payload || { enabled: true, prefilters: defaultPrefilters(), key_interactions: [], reference_dataset_id: null, selection: { sort_by: 'molecule_id', descending: false, top_k: null } })
const pendingProposal = computed(() => [...(session.value?.proposals || [])].reverse().find(p => isCurrentProposal(p)))
const proposalAnchors = computed(() => Object.fromEntries((session.value?.proposals || []).map(proposal => [proposal.id, (proposalNeedsAction(proposal) ? currentReplyTurnId.value : '') || proposalTurnId(proposal, session.value!.turns) || (proposal.id === session.value?.task_plan?.proposal_id || isCurrentProposal(proposal) ? latestTurn.value?.id || '' : '')])))
const proposalsForTurn = (id: string) => (session.value?.proposals || []).filter(proposal => proposal.turn_id === id || session.value?.turns.find(turn => turn.id === id)?.response.proposal_id === proposal.id || proposalAnchors.value[proposal.id] === id)
function showStructureActions(turn: AgentSessionTurn) {
  return Boolean(canActOnTurn(turn) && !turn.trigger && (!turn.source || turn.source === 'chat') && turn.response.message && !turn.response.error_code && !turn.response.missing_requirements?.length && !turn.response.results && !turn.response.result_queries?.length && !proposalsForTurn(turn.id).length && (session.value?.assets.protein_context_id || session.value?.assets.prepared_receptor_id || session.value?.assets.protein_dataset_id) && (turn.response.protein_context_id || turn.response.tools?.some((step: { tool: string }) => ['get_context','inspect_session_protein'].includes(step.tool))))
}
const nextActionTurnId = computed(() => !taskBlocked.value && !draftOpen.value && !activeTaskPlan.value && !pendingRequirements.value.length && !pendingProposal.value && ['ready_for_planning','awaiting_site','awaiting_selection'].includes(session.value?.phase || '') && latestTurn.value?.response.message && !latestTurn.value.response.error_code && !showStructureActions(latestTurn.value) ? latestTurn.value.id : '')
const inlineProposal = (proposal: Proposal) => isCurrentProposal(proposal) && proposal.kind !== 'task_plan' && (!session.value?.task_plan || proposal.kind === 'prepare')
const proposalGeneration = (proposal: Proposal) => proposal.payload.task_plan?.stage === 'postprocessing' ? null : proposal.payload.task_plan?.workflow?.generation || proposal.payload.effective_generation
const proposalTitle = (proposal: Proposal) => proposal.kind === 'task_plan' ? ({preparation:L('蛋白准备方案','Protein preparation plan'),generation:L('生成 / 优化方案','Generation / optimization plan'),postprocessing:L('评价与筛选方案','Evaluation Plan')}[proposal.payload.task_plan?.stage as string] || L('任务方案','Task plan')) : intentLabel(proposal.kind)
const taskPlanStateLabel = (state: string) => ({awaiting_approval:L('待确认','Needs approval'),running:L('执行中','Running'),analyzing:L('分析中','Analyzing'),pause_requested:L('暂停中','Pausing'),paused:L('已暂停','Paused'),blocked:L('待处理','Needs attention'),completed:L('已完成','Completed'),partial:L('部分完成','Partial'),canceled:L('已取消','Canceled')}[state] || statusLabel(state))
function proposalNeedsAction(proposal: Proposal) {
  return !taskBlocked.value && (proposal.id === session.value?.task_plan?.proposal_id ? ['awaiting_approval','paused','blocked'].includes(session.value.task_plan.state) : isCurrentProposal(proposal))
}
function proposalStateLabel(proposal: Proposal) {
  if (proposal.status === 'stale') return L('已失效','Expired')
  if (proposal.id === session.value?.task_plan?.proposal_id) return taskPlanStateLabel(session.value!.task_plan!.state)
  if (proposal.status === 'pending' && !isCurrentProposal(proposal)) return L('已失效','Expired')
  if (proposal.status === 'pending') return L('待处理','Needs action')
  return proposal.job_status ? statusLabel(proposal.job_status) : proposal.status === 'approved' ? L('已确认','Approved') : statusLabel(proposal.status)
}
const reviewReadonly = computed(() => taskBlocked.value || reviewRevision.value !== session.value?.input_revision || (structureSelection.value ? structureSelection.value.session_id !== session.value?.id : !reviewProposal.value || !isCurrentProposal(reviewProposal.value)))
const clarificationField = (requirement:string) => clarificationFields.value.find((field:any) => field.requirement === requirement)
const error = ref(''), busy = ref(false), addOpen = ref(false)
const datasets = ref<BackendDataset[]>([]), contexts = ref<ProteinContextListItem[]>([])
const attachmentPickerOpen = ref(false), contextPickerOpen = ref(false)
watch(addOpen, open => { if (!open) contextPickerOpen.value = false })
const sortBy = ref('docked.affinity'), descending = ref(false), topK = ref<number | string>(20), filters = ref<MetricFilterDraft[]>([])
const exportPoses = ref<Record<string,string>>({})
const workflowLocalDraft = ref<Record<string, any>>({})
const closeIntent = ref<'structure' | 'workflow' | 'newworkflow' | 'delete' | null>(null)
const staleDraft = ref<Record<string,any> | null>(null)
const { editorDrafts } = useWorkspaceState('agent-editor-drafts', () => session.value?.id || 'draft', { editorDrafts: {} as Record<string, any> })
const exportNote = ref(''), clarificationAnswers = ref<Record<string, string | number>>({})
const latestTurn = computed(() => { const turns = session.value?.turns || []; return turns[turns.length - 1] })
const currentReplyTurnId = computed(() => [...(session.value?.turns || [])].reverse().find(turn => turn.response.message && !turn.response.error_code)?.id || '')
const clarificationTurn = computed(() => [...(session.value?.turns || [])].reverse().find(turn => canActOnTurn(turn) && turn.status === 'needs_input'))
const clarificationActionTurnId = computed(() => pendingRequirements.value.length ? currentReplyTurnId.value || clarificationTurn.value?.id : clarificationTurn.value?.id)
const clarificationFields = computed(() => session.value?.pending_clarification_fields ?? clarificationTurn.value?.response.clarification_fields ?? [])
const pendingRequirements = computed<string[]>(() => taskBlocked.value ? [] : session.value?.pending_requirements ?? (latestTurn.value?.status === 'needs_input' ? latestTurn.value.response.missing_requirements || [] : []))
const requirements = computed<string[]>(() => clarificationRequirements(pendingRequirements.value, clarificationFields.value))
watch(() => `${session.value?.id || ''}:${clarificationTurn.value?.id || ''}`, () => { clarificationAnswers.value = {} }, { flush: 'sync' })
const confirmedDeleteEdit = computed(() => {
  const id = session.value?.confirmed_fields.delete_edit_spec_id?.value, mode = session.value?.delete_edit?.mode
  return id && mode ? { id: String(id), mode } : undefined
})
const canSubmitClarification = computed(() => requirements.value.every(requirement => validRequirementAnswer(requirement, clarificationAnswers.value[requirement], Boolean(confirmedDeleteEdit.value), Boolean(session.value?.assets.protein_context_id || draftContext.value), clarificationFields.value)))
const structuralRequirements = computed(() => pendingRequirements.value.filter(requirement => isStructuralRequirement(requirement, clarificationFields.value)))
const structureLabels = computed(() => [...new Set(structuralRequirements.value.map(requirement => clarificationField(requirement)?.id || requirement))].map(id => t('agent.ui.structureFields.' + id)))
const hasCandidateResults = (proposalId: string) => session.value?.candidate_sets.some(set => set.proposal_id === proposalId && candidateResultRoute(set))
const stages = computed(() => session.value?.presentation?.stages || [
  {key:'input',status:session.value?.assets.protein_dataset_id || session.value?.assets.protein_context_id || session.value?.assets.prepared_receptor_id ? 'ready':'waiting'},
  {key:'preparation',status:session.value?.preparation?.status || (session.value?.assets.prepared_receptor_id || session.value?.assets.protein_context_id ? 'succeeded':'pending')},
  {key:'site',status:session.value?.assets.protein_context_id ? 'ready':session.value?.phase === 'awaiting_site' ? 'waiting':'pending'},
  {key:'generation',status:session.value?.workflow?.generation?.status || 'pending',job_id:session.value?.workflow?.generation?.job_id},
  {key:'postprocessing',status:session.value?.workflow?.postprocessing?.status || 'pending',job_id:session.value?.workflow?.postprocessing?.job_id},
  {key:'selection',status:session.value?.candidate_sets.length ? 'ready':'pending'}
])

const stageBlocker = computed(() => {
  const blocker = session.value?.presentation?.blocker
  if (!blocker) return undefined
  if (blocker.kind === 'input') return L('请补充当前步骤所需的输入。','Complete the required inputs for this step.')
  if (blocker.kind === 'approval') return blocker.reason === 'postprocessing_approval_required' ? L('评价与筛选方案已准备好，核对参数后批准。','Review and approve the evaluation plan.') : L('方案已准备好，核对后批准执行。','Review and approve the prepared plan.')
  return typeof blocker.reason === 'object' ? errorText(blocker.reason) : errorText({error_code:blocker.reason,message:blocker.reason})
})
const relatedPostprocessing = computed<Array<Record<string,any>>>(() => (session.value?.presentation?.related_postprocessing_jobs || []).filter((job:any) => job.id !== session.value?.pose_preparation?.job_id))
const rounds = computed<Array<Record<string,any>>>(() => session.value?.presentation?.rounds || [])
const currentResultLinks = computed(() => ['generation','postprocessing'].flatMap(stage => {
  const step = session.value?.workflow?.[stage]
  return step?.job_id && ['succeeded','partial_succeeded'].includes(step.status) ? [{jobId:step.job_id,postprocessing:stage === 'postprocessing'}] : []
}))
const completionCards = computed(() => {
  const cards = new Map<string, {jobId:string;postprocessing:boolean;finishedAt?:string}>()
  for (const round of rounds.value) for (const stage of ['generation','postprocessing']) {
    const step = round[stage]
    if (step?.job_id && ['succeeded','partial_succeeded'].includes(step.status)) cards.set(step.job_id,{jobId:step.job_id,postprocessing:stage === 'postprocessing',finishedAt:step.finished_at})
  }
  const turns = session.value?.turns || []
  return [...cards.values()].map(card => {
    const events = turns.filter(turn => ['completion','task_plan'].includes(turn.trigger || '') && turn.response.message && !turn.response.error_code)
    const anchor = events.find(turn => card.finishedAt && Date.parse(turn.created_at) >= Date.parse(card.finishedAt)) || events[events.length - 1]
    return {...card,turnId:anchor?.id}
  })
})
const resultCardsForTurn = (id: string) => completionCards.value.filter(card => card.turnId === id)
const postprocessingResultJobId = computed(() => session.value?.workflow?.postprocessing?.status === 'succeeded' ? session.value.workflow.postprocessing.job_id || '' : '')
const candidateJob = ref<Record<string,any> | null>(null)
const candidateName = ref('')
const selectionPreview = ref<{total:number;count:number;rows:Array<Record<string,any>>} | null>(null)
const candidateMetrics = computed(() => Object.fromEntries(Object.entries<any>(spec.value?.metrics || {}).filter(([key,info]) => {
  const params = candidateJob.value?.params?.postprocessing || {}
  const output = candidateJob.value?.tasks?.find((task:any) => task.task_code === 'tarpass')?.output_payload || {}
  return !(key.startsWith('original.') && !output.original_sdf) && !(key.startsWith('docked.') && !output.docked_sdf)
    && !(info.requires?.includes('reference_dataset') && !params.reference_dataset_id)
    && !(info.requires?.includes('key_interactions') && !params.key_interactions?.length)
    && !(info.requires?.includes('reference_ligand') && !session.value?.context_spec?.generation_reference)
})))
const {metricLabel,metricDescription,preferredDescending} = useTarPassMetrics(() => spec.value?.metrics || {})
const candidateMetricGroups = computed(() => ['properties','original','docked'].map(key => ({key,label:key === 'properties' ? L('分子性质','Molecular properties') : key === 'original' ? L('原始姿态','Original pose') : L('对接姿态','Docked pose'),keys:Object.keys(candidateMetrics.value).filter(metric => key === 'properties' ? !metric.includes('.') : metric.startsWith(key + '.'))})).filter(group => group.keys.length))
const selectionKey = computed(() => JSON.stringify([postprocessingResultJobId.value,filters.value,sortBy.value,descending.value,topK.value]))
const selectionValid = computed(() => expandFilters(filters.value).length <= 20 && validFilters(filters.value, candidateMetrics.value) && (sortBy.value === 'molecule_id' || candidateMetrics.value[sortBy.value]) && (topK.value === '' || Number.isInteger(Number(topK.value)) && Number(topK.value) >= 1 && Number(topK.value) <= 10000))
watch(selectionKey, () => { selectionPreview.value = null })
watch(postprocessingResultJobId, async id => {
  candidateJob.value = null
  candidateName.value = L('候选集合 ', 'Candidates ') + String((session.value?.candidate_sets.length || 0) + 1)
  if (!id) return
  try { const {data} = await getBackendJob(id); if (postprocessingResultJobId.value === id) { candidateJob.value = data; if (!candidateMetrics.value[sortBy.value]) sortBy.value = 'molecule_id' } } catch (exc) { fail(exc) }
}, {immediate:true})

const draftLabel = (kind: string) => ({protein:L('结构与位点','Structure and site'),structure:L('结构与位点','Structure and site'),delete:L('片段编辑','Fragment editing'),workflow:L('方案参数','Plan parameters'),newworkflow:L('新方案','New plan'),selection:L('结果筛选','Result selection')}[kind] || kind)
const savedDrafts = computed(() => {
  if (taskBlocked.value) return []
  const closed = new Set((session.value?.presentation?.drafts || []).filter((item:any) => item.status !== 'open').map((item:any) => item.id))
  const local = Object.entries(editorDrafts.value).map(([kind,value]:[string,any]) => ({...value,kind})).filter(item => !closed.has(item.id))
  const ids = new Set(local.map(item => item.id))
  return [...local,...(session.value?.presentation?.drafts || []).filter((item:any) => item.status === 'open' && item.has_draft && !ids.has(item.id))]
})
function showGenerationPlan() { if (session.value?.task_plan?.definition.stage === 'generation' && activeTaskPlan.value) { focusCurrentPlan(); return }; openNewDraft() }
async function selectStage(stage: {key:string;job_id?:string}) {
  if (['input','preparation','site'].includes(stage.key)) {
    if (stage.key === 'preparation') {
      if (session.value?.task_plan?.definition.stage === 'preparation' && session.value.task_plan.state === 'awaiting_approval') { reviewTaskPreparation(); return }
      const proposal=[...(session.value?.proposals || [])].reverse().find(item => item.kind === 'prepare')
      if (proposal) { await openPreparation(proposal); return }
    }
    await openStructureSelection()
  } else if (stage.job_id) await openResults(stage.job_id)
  else if (stage.key === 'generation' && session.value?.assets.protein_context_id) {
    if (pendingProposal.value?.kind === 'workflow') locateProposal(pendingProposal.value)
    else showGenerationPlan()
  } else if (stage.key === session.value?.task_plan?.definition.stage && activeTaskPlan.value) focusCurrentPlan()
  else detailsOpen.value = true
}
async function supplementarySubmitted(jobId:string) {await refresh();await openResults(jobId)}
async function openResults(jobId: string, candidateSetId?: string) { await guarded(async () => {const {data}=await getBackendJob(jobId,{summary:true}); resultTarget.value={jobId,jobType:data.job_type,candidateSetId}}) }
const computing = computed(() => ['preparing', 'executing', 'cancel_requested'].includes(session.value?.phase || ''))
const computationLabel = computed(() => session.value?.phase === 'cancel_requested' ? t('agent.session.stopping') : t(session.value?.preparation?.status === 'running' ? 'agent.session.taskRunning' : 'agent.session.taskSubmitted'))
const stoppingTurn = ref(false)
const turnRunning = computed(() => session.value?.turns.some(t => ['queued', 'running'].includes(t.status)))
let timer: ReturnType<typeof setTimeout> | undefined, active = true, restoreGeneration = 0, refreshGeneration = 0, restoringView = false
const phaseLabel = (phase: string) => taskBlocked.value ? L('已拒绝','Refused') : phase === 'waiting_input' ? L('等待你的回答','Waiting for your answer') : phase === 'paused' ? L('任务已暂停','Task paused') : phase === 'analyzing' ? L('正在分析结果','Analyzing results') : phase === 'awaiting_postprocessing_approval' ? L('等待评价审批','Awaiting evaluation approval') : sessionPhaseLabel(phase)
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true })
const composer = ref<HTMLTextAreaElement | null>(null)
const attachmentInput = ref<HTMLInputElement | null>(null)
watch(message, async () => { await nextTick(); if (composer.value) { composer.value.style.height = 'auto'; composer.value.style.height = `${Math.min(160, Math.max(48, composer.value.scrollHeight))}px` } })
const conversation = ref<HTMLElement | null>(null), nearBottom = ref(true), hasNewMessages = ref(false)
const draftContext = ref(''), draftId = ref(randomUUID()), pendingRequest = ref<Record<string, any> | null>(null)
const pendingFiles = ref<Record<string, DraftAttachment>>({})
const uploadingAttachments = ref(false), cancelingAttachments = ref(false), uploadNotice = ref('')
let uploadController: AbortController | undefined, currentUpload : DraftAttachment | undefined
function cancelAttachmentPreparation() {
  if (!uploadingAttachments.value) return
  cancelingAttachments.value = true
  if (currentUpload) currentUpload.cancelPending = true
  uploadController?.abort()
}
async function confirmCanceledUpload(item: DraftAttachment) {
  if (!item.uploadId) return
  const result = await cancelDatasetUpload(item.uploadId)
  if (result.status === 'uploaded' && result.dataset) {
    item.datasetId = result.dataset.id
    item.file = undefined
  }
  item.uploadId = undefined
  item.cancelPending = false
}
async function uploadComposerAttachment(role: string, item: DraftAttachment, generation: number) {
  if (item.cancelPending) {
    await confirmCanceledUpload(item)
    if (!operationCurrent(generation) || cancelingAttachments.value) return
  }
  if (item.datasetId) return
  if (!item.file) throw new Error(L('本地附件需要重新选择。', 'Select the local attachment again.'))
  item.uploadId ||= randomUUID()
  currentUpload = item
  uploadController = new AbortController()
  try {
    const options = {uploadId:item.uploadId, signal:uploadController.signal}
    const dataset = role === 'protein_dataset_id' ? await uploadProteinDataset(item.file, 'agent_protein', options)
      : (await uploadBackendDataset({name:item.name, kind:'agent_ligand', file:item.file, fileRole:'ligand_input', ...options})).data
    item.datasetId = dataset.id
    item.file = undefined
    item.uploadId = undefined
    item.cancelPending = false
  } catch (e: any) {
    if (e?.response?.data?.detail?.error_code === 'UPLOAD_CANCELED') { item.uploadId = undefined; item.cancelPending = false }
    if (!cancelingAttachments.value || !operationCurrent(generation)) throw e
    item.cancelPending = true
    await confirmCanceledUpload(item)
  } finally {
    uploadController = undefined
    currentUpload = undefined
  }
}

const draftOwner = readStoredUserInfo()?.id || ''
const draftScope = props.compact ? props.structureInput?.datasetId || 'structure' : 'main'
const lastSessionKey = `genova:agent:last-session:${draftOwner}:${draftScope}`
const composerSession = ref('')
const draftLoading = ref(true), initializing = ref(true)
const currentOwner = () => active && readStoredUserInfo()?.id === draftOwner
function persistComposer() {
  if (draftLoading.value || !currentOwner()) return
  const files = Object.fromEntries(Object.entries(pendingFiles.value).map(([role, file]) => [role, {...file}]))
  saveAgentDraft(agentDraftKey(draftOwner, draftScope, composerSession.value), {
    text:message.value, files, context:draftContext.value,
    request:pendingRequest.value ? JSON.parse(JSON.stringify(pendingRequest.value)) : null,
    clientId:draftId.value, saved_at:Date.now(),
  })
}
watch([message, pendingFiles, draftContext, pendingRequest, draftId], persistComposer, {deep:true, flush:'sync'})
async function switchComposer(id: string) {
  draftLoading.value = true
  composerSession.value = id
  localStorage.setItem(lastSessionKey, id)
  sessionStorage.setItem(lastSessionKey, id)
  let saved = await readAgentDraft(agentDraftKey(draftOwner, draftScope, id))
  // Restore text written by the prior version without exposing another account's draft.
  if (!saved) {
    try {
      const key = 'genova:agent:composer:' + (props.compact ? draftScope : 'main')
      const legacy = JSON.parse(sessionStorage.getItem(key) || 'null')
      if (legacy?.owner === draftOwner && legacy.session === id) {
        saved = {text:legacy.text, files:{}, context:'', request:null, clientId:randomUUID(), saved_at:legacy.saved_at}
        sessionStorage.removeItem(key)
      }
    } catch { /* malformed legacy data */ }
    for (const key of Object.keys(sessionStorage)) {
      const prefix = 'genova:agent:draft:'
      if (!key.startsWith(prefix)) continue
      try {
        let ownerKey = key.slice(prefix.length)
        if (props.compact) {
          if (!ownerKey.endsWith(':' + draftScope)) continue
          ownerKey = ownerKey.slice(0, -draftScope.length - 1)
        }
        if (JSON.parse(ownerKey).id !== draftOwner) continue
        const legacy = JSON.parse(sessionStorage.getItem(key) || 'null')
        if (!legacy || legacy.id !== id || retention.cacheExpired(legacy.saved_at)) continue
        const draft: AgentDraft = saved || {text:legacy.turn.display_message || legacy.turn.message, files:{}, context:'', request:null, clientId:randomUUID(), saved_at:legacy.saved_at}
        draft.request = legacy.turn
        for (const [role, datasetId] of Object.entries<string>(legacy.turn.attachments || {})) {
          if (role === 'protein_context_id') draft.context = datasetId
          else draft.files[role] = {name:attachmentLabel(role), datasetId, fileId:role === 'protein_dataset_id' ? legacy.turn.values?.protein_file_id : undefined}
        }
        saved = draft
        sessionStorage.removeItem(key)
      } catch { /* legacy draft belongs to a different scope or is malformed */ }
    }
  }
  if (!currentOwner() || composerSession.value !== id) return
  const draft = saved && !retention.cacheExpired(saved.saved_at) ? saved : null
  message.value = draft?.text || ''
  pendingFiles.value = draft?.files || {}
  draftContext.value = draft?.context || ''
  pendingRequest.value = draft?.request || null
  draftId.value = draft?.clientId || randomUUID()
  draftLoading.value = false
  persistComposer()
}
// Input that would be lost by leaving: composer text, local files not uploaded yet, or unsaved editor changes.
const hasUnsavedInput = () => Boolean(message.value.trim() || Object.values(pendingFiles.value).some(item => item.file && !item.datasetId) || editorDirty.value || reviewState.value.dirty || Boolean(session.value?.proposals.some(p => inlineDirty.value[p.id])))
function confirmUnload(event: BeforeUnloadEvent) { if (hasUnsavedInput()) { event.preventDefault(); event.returnValue = '' } }
// A forced sign-in redirect keeps the composer draft, so it is never blocked.
onBeforeRouteLeave(to => to.path === '/login' || !hasUnsavedInput() || window.confirm(t('platform.unsavedChanges.leave')))
const statusLabel = (value: string) => ({awaiting_approval:L('待批准','Awaiting approval'),awaiting_postprocessing_approval:L('待批准评价','Evaluation approval'),authorized:L('已授权','Authorized'),partial_succeeded:L('部分完成','Partial'),partial:L('部分完成','Partial'),cancel_requested:t('agent.session.stopping'),submitted:t('agent.session.submitted'), queued:t('agent.session.queued'), running:t('agent.session.running'), skipped:t('platform.skipped'), completed:t('agent.session.completed'), succeeded:t('agent.session.completed'), failed:t('agent.session.failed'), interrupted:t('agent.session.interrupted'), needs_input:t('agent.session.needsInput'), pending:t('agent.session.pending'), approved:t('agent.session.approved'), superseded:L('已由新方案替换','Replaced by a newer plan'), stale:t('agent.session.stale'), canceled:t('agent.session.canceled')}[value] || value || t('agent.session.waiting'))
const generationStepLabel = (value: string) => value === 'pending' ? t('agent.session.waiting') : statusLabel(value)
const workflowStepLabel = (value: string, generation?: string) => value === 'pending' ? t(generation === 'succeeded' ? 'agent.session.waitingPostprocessing' : 'agent.session.waitingGeneration') : statusLabel(value)
const attachmentLabel = (role: string) => ({protein_dataset_id:t('agent.session.proteinFile'), ligand_dataset_id:t('agent.session.ligand'), protein_context_id:'Protein Context'}[role] || role)
const toolLabel = (tool: string) => ({read_skill:t('agent.session.readSkill'), get_capabilities:t('agent.session.capabilities'), get_context:t('agent.session.context'), find_diagnostic_jobs:t('agent.session.findDiagnosticJobs'), get_job_diagnostics:t('agent.session.jobDiagnostics'), read_job_diagnostic:t('agent.session.readDiagnostic'), preview_workflow:t('agent.session.preview'), get_workflow_status:t('agent.session.workflowStatus'), query_results:t('agent.session.queryResults'), get_parameter_spec:t('agent.session.parameters'), get_metric_spec:t('agent.session.metricDefinitions'), search_project_knowledge:t('agent.session.knowledge'), list_project_knowledge:t('agent.session.knowledge'), read_project_knowledge:t('agent.session.knowledge'), inspect_session_protein:t('agent.session.inspect'), list_available_inputs:t('agent.session.availableInputs')}[tool] || t('agent.session.processing'))
const intentLabel = (value: string) => ({task_plan:L('阶段方案','Stage plan'), prepare_postprocessing:t('agent.session.postprocessing'), auto:t('agent.session.attachments'), ask:t('agent.session.ask'), bind:t('agent.session.bind'), select_context:t('agent.session.selectContext'), prepare:t('agent.session.prepare'), plan:t('agent.session.plan'), modify:t('agent.session.modify'), workflow:t('agent.session.workflow'), postprocessing:t('agent.session.postprocessing'), selection:t('agent.session.selection'), retry_postprocessing:t('agent.session.retryPostprocessing')}[value] || value)
const stageLabel = (stage: string) => te(`agent.session.stages.${stage}`) ? t(`agent.session.stages.${stage}`) : toolLabel(stage)
function errorText(value: any) {
  const code = value.error_code || value.warning_code
  if (value.review_pending) return L('候选方案已保留，最终检查未完成。请重试检查。', 'The candidate plan is preserved. Retry its final check.')
  if (code === 'AGENT_DECISION_INVALID') return L('模型未能正确填写方案字段，已有输入已保留。请重试。', 'The model could not fill the plan fields correctly. Your inputs are preserved. Retry.') + (value.validation_errors?.length ? ` (${value.validation_errors.map((item: any) => item.path).join(', ')})` : '')
  if (code === 'INPUT_CHANGED' && value.committed_effects?.length) return L('输入已保存，但后续方案更新发生冲突。请查看当前方案。', 'Inputs were saved, but the subsequent plan update conflicted. Review the current plan.')
  if (code === 'AGENT_OUTPUT_TRUNCATED' && value.error_stage?.startsWith('output_evidence')) return L('分析回答的核验未完成，已有计算结果仍然保留。请重试分析。', 'The analysis could not finish verification. Computed results are preserved. Retry the analysis.')
  return systemErrorMessage(value, t('agent.session.operationFailed'))
}
const decisionErrors = new Set(['COMMAND_REQUIRED', 'INVALID_DECISION'])
function recoveryText(value: any) { if (value.error_code === 'INPUT_CHANGED' && value.committed_effects?.length || value.error_code === 'AGENT_OUTPUT_TRUNCATED' && value.error_stage?.startsWith('output_evidence')) return ''; const action = decisionErrors.has(value.error_code) ? 'retry_once_then_switch_model' : value.recovery_action; return te(`agent.recoveryActions.${action}`) ? t(`agent.recoveryActions.${action}`) : '' }
function canRetry(turn: AgentSessionTurn) { return !turn.resumed_by && turn.attempt < 3 && ['interrupted', 'failed'].includes(turn.status) && (decisionErrors.has(turn.response.error_code) || turn.response.retryable === true || (!turn.response.error_code && turn.status === 'interrupted')) }
// Text of the last error caused by a transient failure (network, timeout, server). The next successful refresh clears it,
// unless another message has replaced it in the meantime.
let transientError = ''
// Bumped when a refresh succeeds after a failed one, so result cards that failed meanwhile load again.
const syncRecovery = ref(0)
let refreshFailed = false
function fail(e: any) {
  transientError = ''
  if (e?.response?.status === 404 && e?.config?.url === `/api/v1/agent/sessions/${session.value?.id || route.query.session_id}`) {
    session.value = null; pendingRequest.value = null; message.value = ''
    error.value = t('platform.retentionResourceGone')
    return
  }
  // A field-validation list (422) holds raw server text; it falls through to the localized "invalid input" message.
  const detail = e?.response?.data?.detail; const code = detail?.error_code || e?.message
  error.value = code && te(`agent.errors.${code}`) ? t(`agent.errors.${code}`) : code && te(`settings.${code}`) ? t(`settings.${code}`) : requestErrorMessage(e, t('agent.session.operationFailed'))
  if (['network', 'timeout', 'server'].includes(requestErrorKind(e) || '')) transientError = error.value
}
// A response from an unmounted identity must not update the current composer.
function operationCurrent(generation: number) { return currentOwner() && generation === restoreGeneration }
// After a failed send the request stays ready for an identical retry. Any edit turns it back into a draft, so the next send
// builds a new request from the current input; attachments that were already uploaded are reused.
function editFailedRequest(whileLoading = false) {
  const request = pendingRequest.value
  if (!request || (busy.value && !whileLoading)) return
  pendingRequest.value = null
  // A request restored after a reload holds its attachments only in the request itself.
  for (const [role, id] of Object.entries<string>(request.attachments || {})) {
    if (role === 'protein_context_id') { if (!draftContext.value && !Object.keys(pendingFiles.value).length) draftContext.value = id }
    else if (!pendingFiles.value[role] && !draftContext.value) pendingFiles.value[role] = {name:attachmentLabel(role), datasetId:id, fileId:role === 'protein_dataset_id' ? request.values?.protein_file_id : undefined}
  }
}
async function guarded(fn: () => Promise<void>) { if (!currentOwner()) return; busy.value = true; error.value = ''; try { await fn() } catch (e) { if (currentOwner()) fail(e) } finally { busy.value = false } }
function taskPlanRevision(plan: AgentSessionState['task_plan']) {
  if (!plan) return ''
  return JSON.stringify([plan.proposal_id, plan.version, plan.state, plan.definition?.stage, plan.run?.phase, plan.run?.round])
}
function optimizationPlan(seed: Record<string, any>, contextId: string) {
  const engine = seed.engine
  return { generator: engine, template: engine === 'epso' ? 'ecloud_epso' : 'delete', seed_source: seed, protein_context_id: contextId, generation: { engine }, postprocessing: { enabled: false, prefilters: [] } }
}
function mergeState(next: AgentSessionState) {
  const previous = session.value
  if (previous?.research_task_state === 'blocked' && previous.research_task_id === next.research_task_id) {
    next.research_task_state = 'blocked'
    next.pending_requirements = []
    next.pending_clarification_fields = []
  }
  const planChanged = previous?.id === next.id && taskPlanRevision(previous.task_plan) !== taskPlanRevision(next.task_plan)
  const preferences = (next as any).workflow_preferences || {}
  const seed = next.assets.optimization_seed || preferences.seed_source
  const optimizationEngine = preferences.generation?.engine || seed?.engine
  const plannedSeed = next.task_plan?.definition?.workflow?.seed_source
  const planMatchesOptimization = Boolean(optimizationEngine && seed && next.task_plan?.definition?.workflow?.generator === optimizationEngine
    && plannedSeed?.dataset_id === seed.dataset_id && plannedSeed?.file_id === seed.file_id)
  const hasRestorableOptimization = Boolean(optimizationEngine && seed && !next.workflow && !planMatchesOptimization)
  if (draftOpen.value && planChanged && !hasRestorableOptimization) {
    if (newDraftDirty.value) taskPlanChangedDuringDraft.value = true
    else {
      draftOpen.value = false
      newWorkflowPlan.value = null
      newWorkflowDraft.value = {}
      taskPlanChangedDuringDraft.value = false
    }
  }
  if (session.value?.id === next.id) next.turns = next.turns.map(turn => {
    const old = session.value?.turns.find(t => t.id === turn.id)
    return old && old.attempt === turn.attempt && ['queued', 'running'].includes(turn.status) && (!['queued', 'running'].includes(old.status) || (old.response.stream_seq || 0) > (turn.response.stream_seq || 0)) ? old : turn
  })
  if (session.value?.id === next.id) {
    const ids = new Set(next.turns.map(turn => turn.id))
    next.turns = [...session.value.turns.filter(turn => !ids.has(turn.id)), ...next.turns]
    const proposalIds = new Set(next.proposals.map(p => p.id))
    next.proposals = [...session.value.proposals.filter(p => !proposalIds.has(p.id)), ...next.proposals]
  }
  session.value = next
  if (taskBlocked.value) {
    // Keep stored history; close local action editors for this blocked task.
    draftOpen.value = false
    addOpen.value = false
    reviewProposal.value = null; structureSelection.value = null; editorProposal.value = null
    deleteEditId.value = ''; optimizationSource.value = null; staleDraft.value = null; closeIntent.value = null
    reviewState.value = {dirty:false,valid:false,changes:{}}; editorDirty.value = false; deleteDirty.value = false
    newDraftDirty.value = false; newWorkflowPlan.value = null
  }
  if (previous?.research_task_state === 'blocked' && previous.research_task_id !== next.research_task_id) {
    editorDrafts.value = {}
  }
  pendingPose.value = next.pose_preparation_draft || null
  const latestPlanMatchesOptimization = Boolean(optimizationEngine && seed && next.task_plan?.definition?.workflow?.generator === optimizationEngine
    && next.task_plan?.definition.workflow?.seed_source?.dataset_id === seed.dataset_id
    && next.task_plan?.definition.workflow?.seed_source?.file_id === seed.file_id)
  if (!taskBlocked.value && optimizationEngine && seed && !next.workflow && !latestPlanMatchesOptimization && (!draftOpen.value || !newDraftDirty.value)) {
    const completeSeed = { ...seed, engine: optimizationEngine }
    newWorkflowPlan.value = optimizationPlan(completeSeed, next.assets.protein_context_id || '')
    if (!draftOpen.value) {
      draftRevision.value = next.input_revision
      draftOpen.value = true
      detailsOpen.value = true
    }
  }
}
async function refresh() {
  if (!session.value) return
  const id = session.value.id, generation = ++refreshGeneration
  const result = await getAgentSession(id)
  if (!currentOwner() || generation !== refreshGeneration || session.value?.id !== id) return
  const changed = session.value.input_revision !== result.data.input_revision || session.value.phase !== result.data.phase
  if (transientError && error.value === transientError) error.value = ''
  transientError = ''
  if (refreshFailed) { refreshFailed = false; syncRecovery.value++ }
  mergeState(result.data)
  if (changed || (!spec.value && specAttempts < 3 && Date.now() >= specRetryAt)) await hydrate()
}
async function schedule() { try { await refresh() } catch (e) { if (currentOwner()) { refreshFailed = true; fail(e) } } finally { if (currentOwner()) timer = setTimeout(schedule, 4000) } }
function closeLocalEditors() {
  if (deleteDirty.value && deleteEditId.value) { closeIntent.value='delete'; return false }
  if (reviewState.value.dirty && (reviewProposal.value || structureSelection.value)) { closeIntent.value='structure'; return false }
  if (editorDirty.value && editorProposal.value) { closeIntent.value='workflow'; return false }
  if (newDraftDirty.value && draftOpen.value) { closeIntent.value='newworkflow'; return false }
  reviewProposal.value = null; structureSelection.value = null; editorProposal.value = null; draftOpen.value = false
  reviewState.value = {dirty:false,valid:false,changes:{}}; editorDirty.value = false
  deleteEditId.value='';deleteDirty.value=false;resultTarget.value=null;optimizationSource.value=null;pendingPose.value=null;newWorkflowPlan.value=null;staleDraft.value=null;closeIntent.value=null
  filters.value = []; sortBy.value = 'docked.affinity'; descending.value = false; topK.value = 20; addOpen.value = false; attachmentPickerOpen.value = false
  return true
}
async function updateSessionRoute(id = '') {
  if (!currentOwner()) return
  if (props.compact) attachedSessionId.value = id
  else await router.replace({ query: id ? {session_id:id} : {} })
}
async function create() {
  if (!closeLocalEditors()) return
  navigationOpen.value = false
  restoreGeneration++; refreshGeneration++
  persistComposer(); draftLoading.value = true
  session.value = null; spec.value = null; error.value = ''; clarificationAnswers.value = {}; exportNote.value = ''
  addOpen.value = false; nearBottom.value = true; hasNewMessages.value = false
  await switchComposer('')
  await updateSessionRoute()
}
async function removeSession() {
  if (!session.value || !window.confirm(t('agent.session.confirmSession'))) return
  const id = session.value.id
  await guarded(async () => {
    await deleteAgentSession(id)
    await create()
    history.value = (await listAgentSessions()).data
  })
}
// A conversation chosen while another one is still loading is remembered and loaded right after it, so the last
// choice wins instead of being dropped. Loads never overlap, which keeps the content in step with the address bar.
const switchingSession = ref(false)
let queuedSession = ''
async function restore(id: string) {
  if (!id) return
  if (switchingSession.value) { queuedSession = id; return }
  if (!closeLocalEditors()) return
  const generation = ++restoreGeneration; refreshGeneration++
  restoringView = true; switchingSession.value = true
  await guarded(async () => {
    const result = await getAgentSession(id)
    if (!operationCurrent(generation)) return
    persistComposer(); draftLoading.value = true
    spec.value = null; specAttempts = 0; specRetryAt = 0; specLoadError.value = ''
    session.value = result.data; pendingPose.value=result.data.pose_preparation_draft || null; clarificationAnswers.value = {}
    if (composerSession.value !== id) await switchComposer(id)
    else draftLoading.value = false
    if (!operationCurrent(generation)) return
    navigationOpen.value = false
    await updateSessionRoute(id); await hydrate(); await nextTick()
    if (conversation.value && conversationTop.value >= 0) { conversation.value.scrollTop = conversationTop.value; onScroll() } else await scrollToBottom()
  })
  switchingSession.value = false
  if (generation === restoreGeneration) restoringView = false
  const next = queuedSession; queuedSession = ''
  if (active && next && next !== session.value?.id) await restore(next)
}
async function hydrate() {
  const s = session.value; if (!s) return
  const seed=s.assets.optimization_seed
  if (seed?.engine && !s.workflow) newWorkflowPlan.value={generator:seed.engine,generation:{engine:seed.engine},seed_source:seed,postprocessing:{enabled:false,prefilters:[]}}
  const generation = restoreGeneration
  let nextSpec: any
  try { nextSpec = (await getAgentSessionSpecs(s.id)).data }
  catch (failure: any) {
    if (session.value?.id === s.id && generation === restoreGeneration) {
      specAttempts += 1; specRetryAt = Date.now() + 5000 * 2 ** Math.min(specAttempts - 1, 2)
      specLoadError.value = L('参数规格加载失败，请重试。','Parameter specifications could not be loaded. Retry.')
    }
    throw failure
  }
  if (!active || session.value?.id !== s.id || generation !== restoreGeneration) return
  spec.value = nextSpec; specAttempts = 0; specLoadError.value = ''
  const datasetIds = new Set([s.assets.protein_dataset_id, s.prepared_receptor?.source?.dataset_id, ...s.proposals.filter(p => p.kind === 'prepare').map(p => p.payload.protein_dataset_id)].filter(Boolean))
  for (const id of datasetIds) {
    const dataset = (await getBackendDataset(id)).data
    if (!active || session.value?.id !== s.id || generation !== restoreGeneration) return
    for (const file of dataset.files) fileNames.value[file.id] = file.original_filename
  }
}
async function submitMessage(displayMessage?: string, contextMessage?: string, intent: 'auto' | 'new_task' = 'auto') {
  if (initializing.value || busy.value || turnRunning.value || draftLoading.value || !currentOwner() || (composerSession.value && !session.value)) return
  const generation = restoreGeneration
  // The text is fixed when Send is pressed. Input typed while attachments upload or the request is sent is not merged
  // into this request; it stays in the box as the next draft.
  const text = message.value
  uploadNotice.value = ''; cancelingAttachments.value = false
  let accepted = false, failureStage = 'send', filename = ''
  await guarded(async () => {
    try {
      if (!pendingRequest.value && intent === 'new_task') {
        if (!session.value || !text.trim()) return
        pendingRequest.value = {client_request_id:randomUUID(), intent, message:text, base_revision:session.value.input_revision}
      }
      if (!pendingRequest.value) {
        uploadingAttachments.value = Object.keys(pendingFiles.value).length > 0
        const attachments: Record<string, string> = !taskBlocked.value && draftContext.value ? {protein_context_id:draftContext.value} : {}
        for (const [role, item] of Object.entries(taskBlocked.value ? {} : pendingFiles.value)) {
          const protein = role === 'protein_dataset_id'
          failureStage = 'upload'; filename = item.name
          await uploadComposerAttachment(role, item, generation)
          if (!operationCurrent(generation) || cancelingAttachments.value) break
          if (protein && item.datasetId) {
            failureStage = 'structure'
            const prepared = await ensureProteinFile(item.datasetId, item.fileId)
            item.fileId = prepared.fileId
          }
          if (!operationCurrent(generation) || cancelingAttachments.value) break
          if (item.datasetId) attachments[role] = item.datasetId
        }
        uploadingAttachments.value = false
        if (!operationCurrent(generation)) return
        if (cancelingAttachments.value) {
          const items = Object.values(pendingFiles.value)
          const uploaded = items.filter(item => item.datasetId).length
          uploadNotice.value = L(`已上传 ${uploaded} 个，已取消 ${items.length - uploaded} 个。草稿已保留。`, `${uploaded} uploaded, ${items.length - uploaded} canceled. Draft preserved.`)
          return
        }
        pendingRequest.value = {client_request_id:randomUUID(), intent:'auto', message:contextMessage || text, ...(typeof displayMessage === 'string' ? {display_message:displayMessage} : {}), base_revision:session.value?.input_revision || 0, attachments, values:!taskBlocked.value && pendingFiles.value.protein_dataset_id?.fileId ? {protein_file_id:pendingFiles.value.protein_dataset_id.fileId} : {}}
      }
      failureStage = 'send'; filename = ''
      const sent = pendingRequest.value!.display_message || pendingRequest.value!.message || ''
      if (session.value) {
        await sendAgentSessionTurn(session.value.id, pendingRequest.value)
        accepted = true
        if (!operationCurrent(generation)) return
        await refresh()
      } else {
        const result = await startAgentSession({client_session_id:draftId.value, turn:pendingRequest.value})
        accepted = true
        if (!operationCurrent(generation)) return
        mergeState(result.data); await updateSessionRoute(result.data.id); await hydrate()
      }
      if (!operationCurrent(generation)) return
      pendingRequest.value = null; addOpen.value = false
      message.value = unsentRemainder(message.value, sent); pendingFiles.value = {}; draftContext.value = ''
      if (session.value && composerSession.value !== session.value.id) {
        saveAgentDraft(agentDraftKey(draftOwner, draftScope, composerSession.value), {text:'', files:{}, context:'', request:null, clientId:draftId.value, saved_at:Date.now()})
        composerSession.value = session.value.id; localStorage.setItem(lastSessionKey, session.value.id); sessionStorage.setItem(lastSessionKey, session.value.id); persistComposer()
      }
      const nextHistory = (await listAgentSessions()).data
      if (operationCurrent(generation)) { history.value = nextHistory; await scrollToBottom() }
    } catch (e: any) {
      if (!operationCurrent(generation)) return
      if (!accepted && [400, 404, 409, 413, 422].includes(e?.response?.status)) {
        pendingRequest.value = null
        await refresh()
      }
      fail(e)
      if (cancelingAttachments.value) uploadNotice.value = L('暂未确认附件入库结果，请重试确认后再发送。', 'Upload result is not confirmed. Retry confirmation before sending.')
      error.value = `${stageLabel(failureStage)}${filename ? ' · ' + filename : ''}: ${error.value}`
    } finally { uploadingAttachments.value = false; cancelingAttachments.value = false }
  })
}
async function submitClarification() {
  if (!canSubmitClarification.value || busy.value || turnRunning.value || pendingRequest.value) return
  const task = clarificationTurn.value?.message || session.value?.goal || ''
  const completedMessage = clarificationMessage(task, requirements.value, clarificationAnswers.value, confirmedDeleteEdit.value, clarificationFields.value)
  if (completedMessage.length > 4000) { error.value = t('agent.session.informationTooLong'); return }
  if (message.value.trim()) { error.value = t('agent.session.unsentMessage'); return }
  const visible = requirements.value.map(requirement => {
    const field = clarificationField(requirement)
    if (requirementKind(requirement, clarificationFields.value) === 'count') return `${t('agent.session.generationCount')}：${clarificationAnswers.value[requirement]}`
    if (requirementKind(requirement, clarificationFields.value) === 'delete') return t('agent.session.confirmedEdit', {mode:confirmedDeleteEdit.value?.mode})
    if (field?.type === 'engine' || field?.type === 'confirmation') return `${t('agent.ui.' + field.id)}：${clarificationAnswers.value[requirement]}`
    return `${requirement}：${clarificationAnswers.value[requirement] || ''}`
  }).join('；')
  message.value = visible
  await submitMessage(visible, completedMessage)
}
async function stopCurrentTurn() {
  const current = session.value
  const turn = current?.turns.find(turn => ['queued', 'running'].includes(turn.status))
  if (!current || !turn || stoppingTurn.value) return
  stoppingTurn.value = true
  error.value = ''
  try {
    const { data } = await stopAgentSessionTurn(current.id, turn.id)
    if (session.value?.id !== current.id) return
    Object.assign(turn, data)
    await refresh()
  } catch (e) { fail(e) } finally { stoppingTurn.value = false }
}
async function resume(turn: AgentSessionTurn) { await guarded(async () => { await resumeAgentSessionTurn(session.value!.id, turn.id); await refresh() }) }
async function loadHistory() { const el = conversation.value, height = el?.scrollHeight || 0, top = el?.scrollTop || 0; await guarded(async () => { const { data } = await getAgentSessionHistory(session.value!.id, session.value!.turns.length); session.value!.turns = [...data.reverse(), ...session.value!.turns]; const ids = new Set(session.value!.proposals.map(p => p.id)); session.value!.proposals = [...data.flatMap(t => t.proposals || []).filter(p => !ids.has(p.id)), ...session.value!.proposals]; await nextTick(); if (el) el.scrollTop = top + el.scrollHeight - height }) }
async function retry(turn: AgentSessionTurn) { await guarded(async () => { await sendAgentSessionTurn(session.value!.id, {...turn.request, retry:true}); await refresh() }) }
function bindContext(id: string) { if (id && !busy.value && !computing.value && !turnRunning.value) { editFailedRequest(); draftContext.value = id; pendingFiles.value = {}; addOpen.value = false; contextPickerOpen.value = false } }
function selectListedContext(id: string, context?: ProteinContextListItem) { if (context) contexts.value = [context]; bindContext(id) }
function bindFile(dataset: BackendDataset, file: BackendDatasetFile) {
  if (busy.value || computing.value || turnRunning.value) return
  const id = dataset.id, fileId = file.id
  const protein = /\.(pdb|cif|mmcif)$/i.test(file.original_filename)
  if (!protein && (dataset.files.length !== 1 || !/\.(sdf|mol|mol2)$/i.test(dataset.files[0].original_filename))) {
    error.value = t('agent.session.singleLigandDataset'); return
  }
  editFailedRequest()
  draftContext.value = ''; pendingFiles.value[protein ? 'protein_dataset_id' : 'ligand_dataset_id'] = {datasetId:id, fileId, name:file.original_filename}; addOpen.value = false; attachmentPickerOpen.value = false
}
async function loadDatasets() { await guarded(async () => { datasets.value = await listAllBackendDatasets() }) }
function loadAttachments() { attachmentPickerOpen.value = true }
async function uploadRequestedInput() { addOpen.value = true; await nextTick(); attachmentInput.value?.click() }
async function confirmInputFile(datasetId: string, fileId: string) {
  if (busy.value || turnRunning.value || computing.value || pendingRequest.value || !session.value) return
  const id = session.value.id, generation = restoreGeneration
  let dataset: BackendDataset | undefined
  await guarded(async () => { dataset = (await getBackendDataset(datasetId)).data })
  if (!dataset || session.value?.id !== id || generation !== restoreGeneration) return
  const file = dataset.files.find(item => item.id === fileId)
  if (!file) { error.value = t('agent.inputSelection.fileChanged'); return }
  bindFile(dataset, file)
  await saveStructuredInputs()
  if (!error.value && session.value?.id === id && generation === restoreGeneration) await openStructureSelection()
}
function loadContexts() { contextPickerOpen.value = true }
let stageCheck = 0
// The last reason a chosen file was refused; cleared once an acceptable file is chosen, unless another error replaced it.
let stageRejection = ''
async function stageFile(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  if (!file) return
  input.value = ''
  if (!/\.(pdb|cif|mmcif|sdf|mol|mol2)$/i.test(file.name)) { error.value = stageRejection = t('agent.session.supportedFiles'); return }
  const check = ++stageCheck
  const issue = await checkUploadFile(file, ['pdb', 'cif', 'mmcif', 'sdf', 'mol', 'mol2'])
  if (check !== stageCheck || !currentOwner()) return
  if (issue) { error.value = stageRejection = `${file.name}: ${uploadCheckMessage(issue, file.name)}`; return }
  if (stageRejection && error.value === stageRejection) error.value = ''
  editFailedRequest()
  draftContext.value = ''; pendingFiles.value[/\.(pdb|cif|mmcif)$/i.test(file.name) ? 'protein_dataset_id' : 'ligand_dataset_id'] = {name:file.name, file}; addOpen.value = false
}
async function saveStructuredInputs() {
  if (!session.value) return
  const id = session.value.id, generation = restoreGeneration, files = pendingFiles.value
  await guarded(async () => {
    const assets: Record<string, string> = {}
    for (const [role, item] of Object.entries(files)) {
      if (!item.datasetId && item.file) item.datasetId = (role === 'protein_dataset_id' ? await uploadProteinDataset(item.file, 'agent_protein') : (await uploadBackendDataset({name:item.name, kind:'agent_ligand', file:item.file, fileRole:'ligand_input'})).data).id
      if (!operationCurrent(generation) || session.value?.id !== id) return
      if (!item.datasetId) continue
      if (role === 'protein_dataset_id') item.fileId = (await ensureProteinFile(item.datasetId, item.fileId)).fileId
      if (!operationCurrent(generation) || session.value?.id !== id) return
      assets[role] = item.datasetId
    }
    if (!operationCurrent(generation) || session.value?.id !== id) return
    await workflowCommand(id, {command_id:randomUUID(), expected_version:session.value.input_revision, operation:'bind', changes:assets})
    if (!operationCurrent(generation) || session.value?.id !== id) return
    await refresh()
    if (!operationCurrent(generation) || session.value?.id !== id) return
    const fileId = files.protein_dataset_id?.fileId
    if (fileId) {
      await workflowCommand(id, {command_id:randomUUID(), expected_version:session.value.input_revision, operation:'select_context', changes:{protein_file_id:fileId}})
      if (!operationCurrent(generation) || session.value?.id !== id) return
      await refresh()
    }
    if (!operationCurrent(generation) || session.value?.id !== id) return
    pendingFiles.value = {}; addOpen.value = false
  })
}
async function sendCommand(operation: string, changes: Record<string, any> = {}, extra: Record<string, any> = {}) {
  if (!session.value || busy.value || taskBlocked.value && operation !== 'cancel') return false
  let success = false
  await guarded(async () => {
    await workflowCommand(session.value!.id, { command_id: randomUUID(), expected_version: session.value!.input_revision, operation, changes, ...extra })
    await refresh()
    success = true
  })
  return success
}
async function openEditor(kind: 'protein' | 'delete') {
  if (!session.value || kind === 'delete' && computing.value) return
  await guarded(async () => {
    const edit = (await openWorkflowEditor(session.value!.id, kind, session.value!.input_revision)).data
    if(kind === 'delete'){deleteEditId.value=edit.id;deleteDirty.value=false}else await openStructureSelection()
  })
}
function isCurrentProposal(proposal: Proposal) {
  const current = session.value?.proposals.find(p => p.id === proposal.id)
  return Boolean(!taskBlocked.value && current?.status === 'pending' && (current.research_task_id || null) === (session.value?.research_task_id || null) && current.action_hash === proposal.action_hash &&
    ((proposal.input_revision ?? proposal.payload.input_revision) == null || (proposal.input_revision ?? proposal.payload.input_revision) === session.value?.input_revision))
}
function locateProposal(proposal: Proposal) {
  const action = document.getElementById(`action-${proposal.id}-${proposalAnchors.value[proposal.id]}`)
  if (action) { void focusAction(action); return }
  detailsOpen.value = true
  if (proposal.kind === 'task_plan') { if (proposal.payload.task_plan?.stage === 'preparation') void openPreparation(proposal); return }
  if (proposal.kind === 'prepare') openPreparation(proposal)
  else { const card = document.getElementById(`proposal-${proposal.id}`); const summary = card?.querySelector('details'); if (summary) summary.open = true; card?.scrollIntoView({block:'center',behavior:'smooth'}) }
}
async function focusAction(target: HTMLElement) {
  if (!desktopDetails.value) detailsOpen.value = false
  navigationOpen.value = false
  await nextTick()
  const el = conversation.value
  if (el) el.scrollTop += target.getBoundingClientRect().top - el.getBoundingClientRect().top - 12
  target.focus({ preventScroll: true })
}
function focusCurrentPlan() {
  const target = draftOpen.value ? draftActionTarget.value?.closest<HTMLElement>('section') : taskPlanActionTarget.value?.closest<HTMLElement>('section')
  if (target) void focusAction(target)
  else detailsOpen.value = true
}
let preparationFocus: HTMLElement | null = null
function restorePreparationFocus() { preparationFocus?.focus() }
async function openStructureSelection() {
  if (!session.value || busy.value || computing.value || turnRunning.value) return
  if (!session.value.assets.protein_dataset_id && !session.value.assets.protein_context_id && !session.value.assets.prepared_receptor_id) { addOpen.value = true; await loadAttachments(); return }
  if (reviewState.value.dirty) { closeIntent.value='structure'; return }
  preparationFocus = document.activeElement as HTMLElement | null
  const current = session.value, revision = current.input_revision
  await guarded(async () => {
    const context = current.assets.protein_context_id ? (await getProteinContext(current.assets.protein_context_id)).data : {}
    if (session.value?.id !== current.id || session.value.input_revision !== revision) return
    const values = Object.fromEntries(Object.entries(current.confirmed_fields).map(([key, field]) => [key, field.value]))
    structureSelection.value = JSON.parse(JSON.stringify({...context, ...values, site_request: current.workflow_preferences?.site_request, protein_dataset_id:current.assets.protein_dataset_id || ('protein_dataset_id' in context ? context.protein_dataset_id : undefined), prepared_receptor_id:current.assets.prepared_receptor_id || ('prepared_receptor_id' in context ? context.prepared_receptor_id : undefined), session_id:current.id}))
    reviewProposal.value = null; reviewRevision.value = revision; reviewSaved.value = false
    reviewState.value = {dirty:false,valid:false,changes:{}}; detailsOpen.value = false
  })
}
async function openPreparation(proposal: Proposal) {
  if (proposal.job_status === 'succeeded' && proposal.execution.prepared_receptor_id) {
    if (!session.value || busy.value || turnRunning.value || computing.value) return
    if (!session.value.assets.protein_context_id && session.value.assets.prepared_receptor_id !== proposal.execution.prepared_receptor_id) {
      if (!await sendCommand('bind', { prepared_receptor_id: proposal.execution.prepared_receptor_id })) return
    }
    await openStructureSelection()
    return
  }
  if (!reviewProposal.value) preparationFocus = document.activeElement as HTMLElement | null
  structureSelection.value = null
  reviewProposal.value = JSON.parse(JSON.stringify(proposal.kind === 'task_plan' ? {...proposal, payload: {...proposal.payload, ...proposal.payload.task_plan.preparation}} : proposal)); reviewRevision.value = proposal.input_revision ?? proposal.payload.input_revision ?? (proposal.status === 'pending' ? session.value!.input_revision : null)
  reviewState.value = {dirty:false,valid:false,changes:{}}; reviewSaved.value = false; error.value = ''
}
function closePreparation(open: boolean) {
  if (open || busy.value) return
  if (reviewState.value.dirty) { closeIntent.value = 'structure'; return }
  reviewProposal.value = null; structureSelection.value = null
  reviewState.value = {dirty:false,valid:false,changes:{}}
}
function showLatestPreparation() {
  if (reviewState.value.dirty) { closeIntent.value='structure'; return }
  if (structureSelection.value) {
    structureSelection.value = null; reviewState.value = {dirty:false,valid:false,changes:{}}
    void openStructureSelection(); return
  }
  const latest = session.value?.proposals.find(p => p.id === session.value?.task_plan?.proposal_id && p.payload.task_plan?.stage === 'preparation') || [...(session.value?.proposals || [])].reverse().find(p => p.kind === 'prepare')
  if (latest) openPreparation(latest)
}
async function savePreparation(approveAfterSave = false) {
  if (reviewProposal.value?.kind === 'task_plan') {
    if (!session.value?.task_plan || busy.value || reviewReadonly.value || !reviewState.value.valid) return
    const definition = JSON.parse(JSON.stringify(session.value.task_plan.definition))
    definition.preparation = {...definition.preparation, ...reviewState.value.changes}
    if (JSON.stringify(definition.preparation.prepared_spec.edits) !== JSON.stringify((session.value.task_plan.definition.preparation?.prepared_spec as any)?.edits)) {
      delete definition.preparation.target_chain_component_id
      delete definition.preparation.chain_selection_reason
    }
    if (await sendCommand(approveAfterSave ? 'approve_task_plan' : 'patch_task_plan', definition, {task_plan_version:session.value.task_plan.version})) {
      reviewState.value.dirty = false
      if (approveAfterSave) { reviewProposal.value = null; detailsOpen.value = true }
      else { reviewTaskPreparation(); reviewSaved.value = true }
    }
    return
  }
  if (approveAfterSave && !structureSelection.value && !reviewState.value.dirty) { await approvePreparation(); return }
  if (busy.value || reviewReadonly.value || (!structureSelection.value && !reviewState.value.dirty) || !reviewState.value.valid) return
  const id = session.value!.id, revision = reviewRevision.value!, changes = JSON.parse(JSON.stringify(reviewState.value.changes))
  await guarded(async () => {
    const edit = (await openWorkflowEditor(id, 'protein', revision)).data
    try {
      const saved = (await saveWorkflowEditor(edit.id, changes, approveAfterSave)).data
      await clearEditorDraft('structure')
      await refresh()
      if (session.value?.id !== id) return
      if (saved.approved) { reviewProposal.value = null; structureSelection.value = null; reviewState.value.dirty = false; detailsOpen.value = true; return }
      const proposal = session.value.proposals.find(p => p.id === saved.proposal_id)
      if (proposal) { openPreparation(proposal); reviewSaved.value = true }
      else if (saved.reused_preparation || session.value.assets.protein_context_id) { structureSelection.value = null; reviewState.value.dirty = false }
      else throw new Error(t('agent.ui.invalidEditor'))
    } catch (e) { await cancelWorkflowEditor(edit.id).catch(() => {}); throw e }
  })
}
async function approve(proposal: Proposal, version = session.value?.input_revision) {
  if (!isCurrentProposal(proposal) || busy.value || turnRunning.value) return false
  return await sendCommand('approve', {}, {proposal_id:proposal.id, action_hash:proposal.action_hash,expected_version:version})
}
function reviewTaskPreparation() {
  const proposal = session.value?.proposals.find(item => item.id === session.value?.task_plan?.proposal_id)
  if (proposal?.payload.task_plan?.stage === 'preparation') void openPreparation(proposal)
}
async function saveTaskPlan(definition: Record<string, any>) {
  if (!session.value?.task_plan) return
  await sendCommand('patch_task_plan', definition, {task_plan_version:session.value.task_plan.version})
}
async function approveTaskPlan(definition: Record<string, any>) {
  if (!session.value?.task_plan) return
  await sendCommand('approve_task_plan', definition, { task_plan_version: session.value.task_plan.version })
}
async function approvePreparation() {
  if (!reviewProposal.value || reviewReadonly.value || reviewState.value.dirty || !reviewState.value.valid) return
  if (await approve(reviewProposal.value, reviewRevision.value!)) reviewProposal.value = null
}
let workflowFocus: HTMLElement | null = null
function openWorkflow(proposal: Proposal) {
  workflowFocus = document.activeElement as HTMLElement | null
  editorProposal.value = JSON.parse(JSON.stringify(proposal)); editorFilters.value = JSON.parse(JSON.stringify(session.value?.workflow?.prefilter_conditions || [])); editorDirty.value = false
}
async function saveParameterDraft(proposal: Proposal) {
  if (!session.value || busy.value) return
  await guarded(async () => {const edit=(await openWorkflowEditor(session.value!.id,'workflow',session.value!.input_revision)).data;await saveWorkflowEditorDraft(edit.id,{...workflowLocalDraft.value,proposal_id:proposal.id,draft_kind:'parameters'});editorDrafts.value={...editorDrafts.value,workflow:{id:edit.id,revision:session.value!.input_revision,changes:workflowLocalDraft.value,proposalId:proposal.id}}})
}
async function finishEditorClose(save: boolean) {
  const kind = closeIntent.value
  if (!kind || !session.value) return
  if (kind === 'delete') {
    let closed = false
    await guarded(async () => {
      if (save) {
        const saved = await deleteEditor.value?.saveDraft()
        if (saved === false) return
        editorDrafts.value = {...editorDrafts.value,delete:{id:deleteEditId.value,revision:session.value!.input_revision}}
      } else await deleteEditor.value?.discard()
      closed = true
    })
    if (!closed) return
    deleteEditId.value='';deleteDirty.value=false;closeIntent.value=null
    return
  }
  if (save) {
    let saved = false
    await guarded(async () => {
      const changes = kind === 'structure' ? reviewState.value.changes : kind === 'newworkflow' ? newWorkflowDraft.value : workflowLocalDraft.value
      const revision = kind === 'structure' ? reviewRevision.value! : session.value!.input_revision
      const edit = (await openWorkflowEditor(session.value!.id, kind === 'structure' ? 'protein' : 'workflow', revision)).data
      await saveWorkflowEditorDraft(edit.id, kind === 'structure' ? changes : {...changes,draft_kind:kind === 'newworkflow' ? 'new' : 'parameters',proposal_id:kind === 'workflow' ? editorProposal.value?.id : undefined})
      editorDrafts.value = {...editorDrafts.value, [kind]: {id:edit.id,revision,changes,proposalId:editorProposal.value?.id}}
      saved = true
    })
    if (!saved) return
  } else await clearEditorDraft(kind)
  if(kind === 'structure'){reviewProposal.value=null;structureSelection.value=null;reviewState.value={dirty:false,valid:false,changes:{}}}
  else if(kind === 'newworkflow'){draftOpen.value=false;newDraftDirty.value=false}
  else {editorProposal.value=null;editorDirty.value=false}
  closeIntent.value=null
}
async function clearEditorDraft(kind: string) {
  const draft = editorDrafts.value[kind]
  if (draft?.id) await cancelWorkflowEditor(draft.id)
  const next = {...editorDrafts.value}
  for (const [key,value] of Object.entries(next)) if (key === kind || draft?.id && value.id === draft.id) delete next[key]
  editorDrafts.value = next
  if (draft?.id && session.value?.presentation) session.value.presentation.drafts=(session.value.presentation.drafts || []).filter((item:any) => item.id !== draft.id)
}
async function restoreEditorDraft(kind: string, reference?: Record<string,any>) {
  if (!session.value || busy.value) return
  const ref = reference || editorDrafts.value[kind]
  if (!ref) return
  let saved: any
  await guarded(async () => { saved=(await getWorkflowEditor(ref.id)).data })
  if (!saved) return
  if (saved.status !== 'open') { error.value=t('agent.ui.invalidEditor'); await refresh(); return }
  const changes=saved.state.draft || {}
  const key = kind === 'protein' ? 'structure' : changes.draft_kind === 'new' ? 'newworkflow' : kind
  const proposalId=ref.proposalId || changes.proposal_id || (saved.state.workflow_plan && pendingProposal.value?.kind === 'workflow' ? pendingProposal.value.id : undefined)
  const draft = {...ref,proposalId,revision:saved.expected_version,changes}
  editorDrafts.value = {...editorDrafts.value,[key]:draft}
  if (saved.expected_version !== session.value.input_revision) {
    staleDraft.value={kind:key,...draft}
    return
  }
  if(key === 'delete'){deleteEditId.value=draft.id;return}
  if(key === 'newworkflow' || key === 'workflow' && !draft.proposalId && !saved.state.workflow_plan && draft.changes.plan) {newWorkflowPlan.value=draft.changes.plan;openNewDraft();return}
  if(key === 'selection'){filters.value=filterDrafts(draft.changes.filters || []);sortBy.value=draft.changes.sort_by || '';descending.value=Boolean(draft.changes.descending);topK.value=draft.changes.top_k ?? '';detailsOpen.value=true;return}
  if(key === 'structure') { await openStructureSelection(); if(structureSelection.value) structureSelection.value={...structureSelection.value,...draft.changes} }
  else {
    const proposal=session.value.proposals.find(item=>item.id===draft.proposalId) || pendingProposal.value
    if(proposal?.kind === 'workflow') openWorkflow(proposal)
  }
}
async function reviewStaleDraft() {
  if (!staleDraft.value || !session.value) return
  const draft = staleDraft.value
  staleDraft.value = null
  if (draft.kind === 'delete') { await openEditor('delete'); return }
  if (draft.kind === 'structure') {
    await openStructureSelection()
    if (structureSelection.value) structureSelection.value={...structureSelection.value,...draft.changes,session_id:session.value.id}
  } else if (pendingProposal.value?.kind === 'workflow') {
    editorDrafts.value={...editorDrafts.value,workflow:{...draft,revision:session.value.input_revision}}
    openWorkflow(pendingProposal.value)
  }
}
function closeWorkflow(open:boolean) {
  if (open || busy.value) return
  if (editorDirty.value) { closeIntent.value = 'workflow'; return }
  editorProposal.value = null
}
async function saveWorkflow(patch:Record<string,any>, version:number, proposal = editorProposal.value) {
  if (!proposal || !isCurrentProposal(proposal)) return
  if (await sendCommand('patch_workflow',patch,{expected_version:version,approve_after_save:true})) { editorProposal.value = null; editorDirty.value = false; await clearEditorDraft('workflow') }
}
function openNewDraft() {
  if (!session.value) return
  draftActionTurnId.value = latestTurn.value?.id || ''
  draftRevision.value = session.value.input_revision; newDraftDirty.value=false; taskPlanChangedDuringDraft.value=false; draftOpen.value = true; detailsOpen.value = true
  void nextTick(focusCurrentPlan)
}
function showLatestTaskPlan() {
  draftOpen.value = false
  newDraftDirty.value = false
  taskPlanChangedDuringDraft.value = false
  newWorkflowDraft.value = {}
  newWorkflowPlan.value = null
}
async function saveNewDraft(plan:Record<string,any>,version:number) {
  if (await sendCommand('create_workflow',plan,{expected_version:version,approve_after_save:true})) {draftOpen.value = false;newWorkflowPlan.value=null;newDraftDirty.value=false;await clearEditorDraft('newworkflow')}
}
function composerKeydown(event:KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); void submitMessage() }
}
async function cancel() { await sendCommand('cancel') }
function loadDatasetsOnDetails(event: Event) { if ((event.target as HTMLDetailsElement).open && !datasets.value.length) void loadDatasets() }
async function savePostprocessingDraft(postprocessing: Record<string, any>) { await sendCommand('prepare_postprocessing', { choice: 'run', postprocessing }, {approve_after_save:true}) }
async function skipPostprocessing() { await sendCommand('prepare_postprocessing', { choice: 'skip', evidence: 'user_selected_skip' }) }
async function preparePostprocessing(payload: Record<string, any>) { if (await sendCommand('prepare_postprocessing', { choice: 'run', ...payload })) resultTarget.value = null }
async function previewCandidates() {
  if (!postprocessingResultJobId.value || !selectionValid.value) return
  const key = selectionKey.value
  await guarded(async () => {
    const {data} = await request.post(`/api/v1/jobs/${postprocessingResultJobId.value}/postprocessing/results`, {filters:expandFilters(filters.value),sort_by:sortBy.value,descending:descending.value,limit:Math.min(3,Number(topK.value) || 3),offset:0})
    if (key !== selectionKey.value) return
    selectionPreview.value = {total:data.total,count:topK.value === '' ? data.total : Math.min(data.total,Number(topK.value)),rows:data.rows}
  })
}
async function selectCandidates() {
  if (!selectionPreview.value?.count || !candidateName.value.trim()) return
  if (await sendCommand('selection', {name:candidateName.value.trim(),filters:expandFilters(filters.value),sort_by:sortBy.value || null,descending:descending.value,top_k:topK.value === '' ? null : Number(topK.value)}, {approve_after_save:true})) {
    selectionPreview.value = null
    candidateName.value = L('候选集合 ', 'Candidates ') + String((session.value?.candidate_sets.length || 0) + 1)
  }
}
function resetSelection() { filters.value = []; sortBy.value = candidateMetrics.value['docked.affinity'] ? 'docked.affinity' : 'molecule_id'; descending.value = false; topK.value = 20; selectionPreview.value = null }
function resizeComposer() { const el = composer.value; if (el) { el.style.height = '0px'; el.style.height = `${Math.max(56, Math.min(160, el.scrollHeight))}px` } }
watch(message, () => { void nextTick(resizeComposer) })

async function download(id: string, format: string) { await guarded(async () => { const result = await exportAgentCandidateSet(session.value!.id,id,format,exportPoses.value[id] || 'docked'); const url = URL.createObjectURL(result.data); const a = document.createElement('a'); a.href=url; a.download=`candidate-set-${id}.${format}`; a.click(); URL.revokeObjectURL(url); exportNote.value = format === 'sdf' ? t('agent.session.exportSummary', { exported: result.headers['x-exported-count'], skipped: result.headers['x-skipped-count'] }) : '' }) }
function onJobEvent(event: MessageEvent) {
  try {
    const data = JSON.parse(event.data)
    if (data.event === 'job.updated' || data.event === 'ws.subscribed') { void refresh().catch(fail); return }
    const update = data.object
    if (data.event !== 'agent.turn.updated' || !session.value || update.session_id !== session.value.id) return
    const turn = session.value.turns.find(t => t.id === update.id)
    if (!turn) { void refresh().catch(fail); return }
    if (update.attempt < turn.attempt || (update.attempt === turn.attempt && (
      (turn.status !== 'running' && turn.status !== 'queued' && update.status === 'running') ||
      (update.response.stream_seq || 0) <= (turn.response.stream_seq || 0)))) return
    Object.assign(turn, {attempt:update.attempt, status:update.status, response:update.response, research_task_id:update.research_task_id ?? turn.research_task_id})
    if (update.response.safety_decision === 'refuse' && (update.research_task_id || turn.research_task_id) === session.value.research_task_id) {
      session.value.research_task_state = 'blocked'
      session.value.pending_requirements = []
      session.value.pending_clarification_fields = []
    }
    if (update.status !== 'running') void refresh().catch(fail)
  } catch { /* Persisted snapshots recover missed events. */ }
}
function onScroll() { const el = conversation.value; if (el) { if (!restoringView) conversationTop.value = el.scrollTop; nearBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80; if (nearBottom.value) hasNewMessages.value = false } }
async function scrollToBottom() { await nextTick(); const el = conversation.value; if (el) el.scrollTop = el.scrollHeight; nearBottom.value = true; hasNewMessages.value = false }
async function scrollToLatestReply() {
  await nextTick()
  const el = conversation.value
  const article = el?.querySelector(`[data-turn-id="${latestTurn.value?.id}"]`)
  const answer = article?.querySelector('.assistant-response') || article
  if (el && answer) el.scrollTop += answer.getBoundingClientRect().top - el.getBoundingClientRect().top - 12
  hasNewMessages.value = false
}
watch(() => JSON.stringify(latestTurn.value && [latestTurn.value.id,latestTurn.value.status,latestTurn.value.response.message,latestTurn.value.response.error_code]), () => { if (restoringView) return; if (nearBottom.value) void scrollToLatestReply(); else hasNewMessages.value = true })
watch(() => route.query.session_id, id => { if (props.compact || draftLoading.value || !currentOwner()) return; if (id && String(id) !== session.value?.id) void restore(String(id)); else if (!id && session.value) void create() })
watch([() => props.structureInput, session], ([input, current]) => {
  if (!currentOwner() || draftLoading.value || !props.compact || !input || current || Object.keys(pendingFiles.value).length || draftContext.value) return
  if (input.contextId) draftContext.value = input.contextId
  else pendingFiles.value.protein_dataset_id = { name: input.name, datasetId: input.datasetId, fileId: input.fileId }
}, { immediate: true })
onMounted(async () => {
  window.addEventListener('beforeunload', confirmUnload)
  websocket?.addFunc('task_state', onJobEvent)
  const last = sessionStorage.getItem(lastSessionKey) ?? localStorage.getItem(lastSessionKey) ?? ''
  await switchComposer(last)
  if (!currentOwner()) return
  await retention.load().catch(() => {})
  if (!currentOwner()) return
  await guarded(async () => {
    const rows = (await listAgentSessions()).data
    if (!currentOwner()) return
    history.value = rows
    const requested = String(props.compact ? attachedSessionId.value : route.query.session_id || '')
    const last = sessionStorage.getItem(lastSessionKey) ?? localStorage.getItem(lastSessionKey) ?? ''
    const id = [requested, last].find(value => rows.some(row => row.id === value)) || ''
    if (id) await restore(id)
    else {
      if (composerSession.value) await switchComposer('')
      if (!currentOwner()) return
      if (requested) await updateSessionRoute()
      if (props.compact && props.structureInput && !draftContext.value && !Object.keys(pendingFiles.value).length) {
        const input = props.structureInput
        if (input.contextId) draftContext.value = input.contextId
        else pendingFiles.value.protein_dataset_id = {name:input.name, datasetId:input.datasetId, fileId:input.fileId}
      }
    }
  })
  if (currentOwner()) { initializing.value = false; timer = setTimeout(schedule, 4000) }
})
onUnmounted(() => { active=false; uploadController?.abort(); restoreGeneration++; refreshGeneration++; websocket?.removeFunc('task_state', onJobEvent); clearTimeout(timer); window.removeEventListener('beforeunload', confirmUnload) })
</script>
<style scoped>
.agent-session:not(.compact-assistant) { background: #f5f7fb; }
.agent-conversation { border-radius: 16px; border-color: #e3e9f1; box-shadow: 0 2px 8px rgb(23 43 77 / 2%); }
.compact-assistant .agent-conversation { border: 0; border-radius: 0; box-shadow: none; }
.conversation-header { border-color: #edf1f6; }
.conversation-scroll { scrollbar-gutter: stable; padding-right: 4px; }
.conversation-scroll, .agent-workspace :deep(.workspace-auxiliary > div) { scrollbar-width: thin; scrollbar-color: #d8e0ec transparent; }
.agent-workspace :deep(.workspace-main) { overflow: hidden; }
.agent-workspace :deep(.workspace-auxiliary) { overflow: hidden; border: 1px solid #e3e9f1; border-radius: 16px; box-shadow: 0 2px 8px rgb(23 43 77 / 2%); }
.agent-workspace :deep(.workspace-auxiliary > header) { min-height: 62px; border-color: #edf1f6; background: #fff; }
.agent-workspace :deep(.workspace-auxiliary > header h2) { font-size: 14px; }
.agent-workspace :deep(.workspace-auxiliary > div) { background: #fbfcfe; padding: 20px; }
.conversation-empty { display: flex; min-height: 300px; flex-direction: column; align-items: center; justify-content: center; gap: 14px; padding: 40px 24px; text-align: center; }
.assistant-mark { display: grid; width: 56px; height: 56px; place-items: center; border: 1px solid #dce6f5; border-radius: 18px; color: var(--action-primary); background: #eff4fd; }
.conversation-empty h2 { margin-top: 8px; font-size: 22px; font-weight: 600; letter-spacing: -.03em; }
.conversation-empty p { max-width: 340px; font-size: 14px; line-height: 1.8; color: var(--text-secondary); }
.user-message { border-bottom-right-radius: 5px; background: #edf2fa; color: #243b5b; }
.assistant-response { color: #33435b; line-height: 1.85; }
.assistant-response :deep(:is(h1, h2, h3, h4)) { color: #1c3152; }
.assistant-response :deep(p:first-child) { margin-top: 0; }
.assistant-response :deep(p:last-child) { margin-bottom: 0; }
.assistant-response :deep(table) { display: block; max-width: 100%; overflow-x: auto; }
.assistant-response :deep(pre) { max-width: 100%; overflow-x: auto; }
.turn-action-card { overflow: hidden; border: 1px solid #e1e7f0; border-radius: 14px; background: #fff; }
.turn-action-card.action-pending { border-color: #bdcfe9; box-shadow: 0 3px 12px rgb(31 75 153 / 5%); }
.action-card-header { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: #f8fafd; }
.action-pending > .action-card-header { border-bottom: 1px solid #dce6f4; background: #f0f5fd; }
.action-card-header h3 { flex: 1; min-width: 0; font-size: 14px; font-weight: 600; line-height: 1.5; }
.action-card-icon { display: grid; width: 28px; height: 28px; flex-shrink: 0; place-items: center; border-radius: 8px; background: #e8effa; color: var(--action-primary); }
.action-state { flex-shrink: 0; color: #6a7a90; font-size: 12px; }
.action-state.needs-action { border-radius: 6px; background: #fff; padding: 3px 8px; color: var(--action-primary); font-weight: 600; }
.action-card-body { padding: 16px; }
.action-card-body:empty { display: none; }
.action-history .action-card-header { padding-block: 10px; background: #fafbfd; }
.action-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; border-radius: 10px; background: #f6f8fc; padding: 12px; font-size: 14px; }
.action-summary dt { margin-bottom: 4px; color: var(--text-secondary); font-size: 12px; }
.action-summary dd { overflow-wrap: anywhere; color: #233d61; font-weight: 600; }
.turn-action-card :deep([data-testid=task-plan] > header), .turn-action-card .proposal-content > details > summary { display: none; }
.agent-composer { border-color: #dce4ef; border-radius: 16px; background: #fff; box-shadow: 0 4px 20px rgb(23 43 77 / 4%); transition: border-color 150ms, box-shadow 150ms; }
.agent-composer:focus-within { border-color: #9db6db; box-shadow: 0 0 0 3px rgb(31 75 153 / 5%); }
.agent-composer textarea:focus-visible { outline: none; }
.task-overview, .current-plan-summary { border: 1px solid #e3e9f1; border-radius: 12px; background: #fff; padding: 16px; }
.details-empty { display: flex; min-height: 240px; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #8a9bb3; text-align: center; }
.details-empty h3 { color: #465d7e; font-size: 14px; font-weight: 600; }
.details-empty p { max-width: 220px; color: #71829a; font-size: 13px; line-height: 1.8; }
.agent-details { container-type: inline-size; }
@container (max-width: 600px) { .agent-details :deep(.sm\:grid-cols-2) { grid-template-columns: minmax(0,1fr); } }
.candidate-selection { container-type: inline-size; }
.selection-options { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
@container (max-width: 400px) { .selection-options { grid-template-columns: minmax(0,1fr); } }

.compact-assistant :deep(.workspace-auxiliary) { width: 100%; }
.compact-assistant :deep(.sm\:grid-cols-2) { grid-template-columns: minmax(0, 1fr); }
</style>
