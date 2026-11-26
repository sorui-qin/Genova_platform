// 读取PDB文件内容
export function readPDBFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = event => {
      const pdbText = event.target.result
      resolve(pdbText)
    }
    reader.onerror = event => {
      reject(event.target.error)
    }
    reader.readAsText(file)
  })
}


// 确保口袋中没有配体，可以有水分子或者离子
export async function check_pocket(pdb_file, delete_hets, center_dic, dim_dic) {
  const pdb_string = await readPDBFile(pdb_file)
  // delete_hets.push({ residue_number: item.residue_number, chain_id: item.chain_id })
  const delete_hets_list = delete_hets.map(item => item.chain_id + ':' + item.residue_number)
  const x = Number(center_dic.X_center)
  const y = Number(center_dic.Y_center)
  const z = Number(center_dic.Z_center)
  const dim_x = Number(dim_dic.X_dimension)
  const dim_y = Number(dim_dic.Y_dimension)
  const dim_z = Number(dim_dic.Z_dimension)
  const lines = pdb_string.split('\n')
  const het_atom_cnt = {}
  const new_delete_hets = []

  for (const line of lines) {
    if (line.startsWith('HETATM')) {
      const ligand_name = line.substr(17, 3).trim()
      const residue_id = line.substr(22, 5).trim()
      const chain_name = line.substr(21, 1).trim()
      // 转为float
      const x_c = Number(line.substr(30, 8).trim())
      const y_c = Number(line.substr(38, 8).trim())
      const z_c = Number(line.substr(46, 8).trim())
      if (het_atom_cnt[chain_name + ':' + residue_id] === undefined) {
        het_atom_cnt[chain_name + ':' + residue_id] = 1
      } else {
        het_atom_cnt[chain_name + ':' + residue_id] += 1
      }
      if (delete_hets_list.includes(chain_name + ':' + residue_id)) {
        continue
      }
      if (het_atom_cnt[chain_name + ':' + residue_id] < 8) {
        continue
      }
      console.log('ligand_name', ligand_name)
      if (ligand_name !== 'HOH') {
        // 判断坐标是否在口袋内
        if (x_c < x + dim_x / 2 && x_c > x - dim_x / 2 && y_c < y + dim_y / 2 && y_c > y - dim_y / 2 && z_c < z + dim_z / 2 && z_c > z - dim_z / 2) {
          delete_hets_list.push(chain_name + ':' + residue_id)
          delete_hets.push({ residue_number: residue_id, chain_id: chain_name })
          new_delete_hets.push({ residue_number: residue_id, chain_id: chain_name, ligand_name: ligand_name })
        }
      }
    }
  }
  return {delete_hets: delete_hets, new_delete_hets: new_delete_hets}
}


// 分析PDB文件中的配体名称
function analyzePDB(pdbText) {
  const lines = pdbText.split('\n')
  const ligandNames = []

  for (const line of lines) {
    if (line.startsWith('HETATM')) {
      const ligandName = line.substr(17, 3).trim()
      if (!ligandNames.includes(ligandName)) {
        ligandNames.push(ligandName)
      }
    }
  }

  return ligandNames
}

// 同步函数解析PDB文件中的配体名称
export async function parse_ligand(file) {
  try {
    const pdbText = await readPDBFile(file)
    const ligandNames = analyzePDB(pdbText)
    console.log('配体名称:', ligandNames)
    return ligandNames
  } catch (error) {
    console.error('读取文件错误:', error)
    throw error
  }
}

// 同步函数解析PDB文件中的配体名称
export function parse_ligand_string(pdb_string) {
  const ligandNames = analyzePDB(pdb_string)
  console.log('配体名称:', ligandNames)
  return ligandNames
}

export function parse_ligand_info(pdb_string) {
  // 解析所有的配体信息
  // chain_name
  // name
  // count
  const ret_list = []
  const lines = pdb_string.split('\n')
  const ligand_dict = {}
  for (const line of lines) {
    if (line.startsWith('HETATM')) {
      const ligand_name = line.substr(17, 3).trim()
      if (ligand_name === 'HOH') {
        continue
      }
      const residue_id = line.substr(22, 5).trim()
      const chain_name = line.substr(21, 1).trim()
      const x = line.substr(30, 8).trim()
      const y = line.substr(38, 8).trim()
      const z = line.substr(46, 8).trim()

      if (ligand_dict[chain_name + ':' + ligand_name + ':' + residue_id] === undefined) {
        ligand_dict[chain_name + ':' + ligand_name + ':' + residue_id] = {
          chain_name,
          name: chain_name + ':' + ligand_name + ':' + residue_id,
          residue_name: ligand_name,
          residue_id,
          count: 1,
          show_option: true,
          coords: [[Number(x), Number(y), Number(z)]]
        }
      } else {
        ligand_dict[chain_name + ':' + ligand_name + ':' + residue_id].count += 1
        ligand_dict[chain_name + ':' + ligand_name + ':' + residue_id].coords.push([
          Number(x),
          Number(y),
          Number(z)
        ])
      }
    }
  }
  for (const key in ligand_dict) {
    const max_min_dict = calc_max_min(ligand_dict[key])
    ligand_dict[key].max_min_coord = max_min_dict
    ret_list.push(ligand_dict[key])
  }
  return ret_list
}

function calc_max_min(ligand_dict) {
  const coords = ligand_dict.coords
  const x_list = []
  const y_list = []
  const z_list = []
  for (const coord of coords) {
    x_list.push(coord[0])
    y_list.push(coord[1])
    z_list.push(coord[2])
  }
  return {
    max_x: Math.max(...x_list),
    min_x: Math.min(...x_list),
    max_y: Math.max(...y_list),
    min_y: Math.min(...y_list),
    max_z: Math.max(...z_list),
    min_z: Math.min(...z_list)
  }
}

export function parse_chain_info(pdb_string) {
  // 解析所有的链信息
  const lines = pdb_string.split('\n')

  // 获得链中的residue信息
  const chain_dict = {}
  // A Set: an array lookup here made large files freeze the page for seconds.
  const residue_ids = new Set()
  for (const line of lines) {
    if (line.startsWith('ATOM')) {
      const residue_name = line.substr(17, 3).trim()
      const chain_name = line.substr(21, 1).trim()
      const residue_id = line.substr(22, 5).trim()
      if (chain_dict[chain_name] === undefined) {
        chain_dict[chain_name] = []
      }
      if (residue_ids.has(chain_name + ':' + residue_id)) continue
      chain_dict[chain_name].push(residue_name)
      residue_ids.add(chain_name + ':' + residue_id)
    }
  }
  const ret_list = []
  for (const chain_name in chain_dict) {
    ret_list.push({
      chain_full_name: chain_name,
      chain_main_name: chain_name,
      chain_cont: chain_dict[chain_name]
    })
  }
  return ret_list
}


export function search_centry(pdb_string, chain_list=[]) {
  if (chain_list.length === 0) {
    chain_list = parse_chain_info(pdb_string).map(item => item.chain_main_name)
  }
  const lines = pdb_string.split('\n')
  const coord_list = []

  for (const line of lines) {
    if (line.startsWith('ATOM')) {
      const chain_name = line.substr(21, 1).trim()
      const x = line.substr(30, 8).trim()
      const y = line.substr(38, 8).trim()
      const z = line.substr(46, 8).trim()
      if (chain_list.includes(chain_name)) {
        coord_list.push([Number(x), Number(y), Number(z)])
      }
    }
  }
  // 计算中心点
  const center = [0, 0, 0]
  for (const coord of coord_list) {
    center[0] += coord[0]
    center[1] += coord[1]
    center[2] += coord[2]
  }
  center[0] /= coord_list.length
  center[1] /= coord_list.length
  center[2] /= coord_list.length
  return center
}


export function parse_pdb_info(pdb_string, peptide_check=false) {
  const chain_list = parse_chain_info(pdb_string)
  const ligand_list = parse_ligand_info(pdb_string)
  
  let peptide_chains = []
  if (peptide_check) {
    // 短肽链通常定义为氨基酸残基数量小于30的链
    const peptide_threshold = 30
    const short_chains = chain_list.filter(chain => {
      const residue_count = chain.chain_cont.length
      return residue_count > 0 && residue_count < peptide_threshold
    })
    
    // 收集短肽链的坐标信息
    const lines = pdb_string.split('\n')
    const peptide_coords_dict = {}
    
    for (const line of lines) {
      if (line.startsWith('ATOM')) {
        const chain_name = line.substr(21, 1).trim()
        const residue_name = line.substr(17, 3).trim()
        const residue_id = line.substr(22, 5).trim()
        const x = Number(line.substr(30, 8).trim())
        const y = Number(line.substr(38, 8).trim())
        const z = Number(line.substr(46, 8).trim())
        
        // 检查是否属于短肽链
        const is_short_chain = short_chains.some(chain => chain.chain_main_name === chain_name)
        if (is_short_chain) {
          const key = chain_name + ':' + residue_name + ':' + residue_id
          if (peptide_coords_dict[key] === undefined) {
            peptide_coords_dict[key] = {
              chain_name,
              residue_name,
              residue_id,
              coords: [[x, y, z]]
            }
          } else {
            peptide_coords_dict[key].coords.push([x, y, z])
          }
        }
      }
    }
    
    // 构建最终的peptide_chains数据
    peptide_chains = short_chains.map(chain => {
      const chain_name = chain.chain_main_name
      const all_coords = []
      const residue_coords = []
      
      // 收集该链的所有坐标和残基坐标
      for (const key in peptide_coords_dict) {
        if (peptide_coords_dict[key].chain_name === chain_name) {
          all_coords.push(...peptide_coords_dict[key].coords)
          residue_coords.push({
            residue_name: peptide_coords_dict[key].residue_name,
            residue_id: peptide_coords_dict[key].residue_id,
            coords: peptide_coords_dict[key].coords
          })
        }
      }
      
      // 计算max_min坐标
      let max_min_coord = null
      if (all_coords.length > 0) {
        const x_list = all_coords.map(c => c[0])
        const y_list = all_coords.map(c => c[1])
        const z_list = all_coords.map(c => c[2])
        max_min_coord = {
          max_x: Math.max(...x_list),
          min_x: Math.min(...x_list),
          max_y: Math.max(...y_list),
          min_y: Math.min(...y_list),
          max_z: Math.max(...z_list),
          min_z: Math.min(...z_list)
        }
      }
      
      return {
        chain_name: chain.chain_main_name,
        residue_count: chain.chain_cont.length,
        residues: chain.chain_cont,
        coords: all_coords,
        residue_coords: residue_coords,
        max_min_coord: max_min_coord,
        show_option: true,
        name: chain.chain_main_name
      }
    })
  }
  
  return { 
    chain: chain_list, 
    ligand: ligand_list,
    peptide_chains: peptide_chains
  }
}


export function calc_iou(pocket_a, pocket_b) {
  // pocket_a [x, y, z, l1, l2, l3]
  // pocket_b [x, y, z, l1, l2, l3]
  const x1 = Number(pocket_a.x)
  const y1 = Number(pocket_a.y)
  const z1 = Number(pocket_a.z)
  const l1 = Number(pocket_a.l1)
  const l2 = Number(pocket_a.l2)
  const l3 = Number(pocket_a.l3)
  const x2 = Number(pocket_b.x)
  const y2 = Number(pocket_b.y)
  const z2 = Number(pocket_b.z)
  const l4 = Number(pocket_b.l1)
  const l5 = Number(pocket_b.l2)
  const l6 = Number(pocket_b.l3)
  const x_min = Math.min(x1 - l1 / 2, x2 - l4 / 2)
  const x_max = Math.max(x1 + l1 / 2, x2 + l4 / 2)
  const y_min = Math.min(y1 - l2 / 2, y2 - l5 / 2)
  const y_max = Math.max(y1 + l2 / 2, y2 + l5 / 2)
  const z_min = Math.min(z1 - l3 / 2, z2 - l6 / 2)
  const z_max = Math.max(z1 + l3 / 2, z2 + l6 / 2)
  const x = x_max - x_min
  const y = y_max - y_min
  const z = z_max - z_min
  const v1 = l1 * l2 * l3
  const v2 = l4 * l5 * l6
  const v3 = x * y * z
  const v4 = Math.max(0, v1 + v2 - v3)
  const iou = v4 / (v1 + v2 - v4)
  return iou
}

export function change_pocket_to_xyz(coords_info, expand = 10) {
  return {
    x: (coords_info.max_x + coords_info.min_x) / 2,
    y: (coords_info.max_y + coords_info.min_y) / 2,
    z: (coords_info.max_z + coords_info.min_z) / 2,
    l1: coords_info.max_x - coords_info.min_x + expand,
    l2: coords_info.max_y - coords_info.min_y + expand,
    l3: coords_info.max_z - coords_info.min_z + expand
  }
}
