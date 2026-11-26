import hashlib
import math
from itertools import product
from pathlib import Path

METAL_ELEMENTS = set('LI BE NA MG AL K CA SC TI V CR MN FE CO NI CU ZN GA RB SR Y ZR NB MO TC RU RH PD AG CD IN SN CS BA LA CE PR ND PM SM EU GD TB DY HO ER TM YB LU HF TA W RE OS IR PT AU HG TL PB BI PO FR RA AC TH PA U NP PU AM CM BK CF ES FM MD NO LR RF DB SG BH HS MT DS RG CN NH FL MC LV'.split())


def component_manifest(path: Path, source: dict, version=2, *, analyze_connections=True):
    if type(version) is not int or version != 2:
        raise ValueError('Unsupported component manifest version')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != source["sha256"]:
        raise ValueError("Source structure SHA256 mismatch")
    prefix = f'{source["sha256"]}:{source["model_id"]}'
    components = {}
    residues = {}
    seen_atoms = set()
    model_id, segment, models = "1", 0, set()
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), 1):
        record = line[:6].strip()
        if record == "MODEL":
            model_id = line[10:14].strip()
            if not model_id or model_id in models:
                raise ValueError("Missing or duplicate PDB model ID")
            models.add(model_id)
            segment = 0
        elif record == "ENDMDL":
            model_id = ""
        elif model_id == source["model_id"] and record == "TER":
            segment += 1
        elif model_id == source["model_id"] and record in {"ATOM", "HETATM"}:
            chain = line[21:22].strip()
            chain_instance = f"{prefix}:chain:{segment}:{chain}"
            residue_key = (chain_instance, line[22:26], line[26:27], line[17:20])
            residue_id = residues.setdefault(residue_key, f"{prefix}:residue:{line_number}")
            atom_key = (residue_id, line[12:16], line[16:17])
            if atom_key in seen_atoms:
                raise ValueError("Ambiguous duplicate PDB atom identity")
            seen_atoms.add(atom_key)
            component_id = chain_instance if record == "ATOM" else f"{residue_id}:heterogen"
            component = components.setdefault(component_id, {
                "component_id": component_id,
                "selection_kind": "chain_records" if record == "ATOM" else "heterogen_residue_records",
                "atoms": [],
            })
            element = line[76:78].strip().upper()
            if not element:
                letters = ''.join(char for char in line[12:16] if char.isalpha()).upper()
                element = letters[:1] if letters and (record == 'ATOM' or len(letters) == 1) else '?'
            component["atoms"].append({
                "atom_id": f"{prefix}:record:{line_number}", "residue_id": residue_id,
                "chain_instance_id": chain_instance, "source_record": line_number,
                "record_type": record, "author_chain_id": chain,
                "author_residue_number": int(line[22:26]), "insertion_code": line[26:27].strip(),
                "residue_name": line[17:20].strip(), "atom_name": line[12:16].strip(),
                "altloc": line[16:17].strip(),
                "element": element,
                "coordinates": [float(line[30:38]), float(line[38:46]), float(line[46:54])],
                'occupancy': float(line[54:60]),
            })
    if analyze_connections:
        merge_polymer_records(components)
    result = {"version": version, "source": source, "coordinate_frame_id": f"{prefix}:source",
            "coordinate_unit": "angstrom", "chemistry_status": "not_evaluated", "components": list(components.values())}
    if not analyze_connections:
        return result
    connections = component_connections(path, result, include_external=True)
    result['declared_connections'] = [edge for edge in connections if 'symmetry_operations' not in edge]
    result['external_coordination_connections'] = [edge for edge in connections if 'symmetry_operations' in edge]
    result['selection_groups'] = selection_groups(result)
    return result


def connection_kind(link, components):
    if link['evidence'] in {'SSBOND', 'CIF:disulf', 'CIF:covale'}:
        return 'covalent'
    if link['evidence'] not in {'LINK', 'CONECT', 'CIF:metalc'}:
        return 'uncertain'
    atoms = [next(a for a in components[cid]['atoms'] if a['atom_id'] == aid)
             for cid, aid in zip(link['component_ids'], link['atom_ids'])]
    metals = METAL_ELEMENTS
    if link['evidence'] == 'CIF:metalc':
        return 'coordination' if any(a['element'] in metals for a in atoms) else 'uncertain'
    if any(a['element'] in metals and b['element'] in {'N', 'O', 'S'} for a, b in (atoms, atoms[::-1])):
        return 'coordination'
    return 'uncertain' if any(a['element'] in metals for a in atoms) else 'covalent'


def merge_connections(connections, components):
    priorities = {'possible_covalent_distance': 0, 'LINK': 1, 'CONECT': 1,
                  'SSBOND': 2, 'CIF:covale': 3, 'CIF:disulf': 3, 'CIF:metalc': 3}
    merged = {}
    for edge in connections:
        order = sorted(range(2), key=lambda i: edge['atom_ids'][i])
        edge = {**edge, 'atom_ids': [edge['atom_ids'][i] for i in order],
                'component_ids': [edge['component_ids'][i] for i in order]}
        if 'symmetry_operations' in edge:
            edge['symmetry_operations'] = [edge['symmetry_operations'][i] for i in order]
        key = (*edge['atom_ids'], *(s.replace('_', '') for s in edge.get('symmetry_operations', [])))
        previous = merged.get(key)
        priority = priorities[edge['evidence']]
        if previous and (priority == priorities[previous['evidence']] > 0 or min(priority, priorities[previous['evidence']]) >= 2) and connection_kind(previous, components) != connection_kind(edge, components):
            raise ValueError('Conflicting explicit connection types for the same atom pair')
        if previous is None or priority > priorities[previous['evidence']]:
            merged[key] = edge
    return list(merged.values())


def active_connections(manifest, connections, choices):
    atoms = {a['atom_id']: a for c in manifest['components'] for a in c['atoms']}
    return [edge for edge in connections if edge['evidence'] != 'possible_covalent_distance'
            or all(not atoms[aid]['altloc'] or atoms[aid]['residue_id'] not in choices
                   or atoms[aid]['altloc'] == choices[atoms[aid]['residue_id']] for aid in edge['atom_ids'])]


def selection_groups(manifest):
    components = {c['component_id']: c for c in manifest['components']}
    neighbors = {cid: set() for cid in components}
    for edge in manifest.get('declared_connections', []):
        left, right = edge['component_ids']
        if left == right or edge['evidence'] not in {'LINK', 'CONECT', 'CIF:covale'}:
            continue
        if components[left]['atoms'][0]['chain_instance_id'] == components[right]['atoms'][0]['chain_instance_id']:
            neighbors[left].add(right)
            neighbors[right].add(left)
    groups, visited = [], set()
    for cid in components:
        if cid in visited:
            continue
        group, pending = set(), [cid]
        while pending:
            current = pending.pop()
            if current not in group:
                group.add(current)
                pending.extend(neighbors[current] - group)
        visited.update(group)
        if len(group) > 1 and any(components[key]['selection_kind'] == 'chain_records' for key in group):
            ids = sorted(group)
            groups.append({'group_id': hashlib.sha256('|'.join(ids).encode()).hexdigest(),
                           'kind': 'polymer_with_caps', 'component_ids': ids})
    return groups



def merge_polymer_records(components):
    residues = {}
    for component in components.values():
        for atom in component['atoms']:
            residues.setdefault(atom['residue_id'], {})[atom['atom_name']] = atom
    backbone = {key: atoms for key, atoms in residues.items() if {'N', 'CA', 'C'} <= atoms.keys()}
    candidates = {c['atoms'][0]['residue_id'] for c in components.values() if c['selection_kind'] != 'chain_records' and c['atoms'][0]['residue_id'] in backbone and not any(a['altloc'] for a in c['atoms'])}
    if not candidates:
        return
    members = set()
    neighbors = {key: set() for key in candidates}
    for key in candidates:
        atoms = backbone[key]
        for other_key, other in backbone.items():
            if key == other_key or atoms['N']['chain_instance_id'] != other['N']['chain_instance_id']:
                continue
            if min(math.dist(atoms['C']['coordinates'], other['N']['coordinates']),
                   math.dist(atoms['N']['coordinates'], other['C']['coordinates'])) <= 2.0:
                neighbors[key].add(other_key)
    # A peptide-connected residue stays with its whole polymer, including HETATM modifications.
    for key, linked in neighbors.items():
        if linked:
            members.update({key, *linked})
    for cid, component in list(components.items()):
        if component['selection_kind'] == 'chain_records' or component['atoms'][0]['residue_id'] not in members:
            continue
        chain_id = component['atoms'][0]['chain_instance_id']
        target = components.setdefault(chain_id, {'component_id': chain_id, 'selection_kind': 'chain_records', 'atoms': []})
        target['atoms'].extend(component['atoms'])
        del components[cid]
    for component in components.values():
        component['atoms'].sort(key=lambda atom: atom['source_record'])


def component_connections(path, manifest, *, include_external=False, allow_external_covalent=False):
    from rdkit import Chem
    components = manifest['components']
    atoms = [dict(atom, component_id=c['component_id']) for c in components for atom in c['atoms']]
    lines = Path(path).read_text().splitlines()
    serials = {}
    for atom in atoms:
        serial = int(lines[atom['source_record'] - 1][6:11])
        serials.setdefault(serial, []).append(atom)
    links, external = [], []
    component_by_id = {c['component_id']: c for c in components}

    def link(left, right, evidence):
        if left['component_id'] != right['component_id'] or left['atom_id'] != right['atom_id']:
            key = tuple(sorted([left['atom_id'], right['atom_id']]))
            ordered = sorted([left, right], key=lambda a: a['atom_id'])
            ids = [a['component_id'] for a in ordered]
            links.append({'atom_ids': list(key), 'component_ids': ids, 'evidence': evidence})

    for line in lines:
        record = line[:6].strip()
        if record == 'CONECT':
            values = [int(line[i:i+5]) for i in range(6, len(line), 5) if line[i:i+5].strip()]
            for other in values[1:]:
                for number in (values[0], other):
                    if len(serials.get(number, [])) > 1:
                        raise ValueError('Ambiguous CONECT identity')
                if values[0] in serials and other in serials:
                    link(serials[values[0]][0], serials[other][0], 'CONECT')
        elif record in {'LINK', 'SSBOND'}:
            if record == 'LINK':
                selectors = [(line[21:22].strip(), int(line[22:26]), line[26:27].strip(), line[12:16].strip()),
                             (line[51:52].strip(), int(line[52:56]), line[56:57].strip(), line[42:46].strip())]
                altlocs = [line[16:17].strip(), line[46:47].strip()]
                symmetries = [line[59:65].strip(), line[66:72].strip()]
            else:
                selectors = [(line[15:16].strip(), int(line[17:21]), line[21:22].strip(), 'SG'),
                             (line[29:30].strip(), int(line[31:35]), line[35:36].strip(), 'SG')]
                altlocs = ['', '']
                symmetries = [line[59:65].strip(), line[66:72].strip()]
            endpoints = [[a for a in atoms if (a['author_chain_id'], a['author_residue_number'], a['insertion_code'], a['atom_name']) == ref] for ref in selectors]
            endpoints = [[a for a in rows if not alt or a['altloc'] == alt] for rows, alt in zip(endpoints, altlocs)]
            if any(not rows or len({a['residue_id'] for a in rows}) != 1 or len({a['altloc'] for a in rows}) != len(rows) for rows in endpoints):
                raise ValueError(f'Ambiguous or missing {record} endpoints')
            pairs = [(a, b) for a in endpoints[0] for b in endpoints[1] if not a['altloc'] or not b['altloc'] or a['altloc'] == b['altloc']]
            if not pairs:
                raise ValueError(f'Incompatible {record} alternate locations')
            for a, b in pairs:
                if any(symmetry not in {'', '1555'} for symmetry in symmetries):
                    edge = {'atom_ids': [a['atom_id'], b['atom_id']],
                            'component_ids': [a['component_id'], b['component_id']], 'evidence': record,
                            'symmetry_operations': [s or '1555' for s in symmetries]}
                    if connection_kind(edge, component_by_id) != 'coordination' and not allow_external_covalent:
                        raise ValueError('Chemical connection requires an explicit crystallographic assembly')
                    external.append(edge)
                else:
                    link(a, b, record)
    table = Chem.GetPeriodicTable()
    symbols = {table.GetElementSymbol(number).upper() for number in range(1, 119)} | {'D'}
    cells = {}
    for atom in atoms:
        coord = atom['coordinates']
        if not all(math.isfinite(v) for v in coord):
            raise ValueError('Non-finite atom coordinates')
        if atom['element'] not in symbols:
            raise ValueError('Unknown element; connection validation unavailable')
        cell = tuple(math.floor(v / 4) for v in coord)
        for offset in product((-1, 0, 1), repeat=3):
            for other in cells.get(tuple(a+b for a, b in zip(cell, offset)), []):
                if atom['component_id'] == other['component_id']:
                    continue
                radius = table.GetRcovalent('H' if atom['element'] == 'D' else atom['element'].title()) + table.GetRcovalent('H' if other['element'] == 'D' else other['element'].title())
                if math.dist(coord, other['coordinates']) <= radius + 0.4:
                    link(atom, other, 'possible_covalent_distance')
        cells.setdefault(cell, []).append(atom)
    connections = [*links, *manifest.get('declared_connections', [])]
    if include_external:
        connections.extend([*external, *manifest.get('external_coordination_connections', [])])
    return merge_connections(connections, component_by_id)


def validate_exclusions(manifest, exclusions, connections, *, allow_coordination=False, altloc_choices=None):
    known = {c['component_id'] for c in manifest['components']}
    excluded = set(exclusions)
    if not excluded <= known or excluded == known:
        raise ValueError('Unknown selection or empty receptor')
    crossing = [link for link in active_connections(manifest, connections, altloc_choices or {}) if (link['component_ids'][0] in excluded) != (link['component_ids'][1] in excluded)]
    if crossing and manifest['version'] == 2 and allow_coordination:
        components = {c['component_id']: c for c in manifest['components']}
        crossing = [link for link in crossing if connection_kind(link, components) != 'coordination']
    if crossing:
        atoms = {a['atom_id']: a for c in manifest['components'] for a in c['atoms']}
        labels = {aid: f"{a['author_chain_id'] or '∅'}:{a['residue_name']}{a['author_residue_number']}{a['insertion_code']}.{a['atom_name']}" for aid, a in atoms.items()}
        detail = '; '.join(' — '.join(labels[aid] for aid in edge['atom_ids']) + f" ({edge['evidence']})" for edge in crossing[:5])
        raise ValueError('Exclusion would cut a covalent or uncertain connection: ' + detail + '. Provide the original CIF for uncertain distance-only contacts; covalent bonds require dedicated preparation.')


def select_atoms(manifest, excluded, choices, connections=()):
    atoms = [a for c in manifest['components'] for a in c['atoms']]
    variants = {}
    for atom in atoms:
        if atom['altloc']:
            variants.setdefault(atom['residue_id'], set()).add(atom['altloc'])
    if any(key not in variants or choice not in variants[key] for key, choice in choices.items()):
        raise ValueError('Unknown residue or alternate-location choice')
    kept = [a for c in manifest['components'] if c['component_id'] not in excluded for a in c['atoms']
            if not a['altloc'] or a['residue_id'] not in choices or a['altloc'] == choices[a['residue_id']]]
    selected = {a['atom_id'] for a in kept}
    by_id = {a['atom_id']: a for a in atoms}
    bonds = {}
    for edge in connections:
        if edge['evidence'] == 'possible_covalent_distance' or any(cid in excluded for cid in edge['component_ids']):
            continue
        ends = [by_id[a] for a in edge['atom_ids']]
        key = tuple(sorted((a['residue_id'], a['atom_name']) for a in ends))
        bonds.setdefault(key, []).append(edge)
    if any(not any(set(edge['atom_ids']) <= selected for edge in edges) for edges in bonds.values()):
        raise ValueError('Alternate-location choices would break a declared chemical connection')
    return kept


def export_components(path, manifest, excluded, target, altloc_choices=None):
    excluded = set(excluded)
    choices = altloc_choices or {}
    wanted = {a['source_record']: a for a in select_atoms(manifest, excluded, choices)}
    if not wanted or len(wanted) > 99999:
        raise ValueError('Empty receptor or PDB atom capacity exceeded')
    output, serial_map = [], {}
    retained_chains = {a['author_chain_id'] for a in wanted.values() if a['record_type'] == 'ATOM'}
    lines = Path(path).read_text().splitlines()
    for index, line in enumerate(lines, 1):
        record = line[:6].strip()
        if index in wanted:
            serial = len(serial_map) + 1
            serial_map[index] = serial
            if wanted[index]['residue_id'] in choices:
                line = line[:16] + ' ' + line[17:]
            output.append(line[:6] + f'{serial:5d}' + line[11:])
        elif record == 'SEQRES' and line[11:12].strip() in retained_chains:
            output.append(line)
        elif record == 'TER' and output and output[-1].startswith(('ATOM', 'HETATM')):
            output.append('TER')
    # Connections are reconstructed from source identities, never stale atom serials.
    by_serial = {}
    for index in wanted:
        by_serial.setdefault(int(lines[index-1][6:11]), []).append(serial_map[index])
    for line in lines:
        if line.startswith('CONECT'):
            values = [int(line[i:i+5]) for i in range(6, len(line), 5) if line[i:i+5].strip()]
            if any(len(by_serial.get(v, [])) > 1 for v in values):
                raise ValueError('Ambiguous CONECT export')
            retained = [by_serial[v][0] for v in values if v in by_serial]
            if values[0] in by_serial and len(retained) > 1:
                output.append('CONECT' + ''.join(f'{v:5d}' for v in retained))
        elif line.startswith(('LINK  ', 'SSBOND')):
            if any(line[start:end].strip() not in {'', '1555'} for start, end in ((59, 65), (66, 72))):
                continue
            if line.startswith('LINK'):
                selectors = [(line[21:22].strip(), int(line[22:26]), line[26:27].strip(), line[12:16].strip()),
                             (line[51:52].strip(), int(line[52:56]), line[56:57].strip(), line[42:46].strip())]
            else:
                selectors = [(line[15:16].strip(), int(line[17:21]), line[21:22].strip(), 'SG'),
                             (line[29:30].strip(), int(line[31:35]), line[35:36].strip(), 'SG')]
            kept = {(a['author_chain_id'], a['author_residue_number'], a['insertion_code'], a['atom_name']) for a in wanted.values()}
            if all(ref in kept for ref in selectors):
                if line.startswith('LINK'):
                    for position, ref in zip((16, 46), selectors):
                        matches = [a for a in wanted.values() if (a['author_chain_id'], a['author_residue_number'], a['insertion_code'], a['atom_name']) == ref]
                        alt = line[position:position+1].strip()
                        if alt and not any(a['altloc'] == alt for a in matches):
                            break
                        if any(a['residue_id'] in choices for a in matches):
                            line = line[:position] + ' ' + line[position+1:]
                    else:
                        output.append(line)
                    continue
                output.append(line)
    Path(target).write_text('\n'.join([*output, 'END']) + '\n')


def verify_cif_mapping(path, manifest, identity, pdb_path):
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != identity['sha256']:
        raise ValueError('Original CIF SHA256 mismatch')
    data = MMCIF2Dict(str(path))
    pdb_lines = Path(pdb_path).read_text().splitlines()
    count = len(data.get('_atom_site.id', []))
    if not count:
        raise ValueError('CIF contains no atom_site records')

    def field(prefix, name, index, default=''):
        values = data.get(prefix + '.' + name)
        value = values[index] if values is not None else default
        return '' if value in {'.', '?'} else str(value)

    by_key, mapping = {}, []
    component_by_atom = {}
    for component in manifest['components']:
        for atom in component['atoms']:
            key = (atom['record_type'], atom['author_chain_id'], str(atom['author_residue_number']), atom['insertion_code'], atom['residue_name'], atom['atom_name'], atom['altloc'])
            if key in by_key:
                raise ValueError('Ambiguous CIF/PDB identity mapping')
            by_key[key] = atom
            component_by_atom[atom['atom_id']] = component['component_id']
    matched = set()
    for i in range(count):
        if (field('_atom_site', 'pdbx_PDB_model_num', i) or '1') != manifest['source']['model_id']:
            continue
        value = lambda name, default='': field('_atom_site', name, i, default)
        key = (value('group_PDB'), value('auth_asym_id') or value('label_asym_id'),
               str(int(value('auth_seq_id') or value('label_seq_id'))), value('pdbx_PDB_ins_code'),
               value('auth_comp_id') or value('label_comp_id'), value('auth_atom_id') or value('label_atom_id'), value('label_alt_id'))
        atom = by_key.get(key)
        if atom is None or atom['atom_id'] in matched or value('type_symbol').upper() != atom['element'] or math.dist(atom['coordinates'], [float(value('Cartn_' + axis)) for axis in 'xyz']) > 0.002:
            raise ValueError('Client CIF conversion lost or changed source atom identities or coordinates')
        pdb_line = pdb_lines[atom['source_record'] - 1]
        if value('occupancy') and abs(float(value('occupancy')) - float(pdb_line[54:60])) > 0.0051:
            raise ValueError('CIF conversion changed occupancy')
        if value('pdbx_formal_charge'):
            encoded = pdb_line[78:80].strip()
            charge = int(encoded[:-1]) * (-1 if encoded[-1:] == '-' else 1) if encoded else 0
            if charge != int(value('pdbx_formal_charge')):
                raise ValueError('CIF conversion changed formal charge')
        matched.add(atom['atom_id'])
        mapping.append({'source_atom_id': atom['atom_id'], 'cif_atom_site_id': value('id'),
                        **{name: value(name) for name in ('label_asym_id', 'auth_asym_id', 'label_seq_id', 'auth_seq_id', 'label_atom_id', 'auth_atom_id')}})
    if matched != {a['atom_id'] for a in by_key.values()}:
        raise ValueError('CIF/PDB atom coverage mismatch')
    by_label = {}
    by_atom = {a['atom_id']: a for a in by_key.values()}
    for row in mapping:
        by_label.setdefault((row['label_asym_id'], row['label_seq_id'], row['label_atom_id']), []).append(row['source_atom_id'])
    declared, external = [], list(manifest.get('external_coordination_connections', []))
    for i in range(len(data.get('_struct_conn.id', []))):
        connection_type = field('_struct_conn', 'conn_type_id', i)
        if connection_type not in {'covale', 'disulf', 'metalc'}:
            continue
        endpoints = []
        for part in ('ptnr1', 'ptnr2'):
            key = tuple(field('_struct_conn', part + '_' + name, i) for name in ('label_asym_id', 'label_seq_id', 'label_atom_id'))
            if key not in by_label:
                raise ValueError('Unresolved CIF chemical connection')
            alt = field('_struct_conn', 'pdbx_' + part + '_label_alt_id', i)
            author_chain = field('_struct_conn', part + '_auth_asym_id', i)
            author_number = field('_struct_conn', part + '_auth_seq_id', i)
            residue_name = field('_struct_conn', part + '_auth_comp_id', i) or field('_struct_conn', part + '_label_comp_id', i)
            insertion = field('_struct_conn', 'pdbx_' + part + '_PDB_ins_code', i)
            candidates = [aid for aid in by_label[key]
                          if (not alt or by_atom[aid]['altloc'] == alt)
                          and (not author_chain or by_atom[aid]['author_chain_id'] == author_chain)
                          and (not author_number or by_atom[aid]['author_residue_number'] == int(author_number))
                          and (not residue_name or by_atom[aid]['residue_name'] == residue_name)
                          and by_atom[aid]['insertion_code'] == insertion]
            if not candidates:
                raise ValueError('Unresolved CIF connection endpoint or alternate location')
            if len({by_atom[aid]['residue_id'] for aid in candidates}) != 1:
                raise ValueError('Ambiguous CIF connection residue identity')
            endpoints.append(candidates)
        symmetries = [field('_struct_conn', part + '_symmetry', i) or '1_555' for part in ('ptnr1', 'ptnr2')]
        outside = any(s != '1_555' for s in symmetries)
        if outside and connection_type != 'metalc':
            raise ValueError('CIF connection requires an explicit crystallographic assembly')
        for left in endpoints[0]:
            for right in endpoints[1]:
                a, b = by_atom[left], by_atom[right]
                if manifest['version'] == 2 and a['altloc'] and b['altloc'] and a['altloc'] != b['altloc']:
                    continue
                components = [component_by_atom[left], component_by_atom[right]]
                if len(set(components)) == 2 or manifest['version'] == 2:
                    edge = {'atom_ids': [left, right], 'component_ids': components, 'evidence': 'CIF:' + connection_type}
                    if connection_type == 'metalc' and not any(atom['element'] in METAL_ELEMENTS for atom in (a, b)):
                        raise ValueError('CIF metal coordination has no metal endpoint')
                    if outside:
                        external.append({**edge, 'symmetry_operations': symmetries})
                    else:
                        declared.append(edge)
    component_by_id = {c['component_id']: c for c in manifest['components']}
    result = {**manifest, 'original_structure': identity, 'author_label_mapping': mapping,
              'declared_connections': merge_connections([*manifest.get('declared_connections', []), *declared], component_by_id),
              'external_coordination_connections': merge_connections(external, component_by_id)}
    result['selection_groups'] = selection_groups(result)
    return result
