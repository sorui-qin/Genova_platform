import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rdkit import Chem

from genova_runtime import generation_rounds as rounds
from genova_runtime.generation_settings import sampling_plan


def write_csv(path, smiles):
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['smiles'])
        writer.writerows((value,) for value in smiles)


def write_sdf(path, smiles):
    with Chem.SDWriter(str(path)) as writer:
        for value in smiles:
            mol = Chem.MolFromSmiles(value)
            c = Chem.Conformer(mol.GetNumAtoms())
            c.Set3D(True)
            for index in range(mol.GetNumAtoms()):
                c.SetAtomPosition(index, (index, index % 3, index % 2))
            mol.AddConformer(c)
            writer.write(mol)


class GenerationRoundsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.calls = []
        for target, replacement in (
            ('consume_context_inputs', lambda payload, engine: payload),
            ('generation_context_report', lambda payload, result: result),
        ):
            modifier = patch(f'genova_runtime.context_features.{target}', replacement)
            modifier.start()
            self.addCleanup(modifier.stop)

    def fake_worker(self, outcomes):
        def spawn(command, **kwargs):
            child = Mock()

            def finish():
                payload = json.loads(child.stdin.write.call_args.args[0])
                self.calls.append(payload)
                smiles, sdf_smiles = next(outcomes)
                output = Path(payload['output_dir'])
                csv_path = output / 'results.csv'
                write_csv(csv_path, smiles)
                result = {'output_csv': str(csv_path), 'result_count': len(smiles), 'stop_reason': 'target_reached'}
                if sdf_smiles is not None:
                    sdf = output / 'generated.sdf'
                    write_sdf(sdf, sdf_smiles)
                    result['generated_sdf'] = str(sdf)
                rounds.save_json(Path(command[-1]), {'result': result})
                return 0

            child.poll.side_effect = finish
            child.returncode = 0
            return child
        return patch.object(rounds.subprocess, 'Popen', side_effect=spawn)

    def payload(self, engine, target):
        key = 'target_num_molecules' if engine == 'ecloudgen' else 'num_molecules'
        return {key: target, 'generation_policy': rounds.GENERATION_POLICY,
                'output_dir': str(self.root), 'seed': 42, 'job_id': 'initial'}

    def run_task(self, engine, payload, outcomes):
        with self.fake_worker(iter(outcomes)):
            return rounds.run_generation(payload, engine, None)

    def test_surfgen_small_job_uses_one_seed(self):
        payload = self.payload('surfgen', 1000)
        result = self.run_task('surfgen', payload, [(['CC'], ['CC'])])
        self.assertEqual([row['seed'] for row in self.calls], [42])
        self.assertEqual(result['result_count'], 1)
        self.assertFalse(result['can_continue_generation'])

    def test_delete_validates_then_fills_a_small_gap_once(self):
        payload = self.payload('delete', 10)
        nine = ['C' * i for i in range(1, 10)]
        result = self.run_task('delete', payload, [
            (nine + ['CO'], nine + ['CN']),
            (['CC', 'CO'], ['CC', 'CO']),
        ])
        self.assertEqual(result['result_count'], 10)
        self.assertEqual(result['rejected_structure_count'], 1)
        self.assertEqual(result['completed_rounds'], 2)
        self.assertEqual([row['seed'] for row in self.calls], [42, 10000042])
        self.assertEqual(len(list(rounds.structure_records(result))), 10)

    def test_delete_larger_gap_stops_and_replaying_does_not_add_a_round(self):
        payload = self.payload('delete', 10_000)
        result = self.run_task('delete', payload, [(['CC'], ['CC'])])
        replay = self.run_task('delete', payload, [])
        self.assertEqual(self.calls[0]['num_molecules'], 10_000)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(replay['result_count'], result['result_count'])

    def test_ecloudgen_qualified_first_round_uses_full_target(self):
        payload = self.payload('ecloudgen', 50_000)
        plan = sampling_plan(50_000, full_target=True)
        payload.update(num_clouds=plan['num_clouds'], decodes_per_cloud=100, ecloudgen_full_target=True)
        self.assertEqual(plan['num_clouds'], 1552)
        self.assertEqual(plan['max_samples'], 465600)
        first = rounds.round_payload(payload, 'ecloudgen', 0)
        second = rounds.round_payload(payload, 'ecloudgen', 1)
        self.assertEqual((first['target_num_molecules'], first['num_clouds']), (50_000, 1552))
        self.assertEqual((second['target_num_molecules'], second['num_clouds']), (1000, 32))

    def test_surfgen_excludes_a_misaligned_round_and_keeps_other_results(self):
        payload = self.payload('surfgen', 1001)
        result = self.run_task('surfgen', payload, [
            (['CC'], ['CC']),
            (['CO', 'CN'], ['CO']),
            (['CC', 'CCC'], ['CC', 'CCC']),
            (['CC'], ['CC']),
            (['CC'], ['CC']),
            (['CC'], ['CC']),
        ])
        self.assertEqual(result['result_count'], 2)
        self.assertEqual(result['stop_reason'], 'no_new_unique_molecules')
        self.assertEqual(result['rounds'][1]['stop_reason'], 'structure_count_mismatch')
        self.assertEqual([row[0] for row in rounds.structure_records(result)], ['CC', 'CCC'])

    def test_continue_keeps_published_candidates_and_advances_seed(self):
        payload = self.payload('surfgen', 3)
        original = self.root / 'first.csv'
        structures = self.root / 'first.sdf'
        write_csv(original, ['C', 'CC'])
        write_sdf(structures, ['C', 'CC'])
        with patch.object(rounds, 'TASK_SECONDS', 10), patch.object(rounds, 'ROUND_TARGET', 2):
            rounds.save_json(self.root / 'generation_rounds.json', {
                'version': 2, 'engine': 'surfgen', 'elapsed_seconds': 10,
                'payload': {k: v for k, v in payload.items() if k != 'job_id'},
                'rounds': [{'round': 0, 'seed': 42, 'new_unique_count': 2,
                            'result': {'result_count': 2, 'output_csv': str(original),
                                       'generated_sdf': str(structures)}}],
            })
            first = self.run_task('surfgen', payload, [])
            self.assertTrue(first['can_continue_generation'])
            self.assertEqual(first['stop_reason'], 'time_budget_exhausted')
            second = self.run_task('surfgen', {
                **payload, 'job_id': 'continued', 'generation_window': 2,
                'previous_output_csv': first['output_csv'],
            }, [(['CC', 'CCC'], ['CC', 'CCC'])])
        self.assertFalse(second['can_continue_generation'])
        self.assertEqual(self.calls[0]['seed'], 10000042)
        self.assertEqual(second['result_count'], 3)
        self.assertIn('\nC\nCC\n', Path(second['output_csv']).read_text())
        self.assertIn('\nC\nCC\n', Path(first['output_csv']).read_text())
        self.assertNotEqual(first['output_csv'], second['output_csv'])

    def test_ecloudgen_partial_first_round_is_followed_by_bounded_rounds(self):
        payload = self.payload('ecloudgen', 1001)
        payload.update(num_clouds=32, decodes_per_cloud=100, ecloudgen_full_target=True)
        result = self.run_task('ecloudgen', payload, [
            (['C', 'CC'], None), (['CC', 'CO'], None),
            (['C'], None), (['C'], None), (['C'], None),
        ])
        self.assertEqual([p['target_num_molecules'] for p in self.calls], [1001] + [1000] * 4)
        self.assertEqual(result['result_count'], 3)
        self.assertEqual(result['shortfall'], 998)
        self.assertFalse(result['can_continue_generation'])

    def test_queued_job_without_a_generation_policy_keeps_its_original_execution(self):
        single = Mock(return_value={'result_count': 10})
        payload = {'num_molecules': 10, 'output_dir': str(self.root), 'seed': 2030}
        self.assertEqual(rounds.run_generation(payload, 'delete', single), {'result_count': 10})
        single.assert_called_once_with(payload, dry_run=False)
