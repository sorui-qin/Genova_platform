import { ref, computed } from 'vue'
import { createGuestSessionApi, getCurrentUserApi, signoutApi } from '@/api/user'
import { translate } from '@/i18n'
import {
  AUTH_BEARER_TOKEN_KEY,
  AUTH_SIGNED_IN_KEY,
  AUTH_REFRESH_TOKEN_KEY,
  clearStoredAuthState,
  getStoredGuestCode,
  normalizeGuestCode,
  persistUserInfo,
  readStoredUserInfo,
  storeAuthTokens,
  storeGuestCode,
} from '@/utils/guestSession'

let sessionBootstrapPromise: Promise<boolean> | null = null
let bootstrapGuestCode = ''
window.addEventListener('genova:auth-cleared', () => { sessionBootstrapPromise = null })
window.addEventListener('genova:auth-changing', () => { sessionBootstrapPromise = null })
window.addEventListener('storage', event => {
  if (!event.key || ['cs_bearer_token', 'cs_guest_code', 'cs_user_info', 'cs_signined'].includes(event.key)) sessionBootstrapPromise = null
})

export function useAuth() {
  const isAuthenticated = ref(false)
  
  // 公共路由列表（不需要登录的页面）
  const publicRoutes = [
    '/',
    '/index',
    '/login',
    '/sign_up', 
    '/forget_password'
  ]

  // 检查用户是否已认证
  const checkAuth = () => {
    const isSignedIn = localStorage.getItem(AUTH_SIGNED_IN_KEY) === 'true'
    const hasBearerToken = !!localStorage.getItem(AUTH_BEARER_TOKEN_KEY)
    const hasGuestCode = !!getStoredGuestCode()
    const userInfo = readStoredUserInfo()

    isAuthenticated.value = (isSignedIn || hasBearerToken || hasGuestCode) && !!userInfo
    return isAuthenticated.value
  }

  const ensureGuestSession = async (options?: { guestCode?: string }) => {
    const incomingGuestCode = normalizeGuestCode(options?.guestCode)
    if (readStoredUserInfo()?.claim_pending_signin) return false
    if (sessionBootstrapPromise && bootstrapGuestCode === incomingGuestCode) {
      return sessionBootstrapPromise
    }
    const bearerToken = localStorage.getItem(AUTH_BEARER_TOKEN_KEY) || ''
    const originalGuestCode = getStoredGuestCode()
    const stillSelected = () => sessionBootstrapPromise === pending
      && (localStorage.getItem(AUTH_BEARER_TOKEN_KEY) || '') === bearerToken && getStoredGuestCode() === originalGuestCode
    const pending: Promise<boolean> = Promise.resolve().then(async () => {
      if (incomingGuestCode) {
        let user = readStoredUserInfo()
        if ((bearerToken || originalGuestCode) && typeof user?.is_guest !== 'boolean') {
          user = (await getCurrentUserApi({ bearerToken, guestCode: originalGuestCode })).data
          if (!stillSelected()) return false
        }
        if (user?.is_guest === false && !window.confirm(translate('platform.confirmGuestRecovery'))) return false
        if (user?.is_guest === true && incomingGuestCode !== originalGuestCode
          && !window.confirm(translate('platform.confirmSwitchGuestRecovery'))) return false
        const response = await getCurrentUserApi({ guestCode: incomingGuestCode })
        if (!stillSelected() || response.data.is_guest !== true) return false
        if (user?.is_guest !== true || incomingGuestCode !== originalGuestCode) clearStoredAuthState(true)
        storeGuestCode(incomingGuestCode)
        persistUserInfo(response.data)
        localStorage.setItem(AUTH_SIGNED_IN_KEY, 'true')
        isAuthenticated.value = true
        return true
      }
      if (!localStorage.getItem(AUTH_BEARER_TOKEN_KEY) && !getStoredGuestCode()) {
        const response = await createGuestSessionApi()
        if (sessionBootstrapPromise !== pending) return false
        storeAuthTokens(response.data.access_token || '', response.data.refresh_token || '')
        storeGuestCode(response.data.guest_code || '')
      }
      const response = await getCurrentUserApi()
      if (sessionBootstrapPromise !== pending) return false
      persistUserInfo(response.data)
      localStorage.setItem(AUTH_SIGNED_IN_KEY, 'true')
      isAuthenticated.value = true
      return true
    })
      .catch(() => false)
      .finally(() => {
        if (sessionBootstrapPromise === pending) sessionBootstrapPromise = null
      })
    sessionBootstrapPromise = pending
    bootstrapGuestCode = incomingGuestCode
    return pending
  }

  // 检查路由是否为公共路由
  const isPublicRoute = (routePath: string) => {
    return publicRoutes.some(route => {
      if (route === routePath) return true
      // 支持通配符匹配
      if (route.endsWith('*')) {
        const baseRoute = route.slice(0, -1)
        return routePath.startsWith(baseRoute)
      }
      return false
    })
  }

  // 清除认证信息
  const clearAuth = () => {
    clearStoredAuthState()
    isAuthenticated.value = false
  }

  const logout = async () => {
    if (readStoredUserInfo()?.is_guest === true && !window.confirm(translate('platform.confirmLeaveGuest'))) return false
    const refreshToken = localStorage.getItem(AUTH_REFRESH_TOKEN_KEY)
    const bearerToken = localStorage.getItem(AUTH_BEARER_TOKEN_KEY) || ''
    const guestCode = getStoredGuestCode()
    clearAuth()
    // Send the captured credentials; clearing locally also invalidates in-flight refreshes.
    const signout = refreshToken ? signoutApi({ refresh_token: refreshToken }, { bearerToken, guestCode }) : null
    try {
      await signout
    } catch {
      // Local logout still works when the backend is unavailable.
    }
    return !localStorage.getItem(AUTH_BEARER_TOKEN_KEY) && !localStorage.getItem(AUTH_REFRESH_TOKEN_KEY)
      && !getStoredGuestCode() && !readStoredUserInfo() && localStorage.getItem(AUTH_SIGNED_IN_KEY) !== 'true'
  }

  // 设置认证信息
  const setAuth = (userInfo?: any) => {
    localStorage.setItem(AUTH_SIGNED_IN_KEY, 'true')
    if (userInfo) {
      persistUserInfo(userInfo)
    }
    isAuthenticated.value = true
  }

  return {
    isAuthenticated: computed(() => isAuthenticated.value),
    publicRoutes,
    checkAuth,
    ensureGuestSession,
    isPublicRoute,
    clearAuth,
    logout,
    setAuth
  }
}
