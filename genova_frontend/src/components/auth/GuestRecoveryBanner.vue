<template>
  <div v-if="hasRecoveryContext">
    <Dialog v-model:open="dialogOpen">
      <DialogContent class="max-w-lg">
        <DialogHeader>
          <DialogTitle>{{ $t(currentUser?.claim_pending_signin ? 'platform.claimedPendingSignIn' : 'platform.saveOrClaimThisGuestSession') }}</DialogTitle>
          <DialogDescription>
            {{ $t(currentUser?.claim_pending_signin ? 'platform.claimedPendingSignInDescription' : 'platform.guestRecoveryWarning') }}
          </DialogDescription>
        </DialogHeader>

        <div class="space-y-4">
          <div v-if="!currentUser?.claim_pending_signin" class="space-y-2">
            <Label class="text-xs font-semibold text-slate-700">{{ $t('platform.recoveryLink') }}</Label>
            <div class="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs break-all text-slate-700">
              {{ recoveryLink }}
            </div>
            <Button size="sm" variant="outline" @click="copyRecoveryLink">{{ $t('platform.copyRecoveryLink') }}</Button>
          </div>

          <div class="border-t border-slate-200 pt-4 space-y-3">
            <div v-if="!currentUser?.claim_pending_signin" class="text-sm font-semibold text-slate-900">{{ $t('platform.claimAccount') }}</div>
            <p v-else role="alert" class="text-sm text-amber-700">{{ $t('platform.claimedAccountSignInFailed', { email: currentUser.email }) }}</p>
            <Button v-if="currentUser?.claim_pending_signin" size="sm" variant="outline" @click="goToLogin">{{ $t('platform.goToSignInPage') }}</Button>

            <div v-if="claimError" class="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {{ claimError }}
            </div>

            <div v-if="!currentUser?.claim_pending_signin" class="space-y-1.5">
              <Label for="guest-claim-email" class="text-xs text-slate-600">{{ $t('platform.email') }}</Label>
              <Input id="guest-claim-email" v-model="claimForm.email" type="email" autocomplete="email" />
            </div>

            <div v-if="!currentUser?.claim_pending_signin" class="space-y-1.5">
              <Label for="guest-claim-username" class="text-xs text-slate-600">{{ $t('platform.username') }}</Label>
              <Input id="guest-claim-username" v-model="claimForm.username" autocomplete="username" />
            </div>

            <div class="space-y-1.5">
              <Label for="guest-claim-password" class="text-xs text-slate-600">{{ $t('platform.password') }}</Label>
              <Input id="guest-claim-password" v-model="claimForm.password" type="password" :autocomplete="currentUser?.claim_pending_signin ? 'current-password' : 'new-password'" />
            </div>

            <div v-if="!currentUser?.claim_pending_signin" class="space-y-1.5">
              <Label for="guest-claim-password-confirm" class="text-xs text-slate-600">{{ $t('platform.confirmPassword') }}</Label>
              <Input id="guest-claim-password-confirm" v-model="claimForm.confirmPassword" type="password" autocomplete="new-password" />
            </div>

            <div class="flex items-center justify-end gap-2 pt-1">
              <Button size="sm" variant="outline" @click="dialogOpen = false">{{ $t('platform.later') }}</Button>
              <Button size="sm" :disabled="isClaiming" @click="submitClaim">
                {{ isClaiming ? $t(currentUser?.claim_pending_signin ? 'platform.loading' : 'platform.claiming') : currentUser?.claim_pending_signin ? $t('platform.retryClaimedAccountSignIn') : $t('platform.claimAccount') }}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { translate } from '@/i18n'

import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from '@/components/ui/toast/use-toast'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { claimGuestSessionApi } from '@/api/user'
import { copyText } from '@/utils/clipboard'
import {
  getStoredGuestCode,
  readStoredUserInfo,
  safeAuthRedirect,
} from '@/utils/guestSession'
import { displayErrorMessage } from '@/utils/requestError'

const props = defineProps<{
  jobId: string
}>()

const route = useRoute()
const router = useRouter()

const dialogOpen = ref(false)
const isClaiming = ref(false)
const claimError = ref('')
const currentUser = ref(readStoredUserInfo())
const pendingRefreshTimers: number[] = []
const claimForm = reactive({
  email: '',
  username: '',
  password: '',
  confirmPassword: '',
})

const guestCode = computed(() => {
  // Read the active session, not a stale account link from browser history.
  return currentUser.value?.is_guest === true ? getStoredGuestCode() : ''
})

const hasRecoveryContext = computed(() => !!props.jobId && (currentUser.value?.claim_pending_signin === true || (currentUser.value?.is_guest === true && !!guestCode.value)))

const recoveryLink = computed(() => {
  if (!hasRecoveryContext.value || !guestCode.value) return ''
  const resolved = router.resolve({
    path: route.path,
    query: {
      ...route.query,
      job_id: props.jobId,
      gc: guestCode.value,
    },
  })
  return `${window.location.origin}${resolved.href}`
})

function refreshCurrentUser() {
  currentUser.value = readStoredUserInfo()
}

function scheduleCurrentUserRefresh() {
  for (const delay of [0, 200, 800]) {
    const timer = window.setTimeout(() => {
      refreshCurrentUser()
    }, delay)
    pendingRefreshTimers.push(timer)
  }
}

function maybeOpenDialog() {
  if (!hasRecoveryContext.value) return
  if (dialogOpen.value) return
  dialogOpen.value = true
}

function goToLogin() {
  return router.push({ path: '/login', query: { redirect: safeAuthRedirect(route.fullPath) } })
}

async function copyRecoveryLink() {
  if (!recoveryLink.value) return
  try {
    await copyText(recoveryLink.value)
    toast({
      title: translate('platform.recoveryLinkCopied'),
      description: translate('platform.saveThisLinkCarefullyToRecoverTheGuestSessionLater'),
    })
  } catch {
    toast({
      variant: 'destructive',
      title: translate('platform.copyFailed'),
      description: translate('platform.unableToCopyTheRecoveryLink'),
      duration: 4000,
    })
  }
}

async function submitClaim() {
  if (isClaiming.value) return
  claimError.value = ''
  const pendingUser = readStoredUserInfo()?.claim_pending_signin ? readStoredUserInfo() : null
  if (!claimForm.password || (!pendingUser && (!claimForm.email.trim() || !claimForm.username.trim()))) {
    claimError.value = translate(pendingUser ? 'validation.passwordRequired' : 'platform.emailUsernameAndPasswordAreRequired')
    return
  }
  if (!pendingUser && claimForm.password !== claimForm.confirmPassword) {
    claimError.value = translate('platform.passwordsDoNotMatch')
    return
  }
  if (!pendingUser && claimForm.password.length < 8) {
    claimError.value = translate('validation.passwordMinLength')
    return
  }
  if (!pendingUser && new TextEncoder().encode(claimForm.password).length > 72) {
    claimError.value = translate('settings.PASSWORD_TOO_LONG')
    return
  }

  isClaiming.value = true
  try {
    const response = await claimGuestSessionApi({
      email: pendingUser?.email || claimForm.email.trim(),
      username: pendingUser?.username || claimForm.username.trim(),
      password: claimForm.password,
    })
    if (readStoredUserInfo()?.id !== response.data.id || readStoredUserInfo()?.claim_pending_signin) return
    refreshCurrentUser()
    dialogOpen.value = false
    const nextQuery = { ...route.query }
    delete nextQuery.gc
    nextQuery.job_id = props.jobId
    toast({
      title: translate('platform.accountClaimed'),
      description: translate('platform.yourGuestSessionIsNowAttachedToARegularAccount'),
    })
    await router.replace({
      path: route.path,
      query: nextQuery,
    })
  } catch (error: any) {
    refreshCurrentUser()
    if (!currentUser.value?.claim_pending_signin) {
      claimError.value = displayErrorMessage(error, translate('platform.failedToClaimAccount'))
    } else if (pendingUser) {
      // The amber notice explains the pending state; a failed retry needs its own reason.
      const status = error?.response?.status
      claimError.value = translate(status === 401 ? 'auth.unauthorizedError' : status ? 'auth.serverError' : 'auth.networkError')
    }
  } finally {
    isClaiming.value = false
  }
}

watch(
  () => hasRecoveryContext.value,
  (value) => {
    if (value) {
      const currentUser = readStoredUserInfo()
      claimForm.username = claimForm.username || String(currentUser?.username || '')
      maybeOpenDialog()
    }
  },
  { immediate: true },
)

watch(
  () => route.fullPath,
  () => {
    refreshCurrentUser()
    if (guestCode.value) {
      scheduleCurrentUserRefresh()
    }
  },
)

onMounted(() => {
  refreshCurrentUser()
  if (hasRecoveryContext.value) {
    const currentUser = readStoredUserInfo()
    claimForm.username = claimForm.username || String(currentUser?.username || '')
    maybeOpenDialog()
  }
  if (guestCode.value) {
    scheduleCurrentUserRefresh()
  }
})

onBeforeUnmount(() => {
  for (const timer of pendingRefreshTimers) {
    window.clearTimeout(timer)
  }
})
</script>
