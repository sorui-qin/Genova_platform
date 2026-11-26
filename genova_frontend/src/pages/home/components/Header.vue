<template>
  <header
    :class="[
      'fixed inset-x-0 top-0 z-50 transition-all duration-300',
      isScrolled
        ? 'bg-white/80 shadow-[0_1px_0_0_rgba(0,0,0,0.06)] backdrop-blur-xl'
        : 'bg-transparent',
    ]"
  >
    <div class="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
      <button class="flex shrink-0 items-center gap-2.5" @click="goHome">
        <img
          :src="genovaLogo"
          alt="Genova"
          class="h-9 w-auto object-contain"
        />
      </button>

      <nav class="hidden items-center gap-7 lg:flex">
        <button
          v-for="item in navItems"
          :key="item.target"
          class="text-sm text-slate-500 transition hover:text-slate-900"
          @click="scrollToSection(item.target)"
        >
          {{ item.label }}
        </button>
      </nav>

      <LanguageSwitcher />
      <div class="hidden items-center gap-2 lg:flex">
        <template v-if="isAuthenticated">
          <AccountMenu />
          <Button
            class="h-8 rounded-none bg-blue-600 px-4 text-xs font-medium text-white hover:bg-blue-700"
            @click="goDashboard"
          >
            {{ $t('platform.dashboard') }}
          </Button>
        </template>
        <template v-else>
          <Button
            variant="outline"
            class="h-8 rounded-none border-slate-300 px-3 text-xs text-slate-700 hover:bg-slate-50"
            @click="goGuest"
          >
            {{ $t('platform.continueGuest') }}
          </Button>
          <Button
            variant="ghost"
            class="h-8 px-3 text-xs text-slate-600 hover:text-slate-900"
            @click="goLogin"
          >
            {{ $t('platform.signIn') }}
          </Button>
          <Button
            class="h-8 rounded-none bg-blue-600 px-4 text-xs font-medium text-white hover:bg-blue-700"
            @click="goSignup"
          >
            {{ $t('platform.signUp') }}
          </Button>
        </template>
      </div>

      <button
        class="flex h-8 w-8 items-center justify-center text-slate-600 transition hover:text-slate-900 lg:hidden"
        :aria-label="$t('platform.menu')"
        :aria-expanded="mobileMenuOpen"
        @click="mobileMenuOpen = !mobileMenuOpen"
      >
        <X v-if="mobileMenuOpen" class="h-5 w-5" />
        <Menu v-else class="h-5 w-5" />
      </button>
    </div>

    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 -translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <div
        v-if="mobileMenuOpen"
        class="mx-4 mb-3 border border-slate-200 bg-white p-4 shadow-lg lg:hidden"
      >
        <div class="grid gap-1">
          <button
            v-for="item in navItems"
            :key="item.target"
            class="px-3 py-2.5 text-left text-sm text-slate-700 transition hover:bg-slate-50"
            @click="handleMobileNav(item.target)"
          >
            {{ item.label }}
          </button>
        </div>
        <div class="mt-3 grid gap-2 border-t border-slate-100 pt-3">
          <template v-if="isAuthenticated">
            <AccountMenu />
            <Button
              class="w-full rounded-none bg-blue-600 text-white hover:bg-blue-700"
              @click="handleMobileAction(goDashboard)"
            >
              {{ $t('platform.dashboard') }}
            </Button>
          </template>
          <template v-else>
            <Button
              variant="outline"
              class="w-full rounded-none"
              @click="handleMobileAction(goGuest)"
            >
              {{ $t('platform.continueGuest') }}
            </Button>
            <Button
              variant="outline"
              class="w-full rounded-none"
              @click="handleMobileAction(goLogin)"
            >
              {{ $t('platform.signIn') }}
            </Button>
            <Button
              class="w-full rounded-none bg-blue-600 text-white hover:bg-blue-700"
              @click="handleMobileAction(goSignup)"
            >
              {{ $t('platform.signUp') }}
            </Button>
          </template>
        </div>
      </div>
    </Transition>
  </header>
</template>

<script setup lang="ts">
const genovaLogo = `${import.meta.env.BASE_URL}genova-logo.svg`

import { translate } from '@/i18n'
import { computed } from 'vue'
import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'
import AccountMenu from '@/components/auth/AccountMenu.vue'

import { onActivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Menu, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/toast/use-toast'
import { useAuth } from '@/composables/useAuth'

const route = useRoute()
const router = useRouter()
const { checkAuth, ensureGuestSession } = useAuth()

const isScrolled = ref(false)
const mobileMenuOpen = ref(false)
const isAuthenticated = ref(false)

const navItems = computed(() => [
  { label: translate('platform.overview'), target: 'overview' },
  { label: translate('platform.modules'), target: 'modules' },
  { label: translate('platform.workflows'), target: 'workflows' },
  { label: translate('platform.usageGuide'), target: 'guide' },
])

function refreshAuth() {
  isAuthenticated.value = checkAuth()
}

function onScroll() {
  isScrolled.value = window.scrollY > 16
}

function goHome() {
  router.push('/')
  mobileMenuOpen.value = false
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goDashboard() { router.push('/dashboard') }
function goLogin() { router.push('/login') }
function goSignup() { router.push('/sign_up') }
async function goGuest() {
  const ok = await ensureGuestSession()
  refreshAuth()
  mobileMenuOpen.value = false
  if (!ok) {
    toast({
      variant: 'destructive',
      title: translate('platform.guestUnavailable'),
      description: translate('platform.guestUnavailableHint'),
    })
    return
  }
  router.push('/dashboard')
}

function scrollToSection(target: string) {
  if (target === 'guide') {
    router.push('/help')
    return
  }
  const el = document.getElementById(target)
  if (!el) return
  const top = el.getBoundingClientRect().top + window.scrollY - 64
  window.scrollTo({ top, behavior: 'smooth' })
}

function handleMobileNav(target: string) {
  mobileMenuOpen.value = false
  setTimeout(() => scrollToSection(target), 80)
}

function handleMobileAction(action: () => void) {
  mobileMenuOpen.value = false
  action()
}

onMounted(() => {
  refreshAuth()
  onScroll()
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('storage', refreshAuth)
  window.addEventListener('focus', refreshAuth)
  window.addEventListener('genova:auth-updated', refreshAuth)
  window.addEventListener('genova:auth-cleared', refreshAuth)
})

onActivated(() => {
  refreshAuth()
})

watch(() => route.path, () => {
  refreshAuth()
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('storage', refreshAuth)
  window.removeEventListener('focus', refreshAuth)
  window.removeEventListener('genova:auth-updated', refreshAuth)
  window.removeEventListener('genova:auth-cleared', refreshAuth)
})
</script>
