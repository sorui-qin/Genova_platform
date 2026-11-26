declare module '@/components/common/utils.js' {
  export function init_ketcher_module(id: string): Promise<void>
}

declare module '@/components/common/dataCenterSelector.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{
    filetypes?: string[]
  }, {}, any>
  export default component
}

declare module '@/api/molgen' {
  export function smiles_list(id: string | number, params: FormData): Promise<any>
  export function smiles_action(id: string | number, params: FormData): Promise<any>
  export function download_api(job_id: string | number, params: FormData, file_name: string, type: 'zip' | 'csv' | 'sdf'): void
}

declare module '@/pages/molfactory/components/tabulation.js' {
  export function getTablevalue(value: number): string | undefined
  export const algo_name_type: Record<string, string>
  export const property_name: Record<string, string>
}

declare module '@/components/molecule/protein3d_molstar.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{
    box_x?: number
    box_y?: number
    box_z?: number
    l1?: number
    l2?: number
    l3?: number
    if_show_box?: boolean
    ligand_select?: string
    if_pocket?: boolean
    if_show_contact?: boolean
    always_show_ligands?: boolean
    show_ligands_console?: boolean
    if_changed_box?: boolean
    if_click_event?: boolean
    pocket_check?: boolean
  }, {
    loadStructure: (data: string, format?: string) => Promise<any>
    loadContext: (context: import('./proteinContext').ProteinContext) => Promise<void>
    overlayStructure: (data: string, format?: string) => Promise<void>
    change_chain: (chainId: string, checked: boolean, id: string) => Promise<void>
    select_none: () => void
    quick_select: (data: any, mode?: string, single?: boolean) => Promise<void>
    show_selection: (type: string) => void
    hide_selection: () => void
    reset_camera: () => void
    select_and_focus: (data: any) => void
    get_pdb_info: () => any
    open_loading: (text: string) => void
    close_loading: () => void
  }, any>
  export default component
}

declare module './components/createTask.js' {
  export function selectedMethods(
    generationType: string,
    isPocket: boolean,
    methodOptions: Array<{ label: string; value: string; disabled: boolean }>,
    hasFragments: boolean
  ): Array<{ label: string; value: string; disabled: boolean }>;
}

declare module '@/components/molecule/drugflow_molstar.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{
    box_bg_color?: number
    if_sequence_panel?: boolean
    show_tool?: boolean
    disable_comp_btn?: boolean
    prolif_show_ligname?: boolean
  }, {}, any>
  export default component
} 