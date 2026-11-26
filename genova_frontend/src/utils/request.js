import axios from 'axios'
import router from '../router'
import { APP_BASE_PATH } from './appBase'
// import { useRouter } from 'vue-router'
import { useToast } from '@/components/ui/toast'
import { clearStoredAuthState, readStoredUserInfo } from './guestSession'
import i18n, { translate } from '@/i18n'
import { requestErrorMessage } from './requestError'

let baseURL = APP_BASE_PATH
axios.defaults.baseURL = baseURL
// const router = useRouter()
// const router = Vrouter

const instance = axios.create({
  baseURL,
  // headers: {
  //   'content-type': 'application/json'
  // },
  withCredentials: true
})

// 401 toast & redirect dedup
let isHandling401 = false
let lastAuthToastAt = 0
const AUTH_TOAST_DEBOUNCE_MS = 3000
let refreshPromise = null
let refreshedTokens = null

const isAuthEndpoint = (url = '') => {
  return [
    '/api/v1/auth/login',
    '/api/v1/auth/register',
    '/api/v1/auth/refresh',
    '/api/v1/auth/logout',
    '/api/v1/auth/guest',
    '/api/v1/auth/claim',
  ].some(path => url.includes(path))
}

const notifyAuthExpiredOnce = () => {
  const now = Date.now()
  if (now - lastAuthToastAt < AUTH_TOAST_DEBOUNCE_MS) return
  lastAuthToastAt = now
  useToast().toast({
    variant: "destructive",
    title: translate('platform.requestErrors.title'),
    description: translate('platform.requestErrors.signInAgain')
  })
}

const refreshAccessToken = async () => {
  const currentRefreshToken = localStorage.getItem('cs_refresh_token')
  if (!currentRefreshToken) {
    throw new Error('Missing refresh token')
  }

  if (!refreshPromise) {
    const previousAccessToken = localStorage.getItem('cs_bearer_token')
    refreshPromise = axios
      .post(
        '/api/v1/auth/refresh',
        { refresh_token: currentRefreshToken },
        {
          baseURL,
          withCredentials: true,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }
      )
      .then((resp) => {
        if (localStorage.getItem('cs_refresh_token') !== currentRefreshToken) {
          throw new axios.CanceledError('Authentication changed during token refresh')
        }
        const accessToken = resp?.data?.access_token || ''
        const nextRefreshToken = resp?.data?.refresh_token || ''
        if (!accessToken || !nextRefreshToken) {
          throw new Error('Invalid refresh response')
        }
        localStorage.setItem('cs_bearer_token', accessToken)
        localStorage.setItem('cs_refresh_token', nextRefreshToken)
        refreshedTokens = { previous: previousAccessToken, current: accessToken }
        return accessToken
      })
      .finally(() => {
        refreshPromise = null
      })
  }

  return refreshPromise
}

// Whether a request was sent with the credentials that are still selected.
const requestAuthIsCurrent = (config) => {
  const bearer = localStorage.getItem('cs_bearer_token')
  return (config.headers?.Authorization || '') === (bearer ? `Bearer ${bearer}` : '')
    && (config.headers?.['X-Guest-Code'] || '') === (localStorage.getItem('cs_guest_code') || '')
}

// 请求拦截器
// 设置axios请求头加入token
instance.interceptors.request.use(
  config => {
    // config.headers.token = localStorage.getItem('csrf_access_token')
    config.headers = config.headers || {}
    // An explicit credential probe must not refresh or clear the active account.
    const authorization = typeof config.headers.get === 'function' ? config.headers.get('Authorization') : config.headers.Authorization
    const guestCode = typeof config.headers.get === 'function' ? config.headers.get('X-Guest-Code') : config.headers['X-Guest-Code']
    config._explicitAuth = config._explicitAuth ?? (authorization !== undefined || guestCode !== undefined)
    config.headers['X-Requested-With'] = 'XMLHttpRequest';
    config.headers['Accept-Language'] = i18n.global.locale.value
    if (authorization === undefined && localStorage.getItem('cs_bearer_token')) {
      config.headers['Authorization'] = 'Bearer ' + localStorage.getItem('cs_bearer_token')
    }
    if (guestCode === undefined && localStorage.getItem('cs_guest_code')) {
      config.headers['X-Guest-Code'] = localStorage.getItem('cs_guest_code')
    }
    if (config.url?.indexOf('AWSAccessKeyId=') !== -1) {
      config.headers['content-type'] = ''
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
instance.interceptors.response.use(
  response => {
    return response
  },
  async error => {
    const status = error?.response?.status
    const originalRequest = error?.config || {}
    const requestUrl = originalRequest?.url || ''
    // LLM authorization and configuration failures do not invalidate the platform login.
    if ((requestUrl === '/api/v1/agent/settings' || requestUrl.startsWith('/api/v1/agent/settings/'))
      && ['provider_api', 'configuration'].includes(error?.response?.data?.detail?.error_source)) return Promise.reject(error)
    if ((status === 401 || status === 403) && originalRequest._explicitAuth) return Promise.reject(error)
    // The guest recovery code was invalidated by a successful claim. Keep the
    // pending sign-in notice instead of clearing it and bootstrapping an empty guest.
    if ((status === 401 || status === 403) && readStoredUserInfo()?.claim_pending_signin) return Promise.reject(error)

    if ((status === 401 || status === 403) && !isAuthEndpoint(requestUrl)) {
      const bearer = localStorage.getItem('cs_bearer_token')
      const sameGuest = (originalRequest.headers?.['X-Guest-Code'] || '') === (localStorage.getItem('cs_guest_code') || '')
      if (!requestAuthIsCurrent(originalRequest)) {
        if (status === 401 && !originalRequest._retry && sameGuest && refreshedTokens?.current === bearer
          && originalRequest.headers?.Authorization === `Bearer ${refreshedTokens.previous}`) {
          originalRequest._retry = true
          originalRequest.headers.Authorization = `Bearer ${bearer}`
          return instance(originalRequest)
        }
        return Promise.reject(new axios.CanceledError('Authentication changed during request'))
      }
    }

    if (status === 401 && !originalRequest._retry && !isAuthEndpoint(requestUrl)) {
      try {
        originalRequest._retry = true
        const newAccessToken = await refreshAccessToken()
        originalRequest.headers = originalRequest.headers || {}
        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`
        return instance(originalRequest)
      } catch (refreshError) {
        if (axios.isCancel(refreshError)) return Promise.reject(refreshError)
        // Another account may have signed in while the refresh was pending.
        if (!requestAuthIsCurrent(originalRequest)) {
          return Promise.reject(new axios.CanceledError('Authentication changed during token refresh'))
        }
        notifyAuthExpiredOnce()
      }
    }

    if (status === 401 || status === 403) {
      if (!isHandling401 && !isAuthEndpoint(requestUrl)) {
        isHandling401 = true
        const hasGuestCode = !!localStorage.getItem('cs_guest_code')
        clearStoredAuthState()
        useToast().toast({
          variant: "destructive",
          title: translate('platform.requestErrors.title'),
          description: translate(hasGuestCode ? 'platform.requestErrors.guestInvalid' : 'platform.requestErrors.signInAgain'),
        })
        if (router.currentRoute.value.path.startsWith('/admin-monitor')) {
          router.push('/login').finally(() => {
            isHandling401 = false
          })
        } else {
          isHandling401 = false
        }
      }
    } else if ([502, 404, 500].includes(status) && !(status === 404 && originalRequest.method === 'delete')) {
      // Deleting something already gone is not an error for the user; DELETE callers report other failures themselves.
      useToast().toast({
        variant: "destructive",
        title: translate('platform.requestErrors.title'),
        description: requestErrorMessage(error)
      })
    }
    return Promise.reject(error)
  }
)

export default instance
