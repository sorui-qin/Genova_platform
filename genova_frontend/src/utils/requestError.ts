import axios from 'axios'
import { unref } from 'vue'
import i18n, { translate } from '@/i18n'

export type RequestErrorKind = 'canceled' | 'network' | 'timeout' | 'invalid' | 'auth' | 'notFound' | 'conflict' | 'tooLarge' | 'rateLimited' | 'server' | 'unknown'

// Namespaces that already hold localized text for backend error codes.
const CODE_NAMESPACES = ['platform.structureErrors', 'data', 'settings', 'agent.errors']

/** Classifies a failed request by transport state and HTTP status; null when the error did not come from a request. */
export function requestErrorKind(error: any): RequestErrorKind | null {
  if (axios.isCancel(error)) return 'canceled'
  if (!error?.isAxiosError) return null
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return 'timeout'
  const status = error.response?.status
  if (!status) return 'network'
  if (status === 404 || status === 410) return 'notFound'
  if (status === 401 || status === 403) return 'auth'
  if (status === 409) return 'conflict'
  if (status === 413) return 'tooLarge'
  if (status === 429) return 'rateLimited'
  if (status === 400 || status === 422) return 'invalid'
  if (status >= 500) return 'server'
  return 'unknown'
}

export function isNotFoundError(error: any) {
  return requestErrorKind(error) === 'notFound'
}

function backendCode(error: any): string {
  const detail = error?.response?.data?.detail
  const code = typeof detail === 'string' ? detail : detail?.error_code || detail?.code
  return typeof code === 'string' && /^[A-Z][A-Z0-9_]+$/.test(code) ? code : ''
}

// Server sentences that carry no error code, mapped to keys under platform.serverMessages. Sentences whose status
// text is already right (not found, sign-in, rate limit, unavailable) and internal field checks are not listed.
const SERVER_MESSAGES: [RegExp, string][] = [
  [/^Email or username already exists$/, 'accountExists'],
  [/^Invalid email or password$/, 'invalidCredentials'],
  [/^User is disabled$/, 'userDisabled'],
  [/^Admin access required$/, 'adminRequired'],
  [/^Reset link is invalid, used or expired$/, 'resetLinkInvalid'],
  [/^Passwords do not match$/, 'passwordsMismatch'],
  [/^Password must be 8-72 bytes$/, 'passwordLength'],
  [/^Current account is not a guest account$/, 'notGuestAccount'],
  [/^Built-in datasets cannot be renamed$/, 'builtinRename'],
  [/^Built-in datasets cannot be deleted$/, 'builtinDelete'],
  [/^Invalid dataset name$/, 'invalidName'],
  [/^File extension cannot change$/, 'extensionFixed'],
  [/^files is required$/, 'filesRequired'],
  [/num_\w+ must be an integer between 1 and 1000$/, 'countRange'],
  [/now requires target_num_\w+; resubmit the target count$/, 'targetCountRequired'],
  [/requires a prepared Protein Context$|^protein_context_id is required$/, 'contextRequired'],
  [/requires a protein \.pdb file$|^Dataset does not contain a PDB file$/, 'structureRequired'],
  [/requires a (prepared )?reference ligand/, 'referenceRequired'],
  [/^Dataset file missing: /, 'fileMissing'],
  [/^Invalid residue reference$/, 'residueInvalid'],
  [/^Postprocessing protein is unavailable$/, 'resultStructureUnavailable'],
  [/^Artifact path is outside job workspace$/, 'fileNotAccessible'],
  [/^lower must be less than upper$/, 'lowerBelowUpper'],
  [/^\w+\.(lower|upper|target) outside natural bounds$/, 'objectiveOutOfBounds'],
  // The server puts its code before the sentence, in one text; matched by the code.
  [/^SHARED_RECEPTOR_REQUIRED:/, 'contextNotValidated'],
]

/** The server's own reason (`detail` text or `detail.message`), '' when there is none. */
function serverReason(error: any): string {
  const detail = error?.response?.data?.detail
  const text = typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : ''
  return text.trim()
}

export function serverMessageKey(error: any): string {
  const reason = serverReason(error)
  const hit = reason && SERVER_MESSAGES.find(([pattern]) => pattern.test(reason))
  return hit ? `platform.serverMessages.${hit[1]}` : ''
}

function requestIdOf(error: any): string {
  const headers = error?.response?.headers || {}
  return String(headers['x-request-id'] || headers['x-trace-id'] || error?.response?.data?.request_id || '')
}

const CJK = /[　-ヿ㐀-䶿一-鿿가-힯豈-﫿＀-￯]/

/** Only use raw system errors when their language matches the UI. Do not apply this to conversation text. */
function displayableAppMessage(message: string) {
  const zh = String(unref(i18n.global.locale) || '').toLowerCase().startsWith('zh')
  if (zh) return CJK.test(message)
  const han = message.match(/\p{Script=Han}/gu)?.length || 0
  const latin = message.match(/[A-Za-z]/g)?.length || 0
  // An English explanation can contain a Chinese filename or other user-supplied value.
  return han === 0 || latin > han
}

/** Messages persisted by the backend (not Axios errors); keep the original in diagnostic details. */
export function systemErrorMessage(value: any, fallback = ''): string {
  const code = value?.error_code || value?.warning_code || value?.code
  const key = code && CODE_NAMESPACES.map(ns => `${ns}.${code}`).find(key => i18n.global.te(key))
  if (key) return translate(key)
  const message = value?.error_message || value?.message
  if (typeof message === 'string' && message && displayableAppMessage(message)) return message
  return fallback || translate('platform.requestErrors.unknown')
}

/**
 * User-facing text for a failed operation. Request errors are mapped by backend code or HTTP status to
 * localized text; raw server and network messages are never shown. Plain `Error`s raised by the app itself
 * already carry localized text and are kept when readable in the UI language; other exceptions
 * use `fallback`. Canceled requests yield ''.
 */
export function requestErrorMessage(error: any, fallback = ''): string {
  const generic = fallback || translate('platform.requestErrors.unknown')
  const kind = requestErrorKind(error)
  if (kind === 'canceled') return ''
  if (!kind) return error?.constructor === Error && error.message && displayableAppMessage(error.message) ? error.message : generic
  const code = backendCode(error)
  const known = code && CODE_NAMESPACES.map(ns => `${ns}.${code}`).find(key => i18n.global.te(key))
  if (known) return translate(known)
  const sentence = serverMessageKey(error)
  if (sentence) return translate(sentence)
  // A conflict the server explains with a reason not listed above is not necessarily a concurrent edit, so the
  // "data was modified" text would state a wrong cause.
  const message = kind === 'unknown' || (kind === 'conflict' && serverReason(error)) ? generic : translate(`platform.requestErrors.${kind}`)
  const id = ['server', 'unknown'].includes(kind) ? requestIdOf(error) : ''
  return id ? translate('platform.requestErrors.withRequestId', { message, id }) : message
}

/**
 * Like `requestErrorMessage`, but keeps the server's own explanation when it can be shown as is: a `detail` text (or
 * `detail.message`) that is not a bare error code and is readable in the current language. Known error codes, field-validation lists and everything else get the localized text.
 */
export function displayErrorMessage(error: any, fallback = ''): string {
  const code = backendCode(error)
  if (!code || !CODE_NAMESPACES.some(ns => i18n.global.te(`${ns}.${code}`))) {
    const text = serverReason(error)
    if (text && !/^[A-Z][A-Z0-9_]+$/.test(text) && displayableAppMessage(text)) return text
  }
  return requestErrorMessage(error, fallback)
}
