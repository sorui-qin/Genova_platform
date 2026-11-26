import argparse
import hashlib
import importlib.metadata
import json
import math
import string
import subprocess
import sys
from pathlib import Path


PDB2PQR_VERSION = "3.6.2"
VALIDATION_VERSION = 1
AMINO_ACIDS = set("ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL".split())


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_hydrogen(line):
    element = line[76:78].strip().upper()
    return (element or line[12:16].strip().lstrip("0123456789")[:1].upper()) in {"H", "D"}


def residue_id(line):
    return line[21:22].strip(), int(line[22:26]), line[26:27].strip()


def protein_residues(path):
    residues = []
    seen = set()
    boundary = False
    for line in Path(path).read_text().splitlines():
        record = line[:6].strip()
        if record == "TER":
            boundary = True
        if record != "ATOM":
            continue
        key = residue_id(line)
        if not residues or key != residues[-1]["key"] or boundary:
            if key in seen:
                raise ValueError(f"Duplicate protein residue identity: {key}")
            seen.add(key)
            residues.append({"key": key, "name": line[17:20].strip(), "lines": [], "boundary": boundary})
            boundary = False
        row = residues[-1]
        if row["name"] != line[17:20].strip():
            raise ValueError(f"Multiple residue names at {key}; select one alternate conformation")
        xyz = [float(line[30:38]), float(line[38:46]), float(line[46:54])]
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError(f"Non-finite protein coordinates at {key}")
        row["lines"].append(line)
    if not residues:
        raise ValueError("Protein contains no ATOM records")
    for row in residues:
        names = [line[12:16].strip() for line in row["lines"]]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate atom names at {row['key']}; select one alternate conformation")
    return residues


def segment_protein(source, target, *, remove_hydrogens=False, renumber=False):
    rows = protein_residues(source)
    output = []
    mapping = {}
    chain_map = {}
    breaks = []
    removed_hydrogens = 0
    segment = -1
    number = 0
    previous = None
    letters = string.ascii_uppercase + string.ascii_lowercase + string.digits
    for row in rows:
        atoms = {line[12:16].strip(): [float(line[30:38]), float(line[38:46]), float(line[46:54])] for line in row["lines"]}
        distance = None
        reason = None
        if previous is not None:
            if "C" in previous["atoms"] and "N" in atoms:
                distance = math.dist(previous["atoms"]["C"], atoms["N"])
            if row["boundary"]:
                reason = "explicit_ter"
            elif previous["key"][0] != row["key"][0]:
                reason = "chain_change"
            elif "OXT" in previous["atoms"]:
                reason = "terminal_atom"
            elif distance is None:
                reason = "missing_backbone_atom"
            elif distance > 2.0:
                reason = "backbone_distance"
            if reason and previous["key"][0] == row["key"][0]:
                gap = {
                    "chain_id": row["key"][0],
                    "after_residue": str(previous["key"][1]),
                    "after_insertion_code": previous["key"][2],
                    "before_residue": str(row["key"][1]),
                    "before_insertion_code": row["key"][2],
                    "distance_angstrom": round(distance, 3) if distance is not None else None,
                    "reason": reason,
                }
                breaks.append(gap)
        if previous is None or reason:
            if previous is not None:
                output.append("TER")
            segment += 1
            number = 0
            if segment >= len(letters):
                raise ValueError("Protein has more than 62 disconnected fragments; prepare a smaller structure")
            chain_map[letters[segment]] = row["key"][0]
        number += 1
        tool_number = number if renumber else row["key"][1]
        insertion = "" if renumber else row["key"][2]
        tool_key = (letters[segment], tool_number, insertion)
        mapping[tool_key] = row["key"]
        for line in row["lines"]:
            if remove_hydrogens and is_hydrogen(line):
                removed_hydrogens += 1
                continue
            output.append(f"{line[:21]}{letters[segment]}{tool_number:4d}{insertion or ' '}{line[27:]}")
        previous = {**row, "atoms": atoms}
    Path(target).write_text("\n".join([*output, "TER", "END"]) + "\n")
    return {"mapping": mapping, "chain_map": chain_map, "breaks": breaks, "segment_count": segment + 1, "removed_hydrogens": removed_hydrogens}


def restore_pdb(source, target, *, mapping=None, chain_map=None):
    output = []
    for line in Path(source).read_text().splitlines():
        record = line[:6].strip()
        if record in {"ATOM", "HETATM"}:
            chain, number, insertion = residue_id(line)
            if mapping is not None:
                key = (chain, number, insertion)
                if key not in mapping:
                    raise ValueError(f"PDB2PQR changed residue identity unexpectedly: {key}")
                chain, number, insertion = mapping[key]
            elif chain_map is not None:
                chain = chain_map[chain]
            line = f"{line[:21]}{chain or ' '}{number:4d}{insertion or ' '}{line[27:]}"
        elif record == "TER":
            line = "TER"
        elif record != "END":
            continue
        output.append(line)
    Path(target).write_text("\n".join(output) + "\n")


def check_heavy_atoms(path, *, allow_terminal_atoms=False):
    from pdb2pqr import aa, io
    from pdb2pqr.main import setup_molecule

    records, errors = io.get_molecule(str(path))
    if errors:
        raise ValueError(f"PDB2PQR could not parse protein records: {errors}")
    molecule, _, _ = setup_molecule(records, io.get_definitions(), None)
    molecule.set_termini(False, False)
    molecule.update_bonds()
    molecule.num_missing_heavy
    for residue in molecule.residues:
        if not isinstance(residue, aa.Amino):
            raise ValueError(f"Unsupported protein residue: {residue}")
        missing = [name for name in residue.missing if not (allow_terminal_atoms and name == "OXT")]
        unknown = [atom.name for atom in residue.atoms if not atom.has_reference and not atom.is_hydrogen]
        if missing or unknown:
            raise ValueError(f"PDB2PQR incompatible residue {residue}: missing atoms {missing}; unknown atoms {unknown}")


def pdb2pqr_command(protein_input, pqr_output, pdb_output, options, ph, *, assign_only=False, apbs_input=None):
    command = [sys.executable, "-m", "pdb2pqr", "--ff=PARSE", "--keep-chain"]
    if assign_only:
        command.append("--assign-only")
    else:
        if options["update_protonation"]:
            command.extend(["--titration-state-method=propka", f"--with-ph={ph}"])
        if not options["optimize_hydrogen_bonds"]:
            command.append("--noopt")
        if not options["repair_structure"]:
            command.append("--nodebump")
    if apbs_input is not None:
        command.extend(["--apbs-input", str(apbs_input)])
    return [*command, f"--pdb-output={pdb_output}", str(protein_input), str(pqr_output)]


def run_pdb2pqr(protein_input, pqr_output, pdb_output, options, ph, *, assign_only=False, apbs_input=None):
    version = importlib.metadata.version("pdb2pqr")
    if version != PDB2PQR_VERSION:
        raise ValueError(f"PDB2PQR {PDB2PQR_VERSION} required; installed {version}")
    pqr_output = Path(pqr_output)
    tool_input = pqr_output.with_name(pqr_output.stem + "_input.pdb")
    tool_output = pqr_output.with_name(pqr_output.stem + "_tool.pdb")
    segments = segment_protein(protein_input, tool_input, remove_hydrogens=not assign_only, renumber=True)
    if assign_only:
        rows = protein_residues(tool_input)
        sulfur = {row["key"]: [float(line[30:38]), float(line[38:46]), float(line[46:54])] for row in rows for line in row["lines"] if row["name"] == "CYS" and line[12:16].strip() == "SG"}
        names = {}
        for row in rows:
            atoms = {line[12:16].strip() for line in row["lines"]}
            name = row["name"]
            if name == "ASP" and "HD2" in atoms:
                name = "ASH"
            elif name == "GLU" and "HE2" in atoms:
                name = "GLH"
            elif name == "LYS" and "HZ3" not in atoms:
                name = "LYN"
            elif name == "TYR" and "HH" not in atoms:
                name = "TYM"
            elif name == "CYS" and "HG" not in atoms and row["key"] in sulfur:
                # ponytail: infer S-S bonds within 2.5 Å; preserve explicit bond states if distorted disulfides must be supported.
                bonded = any(key != row["key"] and math.dist(sulfur[row["key"]], point) < 2.5 for key, point in sulfur.items())
                name = "CYX" if bonded else "CYM"
            names[row["key"]] = name
        tool_input.write_text("\n".join(line[:17] + names[residue_id(line)] + line[20:] if line.startswith("ATOM") else line for line in tool_input.read_text().splitlines()) + "\n")
    check_heavy_atoms(tool_input, allow_terminal_atoms=not assign_only)
    command = pdb2pqr_command(tool_input, pqr_output, tool_output, options, ph, assign_only=assign_only, apbs_input=apbs_input)
    result = subprocess.run(command, capture_output=True, text=True)
    log = pqr_output.with_suffix(".stderr.log")
    log.write_text(result.stdout + "\n" + result.stderr)
    if result.returncode:
        raise RuntimeError(f"PDB2PQR failed (exit {result.returncode}); see {log.name}: {result.stderr.strip()[-1800:]}")
    if apbs_input is not None:
        apbs_path = Path(apbs_input)
        apbs_path.write_text("\n".join(f"    write pot dx {pqr_output.with_suffix('')}" if line.strip().startswith("write pot dx ") else line for line in apbs_path.read_text().splitlines()) + "\n")
    pdb_atoms = {
        (*residue_id(line)[:2], line[12:16].strip()): line
        for line in tool_output.read_text().splitlines() if line.startswith("ATOM")
    }
    charge_atoms = {}
    for line in pqr_output.read_text().splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        fields = line.split()
        if len(fields) != 11:
            raise ValueError(f"Invalid PQR atom record: {line}")
        xyz_charge_radius = list(map(float, fields[-5:]))
        if not all(math.isfinite(value) for value in xyz_charge_radius) or xyz_charge_radius[-1] < 0:
            raise ValueError(f"Invalid PQR coordinates, charge or radius: {line}")
        key = (fields[4], int(fields[5]), fields[2])
        if key in charge_atoms:
            raise ValueError(f"Duplicate PQR atom: {key}")
        if xyz_charge_radius[-1] == 0 and key in pdb_atoms and not is_hydrogen(pdb_atoms[key]):
            raise ValueError(f"Zero radius for protein heavy atom: {key}")
        charge_atoms[key] = xyz_charge_radius
    if not charge_atoms or set(pdb_atoms) != set(charge_atoms):
        missing = sorted(set(pdb_atoms) - set(charge_atoms))
        raise ValueError(f"PDB2PQR parameter coverage is incomplete; missing atoms: {missing[:20]}")
    heavy_before = {(*residue_id(line)[:2], line[12:16].strip()) for line in tool_input.read_text().splitlines() if line.startswith("ATOM") and not is_hydrogen(line)}
    if not heavy_before.issubset(charge_atoms):
        raise ValueError(f"PDB2PQR removed protein heavy atoms: {sorted(heavy_before - set(charge_atoms))[:20]}")
    if assign_only:
        before = {(*residue_id(line)[:2], line[12:16].strip()): [float(line[30:38]), float(line[38:46]), float(line[46:54])] for line in tool_input.read_text().splitlines() if line.startswith("ATOM")}
        if set(before) != set(charge_atoms) or any(math.dist(point, charge_atoms[key][:3]) > 0.002 for key, point in before.items()):
            raise ValueError("PDB2PQR assignment changed final protein atoms or coordinates")
    restore_pdb(tool_output, pdb_output, mapping=segments["mapping"])
    warnings = list(dict.fromkeys(line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if "WARNING" in line.upper()))
    return {"pdb2pqr_version": version, "parameterized_atoms": len(charge_atoms), "warnings": warnings, "log_file": str(log), "residue_mapping": [{"tool_chain_id": tool[0], "tool_residue_number": tool[1], "chain_id": original[0], "residue_number": original[1], "insertion_code": original[2]} for tool, original in segments["mapping"].items()]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pdb-output", required=True)
    parser.add_argument("--apbs-input", required=True)
    parser.add_argument("--ph", type=float, default=7.4)
    args = parser.parse_args()
    if not math.isfinite(args.ph) or not 0 <= args.ph <= 14:
        parser.error("pH must be between 0 and 14")
    result = run_pdb2pqr(args.input, args.output, args.pdb_output, {"repair_structure": True, "update_protonation": True, "optimize_hydrogen_bonds": False}, args.ph, apbs_input=args.apbs_input)
    Path(args.output).with_suffix(".validation.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
