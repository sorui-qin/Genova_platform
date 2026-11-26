import type { App } from 'vue'
import { setupAutoAnimate } from './autoAnimate'
import { setupDayjs } from './dayjs'
import { setupNProgress } from './nprogress'
import { setupPinia } from './pinia'
import { setupTanstackVueQuery } from './tanstack-vue-query'

export function setupPlugins(app: App) {
  setupDayjs()
  setupNProgress()
  setupAutoAnimate(app)
  setupTanstackVueQuery(app)
  setupPinia(app)
}
