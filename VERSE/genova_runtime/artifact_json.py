import gzip
import json
import io
from pathlib import Path


def read_json(path):
    path = Path(path)
    with open_json(path) as stream:
        return json.load(stream)


def open_json(path):
    path = Path(path)
    return gzip.open(path, 'rt', encoding='utf-8') if path.suffix == '.gz' else path.open(encoding='utf-8')


def compress_json(path):
    path = Path(path)
    if path.suffix == '.gz':
        return path
    target = path.with_suffix(path.suffix + '.gz')
    data = json.dumps(read_json(path), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    temporary = target.with_suffix('.tmp')
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', filename='', compresslevel=6, mtime=0) as stream:
        stream.write(data)
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(target)
    return target


def finalize_artifacts(result):
    from genova_runtime.pdb2pqr_compat import file_sha256
    result = dict(result)
    keys = ('atom_map', 'component_manifest', 'context_receptor_map', 'report', 'results_json',
            'context_preparation_report', 'component_usage_report')
    for key in keys:
        if result.get(key):
            source = Path(result[key])
            if key == 'report' and source.suffix != '.gz' and result.get('artifact_sha256'):
                report = read_json(source)
                for name, item in report.get('artifacts', {}).items():
                    if name in result:
                        item['path'] = result[name]
                source.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False))
            target = compress_json(source)
            result[key] = str(target)
            if key in result.get('artifact_sha256', {}):
                result['artifact_sha256'][key] = file_sha256(target)
    return result
