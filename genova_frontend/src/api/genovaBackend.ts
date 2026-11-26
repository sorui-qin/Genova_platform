import request from '@/utils/request'
import type { AxiosResponse } from 'axios'
import { queryClient } from '@/plugins/tanstack-vue-query'

export interface DataRetentionPolicy {
  enabled: boolean
  retention_days: number
  first_enabled_at: string | null
}
export const getDataRetentionPolicy = () => request.get<DataRetentionPolicy>('/api/v1/platform/retention')

export interface AgentProxySettingsInput {
  proxy_url: string | null
}
export interface AgentProxySettingsOut extends AgentProxySettingsInput {
  allowed_proxy_urls: string[]
}
export const getAgentProxySettings = () => request.get<AgentProxySettingsOut>('/api/v1/agent/settings/proxy')
export const saveAgentProxySettings = (data: AgentProxySettingsInput) => request.put<AgentProxySettingsOut>('/api/v1/agent/settings/proxy', data)

// Standing work preferences the assistant saved at the researcher's request; they apply to every session.
export interface AgentWorkPreference {
  id: string
  text: string
}
export const getAgentWorkPreferences = () => request.get<AgentWorkPreference[]>('/api/v1/agent/settings/preferences')
export const deleteAgentWorkPreference = (id: string) => request.delete(`/api/v1/agent/settings/preferences/${encodeURIComponent(id)}`)

export interface AgentSettingsInput {
  context_window?: number | null
  profile_id?: string | null
  auth_type?: 'api_key' | 'chatgpt'
  profile_name?: string
  base_url: string
  model: string
  api_key?: string
  reasoning?: AgentReasoningConfig | null
}
export interface AgentAPIProfile {
  context_window: number | null
  id: string
  name: string
  base_url: string
  model: string
  has_api_key: boolean
  reasoning: AgentReasoningConfig | null
  auth_type: 'api_key' | 'chatgpt'
  connection_status?: 'connected' | 'disconnected' | 'plan_required' | 'reauthorization_required' | null
  account_label?: string | null
}
export interface AgentSettingsOut {
  context_window: number | null
  active_profile_id: string | null
  profiles: AgentAPIProfile[]
  base_url: string
  model: string
  has_api_key: boolean
  reasoning: AgentReasoningConfig | null
}
export interface AgentReasoningDeclaration {
  effort_parameter: 'reasoning_effort' | 'reasoning.effort' | null
  effort_levels: string[]
  default_effort: string | null
  thinking_parameter: 'thinking.type' | 'enable_thinking' | null
  can_disable: boolean
  budget_parameter: 'thinking_budget' | null
  budget_min: number
  budget_max: number | null
  exclusive_effort_budget: boolean
}
export interface AgentReasoningCapability extends AgentReasoningDeclaration {
  context_window?: number | null
  protocol: 'chat_completions' | 'responses'
  source: 'metadata' | 'builtin' | 'user' | 'unknown'
  warning: string | null
  manual_allowed: boolean
  supported_protocols: Array<'chat_completions' | 'responses'>
}
export interface AgentReasoningSelection {
  effort: string | null
  thinking: boolean | null
  budget_tokens: number | null
}
export interface AgentReasoningConfig {
  api_protocol: 'auto' | 'chat_completions' | 'responses'
  selection: AgentReasoningSelection
  manual: AgentReasoningDeclaration | null
  capability: AgentReasoningCapability | null
}
export const getAgentSettings = () => request.get<AgentSettingsOut>('/api/v1/agent/settings')
export const saveAgentSettings = (data: AgentSettingsInput) => request.put<AgentSettingsOut>('/api/v1/agent/settings', data)
export const testAgentSettings = (data: AgentSettingsInput) => request.post('/api/v1/agent/settings/test', data, { timeout: 65000 })
export const getAgentReasoningCapability = (data: AgentSettingsInput) => request.post<AgentReasoningCapability>('/api/v1/agent/settings/capabilities', data)
export const deleteAgentSettings = (profileId?: string) => request.delete('/api/v1/agent/settings', { params: { profile_id: profileId } })

export const startChatGPTLogin = (profileId?: string, mode: 'local' | 'manual' = 'local') => request.post<{ attempt_id: string; authorization_url: string }>(
  '/api/v1/agent/settings/chatgpt/start', { profile_id: profileId || null, mode })
export const completeChatGPTLogin = (attemptId: string, callbackUrl: string) => request.post(
  '/api/v1/agent/settings/chatgpt/complete', { attempt_id: attemptId, callback_url: callbackUrl }, { timeout: 65000 })
export const getChatGPTLoginStatus = (attemptId: string) => request.get<{
  status: 'pending' | 'succeeded' | 'failed' | 'expired'
  profile_id?: string
  error_code?: string
}>('/api/v1/agent/settings/chatgpt/status/' + attemptId)
export const getChatGPTModels = (profileId: string) => request.get<{ models: Array<{ slug: string; display_name: string }> }>(
  '/api/v1/agent/settings/chatgpt/models', { params: { profile_id: profileId } })
export const disconnectChatGPT = (profileId: string) => request.post<{ revocation_confirmed: boolean }>(
  '/api/v1/agent/settings/chatgpt/disconnect', { profile_id: profileId })

export function getEcloudSamplingPlan(target: number, sampling: Record<string, number | string>) {
  return request.get<{ num_clouds: number; decodes_per_cloud: number }>('/api/v1/jobs/molecule-generation/sampling-plan', {
    params: {
      target_num_molecules: target,
      decodes_per_cloud: sampling.decodes_per_cloud,
      noise: sampling.noise,
      inv_temp: sampling.inv_temp,
      budget_multiplier: sampling.budget_multiplier,
      num_clouds: sampling.num_clouds === '' ? undefined : sampling.num_clouds,
    },
  })
}

export interface BackendDatasetFile {
  id: string
  file_role: string
  original_filename: string
  content_type?: string | null
  size_bytes: number
  sha256?: string | null
  created_at: string
}

export interface BackendDataset {
  id: string
  owner_user_id: string
  name: string
  kind: string
  description?: string | null
  status: string
  meta: Record<string, any>
  created_at: string
  updated_at: string
  files: BackendDatasetFile[]
}

export interface BackendJobCreatePayload {
  prepared_receptor_id?: string
  job_type: 'molecule_generation' | 'molecule_postprocessing' | 'property_optimization' | 'protein_preparation'
  ligand_dataset_id?: string
  pocket_dataset_id?: string
  protein_context_id?: string
  params: {
    molecule_generation?: Record<string, any>
    property_optimization?: Record<string, any>
    property_profile?: Array<Record<string, any>>
    job_name?: string
    [key: string]: any
  }
}

export interface BackendJobTask {
  id: string
  job_id: string
  task_code: string
  runtime_task?: string | null
  status: string
  queue_job_id: string
  depends_on: string[]
  input_payload: Record<string, any>
  output_payload: Record<string, any>
  error_message?: string | null
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface BackendSmallMoleculeResult {
  id: string
  job_id: string
  job_task_id: string
  task_code: string
  smiles: string
  smiles_canonical: string
  extra: Record<string, any>
  created_at: string
  updated_at: string
}

export interface BackendJobOut {
  id: string
  owner_user_id: string
  job_type: string
  status: string
  priority: number
  input_dataset_id?: string | null
  params: Record<string, any>
  summary: Record<string, any>
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
  tasks: BackendJobTask[]
}

export type BackendJobListOut = Pick<BackendJobOut, 'id' | 'job_type' | 'status' | 'params' | 'summary' | 'created_at' | 'updated_at'>

export interface PropertyOptimizationEditCandidate {
  id: string
  retained_molfile: string
  retained_smiles: string
  retained_atom_indices: number[]
  anchor_atom_indices: number[]
}

export interface PropertyOptimizationEditPreview {
  reference_molfile: string
  reference_smiles: string
  atom_count: number
  candidates: PropertyOptimizationEditCandidate[]
}

export interface BackendAgentPageContext {
  page: 'dashboard' | 'protein_context' | 'surfgen' | 'delete' | 'ecloudgen' | 'epso' | 'tarpass' | 'results'
  protein_context_id?: string
  job_id?: string
  workflow_id?: string
  dataset_ids?: string[]
}

export interface BackendAgentWorkflowPlan {
  template: 'surfgen_tarpass_v1' | 'ecloudgen_tarpass_v1' | 'delete_tarpass_v1' | 'epso_tarpass_v1'
  protocol_version: 'generation-2026-09'
  protein_context_id: string
  generator: 'surfgen' | 'ecloudgen' | 'delete' | 'epso'
  generation: {
    engine: 'surfgen' | 'ecloudgen' | 'delete' | 'epso'
    num_molecules?: number
    target_num_molecules?: number
    noise?: 0.1
    edit?: Record<string, any>
    objectives?: Array<Record<string, any>>
    optimizer?: Record<string, any>
  }
  postprocessing: {
    enabled: boolean
    prefilters: Array<{ metric: string; op: 'gt' | 'lt' | 'gte' | 'lte' | 'eq'; value: number }>
  }
  selection: { sort_by?: string | null; descending: boolean; top_k?: number | null }
  warnings: string[]
  missing_requirements: string[]
  evidence_refs: string[]
}

export interface BackendAgentEvidenceCard {
  source_id: string
  chunk_id: string
  content_hash: string
  revision_id: string
  section: string
  protocol_version: string
  name?: string | null
  category?: string | null
  purpose?: string | null
  related_workflows: string[]
  related_components: string[]
  related_metrics: string[]
  why_cited: string
}

export interface BackendAgentResponse {
  message: string
  diagnostic_notes?: string
  plan?: BackendAgentWorkflowPlan | null
  plan_valid: boolean
  missing_requirements: string[]
  warnings: string[]
  error_code?: string | null
  error_source?: 'harness' | 'provider_api' | 'model_output' | 'workflow' | 'configuration' | 'domain' | 'internal' | null
  status_code?: number | null
  recovery_action?: 'revise_request' | 'check_api_key' | 'check_api_permissions' | 'check_model_endpoint' | 'wait_and_retry' | 'switch_model_or_thinking_mode' | 'check_network' | 'retry_once_then_switch_model' | 'reconfigure_agent' | 'refresh_workflow' | 'contact_maintainer' | null
  upstream_status_code?: number | null
  upstream_error_code?: string | null
  workflow_id?: string | null
  plan_version?: number | null
  plan_hash?: string | null
  normalized_plan?: BackendAgentWorkflowPlan | null
  results?: Record<string, any> | null
  evidence_refs: string[]
  evidence_details: Array<Record<string, any>>
  evidence_cards: BackendAgentEvidenceCard[]
  active_skills: Array<{ name: string; version: string }>
  interaction_type?: 'plan' | 'modify' | 'explain' | null
  plan_changed: boolean
  previous_plan_version?: number | null
  refinement_state?: string | null
  client_request_id?: string | null
  planning_status?: 'planning' | 'interrupted' | 'draft' | 'approved' | 'running' | 'failed' | 'succeeded' | 'cancel_requested' | 'canceled' | null
  attempt?: number | null
  retryable: boolean
}

export interface BackendAgentWorkflowStep {
  step_key: string
  status: string
  job_id?: string | null
  error_code?: string | null
  error_message?: string | null
}

export interface BackendAgentWorkflow {
  workflow_id: string
  status: string
  template: string
  protocol_version: string
  plan_version: number
  plan_hash: string
  plan: BackendAgentWorkflowPlan
  refinement_state: string
  approved_version?: number | null
  approved_hash?: string | null
  approved_at?: string | null
  steps: BackendAgentWorkflowStep[]
  interactions: Array<{
    interaction_type: 'plan' | 'modify' | 'explain'
    user_message: string
    assistant_message: string
    base_plan_version: number
    resulting_plan_version: number
    resulting_plan_hash: string
    created_at: string
  }>
  created_at: string
  updated_at: string
}

export interface BackendAgentWorkflowListItem {
  client_request_id?: string | null
  workflow_id?: string | null
  status: string
  template?: string | null
  plan_version?: number | null
  refinement_state?: string | null
  title: string
  message: string
  protein_context_id: string
  attempt?: number | null
  retryable: boolean
  last_error?: string | null
  created_at: string
  updated_at: string
}

export interface BackendAgentRuntime {
  runtime_mode: 'production'
  execution_enabled: boolean
  refinement_enabled: boolean
  max_interactions: number
  recent_context_interactions: number
  gpu_policy: 'single_host_shared_lock'
}

export interface BackendAgentApprovePayload {
  plan_version: number
  plan_hash: string
}

export async function listBackendJobs(params?: {
  limit?: number
  offset?: number
  source_job_id?: string
  job_type?: string
  status?: string
  search?: string
  signal?: AbortSignal
}): Promise<AxiosResponse<BackendJobListOut[]>> {
  return request.get<BackendJobListOut[]>('/api/v1/jobs', {
    params: {
      limit: params?.limit ?? 100,
      offset: params?.offset ?? 0,
      source_job_id: params?.source_job_id,
      job_type: params?.job_type,
      status: params?.status,
      search: params?.search,
    },
    signal: params?.signal,
  })
}

export async function getBackendJob(jobId: string, options?: { summary?: boolean; signal?: AbortSignal }): Promise<AxiosResponse<BackendJobOut>> {
  return request.get<BackendJobOut>(`/api/v1/jobs/${jobId}`, { params: { summary: options?.summary }, signal: options?.signal })
}

export async function cancelBackendJob(jobId: string): Promise<AxiosResponse<{ job_id: string; status: string; ok: boolean }>> {
  return request.post(`/api/v1/jobs/${jobId}/cancel`)
}

export function continueBackendGeneration(jobId: string) {
  return request.post<BackendJobOut>(`/api/v1/jobs/${jobId}/continue`)
}

export interface JobDeletionPreview {
  objects: { kind: string; id: string; name: string }[]
  files: { kind: string; object_id: string; name: string; size_bytes: number }[]
  retained: { kind: string; id: string; name: string; files: { name: string; size_bytes: number }[]; reason: string }[]
  blocked: { kind: string; id: string; reason: string }[]
  reclaimable_bytes: number
  confirmation_token: string
}

export async function previewBackendJobDeletion(jobIds: string[]): Promise<AxiosResponse<JobDeletionPreview>> {
  return request.post('/api/v1/jobs/deletions/preview', { job_ids: jobIds })
}

export async function confirmBackendJobDeletion(jobIds: string[], confirmationToken: string): Promise<AxiosResponse<{ deleted_job_ids: string[]; cleanup_status: 'completed' | 'pending' }>> {
  return request.post('/api/v1/jobs/deletions', { job_ids: jobIds, confirmation_token: confirmationToken })
}

export async function listBackendJobResults(
  jobId: string,
  params?: { task_code?: string; smiles?: string; limit?: number; offset?: number; search?: string; sort_by?: string; descending?: boolean; signal?: AbortSignal }
): Promise<AxiosResponse<BackendSmallMoleculeResult[]>> {
  return request.get<BackendSmallMoleculeResult[]>(`/api/v1/jobs/${jobId}/results`, {
    params: {
      task_code: params?.task_code,
      smiles: params?.smiles,
      limit: params?.limit ?? 50,
      offset: params?.offset ?? 0,
      search: params?.search,
      sort_by: params?.sort_by,
      descending: params?.descending,
    },
    signal: params?.signal,
  })
}

export async function getBackendResult(resultId: string): Promise<AxiosResponse<BackendSmallMoleculeResult>> {
  return request.get<BackendSmallMoleculeResult>(`/api/v1/results/${resultId}`)
}

export async function downloadBackendJobArtifact(
  jobId: string,
  params: { task_code: string; key: string }
): Promise<AxiosResponse<Blob>> {
  return request.get<Blob>(`/api/v1/jobs/${jobId}/artifact`, {
    params: {
      task_code: params.task_code,
      key: params.key,
    },
    responseType: 'blob',
  })
}

export async function uploadBackendDataset(params: {
  name: string
  kind: string
  file: File
  sourceFile?: File
  description?: string
  fileRole?: 'ligand_input' | 'pocket_pdb' | 'attachment' | 'source_structure'
  inputPolicy?: 'generation_auto_v1'
  uploadId?: string
  signal?: AbortSignal
}): Promise<AxiosResponse<BackendDataset>> {
  const form = new FormData()
  form.append('name', params.name)
  form.append('kind', params.kind)
  if (params.description) {
    form.append('description', params.description)
  }
  if (params.sourceFile) {
    form.append('files', params.sourceFile)
    form.append('file_roles', 'source_structure')
  }
  form.append('files', params.file)
  if (params.inputPolicy) form.append('input_policy', params.inputPolicy)
  if (params.uploadId) form.append('upload_id', params.uploadId)
  if (params.fileRole) {
    form.append('file_roles', params.fileRole)
  }
  const response = await request.post<BackendDataset>('/api/v1/datasets/upload', form, { signal: params.signal })
  withPickedFileNames(response.data)
  await queryClient.invalidateQueries({ queryKey: ['datacenter'], refetchType: 'none' })
  return response
}

export async function cancelDatasetUpload(id: string) {
  return (await request.post<{status: 'uploaded' | 'canceled'; dataset?: BackendDataset}>(`/api/v1/datasets/uploads/${id}/cancel`)).data
}

// Browsers send `"` in an upload's file name as %22 and the server keeps it, while the dataset name holds the picked name.
// Only a file whose stored name is exactly that escaped form is shown with the picked name; a name that really contains %22 stays.
function withPickedFileNames(dataset: BackendDataset) {
  if (!dataset?.name?.includes('"')) return
  const escaped = dataset.name.replace(/"/g, '%22')
  dataset.files = dataset.files?.map(file => file.original_filename === escaped ? { ...file, original_filename: dataset.name } : file)
}

export async function listBackendDatasets(params?: {
  limit?: number
  offset?: number
  summary?: boolean
  selectable?: boolean
  search?: string
  attachment?: boolean
  signal?: AbortSignal
}): Promise<AxiosResponse<BackendDataset[]>> {
  const response = await request.get<BackendDataset[]>('/api/v1/datasets', {
    params: {
      limit: params?.limit ?? 200,
      offset: params?.offset ?? 0,
      summary: params?.summary,
      selectable: params?.selectable,
      search: params?.search,
      attachment: params?.attachment,
    },
    signal: params?.signal,
  })
  response.data.forEach(withPickedFileNames)
  return response
}

export async function listAllBackendDatasets(options?: { summary?: boolean; selectable?: boolean; attachment?: boolean; signal?: AbortSignal }): Promise<BackendDataset[]> {
  const datasets: BackendDataset[] = []
  for (let offset = 0; ; offset += 200) {
    const { data } = await listBackendDatasets({ ...options, limit: 200, offset })
    datasets.push(...data)
    if (data.length < 200) return [...new Map(datasets.map(item => [item.id, item])).values()]
  }
}

export async function listBuiltinBackendDatasets(options?: { summary?: boolean; selectable?: boolean; signal?: AbortSignal }): Promise<AxiosResponse<BackendDataset[]>> {
  return request.get<BackendDataset[]>('/api/v1/datasets/builtin', {
    params: { summary: options?.summary, selectable: options?.selectable },
    signal: options?.signal,
  })
}

export const renameBackendDataset = async (datasetId: string, payload: { name: string; file_id?: string }) => {
  const response = await request.patch<BackendDataset>(`/api/v1/datasets/${datasetId}`, payload)
  await queryClient.invalidateQueries({ queryKey: ['datacenter'], refetchType: 'none' })
  return response
}
export const deleteBackendDataset = async (datasetId: string) => {
  const response = await request.delete(`/api/v1/datasets/${datasetId}`)
  await queryClient.invalidateQueries({ queryKey: ['datacenter'], refetchType: 'none' })
  return response
}

export async function getBackendDataset(datasetId: string): Promise<AxiosResponse<BackendDataset>> {
  const response = await request.get<BackendDataset>(`/api/v1/datasets/${datasetId}`)
  withPickedFileNames(response.data)
  return response
}

export async function downloadBackendDataset(
  datasetId: string,
  fileId?: string
): Promise<AxiosResponse<Blob>> {
  return request.get<Blob>(`/api/v1/datasets/${datasetId}/download`, {
    params: fileId ? { file_id: fileId } : undefined,
    responseType: 'blob',
  })
}

export async function createBackendJob(
  payload: BackendJobCreatePayload, idempotencyKey?: string
): Promise<AxiosResponse<BackendJobOut>> {
  return request.post<BackendJobOut>('/api/v1/jobs', payload, { headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined })
}

export async function previewPropertyOptimizationEdits(payload: {
  protein_context_id: string
  ligand_dataset_id?: string
  mode: 'r_group' | 'side_chain' | 'linker' | 'scaffold_hopping' | 'custom' | 'derivation_site'
}): Promise<AxiosResponse<PropertyOptimizationEditPreview>> {
  return request.post<PropertyOptimizationEditPreview>(
    '/api/v1/jobs/property-optimization/edit-candidates',
    payload,
  )
}

export async function planBackendAgent(payload: {
  message: string
  client_request_id: string
  retry?: boolean
  context?: BackendAgentPageContext
}): Promise<AxiosResponse<BackendAgentResponse>> {
  return request.post<BackendAgentResponse>('/api/v1/agent/plan', payload)
}

export async function getBackendAgentRuntime(): Promise<AxiosResponse<BackendAgentRuntime>> {
  return request.get<BackendAgentRuntime>('/api/v1/agent/runtime')
}

export async function interactBackendAgentWorkflow(
  workflowId: string,
  payload: { message: string; intent: 'modify' | 'explain' },
): Promise<AxiosResponse<BackendAgentResponse>> {
  return request.post<BackendAgentResponse>(`/api/v1/agent/workflows/${workflowId}/interactions`, payload)
}

export async function getBackendAgentWorkflow(
  workflowId: string
): Promise<AxiosResponse<BackendAgentWorkflow>> {
  return request.get<BackendAgentWorkflow>(`/api/v1/agent/workflows/${workflowId}`)
}

export async function listBackendAgentWorkflows(params?: {
  limit?: number
  offset?: number
}): Promise<AxiosResponse<BackendAgentWorkflowListItem[]>> {
  return request.get<BackendAgentWorkflowListItem[]>('/api/v1/agent/workflows', {
    params: { limit: params?.limit ?? 50, offset: params?.offset ?? 0 },
  })
}

export async function approveBackendAgentWorkflow(
  workflowId: string,
  payload: BackendAgentApprovePayload
): Promise<AxiosResponse<BackendAgentWorkflow>> {
  return request.post<BackendAgentWorkflow>(`/api/v1/agent/workflows/${workflowId}/approve`, payload)
}

export interface AgentSessionTurn {
  research_task_id?: string | null
  proposals?: AgentSessionState["proposals"]
  can_resume?: boolean
  resumed_by?: string
  recovery_of?: string
  recovery_count?: number
  source?: string
  trigger?: string | null
  created_at: string
  updated_at: string
  request: Record<string, any>
  id: string
  client_request_id: string
  intent: string
  message: string
  status: string
  attempt: number
  response: Record<string, any>
}
export interface AgentClarificationField {
  requirement: string
  id: string
  type: 'structure' | 'engine' | 'confirmation' | 'delete' | 'count' | 'text'
}
export interface AgentTaskPlanDefinition {
  stage?: 'preparation' | 'generation' | 'postprocessing'
  goal: string
  completion: string
  preparation: Record<string, unknown> | null
  site: Record<string, unknown> | null
  workflow: (Omit<BackendAgentWorkflowPlan, 'protein_context_id'> & { protein_context_id: string | null; seed_source?: Record<string, unknown> | null }) | null
  sampling: {enabled: boolean; max_rounds: number} | null
  iteration: { enabled: boolean; engine: 'epso' | 'delete'; max_rounds: number; num_molecules: number; delete_mode: string; epso: {engine: 'epso'; num_molecules: number; optimizer: Record<string, number>; objectives: Array<Record<string, unknown>>} }
  key_interactions: Array<Record<string, unknown>>
  reference_dataset_id: string | null
  success_filters: Array<{metric: string; op: 'gt' | 'lt' | 'gte' | 'lte' | 'eq'; value: number}>
  required_candidates: number
  max_recoveries: number
  auto_hours: number
}
export interface AgentTaskPlan {
  history?: Array<{version: number; status: string; created_at: string}>
  definition: AgentTaskPlanDefinition
  version: number
  state: string
  proposal_id: string
  run: { best_candidates?: Array<{round: number; source_job_id: string; workflow_id: string; molecule_id: string; smiles: string; metric: string | null; score: number | null}>; phase?: string; round?: number; rounds?: string[]; workflow_id?: string; error?: string; deadline?: string; [key: string]: unknown }
}

export interface AgentSessionState {
  workflow_preferences?: { reply_language?: 'zh' | 'en'; site_request?: { center: number[]; size?: number[] | null }; [key: string]: unknown }
  task_plan?: AgentTaskPlan | null
  pose_preparation?: Record<string, any>
  pose_preparation_draft?: Record<string, any>
  presentation?: Record<string, any>
  prepared_receptor?: Record<string, any>
  drafts?: Array<Record<string, any>>
  input_selection?: { candidates: Array<{ id: string; name: string; kind: string; files: Array<{ id: string; name: string; role: string }> }> }
  research_task_id?: string | null
  research_task_state?: 'unassessed' | 'allowed' | 'blocked' | null
  delete_edit?: { mode: string; id: string }
  id: string
  goal: string
  phase: string
  input_revision: number
  assets: Record<string, any>
  confirmed_fields: Record<string, { value: any; source: string; turn_id: string }>
  pending_requirements: string[]
  pending_clarification_fields?: AgentClarificationField[]
  context_spec?: Record<string, any>
  turns: AgentSessionTurn[]
  proposals: Array<{ research_task_id?: string | null; input_revision?: number | null; turn_id: string; created_at: string; execution: Record<string, any>; job_status?: string; workflow?: Record<string, any>; id: string; kind: string; payload: Record<string, any>; status: string; action_hash: string }>
  candidate_sets: Array<{ proposal_id: string; created_at: string; id: string; postprocessing_job_id?: string; workflow_id?: string | null; summary: Record<string, any> }>
  preparation?: { job_id: string; status: string }
  workflow?: Record<string, any>
  last_error?: string
}
export const createAgentSession = (data: { goal?: string; workflow_id?: string } = {}) => request.post<AgentSessionState>('/api/v1/agent/sessions', data)
export const startAgentSession = (data: { client_session_id: string; turn: Record<string, any> }) => request.post<AgentSessionState>('/api/v1/agent/sessions/start', data)
export const listAgentSessions = () => request.get<Array<{ id: string; goal: string; phase: string }>>('/api/v1/agent/sessions')
export const getAgentSession = (id: string) => request.get<AgentSessionState>(`/api/v1/agent/sessions/${id}`)
export const sendAgentSessionTurn = (id: string, data: Record<string, any>) => request.post<AgentSessionTurn>(`/api/v1/agent/sessions/${id}/turns`, data)
export const approveAgentProposal = (id: string, proposalId: string, actionHash: string) => request.post(`/api/v1/agent/sessions/${id}/proposals/${proposalId}/approve`, { action_hash: actionHash })
export const cancelAgentSession = (id: string) => request.post(`/api/v1/agent/sessions/${id}/cancel`)
export const getAgentCandidateSet = (id: string, setId: string, params?: {offset?:number;limit?:number}) => request.get(`/api/v1/agent/sessions/${id}/candidate-sets/${setId}`, {params})
export const exportAgentCandidateSet = (id: string, setId: string, format: string, pose: string) => request.get<Blob>(`/api/v1/agent/sessions/${id}/candidate-sets/${setId}/export`, { params: { format, pose }, responseType: 'blob' })

export const getAgentSessionSpecs = (id: string) => request.get(`/api/v1/agent/sessions/${id}/specs`)
export const inspectAgentProtein = (id: string) => request.get(`/api/v1/agent/sessions/${id}/protein-analysis`)

export const deleteAgentSession = (id: string) => request.delete(`/api/v1/agent/sessions/${id}`)
export const deleteBackendAgentWorkflow = (id: string) => request.delete(`/api/v1/agent/workflows/${id}`)
export const deleteBackendAgentPlanningRequest = (id: string) => request.delete(`/api/v1/agent/planning-requests/${id}`)

export const resumeAgentSessionTurn = (id: string, turnId: string) => request.post<AgentSessionTurn>(`/api/v1/agent/sessions/${id}/turns/${turnId}/resume`)
export const stopAgentSessionTurn = (id: string, turnId: string) => request.post<AgentSessionTurn>(`/api/v1/agent/sessions/${id}/turns/${turnId}/stop`)
export const getAgentSessionHistory = (id: string, offset: number) => request.get<AgentSessionTurn[]>(`/api/v1/agent/sessions/${id}/history`, { params: { offset, limit: 50 } })

export const deriveAgentOptimization = (id: string, data: Record<string, any>) => request.post(`/api/v1/agent/sessions/${id}/optimization-drafts`, data)
export const approveAgentOptimizationPose = (id: string, data: Record<string, any>) => request.post(`/api/v1/agent/sessions/${id}/optimization-drafts/approve-pose`, data)
