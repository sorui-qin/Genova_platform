import type { ComponentManifest } from '@/types/proteinContext'

export function previewCif(components: ComponentManifest['components']) {
    const token = (value: string | number) => { const text = String(value); return !text || /[\s'"#;]/.test(text) ? '"' + text.replace(/"/g, "'") + '"' : text; };
    const columns = ['group_PDB', 'id', 'type_symbol', 'label_atom_id', 'label_alt_id', 'label_comp_id', 'label_asym_id', 'label_entity_id', 'label_seq_id', 'pdbx_PDB_ins_code', 'Cartn_x', 'Cartn_y', 'Cartn_z', 'occupancy', 'B_iso_or_equiv', 'auth_seq_id', 'auth_asym_id', 'pdbx_PDB_model_num'];
    let serial = 0;
    return ['data_preview', '#', 'loop_', ...columns.map(key => '_atom_site.' + key), ...components.flatMap((c, i) => c.atoms.map(a => [a.record_type, ++serial, a.element, a.atom_name, a.altloc || '.', a.residue_name, (a as any).label_asym_id || 'C' + i, i + 1, a.author_residue_number, a.insertion_code || '?', ...a.coordinates, a.occupancy, 0, a.author_residue_number, a.author_chain_id || '.', 1].map(token).join(' '))), '#'].join('\n');
}
