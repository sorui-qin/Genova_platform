<template>
  <section class="space-y-3" data-testid="workflow-parameters">
    <p class="text-xs text-slate-500">{{ t('agent.ui.planVersion', { version: proposal.payload.plan_version }) }} · {{ selectedEngine }}</p>
    <div class="grid grid-cols-2 gap-2">
      <label class="min-w-0 space-y-1 text-sm">{{ t('agent.session.model') }}
        <select v-model="selectedEngine" class="h-9 w-full rounded border px-2" data-testid="plan-engine"><option v-for="(capability, key) in generators" :key="key" :value="key" :disabled="!capability.enabled">{{ key }}{{ !capability.enabled ? ' · ' + t('agent.ui.enabledReason') : '' }}</option></select>
      </label>
      <label class="min-w-0 space-y-1 text-sm">{{ t('agent.session.generationCount') }}
        <input v-model.number="quantity" type="number" min="1" :max="moleculeLimit" class="h-9 w-full rounded border px-2" />
        <span v-if="moleculeLimit === 500 && Number(quantity) > moleculeLimit" role="alert" class="block text-xs text-rose-700">{{ t('platform.epsoAffinityCountLimit') }}</span>
        <span v-if="selectedEngine === 'surfgen' && quantity > SURFGEN_ROUND_TARGET" class="block text-xs text-slate-500">{{ t('platform.generationPlatformSeeds') }}</span>
      </label>
    </div>
    <div v-if="selectedEngine === 'delete' && !editSpec" role="status" class="space-y-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
      <p>{{ L('请先在结构编辑器中选择 DELETE 片段并保存，之后才能批准。','Choose and save DELETE fragments in the structure editor before approving this plan.') }}</p>
      <Button size="sm" variant="outline" :disabled="busy" @click="emit('editDelete')">{{ L('编辑片段','Edit fragments') }}</Button>
    </div>
    <details v-if="['surfgen','ecloudgen'].includes(selectedEngine)" class="rounded border px-2 py-1">
      <summary class="cursor-pointer text-sm">{{ L('高级参数','Advanced parameters') }}</summary>
      <div class="mt-2 space-y-3">
        <GenerationAdvanced v-if="['surfgen','ecloudgen'].includes(selectedEngine)" ref="advanced" v-model="sampling[selectedEngine]" :engine="selectedEngine as 'surfgen' | 'ecloudgen'" :planning="samplingLoading" :platform-seeds="selectedEngine === 'surfgen' && quantity > SURFGEN_ROUND_TARGET" :cloud-estimate="cloudEstimate" />

      </div>
    </details>
    <section v-if="selectedEngine === 'epso'" class="space-y-3">
      <h4 class="text-sm font-medium">{{ L('优化目标', 'Optimization objectives') }}</h4>
          <div v-for="objective in objectives" :key="objective.metric" class="space-y-2 rounded border bg-slate-50 p-2 text-sm">
            <div class="flex flex-wrap items-center gap-2"><span>{{ t('platform.epsoMetric_' + objective.metric) }}</span><select v-if="objective.metric !== 'gnina_affinity'" v-model="objective.mode" :aria-label="t('agent.session.objectiveMode')" class="rounded border px-2 py-1" @change="resetObjective(objective)"><option v-for="mode in Object.keys(modeFields).filter(mode => mode !== 'seed_relative')" :key="mode" :value="mode">{{ t('platform.epsoMode_' + mode) }}</option></select><button type="button" class="text-red-700" @click="objectives = objectives.filter(item => item.metric !== objective.metric)">{{ t('agent.session.deleteObjective') }}</button></div>
            <label v-for="key in Object.keys(objective).filter(key => !['metric', 'mode'].includes(key))" :key="key" class="mr-3 inline-flex items-center gap-1">{{ t(key === 'weight' ? 'platform.epsoWeight' : key === 'softness' ? 'platform.epsoSoftness' : 'platform.epsoField_' + key) }}<input v-model.number="objective[key]" type="number" step="any" class="w-20 rounded border px-2 py-1" /></label>
          </div>
          <select :aria-label="t('agent.session.addEpsoObjective')" value="" class="rounded border px-2 py-1" @change="addObjective(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''"><option value="">{{ t('agent.session.addObjective') }}</option><option v-for="metric in metrics.filter(metric => !objectives.some(objective => objective.metric === metric))" :key="metric" :value="metric">{{ t('platform.epsoMetric_' + metric) }}</option></select>
      <p v-if="!objectives.length" role="alert" class="text-sm text-amber-800">{{ L('请添加至少一个优化目标。','Add at least one optimization objective.') }}</p>
      <details class="rounded border px-2 py-1"><summary class="cursor-pointer text-sm">{{ L('高级参数','Advanced parameters') }}</summary><div class="mt-2">
          <div class="grid grid-cols-2 gap-2"><label v-for="key in ['num_particles', 'num_steps', 'seed']" :key="key" class="space-y-1 text-sm">{{ t(optimizerLabels[key]) }}<input v-model.number="optimizer[key]" type="number" :min="key === 'seed' ? 0 : 1" class="h-9 w-full rounded border px-2" /></label></div>
      </div></details>
    </section>
    <div v-if="samplingError" role="alert" class="space-y-2 text-sm text-red-700"><p>{{ samplingError }}</p><Button variant="outline" :disabled="busy || samplingLoading" @click="refreshSampling">{{ L('重试采样方案','Retry sampling plan') }}</Button></div>
    <Button v-if="showActions !== false" size="sm" :disabled="busy || !valid" @click="save" data-testid="plan-submit">{{ t('agent.session.approve') }}</Button>
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
  version?: number
  input_revision?: number
  protein_context_id?: string
  engine: string
  generator: string
  template: string
  seed_source?: any
  quantity: number | string | null
  optimizer: Record<string, any>
  objectives: Objective[]
  postprocessing: { enabled: boolean; prefilters: any[] }
  selection: { sort_by: null; descending: boolean; top_k: null }
  generation: Record<string, any>
  plan: Record<string, any>
}

const props = withDefaults(defineProps<{
  proposal: any
  filters?: Array<Record<string, any>>
  busy: boolean
  showActions?: boolean
  generators: Record<string, any>
  editSpec?: string
  editMode?: string
  initialDraft?: Record<string, any> | null
}>(), { showActions: true })

const emit = defineEmits<{
  save: [patch: Record<string, any>, version: number]
  dirty: [value: boolean]
  valid: [value: boolean]
  draft: [draft: Record<string, any>]
  editDelete: []
}>()

const clone = <T,>(value: T): T => value == null ? value : JSON.parse(JSON.stringify(value))
const payload = props.proposal?.payload || {}
const inputRevision = Number(payload.input_revision ?? props.proposal?.input_revision ?? 0)
const sourcePlan = payload.plan || {}
const sourceGeneration: Record<string, any> = sourcePlan.generation || payload.effective_generation || {}
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
const optimizerLabels: Record<string,string> = {num_particles:'platform.epsoParticles',num_steps:'platform.epsoSteps',seed:'platform.epsoSeed'}
const defaultOptimizer = { num_particles: 200, num_swarms: 1, num_steps: 20, seed: 2024 }
const defaultObjectives: Objective[] = [
  { metric: 'qed', mode: 'lower_bound', lower: 0.6, weight: 1 },
  { metric: 'sa', mode: 'lower_bound', lower: 0.6, weight: 1 },
  { metric: 'mw', mode: 'range', lower: 250, upper: 500, weight: 1 },
]

function quantityField(engine: string) {
  return engine === 'ecloudgen' ? 'target_num_molecules' : 'num_molecules'
}

const restored = props.initialDraft || {}
const restoredGeneration = restored.generation || restored.plan?.generation || {}
const sourceEngine = String(sourceGeneration.engine || sourcePlan.generator || 'surfgen')
const selectedEngine = ref(String(restored.engine || restored.generator || restored.plan?.generator || restoredGeneration.engine || sourceEngine))
const quantity = ref(restored.quantity ?? restoredGeneration[quantityField(selectedEngine.value)] ?? sourceGeneration[quantityField(sourceEngine)] ?? (selectedEngine.value === 'epso' ? 100 : 1000))
const optimizer = ref<Record<string, any>>({ ...(selectedEngine.value === 'epso' ? defaultOptimizer : {}), ...clone(restored.optimizer ?? restoredGeneration.optimizer ?? sourceGeneration.optimizer ?? {}) })
const objectives = ref<Objective[]>(clone(restored.objectives ?? restoredGeneration.objectives ?? sourceGeneration.objectives ?? (selectedEngine.value === 'epso' ? defaultObjectives : [])))
const moleculeLimit = computed(() => generationCountLimit(selectedEngine.value, objectives.value))
const advanced = ref<InstanceType<typeof GenerationAdvanced> | null>(null)
const samplingLoading = ref(false), samplingError = ref('')
let samplingRequest = 0
const sampling = ref<Record<string, Record<string, number | string>>>({
  surfgen: { beam_size: 500, max_steps: 50, element_threshold: 0.3, bond_threshold: 0.4, seed: 2020 },
  ecloudgen: { noise: 0.1, inv_temp: 2, num_clouds: '', decodes_per_cloud: 100, seed: 42, budget_multiplier: 3 },
})
const restoredSettings = restored.generation || restored.plan?.generation || sourceGeneration
for (const key of Object.keys(sampling.value[selectedEngine.value] || {})) {
  if (restoredSettings[key] != null) sampling.value[selectedEngine.value][key] = restoredSettings[key]
}
const cloudEstimate = ref<number>()
async function refreshSampling() {
  const requestId = ++samplingRequest
  samplingError.value = ''
  if (selectedEngine.value !== 'ecloudgen' || sampling.value.ecloudgen.num_clouds !== '' || !Number.isInteger(Number(quantity.value)) || Number(quantity.value) < 1) { samplingLoading.value = false; return }
  samplingLoading.value = true
  try {
    const { data } = await getEcloudSamplingPlan(Number(quantity.value), sampling.value.ecloudgen)
    if (requestId !== samplingRequest) return
    cloudEstimate.value = data.num_clouds
  } catch (error: any) {
    if (requestId === samplingRequest) samplingError.value = displayErrorMessage(error)
  } finally { if (requestId === samplingRequest) samplingLoading.value = false }
}
watch(() => [selectedEngine.value, quantity.value, sampling.value.ecloudgen.num_clouds,
  sampling.value.ecloudgen.decodes_per_cloud, sampling.value.ecloudgen.noise, sampling.value.ecloudgen.inv_temp],
  () => { void refreshSampling() })
if (selectedEngine.value === 'ecloudgen' && !restoredSettings.num_clouds) void refreshSampling()

function currentState() {
  return {
    engine: selectedEngine.value,
    quantity: quantity.value,
    optimizer: clone(optimizer.value),
    objectives: clone(objectives.value),
    sampling: clone(sampling.value[selectedEngine.value]),
  }
}

const sourceState = {
  engine: sourceEngine,
  quantity: sourceGeneration[quantityField(sourceEngine)] ?? (sourceEngine === 'epso' ? 100 : 1000),
  optimizer: clone(sourceGeneration.optimizer || (sourceEngine === 'epso' ? defaultOptimizer : {})),
  objectives: clone(sourceGeneration.objectives || (sourceEngine === 'epso' ? defaultObjectives : [])),
  sampling: clone(sampling.value[sourceEngine]),
}
const sourceSnapshot = JSON.stringify(sourceState)

function draftSnapshot(): DraftState {
  const engine = selectedEngine.value
  const generation: Record<string, any> = { engine, ...effectiveGenerationSampling(engine, Number(quantity.value), sampling.value[engine] || {}), [quantityField(engine)]: quantity.value }
  if (engine === 'delete') generation.edit = { edit_spec_id: props.editSpec, mode: props.editMode }
  if (engine === 'epso') {
    generation.optimizer = clone(optimizer.value)
    generation.objectives = clone(objectives.value)
  }
  const plan = clone(sourcePlan)
  plan.protein_context_id = plan.protein_context_id || payload.protein_context_id
  plan.generator = engine
  plan.template = `${engine}_tarpass_v1`
  plan.generation = generation
  plan.postprocessing = clone(sourcePlan.postprocessing || { enabled: true, prefilters: defaultPrefilters() })
  plan.selection = { sort_by: null, descending: false, top_k: null }
  const seedSource = restored.seed_source ?? restored.plan?.seed_source ?? sourcePlan.seed_source
  if (seedSource !== undefined) plan.seed_source = clone(seedSource)
  return {
    version: payload.plan_version,
    input_revision: inputRevision,
    protein_context_id: plan.protein_context_id,
    engine,
    generator: engine,
    template: plan.template,
    ...(seedSource === undefined ? {} : { seed_source: clone(seedSource) }),
    quantity: quantity.value,
    optimizer: clone(optimizer.value),
    objectives: clone(objectives.value),
    postprocessing: { enabled: true, prefilters: defaultPrefilters() },
    selection: { sort_by: null, descending: false, top_k: null },
    generation,
    plan,
  }
}

function onChange() {
  emit('dirty', JSON.stringify(currentState()) !== sourceSnapshot)
  emit('draft', draftSnapshot())
}

watch([selectedEngine, quantity, optimizer, objectives, sampling], onChange, { deep: true, immediate: true })
watch(() => [props.editSpec, props.editMode], onChange)
watch(selectedEngine, (engine, previous) => {
  if (engine === 'epso' && previous !== 'epso') {
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
  if (samplingLoading.value || samplingError.value || !props.generators[selectedEngine.value]?.enabled) return false
  if (selectedEngine.value === 'delete' && !props.editSpec) return false
  const count = Number(quantity.value)
  if (!Number.isInteger(count) || count < 1 || count > moleculeLimit.value) return false
  if (selectedEngine.value === 'epso') {
    if (!Number.isInteger(Number(optimizer.value.num_particles)) || Number(optimizer.value.num_particles) < 1 || Number(optimizer.value.num_particles) > 1000) return false
    if (!Number.isInteger(Number(optimizer.value.num_steps)) || Number(optimizer.value.num_steps) < 1 || Number(optimizer.value.num_steps) > 1000) return false
    if (!Number.isInteger(Number(optimizer.value.seed)) || Number(optimizer.value.seed) < 0 || Number(optimizer.value.seed) > 4294967295) return false
    if (Number(optimizer.value.num_particles) * (Number(optimizer.value.num_steps) + 1) > 20000 || Number(optimizer.value.num_swarms) !== 1) return false
    if (!objectives.value.length || new Set(objectives.value.map(item => item.metric)).size !== objectives.value.length || objectives.value.some(item => !objectiveValid(item))) return false
  }
  return true
})

watch(valid, value => emit('valid', Boolean(value)), { immediate: true })
defineExpose({ validate: () => Boolean(valid.value) && advanced.value?.validate() !== false })

function save() {
  if (!valid.value || advanced.value?.validate() === false) return
  const patch: Record<string, any> = {}
  const generationPatch: Record<string, any> = effectiveGenerationSampling(selectedEngine.value, Number(quantity.value), sampling.value[selectedEngine.value] || {})
  const engine = selectedEngine.value
  const field = quantityField(engine)
  if (engine !== sourceEngine) {
    patch.generator = engine
    patch.template = `${engine}_tarpass_v1`
    patch.generation = { engine, ...effectiveGenerationSampling(engine, Number(quantity.value), sampling.value[engine] || {}), [field]: quantity.value,
      ...(engine === 'delete' ? { edit: { edit_spec_id: props.editSpec, mode: props.editMode } } : {}),
      ...(engine === 'epso' ? { optimizer: clone(optimizer.value), objectives: clone(objectives.value) } : {}) }
  } else {
    if (quantity.value !== sourceGeneration[field]) generationPatch[field] = quantity.value
    if (engine === 'ecloudgen' && sampling.value.ecloudgen.num_clouds === '' && sourceGeneration.num_clouds != null) generationPatch.num_clouds = null
    if (engine === 'delete' && (props.editSpec !== sourceGeneration.edit?.edit_spec_id || props.editMode !== sourceGeneration.edit?.mode)) generationPatch.edit = { edit_spec_id: props.editSpec, mode: props.editMode }
    if (engine === 'epso') {
      if (JSON.stringify(optimizer.value) !== JSON.stringify(sourceGeneration.optimizer || {})) generationPatch.optimizer = clone(optimizer.value)
      if (JSON.stringify(objectives.value) !== JSON.stringify(sourceGeneration.objectives || [])) generationPatch.objectives = clone(objectives.value)
    }
    if (Object.keys(generationPatch).length) patch.generation = generationPatch
  }
  emit('save', patch, inputRevision)
}
</script>
