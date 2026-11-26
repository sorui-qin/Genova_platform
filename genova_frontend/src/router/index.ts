import { setupLayouts } from 'virtual:generated-layouts'
import { createRouter, createWebHistory } from 'vue-router'
// @ts-ignore
import generatedRoutes from '~pages'
import { createRouterGuard } from './guard'

const routes = setupLayouts(generatedRoutes)
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior() {
    return {
      x: 0,
      y: 0,
      behavior: 'smooth'
    }
  },
})

router.beforeEach((to) => {
  // There is no 404 page; send unknown addresses home instead of rendering a blank screen.
  if (!to.matched.length) return '/'
})

createRouterGuard(router)

export default router
