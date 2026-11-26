import request from '@/utils/request'

export interface EditSession {
  id: string
  session_id: string
  kind: 'protein' | 'delete' | 'workflow' | 'selection'
  expected_version: number
  status: string
  state: { assets: Record<string, string>; values: Record<string, any>; context?: any; draft?: Record<string, any> }
  result: Record<string, any>
}
export const workflowCommand = (sessionId: string, command: Record<string, any>) => request.post(`/api/v1/agent/sessions/${sessionId}/commands`, command)
export const openWorkflowEditor = (sessionId: string, kind: 'protein' | 'delete' | 'workflow' | 'selection', expected_version: number) => request.post<EditSession>(`/api/v1/agent/sessions/${sessionId}/edit-sessions`, { kind, expected_version })
export const getWorkflowEditor = (id: string) => request.get<EditSession>(`/api/v1/workflow-edit-sessions/${id}`)
export const saveWorkflowEditor = (id: string, changes: Record<string, any>, approve_after_save = false) => request.post(`/api/v1/workflow-edit-sessions/${id}/save`, { changes, approve_after_save })
export const cancelWorkflowEditor = (id: string) => request.post(`/api/v1/workflow-edit-sessions/${id}/cancel`)
export const saveWorkflowEditorDraft = (id: string, changes: Record<string, any>) => request.patch(`/api/v1/workflow-edit-sessions/${id}/draft`, { changes })
