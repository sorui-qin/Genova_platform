<script setup lang="ts">
import { useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLanguage } from '@/i18n'

const { locale, t } = useI18n({ useScope: 'global' })
const groupName = useId()
</script>

<template>
  <div
    role="radiogroup"
    :aria-label="t('common.language')"
    class="relative grid h-8 w-20 shrink-0 grid-cols-2 rounded-full border border-border bg-secondary p-0.5 text-[11px] font-semibold "
  >
    <span
      aria-hidden="true"
      class="pointer-events-none absolute inset-y-0.5 left-0.5 w-[calc(50%-0.125rem)] rounded-full bg-primary transition-transform duration-200 ease-out motion-reduce:transition-none"
      :class="locale === 'en-US' ? 'translate-x-full' : 'translate-x-0'"
    />
    <label class="relative cursor-pointer" lang="zh-CN">
      <input
        type="radio"
        :name="groupName"
        value="zh-CN"
        :checked="locale === 'zh-CN'"
        class="peer sr-only"
        @change="setLanguage('zh-CN')"
      >
      <span class="flex h-full items-center justify-center rounded-full text-muted-foreground transition-colors peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-ring">中</span>
    </label>
    <label class="relative cursor-pointer" lang="en-US">
      <input
        type="radio"
        :name="groupName"
        value="en-US"
        :checked="locale === 'en-US'"
        class="peer sr-only"
        @change="setLanguage('en-US')"
      >
      <span class="flex h-full items-center justify-center rounded-full text-muted-foreground transition-colors peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-ring">EN</span>
    </label>
  </div>
</template>
