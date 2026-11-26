import { defineStore } from 'pinia'

type EnvType = 'saas' | 'private'

interface StatusState {
  env: EnvType
}

export const useStore = defineStore('status', {
  state: (): StatusState => ({
    env: 'saas' // 环境变量: 'saas' | 'private'
  }),
  getters: {
    isSaas: (state): boolean => state.env === 'saas',
    isPrivate: (state): boolean => state.env === 'private'
  },
  actions: {
    setEnv(env: EnvType) {
      this.env = env
    }
  }
})

export default useStore