<template>
  <div class="flex h-full min-h-0 flex-col gap-2">
    <p v-if="loading" role="status" class="p-4 text-sm">{{ $t('platform.loading3dStructure') }}</p>
    <p v-if="error" role="alert" class="p-4 text-sm text-red-700">{{ error }}</p>
    <template v-if="initialized">
      <div class="flex flex-wrap items-center gap-4 text-sm">
        <label v-if="records.length > 1">{{ $t('platform.bindingConformer') }}
          <select v-model.number="recordIndex" class="border p-1" :disabled="loading"><option v-for="(record, index) in records" :key="record.source_index" :value="index">{{ record.source_index + 1 }}</option></select>
        </label>
        <button v-if="records.length < conformerTotal" :disabled="loading" class="text-blue-700" @click="moreConformers">{{ $t('platform.next') }}</button>
        <label v-if="!ligandOnly && context?.reference"><input v-model="showReference" :disabled="loading" type="checkbox"> {{ $t('platform.bindingReference') }}</label>
        <span v-if="protein || (pose && !ligandOnly)">{{ $t(pose ? 'platform.poseOverlayLegend' : 'platform.bindingLegend') }}</span>
      </div>
      <p v-if="warning" role="status" class="text-sm text-amber-800">{{ warning }}</p>
      <p v-if="renderError" role="alert" class="text-sm text-red-700">{{ renderError }}</p>
      <div v-show="!loading && !error" class="flex min-h-0 flex-1 flex-col gap-3 sm:flex-row">
        <drugflow_molstar ref="viewer" class="min-w-0 flex-1" :if_sequence_panel="false" :init_show_tree="false" :ligand_only="ligandOnly" :interaction_2d="!ligandOnly && pose && moleculeId ? interaction2d : null" @request-2d="request2d" @residue-select="focusResidue" @init-complete="viewerReady = true; renderScene()" />
        <aside v-if="pose && !ligandOnly" class="max-h-40 shrink-0 overflow-y-auto border-t pt-2 text-sm sm:max-h-none sm:w-56 sm:border-l sm:border-t-0 sm:pl-3 sm:pt-0">
          <h3 class="mb-2 font-medium">{{ $t('platform.bindingPlip') }}</h3>
          <p v-if="!hasInteractions">{{ $t('platform.notCalculatedUnavailable') }}<span v-if="interactionError">: {{ interactionError }}</span></p>
          <p v-else-if="!interactionGroups.length">{{ $t('platform.bindingNoInteractions') }}</p>
          <section v-for="[type, residues] in interactionGroups" :key="type" class="mb-3">
            <h4 class="font-medium">{{ type }}</h4>
            <button v-for="residue in residues" :key="residue" class="mr-2 text-blue-700 hover:underline disabled:text-slate-400" :disabled="!protein || !sceneReady" @click="focusResidue(residue)">{{ residueLabel(residue) }}</button>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { translate } from '@/i18n'
import request from '@/utils/request'
import drugflow_molstar from '@/components/molecule/drugflow_molstar.vue'
import { displayErrorMessage } from '@/utils/requestError'

const props = withDefaults(defineProps<{
  jobId: string; resultId?: string; smiles?: string; moleculeId?: string
  pose?: 'original' | 'docked'; visible?: boolean; compare?: boolean; ligandOnly?: boolean
  interactions?: Record<string, string[]>; interactionError?: string
}>(), { visible: true })
const emit = defineEmits<{ availability: [value: { original?: boolean; docked?: boolean }] }>()
type ContextFile = { format: string } & ({ dataset_id: string; file_id: string } | { job_id: string; task_code: string; key: string })
const viewer = ref<any>(null)
const initialized = ref(false), viewerReady = ref(false)
const loading = ref(true), sceneReady = ref(false), showReference = ref(false)
const error = ref(''), warning = ref(''), renderError = ref('')
const protein = ref(''), block = ref('')
const otherBlock = ref('')
let otherVersion = '', otherIndex = -1, loadedMolecule = ''
const loadedPoses = new Map<string, string>()
let availabilityIdentity = ''
const invalidPoses = new Set<string>()
const context = ref<{ protein: ContextFile | null; reference: ContextFile | null } | null>(null)
const records = ref<Array<{ source_index: number }>>([])
const recordIndex = ref(0), conformerTotal = ref(0)
const selected = computed(() => records.value[recordIndex.value])
const revision = ref(0)
const interaction2d = ref<{ status: string; diagram?: any; error?: string }>({ status: 'not_requested' })
let pollTimer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
let active = true, contextJob = '', selectionIdentity = '', artifactVersion = '', loadedProtein = '', loadedCandidate = '', loadedReference = ''
let sceneWork = Promise.resolve()
const texts = new Map<string, string>()
let textBytes = 0
let account = localStorage.getItem('cs_user_info')
function clearTexts() { texts.clear(); textBytes = 0 }
window.addEventListener('genova:auth-cleared', clearTexts)
async function textFor(url: string, params: Record<string, unknown>, version = '') {
  const owner = localStorage.getItem('cs_user_info')
  if (owner !== account) { clearTexts(); account = owner }
  const key = JSON.stringify([url, params, version])
  const cached = texts.get(key)
  if (cached !== undefined) { texts.delete(key); texts.set(key, cached); return cached }
  const response = await request.get(url, { params, responseType: 'text', signal: controller?.signal })
  const text = response.data as string
  const bytes = 2 * (key.length + text.length)
  if (bytes <= 32 * 1024 * 1024 && active && owner === localStorage.getItem('cs_user_info')) {
    texts.set(key, text); textBytes += bytes
    while (textBytes > 32 * 1024 * 1024) {
      const [first, value] = texts.entries().next().value!
      texts.delete(first); textBytes -= 2 * (first.length + value.length)
    }
  }
  return text
}
const datasetText = (file: ContextFile) => 'job_id' in file
  ? textFor(`/api/v1/jobs/${file.job_id}/artifact`, { task_code: file.task_code, key: file.key })
  : textFor(`/api/v1/datasets/${file.dataset_id}/download`, { file_id: file.file_id })
const hasInteractions = computed(() => !!interaction2d.value.diagram || !!props.interactions)
const interactionGroups = computed(() => {
  if (!interaction2d.value.diagram) return Object.entries(props.interactions || {}).filter(([, residues]) => residues.length)
  const groups: Record<string, string[]> = {}
  for (const interaction of interaction2d.value.diagram.interactions) {
    const residues = groups[interaction.type] ||= []
    if (!residues.includes(interaction.residue_id)) residues.push(interaction.residue_id)
  }
  return Object.entries(groups)
})
async function request2d(retry = false) {
  if (props.ligandOnly || !props.visible || !props.pose || !props.moleculeId || (!retry && !['not_requested', 'failed'].includes(interaction2d.value.status))) return
  const current = revision.value
  const url = `/api/v1/jobs/${props.jobId}/postprocessing/interactions-2d`
  const params = { molecule_id: props.moleculeId, pose: props.pose }
  const stale = () => !active || !props.visible || current !== revision.value
  clearTimeout(pollTimer)
  interaction2d.value = { status: 'pending' }
  const fetchStatus = async (create: boolean) => {
    try {
      const response = create ? await request.post(url, params) : await request.get(url, { params })
      if (stale()) return
      interaction2d.value = response.data
      if (['pending', 'queued', 'running'].includes(response.data.status)) pollTimer = setTimeout(() => { void fetchStatus(false) }, 1500)
      else if (!['succeeded', 'failed'].includes(response.data.status)) interaction2d.value = { status: 'failed', error: translate('platform.binding2dInputChanged') }
    } catch (exc: any) {
      if (!stale()) interaction2d.value = { status: 'failed', error: displayErrorMessage(exc, translate('platform.binding2dFailed')) }
    }
  }
  await fetchStatus(true)
}
const residueLabel = (key: string) => { const [chain, name, number, insertion] = key.split('|'); return `${chain || '∅'}:${name}${number}${insertion || ''}` }
function focusResidue(key: string) {
  const [chain_id, residue_name, number, insertion_code] = key.split('|')
  viewer.value?.highlight_residues([{ chain_id, residue_name, residue_number: Number(number), insertion_code }], true)
}
const manifestParams = () => ({ result_id: props.resultId, molecule_id: props.moleculeId, pose: props.pose || 'generated', limit: 100 })
async function moreConformers() {
  const current = revision.value
  loading.value = true
  try {
    const response = await request.get(`/api/v1/jobs/${props.jobId}/structures`, { params: { ...manifestParams(), offset: records.value.length }, signal: controller?.signal })
    if (current === revision.value) records.value.push(...response.data.records)
  } catch (exc: any) { if (current === revision.value) error.value = displayErrorMessage(exc) }
  finally { if (current === revision.value) loading.value = false }
}
watch(() => [props.jobId, props.resultId, props.moleculeId, props.pose, props.visible, props.compare, props.ligandOnly], async () => {
  const current = ++revision.value
  controller?.abort(); controller = new AbortController()
  clearTimeout(pollTimer)
  if (!props.visible) return
  loading.value = true; sceneReady.value = false; error.value = ''; renderError.value = ''; warning.value = ''
  interaction2d.value = { status: 'not_requested' }
  const stale = () => !active || current !== revision.value
  try {
    const identity = JSON.stringify([props.jobId, props.resultId, props.moleculeId, props.pose])
    const moleculeIdentity = JSON.stringify([props.jobId, props.moleculeId])
    if (availabilityIdentity !== moleculeIdentity) { invalidPoses.clear(); availabilityIdentity = moleculeIdentity }
    let manifest
    otherBlock.value = ''
    if (props.pose) {
      const poses = ['original', 'docked'] as const
      const manifests = await Promise.allSettled(poses.map(pose => request.get(`/api/v1/jobs/${props.jobId}/structures`, { params: { ...manifestParams(), pose }, signal: controller?.signal })))
      if (stale()) return
      const available: { original?: boolean; docked?: boolean } = {}
      for (const [i, result] of manifests.entries()) available[poses[i]] = result.status === 'fulfilled' && result.value.data.records.length > 0 && !invalidPoses.has(poses[i])
      emit('availability', available)
      const selectedManifest = manifests[poses.indexOf(props.pose)]
      if (selectedManifest.status === 'rejected') throw selectedManifest.reason
      manifest = selectedManifest.value
      if (!available[props.pose]) throw new Error(translate('platform.poseUnavailable', { pose: props.pose }))
      const otherPose = props.pose === 'original' ? 'docked' : 'original'
      if (!available[otherPose]) warning.value = translate('platform.poseUnavailable', { pose: otherPose })
      if (props.compare) {
        const other = manifests[poses.indexOf(otherPose)]
        if (!available[otherPose] || other.status !== 'fulfilled') throw new Error(translate('platform.poseUnavailable', { pose: otherPose }))
        const sourceIndex = other.value.data.records[0].source_index
        const sourceVersion = JSON.stringify(other.value.data.version)
        try {
          const text = await textFor(`/api/v1/jobs/${props.jobId}/structures/${sourceIndex}`, { pose: otherPose }, sourceVersion)
          if (stale()) return
          otherBlock.value = text; otherIndex = sourceIndex; otherVersion = sourceVersion
        } catch (exc: any) {
          if (!stale() && exc?.response?.status === 409) { invalidPoses.add(otherPose); emit('availability', { ...available, [otherPose]: false }) }
          throw exc
        }
      }
    } else {
      manifest = await request.get(`/api/v1/jobs/${props.jobId}/structures`, { params: manifestParams(), signal: controller.signal })
      if (stale()) return
    }
    const version = JSON.stringify(manifest.data.version)
    if (identity !== selectionIdentity || version !== artifactVersion) {
      records.value = manifest.data.records; recordIndex.value = 0
    }
    selectionIdentity = identity; conformerTotal.value = manifest.data.total; artifactVersion = version
    if (!records.value.length) throw new Error(translate('platform.noAvailablePoseForThisRecord'))
    if (!props.ligandOnly && contextJob !== props.jobId) {
      const response = await request.get(`/api/v1/jobs/${props.jobId}/structures/context`, { signal: controller.signal })
      if (stale()) return
      context.value = response.data; contextJob = props.jobId
      showReference.value = false
    }
    try {
      const text = !props.ligandOnly && context.value?.protein ? await datasetText(context.value.protein) : ''
      if (stale()) return
      protein.value = text
    }
    catch (exc) { if (stale()) return; protein.value = '' }
    if (stale()) return
    if (!props.ligandOnly && !protein.value) warning.value = translate('platform.bindingReceptorUnavailable')
    await loadConformer(current)
  } catch (exc: any) {
    if (!stale()) { error.value = displayErrorMessage(exc, translate('platform.failedToLoadGeneratedSdf')); loading.value = false }
  }
}, { immediate: true })
async function loadConformer(current = revision.value) {
  if (!selected.value || !props.visible) return
  loading.value = true; sceneReady.value = false; error.value = ''
  const index = selected.value.source_index
  try {
    const value = await textFor(`/api/v1/jobs/${props.jobId}/structures/${index}`, { pose: props.pose || 'generated' }, artifactVersion)
    if (!active || current !== revision.value || index !== selected.value?.source_index) return
    block.value = value; initialized.value = true; loading.value = false
    await nextTick()
    await renderScene()
  } catch (exc: any) {
    if (active && current === revision.value) {
      if (props.pose && exc?.response?.status === 409) { invalidPoses.add(props.pose); emit('availability', { [props.pose]: false }) }
      error.value = displayErrorMessage(exc); loading.value = false
    }
  }
}
function renderScene() {
  const current = revision.value, index = selected.value?.source_index
  const stale = () => !active || !props.visible || current !== revision.value || index !== selected.value?.source_index
  sceneWork = sceneWork.then(async () => {
    const target = viewer.value
    if (stale() || !target || !viewerReady.value || !block.value) return
    sceneReady.value = false; renderError.value = ''
    try {
      const proteinKey = protein.value ? JSON.stringify(context.value?.protein) : ''
      const moleculeKey = JSON.stringify([props.jobId, props.resultId, props.moleculeId, props.ligandOnly])
      const newMolecule = loadedMolecule !== moleculeKey
      if (loadedProtein !== proteinKey) {
        if (protein.value) await target.load_structure({ render_type: 'default', render_id: '0', format: ['cif', 'mmcif'].includes(context.value?.protein?.format || '') ? 'mmcif' : 'pdb', input: protein.value, if_clean: true, only_display: true })
        else await target.clear_structure()
        loadedProtein = proteinKey; loadedCandidate = ''; loadedReference = ''; loadedPoses.clear()
      }
      if (stale()) return
      if (newMolecule) {
        for (const id of loadedPoses.keys()) await target.load_overlay('', 'sdf', id)
        loadedPoses.clear()
      }
      if (props.pose) {
        const otherPose = props.pose === 'original' ? 'docked' : 'original'
        const inputs = [{ pose: props.pose, text: block.value, index, version: artifactVersion }]
        if (props.compare) inputs.push({ pose: otherPose, text: otherBlock.value, index: otherIndex, version: otherVersion })
        for (const input of inputs) {
          if (stale()) return
          const key = JSON.stringify([moleculeKey, input.index, input.version])
          if (loadedPoses.get(input.pose) !== key) {
            await target.load_overlay(input.text, 'sdf', input.pose, input.pose === 'original' ? 0x06b6d4 : 0xa855f7, !props.ligandOnly, newMolecule && input.pose === props.pose)
            loadedPoses.set(input.pose, key)
          }
        }
        if (stale()) return
        for (const id of ['original', 'docked']) await target.set_overlay_visible(id, props.compare || id === props.pose)
      } else {
        const candidateKey = JSON.stringify([props.jobId, index, artifactVersion])
        if (loadedCandidate !== candidateKey) {
          await target.load_overlay(block.value, 'sdf', 'candidate', 0xffffff, true)
          loadedCandidate = candidateKey
        }
      }
      loadedMolecule = moleculeKey
      if (stale()) return
      await renderReference()
      if (!stale()) sceneReady.value = true
    } catch (exc: any) { if (!stale()) renderError.value = displayErrorMessage(exc, translate('platform.failedToRenderThe3dStructure')) }
  })
  return sceneWork
}
async function renderReference() {
  const target = viewer.value, file = context.value?.reference, current = revision.value
  if (!target || !viewerReady.value) return
  if (!props.ligandOnly && showReference.value && file) {
    const key = JSON.stringify(file)
    if (loadedReference !== key) {
      try {
        const value = await datasetText(file)
        if (!active || current !== revision.value) return
        await target.load_overlay(value, file.format, 'reference', 0xf59e0b)
        loadedReference = key
      } catch { warning.value = translate('platform.bindingReferenceUnavailable'); return }
    }
  }
  await target.set_overlay_visible('reference', !props.ligandOnly && showReference.value && !!file)
}
watch(recordIndex, () => { if (!loading.value) { revision.value++; void loadConformer() } })
watch(showReference, () => { void renderScene() })
onBeforeUnmount(() => { active = false; revision.value++; controller?.abort(); clearTimeout(pollTimer); clearTexts(); window.removeEventListener('genova:auth-cleared', clearTexts) })
</script>
