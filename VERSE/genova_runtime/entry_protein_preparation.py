from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from genova_runtime.pdb2pqr_compat import AMINO_ACIDS, protein_residues, restore_pdb, segment_protein


COFACTORS = {"HEM", "HEC", "HEO", "FAD", "FMN", "NAD", "NAP", "NDP", "NAH", "NAI", "PLP", "PMP", "TPP", "TDP", "SAM", "SAH", "COA"}






def _load_ligand(path: Path, *, sanitize=True):
    from rdkit import Chem

    suffix = path.suffix.lower()
    if suffix == ".sdf":
        molecule = next((mol for mol in Chem.SDMolSupplier(str(path), removeHs=False, sanitize=sanitize) if mol), None)
    elif suffix == ".mol":
        molecule = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=sanitize)
    elif suffix == ".mol2":
        molecule = Chem.MolFromMol2File(str(path), removeHs=False, sanitize=sanitize)
    else:
        molecule = None
    if molecule is None:
        raise ValueError("Reference ligand could not be parsed; upload a valid 3D SDF/MOL/MOL2")
    if sanitize:
        Chem.SanitizeMol(molecule)
    if molecule.GetNumHeavyAtoms() == 0:
        raise ValueError("Reference ligand contains no heavy atoms")
    if molecule.GetNumConformers() == 0 or not molecule.GetConformer().Is3D():
        raise ValueError("Reference ligand must contain 3D coordinates")
    if any(not math.isfinite(value) for point in molecule.GetConformer().GetPositions() for value in point):
        raise ValueError("Reference ligand contains non-finite coordinates")
    return molecule




def _ligand_positions(molecule) -> list[list[float]]:
    positions = molecule.GetConformer().GetPositions()
    return [
        [float(value) for value in positions[atom.GetIdx()]]
        for atom in molecule.GetAtoms()
        if atom.GetAtomicNum() > 1
    ]


def _validate_ligand_box(molecule, box: dict[str, Any]) -> None:
    center = [float(value) for value in box["center"]]
    size = [float(value) for value in box["size"]]
    if any(
        abs(position[axis] - center[axis]) > size[axis] / 2 + 1e-6
        for position in _ligand_positions(molecule)
        for axis in range(3)
    ):
        raise ValueError("Reference ligand heavy atoms must be inside the final Protein Context box")






def _standardize_nonstandard_residues(protein_input: Path, target: Path, *, policy, allowed_keys, residue_source_ids):
    from genova_runtime.preparation_policy import STANDARDIZABLE_RESIDUES
    if policy != 'standardize_supported':
        return protein_input, []
    conversions = {}
    lines = []
    for line in protein_input.read_text().splitlines():
        record = line[:6].strip()
        if record in {'ATOM', 'HETATM'}:
            key = (line[21:22].strip(), int(line[22:26]), line[26:27].strip())
            name = line[17:20].strip()
            spec = STANDARDIZABLE_RESIDUES.get(name)
            if spec and key in allowed_keys:
                atom_name = line[12:16].strip()
                source_element = line[76:78].strip().upper()
                target_name = spec['atom_renames'].get(atom_name, atom_name)
                target_element = spec['element_renames'].get(atom_name, source_element)
                output_name = target_name.rjust(4) if len(target_element) == 2 or len(target_name) == 4 else (' ' + target_name).ljust(4)
                chars = list(line.ljust(80))
                chars[0:6] = 'ATOM  '
                chars[12:16] = output_name
                chars[17:20] = f'{spec["to"]:>3}'
                chars[76:78] = f'{target_element:>2}'
                line = ''.join(chars)
                row = conversions.setdefault(key, dict(source_residue_id=residue_source_ids.get(key),
                    chain_id=key[0], residue_number=key[1], insertion_code=key[2],
                    from_residue_name=name, to_residue_name=spec['to'], atom_mapping=[]))
                if target_name != atom_name:
                    row['atom_mapping'].append(dict(source_atom_name=atom_name, output_atom_name=target_name,
                        source_element=source_element, output_element=target_element))
        lines.append(line)
    target.write_text('\n'.join(lines) + '\n')
    return target, list(conversions.values())


def _repair_protein(protein_input: Path, output_path: Path, *, add_hydrogens, nonstandard_policy,
                    standardize_keys=(), residue_source_ids=None):
    from openmm.app import PDBFile
    from pdbfixer import PDBFixer
    from genova_runtime.preparation_policy import STANDARDIZABLE_RESIDUES

    residue_source_ids = residue_source_ids or {}
    standardized_input, standardized = _standardize_nonstandard_residues(protein_input,
        output_path.with_name('standardized_input.pdb'), policy=nonstandard_policy,
        allowed_keys=set(standardize_keys), residue_source_ids=residue_source_ids)
    original = PDBFixer(filename=str(protein_input))
    original.findMissingResidues()
    chains = list(original.topology.chains())
    unrepaired_gaps = []
    for (chain_index, insertion_index), names in original.missingResidues.items():
        residues = list(chains[chain_index].residues())
        before = residues[insertion_index] if insertion_index < len(residues) else None
        after = residues[insertion_index - 1] if insertion_index else None
        chain_id = chains[chain_index].id.strip()
        gap = {
            "chain_id": chain_id,
            "after_residue": after.id if after else None,
            "after_insertion_code": after.insertionCode.strip() if after else "",
            "before_residue": before.id if before else None,
            "before_insertion_code": before.insertionCode.strip() if before else "",
            "residues": list(names),
            "reason": "report_only",
        }
        unrepaired_gaps.append(gap)

    segmented = output_path.with_name("segmented_protein.pdb")
    segments = segment_protein(standardized_input, segmented, remove_hydrogens=add_hydrogens)
    fixer = PDBFixer(filename=str(segmented))
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findNonstandardResidues()
    replaceable, skipped = [], []
    for residue, replacement in fixer.nonstandardResidues:
        key = (residue.chain.id, int(residue.id), residue.insertionCode.strip())
        if nonstandard_policy == 'standardize_supported' and residue.name in STANDARDIZABLE_RESIDUES and key in set(standardize_keys):
            replaceable.append((residue, replacement))
        else:
            skipped.append(dict(chain_id=segments['chain_map'][residue.chain.id], residue_number=int(residue.id),
                insertion_code=residue.insertionCode.strip(), from_residue_name=residue.name, to_residue_name=replacement,
                reason='No verified standardization template or operation disabled'))
    replaced = list(standardized)
    if replaceable:
        replaced.extend(dict(source_residue_id=residue_source_ids.get((residue.chain.id, int(residue.id), residue.insertionCode.strip())),
            chain_id=segments['chain_map'][residue.chain.id], residue_number=int(residue.id),
            insertion_code=residue.insertionCode.strip(), from_residue_name=residue.name, to_residue_name=replacement,
            atom_mapping=[]) for residue, replacement in replaceable)
        fixer.nonstandardResidues = replaceable
        fixer.replaceNonstandardResidues()
    remaining = [residue for residue in fixer.topology.residues() if residue.name not in AMINO_ACIDS]
    if remaining:
        labels = [f"{segments['chain_map'][residue.chain.id]}:{residue.name}{residue.id}{residue.insertionCode}" for residue in remaining]
        raise ValueError('Unsupported protein residue(s) remain after standardization: ' + ', '.join(labels))
    fixer.findMissingAtoms()
    missing_atoms = sum(len(atoms) for atoms in fixer.missingAtoms.values()) + sum(len(atoms) for atoms in fixer.missingTerminals.values())
    fixer.addMissingAtoms()
    tool_output = output_path.with_name("repaired_segments.pdb")
    with tool_output.open("w", encoding="utf-8") as file:
        PDBFile.writeFile(fixer.topology, fixer.positions, file, keepIds=True)
    restore_pdb(tool_output, output_path, chain_map=segments["chain_map"])
    protein_residues(output_path)
    known = {(gap["chain_id"], gap["after_residue"], gap["before_residue"]) for gap in unrepaired_gaps}
    unrepaired_gaps.extend(gap for gap in segments["breaks"] if (gap["chain_id"], gap["after_residue"], gap["before_residue"]) not in known)
    return {
        "missing_atoms_added": missing_atoms,
        "nonstandard_residues_replaced": replaced,
        "nonstandard_residues_skipped": skipped,
        "repaired_gaps": [],
        "unrepaired_gaps": unrepaired_gaps,
        "backbone_breaks": segments["breaks"],
        "segment_count": segments["segment_count"],
        "removed_hydrogens": segments["removed_hydrogens"],
        "sequence_available": any(line.startswith("SEQRES") for line in protein_input.read_text().splitlines()),
        "residue_mapping": [
            {"fragment_id": tool[0], "residue_number": original[1], "insertion_code": original[2], "chain_id": original[0]}
            for tool, original in segments["mapping"].items()
        ],
    }


def _openmm_structure(path, coordination_pairs=()):
    from openmm.app import Modeller, PDBFile
    protein = PDBFile(str(path))
    if coordination_pairs:
        def identity(atom):
            return (atom.residue.chain.id, atom.residue.id, atom.residue.insertionCode, atom.name)
        model = Modeller(protein.topology, protein.positions)
        # Source coordination remains provenance, not a covalent force-field bond.
        model.delete([bond for bond in model.topology.bonds() if frozenset(identity(atom) for atom in bond) in coordination_pairs])
        return model
    return protein


def _minimize_protein(protein_input: Path, output_path: Path, restraint_source: Path, *, platform_name=None, forcefield_files=None, coordination_pairs=()) -> dict:
    import os
    import time
    from openmm import CustomExternalForce, LangevinMiddleIntegrator, Platform, unit
    from openmm.app import ForceField, HBonds, NoCutoff, PDBFile, Simulation

    start = time.monotonic()
    properties = {}
    if platform_name == 'CPU':
        threads = int(os.getenv('OPENMM_CPU_THREADS', '8'))
        if threads < 1:
            raise ValueError('OPENMM_CPU_THREADS must be a positive integer')
        threads = min(threads, len(os.sched_getaffinity(0)))
        properties['Threads'] = str(threads)
    protein = _openmm_structure(protein_input, coordination_pairs)
    source = PDBFile(str(restraint_source))
    original_heavy = {
        (atom.residue.chain.id, atom.residue.id, atom.residue.insertionCode, atom.name): source.positions[atom.index]
        for atom in source.topology.atoms()
        if atom.element is not None and atom.element.symbol != "H"
    }
    forcefield = ForceField(*(forcefield_files or ("amber14-all.xml", "implicit/obc2.xml")))
    unmatched = forcefield.getUnmatchedResidues(protein.topology)
    if unmatched:
        labels = [f"{r.chain.id}:{r.name}{r.id}{r.insertionCode}" for r in unmatched]
        raise ValueError(f"OpenMM force field does not support prepared residues: {labels}")
    system = forcefield.createSystem(protein.topology, nonbondedMethod=NoCutoff, constraints=HBonds)
    restraint = CustomExternalForce("0.5*k*periodicdistance(x,y,z,x0,y0,z0)^2")
    restraint.addGlobalParameter("k", 1000 * unit.kilojoules_per_mole / unit.nanometer**2)
    for name in ("x0", "y0", "z0"):
        restraint.addPerParticleParameter(name)
    for atom in protein.topology.atoms():
        key = (atom.residue.chain.id, atom.residue.id, atom.residue.insertionCode, atom.name)
        if key in original_heavy:
            point = original_heavy[key].value_in_unit(unit.nanometer)
            restraint.addParticle(atom.index, point)
    system.addForce(restraint)
    integrator = LangevinMiddleIntegrator(300 * unit.kelvin, 1 / unit.picosecond, 0.002 * unit.picoseconds)
    simulation = Simulation(protein.topology, system, integrator, platform=Platform.getPlatformByName(platform_name) if platform_name else None, platformProperties=properties)
    simulation.context.setPositions(protein.positions)
    initial_energy = simulation.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    if not math.isfinite(initial_energy):
        raise ValueError('OpenMM input potential energy is not finite')
    simulation.minimizeEnergy(maxIterations=50)
    state = simulation.context.getState(getPositions=True, getEnergy=True)
    final_energy = state.getPotentialEnergy().value_in_unit(unit.kilojoules_per_mole)
    if not math.isfinite(final_energy):
        raise ValueError('OpenMM minimized potential energy is not finite')
    with output_path.open("w", encoding="utf-8") as file:
        PDBFile.writeFile(protein.topology, state.getPositions(), file, keepIds=True)
    return {'status': 'completed', 'platform': simulation.context.getPlatform().getName(),
            'cpu_threads': int(properties['Threads']) if properties else None,
            'initial_potential_energy_kj_mol': initial_energy, 'final_potential_energy_kj_mol': final_energy,
            'max_iterations': 50, 'elapsed_seconds': round(time.monotonic() - start, 3),
            'convergence': 'not_asserted'}
