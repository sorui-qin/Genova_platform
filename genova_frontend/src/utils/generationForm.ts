export const SURFGEN_ROUND_TARGET = 1000

export function generationCountLimit(engine: string, objectives: readonly { metric: string }[] = []) {
  if (engine === 'epso') return objectives.some(objective => objective.metric === 'gnina_affinity') ? 500 : 1000
  return engine === 'delete' ? 10000 : 50000
}

export function effectiveGenerationSampling(
  engine: string, count: number, sampling: Record<string, number | string>,
) {
  const values = { ...sampling }
  if (engine === 'surfgen' && count > SURFGEN_ROUND_TARGET) delete values.seed
  if (engine === 'ecloudgen' && values.num_clouds === '') delete values.num_clouds
  return values
}
