import json
import hashlib
import io
import logging
import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from werkzeug.utils import secure_filename


logger = logging.getLogger(__name__)


def _close_response(response):
    """Close real requests responses while tolerating lightweight test doubles."""

    close = getattr(response, "close", None)
    if callable(close):
        close()


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
    file_id: str | None = None
    warning: str | None = None

    @property
    def original_name(self):
        return self.original_filename

    def to_dict(self):
        return {
            "file_id": self.file_id,
            "original_name": self.original_filename,
            "original_filename": self.original_filename,
            "url": self.public_url,
            "public_url": self.public_url,
            "path": self.storage_path,
            "storage_path": self.storage_path,
            "md5": self.checksum,
            "checksum": self.checksum,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "warning": self.warning,
        }


class StreamLimit:
    """A small read wrapper that prevents oversized streaming uploads."""

    def __init__(self, stream, maximum):
        self.stream = stream
        self.maximum = maximum
        self.total = 0
        self.digest = hashlib.md5()

    def read(self, size=-1):
        chunk = self.stream.read(size)
        if chunk:
            self.total += len(chunk)
            self.digest.update(chunk)
            if self.total > self.maximum:
                raise StorageError("file exceeds the configured upload size limit")
        return chunk

    @property
    def checksum(self):
        return self.digest.hexdigest() if self.total else None

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
        pool_size = max(
            1,
            int(
                self.config.get("STUDIO_HTTP_POOL_SIZE")
                or os.getenv("STUDIO_HTTP_POOL_SIZE")
                or 10
            ),
        )
        retry_total = max(
            0,
            int(
                self.config.get("STUDIO_HTTP_MAX_RETRIES")
                or os.getenv("STUDIO_HTTP_MAX_RETRIES")
                or 2
            ),
        )
        retry = Retry(
            total=retry_total,
            connect=retry_total,
            read=retry_total,
            backoff_factor=0.5,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            # Upload and delete are POST operations. Retrying them can create
            # duplicate files or repeat destructive requests.
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            pool_block=True,
            max_retries=retry,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

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
    def _original_name(filename):
        """Keep the browser filename while removing any client-side path."""

        value = str(filename or "").strip().replace("\\", "/")
        value = value.rsplit("/", 1)[-1]
        return value[:255] or "upload.bin"

    @staticmethod
    def _value_from_mapping(value, keys):
        if isinstance(value, dict):
            for key in keys:
                item = value.get(key)
                if item not in (None, ""):
                    return item
        else:
            for key in keys:
                item = getattr(value, key, None)
                if item not in (None, ""):
                    return item
        return None

    @classmethod
    def _file_info(cls, value):
        """Normalize model, StoredFile, dict, URL, and legacy file records."""

        if isinstance(value, (str, bytes)):
            return {
                "public_url": value.decode() if isinstance(value, bytes) else value,
                "storage_path": value.decode() if isinstance(value, bytes) else value,
            }
        public_url = cls._value_from_mapping(
            value,
            ("public_url", "url", "href", "file_url"),
        )
        storage_path = cls._value_from_mapping(
            value,
            ("storage_path", "path", "file_path", "filePath"),
        )
        original_filename = cls._value_from_mapping(
            value,
            (
                "original_filename",
                "original_name",
                "filename",
                "file_name",
                "name",
            ),
        )
        file_id = cls._value_from_mapping(
            value,
            ("file_id", "fileId", "id"),
        )
        checksum = cls._value_from_mapping(
            value,
            ("checksum", "md5", "md5sum"),
        )
        content_type = cls._value_from_mapping(
            value,
            ("content_type", "mime", "mime_type"),
        )
        return {
            "public_url": str(public_url or "").strip(),
            "storage_path": str(storage_path or "").strip(),
            "original_filename": cls._original_name(original_filename)
            if original_filename
            else "",
            "file_id": str(file_id) if file_id not in (None, "") else None,
            "checksum": str(checksum) if checksum not in (None, "") else None,
            "content_type": str(content_type or "").strip(),
        }

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

    def download_url_for(self, value, filename=None):
        """Build a GoFastDFS download URL with the caller-visible filename."""

        info = self._file_info(value)
        original_filename = filename or info["original_filename"]
        raw_value = info["public_url"] or info["storage_path"]

        raw_url = str(raw_value or "").strip()
        if not raw_url:
            return ""
        url = (
            raw_url
            if raw_url.startswith(("http://", "https://"))
            else self.public_url_for(raw_url)
        )
        if not url:
            return ""

        parts = urlsplit(url)
        query = [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in {"download", "name"}
        ]
        query.append(("download", "1"))
        if original_filename:
            query.append(("name", self._original_name(original_filename)))
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query, doseq=True),
                parts.fragment,
            )
        )

    def download(self, value, filename=None):
        """Return a streamed response for one stored file."""

        return self.download_response(value, filename=filename)

    def download_response(self, value, filename=None):
        """Open a streamed GoFastDFS response using the shared client config."""

        url = self.download_url_for(value, filename=filename)
        if not url:
            raise StorageError("go-fastdfs download URL is empty")
        response = None
        try:
            response = self.session.get(
                url,
                stream=True,
                timeout=(10, max(self.timeout, 30)),
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if response is not None:
                _close_response(response)
            raise StorageError(f"go-fastdfs download request failed: {exc}") from exc

    def read_bytes(self, value, filename=None, maximum_size=None):
        """Read a stored file through GoFastDFS with a size limit."""

        maximum = (
            self.maximum_size
            if maximum_size is None
            else int(maximum_size)
        )
        response = self.download_response(value, filename=filename)
        try:
            content_length = response.headers.get("Content-Length")
            if maximum and content_length not in (None, ""):
                try:
                    if int(content_length) > maximum:
                        raise StorageError(
                            "downloaded file exceeds the configured size limit"
                        )
                except ValueError:
                    pass

            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if maximum and total > maximum:
                    raise StorageError(
                        "downloaded file exceeds the configured size limit"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            _close_response(response)

    def read_text(
        self,
        value,
        filename=None,
        encoding="utf-8-sig",
        errors="replace",
        maximum_size=None,
    ):
        """Read a stored text file using the shared download path."""

        return self.read_bytes(
            value,
            filename=filename,
            maximum_size=maximum_size,
        ).decode(encoding, errors=errors)

    def exists(self, value, filename=None):
        """Return whether the current GoFastDFS object can be downloaded."""

        response = None
        try:
            response = self.download_response(value, filename=filename)
            return True
        except StorageError:
            return False
        finally:
            if response is not None:
                _close_response(response)

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
        file_id=None,
    ):
        endpoint = self._endpoint(self.upload_endpoint)
        original_filename = self._original_name(original_filename or filename)
        safe_filename = self._safe_name(filename or original_filename)
        file_id = str(file_id or uuid.uuid4().hex)
        extension = os.path.splitext(original_filename)[1].lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
            extension = os.path.splitext(safe_filename)[1].lower()
        upload_filename = original_filename
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
        close_response = getattr(response, "close", None)
        if callable(close_response):
            close_response()
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
                self._find_value(payload, ("md5", "md5sum", "checksum"))
                or limited_stream.checksum
                or ""
            )
            or None,
            response_payload=payload,
            file_id=file_id,
        )

    def upload(self, *args, **kwargs):
        """Stable public upload name; upload_stream remains compatible."""

        return self.upload_stream(*args, **kwargs)

    def update(
        self,
        old_file,
        content=None,
        filename=None,
        content_type=None,
        category="files/updates",
        file_size=None,
        delete_old=True,
    ):
        """Upload and verify a new version before optionally deleting the old one."""

        if content is None:
            raise StorageError("new file content is empty")

        info = self._file_info(old_file)
        original_filename = (
            self._original_name(filename)
            if filename
            else info["original_filename"] or "upload.bin"
        )
        content_type = content_type or info["content_type"] or None

        # Confirm the previous version is still readable before creating a
        # replacement. This keeps an update from silently branching from a
        # missing or inaccessible business file.
        old_path = self._normalise_storage_path(
            info["storage_path"] or info["public_url"]
        )
        if old_path:
            self.read_bytes(old_file, filename=original_filename)

        if hasattr(content, "read"):
            stream = content
            upload_size = file_size
        else:
            if isinstance(content, str):
                content = content.encode("utf-8")
            try:
                content = bytes(content)
            except (TypeError, ValueError) as exc:
                raise StorageError("new file content is invalid") from exc
            stream = io.BytesIO(content)
            upload_size = len(content) if file_size is None else file_size

        # Some GoFastDFS deployments keep the old object when a replacement
        # reuses either the filename or the old file_id. Upload a new object
        # with both values changed, while restoring the original business
        # filename on the returned metadata used by the application and UI.
        upload_filename = original_filename
        if old_path:
            stem, extension = os.path.splitext(original_filename)
            upload_filename = (
                f"{stem or 'replacement'}-"
                f"{uuid.uuid4().hex[:12]}{extension}"
            )
        stored = self.upload_stream(
            stream,
            upload_filename,
            content_type=content_type,
            category=category,
            file_size=upload_size,
            original_filename=upload_filename,
        )
        stored.original_filename = original_filename[:255]
        if old_path and stored.storage_path == old_path:
            # Some GoFastDFS deployments deduplicate identical content or
            # update an object in place and therefore return the old path.
            # Verify the response below and keep the same database identity.
            logger.info(
                "GoFastDFS replacement reused storage path path=%s "
                "old_checksum=%s new_checksum=%s",
                old_path,
                info["checksum"],
                stored.checksum,
            )
        if not self.exists(stored, filename=stored.original_filename):
            try:
                self.delete(stored.storage_path, checksum=stored.checksum)
            except Exception:
                logger.exception(
                    "failed to remove unverified replacement path=%s",
                    stored.storage_path,
                )
            raise StorageError("new GoFastDFS file failed verification")

        if delete_old and old_path and old_path != stored.storage_path:
            try:
                self.delete(old_path, checksum=info["checksum"])
            except Exception as exc:
                stored.warning = (
                    "new file is active, but old GoFastDFS file cleanup failed: "
                    + str(exc)
                )
                logger.warning(
                    "old GoFastDFS file cleanup failed old_path=%s new_path=%s error=%s",
                    old_path,
                    stored.storage_path,
                    str(exc),
                )
        return stored

    def update_text(
        self,
        old_file,
        text,
        filename=None,
        encoding="utf-8",
        content_type=None,
        category="files/updates",
        delete_old=True,
    ):
        """Replace a text file while preserving its business identity and name."""

        if text is None:
            raise StorageError("new text content is empty")
        return self.update(
            old_file,
            content=str(text).encode(encoding),
            filename=filename,
            content_type=content_type or "text/plain; charset=utf-8",
            category=category,
            delete_old=delete_old,
        )

    def update_bytes(
        self,
        old_file,
        data,
        filename=None,
        content_type=None,
        category="files/updates",
        delete_old=True,
    ):
        """Replace a binary file while preserving its business identity and name."""

        return self.update(
            old_file,
            content=data,
            filename=filename,
            content_type=content_type,
            category=category,
            delete_old=delete_old,
        )

    def delete(self, storage_path, checksum=None):
        info = self._file_info(storage_path)
        path = self._normalise_storage_path(
            info["storage_path"] or info["public_url"]
        )
        checksum = checksum or info["checksum"]
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
        _close_response(response)
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
