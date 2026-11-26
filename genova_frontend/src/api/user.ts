import { CanceledError, type AxiosResponse } from 'axios'
import request from '@/utils/request'
import { AUTH_EPOCH_KEY, clearStoredAuthState, persistUserInfo, readStoredUserInfo, storeAuthTokens } from '@/utils/guestSession'

export interface ApiResponse<T = any> { code?: number; message?: string; data: T }
export interface RegisterParams { email: string; username: string; password: string }
export interface SigninParams { email: string; password: string }
export interface ResetPasswordParams { token: string; password: string; confirm_password: string }

export async function signupApi(params: RegisterParams): Promise<AxiosResponse<ApiResponse>> {
  return request.post<ApiResponse>('/api/v1/auth/register', params)
}

/**
 * User signin
 */
export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  access_token_expires_in: number
}

export interface BackendCurrentUser {
  id: string
  email: string
  username: string
  is_active: boolean
  is_admin: boolean
  is_guest: boolean
  created_at: string
}

export interface GuestSessionResponse extends LoginResponse {
  guest_code: string
  is_guest: true
  username: string
}

// A refreshed access token keeps its JWT subject (the user id); non-JWT tokens compare as-is.
function tokenSubject(token: string): string {
  try { return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).sub || token } catch { return token }
}

// The selected identity: a same-user token refresh keeps it, a sign-in, sign-out or account switch changes it.
export function authIdentity(): string {
  return JSON.stringify([
    tokenSubject(localStorage.getItem('cs_bearer_token') || ''),
    localStorage.getItem('cs_guest_code') || '',
    localStorage.getItem('cs_user_info'),
    localStorage.getItem(AUTH_EPOCH_KEY) || '',
  ])
}

/** Sign in; rejects with CanceledError if the selected identity changed since `identity` was read. */
export async function signinApi(params: SigninParams, identity = authIdentity()): Promise<AxiosResponse<LoginResponse>> {
  invalidateCurrentUser()
  const response = await request.post<LoginResponse>('/api/v1/auth/login', params)
  if (authIdentity() !== identity) throw new CanceledError('Authentication changed during sign-in')
  return response
}

export async function refreshTokenApi(refresh_token: string): Promise<AxiosResponse<LoginResponse>> {
  return request.post<LoginResponse>('/api/v1/auth/refresh', { refresh_token })
}

/** Change password; rejects with CanceledError if the selected identity changed since `identity` was read. */
export async function changePasswordApi(params: { current_password: string; new_password: string }, identity = authIdentity()): Promise<AxiosResponse<LoginResponse>> {
  const response = await request.post<LoginResponse>('/api/v1/auth/password', params)
  if (authIdentity() !== identity) throw new CanceledError('Authentication changed during password change')
  return response
}

export async function createGuestSessionApi(): Promise<AxiosResponse<GuestSessionResponse>> {
  return request.post<GuestSessionResponse>('/api/v1/auth/guest')
}

let claiming = false

export async function claimGuestSessionApi(params: {
  email: string
  username: string
  password: string
}): Promise<AxiosResponse<BackendCurrentUser>> {
  if (claiming) throw new CanceledError('Account claim is already in progress')
  claiming = true
  // Only a different identity cancels the claim; a same-user token refresh does not.
  const selected = authIdentity
  let snapshot = selected()
  try {
    invalidateCurrentUser()
    const stored = readStoredUserInfo()
    let user: BackendCurrentUser
    if (stored?.claim_pending_signin) {
      // This account has already been claimed: only retry signing in.
      user = {
        id: stored.id || '', email: stored.email || '', username: stored.username || '',
        is_active: stored.is_active === true, is_admin: stored.is_admin === true,
        is_guest: false, created_at: stored.created_at || '',
      }
    } else {
      const response = await request.post<BackendCurrentUser>('/api/v1/auth/claim', params)
      if (selected() !== snapshot) throw new CanceledError('Authentication changed during account claim')
      user = response.data
      persistUserInfo(user, true)
      snapshot = selected()
    }
    const login = await signinApi({ email: user.email, password: params.password }, snapshot)
    if (!login.data.access_token || !login.data.refresh_token) throw new Error('Invalid sign-in response')
    clearStoredAuthState(true)
    storeAuthTokens(login.data.access_token, login.data.refresh_token)
    persistUserInfo(user)
    return { ...login, data: user }
  } finally { claiming = false }
}

let currentUserRequest: {
  key: string
  expiresAt: number
  promise: Promise<AxiosResponse<BackendCurrentUser>>
} | null = null

function currentAuthKey() {
  return JSON.stringify([localStorage.getItem('cs_bearer_token') || '', localStorage.getItem('cs_guest_code') || ''])
}

function invalidateCurrentUser(identityChanged = true) {
  currentUserRequest = null
  if (identityChanged) window.dispatchEvent(new Event('genova:auth-changing'))
}

window.addEventListener('genova:auth-cleared', () => { currentUserRequest = null })
window.addEventListener('storage', event => {
  if (!event.key || ['cs_bearer_token', 'cs_guest_code'].includes(event.key)) invalidateCurrentUser(false)
})

export function getCurrentUserApi(credentials?: { bearerToken?: string; guestCode: string }): Promise<AxiosResponse<BackendCurrentUser>> {
  // Validate a recovery target without replacing or caching the selected account.
  if (credentials) return request.get<BackendCurrentUser>('/api/v1/auth/me', {
    headers: {
      Authorization: credentials.bearerToken ? `Bearer ${credentials.bearerToken}` : '',
      'X-Guest-Code': credentials.guestCode,
    },
  })
  if (readStoredUserInfo()?.claim_pending_signin) throw new Error('Claimed account requires sign-in')
  const key = currentAuthKey()
  if (currentUserRequest?.key === key && currentUserRequest.expiresAt > Date.now()) {
    return currentUserRequest.promise
  }
  const pending: NonNullable<typeof currentUserRequest> = {
    key,
    expiresAt: Infinity,
    promise: request.get<BackendCurrentUser>('/api/v1/auth/me').then(response => {
      // Compare the actual request credentials, including a refreshed access token.
      const headers = response.config.headers
      const requestKey = JSON.stringify([
        String(headers.Authorization || '').replace(/^Bearer /, ''),
        headers['X-Guest-Code'] || '',
      ])
      if (currentUserRequest !== pending || requestKey !== currentAuthKey()) {
        throw new CanceledError('Authentication changed during user request')
      }
      pending.key = requestKey
      pending.expiresAt = Date.now() + 30_000
      return response
    }).catch(error => {
      if (currentUserRequest === pending) currentUserRequest = null
      throw error
    }),
  }
  currentUserRequest = pending
  return pending.promise
}

/**
 * Reactivate user account
 */
export async function signoutApi(params: { refresh_token: string }, credentials?: { bearerToken: string; guestCode: string }): Promise<AxiosResponse<ApiResponse>> {
  invalidateCurrentUser()
  return request.post<ApiResponse>('/api/v1/auth/logout', params, credentials ? {
    headers: { Authorization: credentials.bearerToken ? `Bearer ${credentials.bearerToken}` : '', 'X-Guest-Code': credentials.guestCode },
  } : undefined)
}

/**
 * Forgot password
 */
export async function forgotPasswordApi(params: { email: string }): Promise<AxiosResponse<ApiResponse>> {
  return request.post<ApiResponse>('/api/v1/auth/forgot_password', params)
}

/**
 * Reset password - GET request to validate token
 */
export async function resetPasswordValidateApi(token: string): Promise<AxiosResponse<ApiResponse>> {
  const url = `/api/v1/auth/reset_password?token=${encodeURIComponent(token)}`
  return request.get<ApiResponse>(url)
}

/**
 * Reset password - POST request to update password
 */
export async function resetPasswordUpdateApi(
  params: ResetPasswordParams
): Promise<AxiosResponse<ApiResponse>> {
  const url = `/api/v1/auth/reset_password`
  return request.post<ApiResponse>(url, params)
}

/**
 * Activate user account
 */
