import { parseCifText } from 'molstar/lib/commonjs/mol-io/reader/cif/text/parser.js'

export async function cifToPdb(text) {
  const parsed = await parseCifText(text).run()
  if (parsed.isError) throw new Error('CIF_INVALID')
  const blocks = parsed.result.blocks.filter(block => block.categories.atom_site?.rowCount)
  if (blocks.length !== 1) throw new Error('CIF_ATOM_BLOCK_REQUIRED')
  const atoms = blocks[0].categories.atom_site
  const lines = []
  let model = '', serial = 0
  const seenModels = new Set()
  const field = (row, ...names) => {
    for (const name of names) {
      const column = atoms.getField(name)
      if (column && column.valueKind(row) === 0) return column.str(row)
    }
    return ''
  }
  const width = (value, size) => {
    if (value.length > size || /[^\x20-\x7e]/.test(value)) throw new Error('CIF_PDB_LIMIT')
    return value
  }
  const decimal = (value, size, precision) => {
    if (!value || !Number.isFinite(Number(value))) throw new Error('CIF_INVALID')
    return width(Number(value).toFixed(precision), size).padStart(size)
  }
  for (let i = 0; i < atoms.rowCount; i++) {
    const currentModel = field(i, 'pdbx_PDB_model_num') || '1'
    if (!/^\d+$/.test(currentModel) || Number(currentModel) < 1) throw new Error('CIF_INVALID')
    if (currentModel !== model) {
      if (seenModels.has(currentModel)) throw new Error('CIF_INVALID')
      if (model) lines.push('ENDMDL')
      lines.push(`MODEL     ${width(currentModel, 4).padStart(4)}`)
      seenModels.add(currentModel); model = currentModel; serial = 0
    }
    const record = field(i, 'group_PDB')
    const name = width(field(i, 'auth_atom_id', 'label_atom_id'), 4)
    const residue = width(field(i, 'auth_comp_id', 'label_comp_id'), 3)
    const chain = width(field(i, 'auth_asym_id', 'label_asym_id'), 1)
    const sequence = field(i, 'auth_seq_id', 'label_seq_id')
    const element = width(field(i, 'type_symbol'), 2)
    if (!['ATOM', 'HETATM'].includes(record) || !name || !residue || !element || !/^-?\d+$/.test(sequence)) throw new Error('CIF_INVALID')
    const atomName = name.length < 4 && element.length === 1 && !/^\d/.test(name) ? ` ${name}`.padEnd(4) : name.padEnd(4)
    const alt = width(field(i, 'label_alt_id'), 1).padEnd(1)
    const insertion = width(field(i, 'pdbx_PDB_ins_code'), 1).padEnd(1)
    const coords = ['Cartn_x', 'Cartn_y', 'Cartn_z'].map(key => decimal(field(i, key), 8, 3)).join('')
    const occupancy = decimal(field(i, 'occupancy') || '1', 6, 2)
    const temperature = decimal(field(i, 'B_iso_or_equiv') || '0', 6, 2)
    const charge = field(i, 'pdbx_formal_charge') || '0'
    if (!/^[+-]?\d+$/.test(charge) || Math.abs(Number(charge)) > 9) throw new Error('CIF_PDB_LIMIT')
    const chargeText = Number(charge) === 0 ? '  ' : `${Math.abs(Number(charge))}${Number(charge) > 0 ? '+' : '-'}`
    lines.push(`${record.padEnd(6)}${width(String(++serial), 5).padStart(5)} ${atomName}${alt}${residue.padStart(3)} ${chain.padEnd(1)}${width(sequence, 4).padStart(4)}${insertion}   ${coords}${occupancy}${temperature}          ${element.padStart(2)}${chargeText}`)
  }
  lines.push('ENDMDL', 'END', '')
  return lines.join('\n')
}
