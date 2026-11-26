export async function getMoleculeProperties(input: string) {
  const { Molecule } = await import('openchemlib')
  const molecule = /V[23]000|M\s+END/i.test(input) ? Molecule.fromMolfile(input) : Molecule.fromSmiles(input)
  const formula = molecule.getMolecularFormula()
  let charge = 0
  for (let atom = 0; atom < molecule.getAllAtoms(); atom++) charge += molecule.getAtomCharge(atom)
  return { formula: formula.formula, weight: formula.relativeWeight, smiles: molecule.toSmiles(), charge }
}
