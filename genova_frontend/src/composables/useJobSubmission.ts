import { ref } from 'vue'
import { createBackendJob, type BackendJobCreatePayload } from '@/api/genovaBackend'
import { randomUUID } from '@/utils/uuid'
import { readStoredUserInfo } from '@/utils/guestSession'

interface Submission { key: string; payload: BackendJobCreatePayload }
export function useJobSubmission(scope: string) {
  const owner = readStoredUserInfo()?.id || ''
  const storageKey = `genova:job-submission:${owner}:${scope}`
  let saved: Submission | null = null
  try { saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null') } catch { /* ignore malformed draft */ }
  const pendingSubmission = ref<Submission | null>(saved)
  const confirmedJob = ref('')
  function save(value: Submission | null) {
    pendingSubmission.value = value
    if (value) sessionStorage.setItem(storageKey, JSON.stringify(value))
    else sessionStorage.removeItem(storageKey)
  }
  let inFlight: ReturnType<typeof createBackendJob> | null = null
  function sendJob(payload?: BackendJobCreatePayload) {
    return inFlight ||= execute(payload).finally(() => { inFlight = null })
  }
  async function execute(payload?: BackendJobCreatePayload) {
    if (readStoredUserInfo()?.id !== owner) throw new Error('Account changed')
    if (!pendingSubmission.value) {
      if (!payload) throw new Error('No original submission')
      save({ key:randomUUID(), payload:JSON.parse(JSON.stringify(payload)) })
      confirmedJob.value = ''
    }
    const original = pendingSubmission.value!
    try {
      const response = await createBackendJob(original.payload, original.key)
      if (readStoredUserInfo()?.id !== owner) throw new Error('Account changed')
      save(null)
      confirmedJob.value = response.data.id
      return response
    } catch (error: any) {
      const status = error?.response?.status
      // Only an explicit rejection allows a new submission. A missing response (or 5xx/408)
      // may mean that the server committed the original request.
      if (status >= 400 && status < 500 && status !== 408) save(null)
      throw error
    }
  }
  return { pendingSubmission, confirmedJob, sendJob }
}
