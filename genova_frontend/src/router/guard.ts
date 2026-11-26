import type { Router } from 'vue-router'
import { ref } from 'vue'
import NProgress from 'nprogress'
// @ts-ignore
import 'nprogress/nprogress.css'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/components/ui/toast'
import { translate } from '@/i18n'
import { AUTH_EPOCH_KEY, AUTH_SIGNIN_EPOCH_PREFIX, readStoredUserInfo, safeAuthRedirect } from '@/utils/guestSession'

// 配置 NProgress
NProgress.configure({
  easing: 'ease',
  speed: 500,
  showSpinner: false,
  trickleSpeed: 200,
  minimum: 0.3
})

/**
 * 设置认证守卫
 */
function setupAuthGuard(router: Router) {
  const { checkAuth, ensureGuestSession, isPublicRoute } = useAuth()

  const path_public_list = [
    'index',
    '404',
    'login',
    'sign_up',
    'forget_password',
    'pswd_transit',
  ]

  // Another tab signed out: leave protected pages now instead of on the next request.
  let authRedirecting = false
  window.addEventListener('storage', event => {
    // Signing in elsewhere also bumps the epoch, but marks it because new credentials follow.
    if (event.key !== AUTH_EPOCH_KEY || event.newValue?.startsWith(AUTH_SIGNIN_EPOCH_PREFIX)) return
    // A sign-in that already replaced this sign-out makes the queued event stale.
    if (event.newValue !== localStorage.getItem(AUTH_EPOCH_KEY)) return
    const route = router.currentRoute.value
    if (authRedirecting || path_public_list.includes(route.name as string) || isPublicRoute(route.path)) return
    authRedirecting = true
    // Tell the user why the page changes; unsent input is kept by the page itself and restored after sign-in.
    useToast().toast({ title: translate('platform.authChanged.title'), description: translate('platform.authChanged.description'), variant: 'destructive' })
    router.replace({ path: '/login', query: { redirect: safeAuthRedirect(route.fullPath) } }).finally(() => { authRedirecting = false })
  })

  router.beforeEach(async (to) => {
    NProgress.start()

    const if_authed = ref(false)
    const protectedPrefixes = ['/admin-monitor']
    const rawGuestCode = Array.isArray(to.query.gc) ? to.query.gc[0] : to.query.gc

    document.body.scrollTop = 0
    document.documentElement.scrollTop = 0

    const publicRoute = path_public_list.includes(to.name as string) || isPublicRoute(to.path)
    if (!publicRoute && readStoredUserInfo()?.claim_pending_signin) {
      return { path: '/login', query: { redirect: safeAuthRedirect(to.fullPath) }, replace: true }
    }

    const guestCode = typeof rawGuestCode === 'string' ? rawGuestCode.trim() : ''
    if (guestCode || !publicRoute) {
      const adopted = await ensureGuestSession({ guestCode })
      if (guestCode && adopted) {
        const query = { ...to.query }
        delete query.gc
        return { path: to.path, query, hash: to.hash, replace: true }
      }
      if (guestCode && !adopted) useToast().toast({
        title: translate('platform.guestRecoveryNotApplied'),
        description: translate('platform.guestRecoveryNotAppliedDetail'),
        variant: 'destructive',
      })
    }

    if_authed.value = checkAuth()

    if (!if_authed.value && protectedPrefixes.some(prefix => to.path.startsWith(prefix))) {
      return {
        path: '/login',
        query: { redirect: safeAuthRedirect(to.fullPath) },
      }
    }

    return true
  })

  router.afterEach(() => {
    // 完成进度条
    NProgress.done()
  })

  router.onError(() => {
    // 路由错误时也要完成进度条
    NProgress.done()
  })
}

export function createRouterGuard(router: Router) {
  setupAuthGuard(router)
}
