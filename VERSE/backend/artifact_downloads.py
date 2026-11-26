import gzip
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import FileResponse, StreamingResponse


def artifact_response(path, filename=None, media_type=None):
    path = Path(path)
    filename = filename or path.name
    if path.name.endswith('.json.gz'):
        def chunks():
            with gzip.open(path, 'rb') as stream:
                while chunk := stream.read(65536):
                    yield chunk
        return StreamingResponse(chunks(), media_type='application/json',
            headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename.removesuffix('.gz'))})
    return FileResponse(path=str(path), filename=filename, media_type=media_type)
