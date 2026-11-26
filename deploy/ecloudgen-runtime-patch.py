"""Apply platform decoding, ligand-optional cached inputs and xTB failure diagnostics."""
import ast
from pathlib import Path

path = Path('/app/models/ECloudDecipher/generative/coati_purifications.py')
source = path.read_text()
head, body = source.split('def force_decode_valid_batch(', 1)
for old, new in (
    ('    max_attempts: int = 4,\n', '    max_attempts: int = 4,\n    strict: bool = False,\n'),
    ('if not mol is None:', 'if mol is not None and (not strict or mol.GetNumAtoms()):'),
    ('                            slist.append(Chem.MolToSmiles(mol))',
     '                            canonical = Chem.MolToSmiles(mol)\n'
     '                            if Chem.MolFromSmiles(canonical) is not None:\n'
     '                                slist.append(canonical)'),
    ('        except Exception as Ex:\n            print(Ex)',
     '        except Exception as Ex:\n            if strict:\n                raise\n            print(Ex)'),
    ('    return "C"', '    return None if strict else "C"'),
):
    if body.count(new) == 1:
        continue
    if body.count(old) != 1:
        raise ValueError(f'Unexpected ECloudGen decoder source: {old!r}')
    body = body.replace(old, new)
source = head + 'def force_decode_valid_batch(' + body
ast.parse(source)
path.write_text(source)

path = Path('/app/generate_from_pdb.py')
source = path.read_text()
tree = ast.parse(source)
method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'sample_from_pdb')
lines = source.splitlines(keepends=True)
replacement = """    def sample_from_pdb(self, pdb_file, lig_file, num_gen=8, batch=1, protein_channel_full=False):
        # GENOVA_POCKET_INPUTS_V2: cached protein occupancy requires no ligand.
        cached_features = os.environ.get('GENOVA_ECLOUD_INPUTS')
        if cached_features:
            with np.load(cached_features, allow_pickle=False) as features:
                pkt_channel = features['pkt_channel']
            if pkt_channel.shape != (32, 32, 32, 5):
                raise ValueError('Invalid cached context feature dimensions')
            if not np.isfinite(pkt_channel).all() or not np.any(pkt_channel[:,:,:,4]):
                raise ValueError('Invalid cached context features')
        else:
            lig_mol = Chem.SDMolSupplier(lig_file, sanitize=False)[0]
            positions = lig_mol.GetConformer().GetPositions()
            centroid = positions[[a.GetIdx() for a in lig_mol.GetAtoms() if a.GetAtomicNum() > 1]].mean(axis=0)
            pkt_file = pocket_trunction(pdb_file, centroid=centroid)
            pkt_mol = Chem.MolFromPDBFile(pkt_file)
            os.remove(pkt_file)
            pkt_channel, _, _ = get_pocket_channel(pkt_mol, grid_protocol=protocol(32))
        return self._sample_channel(pkt_channel, num_gen, batch, protein_channel_full)
"""
source = ''.join(lines[:method.lineno - 1]) + replacement + ''.join(lines[method.end_lineno:])
source = source.replace('protocol, get_occu_ecloud_pair, get_pocket_channel', 'protocol, get_pocket_channel')
source = source.replace('ecloud_pre, pkt_ecloud, ecloud_ref = sampler.sample_from_pdb', 'ecloud_pre, pkt_ecloud = sampler.sample_from_pdb')
source = source.replace("    np.save(os.path.join(args.outputs_dir, f'./{lig_filename}_ecloudref.npy'), ecloud_ref)\n", '')
source = source.replace("default='./play_around/peptide_example/7ux5_peptide.sdf'", 'default=None')
source = source.replace('os.path.basename(args.lig_file)[:-4]', "os.path.basename(args.lig_file)[:-4] if args.lig_file else 'reference'")
source = source.replace('    shutil.copy(args.lig_file, args.outputs_dir)', '    if args.lig_file:\n        shutil.copy(args.lig_file, args.outputs_dir)')
ast.parse(source)
path.write_text(source)

path = Path('/app/ecloud_utils/xtb_density.py')
source = path.read_text()
start = source.index('    def calculate(self, mol:')
end = source.index('\n    def ', start + 5)
replacement = '''    def calculate(self, mol: rd.Chem.rdchem.Mol) -> dict:
        import subprocess
        rd.Chem.rdmolfiles.MolToXYZFile(mol, self.workdir + '/tmp.xyz')
        log_path = self.workdir + '/log'
        with open(log_path, 'w') as log:
            process = subprocess.run([self.xtb_command, '--norestart', '--input', 'xtb.inp', 'tmp.xyz'],
                cwd=self.workdir, stdout=log, stderr=subprocess.STDOUT, check=False)
        self._errno = process.returncode
        if process.returncode:
            retained = self.rootdir + '/xtb_failure_' + os.path.basename(self.workdir) + '.log'
            shutil.copyfile(log_path, retained)
            with open(log_path, errors='replace') as log:
                detail = log.read().lower()
            code = 'XTB_SCC_NOT_CONVERGED' if ('did not converge' in detail or 'convergence criteria cannot be satisfied' in detail) else 'XTB_EXECUTION_FAILED'
            raise RuntimeError(f'{code}: xTB exited with {process.returncode}; original output retained in {retained}')
        try:
            density, meta = cubtools.read_cube(self.workdir + '/density.cub')
            meta['org'] = numpy.array(meta['org']) / BOHR
            meta['len'] = (numpy.array(meta['xvec']) * meta['nx'] +
                           numpy.array(meta['yvec']) * meta['ny'] +
                           numpy.array(meta['zvec']) * meta['nz']) / BOHR
            return {'density': density * (BOHR ** 3), 'meta': meta}
        except Exception as error:
            retained = self.rootdir + '/xtb_failure_' + os.path.basename(self.workdir) + '.log'
            shutil.copyfile(log_path, retained)
            raise RuntimeError(f'XTB_DENSITY_INVALID: {error}; original output retained in {retained}') from error
'''
source = source[:start] + replacement + source[end:]
ast.parse(source)
path.write_text(source)
