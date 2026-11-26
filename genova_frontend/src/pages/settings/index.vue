<template>
  <app_frame>
    <div class="bg-gray-50/30">
      <div class="max-w-5xl mx-auto px-6 py-6">
        <div class="mb-3">
          <h1 class="text-xl font-semibold text-gray-900">{{ t('settings.settings') }}</h1>
        </div>

        <Card class="shadow-none p-4 mb-4">
          <!-- Profile Section -->
          <div class="mb-4">
            <h2 class="text-xl font-semibold text-gray-900 mb-6">{{ t('settings.my_profile') }}</h2>
            
            <!-- Profile Layout: Avatar on left, Info on right -->
            <div class="flex items-center space-x-6 gap-4">
              <!-- Avatar -->
              <div class="w-24 h-24 bg-gradient-to-br from-violet-500 via-purple-500 to-indigo-600 text-white rounded-full flex items-center justify-center text-2xl font-semibold shadow-lg">
                {{ getAvatarText(state.username || state.team_name.value) }}
              </div>
              
              <!-- Profile Info -->
              <div class="flex-1 space-y-6">
                <!-- Username Section -->
                <div>
                  <Label class="text-sm font-medium text-gray-700 mb-2 block">{{ t('settings.username') }}</Label>
                  <div class="text-sm text-gray-900 bg-gray-50 px-3 py-2 rounded-md border">{{ state.username }}</div>
                </div>

                <!-- Team Name (if exists) -->
                <div v-if="state.team_name.value">
                  <Label class="text-sm font-medium text-gray-700 mb-2 block flex items-center">
                    <Users class="w-4 h-4 mr-2 text-gray-400" />
                    {{ t('manage.团队名称') }}
                    <Lock class="w-3 h-3 ml-2 text-gray-400" />
                  </Label>
                  <div class="text-sm font-medium text-gray-900 bg-gray-50 px-3 py-2 rounded-md border">
                    {{ state.team_name.value }}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Account Security Section -->
          <div class="mb-8">
            <h2 class="text-xl font-semibold text-gray-900 mb-6">{{ t('settings.account_security') }}</h2>
            
            <div class="space-y-6">
              <!-- Email (Read-only) -->
              <div>
                <Label class="text-sm font-medium text-gray-700 mb-2 block">{{ t('settings.Email') }}</Label>
                <div class="text-sm text-gray-900 bg-gray-50 px-3 py-2 rounded-md border">
                  {{ state.email.value }}
                </div>
              </div>

              <!-- Password -->
              <div v-if="!isGuest">
                <Label class="text-sm font-medium text-gray-700 mb-2 block">{{ t('settings.Password') }}</Label>
                <div class="flex items-center space-x-3">
                  <div class="flex-1 text-sm text-gray-900 bg-gray-50 px-3 py-2 rounded-md border">
                    ••••••••••
                  </div>
                  <Button variant="outline" size="sm" @click="password_click">
                    {{ t('settings.change_password') }}
                  </Button>
                </div>
              </div>

            </div>
          </div>

        </Card>
        <AgentApiSettings />
        <AgentProxySettings />
        <AgentWorkPreferences />
      </div>
    </div>

    <!-- Password Change Dialog -->
    <Dialog v-if="!isGuest" :open="dialogOptions1.visible" @update:open="setPasswordDialogOpen">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{{ dialogOptions1.title }}</DialogTitle>
          <DialogDescription class="sr-only">{{ t('platform.dialogA11y.password') }}</DialogDescription>
        </DialogHeader>
        <form class="space-y-4" @submit.prevent="handlePasswordChange">
        <fieldset class="space-y-4" :disabled="passwordSaving">
          <div>
            <Label for="current-password">{{ t('settings.current_password') }}</Label>
            <Input 
              id="current-password" 
              type="password" 
              v-model="passwordForm.currentPassword"
              autocomplete="current-password"
              required
              maxlength="128"
              class="mt-1"
            />
          </div>
          <div>
            <Label for="new-password">{{ t('settings.new_password') }}</Label>
            <Input 
              id="new-password" 
              type="password" 
              v-model="passwordForm.newPassword"
              autocomplete="new-password"
              required
              minlength="8"
              maxlength="72"
              class="mt-1"
            />
          </div>
          <div>
            <Label for="confirm-password">{{ t('settings.confirm_password') }}</Label>
            <Input 
              id="confirm-password" 
              type="password" 
              v-model="passwordForm.confirmPassword"
              autocomplete="new-password"
              required
              maxlength="72"
              class="mt-1"
            />
          </div>
        </fieldset>
        <p v-if="passwordError" role="alert" class="text-sm text-red-700">{{ t(`settings.${passwordError}`) }}</p>
        <DialogFooter>
          <Button type="button" variant="outline" :disabled="passwordSaving" @click="setPasswordDialogOpen(false)">
            {{ t('result.取消') }}
          </Button>
          <Button type="submit" :disabled="passwordSaving">
            {{ passwordSaving ? t('settings.password_saving') : t('result.保存') }}
          </Button>
        </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>

  </app_frame>
</template>

<script setup lang="ts">
import { translate } from '@/i18n'
import AgentApiSettings from './components/AgentApiSettings.vue'
import AgentProxySettings from './components/AgentProxySettings.vue'
import AgentWorkPreferences from './components/AgentWorkPreferences.vue'

import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { 
  Users,
  Lock
} from 'lucide-vue-next'

import app_frame from '@/components/Layout/appFrame.vue'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

import { getCurrentUserApi, changePasswordApi } from '@/api/user.ts'
import { isCancel } from 'axios'
import { isGuestUser } from '@/utils/guestSession'
import { toast } from '@/components/ui/toast/use-toast'

const { t } = useI18n()

interface UserField {
  value: string
  is_edit: boolean
}

interface UserState {
  team_name: UserField
  email: UserField
  name: UserField
  password: UserField
  username: string
}

const state = reactive<UserState>({
  team_name: {
    value: '',
    is_edit: false
  },
  email: {
    value: '',
    is_edit: false
  },
  name: {
    value: '',
    is_edit: false
  },
  password: {
    value: t('settings.setup'),
    is_edit: false
  },
  username: ''
})

const isGuest = ref(isGuestUser())
const refreshGuestStatus = () => {
  isGuest.value = isGuestUser()
  if (isGuest.value) dialogOptions1.value.visible = false
}
const authEvents = ['storage', 'genova:auth-updated', 'genova:auth-cleared']
onMounted(() => authEvents.forEach(event => window.addEventListener(event, refreshGuestStatus)))
onBeforeUnmount(() => authEvents.forEach(event => window.removeEventListener(event, refreshGuestStatus)))


const dialogOptions1 = ref({
  visible: false,
  title: '',
})

const passwordForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const passwordSaving = ref(false)
const passwordError = ref('')

const setPasswordDialogOpen = (open: boolean) => {
  if (passwordSaving.value || isGuestUser()) return
  dialogOptions1.value.visible = open
  passwordError.value = ''
  passwordForm.value = { currentPassword: '', newPassword: '', confirmPassword: '' }
}

const password_click = () => {
  setPasswordDialogOpen(true)
  dialogOptions1.value.title = t('settings.change_login_pwd')
}

const handlePasswordChange = async () => {
  if (passwordSaving.value || isGuestUser()) return
  passwordError.value = ''
  const { currentPassword, newPassword, confirmPassword } = passwordForm.value
  if (!currentPassword || newPassword.length < 8) {
    passwordError.value = 'PASSWORD_INVALID_INPUT'
    return
  }
  if (new TextEncoder().encode(newPassword).length > 72) {
    passwordError.value = 'PASSWORD_TOO_LONG'
    return
  }
  if (newPassword !== confirmPassword) {
    passwordError.value = 'password_mismatch'
    return
  }
  passwordSaving.value = true
  try {
    const { data } = await changePasswordApi({ current_password: currentPassword, new_password: newPassword })
    localStorage.setItem('cs_bearer_token', data.access_token)
    localStorage.setItem('cs_refresh_token', data.refresh_token)
    window.dispatchEvent(new Event('genova:auth-updated'))
    passwordSaving.value = false
    setPasswordDialogOpen(false)
    toast({ title: t('common.success'), description: t('settings.password_change_success') })
  } catch (error: any) {
    // Signed out or switched account meanwhile: the reply's tokens belong to an identity this tab no longer uses.
    if (isCancel(error)) {
      dialogOptions1.value.visible = false
      return
    }
    const code = error.response?.data?.detail
    passwordError.value = ['PASSWORD_CURRENT_INCORRECT', 'PASSWORD_UNCHANGED', 'PASSWORD_TOO_LONG',
      'PASSWORD_GUEST_ACCOUNT', 'PASSWORD_INVALID_INPUT'].includes(code) ? code : 'password_change_failed'
  } finally {
    passwordSaving.value = false
  }
}

const get_role = () => {
  getCurrentUserApi()
    .then((res: any) => {
      if (res.data) {
        isGuest.value = isGuestUser()
        state.email.value = res.data.email || ''
        state.name.value = res.data.username || ''
        state.team_name.value = ''
        
        // Set username from name
        state.username = res.data.username || ''
        
      }
    })
    .catch((error: any) => {
      console.error('Failed to fetch user role data:', error)
      toast({
        title: t('common.error'),
        description: translate('platform.failedToLoadUserInformation'),
        variant: 'destructive'
      })
    })
}

const getAvatarText = (text: string) => {
  if (!text) return ''
  
  // Check if text contains Chinese characters
  const chineseRegex = /[\u4e00-\u9fff]/
  if (chineseRegex.test(text)) {
    // Return first Chinese character
    const chineseMatch = text.match(chineseRegex)
    return chineseMatch ? chineseMatch[0] : text.charAt(0).toUpperCase()
  }
  
  // For English text, return first letter
  return text.charAt(0).toUpperCase()
}

onMounted(() => {
  get_role()
})
</script>

<style scoped>
/* Custom toggle switch styles are handled by Tailwind classes in the template */
</style>

<route lang="yaml">
  meta:
    layout: blank
</route>
