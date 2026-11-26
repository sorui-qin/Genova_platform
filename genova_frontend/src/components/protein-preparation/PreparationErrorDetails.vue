<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { PreparationErrorInfo } from '@/types/proteinContext'

defineProps<{ error?: PreparationErrorInfo; fallback?: string }>()
const { t, te } = useI18n()
</script>

<template>
  <div v-if="error" role="alert" class="space-y-1 text-sm text-red-700">
    <p><strong>{{ t(te(`platform.preparationError_${error.error_code}`) ? `platform.preparationError_${error.error_code}` : `platform.preparationError_${error.error_category}`) }}</strong> <code class="break-all text-xs">{{ error.error_code }}</code></p>
    <p v-if="error.objects.length" class="break-words">{{ error.objects.join(', ') }}</p>
    <p v-if="error.stage">{{ t('platform.preparationFailedStage', { stage: te(`platform.execution_${error.stage}`) ? t(`platform.execution_${error.stage}`) : error.stage }) }}</p>
    <p>{{ t(`platform.preparationAction_${error.recovery_action}`) }}</p>
    <details v-if="error.message" class="text-xs text-slate-600">
      <summary class="cursor-pointer">{{ t('platform.preparationTechnicalDetails') }}</summary>
      <p class="max-h-64 overflow-auto whitespace-pre-wrap break-words">{{ error.message }}</p>
    </details>
  </div>
  <p v-else-if="fallback" role="alert" class="break-words text-sm text-red-700">{{ fallback.split('\n')[0] }}</p>
</template>
