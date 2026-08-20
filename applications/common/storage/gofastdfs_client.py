import json
import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from werkzeug.utils import secure_filename


class StorageError(RuntimeError):
    """Raised when a file cannot be uploaded or deleted."""


@dataclass
class StoredFile:
    storage_path: str
    public_url: str
    original_filename: str
    content_type: str
    file_size: int | None = None
    checksum: str | None = None
    response_payload: object | None = None


class StreamLimit:
    """A small read wrapper that prevents oversized streaming uploads."""

    def __init__(self, stream, maximum):
        self.stream = stream
        self.maximum = maximum
        self.total = 0

    def read(self, size=-1):
        chunk = self.stream.read(size)
        if chunk:
            self.total += len(chunk)
            if self.total > self.maximum:
                raise StorageError("file exceeds the configured upload size limit")
        return chunk

    def __getattr__(self, name):
        return getattr(self.stream, name)


class GoFastDFSClient:
    """HTTP client for the local go-fastdfs fileserver."""

    def __init__(self, config=None):
        self.config = config or {}
        self.internal_url = str(
            self.config.get("GOFASTDFS_INTERNAL_URL")
            or os.getenv("GOFASTDFS_INTERNAL_URL")
            or ""
        ).rstrip("/")
        self.public_url = str(
            self.config.get("GOFASTDFS_PUBLIC_URL")
            or os.getenv("GOFASTDFS_PUBLIC_URL")
            or ""
        ).rstrip("/")
        self.group = str(
            self.config.get("GOFASTDFS_GROUP")
            or os.getenv("GOFASTDFS_GROUP")
            or "group1"
        ).strip("/")
        self.timeout = int(
            self.config.get("GOFASTDFS_TIMEOUT")
            or os.getenv("GOFASTDFS_TIMEOUT")
            or 120
        )
        self.maximum_size = int(
            self.config.get("GOFASTDFS_MAX_FILE_SIZE")
            or os.getenv("GOFASTDFS_MAX_FILE_SIZE")
            or 536870912
        )
        self.verify_ssl = self._as_bool(
            self.config.get("GOFASTDFS_VERIFY_SSL")
            if "GOFASTDFS_VERIFY_SSL" in self.config
            else os.getenv("GOFASTDFS_VERIFY_SSL", "true")
        )
        self.upload_endpoint = str(
            self.config.get("GOFASTDFS_UPLOAD_ENDPOINT")
            or os.getenv("GOFASTDFS_UPLOAD_ENDPOINT")
            or "/{group}/upload"
        )
        self.delete_endpoint = str(
            self.config.get("GOFASTDFS_DELETE_ENDPOINT")
            or os.getenv("GOFASTDFS_DELETE_ENDPOINT")
            or "/{group}/delete"
        )
        self.session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.5,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST", "DELETE"}),
            raise_on_status=False,
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    @staticmethod
    def _as_bool(value):
        return str(value).strip().lower() not in ("0", "false", "off", "no")

    def _require_internal_url(self):
        if not self.internal_url:
            raise StorageError(
                "GOFASTDFS_INTERNAL_URL is not configured; "
                "set it to the actual local fileserver address"
            )

    def _endpoint(self, template):
        self._require_internal_url()
        path = template.format(group=self.group)
        if not path.startswith("/"):
            path = "/" + path
        return self.internal_url + path

    @staticmethod
    def _safe_name(filename):
        filename = secure_filename(str(filename or ""))
        if filename:
            return filename
        return "upload.bin"

    @staticmethod
    def _find_value(payload, keys):
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if value not in (None, ""):
                    return value
            for value in payload.values():
                found = GoFastDFSClient._find_value(value, keys)
                if found not in (None, ""):
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = GoFastDFSClient._find_value(value, keys)
                if found not in (None, ""):
                    return found
        return None

    @staticmethod
    def _payload(response):
        try:
            return response.json()
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"raw": response.text[:4000]}

    @classmethod
    def _payload_is_successful(cls, payload):
        """Treat an HTTP 200 response as successful only when go-fastdfs agrees."""

        status = cls._find_value(payload, ("status",))
        if status not in (None, "") and str(status).strip().lower() not in (
            "ok",
            "success",
            "succeeded",
        ):
            return False
        retcode = cls._find_value(payload, ("retcode", "ret_code", "code"))
        if retcode not in (None, "") and str(retcode).strip() not in ("0", "200"):
            return False
        return True

    def _normalise_storage_path(self, value):
        value = str(value or "").strip()
        if not value:
            return ""
        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            value = parsed.path
            if self.public_url:
                public_path = urlparse(self.public_url).path.rstrip("/")
                if public_path and value.startswith(public_path + "/"):
                    value = value[len(public_path) + 1 :]
        return "/" + value.lstrip("/")

    def public_url_for(self, storage_path):
        storage_path = str(storage_path or "").strip()
        if not storage_path:
            return ""
        if storage_path.startswith("http://") or storage_path.startswith("https://"):
            return storage_path
        if not self.public_url:
            raise StorageError("GOFASTDFS_PUBLIC_URL is not configured")
        return self.public_url + "/" + storage_path.lstrip("/")

    def is_managed_url(self, value):
        value = str(value or "").strip()
        return bool(self.public_url and value.startswith(self.public_url + "/"))

    def upload_stream(
        self,
        stream,
        filename,
        content_type=None,
        category="files/uploads",
        file_size=None,
        original_filename=None,
    ):
        endpoint = self._endpoint(self.upload_endpoint)
        original_filename = str(original_filename or filename or "upload.bin")
        safe_filename = self._safe_name(filename)
        extension = os.path.splitext(original_filename)[1].lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
            extension = os.path.splitext(safe_filename)[1].lower()
        upload_filename = f"{uuid.uuid4().hex}{extension}"
        content_type = content_type or mimetypes.guess_type(original_filename)[0]
        content_type = content_type or mimetypes.guess_type(safe_filename)[0]
        content_type = content_type or "application/octet-stream"
        normalized_size = None
        if file_size not in (None, ""):
            try:
                normalized_size = int(file_size)
            except (TypeError, ValueError):
                normalized_size = None
        if normalized_size is not None and normalized_size > self.maximum_size:
            raise StorageError("file exceeds the configured upload size limit")

        limited_stream = StreamLimit(stream, self.maximum_size)
        data = {
            "path": str(category or "").strip("/"),
            "scene": "default",
            "filename": upload_filename,
            "output": "json2",
        }
        try:
            response = self.session.post(
                endpoint,
                files={"file": (upload_filename, limited_stream, content_type)},
                data=data,
                timeout=(10, max(self.timeout, 30)),
                verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            raise StorageError(f"go-fastdfs upload request failed: {exc}") from exc

        payload = self._payload(response)
        if not 200 <= response.status_code < 300:
            raise StorageError(
                f"go-fastdfs upload failed: HTTP {response.status_code} "
                f"{self._find_value(payload, ('message', 'msg', 'error')) or payload}"
            )
        if not self._payload_is_successful(payload):
            raise StorageError(
                "go-fastdfs upload failed: "
                f"{self._find_value(payload, ('message', 'msg', 'error', 'retmsg')) or payload}"
            )

        path = self._find_value(
            payload,
            ("path", "file_path", "filePath", "url", "src", "fileUrl"),
        )
        if not path and isinstance(payload, dict):
            raw = str(payload.get("raw") or "").strip()
            if raw.startswith(("http://", "https://", "/")):
                path = raw.split("?", 1)[0].splitlines()[0].strip()
        if not path:
            raise StorageError(
                "go-fastdfs upload response did not contain a storage path"
            )
        storage_path = self._normalise_storage_path(path)
        size = self._find_value(payload, ("size", "file_size", "fileSize"))
        try:
            size = int(size) if size is not None else None
        except (TypeError, ValueError):
            size = None
        return StoredFile(
            storage_path=storage_path,
            public_url=self.public_url_for(storage_path),
            original_filename=original_filename[:255],
            content_type=content_type,
            file_size=size or normalized_size or limited_stream.total,
            checksum=str(
                self._find_value(payload, ("md5", "md5sum", "checksum")) or ""
            )
            or None,
            response_payload=payload,
        )

    def delete(self, storage_path, checksum=None):
        path = self._normalise_storage_path(storage_path)
        if not path:
            return True
        endpoint = self._endpoint(self.delete_endpoint)
        data = {"path": path.lstrip("/")}
        if checksum:
            data["md5"] = checksum
        try:
            response = self.session.post(
                endpoint,
                data=data,
                timeout=(10, max(self.timeout, 30)),
                verify=self.verify_ssl,
            )
        except requests.RequestException as exc:
            raise StorageError(f"go-fastdfs delete request failed: {exc}") from exc
        payload = self._payload(response)
        if not 200 <= response.status_code < 300:
            raise StorageError(
                f"go-fastdfs delete failed: HTTP {response.status_code} "
                f"{self._find_value(payload, ('message', 'msg', 'error')) or payload}"
            )
        if not self._payload_is_successful(payload):
            raise StorageError(
                "go-fastdfs delete failed: "
                f"{self._find_value(payload, ('message', 'msg', 'error', 'retmsg')) or payload}"
            )
        return True
