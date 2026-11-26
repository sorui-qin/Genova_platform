import { translate } from '@/i18n'

// Same limit as the existing task-name field of the post-processing panel.
export const NAME_MAX_LENGTH = 200

export const nameTooLong = (value: string) => value.trim().length > NAME_MAX_LENGTH

/** Remaining-characters hint shown under name inputs; values restored from older data may already exceed the limit. */
export function nameLengthHint(value: string) {
  const left = NAME_MAX_LENGTH - value.length
  return left >= 0 ? translate('platform.nameLength.left', { count: left }) : translate('platform.nameLength.tooLong', { max: NAME_MAX_LENGTH })
}
