import { translate } from '@/i18n'
import type { BackendJobOut, BackendJobListOut } from '@/api/genovaBackend'
export const activeJobStatuses = ['pending', 'queued', 'running', 'blocked']
export const resultRoutes: Record<string, string> = { molecule_generation: '/molgen/results', property_optimization: '/molopt/results', molecule_postprocessing: '/postprocessing/results' }
export const toolRoutes: Record<string, string> = { protein_preparation: '/protein-preparation', molecule_generation: '/molgen', property_optimization: '/molopt', molecule_postprocessing: '/postprocessing' }
export function jobTitle(job: BackendJobListOut) { return job.params.job_name || job.params.name || `${jobTypeLabel(job.job_type)} · ${job.id.slice(0, 8)}` }
export function jobTypeLabel(type: string) {
  const key = { protein_preparation: 'proteinPreparation', molecule_generation: 'deNovoGeneration', property_optimization: 'leadOptimization', molecule_postprocessing: 'postprocessing', tarpass: 'postprocessing' }[type]
  return key ? translate(`platform.${key}`) : type
}
export function statusTone(status: string) {
  if (['succeeded', 'ready', 'results_ready', 'completed', 'approved', 'authorized'].includes(status)) return 'status-success'
  if (['failed', 'invalid', 'interrupted'].includes(status)) return 'status-failed'
  if (['running', 'executing', 'preparing'].includes(status)) return 'status-active'
  if (['pending', 'queued', 'blocked', 'partial_succeeded', 'draft', 'awaiting_upload', 'awaiting_selection', 'awaiting_site', 'awaiting_preparation_approval', 'awaiting_workflow_approval', 'awaiting_postprocessing_approval', 'ready_for_planning'].includes(status)) return 'status-pending'
  return ''
}
export function sessionPhaseLabel(phase: string) {
  const key = { awaiting_upload: 'awaitingUpload', awaiting_selection: 'awaitingSelection', awaiting_site: 'defineSite', awaiting_preparation_approval: 'awaitingPreparation', preparing: 'preparing', ready_for_planning: 'ready', awaiting_workflow_approval: 'awaitingWorkflow', awaiting_postprocessing_approval: 'awaitingPostprocessing', executing: 'executing', results_ready: 'resultsReady', failed: 'failedTask', cancel_requested: 'stopping', canceled: 'canceledPhase' }[phase]
  return key ? translate(`agent.session.${key}`) : phase
}

export function jobContextLabel(job: BackendJobOut) {
  const context = job.params.structure_context || job.tasks.find(task => task.input_payload.structure_context)?.input_payload.structure_context
  if (!context) return ''
  return [context.name, context.box?.center ? context.box.center.map((value: number) => value.toFixed(1)).join(', ') + ' Å' : ''].filter(Boolean).join(' · ')
}

export function generationQuantityWarning(output: Record<string, any>) {
  if (output.reached_target !== false && !(output.shortfall > 0)) return ''
  const text = translate('platform.generationShortfall', {
    requested: output.requested_count, actual: output.result_count, count: output.shortfall ?? Math.max(0, output.requested_count - output.result_count),
  })
  const reason = {
    max_steps: 'generationStopMaxSteps', queue_empty: 'generationStopQueueEmpty',
    search_budget_exhausted: 'generationStopSearchBudget', budget_exhausted: 'generationStopBudget',
    optimization_completed: 'generationStopOptimization',
    time_budget_exhausted: 'generationStopTimeBudget',
    round_budget_exhausted: 'generationStopRoundBudget',
    no_new_unique_molecules: 'generationStopNoNewUnique',
    validation_shortfall: 'generationStopValidationShortfall',
    structure_count_mismatch: 'generationStopValidationShortfall',
  }[output.stop_reason as string]
  return reason ? `${text} ${translate(`platform.${reason}`)}` : text
}

export function generationDeliverySummary(output: Record<string, any>) {
  return output.reached_target === true && Number.isInteger(output.requested_count) && Number.isInteger(output.result_count)
    ? translate('platform.generationDelivered', { requested: output.requested_count, actual: output.result_count })
    : ''
}
