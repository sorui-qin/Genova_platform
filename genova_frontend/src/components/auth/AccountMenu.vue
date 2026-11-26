<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <button type="button" class="flex min-w-0 items-center gap-2 text-sm text-slate-600" :aria-label="$t('platform.accountMenu')">
        <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">{{ name.charAt(0).toUpperCase() }}</span>
        <span class="max-w-[140px] truncate max-sm:hidden">{{ name }}</span>
        <ChevronDown class="h-3 w-3 shrink-0" />
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" class="w-60">
      <DropdownMenuLabel class="break-words">
        <div>{{ name }}</div>
        <div class="text-xs font-normal text-slate-500">{{ user?.email }}</div>
      </DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem @select="router.push('/settings')"><UserRound />{{ $t('platform.userSettings') }}</DropdownMenuItem>
      <DropdownMenuItem :disabled="busy" @select="leaveAccount()"><ArrowLeftRight />{{ $t('platform.switchAccount') }}</DropdownMenuItem>
      <DropdownMenuItem :disabled="busy" @select="leaveAccount()"><LogOut />{{ $t('platform.logout') }}</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeftRight, ChevronDown, LogOut, UserRound } from 'lucide-vue-next'
import { translate } from '@/i18n'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { readStoredUserInfo } from '@/utils/guestSession'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const { logout } = useAuth()
const user = ref(readStoredUserInfo())
const busy = ref(false)
const name = computed(() => user.value?.username || user.value?.email || translate('platform.user'))
const refreshUser = () => { user.value = readStoredUserInfo() }
const events = ['storage', 'focus', 'genova:auth-updated', 'genova:auth-cleared']
onMounted(() => events.forEach(event => window.addEventListener(event, refreshUser)))
onBeforeUnmount(() => events.forEach(event => window.removeEventListener(event, refreshUser)))

async function leaveAccount() {
  if (busy.value) return
  busy.value = true
  try { if (await logout()) await router.push('/login') }
  finally { busy.value = false }
}
</script>
