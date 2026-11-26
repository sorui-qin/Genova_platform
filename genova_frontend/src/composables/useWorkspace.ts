import { computed, type InjectionKey, type Ref, type WritableComputedRef } from 'vue'
import { useSessionStorage } from '@vueuse/core'
import { readStoredUserInfo } from '@/utils/guestSession'

export interface WorkspaceTask {
  name: string
  stage?: string
  context?: string
  version?: number | string
  draft?: boolean
  details?: () => void
}
export const workspaceTaskKey: InjectionKey<Ref<WorkspaceTask | null>> = Symbol('workspaceTask')
export const workspaceHeaderKey: InjectionKey<{ target: Ref<HTMLElement | null>; active: Ref<boolean> }> = Symbol('workspaceHeader')

export function useWorkspaceState<T extends Record<string, any>>(page: string, scope: () => string, defaults: T) {
  const user = readStoredUserInfo()?.id || 'guest'
  const state = useSessionStorage(computed(() => `genova:view:${user}:${page}:${scope()}`), defaults, { mergeDefaults: true })
  return Object.fromEntries(Object.keys(defaults).map(key => [key, computed({
    get: () => state.value[key],
    set: value => { state.value = { ...state.value, [key]: value } },
  })])) as { [K in keyof T]: WritableComputedRef<T[K]> }
}
