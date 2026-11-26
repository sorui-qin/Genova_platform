import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import { useWorkspaceState } from './useWorkspace'
import { sameValue, type AssistantModule, type ModuleSuggestion } from '@/api/moduleAssistant'
import { randomUUID } from '@/utils/uuid'
import { translate } from '@/i18n'

export function useModuleSuggestion(module: AssistantModule) {
  const { pending } = useWorkspaceState('module-suggestion', () => module, {
    pending: null as { token: string; jobId: string; suggestion: ModuleSuggestion } | null,
  })
  async function openDraft(router: Router, jobId: string, suggestion: ModuleSuggestion) {
    // crypto.randomUUID is missing on plain-HTTP deployments; the shared helper falls back to getRandomValues.
    const token = randomUUID()
    pending.value = { token, jobId, suggestion }
    const path = { tarpass: '/postprocessing', molecule_generation: '/molgen', property_optimization: '/molopt' }[module]
    await router.push({ path, query: { restore_job_id: jobId, assistant_suggestion: token } })
  }
  function consume(route: RouteLocationNormalizedLoaded, form: Record<string, any>, apply: (changes: Record<string, any>) => void) {
    const saved = pending.value
    if (!saved || saved.token !== route.query.assistant_suggestion || saved.jobId !== route.query.restore_job_id) return
    if (saved.suggestion.changes.some(change => !sameValue(form[change.field], change.before))) {
      throw new Error(translate('platform.editorMessages.suggestionChanged'))
    }
    apply(Object.fromEntries(saved.suggestion.changes.map(change => [change.field, change.after])))
    pending.value = null
  }
  return { openDraft, consume }
}
