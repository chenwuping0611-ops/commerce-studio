"""Offline storage and retention checks; no MySQL or go-fastdfs is contacted."""

from io import BytesIO
from unittest.mock import MagicMock, patch

from applications.common.storage import (
    FileService,
    GoFastDFSClient,
    StorageError,
    StoredFile,
)
from applications.studio.generation_service import _extract_outputs
from applications.studio.provider_client import normalize_balance
from applications.studio.retention import clear_stale_task_outputs


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


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
    assert session.last_files["file"][0] != "demo.png"
    assert len(session.last_files["file"][0].split(".")[0]) == 32
    assert stored.original_filename == "demo.png"


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
    with patch.object(FileService, "client", return_value=fake_client), patch(
        "applications.common.storage.file_service.requests.get",
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
    test_gofastdfs_http_200_failure_is_rejected()
    test_data_uri_and_multi_output_are_normalized_without_network()
    test_remote_output_is_downloaded_before_go_fastdfs_upload()
    test_failed_delete_is_kept_for_retry()
    test_stale_task_output_url_is_cleared()
    test_toapis_balance_fields_are_normalized()
    print("storage unit tests passed")


if __name__ == "__main__":
    main()
