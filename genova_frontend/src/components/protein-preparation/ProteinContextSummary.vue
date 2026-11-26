<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, Check, ChevronDown, CircleAlert, Dna, FlaskConical, LoaderCircle } from 'lucide-vue-next'
import { saveAs } from 'file-saver'
import { downloadBackendDataset } from '@/api/genovaBackend'
import { statusLabel } from '@/i18n'
import { retryContextValidation } from '@/api/proteinContext'
import { Button } from '@/components/ui/button'
import AlphaHelixIcon from '@/components/Layout/AlphaHelixIcon.vue'
import { isProteinContextReady, contextBox, type ComponentManifest, type ProteinContext } from '@/types/proteinContext'
import { displayErrorMessage } from '@/utils/requestError'

const props = defineProps<{
  context: ProteinContext | null
  editable?: boolean
  engine?: string
  compact?: boolean
  showActions?: boolean
  sourceManifest?: ComponentManifest | null
  receptorManifest?: ComponentManifest | null
}>()
const emit = defineEmits<{ edit: []; updated: [context: ProteinContext] }>()
const retrying = ref(false)
const retryError = ref('')
async function retry(engine: string) {
  if (!props.context || retrying.value) return
  retrying.value = true; retryError.value = ''
  try { const response = await retryContextValidation(props.context.id, engine); emit('updated', response.data) }
  catch (error: any) { retryError.value = displayErrorMessage(error) }
  finally { retrying.value = false }
}
const { locale, t, te } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const models = [
  { id: 'surfgen', name: 'SurfGen', path: '/molgen' },
  { id: 'ecloudgen', name: 'ECloudGen', path: '/molgen' },
  { id: 'delete', name: 'DELETE', path: '/molopt' },
  { id: 'epso', name: 'EPSO', path: '/molopt' },
]
const rows = computed(() => models.map(model => ({ ...model, ...props.context?.compatibility?.models[model.id], status: props.context?.compatibility?.models[model.id]?.status || 'unchecked' })))
const currentModel = computed(() => rows.value.find(row => row.id === props.engine))
const available = computed(() => rows.value.filter(row => isProteinContextReady(props.context, row.id)).length)
const pending = computed(() => rows.value.some(row => row.status === 'pending'))
const resultStatus = computed(() => {
  if (!isProteinContextReady(props.context)) return props.context?.status === 'ready' ? L('结构待验证', 'Structure validation required') : statusLabel(props.context?.status)
  if (pending.value) return available.value ? L('部分模型可用 · 验证中', 'Some models available · validating') : L('模型验证中', 'Validating models')
  if (available.value === models.length) return L('模型输入已就绪', 'Model inputs ready')
  if (available.value) return L('部分模型可用', 'Some models available')
  return rows.value.some(row => ['failed', 'incompatible'].includes(row.status)) ? L('模型输入未就绪', 'Model inputs not ready') : L('模型尚未验证', 'Models not validated')
})
const statusText = (status: string) => ({ full: L('已验证', 'Verified'), limited: L('有限兼容', 'Limited compatibility'), incompatible: L('输入不兼容', 'Input incompatible'), failed: L('验证失败', 'Validation failed'), pending: L('验证中', 'Validating'), unchecked: L('尚未准备', 'Not prepared') }[status] || status)
const statusClass = (status: string) => ['full', 'limited'].includes(status) ? status === 'full' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800' : status === 'pending' ? 'bg-blue-50 text-blue-700' : ['incompatible', 'failed'].includes(status) ? 'bg-rose-50 text-rose-700' : 'bg-slate-100 text-slate-600'
const groups = computed(() => {
  const grouped = new Map<string, typeof rows.value>()
  for (const row of rows.value) {
    if (!['incompatible', 'failed', 'limited'].includes(row.status) || !(row.error_info || row.error || row.reason)) continue
    const info = row.error_info
    const key = JSON.stringify([row.status, info?.error_code, info?.stage, info?.message || row.error || row.reason, [...(info?.objects || [])].sort()])
    grouped.set(key, [...(grouped.get(key) || []), row])
  }
  return [...grouped.values()]
})
const errorSummary = (row: typeof rows.value[number]) => {
  const key = `platform.preparationError_${row.error_info?.error_code}`
  if (row.error_info && te(key)) return t(key)
  return row.status === 'incompatible' ? L('当前结构不满足模型输入要求', 'The structure does not meet model input requirements') : row.status === 'limited' ? L('部分结构信息未用于模型输入', 'Some structure information is omitted from model inputs') : L('模型输入验证未完成，请查看详情', 'Model input validation failed; inspect details')
}
const componentLabel = (ids: string[], manifest?: ComponentManifest | null) => manifest?.components.filter(c => ids.includes(c.component_id)).map(c => {
  const atom = c.atoms[0]
  return `${atom.author_chain_id || '∅'} · ${atom.residue_name}${atom.author_residue_number}${atom.insertion_code}`
}).join(', ')
const siteLabel = computed(() => {
  const anchor = props.context?.site.anchor
  if (!anchor) return ''
  if (anchor.kind === 'source_components') return componentLabel(anchor.component_ids, props.sourceManifest) || L('源结构配体', 'Source structure ligand')
  if (anchor.kind === 'coordinates') return L('坐标位点', 'Coordinate site')
  const ids = new Set(anchor.residue_ids)
  const atoms = props.receptorManifest?.components.flatMap(c => c.atoms).filter(a => ids.has(a.residue_id)) || []
  return [...new Set(atoms.map(a => `${a.author_chain_id || '∅'} · ${a.residue_name}${a.author_residue_number}${a.insertion_code}`))].join(', ') || `${ids.size} ${L('个残基', 'residues')}`
})
const referenceLabel = computed(() => {
  const reference = props.context?.generation_reference
  if (!reference) return L('未选择', 'Not selected')
  return 'kind' in reference ? componentLabel([reference.source_component_id], props.sourceManifest) || L('源结构配体', 'Source structure ligand') : L('已上传配体', 'Uploaded ligand')
})
const format = (value: number) => Number(value).toFixed(3)
const downloadError = ref('')
async function downloadReport(row: typeof rows.value[number]) {
  const report = row.artifacts?.report
  if (!report) return
  downloadError.value = ''
  try {
    const response = await downloadBackendDataset(report.dataset_id, report.file_id)
    saveAs(response.data, `${row.id}-compatibility-report.json`)
  } catch {
    downloadError.value = L('报告下载失败，请重试。', 'Report download failed. Please retry.')
  }
}
</script>

<template>
  <component :is="compact ? 'details' : 'section'" v-if="context" :key="context.id" class="context-summary min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white text-sm" :class="{ 'group': compact }">
    <summary v-if="compact" class="cursor-pointer list-none space-y-2 bg-slate-50/80 p-3 [&::-webkit-details-marker]:hidden">
      <span class="flex items-center gap-2">
        <span class="flex-1 text-xs font-semibold text-slate-700">{{ L('结构与位点', 'Structure and site') }}</span>
        <span v-if="currentModel" class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs" :class="statusClass(currentModel.status)" role="status">
          <LoaderCircle v-if="currentModel.status === 'pending'" class="size-3 animate-spin" />{{ currentModel.name }} · {{ statusText(currentModel.status) }}
        </span>
        <ChevronDown class="size-4 shrink-0 text-slate-500 group-open:rotate-180" />
      </span>
      <span class="block text-xs" :class="context.generation_reference ? 'text-slate-600' : 'text-amber-800'">{{ context.generation_reference ? L('参考配体已选择', 'Reference ligand selected') : L('未选择参考配体', 'No reference ligand selected') }}</span>
      <span v-if="currentModel && ['failed', 'incompatible', 'limited'].includes(currentModel.status)" class="block text-xs text-amber-800">{{ errorSummary(currentModel) }}</span>
    </summary>
    <header v-else class="flex items-start gap-3 bg-slate-50/80 p-4">
      <span class="flex size-9 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600"><AlphaHelixIcon class="size-5" /></span>
      <div class="min-w-0 flex-1">
        <p class="text-xs font-medium text-slate-500">{{ L('结构与位点', 'Structure and site') }}</p>
        <h3 class="mt-1 break-words font-semibold text-slate-900">{{ context.name }}</h3>
        <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span v-if="isProteinContextReady(context)" class="inline-flex items-center gap-1 text-slate-600"><Check class="size-3.5" />{{ L('位点已保存', 'Site saved') }}</span>
          <span class="rounded-full px-2 py-0.5 font-medium" :class="pending ? 'bg-blue-50 text-blue-700' : available === models.length ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'" role="status">{{ resultStatus }}</span>
        </div>
      </div>
    </header>
    <div class="space-y-4 p-4">
      <dl class="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-xs">
        <dt class="text-slate-500">{{ L('位点', 'Site') }}</dt><dd class="break-words text-slate-800">{{ siteLabel }}</dd>
        <dt class="text-slate-500">{{ L('参考配体', 'Reference ligand') }}</dt><dd class="break-words text-slate-800">{{ referenceLabel }}</dd>
        <dt class="text-slate-500">{{ L('中心', 'Center') }}</dt><dd class="break-words tabular-nums text-slate-700">{{ contextBox(context).center.map(format).join(', ') }} Å</dd>
        <dt class="text-slate-500">{{ L('范围', 'Size') }}</dt><dd class="break-words tabular-nums text-slate-700">{{ contextBox(context).size.map(format).join(' × ') }} Å</dd>
      </dl>
      <section class="border-t border-slate-100 pt-3" :aria-label="L('模型兼容性', 'Model compatibility')">
        <div class="mb-2 flex items-center justify-between gap-2"><h4 class="text-xs font-semibold text-slate-800">{{ L('模型兼容性', 'Model compatibility') }}</h4><span class="text-xs text-slate-500">{{ available }} / {{ models.length }} {{ L('可用', 'available') }}</span></div>
        <div v-for="row in rows" :key="row.id" class="flex items-center justify-between gap-2 rounded-md px-2 py-2" :class="engine === row.id ? 'bg-slate-50' : ''">
          <span class="text-xs font-medium text-slate-700">{{ row.name }}</span>
          <Button v-if="['failed', 'incompatible', 'unchecked'].includes(row.status)" size="sm" variant="outline" :disabled="retrying" @click="retry(row.id)">{{ L('重试', 'Retry') }}</Button>
          <span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs" :class="statusClass(row.status)"><LoaderCircle v-if="row.status === 'pending'" class="size-3 animate-spin" /><Check v-else-if="['full', 'limited'].includes(row.status)" class="size-3" /><CircleAlert v-else-if="['incompatible', 'failed'].includes(row.status)" class="size-3" />{{ statusText(row.status) }}</span>
        </div>
        <p v-if="!context.capabilities.input_preparation" class="mt-2 text-xs text-amber-800">{{ L('请重新保存 Context，验证模型输入。', 'Save the Context again to validate model inputs.') }}</p>
        <div v-for="(group, index) in groups" :key="index" class="mt-3 space-y-2 rounded-lg border p-3 text-xs" :class="group[0].status === 'limited' ? 'border-amber-100 bg-amber-50/60 text-amber-900' : 'border-rose-100 bg-rose-50/60 text-rose-900'">
          <p class="font-semibold">{{ group.map(row => row.name).join(' / ') }}</p>
          <p class="break-words leading-relaxed">{{ errorSummary(group[0]) }}</p>
          <p v-if="group[0].error_info?.objects.length" class="break-words">{{ group[0].error_info.objects.slice(0, 4).join(', ') }}<span v-if="group[0].error_info.objects.length > 4"> …</span></p>
          <details class="text-slate-600">
            <summary class="cursor-pointer font-medium">{{ L('查看详情与报告', 'Details and reports') }}</summary>
            <div class="mt-2 space-y-2">
              <code v-if="group[0].error_info" class="block break-all">{{ group[0].error_info.error_code }}</code>
              <p v-if="group[0].error_info?.stage">{{ L('阶段：', 'Stage: ') }}{{ te(`platform.execution_${group[0].error_info.stage}`) ? t(`platform.execution_${group[0].error_info.stage}`) : group[0].error_info.stage }}</p>
              <p v-if="group[0].error_info?.objects.length" class="break-words">{{ group[0].error_info.objects.join(', ') }}</p>
              <pre class="max-h-48 overflow-auto whitespace-pre-wrap break-words font-sans">{{ group[0].error || group[0].error_info?.message || group[0].reason }}</pre>
              <div class="flex flex-wrap gap-1"><Button v-for="row in group.filter(row => row.artifacts?.report)" :key="row.id" size="sm" variant="outline" @click="downloadReport(row)">{{ row.name }} {{ L('报告', 'report') }}</Button></div>
            </div>
          </details>
        </div>
        <p v-if="context.compatibility?.models.tarpass" class="mt-3 text-xs text-slate-500">TarPass · {{ L('评价时验证', 'Validated during evaluation') }}</p>
        <p v-if="retryError" role="alert" class="text-xs text-rose-700">{{ retryError }}</p>
        <p v-if="downloadError" role="alert" class="mt-2 text-xs text-rose-700">{{ downloadError }}</p>
      </section>
      <section v-if="showActions" class="space-y-2 border-t border-slate-100 pt-3" :aria-label="L('下一步', 'Next step')">
        <h4 class="text-xs font-semibold text-slate-800">{{ L('下一步', 'Next step') }}</h4>
        <div v-for="group in [{ path: '/molgen', name: L('从头生成', 'De novo generation'), icon: FlaskConical }, { path: '/molopt', name: L('先导优化', 'Lead optimization'), icon: Dna }]" :key="group.path" class="rounded-lg border border-slate-200 p-3">
          <h5 class="mb-2 flex items-center gap-2 text-xs font-medium text-slate-700"><component :is="group.icon" class="size-4 text-slate-500" />{{ group.name }}</h5>
          <div class="grid grid-cols-2 gap-2">
            <template v-for="row in rows.filter(row => row.path === group.path)" :key="row.id">
              <RouterLink v-if="isProteinContextReady(context, row.id)" :to="{ path: row.path, query: { protein_context_id: context.id, engine: row.id } }" class="inline-flex min-h-9 items-center justify-center gap-1 rounded-md border border-violet-200 bg-violet-50 px-2 py-2 text-xs font-medium text-violet-800 transition-colors hover:border-violet-300 hover:bg-violet-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500">{{ row.name }}<ArrowUpRight class="size-3.5" /></RouterLink>
              <button v-else type="button" disabled class="flex min-h-9 flex-col items-center justify-center gap-0.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-2 text-xs text-slate-400" :title="statusText(row.status)"><span>{{ row.name }}</span><span>{{ statusText(row.status) }}</span></button>
            </template>
          </div>
        </div>
      </section>
      <Button v-if="editable" size="sm" variant="outline" @click="$emit('edit')">{{ L('编辑结构与位点', 'Edit structure and site') }}</Button>
    </div>
  </component>
</template>
