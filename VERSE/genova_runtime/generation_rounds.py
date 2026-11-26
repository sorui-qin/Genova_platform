"""Bounded, resumable rounds for one molecule-generation job."""

import copy
import csv
import fcntl
import importlib
import json
import math
import os
import random
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

from genova_runtime.generation_settings import COUNT_LIMITS, ROUND_TARGET, TASK_SECONDS, sampling_plan


GENERATION_POLICY = 'generation_v2'
MAX_ROUNDS = 1000


def validate_count(engine, count):
    limit = COUNT_LIMITS[engine]
    if type(count) is not int or not 1 <= count <= limit:
        raise ValueError(f'{engine} molecule count must be between 1 and {limit}')
    return count


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def round_payload(payload, engine, number):
    value = copy.deepcopy(payload)
    key = 'target_num_molecules' if engine == 'ecloudgen' else 'num_molecules'
    target = payload.get(key, 100)
    value[key] = min(target, ROUND_TARGET)
    if payload.get('generation_policy') == GENERATION_POLICY:
        if engine == 'delete' and number == 0:
            value[key] = target
        if engine == 'ecloudgen' and payload.get('ecloudgen_full_target'):
            value['full_target_round'] = number == 0
            if number == 0:
                value[key] = target
            else:
                value['num_clouds'] = sampling_plan(value[key], decodes_per_cloud=value['decodes_per_cloud'])['num_clouds']
    value['output_dir'] = str(Path(payload['output_dir']) / 'rounds' / f'{number:04d}')
    for name in ('output_csv', 'generated_sdf', 'trajectory_csv', 'metadata_json'):
        value.pop(name, None)
    if engine == 'epso':
        value.setdefault('optimizer', {})['seed'] = (
            value.get('optimizer', {}).get('seed', 2024) + number * 10000000) % 2**32
    else:
        from genova_runtime.generation_settings import DEFAULTS
        value['seed'] = (value.get('seed', DEFAULTS[engine]['seed']) + number * 10000000) % 2**32
    value['_allow_empty_generation'] = True
    value['_defer_context_report'] = True
    return value


class StructureCountMismatch(ValueError):
    pass


def structure_records(result, rejected=None):
    from rdkit import Chem
    with Path(result['output_csv']).open(newline='') as stream:
        rows = list(csv.DictReader(stream))
        molecules = Chem.SDMolSupplier(result['generated_sdf'], removeHs=False)
        if len(rows) != len(molecules):
            raise StructureCountMismatch('CSV/SDF record counts differ')
        for index, (row, molecule) in enumerate(zip(rows, molecules)):
            if molecule is None or not molecule.GetNumAtoms() or not molecule.GetNumConformers():
                if rejected is not None:
                    rejected.append({'row': index, 'reason': 'unreadable_structure'})
                continue
            conformer = molecule.GetConformer()
            if not conformer.Is3D() or not all(math.isfinite(v) for p in conformer.GetPositions() for v in p):
                if rejected is not None:
                    rejected.append({'row': index, 'reason': 'invalid_coordinates'})
                continue
            expected = Chem.MolFromSmiles(row['smiles'])
            if expected is None:
                if rejected is not None:
                    rejected.append({'row': index, 'reason': 'invalid_smiles'})
                continue
            actual = Chem.RemoveHs(molecule)
            left, right = Chem.Mol(expected), Chem.Mol(actual)
            Chem.RemoveStereochemistry(left)
            Chem.RemoveStereochemistry(right)
            # SDF may infer previously unspecified stereo from its 3D coordinates.
            # Preserve the model CSV identity while checking all declared stereo.
            if (Chem.MolToSmiles(left) != Chem.MolToSmiles(right)
                    or not actual.HasSubstructMatch(expected, useChirality=True)):
                if rejected is None:
                    raise ValueError(f'CSV/SDF structure mismatch at row {index}')
                rejected.append({'row': index, 'reason': 'structure_mismatch'})
                continue
            yield Chem.MolToSmiles(expected, isomericSmiles=True), molecule


def collect_result(pool, engine, result, rejected=None):
    from rdkit import Chem
    previous = len(pool)
    if result.get('result_count') == 0:
        return 0
    if engine in {'surfgen', 'delete'}:
        for smiles, molecule in structure_records(result, rejected):
            pool.setdefault(smiles, {'smiles': smiles})
    else:
        source = result.get('unique_pool_csv', result['output_csv'])
        with Path(source).open(newline='') as stream:
            for row in csv.DictReader(stream):
                molecule = Chem.MolFromSmiles(row['smiles'])
                if molecule is None:
                    continue
                smiles = Chem.MolToSmiles(molecule, isomericSmiles=True)
                row['smiles'] = smiles
                if engine == 'epso':
                    fitness = float(row['fitness'])
                    if not math.isfinite(fitness):
                        raise ValueError('EPSO returned a non-finite fitness')
                    if smiles not in pool or fitness > float(pool[smiles]['fitness']):
                        pool[smiles] = row
                else:
                    pool.setdefault(smiles, row)
    return len(pool) - previous


def write_outputs(payload, engine, pool, rounds, target):
    output = Path(payload['output_dir'])
    if engine == 'ecloudgen':
        previous = set()
        if payload.get('previous_output_csv'):
            with Path(payload['previous_output_csv']).open(newline='') as source:
                previous = {row['smiles'] for row in csv.DictReader(source)}
            if not previous <= pool.keys() or len(previous) > target:
                raise ValueError('Previous results do not match the saved generation checkpoint')
        new = sorted(pool.keys() - previous)
        slots = target - len(previous)
        if len(new) > slots:
            new = random.Random(payload.get('seed', 42)).sample(new, slots)
        smiles = sorted(previous.union(new))
        rows = [pool[s] for s in smiles]
    elif engine == 'epso':
        rows = sorted(pool.values(), key=lambda row: -float(row['fitness']))[:target]
        rows = [dict(row, rank=i + 1) for i, row in enumerate(rows)]
    else:
        rows = list(pool.values())[:target]
    csv_path = Path(payload.get('output_csv', output / 'generated_molecules.csv'))
    fields = list(rows[0]) if rows else ['smiles']
    with csv_path.with_suffix('.tmp').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    csv_path.with_suffix('.tmp').replace(csv_path)
    artifacts = {'output_csv': str(csv_path)}
    if engine in {'surfgen', 'delete'}:
        from rdkit import Chem
        sdf_path = Path(payload.get('generated_sdf', output / 'generated.sdf'))
        selected, written = {row['smiles'] for row in rows}, set()
        temporary = sdf_path.with_suffix('.tmp')
        with Chem.SDWriter(str(temporary)) as writer:
            for record in rounds:
                if record['result'].get('result_count') == 0:
                    continue
                rejected = [] if payload.get('generation_policy') == GENERATION_POLICY else None
                for smiles, molecule in structure_records(record['result'], rejected):
                    if smiles in selected and smiles not in written:
                        writer.write(molecule)
                        written.add(smiles)
        if written != selected:
            raise RuntimeError('Generation CSV and SDF molecule counts differ')
        temporary.replace(sdf_path)
        artifacts['generated_sdf'] = str(sdf_path)
    if engine == 'epso':
        trajectory = Path(payload.get('trajectory_csv', output / 'trajectory.csv'))
        with trajectory.open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['round', 'seed', 'step', 'best_fitness', 'best_smiles'])
            for record in rounds:
                with Path(record['result']['trajectory_csv']).open(newline='') as source:
                    for row in csv.DictReader(source):
                        writer.writerow([record['round'], record['seed'], row['step'], row['best_fitness'], row['best_smiles']])
        artifacts['trajectory_csv'] = str(trajectory)
    return artifacts, len(rows)


def generation_round_limit(payload, engine, target):
    if payload.get('generation_policy') == GENERATION_POLICY:
        if engine == 'surfgen' and target <= ROUND_TARGET:
            return 1
        if engine == 'delete':
            return 2
    return MAX_ROUNDS


def run_generation(payload, engine, single, dry_run=False, cancel_check=None):
    if payload.get('operation') == 'prepare_context_inputs':
        return single(payload, dry_run=dry_run)
    if not payload.get('generation_policy'):
        checkpoint = Path(payload.get('output_dir', '')) / 'generation_rounds.json'
        if not checkpoint.is_file():
            return single(payload, dry_run=dry_run)
    key = 'target_num_molecules' if engine == 'ecloudgen' else 'num_molecules'
    target = validate_count(engine, payload.get(key, 100))
    first = round_payload(payload, engine, 0)
    if dry_run:
        return {**single(first, dry_run=True), 'requested_count': target,
                'round_target': first[key], 'generation_strategy': payload.get('generation_policy', 'independent_rounds_v1'),
                'max_rounds': generation_round_limit(payload, engine, target),
                'time_budget_seconds': TASK_SECONDS * payload.get('generation_window', 1)}
    output = Path(payload['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.generation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run_locked(payload, engine, target, lock.fileno(), cancel_check)


def _run_locked(payload, engine, target, lock_fd, cancel_check):
    output = Path(payload['output_dir'])
    checkpoint = output / 'generation_rounds.json'
    revised = payload.get('generation_policy') == GENERATION_POLICY
    binding = {k: v for k, v in payload.items()
               if not revised or k not in {'job_id', 'generation_window', 'previous_output_csv'}}
    state = json.loads(checkpoint.read_text()) if checkpoint.is_file() else {
        'version': 2 if revised else 1, 'engine': engine, 'payload': binding, 'rounds': [], 'elapsed_seconds': 0}
    if state['payload'] != binding or state['engine'] != engine:
        raise ValueError('Generation checkpoint belongs to different inputs or parameters')
    pool = {}
    for record in state['rounds']:
        collect_result(pool, engine, record['result'], [] if revised else None)
    window = payload.get('generation_window', 1)
    limit = TASK_SECONDS * window

    def progress():
        if revised:
            save_json(output / 'generation_progress.json', {
                'queue_job_id': payload.get('job_id'), 'requested_count': target,
                'result_count': min(len(pool), target), 'completed_rounds': len(state['rounds']),
            })

    progress()
    round_limit = generation_round_limit(payload, engine, target)

    def after_round():
        if len(pool) >= target:
            return 'target_reached'
        rounds = state['rounds']
        if not rounds:
            return None
        if revised and (engine == 'surfgen' and round_limit == 1 or engine == 'delete' and
                        (len(rounds) >= 2 or len(pool) * 10 < target * 9)):
            reason = rounds[-1]['result'].get('stop_reason') or 'search_budget_exhausted'
            return 'validation_shortfall' if reason == 'target_reached' else reason
        if len(rounds) >= 3 and all(not row['new_unique_count'] for row in rounds[-3:]):
            return 'no_new_unique_molecules'
        return None

    stopped = after_round() or 'round_budget_exhausted'
    for number in range(len(state['rounds']), round_limit):
        reason = after_round()
        if reason:
            stopped = reason
            break
        if cancel_check and cancel_check():
            raise RuntimeError('CANCELED: molecule generation was canceled')
        remaining = limit - state['elapsed_seconds']
        if remaining <= 0:
            stopped = 'time_budget_exhausted'
            break
        current = round_payload(payload, engine, number)
        directory = Path(current['output_dir'])
        directory.mkdir(parents=True, exist_ok=True)
        result_path = directory / 'execution_result.json'
        result_path.unlink(missing_ok=True)
        started = time.monotonic()
        previous_elapsed = state['elapsed_seconds']
        last_saved = started
        with (directory / 'execution.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'genova_runtime.generation_rounds',
                engine, str(result_path)], stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                text=True, start_new_session=True, pass_fds=(lock_fd,))
            process.stdin.write(json.dumps(current))
            process.stdin.close()
            reason = None
            while process.poll() is None:
                if cancel_check and cancel_check():
                    reason = 'canceled'
                elif time.monotonic() - started >= remaining:
                    reason = 'time_budget_exhausted'
                if reason:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                if time.monotonic() - last_saved >= 10:
                    state['elapsed_seconds'] = previous_elapsed + time.monotonic() - started
                    save_json(checkpoint, state)
                    last_saved = time.monotonic()
                time.sleep(0.25)
        state['elapsed_seconds'] = previous_elapsed + time.monotonic() - started
        if reason:
            state['interruption'] = {'round': number, 'reason': reason}
            save_json(checkpoint, state)
            if reason == 'canceled':
                raise RuntimeError('CANCELED: molecule generation was canceled')
            stopped = reason
            break
        if process.returncode or not result_path.is_file():
            error = json.loads(result_path.read_text()).get('error') if result_path.is_file() else 'No round result'
            fallback = (revised and engine == 'ecloudgen' and current.get('full_target_round')
                        and 'out of memory' in (error or '').lower())
            if not fallback:
                save_json(checkpoint, state)
                raise RuntimeError(f'{engine} round {number} failed: {error}; inspect {directory / "execution.log"}')
            result = {'result_count': 0, 'stop_reason': 'out_of_memory'}
        else:
            result = json.loads(result_path.read_text())['result']
        rejected = [] if revised else None
        try:
            added = collect_result(pool, engine, result, rejected)
        except StructureCountMismatch:
            if not revised:
                raise
            added = 0
            result = {**result, 'result_count': 0, 'stop_reason': 'structure_count_mismatch'}
        seed = current['optimizer']['seed'] if engine == 'epso' else current['seed']
        state['rounds'].append({'round': number, 'seed': seed, 'new_unique_count': added,
            'unique_pool_count': len(pool), 'elapsed_seconds': time.monotonic() - started, 'result': result,
            'stop_reason': result.get('stop_reason'), 'rejected_count': len(rejected or ())})
        if rejected:
            save_json(directory / 'rejected_structures.json', rejected)
        save_json(checkpoint, state)
        progress()
        reason = after_round()
        if reason:
            stopped = reason
            break
    published = payload
    if revised:
        destination = output / 'published' / str(payload.get('job_id') or 'local')
        destination.mkdir(parents=True, exist_ok=True)
        published = {**payload, 'output_dir': str(destination)}
        for key in ('output_csv', 'generated_sdf'):
            published.pop(key, None)
    artifacts, count = write_outputs(published, engine, pool, state['rounds'], target)
    last = next((item['result'] for item in reversed(state['rounds']) if item['result'].get('result_count')), {})
    result = {**last, **artifacts, 'task': engine, 'engine': engine,
        'requested_count': target, 'result_count': count, 'shortfall': max(0, target - count),
        'reached_target': count == target, 'stop_reason': stopped,
        'generation_strategy': GENERATION_POLICY if revised else 'independent_rounds_v1', 'unique_pool_count': len(pool),
        'elapsed_seconds': state['elapsed_seconds'], 'time_budget_seconds': limit,
        'max_rounds': round_limit, 'completed_rounds': len(state['rounds']),
        'rounds': [{k: v for k, v in record.items() if k != 'result'} for record in state['rounds']]}
    counters = {}
    for record in state['rounds']:
        for key, value in record['result'].get('generation_stats', {}).items():
            if type(value) in (int, float) and key not in {'optimization_steps', 'unique_pool_count', 'unique_evaluated_count'}:
                counters[key] = counters.get(key, 0) + value
    result['generation_stats'] = {**counters, 'unique_pool_count': len(pool)}
    for key in ('sampled_count', 'valid_count', 'decoded_clouds', 'generated_clouds'):
        if key in last or engine == 'ecloudgen':
            result[key] = sum(r['result'].get(key, 0) for r in state['rounds'])
    if engine == 'ecloudgen':
        result['new_unique_count'] = len(pool)
        result['duplicate_count'] = result['valid_count'] - len(pool)
        result['generation_stats']['duplicate_count'] = result['duplicate_count']
        result.pop('unique_pool_csv', None)
    if engine == 'epso':
        result['unique_evaluated_count'] = len(pool)
        result['decode_failures'] = counters.get('failed_decode_request_count', 0)
        result['no_new_molecules'] = len(pool) <= 1
        result['no_fitness_improvement'] = all(r['result'].get('no_fitness_improvement', False) for r in state['rounds'])
        if state['rounds']:
            detail = json.loads(Path(state['rounds'][0]['result']['metadata_json']).read_text())
            result.update({key: detail[key] for key in ('fixed_parameters', 'reference_smiles', 'versions', 'checkpoint')})
        from genova_runtime.epso_objectives import validate_parameters
        result['parameters'] = validate_parameters({key: payload[key] for key in ('num_molecules', 'objectives', 'optimizer') if key in payload})
        result.pop('unique_pool_csv', None)
    if revised:
        result['rejected_structure_count'] = sum(row.get('rejected_count', 0) for row in state['rounds'])
        result['can_continue_generation'] = (
            window == 1 and 0 < count < target and stopped == 'time_budget_exhausted'
            and len(state['rounds']) < MAX_ROUNDS
            and engine == 'surfgen' and target > ROUND_TARGET)
    metadata = Path(published['output_dir']) / 'generation_metadata.json'
    result['generation_metadata'] = str(metadata)
    if engine == 'epso':
        result['metadata_json'] = str(metadata)
    elif count:
        from genova_runtime.context_features import consume_context_inputs, generation_context_report
        initialized = consume_context_inputs(payload, engine)
        result = generation_context_report({**initialized, 'output_dir': published['output_dir']}, result)
    save_json(metadata, result)
    if not count:
        raise RuntimeError(f'{engine} generated no valid unique molecules; {metadata}')
    return result


if __name__ == '__main__':
    engine, destination = sys.argv[1:]
    try:
        adapter = importlib.import_module(f'genova_runtime.entry_{engine}')
        result = adapter.run_single_job(json.load(sys.stdin))
        save_json(Path(destination), {'status': 'succeeded', 'result': result})
    except Exception as exc:
        traceback.print_exc()
        save_json(Path(destination), {'status': 'failed', 'error': str(exc)})
        sys.exit(1)
