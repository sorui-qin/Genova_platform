import { listBackendJobs, type BackendJobListOut } from '@/api/genovaBackend'
import { readStoredUserInfo, AUTH_EPOCH_KEY, AUTH_USER_INFO_KEY } from '@/utils/guestSession'

// One job-list poll shared by every subscriber (layout notifications, dashboard).
export const JOB_POLL_INTERVAL = 10000
const MAX_POLL_INTERVAL = 120000

export interface JobListListener {
  update: (jobs: BackendJobListOut[]) => void
  error: (error: unknown) => void
}

/** Delay before the next poll: the base interval, doubled for each consecutive failure up to two minutes. */
export function jobPollDelay(failures: number) {
  return Math.min(JOB_POLL_INTERVAL * 2 ** Math.max(0, failures), MAX_POLL_INTERVAL)
}

const listeners = new Set<JobListListener>()
let timer: ReturnType<typeof setTimeout> | undefined
let running: Promise<void> | null = null
let failures = 0
let revision = 0, refreshQueued = false
let owner = readStoredUserInfo()?.id || ''
let latest: { jobs: BackendJobListOut[]; at: number } | null = null

function schedule() {
  clearTimeout(timer)
  timer = undefined
  // Hidden tabs do not poll; becoming visible again fetches at once.
  if (owner && listeners.size && document.visibilityState !== 'hidden') timer = setTimeout(() => void fetchJobs(), jobPollDelay(failures))
}

function fetchJobs(): Promise<void> {
  if (!owner) return Promise.resolve()
  running ||= (async () => {
    clearTimeout(timer)
    const current = revision
    const selectedOwner = owner
    try {
      const jobs = (await listBackendJobs({ limit: 200 })).data
      if (current !== revision || readStoredUserInfo()?.id !== selectedOwner) return
      failures = 0
      latest = { jobs, at: Date.now() }
      listeners.forEach(listener => listener.update(jobs))
    } catch (error) {
      if (current !== revision || readStoredUserInfo()?.id !== selectedOwner) return
      failures++
      listeners.forEach(listener => listener.error(error))
    } finally {
      running = null
      if (refreshQueued && listeners.size) { refreshQueued = false; void fetchJobs() }
      else schedule()
    }
  })()
  return running
}

function refreshSnapshot() {
  revision++
  if (!listeners.size || !owner) return
  if (running) refreshQueued = true
  else void fetchJobs()
}
function onIdentityChange() {
  const next = readStoredUserInfo()?.id || ''
  if (next === owner) return
  owner = next; latest = null; failures = 0; refreshQueued = false; revision++
  clearTimeout(timer)
  listeners.forEach(listener => listener.update([]))
  if (owner) refreshSnapshot()
}
window.addEventListener('online', refreshSnapshot)
window.addEventListener('genova:connection-restored', refreshSnapshot)
window.addEventListener('genova:auth-updated', onIdentityChange)
window.addEventListener('genova:auth-cleared', onIdentityChange)
window.addEventListener('storage', event => {
  if (!event.key || [AUTH_EPOCH_KEY, AUTH_USER_INFO_KEY].includes(event.key)) onIdentityChange()
})

function onVisibilityChange() {
  if (document.visibilityState === 'hidden') { clearTimeout(timer); timer = undefined }
  else if (listeners.size) refreshSnapshot()
}

/** Starts receiving the shared job list; `refresh` fetches now (joining a request already in flight). */
export function subscribeJobList(listener: JobListListener) {
  listeners.add(listener)
  if (listeners.size === 1) document.addEventListener('visibilitychange', onVisibilityChange)
  // A recent result is reused, so a second subscriber does not cause an extra request.
  if (latest && Date.now() - latest.at < JOB_POLL_INTERVAL && failures === 0) {
    listener.update(latest.jobs)
    // After every subscriber left, stop() cleared the timer: arm it again or polling would never resume.
    if (!timer && !running) schedule()
  } else void fetchJobs()
  return {
    refresh: fetchJobs,
    stop() {
      if (!listeners.delete(listener) || listeners.size) return
      clearTimeout(timer)
      timer = undefined
      document.removeEventListener('visibilitychange', onVisibilityChange)
    },
  }
}
