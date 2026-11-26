import type { Composer, I18n } from 'vue-i18n'

declare const i18n: I18n<{}, {}, {}, string, false>
export default i18n
export const translate: Composer['t']
export function setLanguage(language: string): void
export function statusLabel(status?: string | null): string
