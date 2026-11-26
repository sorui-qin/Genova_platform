<template>
  <section class="space-y-3 rounded-lg border bg-white p-3" data-testid="workflow-draft-card">
    <header class="flex items-center justify-between gap-2"><h3 class="font-semibold">{{ t('agent.ui.newDraft') }}</h3><span class="text-xs text-slate-500">{{ engine }}</span></header>
    <div v-if="!contextId" role="status" class="space-y-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
      <p>{{ L('请先选择并准备蛋白，生成 Protein Context 后再提交方案。','Select and prepare a protein to create a Protein Context before submitting this plan.') }}</p>
      <Button size="sm" variant="outline" :disabled="busy" @click="emit('openContext')">{{ L('选择或准备蛋白','Select or prepare protein') }}</Button>
    </div>
    <div class="grid grid-cols-2 gap-2">
      <label class="min-w-0 space-y-1 text-sm">{{ t('agent.session.model') }}
        <select v-model="engine" class="h-9 w-full rounded border px-2" data-testid="draft-engine">
          <option v-for="(capability, key) in generators" :key="key" :value="key" :disabled="!capability.enabled">{{ key }}{{ !capability.enabled ? ' · ' + t('agent.ui.enabledReason') : '' }}</option>
        </select>
      </label>
      <label class="min-w-0 space-y-1 text-sm">{{ t('agent.session.generationCount') }}
        <input v-model.number="quantity" type="number" min="1" :max="moleculeLimit" class="h-9 w-full rounded border px-2" />
        <span v-if="moleculeLimit === 500 && Number(quantity) > moleculeLimit" role="alert" class="block text-xs text-rose-700">{{ t('platform.epsoAffinityCountLimit') }}</span>
        <span v-if="engine === 'surfgen' && quantity > SURFGEN_ROUND_TARGET" class="block text-xs text-slate-500">{{ t('platform.generationPlatformSeeds') }}</span>
      </label>
    </div>
    <p v-if="engine === 'delete' && !editSpec" role="status" class="text-sm text-amber-800">{{ contextPreparing ? L('正在准备模型输入，完成后可编辑片段。','Model inputs are being prepared. Fragment editing will be available when ready.') : L('请先在结构编辑器中选择需要保留和生成的片段。','Choose the fragment to retain and regenerate in the structure editor first.') }}</p>
    <Button v-if="engine === 'delete' && !editSpec" size="sm" variant="outline" :disabled="busy || contextPreparing || !contextId" @click="emit('editDelete')">{{ L('编辑片段','Edit fragments') }}</Button>
    <details v-if="['surfgen','ecloudgen'].includes(engine) || engine === 'epso'" class="rounded border px-2 py-1">
      <summary class="cursor-pointer text-sm">{{ L('高级参数','Advanced parameters') }}</summary>
      <div class="mt-2 space-y-3">
        <GenerationAdvanced v-if="['surfgen','ecloudgen'].includes(engine)" ref="advanced" v-model="sampling[engine]" :engine="engine as 'surfgen' | 'ecloudgen'" :planning="samplingLoading" :platform-seeds="engine === 'surfgen' && quantity > SURFGEN_ROUND_TARGET" :cloud-estimate="cloudEstimate" />
        <template v-if="engine === 'epso'">
          <div class="grid grid-cols-2 gap-2">
            <label v-for="key in ['num_particles', 'num_steps', 'seed']" :key="key" class="space-y-1 text-sm">{{ t(optimizerLabels[key]) }}<input v-model.number="optimizer[key]" type="number" min="0" class="h-9 w-full rounded border px-2" /></label>
          </div>
          <div v-for="objective in objectives" :key="objective.metric" class="space-y-2 rounded border bg-slate-50 p-2 text-sm">
            <div class="flex flex-wrap items-center gap-2"><span>{{ t('platform.epsoMetric_' + objective.metric) }}</span><select v-if="objective.metric !== 'gnina_affinity'" v-model="objective.mode" :aria-label="t('agent.session.objectiveMode')" class="rounded border px-2 py-1" @change="resetObjective(objective)"><option v-for="mode in Object.keys(modeFields).filter(mode => mode !== 'seed_relative')" :key="mode" :value="mode">{{ t('platform.epsoMode_' + mode) }}</option></select><button type="button" class="text-red-700" @click="objectives = objectives.filter(item => item.metric !== objective.metric)">{{ t('agent.session.deleteObjective') }}</button></div>
            <label v-for="key in Object.keys(objective).filter(key => !['metric', 'mode'].includes(key))" :key="key" class="mr-3 inline-flex items-center gap-1">{{ t(key === 'weight' ? 'platform.epsoWeight' : key === 'softness' ? 'platform.epsoSoftness' : 'platform.epsoField_' + key) }}<input v-model.number="objective[key]" type="number" step="any" class="w-20 rounded border px-2 py-1" /></label>
          </div>
          <select :aria-label="t('agent.session.addEpsoObjective')" value="" class="rounded border px-2 py-1" @change="addObjective(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''"><option value="">{{ t('agent.session.addObjective') }}</option><option v-for="metric in metrics.filter(metric => !objectives.some(objective => objective.metric === metric))" :key="metric" :value="metric">{{ t('platform.epsoMetric_' + metric) }}</option></select>
        </template>
      </div>
    </details>
    <p v-if="samplingError" role="alert" class="text-sm text-red-700">{{ samplingError }}</p>
    <p v-if="editSpec" class="text-xs text-slate-500">{{ t('agent.session.deleteEdit') }} {{ editSpec }}</p>
    <div v-if="showActions !== false" class="sticky bottom-0 flex justify-end border-t bg-white/95 pt-2">
      <Button :disabled="busy || contextPreparing || !contextId || !valid" @click="save" data-testid="draft-submit">{{ L('提交并执行','Submit and execute') }}</Button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { displayErrorMessage } from '@/utils/requestError'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { effectiveGenerationSampling, generationCountLimit, SURFGEN_ROUND_TARGET } from '@/utils/generationForm'
import GenerationAdvanced from '@/components/common/GenerationAdvanced.vue'
import { getEcloudSamplingPlan } from '@/api/genovaBackend'
import { defaultPrefilters } from '@/utils/tarpassDefaults'

const { t, locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en

interface Objective {
  metric: string
  mode: string
  [field: string]: string | number
}

interface DraftState {
  version: number
  input_revision: number
  protein_context_id: string
  generator: string
  template: string
  seed_source?: any
  engine: string
  quantity: number | string | null
  optimizer: Record<string, any>
  objectives: Objective[]
  postprocessing: { enabled: boolean; prefilters: any[] }
  selection: { sort_by: null; descending: boolean; top_k: null }
  generation: Record<string, any>
  plan: Record<string, any>
}

const props = withDefaults(defineProps<{
  version: number
  contextId: string
  busy: boolean
  contextPreparing?: boolean
  showActions?: boolean
  generators: Record<string, any>
  editSpec?: string
  editMode?: string
  plan?: Record<string, any> | null
  initialDraft?: Record<string, any> | null
}>(), { showActions: true })

const emit = defineEmits<{
  save: [plan: Record<string, any>, version: number]
  dirty: [value: boolean]
  valid: [value: boolean]
  draft: [draft: Record<string, any>]
  editDelete: []
  openContext: []
}>()

const clone = <T,>(value: T): T => value == null ? value : JSON.parse(JSON.stringify(value))
const optimizerLabels: Record<string,string> = {num_particles:'platform.epsoParticles',num_steps:'platform.epsoSteps',seed:'platform.epsoSeed'}
const defaultOptimizer = { num_particles: 200, num_swarms: 1, num_steps: 20, seed: 2024 }
const defaultObjectives: Objective[] = [
  { metric: 'qed', mode: 'lower_bound', lower: 0.6, weight: 1 },
  { metric: 'sa', mode: 'lower_bound', lower: 0.6, weight: 1 },
  { metric: 'mw', mode: 'range', lower: 250, upper: 500, weight: 1 },
]
const metrics = ['qed', 'sa', 'mw', 'logp', 'lipinski', 'hba', 'hbd', 'heavy_atom_count', 'similarity', 'gnina_affinity']
const modeFields: Record<string, string[]> = {
  lower_bound: ['lower'],
  upper_bound: ['upper'],
  range: ['lower', 'upper'],
  target: ['target'],
  maximize: ['lower', 'upper'],
  minimize: ['lower', 'upper'],
  seed_relative: [],
}
const metricBounds: Record<string, [number | null, number | null]> = {
  qed: [0, 1], sa: [0, 1], mw: [0, null], logp: [null, null], lipinski: [0, 5], hba: [0, null], hbd: [0, null], heavy_atom_count: [0, null], similarity: [0, 1], gnina_affinity: [null, null],
}
const restored = props.initialDraft || {}
const sourcePlan = props.plan || restored.plan || {}
const sourceGeneration = sourcePlan.generation || {}
const baseVersion = ref(Number(restored.input_revision ?? restored.version ?? props.version))
const defaultEngine = Object.keys(props.generators).find(key => props.generators[key].enabled && key !== 'delete') || ''
const engine = ref(String(restored.engine || restored.generator || restored.generation?.engine || sourceGeneration.engine || defaultEngine))
const quantity = ref(restored.quantity ?? restored.generation?.[engine.value === 'ecloudgen' ? 'target_num_molecules' : 'num_molecules'] ?? sourceGeneration[engine.value === 'ecloudgen' ? 'target_num_molecules' : 'num_molecules'] ?? (engine.value === 'epso' ? 100 : 1000))
const optimizer = ref<Record<string, any>>(clone(restored.optimizer ?? restored.generation?.optimizer ?? sourceGeneration.optimizer ?? (engine.value === 'epso' ? defaultOptimizer : {})))
const objectives = ref<Objective[]>(clone(restored.objectives ?? restored.generation?.objectives ?? sourceGeneration.objectives ?? (engine.value === 'epso' ? defaultObjectives : [])))
const moleculeLimit = computed(() => generationCountLimit(engine.value, objectives.value))
const advanced = ref<InstanceType<typeof GenerationAdvanced> | null>(null)
const samplingLoading = ref(false), samplingError = ref('')
let samplingRequest = 0
const sampling = ref<Record<string, Record<string, number | string>>>({
  surfgen: { beam_size: 500, max_steps: 50, element_threshold: 0.3, bond_threshold: 0.4, seed: 2020 },
  ecloudgen: { noise: 0.1, inv_temp: 2, num_clouds: '', decodes_per_cloud: 100, seed: 42, budget_multiplier: 3 },
})
const restoredSettings = restored.generation || restored.plan?.generation || sourceGeneration
for (const key of Object.keys(sampling.value[engine.value] || {})) {
  if (restoredSettings[key] != null) sampling.value[engine.value][key] = restoredSettings[key]
}
const cloudEstimate = ref<number>()
async function refreshSampling() {
  const requestId = ++samplingRequest
  samplingError.value = ''
  if (engine.value !== 'ecloudgen' || sampling.value.ecloudgen.num_clouds !== '' || !Number.isInteger(Number(quantity.value)) || Number(quantity.value) < 1) { samplingLoading.value = false; return }
  samplingLoading.value = true
  try {
    const { data } = await getEcloudSamplingPlan(Number(quantity.value), sampling.value.ecloudgen)
    if (requestId !== samplingRequest) return
    cloudEstimate.value = data.num_clouds
  } catch (error: any) {
    if (requestId === samplingRequest) samplingError.value = displayErrorMessage(error)
  } finally { if (requestId === samplingRequest) samplingLoading.value = false }
}
watch(() => [engine.value, quantity.value, sampling.value.ecloudgen.num_clouds,
  sampling.value.ecloudgen.decodes_per_cloud, sampling.value.ecloudgen.noise, sampling.value.ecloudgen.inv_temp],
  () => { void refreshSampling() })
if (engine.value === 'ecloudgen' && !restoredSettings.num_clouds) void refreshSampling()

function quantityField(value: string) {
  return value === 'ecloudgen' ? 'target_num_molecules' : 'num_molecules'
}

function planPayload(): Record<string, any> {
  const generation: Record<string, any> = { engine: engine.value, ...effectiveGenerationSampling(engine.value, Number(quantity.value), sampling.value[engine.value] || {}), [quantityField(engine.value)]: quantity.value }
  if (engine.value === 'epso') {
    generation.optimizer = clone(optimizer.value)
    generation.objectives = clone(objectives.value)
  }
  const plan: Record<string, any> = {
    protein_context_id: props.contextId,
    generator: engine.value,
    template: `${engine.value}_tarpass_v1`,
    generation,
    postprocessing: { enabled: true, prefilters: defaultPrefilters() },
    selection: { sort_by: null, descending: false, top_k: null },
  }
  const protocolVersion = restored.protocol_version ?? sourcePlan.protocol_version
  if (protocolVersion !== undefined) plan.protocol_version = protocolVersion
  const seedSource = restored.seed_source ?? sourcePlan.seed_source
  if (seedSource !== undefined) plan.seed_source = clone(seedSource)
  if (engine.value === 'delete') generation.edit = { edit_spec_id: props.editSpec, mode: props.editMode }
  return plan
}

function draftSnapshot(): DraftState {
  const plan = planPayload()
  return {
    version: baseVersion.value,
    input_revision: baseVersion.value,
    protein_context_id: props.contextId,
    generator: engine.value,
    template: plan.template,
    ...(plan.seed_source === undefined ? {} : { seed_source: clone(plan.seed_source) }),
    engine: engine.value,
    quantity: quantity.value,
    optimizer: clone(optimizer.value),
    objectives: clone(objectives.value),
    postprocessing: { enabled: true, prefilters: defaultPrefilters() },
    selection: { sort_by: null, descending: false, top_k: null },
    generation: clone(plan.generation),
    plan: clone(plan),
  }
}

const initialSnapshot = JSON.stringify(draftSnapshot())
function onChange() {
  const draft = draftSnapshot()
  emit('dirty', JSON.stringify(draft) !== initialSnapshot)
  emit('draft', draft)
}

watch([engine, quantity, optimizer, objectives, sampling], onChange, { deep: true, immediate: true })
watch(engine, value => {
  if (value === 'epso') {
    if (!Object.keys(optimizer.value).length) optimizer.value = clone(defaultOptimizer)
    if (!objectives.value.length) objectives.value = clone(defaultObjectives)
  }
})

function resetObjective(objective: Objective) {
  for (const key of ['lower', 'upper', 'target', 'softness']) delete objective[key]
  for (const key of modeFields[objective.mode] || []) objective[key] = key === 'lower' ? 0 : objective.metric === 'mw' ? 500 : objective.metric === 'lipinski' ? 5 : 1
}

function addObjective(metric: string) {
  if (!metric) return
  const objective: Objective = { metric, mode: metric === 'gnina_affinity' ? 'seed_relative' : 'lower_bound', weight: 1 }
  resetObjective(objective)
  objectives.value.push(objective)
}

function objectiveValid(objective: Objective) {
  const fields = modeFields[objective.mode]
  const bounds = metricBounds[objective.metric]
  if (!fields || !bounds) return false
  if (Object.entries(objective).some(([key, value]) => !['metric', 'mode'].includes(key) && (!Number.isFinite(Number(value)) || (['weight', 'softness'].includes(key) && Number(value) <= 0)))) return false
  for (const field of fields) {
    if (objective[field] == null && (objective.mode !== 'maximize' && objective.mode !== 'minimize' || bounds[1] == null)) return false
    if (objective[field] == null) continue
    const value = Number(objective[field])
    if (bounds[0] != null && value < bounds[0] || bounds[1] != null && value > bounds[1]) return false
  }
  return !(objective.lower != null && objective.upper != null && Number(objective.lower) >= Number(objective.upper))
}

const valid = computed(() => {
  if (!props.contextId || props.contextPreparing || samplingLoading.value || samplingError.value || !props.generators[engine.value]?.enabled) return false
  if (engine.value === 'delete' && !props.editSpec) return false
  const count = Number(quantity.value)
  if (!engine.value || !Number.isInteger(count) || count < 1 || count > moleculeLimit.value) return false
  if (engine.value !== 'epso') return true
  return Number.isInteger(Number(optimizer.value.num_particles)) && Number(optimizer.value.num_particles) > 0 && Number(optimizer.value.num_particles) <= 1000
    && Number.isInteger(Number(optimizer.value.num_steps)) && Number(optimizer.value.num_steps) > 0 && Number(optimizer.value.num_steps) <= 1000
    && Number.isInteger(Number(optimizer.value.seed)) && Number(optimizer.value.seed) >= 0 && Number(optimizer.value.seed) <= 4294967295
    && Number(optimizer.value.num_particles) * (Number(optimizer.value.num_steps) + 1) <= 20000
    && Number(optimizer.value.num_swarms) === 1
    && objectives.value.length > 0
    && new Set(objectives.value.map(item => item.metric)).size === objectives.value.length
    && objectives.value.every(item => objectiveValid(item))
})

watch(valid, value => emit('valid', Boolean(value)), { immediate: true })

function save() {
  if (!valid.value || advanced.value?.validate() === false) return
  emit('save', planPayload(), baseVersion.value)
}
</script>
