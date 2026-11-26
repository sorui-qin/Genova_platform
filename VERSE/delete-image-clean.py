"""Select runtime files from the backed-up DELETE image for a fresh final stage."""
import ast
import fnmatch
import hashlib
import shutil
from pathlib import Path

DEST = Path('/clean')
MODEL = Path('/code/components/Delete')
IGNORE = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '.git', '*.ipynb', '*:Zone.Identifier',
    'direct_url.json', 'conda-meta', 'tests', 'test', '*.log', 'io.mc',
)


def copy(path):
    target = DEST / path.relative_to('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        shutil.copytree(path, target, symlinks=True, ignore=IGNORE)
    else:
        shutil.copy2(path, target, follow_symlinks=False)


packages = Path('/usr/local/lib/python3.8/dist-packages')
inference = (
    'Bio* easydict* lmdb* numpy* pandas* plyfile* PyYAML* yaml _yaml rdkit* '
    'redis* async_timeout* PyJWT* jwt torch* scipy* sklearn scikit_learn* '
    'joblib* threadpoolctl* tqdm* typing_extensions* dateutil python_dateutil* '
    'pytz* tzdata* six* requests* urllib3* certifi* charset_normalizer* idna* '
    'PIL Pillow* jinja2 Jinja2* markupsafe MarkupSafe* pyparsing*'
).split()
for path in sorted(packages.iterdir()):
    if any(fnmatch.fnmatchcase(path.name, pattern) for pattern in inference):
        copy(path)

# Keep the native surface environment without Conda history or web services.
surface = Path('/opt/conda/envs/surfmaker')
for path in (surface / 'lib').iterdir():
    if path.name != 'python3.6' and not path.name.endswith('.a'):
        copy(path)
stdlib = surface / 'lib/python3.6'
for path in stdlib.iterdir():
    if path.name not in {'site-packages', '__pycache__', 'test'}:
        copy(path)
surface_packages = (
    'Bio* numpy* scipy* rdkit* pymesh* plyfile* joblib* IPython ipython* '
    'traitlets* decorator* six* jedi* parso* backcall* pickleshare* pexpect* '
    'ptyprocess* prompt_toolkit* wcwidth* pygments* Pygments* dateutil '
    'python_dateutil* pytz* pkg_resources setuptools* typing_extensions* tqdm* '
    'packaging* pyparsing* PIL Pillow* reportlab* cairo* pycairo* matplotlib* '
    'mpl_toolkits cycler* kiwisolver* certifi* pandas*'
).split()
for path in sorted((stdlib / 'site-packages').iterdir()):
    if any(fnmatch.fnmatchcase(path.name, pattern) for pattern in surface_packages):
        copy(path)
for path in (surface / 'bin').glob('python*'):
    if not path.name.endswith('-config'):
        copy(path)
copy(surface / 'COPYING')
if (surface / 'share/licenses').exists():
    copy(surface / 'share/licenses')

for relative in ('main.py', 'get_ply.py', 'src/main_gen.py', 'src/configs/sample.yml',
                 'delete_input/src/main.py', 'delete_input/src/base.py'):
    copy(MODEL / relative)
for relative in ('src/models', 'src/utils', 'delete_input/src/models/masif'):
    for path in (MODEL / relative).rglob('*.py'):
        if not any(part.startswith('test') or part == '__pycache__' for part in path.parts):
            copy(path)
for name in ('APBS-3.0.0.Linux', 'pdb2pqr-linux-bin64-2.1.1'):
    copy(MODEL / 'delete_input/src/inputs' / name)
copy(Path('/opt/delete/delete.pt'))

# Remove the standalone demo and its old input names; keep the callable unchanged.
main = DEST / MODEL.relative_to('/') / 'main.py'
source = main.read_text()
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
main.write_text(''.join(
    ''.join(lines[node.lineno - 1:node.end_lineno])
    for node in tree.body
    if not isinstance(node, ast.Expr)
    and not (isinstance(node, ast.If) and '__name__' in ast.dump(node.test))
))

for relative in ('src/online', 'src/input', 'src/output',
                 'delete_input/src/temp', 'delete_input/src/outputs/ply'):
    (DEST / MODEL.relative_to('/') / relative).mkdir(parents=True, exist_ok=True)

# A build fails if known company identifiers remain in selected text files.
manifest = []
for path in sorted(DEST.rglob('*')):
    if path.is_symlink() or not path.is_file():
        continue
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if path.stat().st_size <= 2 * 1024 * 1024:
        data = path.read_bytes().lower()
        assert not any(marker in data for marker in (b'carbonsilicon', b'feishu.cn')), str(path)
    manifest.append(f'{digest.hexdigest()}  /{path.relative_to(DEST)}\n')
(DEST / 'opt/delete/runtime-files.sha256').write_text(''.join(manifest))
