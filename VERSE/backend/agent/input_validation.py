"""Bounded parsing for Agent protein and ligand inputs, without shell execution."""
import json
import math
import subprocess
import sys
from pathlib import Path

from fastapi import HTTPException


def validate_structure_input(path, kind, values=None):
    limit = (10 if kind == "ligand" else 50) * 1024 * 1024
    if Path(path).stat().st_size > limit:
        raise HTTPException(413, "Structure input exceeds its size limit")
    try:
        result = subprocess.run([sys.executable, "-m", "backend.agent.input_validation", kind, str(path)],
            input=json.dumps(values or {}), text=True, capture_output=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, "Structure parsing exceeded 30 seconds") from exc
    if result.returncode:
        try:
            error = json.loads(result.stdout)["error"]
        except (ValueError, KeyError):
            error = "Structure input could not be parsed"
        raise HTTPException(422, error)
    return json.loads(result.stdout)


def _parse(kind, path, values):
    if kind == "ligand":
        from rdkit import Chem
        suffix = path.suffix.lower()
        if suffix == ".sdf":
            molecules = list(Chem.SDMolSupplier(str(path), removeHs=False))
            if len(molecules) != 1:
                raise ValueError("Reference ligand must contain exactly one molecule; choose a single molecule")
            mol = molecules[0]
        elif suffix == ".mol":
            mol = Chem.MolFromMolFile(str(path), removeHs=False)
        elif suffix == ".mol2":
            mol = Chem.MolFromMol2File(str(path), removeHs=False)
        else:
            raise ValueError("Reference ligand requires SDF, MOL or MOL2")
        if mol is None or not mol.GetNumHeavyAtoms() or not mol.GetNumConformers() or not mol.GetConformer().Is3D():
            raise ValueError("Reference ligand requires valid heavy atoms and 3D coordinates")
        if not all(math.isfinite(v) for point in mol.GetConformer().GetPositions() for v in point):
            raise ValueError("Reference ligand coordinates must be finite")
        return {"valid": True, "molecule_count": 1}
    if path.suffix.lower() != ".pdb":
        raise ValueError("Protein requires a PDB file")
    count = 0
    for line in path.read_text().splitlines():
        if line[:6].strip() in {"ATOM", "HETATM"}:
            count += 1
            if not all(math.isfinite(float(line[start:start + 8])) for start in (30, 38, 46)):
                raise ValueError("Protein coordinates must be finite")
    if not count:
        raise ValueError("Protein contains no atoms")
    from backend.protein_context import parse_protein_pdb
    if kind != "protein":
        raise ValueError("Input kind must be protein or ligand")
    return parse_protein_pdb(path)


if __name__ == "__main__":
    try:
        print(json.dumps(_parse(sys.argv[1], Path(sys.argv[2]), json.load(sys.stdin)), allow_nan=False))
    except (ValueError, OSError, HTTPException) as exc:
        print(json.dumps({"error": exc.detail if isinstance(exc, HTTPException) else str(exc)}))
        sys.exit(1)
