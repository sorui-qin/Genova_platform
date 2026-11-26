import request from '@/utils/request'
import type { AgentSessionState } from './genovaBackend'

export type AssistantModule = 'tarpass' | 'molecule_generation' | 'property_optimization'
export interface ModuleContext {
  engine: 'tarpass' | 'surfgen' | 'ecloudgen' | 'delete' | 'epso'
  source_job_id?: string
  protein_context_id?: string
  ligand_dataset_id?: string
  form: Record<string, any>
  view?: Record<string, any>
  view_draft?: Record<string, any>
  selected_ids?: string[]
}
export interface ModuleSuggestion {
  target: 'view' | 'draft'
  engine: ModuleContext['engine']
  job_id: string | null
  source_job_id: string | null
  input_binding: { protein_context_id?: string | null; ligand_dataset_id?: string | null; reference_dataset_id?: string | null }
  reason: string
  changes: Array<{ field: string; before: any; after: any }>
}
export const openModuleSession = (module: AssistantModule, jobId?: string) =>
  request.post<AgentSessionState>('/api/v1/agent/sessions/module', { module, job_id: jobId || null })
export const bindModuleSession = (id: string, module: AssistantModule, jobId: string) =>
  request.post<AgentSessionState>(`/api/v1/agent/sessions/${id}/module-job`, { module, job_id: jobId })

export function sameValue(a: any, b: any): boolean {
  if (a == null || b == null) return a == null && b == null
  if (typeof a !== 'object' || typeof b !== 'object') return a === b
  const keys = Object.keys(a).sort(), other = Object.keys(b).sort()
  return keys.length === other.length && keys.every((key, index) => key === other[index] && sameValue(a[key], b[key]))
}
