"""Apply candidate optimizations and deterministic reductions at image build time."""
import ast
from pathlib import Path

root = Path('/app')
path = root / 'models/sample.py'
source = path.read_text()
if 'results.append(None)' not in source:
    start = source.index('        # # add new atom information', source.index('def get_next_step'))
    end = source.index('        # # add generation probabilities', start)
    block = source[start:end].replace('        # # add new atom information\n', '').replace(
        '        index_bond_i = (bond_index[0, :] == i)\n', '')
    block = block.replace('        data_new = transform(data_new)',
                          '        if transform is not None:\n            data_new = transform(data_new)')
    source = source[:start] + '        index_bond_i = (bond_index[0, :] == i)\n' + source[end:]
    source = source.replace('        data_new.is_high_prob = is_high_prob',
        '        if not is_high_prob:\n'
        '            # Preserve shuffle RNG consumption and accepted candidate order.\n'
        '            results.append(None)\n'
        '            continue\n' + block + '        data_new.is_high_prob = is_high_prob')
    source = source.replace('    return results', '    return [data for data in results if data is not None]')
    ast.parse(source)
    path.write_text(source)
assert 'if transform is not None:' in source
assert 'return [data for data in results if data is not None]' in source

path = root / 'utils/sample.py'
source = path.read_text()
failure = "                raise RuntimeError('SurfGen initialization failed: no initial candidate satisfies all probability thresholds. Try another seed or Protein Context.')"
if failure not in source:
    previous = "                print('Initialization failed.')"
    assert source.count(previous) == 1
    source = source.replace(previous, failure)
    ast.parse(source)
    path.write_text(source)
assert failure in source

path = root / 'utils/masif/generate_prot_ply.py'
source = path.read_text()
if "region['box']" in source:
    replaced = 0
    for indent in ('\t\t', '\t\t\t'):
        previous = (
            f"{indent}if region is not None:\n"
            f"{indent}\tcenter = np.array(region['box']['center'])\n"
            f"{indent}\thalf_size = np.array(region['box']['size']) / 2\n"
            f"{indent}\tiface_v = np.where(np.all(np.abs(vertices1 - center) <= half_size, axis=1))[0]\n"
            f"{indent}else:\n"
            f"{indent}\tiface_v = np.where(d <= dist_threshold)[0]"
        )
        replaced += source.count(previous)
        source = source.replace(previous, f'{indent}iface_v = np.where(d <= dist_threshold)[0]')
    assert replaced == 3
    ast.parse(source)
    path.write_text(source)
assert "region['box']" not in source
assert source.count('iface_v = np.where(d <= dist_threshold)[0]') == 3

path = root / 'gen.py'
source = path.read_text()
if 'pool.queue = [composer(queue_tmp[idx]) for idx in next_idx]' not in source:
    assert source.count('            transform = composer,') == 1
    assert source.count('pool.queue = [queue_tmp[idx] for idx in next_idx]') == 1
    source = source.replace('            transform = composer,', '            transform = None,')
    source = source.replace('pool.queue = [queue_tmp[idx] for idx in next_idx]',
                            'pool.queue = [composer(queue_tmp[idx]) for idx in next_idx]')
    ast.parse(source)
    path.write_text(source)
path = root / 'utils/misc.py'
source = path.read_text()
if 'def deterministic_scatter(' not in source:
    source += '''


from torch_scatter import segment_csr
from torch_geometric.utils import softmax as segment_softmax


def deterministic_scatter(function, src, index, dim=0, dim_size=None):
    # Stable edge order avoids CUDA atomic sums changing the beam trajectory.
    if src.numel() == 0:
        return function(src, index, dim=dim, dim_size=dim_size)
    src = src.movedim(dim, 0)
    order = index.argsort(stable=True)
    ptr = torch.cat((index.new_zeros(1),
                     index.bincount(minlength=dim_size or 0).cumsum(0)))
    if function.__name__ == 'scatter_softmax':
        sorted_output = segment_softmax(src[order], ptr=ptr, dim=0)
        result = torch.empty_like(src).index_copy_(0, order, sorted_output)
    else:
        result = segment_csr(src[order], ptr, reduce='sum')
    return result.movedim(0, dim)
'''
    ast.parse(source)
    path.write_text(source)

for relative, names in (
    ('models/model_utils.py', ('scatter_add',)),
    ('models/interaction/geodesic.py', ('scatter_sum',)),
    ('models/interaction/geoattn.py', ('scatter_sum', 'scatter_softmax')),
    ('models/interaction/interaction.py', ('scatter_sum',)),
    ('models/generation/topology.py', ('scatter_add', 'scatter_sum', 'scatter_softmax')),
):
    path = root / relative
    source = path.read_text()
    if 'from utils.misc import deterministic_scatter' not in source:
        imports = [line for line in source.splitlines() if line.startswith('from torch_scatter import ')]
        assert imports and all(any(name in line.split(' import ')[1].split(', ') for line in imports) for name in names)
        block = '\nfrom functools import partial\nfrom utils.misc import deterministic_scatter\n'
        block += '\n'.join(f'{name} = partial(deterministic_scatter, {name})' for name in names)
        source = source.replace(imports[-1], imports[-1] + block, 1)
        ast.parse(source)
        path.write_text(source)
print('SurfGen candidate optimizations and deterministic reductions applied')


# Count search states separately from completed molecule candidates.
path = root / 'gen.py'
source = path.read_text()
if 'generation_stats = {' not in source:
    def replace_generation(old, new):
        global source
        assert source.count(old) == 1, old
        source = source.replace(old, new)

    replace_generation('global_step = 0', """generation_stats = {
    'initial_state_count': len(init_data_list),
    'proposed_state_count': 0, 'finished_state_count': 0,
    'running_state_count': 0, 'other_state_count': 0,
    'steps': 0,
}
stop_reason = 'target_reached'
global_step = 0""")
    replace_generation('    if global_step > config.sample.max_steps:\n        break',
                       "    if global_step > config.sample.max_steps:\n        stop_reason = 'max_steps'\n        break\n    generation_stats['steps'] += 1")
    replace_generation('        for data_next in data_next_list:',
                       "        generation_stats['proposed_state_count'] += len(data_next_list)\n        for data_next in data_next_list:")
    replace_generation('            if data_next.status == STATUS_FINISHED:',
                       "            if data_next.status == STATUS_FINISHED:\n                generation_stats['finished_state_count'] += 1")
    replace_generation('            elif data_next.status == STATUS_RUNNING:\n                nexts.append(data_next)',
                       "            elif data_next.status == STATUS_RUNNING:\n                generation_stats['running_state_count'] += 1\n                nexts.append(data_next)\n            else:\n                generation_stats['other_state_count'] += 1")
    replace_generation('    if n_tmp == 0:', "    if n_tmp == 0:\n        stop_reason = 'queue_empty'")
    replace_generation('# save the generation results', """# save the generation results
if len(pool.finished) >= config.sample.num_samples:
    stop_reason = 'target_reached'
generation_stats.update(
    valid_unique_count=len(pool.finished),
    duplicate_count=len(pool.duplicate), rejected_finished_count=len(pool.failed),
)
if args.results_json:
    metadata_path = args.results_json + '.metadata.json'
    os.makedirs(os.path.dirname(os.path.abspath(metadata_path)), exist_ok=True)
    with open(metadata_path, 'w') as metadata_file:
        json.dump({'stop_reason': stop_reason, 'generation_stats': generation_stats}, metadata_file)
""")
    ast.parse(source)
    path.write_text(source)

# Release builds may relocate this slice; retain the pre-truncation counts.
source = path.read_text()
source = source.replace('\npool.finished = pool.finished[:config.sample.num_samples]\n', '\n')
marker = "task_name = args.ply_file.split('/')[-1][:-4]"
assert source.count(marker) == 1
source = source.replace(marker, 'pool.finished = pool.finished[:config.sample.num_samples]\n' + marker)
ast.parse(source)
path.write_text(source)

# Completed outputs only need the molecule, not its GPU search graph.
source = path.read_text()
source = source.replace('pool.duplicate.append(data_next)', 'pool.duplicate.append(None)')
source = source.replace('pool.failed.append(data_next)', 'pool.failed.append(None)')
source = source.replace('pool.finished.append(data_next)',
                        'pool.finished.append(EasyDict(rdmol=rdmol, smiles=smiles))')
if "SDF_dir = osp.join(task_dir,'SDF')" in source:
    start = source.index("SDF_dir = osp.join(task_dir,'SDF')")
    end = source.index('shutil.copy(args.ply_file,task_dir)', start)
    source = source[:start] + source[end:]
ast.parse(source)
path.write_text(source)
