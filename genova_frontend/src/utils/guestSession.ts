export interface StoredUserInfo {
  id?: string
  email?: string
  username?: string
  is_active?: boolean
  is_admin?: boolean
  is_guest?: boolean
  created_at?: string
  claim_pending_signin?: boolean
  [key: string]: any
}

export const AUTH_SIGNED_IN_KEY = 'cs_signined'
export const AUTH_BEARER_TOKEN_KEY = 'cs_bearer_token'
export const AUTH_REFRESH_TOKEN_KEY = 'cs_refresh_token'
export const AUTH_USER_INFO_KEY = 'cs_user_info'
export const AUTH_GUEST_CODE_KEY = 'cs_guest_code'
export const AUTH_EPOCH_KEY = 'cs_auth_epoch'

export function safeAuthRedirect(raw: unknown): string {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || /[\\\u0000-\u001f\u007f]/.test(raw)) return '/dashboard'
  try {
    const url = new URL(raw, window.location.origin)
    if (url.origin !== window.location.origin) return '/dashboard'
    const decode = (value: string) => {
      for (let i = 0; i < 3; i++) {
        const next = decodeURIComponent(value)
        if (next === value) break
        value = next
      }
      return value
    }
    let checkedPath = decode(url.pathname)
    if (checkedPath.startsWith('//') || /[\\?#\u0000-\u001f\u007f]|%[0-9a-f]{2}/i.test(checkedPath)) return '/dashboard'
    // Normalize decoded dot segments for validation, but keep the original encoded route.
    checkedPath = new URL(checkedPath, window.location.origin).pathname
    const base = import.meta.env.BASE_URL.replace(/\/$/, '')
    if (base && (checkedPath === base || checkedPath.startsWith(`${base}/`))) checkedPath = checkedPath.slice(base.length) || '/'
    if (checkedPath.startsWith('//') || /^\/login(?:\/|$)/i.test(checkedPath)) return '/dashboard'
    let path = url.pathname
    if (base && (path === base || path.startsWith(`${base}/`))) path = path.slice(base.length) || '/'
    const secretKey = /^(gc|guest_code|redirect|authorization|api[_-]?key|.*token.*|.*password.*|.*secret.*|.*credential.*)$/i
    for (const key of [...url.searchParams.keys()]) if (secretKey.test(decode(key))) url.searchParams.delete(key)
    const hash = /(?:^|[?&#])(?:gc|guest_code|redirect|authorization|api[_-]?key|[^=&#]*(?:token|password|secret|credential)[^=&#]*)=/i.test(decode(url.hash)) ? '' : url.hash
    const query = url.searchParams.toString()
    return `${path}${query ? `?${query}` : ''}${hash}`
  } catch { return '/dashboard' }
}

export function normalizeGuestCode(raw: unknown): string {
  return String(raw || '').trim()
}

export function getStoredGuestCode(): string {
  return normalizeGuestCode(localStorage.getItem(AUTH_GUEST_CODE_KEY))
}

export function storeGuestCode(code: string): void {
  const normalized = normalizeGuestCode(code)
  if (!normalized) return
  localStorage.setItem(AUTH_GUEST_CODE_KEY, normalized)
}

export function readStoredUserInfo(): StoredUserInfo | null {
  const raw = localStorage.getItem(AUTH_USER_INFO_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      return parsed as StoredUserInfo
    }
  } catch {
    return null
  }
  return null
}

export function persistUserInfo(user: {
  id: string
  email: string
  username: string
  is_active: boolean
  is_admin: boolean
  is_guest: boolean
  created_at: string
}, claimPendingSignIn = false): void {
  const existing = readStoredUserInfo() || {}
  localStorage.setItem(
    AUTH_USER_INFO_KEY,
    JSON.stringify({
      ...existing,
      id: user.id,
      email: user.email,
      username: user.username,
      is_active: user.is_active,
      is_admin: user.is_admin,
      is_guest: user.is_guest,
      created_at: user.created_at,
      claim_pending_signin: claimPendingSignIn,
    }),
  )
  window.dispatchEvent(new Event('genova:auth-updated'))
}

export function storeAuthTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(AUTH_SIGNED_IN_KEY, 'true')
  localStorage.setItem(AUTH_BEARER_TOKEN_KEY, accessToken || '')
  localStorage.setItem(AUTH_REFRESH_TOKEN_KEY, refreshToken || '')
}

export const AUTH_SIGNIN_EPOCH_PREFIX = 'signin-'

// signingIn: new credentials are stored right after, so other tabs must not treat this as a sign-out.
export function clearStoredAuthState(signingIn = false): void {
  localStorage.removeItem(AUTH_SIGNED_IN_KEY)
  localStorage.removeItem(AUTH_BEARER_TOKEN_KEY)
  localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY)
  localStorage.removeItem(AUTH_USER_INFO_KEY)
  localStorage.removeItem(AUTH_GUEST_CODE_KEY)
  // Sign-in also clears first, so a sign-out followed by signing in to the same account still changes the epoch.
  localStorage.setItem(AUTH_EPOCH_KEY, `${signingIn ? AUTH_SIGNIN_EPOCH_PREFIX : ''}${Date.now()}-${Math.random()}`)
  window.dispatchEvent(new Event('genova:auth-cleared'))
}

export function isGuestUser(): boolean {
  return readStoredUserInfo()?.is_guest === true
}
