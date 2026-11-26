import { watch } from 'vue'
import type { LocationQuery, RouteLocationNormalizedLoaded, Router } from 'vue-router'

/** Accepted query parameters of a page, each with a check for its value. */
export type QueryRules = Record<string, (value: string) => boolean>

export const nonEmptyQueryValue = (value: string) => value.trim().length > 0

/** The query without unknown or invalid parameters, or null when nothing has to be removed. */
export function sanitizeQuery(query: LocationQuery, rules: QueryRules): LocationQuery | null {
  const kept: LocationQuery = {}
  let changed = false
  for (const [key, value] of Object.entries(query)) {
    if (Object.prototype.hasOwnProperty.call(rules, key) &&typeof value === 'string' && rules[key](value)) kept[key] = value
    else changed = true
  }
  return changed ? kept : null
}

/** Removes unknown or invalid parameters from the address bar without adding a history entry. */
export function useQueryCleanup(route: RouteLocationNormalizedLoaded, router: Router, rules: QueryRules) {
  const path = route.path
  watch(() => route.query, query => {
    if (route.path !== path) return
    const cleaned = sanitizeQuery(query, rules)
    if (cleaned) void router.replace({ query: cleaned, hash: route.hash })
  }, { immediate: true })
}
