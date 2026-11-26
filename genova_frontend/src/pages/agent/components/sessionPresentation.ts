import type { AgentSessionState } from '@/api/genovaBackend'

export type ClarificationField = import('@/api/genovaBackend').AgentClarificationField

const structureIds = new Set(['protein_dataset_id', 'protein_file_id', 'prepared_spec', 'prepared_receptor_id', 'site', 'generation_reference', 'preparation_defaults', 'valid_structure_selection', 'prepared_context', 'protein_context_id'])

export function requirementKind(requirement: string, fields: ClarificationField[] = []) {
  const field = fields.find(item => item.requirement === requirement)
  if (field) return field.type
  if (structureIds.has(requirement)) return 'structure'
  if (requirement === 'delete_edit_spec_id') return 'delete'
  if (requirement === 'num_molecules' || requirement === 'target_num_molecules') return 'count'
  if (requirement === 'engine' || requirement === 'generator') return 'engine'
  if (requirement === 'postprocessing') return 'confirmation'
  return 'text'
}

export const isStructuralRequirement = (requirement: string, fields: ClarificationField[] = []) => requirementKind(requirement, fields) === 'structure'

export function clarificationRequirements(requirements: string[], metadata: ClarificationField[] = []) {
  return requirements.filter(requirement => !isStructuralRequirement(requirement, metadata))
}

export function candidateResultRoute(set: { postprocessing_job_id?: string }) {
  return set.postprocessing_job_id ? { path: '/postprocessing/results', query: { job_id: set.postprocessing_job_id } } : null
}

export function validRequirementAnswer(requirement: string, answer: string | number = '', editReady = false, contextReady = false, fields: ClarificationField[] = []) {
  const kind = requirementKind(requirement, fields)
  if (kind === 'delete') return editReady
  if (kind === 'structure') return contextReady
  if (kind === 'count') return Boolean(String(answer).trim()) && Number.isInteger(Number(answer)) && Number(answer) >= 1 && Number(answer) <= 50000
  return Boolean(String(answer).trim())
}

export function clarificationMessage(goal: string, requirements: string[], answers: Record<string, string | number>, edit?: { id: string; mode: string }, fields: ClarificationField[] = []) {
  const replies = requirements.map(requirement => {
    const kind = requirementKind(requirement, fields)
    if (kind === 'delete' && edit) return `DELETE: delete_edit_spec_id=${edit.id}; mode=${edit.mode}`
    if (kind === 'count') return `${fields.find(field => field.requirement === requirement)?.id || requirement}: ${answers[requirement]}`
    return `${requirement}: ${answers[requirement] || ''}`
  })
  return [goal, ...replies].filter(Boolean).join('\n')
}

export function proposalTurnId(proposal: AgentSessionState['proposals'][number], turns: AgentSessionState['turns']) {
  const linked = [...turns].reverse().find(turn => turn.response.proposal_id === proposal.id && turn.response.message && !turn.response.error_code)
  return linked?.id || turns.find(turn => turn.id === proposal.turn_id)?.id || ''
}
