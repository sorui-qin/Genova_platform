/// <reference types="vite/client" />
type Drawing = {
  input: string; smarts: string; width: number; height: number
  atoms: number[]; colors: Record<number, [number, number, number]>
  showAtomIndex: boolean; bondWidth: number; regenerateCoords?: boolean; removeHs?: boolean; maxFontSize?: number; rotation?: number
}
type Listener = { resolve: (value: string) => void; reject: (error: Error) => void }
type Work = { id: number; key: string; drawing: Drawing; listeners: Set<Listener> }
const cache = new Map<string, string>()
const queue = new Map<string, Work>()
const MAX_BYTES = 20 * 1024 * 1024
let cacheBytes = 0, sequence = 0
let worker: Worker | undefined, running: Work | undefined
const base = new URL(import.meta.env.BASE_URL, location.origin)

function pump() {
  if (running || !queue.size) return
  if (!worker) {
    worker = new Worker(new URL('vendor/rdkit/render-worker.js', base))
    worker.onmessage = ({ data }) => {
      const work = running
      if (!work || work.id !== data.id) return
      queue.delete(work.key)
      running = undefined
      if (data.error) work.listeners.forEach(listener => listener.reject(new Error(data.error)))
      else {
        const size = 2 * (work.key.length + data.svg.length)
        if (size <= MAX_BYTES) {
          cache.set(work.key, data.svg); cacheBytes += size
          while (cacheBytes > MAX_BYTES) {
            const [key, svg] = cache.entries().next().value!
            cache.delete(key); cacheBytes -= 2 * (key.length + svg.length)
          }
        }
        work.listeners.forEach(listener => listener.resolve(data.svg))
      }
      pump()
    }
    worker.onerror = () => clearMoleculeRenderer()
  }
  running = queue.values().next().value
  worker.postMessage({ ...running!.drawing, id: running!.id, scriptUrl: new URL('vendor/rdkit/RDKit_minimal.js', base).href })
}

export function renderMolecule(drawing: Drawing) {
  const key = JSON.stringify(drawing)
  const cached = cache.get(key)
  if (cached !== undefined) {
    cache.delete(key); cache.set(key, cached)
    return { promise: Promise.resolve(cached), cancel() {} }
  }
  let listener: Listener
  const promise = new Promise<string>((resolve, reject) => { listener = { resolve, reject } })
  const work = queue.get(key) || { id: ++sequence, key, drawing, listeners: new Set<Listener>() }
  work.listeners.add(listener!)
  queue.set(key, work)
  pump()
  return { promise, cancel() {
    work.listeners.delete(listener)
    listener.reject(new DOMException('Rendering cancelled', 'AbortError'))
    if (!work.listeners.size && running !== work) queue.delete(key)
  } }
}

export function clearMoleculeRenderer() {
  worker?.terminate(); worker = undefined; running = undefined
  for (const work of queue.values()) work.listeners.forEach(listener => listener.reject(new Error('Rendering stopped')))
  queue.clear(); cache.clear(); cacheBytes = 0
}

window.addEventListener('genova:auth-cleared', clearMoleculeRenderer)
window.addEventListener('storage', event => { if (event.key === 'cs_user_info') clearMoleculeRenderer() })
