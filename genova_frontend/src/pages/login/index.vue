<template>
  <div class="flex flex-col min-h-screen p-4">
    <div class="flex-1 flex items-center justify-center">
      <div class="flex flex-col gap-4">
        <div class="flex items-center justify-start gap-3">
          <div class="flex items-center">
            <img :src="genovaIcon" :alt="t('brand.logoAlt') || 'Genova Logo'" class="w-8 h-8 object-contain" />
          </div>
          <div class="flex flex-col items-start">
            <h1 class="text-2xl font-bold text-gray-900 leading-tight">Genova</h1>
          </div>
        </div>
        <Card class="w-full max-w-sm w-[330px]">
          <CardHeader>
            <CardTitle class="text-2xl">
              {{ t('auth.signin') || '登录' }}
            </CardTitle>
            <CardDescription>
              <span>{{ t('auth.drugflowAccountLogin') || '还没有账号？' }}</span>
              <Button
                v-if="env === 'saas'"
                variant="link" 
                class="px-0 font-medium text-primary"
                @click="$router.push('/sign_up')"
              >
                {{ t('auth.registerNow') || '立即注册' }}
              </Button>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p v-if="pendingEmail" class="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              {{ t('platform.claimedPendingSignInDescription') }}
            </p>
            <div v-if="failList.general && failList.general.length > 0" class="mb-4">
              <div class="bg-red-50 border border-red-200 rounded-md p-3">
                <div class="text-sm text-red-800">
                  <p v-for="error in failList.general" :key="error" class="mb-1 last:mb-0">
                    {{ error }}
                  </p>
                </div>
              </div>
            </div>
            
            <form class="grid gap-4" @submit.prevent="onSubmit">
              <!-- Email Field -->
              <div class="space-y-2">
                <Label for="email">
                  <span>{{ t('auth.email') || '邮箱' }}</span>
                </Label>
                <Input 
                  id="email"
                  v-model="formData.email"
                  type="text" 
                  autocomplete="username"
                  :placeholder="t('auth.emailPlaceholder') || '请输入邮箱'" 
                  :disabled="isSubmitting"
                />
                <div v-if="failList.email && failList.email.length > 0" class="text-sm text-red-500 mt-1">
                  <p v-for="item in failList.email" :key="item">{{ item }}</p>
                </div>
              </div>

              <!-- Password Field -->
              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <Label for="password">{{ t('auth.password') || '密码' }}</Label>
                  <Button
                    v-if="env === 'saas'"
                    type="button"
                    variant="link" 
                    class="px-0 font-medium text-primary h-auto"
                    @click="$router.push('/forget_password')" 
                  >
                    {{ t('auth.forgetPassword') || '忘记密码？' }}
                  </Button>
                </div>
                <Input 
                  id="password"
                  v-model="formData.password"
                  type="password" 
                  autocomplete="current-password"
                  :placeholder="t('auth.passwordPlaceholder')" 
                  :disabled="isSubmitting"
                />
                <div v-if="failList.password && failList.password.length > 0" class="text-sm text-red-500 mt-1">
                  <p v-for="item in failList.password" :key="item">{{ item }}</p>
                </div>
              </div>

              <label class="flex items-center gap-2 text-sm text-slate-600">
                <input v-model="rememberAccount" type="checkbox" :disabled="isSubmitting" class="h-4 w-4 accent-blue-600" />
                {{ t('platform.rememberAccount') }}
              </label>

              <div v-if="guestRecoveryAvailable" class="space-y-2 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                <p>{{ locale.startsWith('zh') ? '登录已有账号不会转移访客草稿和文件。可先复制恢复链接，也可以直接继续登录。' : 'Signing into an existing account does not transfer guest drafts or files. Copy a recovery link first, or continue signing in.' }}</p>
                <Button type="button" size="sm" variant="outline" :disabled="isSubmitting" @click="copyGuestRecovery">{{ locale.startsWith('zh') ? '复制恢复链接' : 'Copy recovery link' }}</Button>
                <p v-if="recoveryCopied" role="status">{{ locale.startsWith('zh') ? '恢复链接已复制。' : 'Recovery link copied.' }}</p>
              </div>
              <Button type="submit" class="w-full" :disabled="isSubmitting">
                <Loader2 v-if="isSubmitting" class="w-4 h-4 mr-2 animate-spin" />
                {{ 
                  isSubmitting 
                    ? (retryCount > 0 
                        ? (t('auth.retryingAttempt', { count: retryCount }) || `Retrying (${retryCount}/${maxRetries})...`)
                        : (t('auth.submitting') || 'Submitting...'))
                    : (t('auth.submit') || '提交')
                }}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const genovaIcon = `${import.meta.env.BASE_URL}genova-icon.svg`

import { ref, reactive, inject, onMounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2 } from 'lucide-vue-next'
import { useToast } from '@/components/ui/toast'

// API
import { CanceledError, isCancel } from 'axios'
import { signinApi, getCurrentUserApi, authIdentity } from '@/api/user'
import { clearStoredAuthState, storeAuthTokens, persistUserInfo, readStoredUserInfo, safeAuthRedirect, getStoredGuestCode } from '@/utils/guestSession'
import { displayErrorMessage } from '@/utils/requestError'

// Composables
const { t, locale } = useI18n()
const router = useRouter()
const { toast } = useToast()
const websocket = inject('websocket') as any
const rememberedEmail = localStorage.getItem('genova:remembered-email') || ''
// A claimed account that still has to sign in should not need its email retyped.
const storedUser = readStoredUserInfo()
const guestRecoveryAvailable = computed(() => storedUser?.is_guest === true && Boolean(getStoredGuestCode()))
const recoveryCopied = ref(false)
async function copyGuestRecovery() {
  const user = readStoredUserInfo()
  const code = getStoredGuestCode()
  if (!code || user?.id !== storedUser?.id || !user?.is_guest) return
  const target = router.resolve(safeAuthRedirect(router.currentRoute.value.query.redirect))
  const link = new URL(target.href, window.location.origin)
  link.searchParams.set('gc', code)
  try {
    await navigator.clipboard.writeText(link.toString())
    recoveryCopied.value = true
  } catch {
    // Clipboard access can be disabled on a local HTTP deployment.
    window.prompt(locale.value.startsWith('zh') ? '复制恢复链接' : 'Copy recovery link', link.toString())
  }
}

const pendingEmail = storedUser?.claim_pending_signin ? storedUser.email || '' : ''
const rememberAccount = ref(!!rememberedEmail)
watch(rememberAccount, remember => { if (!remember) localStorage.removeItem('genova:remembered-email') })

// Form data
const formData = reactive({
  email: pendingEmail || rememberedEmail,
  password: ''
})

// Reactive data
const isSubmitting = ref(false)
const env = ref('saas')
const retryCount = ref(0)
const maxRetries = 3
const failList = reactive({
  email: [] as string[],
  password: [] as string[],
  general: [] as string[]
})

// Validation functions
const validateEmail = (): boolean => {
  failList.email = []
  
  if (!formData.email || formData.email.trim() === '') {
    failList.email.push(t('validation.emailRequired') || '邮箱不能为空')
    return false
  }
  
  const value = formData.email.trim()

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailRegex.test(value)) {
    failList.email.push(t('validation.emailInvalid') || '请输入有效的邮箱地址')
    return false
  }
  
  return true
}

const validatePassword = (): boolean => {
  failList.password = []
  
  if (!formData.password || formData.password.trim() === '') {
    failList.password.push(t('validation.passwordRequired') || '密码不能为空')
    return false
  }
  
  if (formData.password.length < 8) {
    failList.password.push(t('validation.passwordMinLength') || '密码至少需要8个字符')
    return false
  }
  
  return true
}

const validateForm = (): boolean => {
  const isEmailValid = validateEmail()
  const isPasswordValid = validatePassword()
  return isEmailValid && isPasswordValid
}

// Error handling functions
const handleApiError = (error: any) => {
  // Clear previous errors
  failList.email = []
  failList.password = []
  failList.general = []

  if (!error.response) {
    // Network error
    const networkError = t('auth.networkError') || 'Network error. Please check your connection.'
    failList.general.push(networkError)
    toast({
      variant: "destructive",
      title: t('common.error') || 'Error',
      description: networkError
    })
    return
  }

  const status = error.response.status
  const data = error.response.data

  switch (status) {
    case 400:
      // Validation errors
      if (data?.detail) {
        // Text, codes and validation lists get localized text; only a per-field map is spread onto the fields.
        if (typeof data.detail !== 'object' || Array.isArray(data.detail) || 'error_code' in data.detail) {
          failList.general.push(displayErrorMessage(error, t('auth.invalidCredentials') || 'Invalid credentials'))
        } else {
          if (data.detail.email) {
            failList.email = Array.isArray(data.detail.email) ? data.detail.email : [data.detail.email]
          }
          if (data.detail.password) {
            failList.password = Array.isArray(data.detail.password) ? data.detail.password : [data.detail.password]
          }
          if (data.detail.non_field_errors) {
            failList.general = Array.isArray(data.detail.non_field_errors) ? data.detail.non_field_errors : [data.detail.non_field_errors]
          }
        }
      } else {
        failList.general.push(t('auth.invalidCredentials') || 'Invalid credentials')
      }
      break
    
    case 401:
      failList.general.push(t('auth.unauthorizedError') || 'Invalid email or password')
      break
    
    case 403:
      failList.general.push(t('auth.accountDisabled') || 'Account is disabled. Please contact support.')
      break
    
    case 429:
      failList.general.push(t('auth.tooManyAttempts') || 'Too many login attempts. Please try again later.')
      break
    
    case 500:
    case 502:
    case 503:
    case 504:
      failList.general.push(t('auth.serverError') || 'Server error. Please try again later.')
      break
    
    default:
      failList.general.push(t('auth.unknownError') || 'An unknown error occurred. Please try again.')
  }

  // Show toast for general errors
  if (failList.general.length > 0) {
    toast({
      variant: "destructive",
      title: t('common.error') || 'Error',
      description: failList.general[0]
    })
  }
}

const performSignin = async (formDataToSubmit: { email: string, password: string }, identity: string) => {
  try {
    const response = await signinApi(formDataToSubmit, identity)
    
    // Only replace the current session after a successful sign-in.
    clearStoredAuthState(true)
    storeAuthTokens(response.data.access_token || '', response.data.refresh_token || '')
    const signedInIdentity = authIdentity()
    if (rememberAccount.value) localStorage.setItem('genova:remembered-email', formDataToSubmit.email)
    else localStorage.removeItem('genova:remembered-email')
    // Reconnect websocket if available
    try {
      if (websocket?.reconnect) {
        websocket.reconnect()
      }
    } catch {
      console.warn('Failed to reconnect websocket')
    }

    // Get user role and permissions
    try {
      const userResponse = await getCurrentUserApi()
      if (authIdentity() !== signedInIdentity) throw new CanceledError('Authentication changed during sign-in')
      persistUserInfo(userResponse.data)
    } catch (error) {
      if (isCancel(error)) throw error
      if (authIdentity() !== signedInIdentity) throw new CanceledError('Authentication changed during sign-in')
      console.warn('Failed to get user role:', error)
    }

    // Success notification
    toast({
      title: t('common.success') || 'Success',
      description: t('auth.signinSuccess') || 'Sign in successful!'
    })

    // Reset retry count on success
    retryCount.value = 0

    // Redirect
    router.push(safeAuthRedirect(router.currentRoute.value.query.redirect))

    return response
  } catch (error) {
    throw error
  }
}

// Form submission with retry mechanism
const onSubmit = async () => {
  if (isSubmitting.value) return
  
  // Validate form
  if (!validateForm()) {
    return
  }
  
  try {
    isSubmitting.value = true
    
    // Clear previous errors
    failList.email = []
    failList.password = []
    failList.general = []

    const formDataToSubmit: { email: string, password: string } = {
      email: formData.email.trim().toLowerCase(),
      password: formData.password
    }
    
    // Attempt signin with retry mechanism
    // A sign-in or sign-out elsewhere after this submit takes precedence over its late response.
    const identity = authIdentity()
    let lastError: any = null
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        await performSignin(formDataToSubmit, identity)
        return
      } catch (error: any) {
        if (isCancel(error)) return
        console.error('Signin error:', error)
        lastError = error
        
        // Don't retry for client errors (4xx) except for network issues
        if (error.response?.status && error.response.status >= 400 && error.response.status < 500) {
          if (error.response.status !== 408 && error.response.status !== 429) {
            break
          }
        }
        
        // If this is not the last attempt and it's a retryable error
        if (attempt < maxRetries) {
          retryCount.value = attempt + 1
          const delay = Math.min(1000 * Math.pow(2, attempt), 5000)
          
          toast({
            title: t('auth.retrying') || 'Retrying...',
            description: t('auth.retryMessage', { attempt: attempt + 1, max: maxRetries + 1 }) || `Attempt ${attempt + 1} of ${maxRetries + 1} failed. Retrying in ${delay/1000}s...`
          })
          
          await new Promise(resolve => setTimeout(resolve, delay))
        }
      }
    }
    
    // If we get here, all retries failed
    if (lastError) {
      handleApiError(lastError)
    }
    
  } catch (error: any) {
    console.error('Unexpected signin error:', error)
    handleApiError(error)
  } finally {
    isSubmitting.value = false
  }
}

// Initialize
onMounted(async () => {
  // Clear any existing target cookie
  document.cookie = 'target=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})
</script>

<style scoped>
/* Any additional custom styles if needed */
</style>

<route lang="yaml">
  meta:
    layout: blank
</route>
