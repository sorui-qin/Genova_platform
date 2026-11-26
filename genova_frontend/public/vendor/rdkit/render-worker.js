let rdkit
self.onmessage = async ({ data }) => {
  let mol, query
  try {
    if (!rdkit) {
      importScripts(data.scriptUrl)
      rdkit = await self.initRDKitModule({ locateFile: name => new URL(name, data.scriptUrl).href })
    }
    mol = rdkit.get_mol(data.input, data.removeHs ? '{"removeHs":true}' : '{}')
    if (!mol) throw new Error('Invalid molecule')
    if (!/V[23]000|M\s+END/i.test(data.input)) {
      const smiles = mol.get_smiles()
      mol.delete()
      mol = rdkit.get_mol(smiles)
      if (!mol) throw new Error('Invalid standardized molecule')
    }
    if (data.regenerateCoords) mol.set_new_coords()
    const atoms = new Set(data.atoms)
    Object.keys(data.colors).forEach(index => atoms.add(Number(index)))
    if (data.smarts) {
      query = rdkit.get_qmol(data.smarts)
      if (query) {
        const match = JSON.parse(mol.get_substruct_match(query))
        for (const index of (Array.isArray(match) ? match : match.atoms || [])) atoms.add(index)
      }
    }
    const svg = mol.get_svg_with_highlights(JSON.stringify({
      atoms: [...atoms], bonds: [], highlightAtomColors: data.colors,
      width: data.width, height: data.height, addAtomIndices: data.showAtomIndex,
      bondLineWidth: data.bondWidth,
      rotate: data.rotation || 0,
      ...(data.maxFontSize == null ? {} : { maxFontSize: data.maxFontSize }),
    }))
    self.postMessage({ id: data.id, svg })
  } catch (error) {
    self.postMessage({ id: data.id, error: error.message })
  } finally {
    query?.delete()
    mol?.delete()
  }
}
