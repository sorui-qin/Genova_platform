from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Scaffolds import MurckoScaffold


EDIT_MODES = {
    "r_group",
    "side_chain",
    "linker",
    "scaffold_hopping",
    "custom",
    "derivation_site",
}
AUTO_EDIT_MODES = {"r_group", "side_chain", "linker", "scaffold_hopping"}
MMPA_BOND = Chem.MolFromSmarts("[#6+0;!$(*=,#[!#6])]!@!=!#[*]")
MIN_CUSTOM_FRAGMENT_ATOMS = 3


class DeleteEditValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def read_reference(path: str | Path) -> Chem.Mol:
    supplier = Chem.SDMolSupplier(str(path), removeHs=False)
    mol = supplier[0] if len(supplier) else None
    if mol is None:
        raise ValueError("Reference ligand must contain a valid SDF molecule")
    mol = Chem.RemoveHs(mol)
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(atom.GetIdx() + 1)
    if mol.GetNumConformers() == 0:
        raise ValueError("Reference ligand must contain 3D coordinates")
    return mol


def reference_preview(path: str | Path) -> dict[str, Any]:
    mol = read_reference(path)
    return {
        "reference_molfile": _preview_molblock(mol),
        "reference_smiles": Chem.MolToSmiles(mol),
        "atom_count": mol.GetNumAtoms(),
    }


def build_candidates(path: str | Path, mode: str) -> list[dict[str, Any]]:
    if mode not in AUTO_EDIT_MODES:
        raise ValueError("Unsupported automatic edit mode")
    mol = read_reference(path)
    if mode == "r_group":
        retained_sets = _r_group_candidates(mol)
    elif mode == "linker":
        retained_sets = _linker_candidates(mol)
    elif mode == "side_chain":
        retained_sets = [_murcko_indices(mol)]
    else:
        scaffold = set(_murcko_indices(mol))
        retained_sets = [sorted(set(range(mol.GetNumAtoms())) - scaffold)]

    candidates = []
    seen = set()
    for retained in retained_sets:
        retained = sorted(set(retained))
        if not retained or len(retained) == mol.GetNumAtoms():
            continue
        anchors = _anchor_indices(mol, retained)
        candidate_id = _candidate_id(mode, retained, anchors)
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        fragment = _subset_mol(mol, retained)
        candidates.append(
            {
                "id": candidate_id,
                "retained_molfile": _preview_molblock(fragment),
                "retained_smiles": _plain_smiles(fragment),
                "retained_atom_indices": retained,
                "anchor_atom_indices": anchors,
            }
        )
    return sorted(candidates, key=lambda row: (row["retained_smiles"], row["id"]))


def validate_edit_request(edit):
    mode = edit.get('mode') if isinstance(edit, dict) else None
    if not isinstance(mode, str) or mode not in EDIT_MODES:
        raise ValueError('property_optimization.edit.mode is invalid')
    field = 'candidate_id' if mode in AUTO_EDIT_MODES else 'edited_molfile' if mode == 'custom' else 'anchor_atom_index'
    if set(edit) != {'mode', field}:
        raise ValueError('Missing or unknown edit request fields')
    if field == 'anchor_atom_index':
        if type(edit[field]) is not int or edit[field] < 0:
            raise ValueError('derivation_site requires a nonnegative anchor_atom_index')
    elif not isinstance(edit[field], str) or not edit[field].strip():
        raise ValueError('Empty edit selection')


def validate_delete_edit(reference_path: str | Path, edit: dict[str, Any]) -> dict[str, Any]:
    """Validate a new edit against the prepared reference without writing a fragment."""
    validate_edit_request(edit)
    _, metadata = _resolve_fragment(reference_path, edit, validate_graph=True)
    return metadata


def _resolve_fragment(
    reference_path: str | Path,
    edit: dict[str, Any],
    *,
    validate_graph: bool,
) -> tuple[Chem.Mol, dict[str, Any]]:
    mode = str(edit.get("mode") or "").strip()
    if mode not in EDIT_MODES:
        raise ValueError("property_optimization.edit.mode is invalid")

    mol = read_reference(reference_path)
    if mode in AUTO_EDIT_MODES:
        candidate_id = str(edit.get("candidate_id") or "")
        candidate = next(
            (row for row in build_candidates(reference_path, mode) if row["id"] == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("Selected edit candidate is invalid")
        retained = candidate["retained_atom_indices"]
        anchors = candidate["anchor_atom_indices"]
    elif mode == "custom":
        retained = _validate_custom_edit(mol, str(edit.get("edited_molfile") or ""), validate_graph=validate_graph)
        anchors = _anchor_indices(mol, retained)
    else:
        try:
            anchor = int(edit.get("anchor_atom_index"))
        except (TypeError, ValueError) as exc:
            raise ValueError("derivation_site requires anchor_atom_index") from exc
        if anchor < 0 or anchor >= mol.GetNumAtoms():
            raise ValueError("anchor_atom_index is out of range")
        if mol.GetAtomWithIdx(anchor).GetTotalNumHs() < 1:
            raise ValueError("Selected derivation atom has no implicit hydrogen")
        retained = list(range(mol.GetNumAtoms()))
        anchors = [anchor]

    fragment = _subset_mol(mol, retained)
    for atom in fragment.GetAtoms():
        atom.ClearProp("molAtomMapNumber")
    return fragment, {
        "edit_mode": mode,
        "retained_smiles": Chem.MolToSmiles(fragment),
        "retained_atom_indices": retained,
        "anchor_atom_indices": anchors,
    }


def prepare_fragment(
    reference_path: str | Path,
    edit: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    # Previously queued jobs still use the molecular checks in effect when they were accepted.
    fragment, metadata = _resolve_fragment(reference_path, edit, validate_graph=False)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = Chem.SDWriter(str(target))
    try:
        writer.write(fragment)
    finally:
        writer.close()
    return metadata


def _eligible_bonds(mol: Chem.Mol) -> list[tuple[int, int]]:
    matches = mol.GetSubstructMatches(MMPA_BOND, uniquify=True)
    return sorted({tuple(sorted(match[:2])) for match in matches if len(match) >= 2})


def _components_after_cuts(mol: Chem.Mol, cuts: set[tuple[int, int]]) -> list[set[int]]:
    adjacency = {atom.GetIdx(): set() for atom in mol.GetAtoms()}
    for bond in mol.GetBonds():
        pair = tuple(sorted((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())))
        if pair in cuts:
            continue
        adjacency[pair[0]].add(pair[1])
        adjacency[pair[1]].add(pair[0])

    components = []
    remaining = set(adjacency)
    while remaining:
        start = min(remaining)
        stack = [start]
        component = set()
        while stack:
            atom = stack.pop()
            if atom in component:
                continue
            component.add(atom)
            stack.extend(adjacency[atom] - component)
        remaining -= component
        components.append(component)
    return components


def _r_group_candidates(mol: Chem.Mol) -> list[list[int]]:
    candidates = []
    for bond in _eligible_bonds(mol):
        components = _components_after_cuts(mol, {bond})
        if len(components) != 2:
            continue
        retained = max(components, key=lambda atoms: (len(atoms), tuple(sorted(atoms))))
        if len(retained) >= 5:
            candidates.append(sorted(retained))
    return candidates


def _linker_candidates(mol: Chem.Mol) -> list[list[int]]:
    bonds = _eligible_bonds(mol)
    candidates = []
    for index, first in enumerate(bonds):
        for second in bonds[index + 1 :]:
            components = _components_after_cuts(mol, {first, second})
            if len(components) != 3:
                continue
            linker = next(
                (
                    component
                    for component in components
                    if component.intersection(first) and component.intersection(second)
                ),
                None,
            )
            if linker is None or len(linker) < 2:
                continue
            retained_components = [component for component in components if component is not linker]
            if len(retained_components) != 2 or min(map(len, retained_components)) < 5:
                continue
            candidates.append(sorted(set().union(*retained_components)))
    return candidates


def _murcko_indices(mol: Chem.Mol) -> list[int]:
    scaffold = MurckoScaffold.GetScaffoldForMol(mol)
    if scaffold.GetNumAtoms() == 0:
        raise ValueError("Reference ligand has no Bemis-Murcko scaffold")
    return [atom.GetAtomMapNum() - 1 for atom in scaffold.GetAtoms()]


def _anchor_indices(mol: Chem.Mol, retained: list[int]) -> list[int]:
    retained_set = set(retained)
    return sorted(
        atom_idx
        for atom_idx in retained
        if any(neighbor.GetIdx() not in retained_set for neighbor in mol.GetAtomWithIdx(atom_idx).GetNeighbors())
    )


def _subset_mol(mol: Chem.Mol, retained: list[int]) -> Chem.Mol:
    editable = Chem.RWMol(Chem.Mol(mol))
    # Resolve aromatic valence before cutting substituents from aromatic nitrogens.
    Chem.Kekulize(editable, clearAromaticFlags=True)
    retained_set = set(retained)
    for atom_idx in range(mol.GetNumAtoms() - 1, -1, -1):
        if atom_idx not in retained_set:
            editable.RemoveAtom(atom_idx)
    fragment = editable.GetMol()
    Chem.SanitizeMol(fragment)
    return fragment


def _preview_molblock(mol: Chem.Mol) -> str:
    preview = Chem.Mol(mol)
    if preview.GetNumConformers():
        preview.RemoveAllConformers()
    rdDepictor.Compute2DCoords(preview)
    return Chem.MolToMolBlock(preview, forceV3000=True)


def _check_custom_graph(edited: Chem.Mol) -> None:
    if edited.GetNumAtoms() < MIN_CUSTOM_FRAGMENT_ATOMS:
        raise DeleteEditValidationError("DELETE_EDIT_TOO_SMALL", f"Keep at least {MIN_CUSTOM_FRAGMENT_ATOMS} atoms.")
    if not any(atom.GetAtomicNum() > 1 for atom in edited.GetAtoms()):
        raise DeleteEditValidationError("DELETE_EDIT_ONLY_HYDROGEN", "Keep at least one atom other than hydrogen.")
    try:
        Chem.SanitizeMol(edited)
    except ValueError as exc:
        raise DeleteEditValidationError("DELETE_EDIT_INVALID_MOLFILE", "Custom edit is not a valid molecule") from exc


def _validate_custom_edit(reference: Chem.Mol, molfile: str, *, validate_graph: bool = False) -> list[int]:
    edited = Chem.MolFromMolBlock(molfile, removeHs=not validate_graph, sanitize=not validate_graph)
    if edited is None:
        raise DeleteEditValidationError("DELETE_EDIT_INVALID_MOLFILE", "Custom edit is not a valid molecule")
    if validate_graph:
        _check_custom_graph(edited)
    if edited.GetNumAtoms() == 0 or edited.GetNumAtoms() >= reference.GetNumAtoms():
        raise DeleteEditValidationError("DELETE_EDIT_UNCHANGED", "Custom edit must delete at least one atom")

    mapped = [atom.GetAtomMapNum() for atom in edited.GetAtoms()]
    has_atom_maps = any(mapped)
    if has_atom_maps:
        if not all(1 <= index <= reference.GetNumAtoms() for index in mapped) or len(set(mapped)) != len(mapped):
            raise DeleteEditValidationError(
                "ATOM_MAPPING_INVALID", "ATOM_MAPPING_INVALID: preserve the unique atom maps of the reference ligand"
            )
        retained = sorted(index - 1 for index in mapped)
        expected_fragment = _subset_mol(reference, retained)
        # Compare the mapped retained graphs after aromaticity and valence have been
        # recomputed. Exact atom maps also avoid enumerating matches for repeated fragments.
        edited_smiles = Chem.MolToSmiles(edited)
        if edited_smiles == Chem.MolToSmiles(expected_fragment):
            return retained

        # Opening a ring may expose an alkene configuration that the editor now
        # specifies. Read it from the retained 3D coordinates without atom-map
        # labels, which can make equivalent substituents appear distinct.
        if expected_fragment.GetNumConformers() and expected_fragment.GetConformer().Is3D():
            atoms = list(expected_fragment.GetAtoms())
            atom_maps = [atom.GetAtomMapNum() for atom in atoms]
            for atom in atoms:
                atom.SetAtomMapNum(0)
            Chem.AssignStereochemistryFrom3D(expected_fragment, replaceExistingTags=False)
            Chem.AssignStereochemistry(expected_fragment, cleanIt=True, force=True)
            for atom, atom_map in zip(atoms, atom_maps):
                atom.SetAtomMapNum(atom_map)
            if edited_smiles == Chem.MolToSmiles(expected_fragment):
                return retained

    matches = reference.GetSubstructMatches(edited, uniquify=False, useChirality=True, maxMatches=4096)
    if len(matches) >= 4096:
        raise DeleteEditValidationError("ATOM_MAPPING_AMBIGUOUS", "ATOM_MAPPING_AMBIGUOUS: too many matches; select an explicit candidate")
    valid = set()
    for match in matches:
        if has_atom_maps and any(index + 1 != mapped[i] for i, index in enumerate(match)):
            continue
        edited_indices = {reference_idx: edited_idx for edited_idx, reference_idx in enumerate(match)}
        if all(
            begin not in edited_indices or end not in edited_indices
            or edited.GetBondBetweenAtoms(edited_indices[begin], edited_indices[end]) is not None
            for begin, end in ((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()) for bond in reference.GetBonds())
        ):
            valid.add(tuple(sorted(match)))
    if len(valid) == 1:
        return list(next(iter(valid)))
    if len(valid) > 1:
        raise DeleteEditValidationError("ATOM_MAPPING_AMBIGUOUS", "ATOM_MAPPING_AMBIGUOUS: preserve reference atom maps or select an explicit candidate")
    raise DeleteEditValidationError(
        "DELETE_EDIT_NOT_DELETION", "Custom edit may only delete atoms and their attached bonds; reference maps must match"
    )


def _candidate_id(mode: str, retained: list[int], anchors: list[int]) -> str:
    value = json.dumps(
        {"mode": mode, "retained": retained, "anchors": anchors},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _plain_smiles(mol: Chem.Mol) -> str:
    plain = Chem.Mol(mol)
    for atom in plain.GetAtoms():
        atom.ClearProp("molAtomMapNumber")
    return Chem.MolToSmiles(plain)
