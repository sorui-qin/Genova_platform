// Browser drafts are keyed by the account's immutable id and the conversation.
export interface DraftAttachment { name: string; file?: File; datasetId?: string; fileId?: string; uploadId?: string; cancelPending?: boolean }
export interface AgentDraft {
  text: string
  files: Record<string, DraftAttachment>
  context: string
  request: Record<string, any> | null
  clientId: string
  saved_at: number
}
const memory = new Map<string, AgentDraft>()
export const agentDraftKey = (owner: string, scope: string, session: string) =>
  `genova:agent:draft:v2:${owner}:${scope}:${session || 'new'}`
let database: Promise<IDBDatabase> | undefined
function db() {
  return database ||= new Promise((resolve, reject) => {
    const request = indexedDB.open('genova-agent-drafts', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('drafts')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}
export function saveAgentDraft(key: string, draft: AgentDraft) {
  const exists = Boolean(draft.text.trim() || Object.keys(draft.files).length || draft.context || draft.request)
  if (exists) memory.set(key, draft)
  else memory.delete(key)
  if (exists) localStorage.setItem(key, JSON.stringify(draft))
  else localStorage.removeItem(key)
  // IndexedDB can retain the original browser File, unlike JSON storage.
  void db().then(database => {
    const transaction = database.transaction('drafts', 'readwrite')
    if (exists) transaction.objectStore('drafts').put(draft, key)
    else transaction.objectStore('drafts').delete(key)
  }).catch(() => {})
}
export async function readAgentDraft(key: string): Promise<AgentDraft | null> {
  const raw = localStorage.getItem(key)
  if (!raw) return null
  try {
    const metadata = JSON.parse(raw) as AgentDraft
    const cached = memory.get(key)
    if (cached?.saved_at === metadata.saved_at) return cached
    const stored = await db().then(database => new Promise<AgentDraft | undefined>((resolve, reject) => {
      const request = database.transaction('drafts').objectStore('drafts').get(key)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })).catch(() => undefined)
    if (stored?.saved_at === metadata.saved_at) return stored
    // JSON can retain attachment references, but not the actual browser File.
    for (const item of Object.values(metadata.files)) delete item.file
    return metadata
  } catch { return null }
}
