from pathlib import Path
import os


def gnina_command(payload, input_sdf, output_sdf, mode, cpus):
    box = payload['box']
    cmd = [os.environ.get('GNINA_BIN', 'gnina'), '-r', payload['protein_pdb'], '-l', str(input_sdf), '-o', str(output_sdf),
           '--cnn', 'fast', '--cnn_scoring', 'rescore', '--exhaustiveness', '8', '--num_modes', '1', '--seed', '42', '--cpu', str(cpus)]
    for name in ('center', 'size'):
        for axis, value in zip('xyz', box[name]):
            cmd += [f'--{name}_{axis}', str(value)]
    if os.environ.get('TARPASS_GNINA_NO_GPU', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        cmd.append('--no_gpu')
    if mode == 'original':
        cmd.append('--score_only')
    return cmd


INTERACTION_TYPES = {'H-Bond', 'H-Bond donor', 'H-Bond acceptor', 'Halogen bond', 'Hydrophobic contact', 'Pi-cation lAro', 'Pi-cation pAro', 'Pi-stacking', 'Salt Bridge lneg', 'Salt Bridge pneg'}


def residue_id(residue):
    return f"{residue['chain_id']}|{residue['residue_name']}|{residue['residue_number']}|{residue.get('insertion_code', '')}"


def protein_residues(path):
    if Path(path).suffix.lower() in {'.cif', '.mmcif'}:
        from genova_runtime.structure_inventory import source_inventory
        from genova_runtime.pdb2pqr_compat import file_sha256
        manifest = source_inventory(Path(path), {'sha256': file_sha256(path), 'model_id': '1'})
        return list({a['residue_id']: {'chain_id': a['author_chain_id'], 'residue_name': a['residue_name'],
            'residue_number': a['author_residue_number'], 'insertion_code': a['insertion_code']}
            for c in manifest['components'] for a in c['atoms'] if c['selection_kind'] == 'chain_records'}.values())
    residues = {}
    for line in Path(path).read_text().splitlines():
        if line.startswith(('ATOM  ', 'HETATM')):
            residue = {'chain_id': line[21:22].strip(), 'residue_name': line[17:20].strip(), 'residue_number': int(line[22:26]), 'insertion_code': line[26:27].strip()}
            residues[residue_id(residue)] = residue
    return list(residues.values())


def validate_interactions(rules, residues):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError('key_interactions must be a list of at most 100 rules')
    allowed = {residue_id(r) for r in residues}
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get('interaction_type'), str) or not isinstance(rule.get('match_mode'), str) or rule['interaction_type'] not in INTERACTION_TYPES or rule['match_mode'] not in {'any', 'all'}:
            raise ValueError('Invalid interaction type or match_mode')
        selected = rule.get('residues')
        if not isinstance(selected, list) or not selected or len(selected) > len(allowed):
            raise ValueError('Select at least one receptor residue per rule')
        for residue in selected:
            if not isinstance(residue, dict) or not {'chain_id', 'residue_name', 'residue_number'} <= residue.keys() or residue_id(residue) not in allowed:
                raise ValueError('Interaction residue is not present in the prepared receptor')
    return rules
