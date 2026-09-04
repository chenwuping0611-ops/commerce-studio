"""Offline storage and retention checks; no MySQL or go-fastdfs is contacted."""

from io import BytesIO
import base64
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import requests

from applications import create_app
from applications.common.storage import (
    FileService,
    GoFastDFSClient,
    StorageError,
    StoredFile,
)
from applications.studio.generation_service import (
    _extract_outputs,
    _result_payload_snapshot,
    _upload_provider_output,
)
from applications.studio.provider_client import normalize_balance
from applications.studio.retention import clear_stale_task_outputs
from applications.view.amazon_ai import routes as amazon_ai_routes
from applications.view.amazon_ai.routes import (
    _legacy_storage_refs as _task_legacy_storage_refs,
)


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeDownloadResponse:
    def __init__(self, content=b"new content", status_code=200):
        self.content = content
        self.status_code = status_code
        self.headers = {
            "Content-Type": "text/markdown",
            "Content-Length": str(len(content)),
        }

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024 * 1024):
        assert chunk_size == 1024 * 1024
        return iter((self.content,))

    def close(self):
        return None


class FakeSession:
    def __init__(self):
        self.last_files = None
        self.last_data = None

    def post(self, _endpoint, files=None, data=None, **_kwargs):
        self.last_files = files
        self.last_data = data
        return FakeResponse(
            {
                "data": {
                    "path": "group1/images/generated/mock.png",
                    "size": 3,
                    "md5": "mock-md5",
                }
            }
        )


class ReplacementSession:
    def __init__(
        self,
        content=b"new content",
        upload_error=None,
        verify_status=200,
        delete_failure=False,
        verify_statuses=None,
        path_from_filename=False,
        same_path=False,
    ):
        self.content = content
        self.upload_error = upload_error
        self.verify_status = verify_status
        self.verify_statuses = list(verify_statuses or [])
        self.delete_failure = delete_failure
        self.path_from_filename = path_from_filename
        self.same_path = same_path
        self.upload_count = 0
        self.delete_paths = []
        self.get_urls = []
        self.upload_filenames = []
        self.last_data = None

    def post(self, endpoint, files=None, data=None, **_kwargs):
        self.last_data = data
        if endpoint.endswith("/upload"):
            if self.upload_error:
                raise self.upload_error
            self.upload_count += 1
            filename = files["file"][0]
            self.upload_filenames.append(filename)
            path = (
                "group1/files/old-md5-name.md"
                if self.same_path
                else (
                    f"group1/files/{filename}"
                    if self.path_from_filename
                    else (
                        "group1/files/"
                        f"revision-{self.upload_count}.md"
                    )
                )
            )
            return FakeResponse(
                {
                    "data": {
                        "path": path,
                        "size": len(self.content),
                        "md5": f"new-md5-{self.upload_count}",
                        "filename": filename,
                    }
                }
            )
        if endpoint.endswith("/delete"):
            self.delete_paths.append(data["path"])
            if self.delete_failure:
                return FakeResponse(
                    {
                        "status": "fail",
                        "message": "old file cleanup failed",
                    }
                )
            return FakeResponse({"status": "success", "retcode": 0})
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    def get(self, url, **_kwargs):
        self.get_urls.append(url)
        status_code = (
            self.verify_statuses.pop(0)
            if self.verify_statuses
            else self.verify_status
        )
        return FakeDownloadResponse(
            content=self.content,
            status_code=status_code,
        )


def _replacement_client(session):
    client = GoFastDFSClient(
        {
            "GOFASTDFS_INTERNAL_URL": "http://127.0.0.1:9999",
            "GOFASTDFS_PUBLIC_URL": "https://ray.example/gofastdfs",
            "GOFASTDFS_VERIFY_SSL": False,
        }
    )
    client.session = session
    return client


def _old_file_info():
    return {
        "file_id": "business-file-123",
        "original_name": "test123.md",
        "url": (
            "https://ray.example/gofastdfs/"
            "group1/files/old-md5-name.md"
        ),
        "path": "/group1/files/old-md5-name.md",
        "md5": "old-md5",
        "content_type": "text/markdown",
    }


def test_gofastdfs_upload_response_normalization():
    client = GoFastDFSClient(
        {
            "GOFASTDFS_INTERNAL_URL": "http://127.0.0.1:9999",
            "GOFASTDFS_PUBLIC_URL": "https://ray.example/gofastdfs",
            "GOFASTDFS_VERIFY_SSL": False,
        }
    )
    session = FakeSession()
    client.session = session

    stored = client.upload_stream(
        BytesIO(b"abc"),
        "demo.png",
        content_type="image/png",
        category="images/generated",
    )

    assert stored.storage_path == "/group1/images/generated/mock.png"
    assert stored.public_url.endswith("/group1/images/generated/mock.png")
    assert stored.file_size == 3
    assert session.last_data["path"] == "images/generated"
    assert session.last_data["scene"] == "default"
    assert session.last_data["output"] == "json2"
    assert session.last_data["filename"] == session.last_files["file"][0]
    assert session.last_files["file"][0] == "demo.png"
    assert session.last_data["filename"] == "demo.png"
    assert stored.original_filename == "demo.png"


def test_gofastdfs_download_url_restores_original_filename():
    client = GoFastDFSClient(
        {
            "GOFASTDFS_INTERNAL_URL": "http://127.0.0.1:9999",
            "GOFASTDFS_PUBLIC_URL": "https://ray.example/gofastdfs",
            "GOFASTDFS_VERIFY_SSL": False,
        }
    )

    url = client.download_url_for(
        "https://ray.example/gofastdfs/group1/files/report.md?token=abc&name=old.md",
        "original report.txt",
    )
    query = parse_qs(urlsplit(url).query)

    assert query["token"] == ["abc"]
    assert query["download"] == ["1"]
    assert query["name"] == ["original report.txt"]
    assert url.count("name=") == 1


def test_gofastdfs_delete_uses_storage_path_and_checksum():
    session = ReplacementSession()
    client = _replacement_client(session)

    assert client.delete(
        (
            "https://ray.example/gofastdfs/group1/uploads/"
            "result-md5.txt?download=1&name=result.txt"
        ),
        checksum="result-checksum",
    )

    assert session.delete_paths == ["group1/uploads/result-md5.txt"]
    assert session.last_data["md5"] == "result-checksum"


def test_gofastdfs_replacement_uses_unique_storage_filename():
    session = ReplacementSession(path_from_filename=True)
    client = _replacement_client(session)

    stored = client.update(
        _old_file_info(),
        content=b"new content",
        filename="old-md5-name.md",
        category="files",
        delete_old=True,
    )

    assert stored.storage_path != "/group1/files/old-md5-name.md"
    assert stored.original_filename == "old-md5-name.md"
    assert len(session.upload_filenames) == 1
    assert session.upload_filenames[0] != "old-md5-name.md"
    assert session.delete_paths == ["group1/files/old-md5-name.md"]


def test_gofastdfs_replacement_accepts_reused_storage_path():
    session = ReplacementSession(same_path=True)
    client = _replacement_client(session)

    stored = client.update(
        _old_file_info(),
        content=b"new content",
        filename="old-md5-name.md",
        category="files",
        delete_old=True,
    )

    assert stored.storage_path == "/group1/files/old-md5-name.md"
    assert stored.original_filename == "old-md5-name.md"
    assert session.upload_count == 1
    assert session.delete_paths == []


def test_amazon_legacy_result_cleanup_only_selects_managed_urls():
    managed_url = (
        "https://ray.example/gofastdfs/group1/uploads/legacy-result.txt"
    )
    task = SimpleNamespace(
        file_refs_json=json.dumps({}, ensure_ascii=False),
        result_refs_json=json.dumps(
            {
                "response_download_url": managed_url,
                "response_filename": "legacy-result.txt",
                "response_md5": "legacy-md5",
                "output_urls": [
                    managed_url,
                    "https://cdn.example/should-not-delete.txt",
                ],
            },
            ensure_ascii=False,
        )
    )

    with patch.object(
        FileService,
        "is_managed_url",
        side_effect=lambda value: value.startswith(
            "https://ray.example/gofastdfs/"
        ),
    ):
        refs = _task_legacy_storage_refs(task, [])

    assert refs == [(managed_url, "legacy-md5")]


def test_amazon_task_delete_removes_legacy_managed_result_url():
    managed_url = (
        "https://ray.example/gofastdfs/group1/uploads/legacy-result.txt"
    )
    task = SimpleNamespace(
        id=42,
        task_code="AMZ-legacy-delete",
        dept_id=1,
        status="SUCCEEDED",
        output_asset_id=None,
        output_url="",
        output_checksum=None,
        input_asset_ids_json=json.dumps([], ensure_ascii=False),
        file_refs_json=json.dumps({}, ensure_ascii=False),
        result_refs_json=json.dumps(
            {
                "response_download_url": managed_url,
                "response_md5": "legacy-md5",
            },
            ensure_ascii=False,
        ),
        input_refs_json=json.dumps({"asset_ids": []}),
    )
    asset_query = MagicMock()
    fake_db = SimpleNamespace(session=MagicMock())
    fake_asset_model = SimpleNamespace(id=MagicMock(), query=asset_query)
    asset_query.filter.return_value.all.return_value = []

    with patch.object(
        amazon_ai_routes,
        "StudioAsset",
        fake_asset_model,
    ), patch.object(
        amazon_ai_routes,
        "db",
        fake_db,
    ), patch.object(
        FileService,
        "is_managed_url",
        return_value=True,
    ), patch.object(
        FileService,
        "delete_storage",
        return_value=True,
    ) as delete_storage:
        result = amazon_ai_routes._delete_amazon_task(task)

    assert result["deleted"] is True
    delete_storage.assert_called_once_with(
        managed_url,
        checksum="legacy-md5",
    )
    fake_db.session.delete.assert_called_once_with(task)
    fake_db.session.commit.assert_called_once()


def test_gofastdfs_http_200_failure_is_rejected():
    client = GoFastDFSClient(
        {
            "GOFASTDFS_INTERNAL_URL": "http://127.0.0.1:9999",
            "GOFASTDFS_PUBLIC_URL": "https://ray.example/gofastdfs",
            "GOFASTDFS_VERIFY_SSL": False,
        }
    )

    class FailedSession(FakeSession):
        def post(self, *_args, **_kwargs):
            return FakeResponse(
                {
                    "status": "fail",
                    "message": "md5 unvalid",
                    "data": None,
                }
            )

    client.session = FailedSession()
    try:
        client.upload_stream(
            BytesIO(b"abc"),
            "demo.png",
            content_type="image/png",
            category="images/generated",
        )
    except StorageError as exc:
        assert "md5 unvalid" in str(exc)
    else:
        raise AssertionError("HTTP 200 failure payload must be rejected")


def test_provider_result_snapshot_omits_large_base64_output():
    payload = {
        "id": "mock-image",
        "status": "completed",
        "data": [
            {
                "b64_json": "A" * 5_000_000,
                "format": "png",
                "width": 3200,
                "height": 1296,
            }
        ],
    }

    snapshot = _result_payload_snapshot(payload)

    assert len(snapshot.encode("utf-8")) < 65535
    assert "A" * 100 not in snapshot
    assert "BINARY_PAYLOAD_OMITTED" in snapshot


def test_provider_output_upload_retries_without_resubmitting_ai_request():
    app = create_app()
    upload_attempts = []

    def upload_local_file(path, **kwargs):
        upload_attempts.append((path, kwargs))
        assert os.path.isfile(path)
        if len(upload_attempts) == 1:
            raise StorageError("temporary GoFastDFS timeout")
        return StoredFile(
            storage_path="/group1/images/generated/retry.png",
            public_url=(
                "https://ray.example/gofastdfs/"
                "group1/images/generated/retry.png"
            ),
            original_filename="retry.png",
            content_type="image/png",
            file_size=3,
        )

    task = SimpleNamespace(
        task_code="retry01",
        user_id=1,
        dept_id=1,
    )
    with app.app_context(), patch.object(
        FileService,
        "upload_local_file",
        side_effect=upload_local_file,
    ):
        stored = _upload_provider_output(
            task,
            {"data": "YWJj", "format": "png"},
            "retry01-1.png",
            "IMAGE",
        )

    assert stored.public_url.endswith("/retry.png")
    assert len(upload_attempts) == 2
    assert not os.path.exists(upload_attempts[0][0])


def test_provider_base64_output_uses_and_cleans_local_temp_file():
    app = create_app()
    observed = {}

    def upload_local_file(path, **kwargs):
        observed["path"] = path
        observed["bytes"] = open(path, "rb").read()
        observed["kwargs"] = kwargs
        return StoredFile(
            storage_path="/group1/images/generated/temp.png",
            public_url=(
                "https://ray.example/gofastdfs/"
                "group1/images/generated/temp.png"
            ),
            original_filename=kwargs["filename"],
            content_type="image/png",
            file_size=len(observed["bytes"]),
        )

    task = SimpleNamespace(
        task_code="temp01",
        user_id=1,
        dept_id=1,
    )
    with app.app_context(), patch.object(
        FileService,
        "upload_local_file",
        side_effect=upload_local_file,
    ):
        stored = _upload_provider_output(
            task,
            {
                "data": base64.b64encode(b"generated image").decode("ascii"),
                "format": "png",
            },
            "temp01-1.png",
            "IMAGE",
        )

    assert stored.public_url.endswith("/temp.png")
    assert observed["bytes"] == b"generated image"
    assert observed["kwargs"]["content_type"] == "image/png"
    assert not os.path.exists(observed["path"])


def test_gofastdfs_update_keeps_business_name_and_reads_new_file():
    session = ReplacementSession(content=b"updated content")
    client = _replacement_client(session)

    updated = client.update_text(
        _old_file_info(),
        "updated content",
    )

    assert updated.file_id
    assert updated.file_id != "business-file-123"
    assert updated.original_filename == "test123.md"
    assert updated.storage_path == "/group1/files/revision-1.md"
    assert updated.public_url.endswith("/revision-1.md")
    assert session.delete_paths == ["group1/files/old-md5-name.md"]
    assert "name=test123.md" in session.get_urls[0]
    assert client.read_text(updated) == "updated content"


def test_gofastdfs_update_upload_failure_keeps_old_file():
    session = ReplacementSession(
        upload_error=requests.ConnectionError("upload unavailable"),
    )
    client = _replacement_client(session)

    try:
        client.update_text(_old_file_info(), "updated content")
    except StorageError as exc:
        assert "upload request failed" in str(exc)
    else:
        raise AssertionError("upload failure must raise StorageError")

    assert session.delete_paths == []


def test_gofastdfs_update_old_file_read_failure_keeps_storage_untouched():
    session = ReplacementSession(verify_status=404)
    client = _replacement_client(session)

    try:
        client.update_text(_old_file_info(), "updated content")
    except StorageError as exc:
        assert "download request failed" in str(exc)
    else:
        raise AssertionError("old file read failure must raise StorageError")

    assert session.upload_count == 0
    assert session.delete_paths == []


def test_gofastdfs_update_verification_failure_does_not_delete_old_file():
    session = ReplacementSession(
        content=b"updated content",
        verify_statuses=[200, 404],
    )
    client = _replacement_client(session)

    try:
        client.update_text(_old_file_info(), "updated content")
    except StorageError as exc:
        assert "failed verification" in str(exc)
    else:
        raise AssertionError("verification failure must raise StorageError")

    assert session.delete_paths == ["group1/files/revision-1.md"]


def test_gofastdfs_update_survives_old_file_cleanup_failure():
    session = ReplacementSession(
        content=b"updated content",
        delete_failure=True,
    )
    client = _replacement_client(session)

    updated = client.update_text(_old_file_info(), "updated content")

    assert updated.file_id
    assert updated.file_id != "business-file-123"
    assert updated.original_filename == "test123.md"
    assert updated.warning
    assert session.delete_paths == ["group1/files/old-md5-name.md"]


def test_data_uri_and_multi_output_are_normalized_without_network():
    stored = StoredFile(
        storage_path="/group1/images/generated/mock.png",
        public_url="https://ray.example/gofastdfs/group1/images/generated/mock.png",
        original_filename="mock.png",
        content_type="image/png",
        file_size=3,
    )
    fake_client = MagicMock()
    fake_client.upload_stream.return_value = stored

    with patch.object(FileService, "client", return_value=fake_client):
        result = FileService.upload_data_uri(
            "data:image/png;base64,YWJj",
            "mock.png",
            asset_type="IMAGE",
            record=False,
        )

    assert result.public_url.endswith("mock.png")
    fake_client.upload_stream.assert_called_once()
    outputs = _extract_outputs(
        {
            "result": {
                "data": [
                    {"url": "https://cdn.example/one.png"},
                    {"b64_json": "YWJj", "format": "png"},
                ]
            }
        }
    )
    assert len(outputs) == 2


def test_remote_output_is_downloaded_before_go_fastdfs_upload():
    stored = StoredFile(
        storage_path="/group1/images/generated/remote.png",
        public_url="https://ray.example/gofastdfs/group1/images/generated/remote.png",
        original_filename="remote.png",
        content_type="image/png",
        file_size=3,
    )

    class FakeDownloadResponse:
        status_code = 200
        headers = {"Content-Type": "image/png", "Content-Length": "3"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024 * 1024):
            assert chunk_size == 1024 * 1024
            return iter((b"abc",))

        def close(self):
            return None

    fake_client = MagicMock()
    fake_client.is_managed_url.return_value = False
    fake_client.timeout = 120
    fake_client.maximum_size = 1024

    def upload_stream(stream, *_args, **_kwargs):
        assert stream.read() == b"abc"
        return stored

    fake_client.upload_stream.side_effect = upload_stream
    with patch.object(FileService, "client", return_value=fake_client), patch.object(
        fake_client.session,
        "get",
        return_value=FakeDownloadResponse(),
    ):
        result = FileService.upload_from_url(
            "https://files.example/temporary.png",
            filename="remote.png",
            asset_type="IMAGE",
            record=False,
        )

    assert result.public_url.endswith("/remote.png")


def test_failed_delete_is_kept_for_retry():
    asset = MagicMock(status="ACTIVE", storage_path="/group1/mock.png")
    with patch.object(
        FileService,
        "delete_storage",
        side_effect=RuntimeError("fileserver unavailable"),
    ):
        assert FileService.delete_asset(asset) is False
    assert asset.status == "DELETE_FAILED"
    assert asset.error_message


def test_stale_task_output_url_is_cleared():
    task = MagicMock(id=10, output_url="https://ray.example/old.png")
    task_query = MagicMock()
    task_query.filter.return_value.all.return_value = [task]
    asset_query = MagicMock()
    asset_query.filter_by.return_value.first.return_value = None

    task_model = MagicMock(id=MagicMock())
    task_model.query = task_query
    asset_model = MagicMock()
    asset_model.query = asset_query
    with patch("applications.studio.retention.StudioGenerationTask", task_model), patch(
        "applications.studio.retention.StudioAsset", asset_model
    ), patch(
        "applications.studio.retention.generation_task_assets",
        return_value=[],
    ):
        assert clear_stale_task_outputs([10]) == 1
    assert task.output_url is None


def test_toapis_balance_fields_are_normalized():
    summary = normalize_balance(
        {
            "success": True,
            "remain_balance": 10.5,
            "used_balance": 2.3,
            "remain_credits": 2100,
            "used_credits": 460,
            "credits_per_usd": 200,
            "unlimited_quota": False,
        }
    )
    assert summary["available"] is True
    assert summary["remain_balance"] == 10.5
    assert summary["remain_credits"] == 2100


def main():
    test_gofastdfs_upload_response_normalization()
    test_gofastdfs_download_url_restores_original_filename()
    test_gofastdfs_http_200_failure_is_rejected()
    test_gofastdfs_update_keeps_business_name_and_reads_new_file()
    test_gofastdfs_update_upload_failure_keeps_old_file()
    test_gofastdfs_update_old_file_read_failure_keeps_storage_untouched()
    test_gofastdfs_update_verification_failure_does_not_delete_old_file()
    test_gofastdfs_update_survives_old_file_cleanup_failure()
    test_data_uri_and_multi_output_are_normalized_without_network()
    test_remote_output_is_downloaded_before_go_fastdfs_upload()
    test_failed_delete_is_kept_for_retry()
    test_stale_task_output_url_is_cleared()
    test_toapis_balance_fields_are_normalized()
    print("storage unit tests passed")


if __name__ == "__main__":
    main()
