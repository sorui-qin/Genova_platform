<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, Check, Link2 } from 'lucide-vue-next'
import type { HelpEntry, HelpLanguage, HelpReference } from '@/api/help'

const props = withDefaults(defineProps<{
  entry: HelpEntry
  language: HelpLanguage
  references: Record<string, HelpReference>
  copied: string
  heading?: 'h2' | 'h3'
}>(), { heading: 'h3' })
defineEmits<{ copy: [id: string] }>()
const text = computed(() => props.entry.translations[props.language])
const zh = computed(() => props.language === 'zh-CN')
const description = computed(() => {
  const content = [text.value.summary, text.value.details, text.value.guidance].filter(Boolean).join(' ')
  if (props.entry.group !== 'parameters' || !('default' in props.entry)) return content
  const value = props.entry.default
  const defaults = Array.isArray(value)
    ? value.map(objective => `${objective.metric.toUpperCase()} ${objective.mode === 'range' ? `${objective.lower}–${objective.upper}` : `≥ ${objective.lower}`} (${zh.value ? '权重' : 'weight'} ${objective.weight})`).join('; ')
    : value === null ? (zh.value ? '根据目标数量估算' : 'estimated from the target count') : String(value)
  return `${zh.value ? `默认 ${defaults}。` : `Default: ${defaults}.`} ${content}`
})
</script>

<template>
  <article :id="entry.id" tabindex="-1" class="help-entry scroll-mt-4 rounded-xl border border-slate-200 bg-white p-4 outline-none focus:border-blue-400 sm:p-5">
    <div class="flex items-start justify-between gap-3">
      <component :is="heading" class="font-semibold text-slate-900" :class="heading === 'h2' ? 'text-xl' : 'text-base'">{{ text.title }}</component>
      <button type="button" :aria-label="copied === entry.id ? (zh ? '链接已复制' : 'Link copied') : (zh ? '复制条目链接' : 'Copy article link')" :title="zh ? '复制条目链接' : 'Copy article link'" class="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500" @click="$emit('copy', entry.id)"><Check v-if="copied === entry.id" class="h-4 w-4" /><Link2 v-else class="h-4 w-4" /></button>
    </div>
    <div v-if="!['parameters', 'guides'].includes(entry.group) && entry.keys.length" class="mt-1.5 flex flex-wrap gap-x-3 gap-y-1"><code v-for="key in entry.keys" :key="key" class="break-all text-[11px] text-slate-400">{{ key }}</code></div>
    <p class="mt-3 whitespace-pre-line text-sm leading-6 text-slate-600">{{ description }}</p>
    <RouterLink v-if="entry.route && text.action" :to="entry.route" class="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100">{{ text.action }}<ArrowRight class="h-4 w-4" aria-hidden="true" /></RouterLink>
    <section v-for="section in text.sections" :key="section.title" class="mt-6">
      <component :is="heading === 'h2' ? 'h3' : 'h4'" class="text-sm font-semibold text-slate-900">{{ section.title }}</component>
      <component :is="section.ordered ? 'ol' : 'ul'" class="mt-3 space-y-3 pl-5 text-sm leading-6 text-slate-600" :class="section.ordered ? 'list-decimal marker:font-semibold marker:text-blue-700' : 'list-disc marker:text-slate-400'">
        <li v-for="item in section.items" :key="item" class="pl-1">{{ item }}</li>
      </component>
    </section>
    <dl v-if="!['parameters', 'guides'].includes(entry.group) && (text.range || entry.unit || 'default' in entry || entry.references.length)" class="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-xs leading-5">
      <div v-if="text.range" class="flex gap-2"><dt class="shrink-0 text-slate-400">{{ zh ? '范围' : 'Range' }}</dt><dd class="text-slate-700">{{ text.range }}</dd></div>
      <div v-if="entry.unit" class="flex gap-2"><dt class="text-slate-400">{{ zh ? '单位' : 'Unit' }}</dt><dd class="text-slate-700">{{ entry.unit }}</dd></div>
      <div v-if="'default' in entry" :class="Array.isArray(entry.default) ? 'w-full' : 'flex gap-2'"><dt class="text-slate-400">{{ zh ? '默认值' : 'Default' }}</dt><dd class="text-slate-700"><ul v-if="Array.isArray(entry.default)" class="mt-1 space-y-1"><li v-for="(value, index) in entry.default" :key="index"><code>{{ value.metric }}</code>: {{ value.mode === 'range' ? `${value.lower}–${value.upper}` : `≥ ${value.lower}` }} · {{ zh ? '权重' : 'weight' }} {{ value.weight }}</li></ul><template v-else>{{ entry.default === null ? (zh ? '根据目标数量估算' : 'Estimated from target count') : entry.default }}</template></dd></div>
      <div v-if="entry.references.length" class="flex gap-2"><dt class="text-slate-400">{{ zh ? '文献' : 'References' }}</dt><dd class="flex gap-2"><a v-for="id in entry.references" :key="id" :href="references[id].url" :title="references[id].title" :aria-label="references[id].title" target="_blank" rel="noopener noreferrer" class="text-blue-700 hover:underline">[{{ Object.keys(references).indexOf(id) + 1 }}]</a></dd></div>
    </dl>
  </article>
</template>
