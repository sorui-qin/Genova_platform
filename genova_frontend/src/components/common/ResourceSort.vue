<template>
  <select v-model="model" :aria-label="L('排序方式', 'Sort order')" class="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700">
    <option value="time">{{ defaultOrder ? L('默认顺序', 'Default order') : L('按时间', 'By time') }}</option>
    <option value="name">{{ L('按名称', 'By name') }}</option>
  </select>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
defineProps<{ defaultOrder?: boolean }>()
const model = defineModel<'time' | 'name'>({ required: true })
const { locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
</script>
