import { buildWebSocketUrl } from '@/utils/appBase'
import { AUTH_EPOCH_KEY, getStoredGuestCode } from '@/utils/guestSession'

export type WebSocketHandler = (e: MessageEvent) => void
type WebSocketChannel = 'task_state' | 'taskCenter'

export interface WebSocketManager {
  ws: WebSocket | null
  func_dict: Record<WebSocketChannel, Set<WebSocketHandler>>
  setWs(): void
  addFunc(name: WebSocketChannel, func: WebSocketHandler): void
  removeFunc(name: WebSocketChannel, func?: WebSocketHandler): void
  reconnect(): void
}

let retryTimer: ReturnType<typeof setTimeout> | undefined
let retryDelay = 1000
let socketIdentity = ''

const websocket: WebSocketManager = {
  ws: null,
  func_dict: {
    task_state: new Set(),
    taskCenter: new Set(),
  },

  setWs: function() {
    clearTimeout(retryTimer)
    const bearerToken = localStorage.getItem('cs_bearer_token')
    // A guest restored from a recovery link has only its code.
    const guestCode = bearerToken ? '' : getStoredGuestCode()
    const identity = bearerToken || (guestCode && `guest:${guestCode}`)
    // A remounted layout must not open a second socket that delivers every event twice,
    // but a socket opened with another sign-in's token must not keep delivering that user's events.
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) {
      if (identity === socketIdentity) return
      const previous = this.ws
      this.ws = null
      previous.close()
    }
    // Retry with backoff so a backend restart, network drop or late guest sign-in does not silence task updates.
    const retry = () => {
      retryTimer = setTimeout(() => this.setWs(), retryDelay)
      retryDelay = Math.min(retryDelay * 2, 30000)
    }
    const webSocketUrl = new URL(buildWebSocketUrl('/ws/subscribe'))
    if (!identity) {
      retry()
      return
    }
    // Browser credentials travel in the subprotocol header so access logs never contain them.
    const ws = bearerToken
      ? new WebSocket(webSocketUrl.toString(), ['genova.bearer', bearerToken])
      : new WebSocket(webSocketUrl.toString(), ['genova.guest', guestCode])
    
    ws.onopen = () => {
      if (this.ws !== ws) return
      retryDelay = 1000
      window.dispatchEvent(new Event('genova:connection-restored'))
    }
    
    ws.onclose = () => {
      if (this.ws !== ws) return
      this.ws = null
      retry()
    }
    
    ws.onmessage = (e: MessageEvent) => {
      if (this.ws !== ws) return
      for (const key in this.func_dict) {
        const handlers = this.func_dict[key as WebSocketChannel]
        for (const handler of handlers) {
          try {
            handler(e)
          } catch (err) {
            console.error(`WebSocket handler failed for ${key}:`, err)
          }
        }
      }
    }

    socketIdentity = identity
    this.ws = ws
  },

  addFunc: function(name: WebSocketChannel, func: WebSocketHandler) {
    this.func_dict[name].add(func)
  },

  removeFunc: function(name: WebSocketChannel, func?: WebSocketHandler) {
    if (!func) {
      this.func_dict[name].clear()
      return
    }
    this.func_dict[name].delete(func)
  },

  reconnect: function() {
    const previous = this.ws
    this.ws = null
    try {
      previous?.close()
    } catch (err) {
      console.log(err)
    }
    retryDelay = 1000
    this.setWs()
  }
}

// Logout or a user switch drops the previous user's socket; setWs keeps retrying until the next sign-in stores a token.
window.addEventListener('genova:auth-cleared', () => websocket.reconnect())
window.addEventListener('genova:auth-updated', () => websocket.setWs())
window.addEventListener('online', () => websocket.setWs())
window.addEventListener('storage', (e) => {
  if (e.key === AUTH_EPOCH_KEY || e.key === null) websocket.reconnect()
})

export default websocket 
