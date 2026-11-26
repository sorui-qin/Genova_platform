/**
 * PDB文件解析工具
 * 用于前端计算蛋白质基本信息，替代 get_basic_info 后端接口
 */

export interface ChainInfo {
  chain_id: string
  start_residue_number: number
  end_residue_number: number
  if_checked?: boolean
}

export interface WaterInfo {
  residue_number: number
  chain_id: string
  if_water_bridge: boolean
}

export interface HetInfo {
  name: string
  residue_number: number
  chain_id: string
  water_within_dist: WaterInfo[]
  if_checked?: boolean
}

export interface PdbBasicInfo {
  status: boolean
  msg: string
  chains: ChainInfo[]
  hets: HetInfo[]
}

interface Atom {
  serial: number
  name: string
  altLoc: string
  resName: string
  chainId: string
  resSeq: number
  x: number
  y: number
  z: number
  element: string
  isHetatm: boolean
}

// 水分子残基名
const WATER_NAMES = new Set(['HOH', 'WAT', 'H2O', 'DOD', 'TIP', 'TIP3', 'TIP4', 'SPC'])

// 标准氨基酸残基名
const STANDARD_RESIDUES = new Set([
  'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE',
  'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL',
  // DNA/RNA
  'DA', 'DC', 'DG', 'DT', 'A', 'C', 'G', 'U', 'DI', 'I'
])

// 可形成氢键的原子元素
const HBOND_ELEMENTS = new Set(['N', 'O', 'S', 'F'])

/**
 * 解析PDB文件内容
 */
function parsePdbContent(pdbContent: string): Atom[] {
  const atoms: Atom[] = []
  const lines = pdbContent.split('\n')

  for (const line of lines) {
    const recordType = line.substring(0, 6).trim()
    
    if (recordType !== 'ATOM' && recordType !== 'HETATM') continue

    try {
      const atom: Atom = {
        serial: parseInt(line.substring(6, 11).trim()) || 0,
        name: line.substring(12, 16).trim(),
        altLoc: line.substring(16, 17).trim(),
        resName: line.substring(17, 20).trim(),
        chainId: line.substring(21, 22).trim() || 'A',
        resSeq: parseInt(line.substring(22, 26).trim()) || 0,
        x: parseFloat(line.substring(30, 38).trim()) || 0,
        y: parseFloat(line.substring(38, 46).trim()) || 0,
        z: parseFloat(line.substring(46, 54).trim()) || 0,
        element: line.substring(76, 78).trim() || line.substring(12, 14).trim().replace(/[0-9]/g, ''),
        isHetatm: recordType === 'HETATM'
      }
      atoms.push(atom)
    } catch (e) {
      // Skip malformed lines
      continue
    }
  }

  return atoms
}

/**
 * 计算两点间的距离
 */
function distance(a1: Atom, a2: Atom): number {
  const dx = a1.x - a2.x
  const dy = a1.y - a2.y
  const dz = a1.z - a2.z
  return Math.sqrt(dx * dx + dy * dy + dz * dz)
}

/**
 * 判断原子是否可以形成氢键
 */
function canFormHBond(atom: Atom): boolean {
  return HBOND_ELEMENTS.has(atom.element.toUpperCase())
}

/**
 * 提取链信息
 */
function extractChains(atoms: Atom[]): ChainInfo[] {
  const chainMap = new Map<string, { min: number; max: number }>()

  for (const atom of atoms) {
    // 只考虑蛋白质/核酸的ATOM记录，或标准残基
    if (atom.isHetatm && !STANDARD_RESIDUES.has(atom.resName)) continue
    if (WATER_NAMES.has(atom.resName)) continue

    const existing = chainMap.get(atom.chainId)
    if (existing) {
      existing.min = Math.min(existing.min, atom.resSeq)
      existing.max = Math.max(existing.max, atom.resSeq)
    } else {
      chainMap.set(atom.chainId, { min: atom.resSeq, max: atom.resSeq })
    }
  }

  const chains: ChainInfo[] = []
  for (const [chainId, range] of chainMap) {
    chains.push({
      chain_id: chainId,
      start_residue_number: range.min,
      end_residue_number: range.max,
      if_checked: true
    })
  }

  // 按链ID排序
  chains.sort((a, b) => a.chain_id.localeCompare(b.chain_id))
  return chains
}

/**
 * 提取配体/杂原子组信息，并计算附近的水分子
 */
function extractHets(atoms: Atom[], waterDistThreshold = 5.0, hbondDistThreshold = 3.5): HetInfo[] {
  // 分离水分子和其他杂原子
  const waterAtoms: Atom[] = []
  const hetAtomMap = new Map<string, Atom[]>() // key: chainId-resSeq-resName
  const proteinAtoms: Atom[] = []

  for (const atom of atoms) {
    if (WATER_NAMES.has(atom.resName)) {
      waterAtoms.push(atom)
    } else if (atom.isHetatm && !STANDARD_RESIDUES.has(atom.resName)) {
      const key = `${atom.chainId}-${atom.resSeq}-${atom.resName}`
      if (!hetAtomMap.has(key)) {
        hetAtomMap.set(key, [])
      }
      hetAtomMap.get(key)!.push(atom)
    } else {
      proteinAtoms.push(atom)
    }
  }

  // 为每个配体计算附近的水分子
  const hets: HetInfo[] = []
  
  for (const [key, hetAtoms] of hetAtomMap) {
    const [chainId, resSeqStr, resName] = key.split('-')
    const resSeq = parseInt(resSeqStr)

    // 找到该配体附近的水分子
    const waterWithinDist: WaterInfo[] = []
    const seenWaters = new Set<string>()

    for (const waterAtom of waterAtoms) {
      // 只考虑氧原子（水分子的主原子）
      if (waterAtom.element.toUpperCase() !== 'O') continue

      const waterKey = `${waterAtom.chainId}-${waterAtom.resSeq}`
      if (seenWaters.has(waterKey)) continue

      // 检查水是否在配体附近
      let minDist = Infinity
      for (const hetAtom of hetAtoms) {
        const dist = distance(waterAtom, hetAtom)
        minDist = Math.min(minDist, dist)
      }

      if (minDist <= waterDistThreshold) {
        seenWaters.add(waterKey)
        
        // 判断是否是水桥
        const isWaterBridge = checkWaterBridge(
          waterAtom, 
          hetAtoms, 
          proteinAtoms, 
          hbondDistThreshold
        )

        waterWithinDist.push({
          residue_number: waterAtom.resSeq,
          chain_id: waterAtom.chainId,
          if_water_bridge: isWaterBridge
        })
      }
    }

    hets.push({
      name: resName,
      residue_number: resSeq,
      chain_id: chainId,
      water_within_dist: waterWithinDist,
      if_checked: true
    })
  }

  // 按链ID和残基号排序
  hets.sort((a, b) => {
    if (a.chain_id !== b.chain_id) return a.chain_id.localeCompare(b.chain_id)
    return a.residue_number - b.residue_number
  })

  return hets
}

/**
 * 检查水分子是否形成水桥
 * 水桥：水分子同时与配体和蛋白质形成氢键
 */
function checkWaterBridge(
  waterAtom: Atom,
  hetAtoms: Atom[],
  proteinAtoms: Atom[],
  hbondDistThreshold: number
): boolean {
  // 检查水是否与配体中的氢键供体/受体原子接近
  let contactsHet = false
  for (const hetAtom of hetAtoms) {
    if (canFormHBond(hetAtom)) {
      const dist = distance(waterAtom, hetAtom)
      if (dist <= hbondDistThreshold) {
        contactsHet = true
        break
      }
    }
  }

  if (!contactsHet) return false

  // 检查水是否与蛋白质中的氢键供体/受体原子接近
  for (const protAtom of proteinAtoms) {
    if (canFormHBond(protAtom)) {
      const dist = distance(waterAtom, protAtom)
      if (dist <= hbondDistThreshold) {
        return true // 同时接触配体和蛋白，是水桥
      }
    }
  }

  return false
}

/**
 * 解析PDB文件，返回基本信息
 * @param pdbContent PDB文件内容字符串
 * @param waterDistThreshold 水分子距离阈值（默认5.0 Å）
 * @param hbondDistThreshold 氢键距离阈值（默认3.5 Å）
 */
export function parsePdbBasicInfo(
  pdbContent: string,
  waterDistThreshold = 5.0,
  hbondDistThreshold = 3.5
): PdbBasicInfo {
  try {
    const atoms = parsePdbContent(pdbContent)
    
    if (atoms.length === 0) {
      return {
        status: false,
        msg: 'No atoms found in PDB file',
        chains: [],
        hets: []
      }
    }

    const chains = extractChains(atoms)
    const hets = extractHets(atoms, waterDistThreshold, hbondDistThreshold)

    return {
      status: true,
      msg: '',
      chains,
      hets
    }
  } catch (error) {
    return {
      status: false,
      msg: error instanceof Error ? error.message : 'Failed to parse PDB file',
      chains: [],
      hets: []
    }
  }
}

export default parsePdbBasicInfo

