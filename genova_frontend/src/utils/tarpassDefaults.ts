export const defaultPrefilters = () => [
  { metric: 'qed', op: 'gt' as const, value: 0.4 },
  { metric: 'sa_score', op: 'lt' as const, value: 5 },
  { metric: 'highly_fused', op: 'eq' as const, value: 0 },
]
