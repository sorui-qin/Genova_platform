const DEFAULT_APP_BASE = '/genova/'

export function normalizeBasePath(basePath?: string): string {
  const rawBasePath = (basePath || DEFAULT_APP_BASE).trim()
  if (!rawBasePath || rawBasePath === '/') {
    return '/'
  }

  const withoutEdgeSlashes = rawBasePath.replace(/^\/+|\/+$/g, '')
  if (!withoutEdgeSlashes) {
    return '/'
  }

  return `/${withoutEdgeSlashes}/`
}

export const APP_BASE_PATH = normalizeBasePath(import.meta.env.BASE_URL || import.meta.env.VITE_APP_BASE_PATH)

export function withAppBase(path = ''): string {
  if (!path) {
    return APP_BASE_PATH
  }

  if (APP_BASE_PATH !== '/' && path.startsWith(APP_BASE_PATH)) {
    return path
  }

  const normalizedPath = path.replace(/^\/+/, '')
  return APP_BASE_PATH === '/' ? `/${normalizedPath}` : `${APP_BASE_PATH}${normalizedPath}`
}

export function buildWebSocketUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return new URL(withAppBase(path), `${protocol}//${window.location.host}`).toString()
}
