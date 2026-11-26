
import json
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI

from backend.db import get_db
from backend.deps import get_current_user
from backend.models import Dataset
from backend.routers import datasets


class DatasetFilenameTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        data_root = patch.object(datasets.settings, "data_root", Path(self.temp.name))
        data_root.start()
        self.addCleanup(data_root.stop)
        admission = patch("backend.services.resources.check_admission", return_value=10_000)
        admission.start()
        self.addCleanup(admission.stop)

        self.rows = []
        self.db = Mock()

        def add(row):
            if isinstance(row, Dataset):
                row.id = uuid.uuid4()
            self.rows.append(row)

        self.db.add.side_effect = add
        self.db.scalars.return_value.all.side_effect = lambda: [
            row for row in self.rows if not isinstance(row, Dataset)
        ]
        self.user = SimpleNamespace(id=uuid.uuid4(), is_guest=True)
        self.app = FastAPI()
        self.app.include_router(datasets.router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.user

    async def request(self, method, path, body, content_type):
        messages = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await self.app({
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "root_path": "",
            "query_string": b"",
            "headers": [(b"content-type", content_type)],
            "client": ("127.0.0.1", 10000),
            "server": ("test", 80),
        }, receive, send)
        response = next(message for message in messages if message["type"] == "http.response.start")
        content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return response["status"], dict(response["headers"]), content

    async def upload(self, filename, *, charset=b"utf-8"):
        body = (
            b'--qa\r\nContent-Disposition: form-data; name="name"\r\n\r\nExample\r\n'
            b'--qa\r\nContent-Disposition: form-data; name="kind"\r\n\r\nupload\r\n'
            b'--qa\r\nContent-Disposition: form-data; name="files"; filename="' + filename +
            b'"\r\nContent-Type: text/plain\r\n\r\nfixture\r\n--qa--\r\n'
        )
        return await self.request("POST", "/api/v1/datasets/upload", body,
                                  b"multipart/form-data; boundary=qa; charset=" + charset)

    async def test_255_utf8_bytes_preserve_original_and_use_short_storage_path(self):
        filename = "测" * 83 + "AB.sdf"
        self.assertEqual(len(filename.encode("utf-8")), 255)
        status, _, body = await self.upload(filename.encode("utf-8"), charset=b"latin-1")

        self.assertEqual(status, 200, body)
        row = json.loads(body)["files"][0]
        self.assertEqual(row["original_filename"], filename)
        saved = self.rows[1]
        path = Path(saved.storage_path)
        self.assertEqual(path.name, row["id"] + ".sdf")
        self.assertEqual(path.read_bytes(), b"fixture")

    async def test_legacy_upload_boundary_is_now_accepted(self):
        for size in (218, 219, 220):
            with self.subTest(size=size):
                self.rows.clear()
                filename = b"a" * (size - 4) + b".sdf"
                status, _, body = await self.upload(filename)
                self.assertEqual(status, 200, body)
                row = json.loads(body)["files"][0]
                self.assertEqual(row["original_filename"], filename.decode("ascii"))
                self.assertEqual(Path(self.rows[1].storage_path).name, row["id"] + ".sdf")

    async def test_single_download_preserves_legacy_path_and_original_name(self):
        name = "配体.sdf"
        status, _, body = await self.upload(name.encode("utf-8"))
        self.assertEqual(status, 200, body)
        dataset, row = self.rows
        saved = Path(row.storage_path)
        legacy = saved.with_name(f"{row.id}_{row.original_filename}")
        saved.rename(legacy)
        row.storage_path = str(legacy)
        self.db.scalar.return_value = dataset
        status, headers, payload = await self.request(
            "GET", f"/api/v1/datasets/{dataset.id}/download", b"", b"application/octet-stream"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload, b"fixture")
        self.assertIn(b"%E9%85%8D%E4%BD%93.sdf", headers[b"content-disposition"])

    async def test_256_bytes_are_rejected_before_creating_dataset(self):
        filename = ("测" * 84 + ".sdf").encode("utf-8")
        self.assertEqual(len(filename), 256)
        status, _, body = await self.upload(filename)
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["detail"], {
            "error_code": "FILENAME_TOO_LONG",
            "actual_bytes": 256,
            "max_bytes": 255,
        })
        self.db.add.assert_not_called()

    async def test_invalid_utf8_is_rejected_without_charset_fallback(self):
        # A legacy single-byte filename in the isolated request.
        filename = "café.sdf".encode("latin-1")
        status, _, body = await self.upload(filename, charset=b"latin-1")
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["detail"], "FILENAME_INVALID_UTF8")
        self.db.add.assert_not_called()

    async def test_file_rename_counts_extension_and_utf8_bytes(self):
        status, _, body = await self.upload(b"short.sdf")
        self.assertEqual(status, 200, body)
        dataset, row = self.rows
        self.db.scalar.side_effect = [dataset, dataset, row]
        path = f"/api/v1/datasets/{dataset.id}"

        async def rename(name):
            payload = json.dumps({"name": name, "file_id": str(row.id)}).encode("utf-8")
            return await self.request("PATCH", path, payload, b"application/json")

        status, _, body = await rename("测" * 84 + ".sdf")
        self.assertEqual(status, 422, body)
        self.assertEqual(json.loads(body)["detail"]["error_code"], "FILENAME_TOO_LONG")
        old_path = row.storage_path
        filename = "测" * 83 + "AB.sdf"
        status, _, body = await rename(filename)
        self.assertEqual(status, 200, body)
        self.assertEqual(row.original_filename, filename)
        self.assertEqual(row.storage_path, old_path)

    def test_archive_duplicates_stay_within_byte_limit(self):
        name = "测" * 83 + "AB.sdf"
        used = set()
        self.assertEqual(datasets._archive_filename(name, used), name)
        second = datasets._archive_filename(name, used)
        self.assertNotEqual(second, name)
        self.assertTrue(second.endswith("_1.sdf"))
        self.assertLessEqual(len(second.encode("utf-8")), 255)

    def test_compressed_json_keeps_download_format(self):
        file_id = uuid.uuid4()
        self.assertEqual(datasets._upload_storage_name(file_id, "report.json.gz"), f"{file_id}.json.gz")
