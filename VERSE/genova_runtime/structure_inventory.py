import copy
import hashlib
import json
import math
import string
from pathlib import Path

from genova_runtime.structure_identity import component_manifest


def source_inventory(path, source):
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
        raise ValueError('Source structure SHA256 mismatch')
    if path.suffix.lower() == '.pdb':
        result = component_manifest(path, source, analyze_connections=False)
        result.update(inventory_policy='generation_auto_v1', source_format='pdb')
    else:
        from Bio.PDB.MMCIF2Dict import MMCIF2Dict
        data = MMCIF2Dict(str(path))
        def value(name, index, default=''):
            values = data.get('_atom_site.' + name)
            item = values[index] if values is not None else default
            return '' if item in {'.', '?'} else str(item)
        prefix = f"{source['sha256']}:{source['model_id']}"
        components, mapping = {}, []
        for i in range(len(data.get('_atom_site.id', []))):
            if (value('pdbx_PDB_model_num', i) or '1') != source['model_id']:
                continue
            label_chain = value('label_asym_id', i)
            chain = f'{prefix}:chain:{label_chain}'
            number = int(value('auth_seq_id', i) or value('label_seq_id', i))
            name = value('auth_comp_id', i) or value('label_comp_id', i)
            insertion = value('pdbx_PDB_ins_code', i)
            residue = f'{chain}:residue:{number}:{insertion}:{name}'
            record = value('group_PDB', i)
            cid = chain if record == 'ATOM' else residue + ':heterogen'
            aid = f"{prefix}:atom_site:{value('id', i)}"
            atom = dict(atom_id=aid, residue_id=residue, chain_instance_id=chain,
                source_record=i + 1, record_type=record, author_chain_id=value('auth_asym_id', i) or label_chain,
                author_residue_number=number, insertion_code=insertion, residue_name=name,
                atom_name=value('auth_atom_id', i) or value('label_atom_id', i), altloc=value('label_alt_id', i),
                element=value('type_symbol', i).upper(), occupancy=float(value('occupancy', i, '1')),
                coordinates=[float(value('Cartn_' + axis, i)) for axis in 'xyz'],
                label_asym_id=label_chain, label_seq_id=value('label_seq_id', i))
            components.setdefault(cid, dict(component_id=cid, selection_kind='chain_records' if record == 'ATOM'
                else 'heterogen_residue_records', atoms=[]))['atoms'].append(atom)
            mapping.append(dict(source_atom_id=aid, cif_atom_site_id=value('id', i), label_asym_id=label_chain,
                auth_asym_id=atom['author_chain_id'], label_seq_id=atom['label_seq_id'], auth_seq_id=str(number),
                label_atom_id=value('label_atom_id', i), auth_atom_id=atom['atom_name']))
        result = dict(version=2, source=source, coordinate_frame_id=prefix + ':source', coordinate_unit='angstrom',
            chemistry_status='not_evaluated', components=list(components.values()), selection_groups=[],
            declared_connections=[], external_coordination_connections=[], author_label_mapping=mapping,
            inventory_policy='generation_auto_v1', source_format='mmcif')
    atoms = [a for c in result['components'] for a in c['atoms']]
    if not atoms:
        raise ValueError('Structure contains no atoms in the selected model')
    if any(not all(math.isfinite(v) for v in a['coordinates']) for a in atoms):
        raise ValueError('Non-finite atom coordinates')
    # PostgreSQL JSONB canonicalizes negative zero; keep request fingerprints stable across storage.
    for atom in atoms:
        atom['coordinates'] = [0.0 if value == 0 else value for value in atom['coordinates']]
        if atom['occupancy'] == 0:
            atom['occupancy'] = 0.0
    if len({a['atom_id'] for a in atoms}) != len(atoms):
        raise ValueError('Duplicate source atom identities')
    return result


def inventory_summary(manifest):
    residues, chains, ligands = {}, [], []
    for c in manifest['components']:
        for a in c['atoms']:
            residues.setdefault(a['residue_id'], dict(chain_id=a['author_chain_id'], residue_number=a['author_residue_number'],
                insertion_code=a['insertion_code'], residue_name=a['residue_name']))
        first = c['atoms'][0]
        if c['selection_kind'] == 'chain_records':
            chains.append(dict(chain_id=first['author_chain_id'], residue_count=len({a['residue_id'] for a in c['atoms']})))
        elif first['residue_name'] not in {'HOH', 'WAT', 'DOD', 'H2O'}:
            heavy = [a for a in c['atoms'] if a['element'] not in {'H', 'D'}]
            if heavy:
                center = [sum(a['coordinates'][i] for a in heavy) / len(heavy) for i in range(3)]
                ligands.append(dict(key=c['component_id'], component_id=c['component_id'], chain_id=first['author_chain_id'],
                    residue_number=first['author_residue_number'], insertion_code=first['insertion_code'], residue_name=first['residue_name'],
                    heavy_atom_count=len(heavy), center=center))
    return dict(chains=chains, residues=list(residues.values()), ligands=ligands, inventory_error=manifest.get('inventory_error'),
        chemistry_status='deferred_to_task', source_file_id=manifest['source']['file_id'], source_sha256=manifest['source']['sha256'])


def protein_residue_inventory(manifest, *, box=None, offset=0, limit=20):
    """Return a stable, paginated list of observed protein residues."""
    from genova_runtime.pdb2pqr_compat import AMINO_ACIDS
    from genova_runtime.structure_inputs import RESIDUE_ALIASES

    protein_names = AMINO_ACIDS | RESIDUE_ALIASES.keys() | {
        'MSE', 'SEC', 'PYL', 'HYP', 'SEP', 'TPO', 'PTR', 'CSO', 'CME', 'MLY', 'M3L',
        'FME', 'KCX', 'LLP', 'PCA', 'CSD', 'CSE', 'CGL', 'OCS',
    }
    if hasattr(box, 'model_dump'):
        box = box.model_dump(mode='json')
    center = box.get('center') if isinstance(box, dict) else None
    size = box.get('size') if isinstance(box, dict) else None
    if center is None or size is None:
        center = size = None

    residues = {}
    for component in manifest.get('components', []):
        if component.get('selection_kind') != 'chain_records':
            continue
        grouped = {}
        for atom in component.get('atoms', []):
            grouped.setdefault(atom['residue_id'], []).append(atom)
        for residue_id, atoms in grouped.items():
            first = atoms[0]
            if first['residue_name'].upper() not in protein_names:
                continue
            if center is not None:
                half_size = [dimension / 2 for dimension in size]
                if not any(all(abs(coordinate - origin) <= half
                        for coordinate, origin, half in zip(atom['coordinates'], center, half_size))
                        for atom in atoms if atom.get('element', '').upper() not in {'H', 'D'}):
                    continue
            residues[residue_id] = {
                'component_id': component['component_id'],
                'residue_id': residue_id,
                'chain_instance_id': first['chain_instance_id'],
                'chain_id': first['author_chain_id'],
                'author_chain_id': first['author_chain_id'],
                'label_asym_id': first.get('label_asym_id'),
                'residue_number': first['author_residue_number'],
                'author_residue_number': first['author_residue_number'],
                'insertion_code': first['insertion_code'],
                'label_seq_id': first.get('label_seq_id'),
                'residue_name': first['residue_name'],
            }

    rows = list(residues.values())
    rows.sort(key=lambda row: (row['chain_instance_id'],
        (0, int(row['label_seq_id'])) if row['label_seq_id'] not in (None, '', '.', '?') else
        (1, row['author_residue_number']), row['insertion_code'], row['residue_id']))
    page_offset = max(0, offset)
    page_limit = min(50, max(1, limit))
    return {'residues': rows[page_offset:page_offset + page_limit], 'residue_count': len(rows)}


def chain_annotations(path, manifest):
    """Return coordinate and entry-level polymer information for each protein chain."""
    from Bio.Data.PDBData import protein_letters_3to1_extended

    path = Path(path)
    letters = {name.upper(): letter.upper() for name, letter in protein_letters_3to1_extended.items()}
    chains = {}
    for component in manifest.get('components', []):
        if component.get('selection_kind') != 'chain_records' or not component.get('atoms'):
            continue
        first = component['atoms'][0]
        chain_id = first['chain_instance_id']
        chain = chains.setdefault(chain_id, {
            'component_id': component['component_id'],
            'chain_instance_id': chain_id,
            'author_chain_id': first['author_chain_id'],
            'label_asym_id': first.get('label_asym_id'),
            '_residues': {},
        })
        for atom in component['atoms']:
            chain['_residues'].setdefault(atom['residue_id'], atom)

    title = ''
    declared_sequences = {}
    if path.suffix.lower() == '.pdb':
        title_parts = []
        for line in path.read_text(errors='replace').splitlines():
            record = line[:6].strip()
            if record == 'TITLE':
                title_parts.append(line[10:80].strip())
            elif record == 'SEQRES' and len(line) >= 19:
                declared_sequences.setdefault(line[11].strip(), []).extend(line[19:70].split())
        title = ' '.join(title_parts)[:512]
    else:
        from Bio.PDB.MMCIF2Dict import MMCIF2Dict
        data = MMCIF2Dict(str(path))

        def values(key):
            value = data.get(key, [])
            return value if isinstance(value, list) else [value]

        title = ' '.join(str(v) for v in values('_struct.title') if v not in {'.', '?'})[:512]
        asym = values('_struct_asym.id')
        entities = values('_struct_asym.entity_id')
        descriptions = dict(zip(values('_entity.id'), values('_entity.pdbx_description')))
        sequences = dict(zip(values('_entity_poly.entity_id'), values('_entity_poly.pdbx_seq_one_letter_code_can')))
        for label_id, entity_id in zip(asym, entities):
            for chain in chains.values():
                if chain.get('label_asym_id') == label_id:
                    chain['entity_id'] = entity_id
                    chain['entity_description'] = descriptions.get(entity_id)
                    chain['declared_sequence'] = sequences.get(entity_id)

    result = []
    for chain in chains.values():
        residues = list(chain.pop('_residues').values())
        if residues and all(atom.get('label_seq_id') for atom in residues):
            residues.sort(key=lambda atom: (int(atom['label_seq_id']), atom['residue_id']))
        observed = ''.join(letters.get(atom['residue_name'].upper(), 'X') for atom in residues)
        declared = chain.get('declared_sequence')
        if declared is None and chain['author_chain_id'] in declared_sequences:
            declared = ''.join(letters.get(name.upper(), 'X') for name in declared_sequences[chain['author_chain_id']])
        item = {**chain, 'residue_count': len(residues), 'observed_sequence': observed[:1200],
                'observed_sequence_length': len(observed), 'sequence_truncated': len(observed) > 1200}
        if declared:
            declared = str(declared).replace('\n', '').replace(' ', '')
            item.update(declared_sequence=declared[:1200], declared_sequence_length=len(declared),
                        declared_sequence_truncated=len(declared) > 1200)
        if title:
            item['structure_title'] = title
        result.append(item)
    return result


def validate_selection(manifest, edits):
    known = {c['component_id'] for c in manifest['components']}
    excluded = set(edits['excluded_component_ids'])
    retained = set(edits.get('retained_component_ids', []))
    if excluded & retained or not (excluded | retained) <= known:
        raise ValueError('Unknown or conflicting component selection')
    if manifest.get('inventory_error'):
        if excluded or retained or edits.get('altloc_choices'):
            raise ValueError('Source objects cannot be identified; submit the full structure')
        return
    if known <= excluded:
        raise ValueError('Preparation must retain at least one component')
    variants = {}
    for c in manifest['components']:
        for a in c['atoms']:
            if a['altloc']:
                variants.setdefault(a['residue_id'], set()).add(a['altloc'])
    if any(key not in variants or choice not in variants[key] for key, choice in edits.get('altloc_choices', {}).items()):
        raise ValueError('Unknown residue or alternate-location choice')
    resolve_altlocs(manifest, edits.get('altloc_choices', {}), automatic=False)


def resolve_altlocs(manifest, explicit, *, automatic=True):
    groups, residues = {}, {}
    for c in manifest['components']:
        for a in c['atoms']:
            if not a['altloc']:
                continue
            key = (a['chain_instance_id'], a['author_residue_number'], a['insertion_code'])
            groups.setdefault(key, {}).setdefault(a['altloc'], []).append(a['occupancy'])
            residues.setdefault(a['residue_id'], (key, set()))[1].add(a['altloc'])
    overrides = {}
    for rid, choice in explicit.items():
        group = residues[rid][0]
        if group in overrides and overrides[group] != choice:
            raise ValueError('Conflicting alternate locations at the same residue position')
        overrides[group] = choice
    chosen = {key: overrides.get(key) or min(values, key=lambda alt: (-sum(values[alt]) / len(values[alt]), alt))
              for key, values in groups.items() if automatic or key in overrides}
    choices, excluded_residues = {}, []
    for rid, (group, variants) in residues.items():
        if group not in chosen:
            continue
        if chosen[group] in variants:
            choices[rid] = chosen[group]
        else:
            excluded_residues.append(rid)
    return choices, sorted(excluded_residues)


def ordered_atoms(manifest):
    # Components can split ATOM and HETATM records of the same polymer.
    atoms = [a for c in manifest['components'] for a in c['atoms']]
    chains, residues = {}, {}
    for a in sorted(atoms, key=lambda a: a['source_record']):
        chains.setdefault(a['chain_instance_id'], len(chains))
        residues.setdefault(a['residue_id'], len(residues))
    return sorted(atoms, key=lambda a: (chains[a['chain_instance_id']], residues[a['residue_id']], a['source_record']))


def residue_key(atom):
    chain = atom.get('label_asym_id') or atom['chain_instance_id'].split(':chain:')[-1].replace(':', '_') or 'A'
    return (chain, atom['author_chain_id'] or chain, atom['author_residue_number'], atom['insertion_code'])


def validate_integrity(before, after, *, stage, restored_residue_ids=(), preserve_heavy=True, atom_renames=None):
    from genova_runtime.preparation_errors import PreparationError
    atom_renames = atom_renames or {}
    def inventory(manifest):
        residues, atoms = {}, {}
        polymer = {a['residue_id'] for c in manifest['components'] if c['selection_kind'] == 'chain_records' for a in c['atoms']}
        for a in ordered_atoms(manifest):
            key = residue_key(a)
            if a['residue_id'] in polymer or a['atom_name'] in {'N', 'CA', 'C'}:
                residues.setdefault(key, {})[a['atom_name']] = a
            atom_key = (*key, a['atom_name'], a['altloc'])
            if atom_key in atoms:
                raise PreparationError('STRUCTURE_INTEGRITY_FAILED', stage + ': ambiguous atom mapping', [str(key)])
            atoms[atom_key] = a
        return residues, atoms
    old, old_atoms = inventory(before)
    new, new_atoms = inventory(after)
    errors = []
    if [k for k in new if k in old] != [k for k in old if k in new]:
        errors.append(dict(type='residue_order_changed', residues=[str(k) for k in old]))
    errors.extend(dict(type='residue_missing', residues=[str(k)]) for k in old if k not in new)
    def issues(residues):
        found = {}
        keys = list(residues)
        for i, key in enumerate(keys):
            atoms = residues[key]
            if any(name in atoms for name in ('N', 'CA', 'C')):
                missing = sorted({'N', 'CA', 'C', 'O'} - atoms.keys())
                if missing:
                    found[('missing_backbone', key)] = dict(type='missing_backbone', residues=[str(key)], missing=missing)
            if i and keys[i-1][:2] == key[:2]:
                previous = residues[keys[i-1]]
                if 'C' in previous and 'N' in atoms:
                    distance = math.dist(previous['C']['coordinates'], atoms['N']['coordinates'])
                    if not 0.9 <= distance <= 2.0:
                        found[('backbone_distance', keys[i-1], key)] = dict(type='backbone_distance', residues=[str(keys[i-1]), str(key)], distance_angstrom=distance)
                    elif 'OXT' in previous:
                        found[('internal_oxt', keys[i-1])] = dict(type='internal_oxt', residues=[str(keys[i-1])])
        return found
    baseline, current = issues(old), issues(new)
    errors.extend(row for key, row in current.items() if key not in baseline)
    restored = {residue_key(a) for a in old_atoms.values() if a['residue_id'] in set(restored_residue_ids)}
    errors.extend(row for key, row in current.items() if key[0] == 'missing_backbone' and key[1] in restored and row not in errors)
    for key, a in old_atoms.items():
        if a['element'] in {'H', 'D'}:
            continue
        name, element = atom_renames.get(a['atom_id'], (a['atom_name'], a['element']))
        b = new_atoms.get((*key[:-2], name, key[-1]))
        if b is None or b['element'] != element:
            errors.append(dict(type='heavy_atom_mapping', residues=[str(key[:4])], atom=a['atom_name']))
        elif preserve_heavy and math.dist(a['coordinates'], b['coordinates']) > 0.000002:
            errors.append(dict(type='heavy_atom_moved', residues=[str(key[:4])], atom=a['atom_name']))
    report = dict(stage=stage, status='failed' if errors else 'passed', original_issues=list(baseline.values()), introduced_issues=errors,
        residue_count=len(new), mapped_heavy_atoms=sum(a['element'] not in {'H', 'D'} for a in old_atoms.values()))
    if errors:
        raise PreparationError('STRUCTURE_INTEGRITY_FAILED', json.dumps(report, ensure_ascii=False), [r for e in errors for r in e['residues']])
    return report


def tool_structure(manifest, target, excluded=(), choices=None, excluded_residues=()):
    choices = choices or {}
    excluded_atoms = {a['atom_id'] for c in manifest['components'] if c['component_id'] in excluded for a in c['atoms']}
    atoms = [a for a in ordered_atoms(manifest) if a['atom_id'] not in excluded_atoms and a['residue_id'] not in excluded_residues
             if not a['altloc'] or a['residue_id'] not in choices or a['altloc'] == choices[a['residue_id']]]
    component_by_atom = {a['atom_id']: c['component_id'] for c in manifest['components'] for a in c['atoms']}
    chains = list(dict.fromkeys(a['chain_instance_id'] for a in atoms))
    if not atoms or len(atoms) > 99999 or len(chains) > 62:
        raise ValueError('TOOL_FORMAT_CAPACITY: selected structure exceeds PDB capacity')
    aliases = dict(zip(chains, string.ascii_uppercase + string.ascii_lowercase + string.digits))
    residues, rows, mapping = {}, [], []
    for a in atoms:
        chain = aliases[a['chain_instance_id']]
        key = a['residue_id']
        if key not in residues:
            residues[key] = sum(1 for c, _ in residues.values() if c == chain) + 1
            residues[key] = (chain, residues[key])
        _, number = residues[key]
        if number > 9999 or len(a['residue_name']) > 3 or len(a['atom_name']) > 4 or any(v < -999.999 or v > 9999.999 for v in a['coordinates']):
            raise ValueError('TOOL_FORMAT_CAPACITY: atom or residue cannot be represented in PDB')
        if rows and mapping[-1]['chain_instance_id'] != a['chain_instance_id']:
            rows.append('TER')
        serial = len(mapping) + 1
        x, y, z = a['coordinates']
        atom_name = a['atom_name'].rjust(4) if len(a['element']) == 2 or len(a['atom_name']) == 4 else (' ' + a['atom_name']).ljust(4)
        rows.append(f"{a['record_type']:<6}{serial:5d} {atom_name} {a['residue_name']:>3} {chain}{number:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{a['occupancy']:6.2f}{0:6.2f}          {a['element']:>2}")
        mapping.append(dict(source_atom_id=a['atom_id'], source_component_id=component_by_atom[a['atom_id']], source_residue_id=key, chain_instance_id=a['chain_instance_id'],
            author_chain_id=a['author_chain_id'], author_residue_number=a['author_residue_number'],
            insertion_code=a['insertion_code'], label_asym_id=a.get('label_asym_id'), label_seq_id=a.get('label_seq_id'),
            tool_chain_id=chain, tool_residue_number=number, atom_name=a['atom_name'], serial=serial,
            source_record=a['source_record'], coordinates=a['coordinates'], element=a['element'], record_type=a['record_type']))
    serials = {row['source_atom_id']: row['serial'] for row in mapping}
    for edge in manifest.get('declared_connections', []):
        if 'symmetry_operations' not in edge and edge['evidence'] != 'possible_covalent_distance' and all(aid in serials for aid in edge['atom_ids']):
            rows.append('CONECT' + ''.join(f'{serials[aid]:5d}' for aid in edge['atom_ids']))
    Path(target).write_text('\n'.join([*rows, 'END']) + '\n')
    return {'version': 1, 'source': manifest['source'], 'atoms': mapping}


def write_cif(manifest, target, excluded=(), choices=None, excluded_residues=()):
    from Bio.PDB import MMCIFIO
    choices = choices or {}
    data = {'data_': 'genova'}
    names = ('group_PDB', 'id', 'type_symbol', 'label_atom_id', 'label_alt_id', 'label_comp_id',
        'label_asym_id', 'label_entity_id', 'label_seq_id', 'pdbx_PDB_ins_code', 'Cartn_x', 'Cartn_y', 'Cartn_z',
        'occupancy', 'B_iso_or_equiv', 'auth_seq_id', 'auth_comp_id', 'auth_asym_id', 'auth_atom_id', 'pdbx_PDB_model_num')
    for n in names:
        data['_atom_site.' + n] = []
    by_atom = {}
    excluded_atoms = {a['atom_id'] for c in manifest['components'] if c['component_id'] in excluded for a in c['atoms']}
    for a in ordered_atoms(manifest):
        if a['atom_id'] in excluded_atoms:
            continue
        if a['residue_id'] in excluded_residues:
            continue
        if a['altloc'] and a['residue_id'] in choices and choices[a['residue_id']] != a['altloc']:
            continue
        alt = '' if a['residue_id'] in choices else a['altloc']
        chain = a.get('label_asym_id') or a['chain_instance_id'].split(':chain:')[-1].replace(':', '_') or 'A'
        number = str(len(by_atom) + 1)
        values = [a['record_type'], number, a['element'], a['atom_name'], alt or '.', a['residue_name'],
            chain, '1', a.get('label_seq_id') or str(a['author_residue_number']), a['insertion_code'] or '?',
            *[repr(v) for v in a['coordinates']], str(a['occupancy']), '0', str(a['author_residue_number']),
            a['residue_name'], a['author_chain_id'] or chain, a['atom_name'], '1']
        for n, value in zip(names, values):
            data['_atom_site.' + n].append(value)
        by_atom[a['atom_id']] = {**a, 'label_asym_id': chain, 'altloc': alt}
    conn_names = ['id', 'conn_type_id'] + [part + '_' + n for part in ('ptnr1', 'ptnr2') for n in
        ('label_asym_id', 'label_seq_id', 'label_comp_id', 'label_atom_id', 'auth_asym_id', 'auth_seq_id', 'symmetry')] + [
        'pdbx_ptnr1_PDB_ins_code', 'pdbx_ptnr2_PDB_ins_code', 'pdbx_ptnr1_label_alt_id', 'pdbx_ptnr2_label_alt_id']
    edges = [e for e in manifest.get('declared_connections', []) if e['evidence'] != 'possible_covalent_distance' and all(aid in by_atom for aid in e['atom_ids'])]
    for i, edge in enumerate(edges):
        evidence = edge['evidence']
        kind = 'metalc' if evidence == 'CIF:metalc' else 'disulf' if evidence in {'SSBOND', 'CIF:disulf'} else 'covale'
        ends = [by_atom[aid] for aid in edge['atom_ids']]
        values = [str(i + 1), kind]
        for partner, a in enumerate(ends):
            values.extend([a['label_asym_id'], a.get('label_seq_id') or str(a['author_residue_number']), a['residue_name'], a['atom_name'],
                a['author_chain_id'] or a['label_asym_id'], str(a['author_residue_number']), edge.get('symmetry_operations', ['1_555', '1_555'])[partner]])
        values.extend([a['insertion_code'] or '?' for a in ends] + [a['altloc'] or '.' for a in ends])
        for n, value in zip(conn_names, values):
            data.setdefault('_struct_conn.' + n, []).append(value)
    writer = MMCIFIO()
    writer.set_dict(data)
    target = Path(target)
    temporary = target.with_name(target.name + ".tmp")
    writer.save(str(temporary))
    temporary.replace(target)


def restore_tool_identities(manifest, mapping, *, preserve_heavy=True):
    result = copy.deepcopy(manifest)
    residues = {(r['tool_chain_id'], r['tool_residue_number']): r for r in mapping['atoms']}
    original_atoms = {(r['tool_chain_id'], r['tool_residue_number'], r['atom_name']): r for r in mapping['atoms']}
    for c in result['components']:
        for a in c['atoms']:
            tool_key = (a['author_chain_id'], a['author_residue_number'])
            row = residues[tool_key]
            original = original_atoms.get((*tool_key, a['atom_name']))
            if original is None and a['atom_name'] == 'SD':
                original = original_atoms.get((*tool_key, 'SE'))
            a['source_record'] = (original or row).get('source_record', a['source_record'])
            a['residue_id'] = row['source_residue_id']
            if original and preserve_heavy and original.get('element') not in {'H', 'D', None}:
                a['coordinates'] = original['coordinates']
            a.update(author_chain_id=row['author_chain_id'], author_residue_number=row['author_residue_number'],
                insertion_code=row['insertion_code'], label_asym_id=row['label_asym_id'], label_seq_id=row['label_seq_id'],
                chain_instance_id=row['chain_instance_id'])
    return result
