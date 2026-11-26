import request from '@/utils/request'

export type HelpLanguage = 'en-US' | 'zh-CN'
export interface HelpText {
  title: string
  summary: string
  details: string
  guidance: string
  range: string
  action?: string
  sections?: Array<{ title: string; items: string[]; ordered: boolean }>
}
export interface HelpEntry {
  id: string
  group: string
  model: string
  keys: string[]
  aliases: string[]
  unit: string
  source: string
  references: string[]
  guide_section?: 'basics' | 'modules'
  route?: string
  related?: string[]
  default?: unknown
  translations: Record<HelpLanguage, HelpText>
}
export interface HelpReference {
  title: string
  citation: string
  url: string
}
export interface HelpCatalog {
  version: string
  updated_at: string
  metric_count: number
  entries: HelpEntry[]
  references: Record<string, HelpReference>
}

export const getHelpCatalog = () => request.get<HelpCatalog>('/api/v1/help')
