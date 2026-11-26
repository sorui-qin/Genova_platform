<template>
  <div class="flex flex-col min-h-screen p-4">
    <div class="flex-1 flex items-center justify-center py-8">
      <main class="flex flex-col gap-3">
        <!-- Success state - email sent confirmation -->
        <div v-if="isEmailSent" class="flex items-center justify-start gap-3 mb-4">
          <div class="flex items-center">
            <img :src="genovaIcon" :alt="t('brand.logoAlt') || 'Logo'" class="w-16 h-16 object-contain" />
          </div>
          <div class="flex flex-col items-start">
            <h1 class="text-2xl font-bold text-gray-900 leading-tight">Genova</h1>
            <p class="text-sm text-gray-600 leading-tight">{{ t('brand.subtitle') }}</p>
          </div>
        </div>

        <Card v-if="isEmailSent" class="w-full max-w-md">
          <CardHeader class="text-center pb-4">
            <div class="mx-auto mb-3 w-12 h-12 bg-green-100 rounded-full flex items-center justify-center">
              <CheckCircle class="w-6 h-6 text-green-600" />
            </div>
            <CardTitle class="text-xl">
              {{ t('auth.registrationSuccess') }}
            </CardTitle>
            <CardDescription class="text-sm">
              <div class="space-y-1">
                <p>{{ t('auth.thankYouForRegistering') || 'Thank you for registering!' }}</p>
                <p>
                  {{ t('auth.pleaseCheck') || 'Please check' }}
                  <span class="font-medium text-primary">{{ formData.email }}</span>
                  {{ t('auth.toActivateAccount') || 'to activate your account' }}
                </p>
              </div>
            </CardDescription>
          </CardHeader>
          <CardContent class="pt-0">
            <Button 
              class="w-full" 
              @click="$router.push('/')"
            >
              {{ t('auth.backToHome') || 'Back to Home' }}
            </Button>
          </CardContent>
        </Card>

        <!-- Registration form -->
        <template v-else>
          <div class="flex items-center justify-start gap-3">
            <div class="flex items-center">
              <img :src="genovaIcon" :alt="t('brand.logoAlt') || 'Logo'" class="w-8 h-8 object-contain" />
            </div>
            <div class="flex flex-col items-start">
              <h1 class="text-2xl font-bold text-gray-900 leading-tight">Genova</h1>
            </div>
          </div>
          
          <Card class="w-full max-w-4xl">
            <CardHeader class="pb-4">
              <div class="flex items-center justify-between">
                <CardTitle class="text-xl">
                  {{ t('auth.signup') || 'Sign Up' }}
                </CardTitle>
                <Button
                  variant="link" 
                  class="px-0 font-medium text-primary text-sm h-auto"
                  @click="$router.push('/login')"
                >
                  {{ t('auth.goToLogin') || 'Go to Login' }}
                </Button>
              </div>
              <CardDescription class="text-sm">
                {{ t('auth.createDrugflowAccount') || 'Create your Genova account' }}
              </CardDescription>
            </CardHeader>
            <CardContent class="pt-0">
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
                
                <div class="space-y-4">
                  <!-- Basic Info Fields - Single Column -->
                  <div class="space-y-3">
                    <!-- Name Field -->
                    <div class="space-y-2">
                      <Label for="name">
                        {{ t('auth.name') || 'Name' }} <span class="text-red-500">*</span>
                      </Label>
                      <Input 
                        id="name"
                        v-model="formData.name"
                        type="text" 
                        :placeholder="t('auth.namePlaceholder') || 'Please enter your name'" 
                        maxlength="30"
                        :disabled="isSubmitting"
                      />
                      <div v-if="failList.name && failList.name.length > 0" class="text-sm text-red-500 mt-1">
                        <p v-for="item in failList.name" :key="item">{{ item }}</p>
                      </div>
                    </div>

                    <!-- Email Field -->
                    <div class="space-y-2">
                      <Label for="email">
                        {{ t('auth.email') || 'Email' }} <span class="text-red-500">*</span>
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

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <!-- Password Field -->
                      <div class="space-y-2">
                        <Label for="password">
                          {{ t('auth.password') || 'Password' }} <span class="text-red-500">*</span>
                        </Label>
                        <Input 
                          id="password"
                          v-model="formData.password"
                          type="password" 
                          :placeholder="t('auth.passwordHint') || 'Password (at least 8 characters, including numbers and letters)'" 
                          maxlength="20"
                          :disabled="isSubmitting"
                        />
                        <div v-if="failList.password1 && failList.password1.length > 0" class="text-sm text-red-500 mt-1">
                          <p v-for="item in failList.password1" :key="item">{{ item }}</p>
                        </div>
                      </div>

                      <!-- Confirm Password Field -->
                      <div class="space-y-2">
                        <Label for="confirmPassword">
                          {{ t('auth.confirmPassword') || 'Confirm Password' }} <span class="text-red-500">*</span>
                        </Label>
                        <Input 
                          id="confirmPassword"
                          v-model="formData.confirmPassword"
                          type="password" 
                          :placeholder="t('auth.confirmPasswordHint') || 'Confirm password (at least 8 characters, including numbers and letters)'" 
                          maxlength="20"
                          :disabled="isSubmitting"
                        />
                        <div v-if="failList.password2 && failList.password2.length > 0" class="text-sm text-red-500 mt-1">
                          <p v-for="item in failList.password2" :key="item">{{ item }}</p>
                        </div>
                      </div>
                    </div>
                  </div>

                </div>

                <!-- Submit Buttons -->
                <div class="flex pt-4">
                  <Button type="submit" class="flex-1" :disabled="isSubmitting">
                    <Loader2 v-if="isSubmitting" class="w-4 h-4 mr-2 animate-spin" />
                    {{ t('auth.signup') || 'Sign Up' }}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </template>
      </main>
    </div>
    
    <!-- Footer fixed at bottom -->
    <div class="text-center pb-2">
      <div class="flex items-center justify-center space-x-3 text-xs text-gray-500">
        <a href="#" class="hover:text-gray-700">{{ t('legal.privacyPolicy') || 'Privacy Policy' }}</a>
        <span>•</span>
        <a href="#" class="hover:text-gray-700">{{ t('legal.legalStatement') || 'Legal Statement' }}</a>
        <span>•</span>
        <a href="#" class="hover:text-gray-700">{{ t('legal.businessLicense') || 'Business License' }}</a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const genovaIcon = `${import.meta.env.BASE_URL}genova-icon.svg`

import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
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
import { signupApi, type RegisterParams } from '@/api/user'
import { displayErrorMessage } from '@/utils/requestError'

// Validation utils
const isEmail = (s: string): boolean => /\w[-\w.+]*@([A-Za-z0-9][-A-Za-z0-9]+\.)+[A-Za-z]{2,14}/.test(s)

// Composables
const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const { toast } = useToast()

// Reactive data
const isEmailSent = ref(false)
const isSubmitting = ref(false)

// Form data
const formData = reactive({
  name: '',
  email: '',
  password: '',
  confirmPassword: ''
})

// Error handling
const failList = reactive({
  general: [] as string[],
  name: [] as string[],
  email: [] as string[],
  password1: [] as string[],
  password2: [] as string[]
})

// Initialize email from route
onMounted(() => {
  if (route.query.email && typeof route.query.email === 'string') {
    formData.email = route.query.email
  } else if (route.query.input_email && typeof route.query.input_email === 'string') {
    formData.email = route.query.input_email
  }
})

// Handle API errors
const handleApiError = (error: any) => {
  Object.keys(failList).forEach(key => {
    ;(failList as any)[key] = []
  })

  if (!error.response) {
    const networkError = t('auth.networkError') || '网络错误，请检查您的连接'
    failList.general.push(networkError)
    toast({
      variant: "destructive",
      title: t('common.error') || '错误',
      description: networkError,
      duration: 5000
    })
    return
  }

  const { data } = error.response

  // Only a per-field map is spread onto the fields; text, codes and validation lists get localized text.
  if (data?.detail && typeof data.detail === 'object' && !Array.isArray(data.detail) && !('error_code' in data.detail)) {
    Object.keys(data.detail).forEach(field => {
      const fieldMessages = Array.isArray(data.detail[field]) ? data.detail[field] : [data.detail[field]]
      const fieldMapping: Record<string, string> = {
        'password1': 'password1',
        'password2': 'password2',
        'username': 'name'
      }
      const targetField = fieldMapping[field] || field
      if ((failList as any)[targetField]) {
        ;(failList as any)[targetField] = fieldMessages
      } else {
        failList.general.push(...fieldMessages)
      }
    })
  } else {
    const message = displayErrorMessage(error, t('auth.unknownError') || '发生未知错误，请重试')
    failList.general.push(message)
    toast({
      variant: "destructive",
      title: t('common.error') || '错误',
      description: message,
      duration: 5000
    })
  }
}

// Form submission
const onSubmit = async () => {
  if (isSubmitting.value) return
  
  try {
    isSubmitting.value = true
    
    Object.keys(failList).forEach(key => {
      ;(failList as any)[key] = []
    })

    if (!validateFormData()) {
      return
    }

    const params: RegisterParams = {
      email: formData.email.trim().toLowerCase(),
      username: formData.name.trim(),
      password: formData.password,
    }
    await signupApi(params)

    toast({
      title: t('common.success') || '成功',
      description: t('auth.registrationSuccessLogin') || '注册成功，请登录。',
      duration: 5000
    })
    router.push('/login')

  } catch (error: any) {
    console.error('Signup failed:', error)
    handleApiError(error)
  } finally {
    isSubmitting.value = false
  }
}

// Client-side form validation
const validateFormData = (): boolean => {
  const requiredFields = ['name', 'email', 'password', 'confirmPassword']
  
  for (const field of requiredFields) {
    if (!formData[field as keyof typeof formData] || formData[field as keyof typeof formData].toString().trim() === '') {
      const fieldName = t(`auth.${field}`) || field
      toast({
        variant: "destructive",
        title: t('validation.validationError') || '验证错误',
        description: `${fieldName} ${t('validation.required') || '是必填项'}`,
        duration: 3000
      })
      return false
    }
  }

  if (!isEmail(formData.email)) {
    failList.email.push(t('validation.emailInvalid') || '请输入有效的邮箱地址')
    toast({
      variant: "destructive",
      title: t('validation.validationError') || '验证错误',
      description: t('validation.emailInvalid') || '请输入有效的邮箱地址',
      duration: 3000
    })
    return false
  }

  if (formData.password.length < 8) {
    failList.password1.push(t('validation.passwordMinLength') || '密码至少需要8个字符')
    toast({
      variant: "destructive",
      title: t('validation.validationError') || '验证错误',
      description: t('validation.passwordMinLength') || '密码至少需要8个字符',
      duration: 3000
    })
    return false
  }

  // bcrypt only uses the first 72 bytes; the server rejects longer passwords.
  if (new TextEncoder().encode(formData.password).length > 72) {
    failList.password1.push(t('settings.PASSWORD_TOO_LONG'))
    toast({
      variant: "destructive",
      title: t('validation.validationError') || '验证错误',
      description: t('settings.PASSWORD_TOO_LONG'),
      duration: 3000
    })
    return false
  }

  if (!/[0-9]+.*[a-zA-Z]+/.test(formData.password) && !/[a-zA-Z]+.*[0-9]+/.test(formData.password)) {
    failList.password1.push(t('validation.passwordFormat') || '密码必须包含至少一个数字和一个字母')
    toast({
      variant: "destructive",
      title: t('validation.validationError') || '验证错误',
      description: t('validation.passwordFormat') || '密码必须包含至少一个数字和一个字母',
      duration: 3000
    })
    return false
  }

  if (formData.password !== formData.confirmPassword) {
    failList.password2.push(t('validation.passwordMismatch') || '两次输入的密码不一致')
    toast({
      variant: "destructive",
      title: t('validation.validationError') || '验证错误',
      description: t('validation.passwordMismatch') || '两次输入的密码不一致',
      duration: 3000
    })
    return false
  }

  return true
}
</script>

<style scoped>
/* Any additional custom styles if needed */
</style>

<route lang="yaml">
  meta:
    layout: blank
</route>
