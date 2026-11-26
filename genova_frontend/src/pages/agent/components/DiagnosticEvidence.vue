<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MarkdownIt from 'markdown-it'

const props = defineProps<{ evidence: Record<string, any>; notes?: string }>()
const { t } = useI18n()
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true })
const errors = computed(() => props.evidence.errors || props.evidence.job?.tasks?.filter((task: any) => task.error) || [])
const sources = computed(() => props.evidence.sources || [])
const excerpts = computed(() => (props.evidence.evidence || []).map((entry: any) => ({
  ...entry,
  name: entry.name || sources.value.find((source: any) => entry.ref.startsWith(source.ref.split(':L')[0]))?.name || entry.ref,
})))
</script>

<template>
  <details v-if="errors.length || sources.length || excerpts.length || notes" class="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-xs text-slate-600">
    <summary class="cursor-pointer font-medium">{{ t('agent.session.diagnosticEvidence') }}</summary>
    <div class="mt-3 space-y-4 border-t border-slate-200 pt-3">
      <section v-if="notes" class="space-y-2">
        <h4 class="font-medium">{{ t('agent.session.diagnosticNotes') }}</h4>
        <div class="prose prose-sm max-w-none break-words" v-html="markdown.render(notes)" />
      </section>
      <section v-if="errors.length" class="space-y-3">
        <h4 class="font-medium">{{ t('agent.session.diagnosticErrors') }}</h4>
        <div v-for="error in errors" :key="error.task_id" class="space-y-1">
          <p class="break-words font-medium">{{ error.engine || error.task_code }}<span v-if="error.error_code"> · {{ error.error_code }}</span></p>
          <p v-if="error.stage">{{ t('agent.session.failureStage') }}: {{ error.stage }}</p>
          <pre class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2">{{ error.error }}</pre>
          <p v-if="error.error_truncated">{{ t('agent.session.diagnosticErrorTruncated') }}</p>
          <p class="break-all text-slate-500">{{ error.ref }}</p>
        </div>
      </section>
      <section v-if="excerpts.length" class="space-y-3">
        <h4 class="font-medium">{{ t('agent.session.diagnosticExcerpts') }}</h4>
        <div v-for="(excerpt, index) in excerpts" :key="`${excerpt.ref}:${index}`" class="space-y-1">
          <p class="break-words font-medium">{{ excerpt.name }}</p>
          <p v-if="excerpt.source_version" class="break-all">{{ t('agent.session.diagnosticSourceVersion') }}: {{ excerpt.source_version }}</p>
          <pre class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-2"><span v-for="line in excerpt.lines" :key="`${line.line}:${line.column}`" class="block">L{{ line.line }}<span v-if="line.column">:{{ line.column }}</span>  {{ line.text }}</span></pre>
          <p v-if="excerpt.truncated">{{ t('agent.session.diagnosticExcerptOnly') }}</p>
          <p class="break-all text-slate-500">{{ excerpt.ref }}</p>
        </div>
      </section>
      <section v-if="sources.length" class="space-y-3">
        <h4 class="font-medium">{{ t('agent.session.sourceReferences') }}</h4>
        <div v-for="source in sources" :key="`${source.job_id}:${source.source_id}`" class="space-y-1">
          <p class="break-words font-medium">{{ source.name }}</p>
          <p class="break-all text-slate-500">{{ source.ref }}</p>
          <p class="break-all">{{ t('agent.session.diagnosticSourceVersion') }}: {{ source.source_version }}</p>
          <p v-if="source.query">{{ t('agent.session.diagnosticSearch') }}: {{ source.query }}</p>
          <p>{{ t('agent.session.diagnosticReadPosition', { line: source.start_line, column: source.start_column }) }}</p>
          <p v-if="source.next_line">{{ t('agent.session.diagnosticNextPosition', { line: source.next_line, column: source.next_column }) }}</p>
          <p v-if="source.scan_complete">{{ t('agent.session.diagnosticScanComplete') }}</p>
        </div>
      </section>
    </div>
  </details>
</template>
