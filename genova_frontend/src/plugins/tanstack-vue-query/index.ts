import type { App } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { shallowRef } from 'vue'
import { AUTH_EPOCH_KEY, AUTH_USER_INFO_KEY, readStoredUserInfo } from '@/utils/guestSession'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
    },
  },
})

export const datacenterIdentity = shallowRef([
  readStoredUserInfo()?.id || '', localStorage.getItem(AUTH_EPOCH_KEY) || '',
])

export function setupTanstackVueQuery(app: App) {
  const syncIdentity = (event: Event) => {
    if (event.type === 'storage' && ![null, AUTH_EPOCH_KEY, AUTH_USER_INFO_KEY].includes((event as StorageEvent).key)) return
    const next = [readStoredUserInfo()?.id || '', localStorage.getItem(AUTH_EPOCH_KEY) || '']
    if (next.every((value, index) => value === datacenterIdentity.value[index])
      && !['genova:auth-cleared', 'genova:auth-changing'].includes(event.type)) return
    void queryClient.cancelQueries({ queryKey: ['datacenter'] })
    queryClient.removeQueries({ queryKey: ['datacenter'] })
    datacenterIdentity.value = next
  }
  for (const event of ['storage', 'genova:auth-cleared', 'genova:auth-changing', 'genova:auth-updated']) {
    window.addEventListener(event, syncIdentity)
  }
  app.use(VueQueryPlugin, {
    enableDevtoolsV6Plugin: true,
    queryClient,
  })
}
