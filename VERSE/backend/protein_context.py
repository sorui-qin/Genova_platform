import math
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status


EXCLUDED_LIGAND_NAMES = {
    "HOH",
    "WAT",
    "DOD",
    "EDO",
    "GOL",
    "PEG",
    "PG4",
    "MPD",
    "DMS",
    "CL",
    "NA",
    "MG",
    "ZN",
    "CA",
    "FE",
    "MN",
    "CO",
    "CU",
    "NI",
    "K",
    "CD",
    "HG",
    "CS",
    "SR",
    "BA",
    "PB",
    "AU",
    "AG",
    "PT",
    "PD",
    "LI",
    "AL",
    "HEM",
    "HEC",
    "HEO",
    "FAD",
    "FMN",
    "NAD",
    "NAP",
    "NDP",
    "NAH",
    "NAI",
    "PLP",
    "PMP",
    "TPP",
    "TDP",
    "SAM",
    "SAH",
    "COA",
}


def _residue_key(ref: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(ref.get("chain_id") or ""),
        int(ref.get("residue_number")),
        str(ref.get("insertion_code") or ""),
        str(ref.get("residue_name") or "").upper(),
    )


def _normalize_ref(ref: dict[str, Any]) -> dict[str, Any]:
    try:
        chain_id, residue_number, insertion_code, residue_name = _residue_key(ref)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid residue reference") from exc
    if not residue_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid residue reference")
    return {
        "chain_id": chain_id,
        "residue_name": residue_name,
        "residue_number": residue_number,
        "insertion_code": insertion_code,
    }


def _read_atoms(path: Path) -> list[dict[str, Any]]:
    atoms: OrderedDict[tuple[str, str, int, str, str, str], dict[str, Any]] = OrderedDict()
    lines = []
    saw_model = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        record = line[:6].strip().upper()
        if record == "MODEL":
            if saw_model:
                break
            saw_model = True
            continue
        if record == "ENDMDL" and saw_model:
            break
        if record in {"ATOM", "HETATM"}:
            lines.append(line)

    occupancy: dict[tuple[str, int, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for line in lines:
        alt_loc = line[16:17].strip()
        if not alt_loc:
            continue
        try:
            residue_number = int(line[22:26].strip())
            occupancy[(line[21:22].strip(), residue_number, line[26:27].strip(), line[17:20].strip().upper())][
                alt_loc
            ] += float(line[54:60].strip() or 0)
        except ValueError:
            continue
    selected_altloc = {
        key: min(scores, key=lambda alt: (-scores[alt], alt != "A", alt))
        for key, scores in occupancy.items()
    }

    for line in lines:
        record = line[:6].strip().upper()
        alt_loc = line[16:17].strip()
        try:
            residue_number = int(line[22:26].strip())
            coord = [float(line[30:38]), float(line[38:46]), float(line[46:54])]
        except ValueError:
            continue
        residue_name = line[17:20].strip().upper()
        chain_id = line[21:22].strip()
        insertion_code = line[26:27].strip()
        if alt_loc and alt_loc != selected_altloc.get((chain_id, residue_number, insertion_code, residue_name)):
            continue
        atom_name = line[12:16].strip()
        element = line[76:78].strip().upper()
        if not element:
            element = "".join(char for char in atom_name if char.isalpha())[:1].upper()
        key = (record, chain_id, residue_number, insertion_code, residue_name, atom_name)
        atom = {
            "record": record,
            "chain_id": chain_id,
            "residue_number": residue_number,
            "insertion_code": insertion_code,
            "residue_name": residue_name,
            "atom_name": atom_name,
            "element": element,
            "coord": coord,
        }
        if key not in atoms or alt_loc == "":
            atoms[key] = atom
    return list(atoms.values())


def calculate_bounds_center(coords: list[list[float]]) -> list[float]:
    if not coords:
        raise ValueError("coordinates are empty")
    return [(min(axis) + max(axis)) / 2 for axis in zip(*coords)]


def calculate_centroid(coords: list[list[float]]) -> list[float]:
    if not coords:
        raise ValueError("coordinates are empty")
    return [sum(axis) / len(coords) for axis in zip(*coords)]


def calculate_ligand_box(coords: list[list[float]]) -> dict[str, list[float]]:
    center = calculate_bounds_center(coords)
    spans = [max(axis) - min(axis) for axis in zip(*coords)]
    diameter = max(
        (
            math.dist(left, right)
            for index, left in enumerate(coords)
            for right in coords[index + 1 :]
        ),
        default=0.0,
    )
    return {
        "center": center,
        "size": [max(span + 8.0, diameter) for span in spans],
    }


def coordinates_inside_box(coords: list[list[float]], box: dict[str, Any]) -> bool:
    center = _triplet(box.get("center"), "box.center")
    size = _triplet(box.get("size"), "box.size", positive=True)
    return all(
        all(abs(coord[axis] - center[axis]) <= size[axis] / 2 + 1e-6 for axis in range(3))
        for coord in coords
    )


def get_residue_coordinates(path: Path, residues: list[dict[str, Any]]) -> list[list[float]]:
    wanted = {_residue_key(ref) for ref in residues}
    return [
        atom["coord"]
        for atom in _read_atoms(path)
        if atom["record"] == "ATOM"
        and atom["element"] not in {"H", "D"}
        and (
            atom["chain_id"],
            atom["residue_number"],
            atom["insertion_code"],
            atom["residue_name"],
        )
        in wanted
    ]


def get_ligand_coordinates(path: Path, ligand: dict[str, Any]) -> list[list[float]]:
    wanted = _residue_key(ligand)
    return [
        atom["coord"]
        for atom in _read_atoms(path)
        if atom["record"] == "HETATM"
        and atom["element"] not in {"H", "D"}
        and (
            atom["chain_id"],
            atom["residue_number"],
            atom["insertion_code"],
            atom["residue_name"],
        )
        == wanted
    ]


def parse_protein_pdb(path: Path) -> dict[str, Any]:
    atoms = _read_atoms(path)
    residue_atoms: OrderedDict[tuple[str, int, str, str], list[dict[str, Any]]] = OrderedDict()
    ligand_atoms: OrderedDict[tuple[str, int, str, str], list[dict[str, Any]]] = OrderedDict()
    for atom in atoms:
        key = (
            atom["chain_id"],
            atom["residue_number"],
            atom["insertion_code"],
            atom["residue_name"],
        )
        target = residue_atoms if atom["record"] == "ATOM" else ligand_atoms
        target.setdefault(key, []).append(atom)

    residues = []
    chain_counts: OrderedDict[str, int] = OrderedDict()
    for (chain_id, residue_number, insertion_code, residue_name), rows in residue_atoms.items():
        heavy_coords = [row["coord"] for row in rows if row["element"] not in {"H", "D"}]
        if not heavy_coords:
            continue
        chain_counts[chain_id] = chain_counts.get(chain_id, 0) + 1
        residues.append(
            {
                "chain_id": chain_id,
                "residue_number": residue_number,
                "insertion_code": insertion_code,
                "residue_name": residue_name,
                "center": calculate_centroid(heavy_coords),
                "heavy_atom_count": len(heavy_coords),
            }
        )

    ligands = []
    for (chain_id, residue_number, insertion_code, residue_name), rows in ligand_atoms.items():
        heavy_coords = [row["coord"] for row in rows if row["element"] not in {"H", "D"}]
        if residue_name in EXCLUDED_LIGAND_NAMES or len(heavy_coords) < 3:
            continue
        axes = list(zip(*heavy_coords))
        bounds_min = [min(axis) for axis in axes]
        bounds_max = [max(axis) for axis in axes]
        ligands.append(
            {
                "key": f"{chain_id}:{residue_name}:{residue_number}:{insertion_code}",
                "chain_id": chain_id,
                "residue_name": residue_name,
                "residue_number": residue_number,
                "insertion_code": insertion_code,
                "atom_count": len(rows),
                "heavy_atom_count": len(heavy_coords),
                "center": [(low + high) / 2 for low, high in zip(bounds_min, bounds_max)],
                "bounds": {"min": bounds_min, "max": bounds_max},
                "box": calculate_ligand_box(heavy_coords),
            }
        )
    ligands.sort(key=lambda item: item["heavy_atom_count"], reverse=True)
    return {
        "version": 2,
        "chains": [{"chain_id": chain_id, "residue_count": count} for chain_id, count in chain_counts.items()],
        "residues": residues,
        "ligands": ligands,
    }
