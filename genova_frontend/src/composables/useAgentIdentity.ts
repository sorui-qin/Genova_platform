import { onMounted, onUnmounted, ref } from 'vue'
import { AUTH_USER_INFO_KEY, AUTH_EPOCH_KEY, readStoredUserInfo } from '@/utils/guestSession'

// A new component instance owns each identity's asynchronous work and UI state.
export function useAgentIdentity() {
  const selected = () => {
    const id = readStoredUserInfo()?.id
    return id ? id + ':' + (localStorage.getItem(AUTH_EPOCH_KEY) || '') : ''
  }
  const identity = ref(selected())
  const update = () => { identity.value = selected() }
  const storage = (event: StorageEvent) => {
    if (!event.key || [AUTH_USER_INFO_KEY, AUTH_EPOCH_KEY].includes(event.key)) update()
  }
  onMounted(() => {
    window.addEventListener('storage', storage)
    window.addEventListener('genova:auth-updated', update)
    window.addEventListener('genova:auth-cleared', update)
    update()
  })
  onUnmounted(() => {
    window.removeEventListener('storage', storage)
    window.removeEventListener('genova:auth-updated', update)
    window.removeEventListener('genova:auth-cleared', update)
  })
  return identity
}
