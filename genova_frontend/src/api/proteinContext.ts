import request from '@/utils/request'
import { translate } from '@/i18n'
import { MAX_UPLOAD_BYTES } from '@/utils/uploadFileCheck'
import { getBackendDataset, uploadBackendDataset } from './genovaBackend'
import type { ProteinAnalysis, ProteinContext, ProteinContextListItem, PreparedReceptor, PreparedSpec, ComponentManifest, BindingSite, GenerationReference, SourceComponentReference } from '@/types/proteinContext'

export function getProteinAnalysis(datasetId: string, fileId?: string) {
  return request.get<ProteinAnalysis>(`/api/v1/datasets/${datasetId}/protein-analysis`, { params: { file_id: fileId } })
}

export function listProteinContexts(params?: { limit?: number; offset?: number; search?: string; signal?: AbortSignal }) {
  const { signal, ...query } = params || {}
  return request.get<ProteinContextListItem[]>('/api/v1/protein-contexts', { params: query, signal })
}

export function getProteinContext(contextId: string) {
  return request.get<ProteinContext>(`/api/v1/protein-contexts/${contextId}`)
}

export function proteinSourceFiles<T extends { id: string; original_filename: string }>(dataset: { files: T[]; meta?: Record<string, any> }) {
  return dataset.files.filter(file => /\.(pdb|cif|mmcif)$/i.test(file.original_filename))
}

export async function uploadProteinDataset(file: File, kind = 'protein_pdb', options: { uploadId?: string; signal?: AbortSignal } = {}) {
  if (!/\.(pdb|cif|mmcif)$/i.test(file.name)) throw new Error(translate('platform.onlyPdbFilesAreSupported'))
  if (file.size > MAX_UPLOAD_BYTES) throw new Error(translate('platform.structureErrors.CIF_TOO_LARGE'))
  return (await uploadBackendDataset({ name: file.name, kind, file, fileRole: 'source_structure', inputPolicy: 'generation_auto_v1', ...options })).data
}

export async function ensureProteinFile(datasetId: string, fileId?: string) {
  const dataset = (await getBackendDataset(datasetId)).data
  const sources = proteinSourceFiles(dataset)
  const source = fileId ? dataset.files.find(file => file.id === fileId) : sources.length === 1 ? sources[0] : undefined
  if (!source || !/\.(pdb|cif|mmcif)$/i.test(source.original_filename)) throw new Error(translate('platform.selectProteinFile'))
  return { dataset, fileId: source.id }
}

export const getComponentManifest = (source: PreparedSpec['source']) => request.get<ComponentManifest>(`/api/v1/datasets/${source.dataset_id}/component-manifest`, { params: { file_id: source.file_id, sha256: source.sha256, model_id: source.model_id } })
export const createPreparedReceptor = (payload: PreparedSpec & { name: string }) => request.post<PreparedReceptor>('/api/v1/prepared-receptors', payload)
export const listPreparedReceptors = () => request.get<(Pick<PreparedReceptor, 'id' | 'name' | 'status'> & { job_id?: string | null })[]>('/api/v1/prepared-receptors')
export const getPreparedReceptor = (id: string, timeout?: number) => request.get<PreparedReceptor>(`/api/v1/prepared-receptors/${id}`, { timeout })
export const createBindingSite = (payload: {version: 4; name: string; prepared_receptor_id: string; prepared_artifact_sha256: string; site: BindingSite; generation_reference: GenerationReference | SourceComponentReference | null; input_parameters?: {version: 1; ph: number; condition_seed: number}; derived_from_context_id?: string}) => request.post<ProteinContext>('/api/v1/protein-contexts', payload)

export const retryContextValidation = (id: string, engine: string) => request.post<ProteinContext>(`/api/v1/protein-contexts/${id}/retry-validation`, null, { params: { engine } })
