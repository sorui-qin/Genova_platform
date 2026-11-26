export const metricSections = [
  { id: 'physicochemical', zh: '理化性质与类药性', en: 'Properties & drug-likeness', ids: ['exact_molecular_weight', 'hba', 'hbd', 'lipinski_violations', 'logp', 'molecular_volume', 'molecular_weight', 'qed', 'sa_score', 'tpsa'] },
  { id: 'composition', zh: '分子组成与柔性', en: 'Composition & flexibility', ids: ['all_common', 'complete', 'csp3', 'flexibility', 'heavy_atoms', 'heteroatom_ratio', 'heteroatoms', 'rotatable_bonds', 'torsion_count'] },
  { id: 'complexity', zh: '立体特征与复杂度', en: 'Stereochemistry & complexity', ids: ['bertz_ct', 'chiral_atoms', 'morgan_fragments', 'spacial_score', 'spiro_atoms'] },
  { id: 'rings', zh: '环结构', en: 'Ring systems', ids: ['fused_ring_present', 'fused_systems', 'highly_fused', 'largest_ring', 'ring_count', 'rings_in_fused_system', 'unusual_ring_present', 'unusual_rings'] },
  { id: 'alerts', zh: '结构警示', en: 'Structural alerts', ids: ['glaxo_alert', 'pains_alert', 'surechembl_alert'] },
  { id: 'similarity-2d', zh: '二维参考相似度', en: '2D reference similarity', ids: ['reference_similarity', 'scaffold_similarity'] },
  { id: 'docking', zh: '对接评分与效率', en: 'Docking scores & efficiency', ids: ['affinity', 'cnn_affinity', 'cnn_score', 'le_heavyatom', 'le_mw'] },
  { id: 'geometry', zh: '三维形状与几何', en: '3D shape & geometry', ids: ['centroid_shift', 'electrostatic_similarity', 'no_clashes', 'shape_similarity', 'sucos', 'volume'] },
  { id: 'interaction-metrics', zh: '相互作用', en: 'Interactions', ids: ['fully_matched', 'matched_rate'] },
]
