"""Apply platform inference fixes to the DELETE source image at build time."""
import ast
from pathlib import Path

root = Path('/code/components/Delete')


def replace(path, old, new):
    source = path.read_text()
    if new in source:
        return
    if source.count(old) != 1:
        raise ValueError(f'Unexpected DELETE source: {path}: {old!r}')
    source = source.replace(old, new)
    ast.parse(source)
    path.write_text(source)


path = root / 'src/main_gen.py'
source = path.read_text()
if 'for attempt in range(1, 12):' not in source:
    old = '        try_times = 0\n        while True:\n'
    if source.count(old) != 1:
        raise ValueError('Unexpected DELETE retry loop')
    head, body = source.split(old)
    source = head + ''.join(line[4:] if line.startswith('    ') else line for line in body.splitlines(keepends=True))
    source = source.replace('from src.utils.misc import load_config\n', 'from src.utils.misc import load_config, seed_all\n')
    source = source.replace("        config = load_config(dict['config_path'])\n", "        config = load_config(dict['config_path'])\n        seed_all(config.sample.seed)\n        print('sample_seed:', config.sample.seed, flush=True)\n")
    source = source.replace("        while True:\n            if try_times>10:\n                print('Delete Can Not Generate in this mission')\n                break\n", "        input_data = data\n        for attempt in range(1, 12):\n            data = deepcopy(input_data)\n            reason = 'target_finished'\n")
    source = source.replace("            print('search_init:', {\n", "            print('search_init:', {\n                'attempt': attempt,\n")
    source = source.replace('                if global_step > config.sample.max_steps:break', "                if global_step > config.sample.max_steps:\n                    reason = 'max_steps'\n                    break")
    source = source.replace("                    try_times +=1\n                    print('retry_search:', {\n                        'attempt': try_times,\n                        'reason': 'queue_tmp_empty',\n                    }, flush=True)", "                    reason = 'queue_tmp_empty'")
    source = source.rstrip() + "\n            print('search_end:', {'attempt': attempt, 'reason': reason, 'generated': len(result_smis)}, flush=True)\n        print('search_exhausted:', {'attempts': 11, 'generated': len(result_smis)}, flush=True)\n"
    assert 'try_times' not in source and 'while True:' not in source
    assert source.count('seed_all(config.sample.seed)') == 1
    assert source.count('for attempt in range(1, 12):') == 1
    ast.parse(source)
    path.write_text(source)

path = root / 'main.py'
replace(path, "c[nH]1'):", "c[nH]1',ph=7.4):")
replace(path, "ply_py_path, 'make_ply', pkt_file_sdf_file]", "ply_py_path, 'make_ply', pkt_file_sdf_file, str(ph)]")
path = root / 'get_ply.py'
replace(path, 'def make_ply(pkt_file_sdf_file):', 'def make_ply(pkt_file_sdf_file, ph=7.4):')
replace(path, "        'pkt_file':pkt_file,", "        'pkt_file':pkt_file,\n        'ph':ph,")
replace(path, 'if len(sys.argv) == 3:', 'if len(sys.argv) in (3, 4):')
replace(path, '            make_ply(arg1)', '            make_ply(arg1, float(sys.argv[3]) if len(sys.argv) == 4 else 7.4)')
path = root / 'delete_input/src/main.py'
replace(path, 'out_name=out_name, mesh_res=1.5,dist_threshold=8.0)', "out_name=out_name, mesh_res=1.5,dist_threshold=8.0, ph=self.param.get('ph', 7.4))")
path = root / 'delete_input/src/models/masif/generate_prot_ply.py'
replace(path, 'out_name= None):', 'out_name= None, ph=7.4):')
replace(path, 'apbs_bin, pdb2pqr_bin, multivalue_bin, workdir)', 'apbs_bin, pdb2pqr_bin, multivalue_bin, workdir, ph=ph)')
path = root / 'delete_input/src/models/masif/computeAPBS.py'
replace(path, 'multivalue_bin, workdir="."):', 'multivalue_bin, workdir=".", ph=7.4):')
replace(path, ' --ff=PARSE --whitespace --noopt --apbs-input {} {}/temp1".format(pdb_file,workdir)', ' --ff=PARSE --whitespace --noopt --ph-calc-method=propka --with-ph={} --apbs-input {} {}/temp1".format(ph,pdb_file,workdir)')
source = path.read_text()
old = "    p = subprocess.Popen([cmd], shell=True, cwd='./')\n    p.wait()"
new = "    subprocess.run(cmd, shell=True, cwd='./', check=True)"
if old in source:
    assert source.count(old) == 3
    source = source.replace(old, new)
    ast.parse(source)
    path.write_text(source)
else:
    assert source.count(new) == 3

path = root / 'src/configs/sample.yml'
lines = path.read_text().splitlines(keepends=True)
path.write_text(''.join('  beam_size: 500\n' if line.startswith('  beam_size:') else
                        '  max_steps: 50\n' if line.startswith('  max_steps:') else line
                        for line in lines if not line.startswith('  mask_init:')))
print('DELETE runtime fixes applied')

replace(root / 'main.py', 'ph=7.4):', 'ph=7.4,sampling=None):')
replace(root / 'main.py', "        'frag_smis' : frag_smis", "        'sampling': sampling,\n        'frag_smis' : frag_smis")
replace(root / 'src/main_gen.py',
        "        config = load_config(dict['config_path'])\n        seed_all(config.sample.seed)",
        "        config = load_config(dict['config_path'])\n"
        "        sampling = dict.get('sampling') or {}\n"
        "        for key in ('seed', 'beam_size', 'max_steps'):\n"
        "            if key in sampling:\n"
        "                config.sample[key] = sampling[key]\n"
        "        for key in ('element_threshold', 'bond_threshold'):\n"
        "            if key in sampling:\n"
        "                config.sample.threshold[key] = sampling[key]\n"
        "        seed_all(config.sample.seed)")

# Build graphs only for candidates selected for the next search layer.
replace(root / 'src/models/sample.py',
        '        data_new = transform(data_new)',
        '        if transform is not None:\n            data_new = transform(data_new)')
replace(root / 'src/main_gen.py',
        '                        transform = composer,',
        '                        transform = None,')
replace(root / 'src/main_gen.py',
        'pool.queue = [queue_tmp[idx] for idx in next_idx]',
        'pool.queue = [composer(queue_tmp[idx]) for idx in next_idx]')
replace(root / 'src/main_gen.py',
        '        seed_all(config.sample.seed)',
        '        torch.set_num_threads(1)\n        seed_all(config.sample.seed)')

# LigandMaskZero uses this path at inference. A retained atom with no bonds
# still needs a node index, so the bond list cannot determine the node count.
context_subgraph = (
    "        # new bond with ligand context atoms\n"
    "        if data.ligand_bond_index.size(1) != 0:\n"
    "            data.ligand_context_bond_index, data.ligand_context_bond_type = subgraph(\n"
    "                context_idx,\n"
    "                data.ligand_bond_index,\n"
    "                edge_attr = data.ligand_bond_type,\n"
    "                relabel_nodes = True,\n"
    "            )\n"
    "        else:\n"
    "            data.ligand_context_bond_index = torch.empty([2, 0], dtype=torch.long)\n"
    "            data.ligand_context_bond_type = torch.empty([0], dtype=torch.long)\n"
    "        # change context atom features that relate to bonds\n"
)
replace(root / 'src/utils/transforms.py', context_subgraph, context_subgraph.replace(
    '                relabel_nodes = True,\n',
    '                relabel_nodes = True,\n                num_nodes = data.ligand_element.size(0),\n',
))


# The adapter shares this dictionary with the generator, including on close().
path = root / 'src/main_gen.py'
source = path.read_text()
if "stats = self.param['generation_stats']" not in source:
    def replace_generation(old, new):
        global source
        assert source.count('\n' + old) == 1, old
        source = source.replace('\n' + old, '\n' + new)

    replace_generation('        input_data = data', """        stats = self.param['generation_stats']
        stats.update(initial_state_count=0, proposed_state_count=0,
                     processed_state_count=0, finished_state_count=0,
                     running_state_count=0, other_state_count=0,
                     rejected_finished_count=0, duplicate_finished_count=0, valid_finished_count=0,
                     reconstruction_attempt_count=0, rejected_reconstruction_count=0,
                     duplicate_reconstruction_count=0, valid_unique_count=0,
                     search_attempts=0, steps=0)
        input_data = data""")
    replace_generation('        for attempt in range(1, 12):',
                       "        for attempt in range(1, 12):\n            stats['search_attempts'] = attempt")
    replace_generation('            pool.queue = init_data_list',
                       "            stats['initial_state_count'] += len(init_data_list)\n            pool.queue = init_data_list")
    replace_generation('                queue_size = len(pool.queue)',
                       "                stats['steps'] += 1\n                queue_size = len(pool.queue)")
    replace_generation('                    for data_next in data_next_list:',
                       "                    stats['proposed_state_count'] += len(data_next_list)\n                    for data_next in data_next_list:\n                        stats['processed_state_count'] += 1")
    replace_generation('                        if data_next.status == STATUS_FINISHED:',
                       "                        if data_next.status == STATUS_FINISHED:\n                            stats['finished_state_count'] += 1")
    # Each existing failure/duplicate branch keeps its original behavior.
    for statement, counter in (('pool.failed.append(data_next)', 'rejected_finished_count'),
                               ('pool.duplicate.append(data_next)', 'duplicate_finished_count'),
                               ('pool.finished.append(data_next)', 'valid_finished_count')):
        source = ''.join(
            f"{line[:len(line) - len(line.lstrip())]}stats['{counter}'] += 1\n{line}"
            if line.strip() == statement else line
            for line in source.splitlines(keepends=True))
    replace_generation('                        elif data_next.status == STATUS_RUNNING:\n                            nexts.append(data_next)',
                       "                        elif data_next.status == STATUS_RUNNING:\n                            stats['running_state_count'] += 1\n                            nexts.append(data_next)\n                        else:\n                            stats['other_state_count'] += 1")
    replace_generation('                                rdmol = reconstruct_from_generated_with_edges(queue_tmp[idx])',
                       "                                stats['reconstruction_attempt_count'] += 1\n                                rdmol = reconstruct_from_generated_with_edges(queue_tmp[idx])")
    replace_generation('                                if mol is None:\n                                    continue',
                       "                                if mol is None:\n                                    stats['rejected_reconstruction_count'] += 1\n                                    continue")
    marker = "                                    if mol is not None and smiles not in result_smis and '.' not in smiles:"
    replace_generation(marker, "                                    if smiles in result_smis:\n                                        stats['duplicate_reconstruction_count'] += 1\n" + marker)
    # Track outputs before yielding so adapter.close() cannot lose the last one.
    source = ''.join(
        line + f"{line[:len(line) - len(line.lstrip())]}stats['valid_unique_count'] = len(result_smis)\n"
        if line.strip() == 'result_smis.append(smiles)' else line
        for line in source.splitlines(keepends=True))
    replace_generation('                            except Exception:pass',
                       "                            except Exception:\n                                stats['rejected_reconstruction_count'] += 1")
    replace_generation("            print('search_end:',", "            stats['last_search_stop_reason'] = 'target_reached' if len(pool.finished) >= config.sample.num_samples else ('queue_empty' if reason == 'queue_tmp_empty' else reason)\n            print('search_end:',")
    replace_generation("        print('search_exhausted:',", "        stats['stop_reason'] = 'search_budget_exhausted'\n        print('search_exhausted:',")
    ast.parse(source)
    path.write_text(source)
