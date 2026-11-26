<template>
  <div class="flex flex-col min-h-screen p-4">
    <div class="flex-1 flex items-center justify-center">
      <main class="flex flex-col gap-4">
        <div class="flex items-center justify-start gap-3">
          <div class="flex items-center">
            <img :src="genovaIcon" :alt="t('brand.logoAlt')" class="w-8 h-8 object-contain" />
          </div>
          <div class="flex flex-col items-start">
            <h1 class="text-2xl font-bold text-gray-900 leading-tight">Genova</h1>
          </div>
        </div>

        <!-- Success State -->
        <Card v-if="emailSent" class="w-full w-[430px]">
          <CardHeader class="text-center">
            <div class="flex justify-center mb-4">
              <div class="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
                <CheckCircle class="w-8 h-8 text-green-600" />
              </div>
            </div>
            <CardTitle class="text-xl">
              {{ t('auth.emailSentTitle') || '邮件发送成功' }}
            </CardTitle>
            <CardDescription class="text-center">
              <span>{{ t('auth.emailSentMessage') || '请访问' }}</span>
              <span class="font-medium text-primary">{{ formData.email }}</span>
              <span>{{ t('auth.emailSentSuffix') || '来重置您的密码' }}</span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              class="w-full" 
              @click="$router.push('/')"
            >
              {{ t('auth.backToHome') || '返回首页' }}
            </Button>
          </CardContent>
        </Card>

        <!-- Form State -->
        <Card v-else class="w-full w-[430px]">
          <CardHeader>
            <div class="flex items-center justify-between">
              <CardTitle class="text-2xl">
                {{ t('auth.forgetPassword') || '忘记密码' }}
              </CardTitle>
              <Button
                variant="link" 
                class="px-0 font-medium text-primary h-auto"
                @click="$router.push('/login')"
              >
                {{ t('auth.backToLogin') || '回到登录页面' }}
              </Button>
            </div>
            <CardDescription>
              {{ t('auth.forgotPasswordDescription') || '输入您的邮箱地址，我们将向您发送重置密码的链接。' }}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form @submit.prevent="onSubmit">
              <!-- General error messages -->
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
                <div class="space-y-2">
                  <Label for="email">
                    {{ t('auth.email') || '邮箱地址' }}
                  </Label>
                  <Input 
                    id="email"
                    v-model="formData.email"
                    type="email" 
                    :placeholder="t('auth.emailPlaceholder')" 
                    :disabled="isSubmitting"
                  />
                  <div v-if="failList.email && failList.email.length > 0" class="text-sm text-red-500 mt-1">
                    <p v-for="item in failList.email" :key="item">{{ item }}</p>
                  </div>
                </div>

                <Button 
                  type="submit" 
                  :disabled="isSubmitting"
                >
                  <Loader2 v-if="isSubmitting" class="w-4 h-4 mr-2 animate-spin" />
                  {{ 
                    isSubmitting 
                      ? (t('auth.sending') || '发送中...') 
                      : (t('auth.sendEmail') || '发送邮件')
                  }}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </main>
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

import { ref, reactive } from 'vue'
import { useI18n } from 'vue-i18n'

// UI Components
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

// Icons
import { Loader2, CheckCircle } from 'lucide-vue-next'

// Toast notifications
import { useToast } from '@/components/ui/toast'

// API
import { forgotPasswordApi } from '@/api/user'
import { displayErrorMessage } from '@/utils/requestError'

// Composables
const { t } = useI18n()
const { toast } = useToast()

// Reactive data
const emailSent = ref(false)
const isSubmitting = ref(false)
const formData = reactive({
  email: ''
})
const failList = reactive({
  email: [] as string[],
  general: [] as string[]
})

// Validation
const validateEmail = (): boolean => {
  failList.email = []
  failList.general = []
  
  if (!formData.email || formData.email.trim() === '') {
    failList.email.push(t('validation.emailRequired') || '邮箱地址不能为空')
    return false
  }
  
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailRegex.test(formData.email)) {
    failList.email.push(t('validation.emailInvalid') || '请输入有效的邮箱地址')
    return false
  }
  
  return true
}

// Error handling function
const handleApiError = (error: any) => {
  failList.email = []
  failList.general = []

  if (!error.response) {
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
      if (data?.detail) {
        // Text, codes and validation lists get localized text; only a per-field map is spread onto the fields.
        if (typeof data.detail !== 'object' || Array.isArray(data.detail) || 'error_code' in data.detail) {
          failList.general.push(displayErrorMessage(error, t('auth.invalidEmail') || 'Invalid email address'))
        } else {
          if (data.detail.email) {
            failList.email = Array.isArray(data.detail.email) ? data.detail.email : [data.detail.email]
          }
          if (data.detail.non_field_errors) {
            failList.general = Array.isArray(data.detail.non_field_errors) ? data.detail.non_field_errors : [data.detail.non_field_errors]
          }
        }
      } else {
        failList.general.push(t('auth.invalidEmail') || 'Invalid email address')
      }
      break
    
    // Request validation rejects malformed or reserved-domain addresses.
    case 422:
      failList.general.push(t('auth.invalidEmail') || 'Invalid email address')
      break

    case 404:
      failList.general.push(t('auth.emailNotFound') || 'Email address not found in our system')
      break
    
    case 429:
      failList.general.push(t('auth.tooManyRequests') || 'Too many requests. Please try again later.')
      break
    
    case 500:
    case 502:
    case 503:
    case 504:
      failList.general.push(data?.detail === 'PASSWORD_RESET_EMAIL_DISABLED'
        ? (t('auth.passwordResetEmailDisabled') || '邮件服务未开通，请联系管理员获取密码重置链接')
        : (t('auth.serverError') || 'Server error. Please try again later.'))
      break
    
    default:
      failList.general.push(t('auth.unknownError') || 'An unknown error occurred. Please try again.')
  }

  if (failList.general.length > 0) {
    toast({
      variant: "destructive",
      title: t('common.error') || 'Error',
      description: failList.general[0]
    })
  }
}

// Form submission
const onSubmit = async () => {
  if (isSubmitting.value) return
  
  if (!validateEmail()) {
    toast({
      variant: "destructive",
      title: t('validation.validationError') || '验证错误',
      description: failList.email[0] || t('validation.emailInvalid') || '请输入有效的邮箱地址'
    })
    return
  }
  
  try {
    isSubmitting.value = true
    
    failList.email = []
    failList.general = []
    const params = {
      email: formData.email
    }

    await forgotPasswordApi(params)
    
    emailSent.value = true
    
    toast({
      title: t('common.success') || 'Success',
      description: t('auth.emailSentSuccess') || 'Password reset email sent successfully!'
    })

  } catch (error: any) {
    console.error('Forgot password error:', error)
    handleApiError(error)
  } finally {
    isSubmitting.value = false
  }
}
</script>

<style scoped>
/* Any additional custom styles if needed */
</style>

<route lang="yaml">
  meta:
    layout: blank
</route>
