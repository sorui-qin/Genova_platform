<template>
  <section class="space-y-3 border-b pb-4" data-testid="context-result-card">
    <h3 class="font-semibold">{{ L('结构与位点', 'Structure and site') }}</h3>
    <p class="break-words text-sm">{{ context?.name || prepared?.name }}</p>
    <p v-if="context?.generation_reference" class="break-words text-sm">{{ L('生成 / 对接参考配体', 'Generation / docking reference ligand') }} · {{ referenceLabel }}</p>
    <dl v-if="context?.site" class="grid gap-3 text-sm sm:grid-cols-2"><div><dt class="text-slate-500">{{ L('位点中心', 'Site center') }}</dt><dd>{{ context.site.box.center.map((value: number) => Number(value.toFixed(2))).join(', ') }} Å</dd></div><div><dt class="text-slate-500">{{ L('盒子尺寸', 'Box size') }}</dt><dd>{{ context.site.box.size.map((value: number) => Number(value.toFixed(2))).join(' × ') }} Å</dd></div></dl>
    <!-- Worker text is technical and usually English: show the localized summary, with the text under technical details. -->
    <PreparationErrorDetails v-if="prepared?.execution?.error_info || prepared?.execution?.error" :error="prepared.execution.error_info" :fallback="L('结构准备失败，请重新准备。', 'Structure preparation failed. Please prepare it again.')" />
    <footer class="flex flex-wrap gap-2"><Button size="sm" variant="outline" @click="$emit('open')">{{ L('查看结构 / 位点', 'View structure / site') }}</Button><Button v-if="context" size="sm" variant="outline" :disabled="disabled" @click="$emit('plan')">{{ L('生成 / 优化方案', 'Plan generation / optimization') }}</Button></footer>
  </section>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import PreparationErrorDetails from '@/components/protein-preparation/PreparationErrorDetails.vue'
const props = defineProps<{ context?: Record<string, any>; prepared?: Record<string, any>; filename?: string; disabled: boolean }>()
defineEmits<{open: []; plan: []}>()
const { locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const referenceLabel = computed(() => { const ref = props.context?.generation_reference; return ref?.label || ref?.name || ref?.residue_name || ref?.source?.original_filename || L('使用 Context 中已确认的配体', 'Confirmed ligand from the Context') })
</script>
