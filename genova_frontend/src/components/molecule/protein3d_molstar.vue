<template>
  <div 
    id="protein_frame"
    class="relative" :class="compact ? 'min-h-0 min-w-0' : 'min-w-[200px] min-h-[400px]'"
  >
    <div class="relative h-full w-full" :class="compact ? 'min-h-0 min-w-0 overflow-hidden' : 'min-h-[500px] min-w-[540px] overflow-visible'">
      <component :is="DrugflowMolstar" v-if="DrugflowMolstar" ref="molstar_ref" @init-complete="onChildInit" />
    </div>

    <!-- Cover overlay with title and icon -->
    <div v-if="if_cover" class="absolute inset-0 z-[50] flex flex-col justify-start bg-white">
      <!-- Title bar -->
      <div v-if="title" class="flex-shrink-0 p-4 pb-0">
        <h1 class="text-sm font-semibold text-slate-900">{{ title }}</h1>
      </div>
      
      <!-- Center content -->
      <div class="flex items-center justify-center p-4">
        <div class="w-full border border-dashed bg-slate-50 flex items-center justify-center">
          <div class="text-center px-6 py-8">
            <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-white shadow-sm">
              <Atom class="h-6 w-6 text-slate-400" />
            </div>
            <div class="text-slate-700 text-sm font-medium mb-1">{{ $t('platform.noProteinStructureData') }}</div>
            <div class="text-slate-500 text-xs">{{ $t('platform.loadAProteinFromTheLeftPanelToPreviewItHere') }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Error overlay -->
    <div v-if="if_err" class="absolute inset-0 z-[3] flex items-center justify-center bg-white">
      <div class="flex flex-col items-center justify-center space-y-4">
        <AlertCircle class="w-8 h-8 text-violet-500" />
        <p class="max-w-md break-words text-sm text-violet-500">{{ viewerImportFailed ? $t('platform.viewerLibraryUnavailable') : $t(viewerErrorKey || 'platform.previewErrors.load') }}</p>
      </div>
    </div>

    <!-- Loading overlay -->
    <div v-if="is_loading || context_loading" class="absolute inset-0 z-[2] flex items-center justify-center bg-white bg-opacity-80">
      <div class="flex flex-col items-center justify-center space-y-4">
        <Loader2 class="w-8 h-8 animate-spin text-violet-500" />
        <p class="text-sm text-violet-500">{{ loading_text || $t('platform.loading') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { translate } from '@/i18n'

import { ref, shallowRef, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Atom, AlertCircle, Loader2 } from 'lucide-vue-next'
import { parse_ligand_string, change_pocket_to_xyz, calc_iou, parse_pdb_info, search_centry } from '@/components/molecule/pdb_parser.js'
import { downloadBackendDataset, getBackendDataset } from '@/api/genovaBackend'
import { getPreparedReceptor } from '@/api/proteinContext'
import { previewCif } from '@/utils/structurePreview'
import { probeFileHead, UPLOAD_PROBE_BYTES } from '@/utils/uploadFileCheck'

const DrugflowMolstar = shallowRef(null)
const viewerImportFailed = ref(false)
const viewerError = ref('')
// The overlay shows a localized message for the failure kind; the raw error stays in viewerError and the console.
const viewerErrorKey = ref('')
let Bond, StructureElement, StructureProperties, ButtonsType
let disposed = false

const { t } = useI18n()

const props = defineProps({
  compact: { type: Boolean, default: false },
  title: { type: String }, // Optional title prop
  box_x: { type: Number },
  box_y: { type: Number },
  box_z: { type: Number },
  l1: { type: Number },
  l2: { type: Number },
  l3: { type: Number },
  if_show_box: { type: Boolean },
  ligand_select: { type: String },
  if_pocket: { type: Boolean, default: false },
  if_show_contact: { type: Boolean, default: false },
  always_show_ligands: { type: Boolean, default: false },
  show_ligands_console: { type: Boolean, default: true },
  surface_opacity: { type: Number, default: 0.3 },
  if_can_change_ligand_type: { type: Boolean, default: false },
  if_changed_box: { type: Boolean, default: false },
  if_click_event: { type: Boolean, default: true },
  pocket_check: { type: Boolean, default: false },
  wait_molstar_init: { type: Boolean, default: false },
  selectionMode: { type: String, default: 'none' },
  selectedResidues: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'update:box_x',
  'update:box_y', 
  'update:box_z',
  'update:ligand_select',
  'update:if_changed_box',
  'iou_func',
  'residue-click',
  'structure-ready',
  'residue-toggle',
  'ligand-select',
  'point-pick',
])

// Reactive state
const if_cover = ref(true)
const if_err = ref(false)
const is_loading = ref(false)
const context_loading = ref(false)
const loading_text = ref('')
const chain_content = ref([])
const ligand_content = ref([])
const box_params = ref({
  x: 100,
  y: 100,
  z: 100
})
const ligand_names_list = ref([])
const molstar_ref = ref(null)
const pdb_string = ref('')
const shape_selector = ref(null)
const is_initialized = ref(false)
const mouse_listener_registered = ref(false)
// False when the 3D view could not start (for example, no graphics support in this browser).
let viewerUsable = true
const onChildInit = (ready = true) => {
  viewerUsable = ready
  is_initialized.value = true
  registerMouseEvent()
}

// Methods
// `untrusted`: the text is a user's file as is (not built by the app), so its content is checked before parsing.
const loadStructure = async (pdb_string_param, format = 'pdb', peptide_check=false, untrusted=false) => {
  open_loading()
  if_err.value = false
  viewerError.value = ''
  viewerErrorKey.value = ''
  viewerImportFailed.value = false

  if (!DrugflowMolstar.value) {
    try {
      const [viewer, structure, input] = await Promise.all([
        import('@/components/molecule/drugflow_molstar.vue'),
        import('molstar/lib/mol-model/structure'),
        import('molstar/lib/mol-util/input/input-observer'),
      ])
      if (disposed) return
      ;({ Bond, StructureElement, StructureProperties } = structure)
      ;({ ButtonsType } = input)
      DrugflowMolstar.value = viewer.default
      await nextTick()
    } catch (error) {
      viewerImportFailed.value = true
      viewerError.value = error.message
      close_loading(true)
      // Same localized text as the overlay; the raw error stays in viewerError.
      throw new Error(translate('platform.viewerLibraryUnavailable'))
    }
  }
  if (disposed) return

  if_err.value = false
  pdb_string.value = pdb_string_param
  
  // Ensure viewer is initialized before loading
  const waitFor = async (predicate, timeoutMs = 15000, intervalMs = 50) => {
    const start = Date.now()
    while (!predicate()) {
      if (disposed || Date.now() - start > timeoutMs) return false
      await new Promise(r => setTimeout(r, intervalMs))
    }
    return true
  }
  const ready = await waitFor(() => is_initialized.value && !!molstar_ref.value?.load_structure)
  if (!ready) {
    viewerError.value = 'Protein viewer initialization timed out'
    viewerErrorKey.value = 'platform.previewErrors.timeout'
    close_loading(true)
    if (disposed) return
    // Callers may show this message to the user, so it carries localized text.
    throw new Error(translate('platform.previewErrors.timeout'))
  }
  if (!viewerUsable) {
    viewerError.value = 'Protein viewer could not start'
    viewerErrorKey.value = 'platform.previewErrors.unavailable'
    close_loading(true)
    throw new Error(translate('platform.previewErrors.unavailable'))
  }
  // A file that is not a structure of this format never reaches the parser, which only fails on it with a console error.
  const head = String(pdb_string_param ?? '').slice(0, UPLOAD_PROBE_BYTES)
  if (untrusted && probeFileHead(new TextEncoder().encode(head), format === 'mmcif' ? 'cif' : 'pdb', head.length === String(pdb_string_param ?? '').length)) {
    viewerError.value = 'Not a readable structure'
    viewerErrorKey.value = 'platform.previewErrors.content'
    close_loading(true)
    throw new Error(translate('platform.previewErrors.content'))
  }
  // load new data
  let info_dict
  try {
    ligand_names_list.value = parse_ligand_string(pdb_string_param)
    info_dict = parse_pdb_info(pdb_string_param, peptide_check)
    chain_content.value = info_dict['chain']
    ligand_content.value = info_dict['ligand']

    if (ligand_names_list.value.length === 0 && props.pocket_check) {
      emit('iou_func', true)
    }
  
    const init_params = {
      'url': undefined,
      'format': format,
      'is_binary': false,
      'input': pdb_string_param,
      'if_render': true,
      'render_type': 'default',
      'render_id': '0',
      'if_clean': true,
      'pdb_name': 'ref',
      'only_display': true
    }
    await shapeUpdate
    await molstar_ref.value.load_structure(init_params)
    shape_selector.value = null
  } catch (err) {
    viewerError.value = err.message
    viewerErrorKey.value = 'platform.previewErrors.content'
    console.warn('Preview failed:', err)
    close_loading(true)
    throw err
  } 
  
  combine_ligand_info()
  close_loading()
  if (props.selectionMode === 'residue') highlightResidues(props.selectedResidues)
  emit('structure-ready', getStructureInfo())
  if (peptide_check) {
    return { protein_content: chain_content.value, protein_lig_content: ligand_content.value, peptide_content: info_dict['peptide_chains'] }
  } else {
    return { protein_content: chain_content.value, protein_lig_content: ligand_content.value }
  }
}

let contextRequest = 0
const loadContext = async (context, preparedReceptor) => {
  const request = ++contextRequest
  context_loading.value = true
  open_loading()
  if_err.value = false
  viewerError.value = ''
  viewerErrorKey.value = ''
  try {
    const proteinIdentity = context.artifacts.effective_receptor
    const referencePromise = (async () => {
      const reference = context.generation_reference
      if (!reference) return null
      if (reference.kind === 'source_component') {
        const prepared = preparedReceptor || (await getPreparedReceptor(context.prepared_receptor_id)).data
        const component = prepared.component_manifest.components.find(item => item.component_id === reference.source_component_id)
        if (!component) throw new Error('Context reference component is unavailable')
        const atoms = component.atoms.filter(atom => !atom.altloc || !prepared.edits.altloc_choices?.[atom.residue_id] || prepared.edits.altloc_choices[atom.residue_id] === atom.altloc)
        return { input: previewCif([{ ...component, atoms }]), format: 'mmcif' }
      }
      const identity = reference.structure
      const [response, { data: dataset }] = await Promise.all([
        downloadBackendDataset(identity.dataset_id, identity.file_id),
        getBackendDataset(identity.dataset_id),
      ])
      const file = dataset.files.find(item => item.id === identity.file_id)
      return { input: await response.data.text(), format: file.original_filename.split('.').pop().toLowerCase() }
    })()
    const [protein, reference] = await Promise.all([
      downloadBackendDataset(proteinIdentity.dataset_id, proteinIdentity.file_id).then(response => response.data.text()),
      referencePromise,
    ])
    if (request !== contextRequest || disposed) return
    await loadStructure(protein, /^\s*data_/m.test(protein) ? 'mmcif' : 'pdb')
    if (request !== contextRequest || disposed) return
    if (reference) await overlayStructure(reference.input, reference.format)
    if (request !== contextRequest || disposed) return
    const box = context.site.box
    await add_shape(...box.center, ...box.size, false)
  } catch (error) {
    if (request === contextRequest && !disposed) {
      viewerError.value = error.message
      close_loading(true)
    }
    throw error
  } finally {
    if (request === contextRequest) {
      context_loading.value = false
      close_loading()
    }
  }
}

const overlayStructure = async (input, format = 'sdf', id = 'reference') => {
  return await molstar_ref.value?.load_overlay(input, format, id)
}

const combine_ligand_info = () => {
  const ligands = molstar_ref.value.get_pdb_info().ligand
  for (let i = 0; i < ligand_content.value.length; i++) {
    for (let j = 0; j < ligands.length; j++) {
      const chain_name = ligands[j].auth_asym_id
      const residue_id = ligands[j].auth_residue_number
      if (ligand_content.value[i].residue_id == residue_id && ligand_content.value[i].chain_name === chain_name) {
        ligand_content.value[i].auth_asym_id = ligands[j].auth_asym_id
        ligand_content.value[i].auth_residue_number = ligands[j].auth_residue_number
        break
      }
    }
  }
  console.log('ligand_content', ligand_content.value)
}

let shapeUpdate = Promise.resolve()
let shapeVersion = 0
const add_shape = (x, y, z, l1, l2, l3, flag = true) => {
  if (!is_initialized.value) return
  const version = ++shapeVersion
  const params = {x: Number(x), y: Number(y), z: Number(z), l1: Number(l1), l2: Number(l2), l3: Number(l3)}
  const update = shapeUpdate.then(async () => {
    if (version !== shapeVersion) return
    if (shape_selector.value) {
      await molstar_ref.value.remove_shape(shape_selector.value)
      shape_selector.value = null
    }
    shape_selector.value = await molstar_ref.value.add_shape(params)
    if (version !== shapeVersion) return
    emit('update:box_x', x)
    emit('update:box_y', y)
    emit('update:box_z', z)
    if (flag) emit('update:ligand_select', 'default')
  })
  shapeUpdate = update.catch(() => {})
  return update
}

const get_pdb_info = () => {
  return molstar_ref.value.get_pdb_info()
}

const remove_shape = () => {
  if (shape_selector.value) {
    molstar_ref.value.remove_shape(shape_selector.value)
  }
}

const change_chain = async (chain_name, if_show, chain_id) => {
  molstar_ref.value.select_none()
  if (!if_show) {
    await molstar_ref.value.quick_select({'auth_asym_id': chain_name, 'group_PDB': 'ATOM'})
    await molstar_ref.value.hide_selection()
  } else {
    await molstar_ref.value.quick_select({'auth_asym_id': chain_name, 'group_PDB': 'ATOM'})
    await molstar_ref.value.show_selection('chain', [{'auth_asym_id': chain_name, 'group_PDB': 'ATOM'}])
  }
}

const calc_coords_info = (ligand_atoms_list) => {
  let max_x = -1000
  let max_y = -1000
  let max_z = -1000
  let min_x = 1000
  let min_y = 1000
  let min_z = 1000
  
  for (let i = 0; i < ligand_atoms_list.length; i++) {
    const atom = ligand_atoms_list[i]
    if (Number(atom[0]) > max_x) {
      max_x = atom[0]
    }
    if (Number(atom[1]) > max_y) {
      max_y = atom[1]
    }
    if (Number(atom[2]) > max_z) {
      max_z = atom[2]
    }
    if (Number(atom[0]) < min_x) {
      min_x = atom[0]
    }
    if (Number(atom[1]) < min_y) {
      min_y = atom[1]
    }
    if (Number(atom[2]) < min_z) {
      min_z = atom[2]
    }
  }
  
  return {
    max_x,
    max_y,
    max_z,
    min_x,
    min_y,
    min_z
  }
}

const calc_ligand_box = (ligand_dict, expand = 10) => {
  // Draw pocket view
  console.log('ligand_dict', ligand_dict)
  if (!ligand_dict) {
    const centry = search_centry(pdb_string.value)
    return {
      x: centry[0],
      y: centry[1],
      z: centry[2],
      l1: 25,
      l2: 25,
      l3: 25
    }
  }
  
  // get ligand coord info
  const coords_info = calc_coords_info(ligand_dict.coords)
  let l1 = coords_info.max_x - coords_info.min_x + expand
  let l2 = coords_info.max_y - coords_info.min_y + expand
  let l3 = coords_info.max_z - coords_info.min_z + expand
  
  return {
    x: (coords_info.max_x + coords_info.min_x) / 2,
    y: (coords_info.max_y + coords_info.min_y) / 2,
    z: (coords_info.max_z + coords_info.min_z) / 2,
    l1,
    l2,
    l3
  }
}

const select_and_focus = (d) => {
  const data = change_data_name(d)
  molstar_ref.value.select_none()
  if (data.struct_asym_id != undefined) {
    molstar_ref.value.quick_select({ auth_asym_id: data.struct_asym_id, start_residue_number: data.start_residue_number, end_residue_number: data.end_residue_number, focus: true })
  } else if (data.start_residue_number) {
    molstar_ref.value.quick_select({ start_residue_number: data.start_residue_number, end_residue_number: data.end_residue_number, focus: true })
  } else if (data.auth_asym_id && data.residue_number) {
    molstar_ref.value.quick_select({ auth_asym_id: data.auth_asym_id, residue_number: data.residue_number, focus: true })
  } else {
    molstar_ref.value.quick_select({ residue_number: data.residue_number, focus: true })
  }
}

const change_data_name = (data) => {
  const ret = data
  if (ret.chain_id != undefined) {
    ret.auth_asym_id = ret.chain_id
  }
  return ret
}

const select_show_hide = async (data, isShow) => {
  molstar_ref.value.select_none()
  if (data.struct_asym_id != undefined) {
    await molstar_ref.value.quick_select({ auth_asym_id: data.struct_asym_id, start_residue_number: data.start_residue_number, end_residue_number: data.end_residue_number, focus: true })
  } else if (data.start_residue_number) {
    await molstar_ref.value.quick_select({ start_residue_number: data.start_residue_number, end_residue_number: data.end_residue_number, focus: true })
  } else {
    await molstar_ref.value.quick_select({ residue_number: data.residue_number, focus: true })
  }

  if (isShow) {
    await molstar_ref.value.show_selection('chain')
  } else {
    await molstar_ref.value.hide_selection()
  }
}

const select_none = () => {
  molstar_ref.value.select_none()
}

const quick_select = (params, type = 'single', not_focus) => {
  molstar_ref.value.quick_select(params, type, not_focus)
}

const show_selection = async (type = 'prev') => {
  await molstar_ref.value.show_selection(type)
}

const hide_selection = async () => {
  await molstar_ref.value.hide_selection()
}

const showChain = async (chainId) => {
  await molstar_ref.value.showChain(chainId)
}

const hideChain = async (chainId) => {
  await molstar_ref.value.hideChain(chainId)
}

const showLigand = async (chainId, resId, resName) => {
  await molstar_ref.value.showLigand(chainId, resId, resName)
}

const hideLigand = async (chainId, resId, resName) => {
  await molstar_ref.value.hideLigand(chainId, resId, resName)
}

const reset_camera = () => {
  molstar_ref.value.reset_camera()
}

const highlightResidues = (residues) => molstar_ref.value?.highlight_residues(residues)
const clearHighlightedResidues = () => molstar_ref.value?.select_none()
const focusResidues = (residues) => molstar_ref.value?.highlight_residues(residues, true)
const getStructureInfo = () => ({
  ...get_pdb_info(),
  chains: chain_content.value,
  ligands: ligand_content.value,
})

const clean_old_data = () => {
  chain_content.value = []
  ligand_content.value = []
  shape_selector.value = null
}

const open_loading = (content) => {
  if_cover.value = false
  is_loading.value = true
  loading_text.value = content || translate('platform.loading')
}

const close_loading = (flag) => {
  is_loading.value = false
  loading_text.value = ''
  
  if (flag) {
    if_err.value = true
  }
}

const getPickedResidue = (e) => {
  const pickedLoci = e.current?.loci
  const loci = StructureElement.Loci.is(pickedLoci)
    ? pickedLoci
    : Bond.isLoci(pickedLoci) && !Bond.isLociEmpty(pickedLoci)
      ? Bond.toFirstStructureElementLoci(pickedLoci)
      : null
  if (!loci) return null
  const location = StructureElement.Loci.getFirstLocation(loci)
  if (!location) return null
  const insertionCode = StructureProperties.residue.pdbx_PDB_ins_code(location)
  return {
    chain_id: StructureProperties.chain.auth_asym_id(location).trim(),
    residue_number: StructureProperties.residue.auth_seq_id(location),
    insertion_code: insertionCode === '?' || insertionCode === '.' ? '' : insertionCode || '',
    residue_name: StructureProperties.atom.label_comp_id(location),
    record_type: StructureProperties.residue.group_PDB(location),
    overlay_id: molstar_ref.value.get_overlay_id(loci),
  }
}

const mouse_event = (e) => {
  if (
    e.button === ButtonsType.Flag.Primary
    && props.selectionMode !== 'none'
    && e.current
    && e.current.loci.kind !== 'empty-loci'
  ) {
    if (props.selectionMode === 'point') {
      emit('point-pick', { center: e.position })
      return
    }
    const residue = getPickedResidue(e)
    if (!residue) return
    if (props.selectionMode === 'residue' && residue.record_type === 'ATOM') {
      emit('residue-toggle', residue)
    } else if (props.selectionMode === 'ligand' && (residue.record_type === 'HETATM' || residue.overlay_id === 'reference')) {
      emit('ligand-select', residue)
    }
    return
  }
  if(e.button === ButtonsType.Flag.Primary && e.current && e.current.loci.kind !== 'empty-loci'){
    const position = e.position
    
    // Emit residue click event with chain and residue info
    try {
      const loci = e.current.loci
      if (loci && loci.elements && loci.elements.length > 0) {
        const residue = getPickedResidue(e)
        if (residue) {
          emit('residue-click', {
            chainId: residue.chain_id,
            position: residue.residue_number,
            name: residue.residue_name
          })
        }
      }
    } catch (err) {
      console.log('Error extracting residue info:', err)
    }
    
    let flag = false
    if (props.if_show_box === true) {
      if (props.pocket_check) {
        for (let i = 0; i < ligand_content.value.length; i++) {
          const pocket_coord_dict = change_pocket_to_xyz(ligand_content.value[i].max_min_coord)
          const iou = calc_iou(pocket_coord_dict, {'x': position[0], 'y': position[1], 'z': position[2], 'l1': props.l1, 'l2': props.l2, 'l3': props.l3})
          console.log('iou: ', iou)
          if (iou > 0.5) {
            flag = true
            break
          }
          flag = false
        }
      }

      emit('update:if_changed_box', true)
      add_shape(
        position[0],
        position[1],
        position[2],
        props.l1,
        props.l2,
        props.l3
      )
      console.log('click func flag: ', flag)
      if (!flag) {
        // Trigger parent callback
        emit('iou_func', true)
      } else {
        emit('iou_func', false)
      }
    }
  }
}

function registerMouseEvent() {
  if (
    !mouse_listener_registered.value
    && is_initialized.value
    && (props.if_click_event || props.selectionMode !== 'none')
  ) {
    molstar_ref.value.add_mouse_event(mouse_event)
    mouse_listener_registered.value = true
  }
}

onMounted(registerMouseEvent)

watch(
  () => props.selectedResidues,
  (value) => {
    if (is_initialized.value && props.selectionMode === 'residue') highlightResidues(value)
  },
  { deep: true },
)
watch(() => props.selectionMode, (mode) => {
  registerMouseEvent()
  if (is_initialized.value) highlightResidues(mode === 'residue' ? props.selectedResidues : [])
})

onBeforeUnmount(() => {
  disposed = true
  contextRequest++
})

// Additional loading control methods
const show_loading = (text) => {
  is_loading.value = true
  loading_text.value = text || translate('platform.loading')
}

const hide_loading = () => {
  is_loading.value = false
  loading_text.value = ''
}

// Expose methods
defineExpose({
  loadStructure,
  loadContext,
  overlayStructure,
  add_shape,
  get_pdb_info,
  remove_shape,
  change_chain,
  calc_ligand_box,
  select_and_focus,
  select_show_hide,
  select_none,
  quick_select,
  show_selection,
  hide_selection,
  reset_camera,
  clean_old_data,
  open_loading,
  close_loading,
  show_loading,
  hide_loading,
  showChain,
  hideChain,
  showLigand,
  hideLigand,
  highlightResidues,
  clearHighlightedResidues,
  focusResidues,
  getStructureInfo,
})
</script>

<style scoped>
/* Custom styles can be added here if needed */
</style>
