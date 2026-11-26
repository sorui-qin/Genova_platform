<template>
  <div class="flex flex-col min-h-screen p-4">
    <div class="flex-1 flex items-center justify-center">
      <div class="flex flex-col gap-4">
        <div class="flex items-center justify-start gap-3">
          <div class="flex items-center">
            <img :src="genovaIcon" :alt="t('brand.logoAlt')" class="w-8 h-8 object-contain" />
          </div>
          <div class="flex flex-col items-start">
            <h1 class="text-2xl font-bold text-gray-900 leading-tight">Genova</h1>
          </div>
        </div>
        
        <!-- Authenticated state - password reset form -->
        <Card v-if="ifAuthed" class="w-full max-w-sm w-[400px]">
          <CardHeader>
            <CardTitle class="text-2xl">
              {{ pswdTitle }}
            </CardTitle>
            <CardDescription>
              {{ queryType === 'reset_password' ? (t('auth.resetPasswordDesc') || '请输入您的新密码') : (t('auth.setPasswordDesc') || '请设置您的账户密码') }}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div v-if="failList.general && failList.general.length > 0" class="mb-4">
              <div class="bg-red-50 border border-red-200 rounded-md p-3">
                <div class="text-sm text-red-800">
                  <p v-for="error in failList.general" :key="error" class="mb-1 last:mb-0">
                    {{ error }}
                  </p>
                </div>
              </div>
            </div>
            
            <div class="grid gap-4">
              <!-- Password Field -->
              <div class="space-y-2">
                <Label for="password">
                  {{ t('auth.password') || '密码' }}
                </Label>
                <Input 
                  id="password"
                  v-model="formData.password"
                  type="password" 
                  :placeholder="t('auth.passwordHint') || '至少8个字符，包含数字和字母'"
                  :disabled="isSubmitting"
                  maxlength="20"
                  autocomplete="new-password"
                />
                <div v-if="failList.password && failList.password.length > 0" class="text-sm text-red-500 mt-1">
                  <p v-for="item in failList.password" :key="item">{{ item }}</p>
                </div>
              </div>

              <!-- Confirm Password Field -->
              <div class="space-y-2">
                <Label for="confirmPassword">
                  {{ t('auth.confirmPassword') || '确认密码' }}
                </Label>
                <Input 
                  id="confirmPassword"
                  v-model="formData.confirmPassword"
                  type="password" 
                  :placeholder="t('auth.confirmPasswordHint') || '再次输入密码'"
                  :disabled="isSubmitting"
                  maxlength="20"
                  autocomplete="new-password"
                />
                <div v-if="failList.confirmPassword && failList.confirmPassword.length > 0" class="text-sm text-red-500 mt-1">
                  <p v-for="item in failList.confirmPassword" :key="item">{{ item }}</p>
                </div>
              </div>

              <div class="flex gap-2 mt-2">
                <Button 
                  type="submit" 
                  class="flex-1" 
                  :disabled="isSubmitting" 
                  @click="onSubmit"
                >
                  <Loader2 v-if="isSubmitting" class="w-4 h-4 mr-2 animate-spin" />
                  {{ isSubmitting ? (t('auth.submitting') || '提交中...') : (t('task.确认') || '确认') }}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- Unauthenticated state - validation message -->
        <Card v-else class="w-full max-w-sm w-[400px]">
          <CardContent class="pt-6">
            <div class="flex flex-col items-center justify-center gap-4 py-8">
              <Loader2 v-if="isValidating" class="w-12 h-12 animate-spin text-primary" />
              <div v-else class="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
              <p class="text-lg font-medium text-center">
                {{ t(showText) }}
              </p>
              <Button 
                v-if="!isValidating" 
                variant="outline"
                @click="$router.push('/login')"
              >
                {{ t('auth.backToLogin') || '返回登录' }}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
    
    <!-- Footer fixed at bottom -->
    <div class="text-center pb-4">
      <div class="flex items-center justify-center space-x-4 text-xs text-gray-500">
        <a href="#" class="hover:text-gray-700">{{ t('legal.privacyPolicy') || '隐私政策' }}</a>
        <span>•</span>
        <a href="#" class="hover:text-gray-700">{{ t('legal.legalStatement') || '法律声明' }}</a>
        <span>•</span>
        <a href="#" class="hover:text-gray-700">{{ t('legal.businessLicense') || '营业执照' }}</a>
        <span>•</span>
        <a href="http://beian.miit.gov.cn/" class="hover:text-gray-700" target="_blank">
          浙ICP备2021033527号
        </a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const genovaIcon = `${import.meta.env.BASE_URL}genova-icon.svg`

import { computed } from 'vue'
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2 } from 'lucide-vue-next'
import { useToast } from '@/components/ui/toast'

// API
import { resetPasswordValidateApi, resetPasswordUpdateApi } from '@/api/user'
import { displayErrorMessage } from '@/utils/requestError'

// Composables
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { toast } = useToast()

// Form data
const formData = reactive({
  password: '',
  confirmPassword: ''
})

// Reactive data
const isSubmitting = ref(false)
const isValidating = ref(true)
const ifAuthed = ref(false)
const showText = ref('message.验证中')
const queryType = route.query.type as string
const pswdTitle = computed(() => t(queryType === 'reset_password' ? 'auth.重置密码' : 'auth.设置密码'))
const succInfo = computed(() => t(queryType === 'reset_password' ? 'auth.密码修改成功' : 'auth.密码设置成功'))

const failList = reactive({
  password: [] as string[],
  confirmPassword: [] as string[],
  general: [] as string[]
})

// Validation functions
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
  
  // Check if password contains both numbers and letters
  if (!/[0-9]+.*[a-zA-Z]+/.test(formData.password) && !/[a-zA-Z]+.*[0-9]+/.test(formData.password)) {
    failList.password.push(t('validation.passwordFormat') || '密码必须包含至少一个数字和一个字母')
    return false
  }
  
  return true
}

const validateConfirmPassword = (): boolean => {
  failList.confirmPassword = []
  
  if (!formData.confirmPassword || formData.confirmPassword.trim() === '') {
    failList.confirmPassword.push(t('validation.confirmPasswordRequired') || '请再次输入密码')
    return false
  }
  
  if (formData.password !== formData.confirmPassword) {
    failList.confirmPassword.push(t('validation.passwordMismatch') || '两次输入的密码不一致')
    return false
  }
  
  return true
}

const validateForm = (): boolean => {
  const isPasswordValid = validatePassword()
  const isConfirmPasswordValid = validateConfirmPassword()
  return isPasswordValid && isConfirmPasswordValid
}

// Error handling
const handleApiError = (error: any, context: string) => {
  console.error(`${context} error:`, error)
  
  // Clear previous errors
  failList.password = []
  failList.confirmPassword = []
  failList.general = []

  if (!error.response) {
    // Network error
    const networkError = t('auth.networkError') || '网络错误，请检查您的连接'
    failList.general.push(networkError)
    toast({
      variant: "destructive",
      title: t('common.error') || '错误',
      description: networkError
    })
    return
  }

  const status = error.response.status
  const data = error.response.data

  // Text, codes and validation lists get localized text; only a per-field map is spread onto the fields.
  if (data?.detail && (typeof data.detail !== 'object' || Array.isArray(data.detail) || 'error_code' in data.detail)) {
    const message = displayErrorMessage(error, t('auth.invalidRequest') || '请求参数错误')
    failList.general.push(message)
    toast({
      variant: "destructive",
      title: t('common.error') || '错误',
      description: message
    })
  } else if (data?.detail) {
      // Handle field-specific errors
      if (data.detail.new_password1) {
        failList.password = Array.isArray(data.detail.new_password1) 
          ? data.detail.new_password1 
          : [data.detail.new_password1]
      }
      if (data.detail.new_password2) {
        failList.confirmPassword = Array.isArray(data.detail.new_password2) 
          ? data.detail.new_password2 
          : [data.detail.new_password2]
      }
      if (data.detail.non_field_errors) {
        failList.general = Array.isArray(data.detail.non_field_errors) 
          ? data.detail.non_field_errors 
          : [data.detail.non_field_errors]
      }
      
      // Show toast for general errors
      if (failList.general.length > 0) {
        toast({
          variant: "destructive",
          title: t('common.error') || '错误',
          description: failList.general[0]
        })
      }
  } else {
    // Default error message based on status
    let errorMessage = ''
    switch (status) {
      case 400:
        errorMessage = t('auth.invalidRequest') || '请求参数错误'
        break
      case 401:
        errorMessage = t('auth.unauthorizedError') || '未授权，请重新登录'
        break
      case 403:
        errorMessage = t('auth.tokenExpired') || '链接已过期，请重新申请'
        break
      case 404:
        errorMessage = t('auth.notFound') || '请求的资源不存在'
        break
      case 429:
        errorMessage = t('auth.tooManyAttempts') || '请求过于频繁，请稍后再试'
        break
      case 500:
      case 502:
      case 503:
      case 504:
        errorMessage = t('auth.serverError') || '服务器错误，请稍后再试'
        break
      default:
        errorMessage = t('auth.unknownError') || '发生未知错误，请稍后再试'
    }
    
    failList.general.push(errorMessage)
    toast({
      variant: "destructive",
      title: t('common.error') || '错误',
      description: errorMessage
    })
  }
}

// Validate token on mount
const validateToken = async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  
  if (!token) {
    showText.value = 'auth.missingToken'
    isValidating.value = false
    toast({
      variant: "destructive",
      title: t('common.error') || '错误',
      description: t(showText.value)
    })
    return
  }

  try {
    await resetPasswordValidateApi(token)
    ifAuthed.value = true
    isValidating.value = false
    toast({
      title: t('common.success') || '成功',
      description: t('message.验证成功') || '验证成功'
    })
  } catch (error: any) {
    isValidating.value = false
    showText.value = 'message.验证失败'
    handleApiError(error, 'Token validation')
  }
}

// Form submission
const onSubmit = async () => {
  if (isSubmitting.value) return
  
  // Validate form
  if (!validateForm()) {
    return
  }
  
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token) {
    toast({
      variant: "destructive",
      title: t('common.error') || '错误',
      description: t('auth.missingToken') || '缺少验证令牌'
    })
    return
  }

  try {
    isSubmitting.value = true
    
    // Clear previous errors
    failList.password = []
    failList.confirmPassword = []
    failList.general = []

    const params = {
      token,
      password: formData.password,
      confirm_password: formData.confirmPassword
    }

    // Submit password reset
    await resetPasswordUpdateApi(params)
    
    // Success notification
    toast({
      title: t('common.success') || '成功',
      description: succInfo.value
    })

    // Redirect to login after 2 seconds
    setTimeout(() => {
      router.push('/login')
    }, 1000)
    
  } catch (error: any) {
    handleApiError(error, 'Password reset')
  } finally {
    isSubmitting.value = false
  }
}

// Initialize
onMounted(() => {
  validateToken()
})
</script>

<style scoped>
/* Any additional custom styles if needed */
</style>

<route lang="yaml">
  meta:
    layout: blank
</route>
