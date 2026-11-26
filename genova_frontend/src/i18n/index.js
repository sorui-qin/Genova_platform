import { watch } from 'vue'
import { createI18n } from 'vue-i18n'
import enUS from './locales/en-US.js'
import zhCN from './locales/zh-CN.js'
import platformEN from './locales/platform.en-US.js'
import platformZH from './locales/platform.zh-CN.js'

function mergeModules(modules) {
  return Object.values(modules).reduce((acc, mod) => {
    const messages = mod?.default ?? mod
    return Object.assign(acc, messages || {})
  }, {})
}

const enUSModules = import.meta.glob(
  [
    '@/pages/**/i18n.en-US.js',
    '@/components/**/i18n.en-US.js',
  ],
  { eager: true },
)

const zhCNModules = import.meta.glob(
  [
    '@/pages/**/i18n.zh-CN.js',
    '@/components/**/i18n.zh-CN.js',
  ],
  { eager: true },
)

const messages = {
  'en-US': {
    ...enUS,
    ...mergeModules(enUSModules),
    ...platformEN,
  },
  'zh-CN': {
    ...zhCN,
    ...mergeModules(zhCNModules),
    ...platformZH,
  },
}

const getDefaultLanguage = () => {
  const savedLang = localStorage.getItem('language')
  if (savedLang && ['en-US', 'zh-CN'].includes(savedLang)) {
    return savedLang
  }

  return 'en-US'
}

const i18n = createI18n({
  legacy: false,
  locale: getDefaultLanguage(),
  fallbackLocale: 'en-US',
  messages,
})

watch(i18n.global.locale, (language) => {
  document.documentElement.lang = language
}, { immediate: true })

export const translate = i18n.global.t

export function setLanguage(language) {
  if (!['zh-CN', 'en-US'].includes(language)) return
  localStorage.setItem('language', language)
  i18n.global.locale.value = language
}

export default i18n

const statusKeys = {
  pending: 'pending', queued: 'queued', running: 'running', blocked: 'blocked',
  succeeded: 'succeeded', partial_succeeded: 'partialSucceeded', failed: 'failed',
  canceled: 'canceled', skipped: 'skipped', ready: 'ready', draft: 'draft',
  preparing: 'preparing', finished: 'finished', aborted: 'aborted',
  prefiltered: 'prefiltered', invalid: 'invalid', partial: 'partialSucceeded',
}

export function statusLabel(status) {
  return statusKeys[status] ? translate(`platform.${statusKeys[status]}`) : status || '—'
}
