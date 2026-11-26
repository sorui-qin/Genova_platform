"""Shared export of an already selected, ordered list of physical result records."""
import csv
import io
import json

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from backend.services.jobs import resolve_job_artifact, DomainValidationError
from genova_runtime.structure_index import structure_index, read_record
from tarpass.filters import METRICS, metric_value
from tarpass.selection import CLUSTER_FIELDS


def export_rows(job, task, rows, *, pose="docked", format="csv", clustering=False):
    headers = {'Content-Disposition': f'attachment; filename="tarpass-{pose}.{format}"'}
    if format == 'csv':
        cluster_fields = CLUSTER_FIELDS if clustering else ()
        fields = ['molecule_id', 'source_index', 'smiles', 'status', 'has_original_pose', *sorted(METRICS), *cluster_fields, 'prefilter_reasons', 'errors']
        def chunks():
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for index, row in enumerate(rows):
                writer.writerow({**{key: row[key] for key in fields[:4]}, 'has_original_pose': row.get('has_original_pose'), **{key: metric_value(row, key) for key in METRICS},
                    **{key: row[key] for key in cluster_fields}, 'prefilter_reasons': json.dumps(row.get('prefilter_reasons', [])),
                    'errors': json.dumps({'input': row['errors'], 'original': row['metrics'].get('original', {}).get('errors'),
                                         'docked': row['metrics'].get('docked', {}).get('errors')})})
                if index % 128 == 127:
                    yield stream.getvalue().encode()
                    stream.seek(0); stream.truncate()
            if stream.tell():
                yield stream.getvalue().encode()
        return StreamingResponse(chunks(), media_type='text/csv',
            headers={**headers, 'X-Exported-Count': str(len(rows)), 'X-Skipped-Count': '0'})
    if not task.output_payload.get(pose + '_sdf'):
        return StreamingResponse(iter(()), media_type='chemical/x-mdl-sdfile', headers={**headers,
            'X-Exported-Count': '0', 'X-Skipped-Count': str(len(rows)), 'X-Skipped-Reason': 'pose-unavailable'})
    try:
        sdf = resolve_job_artifact(job, task.output_payload.get(pose + '_sdf'))
    except DomainValidationError as exc:
        raise HTTPException(exc.http_status, {'error_code': exc.code, 'message': exc.message}) from exc
    by_id = structure_index(sdf)['names']
    ids = [by_id[row['molecule_id']][0] for row in rows if len(by_id.get(row['molecule_id'], [])) == 1]
    return StreamingResponse((read_record(sdf, index) for index in ids), media_type='chemical/x-mdl-sdfile',
        headers={**headers, 'X-Exported-Count': str(len(ids)), 'X-Skipped-Count': str(len(rows) - len(ids)), 'X-Skipped-Reason': 'missing-or-ambiguous-pose'})
