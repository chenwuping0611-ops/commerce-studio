import base64
import binascii
import io
import mimetypes
import os
import tempfile
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from flask import current_app, has_app_context
from werkzeug.utils import secure_filename

from applications.extensions import db
from applications.models import StudioAsset

from .gofastdfs_client import GoFastDFSClient, StorageError, StoredFile


class FileService:
    """Application-level storage facade used by every media workflow."""

    PERMANENT = "PERMANENT"
    TTL_7D = "TTL_7D"

    @classmethod
    def client(cls):
        config = current_app.config if has_app_context() else {}
        return GoFastDFSClient(config)

    @classmethod
    def retention_expiry(cls, retention_policy):
        if retention_policy == cls.TTL_7D:
            days = int(
                (current_app.config.get("STUDIO_ASSET_TTL_DAYS") if has_app_context() else None)
                or os.getenv("STUDIO_ASSET_TTL_DAYS")
                or 7
            )
            return datetime.now() + timedelta(days=days)
        return None

    @staticmethod
    def infer_asset_type(filename="", content_type=""):
        content_type = str(content_type or "").lower()
        if content_type.startswith("image/"):
            return "IMAGE"
        if content_type.startswith("video/"):
            return "VIDEO"
        extension = os.path.splitext(str(filename or ""))[1].lower()
        if extension in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif"}:
            return "IMAGE"
        if extension in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
            return "VIDEO"
        return "FILE"

    @staticmethod
    def safe_filename(filename, fallback="upload.bin"):
        filename = secure_filename(str(filename or ""))
        return filename or fallback

    @classmethod
    def upload_file(
        cls,
        file_storage,
        asset_type=None,
        purpose="FILE",
        retention_policy=PERMANENT,
        created_by=None,
        category=None,
        record=True,
    ):
        original_filename = str(
            getattr(file_storage, "filename", "") or "upload.bin"
        )
        filename = cls.safe_filename(original_filename)
        content_type = getattr(file_storage, "mimetype", None) or getattr(
            file_storage, "content_type", None
        )
        asset_type = asset_type or cls.infer_asset_type(filename, content_type)
        category = category or cls.default_category(asset_type, purpose)
        stored = cls.client().upload_stream(
            getattr(file_storage, "stream", file_storage),
            filename,
            content_type=content_type,
            category=category,
            file_size=getattr(file_storage, "content_length", None),
            original_filename=original_filename,
        )
        if not record:
            return stored
        return cls.create_asset_record(
            stored,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention_policy,
            created_by=created_by,
        )

    @classmethod
    def upload_bytes(
        cls,
        data,
        filename,
        content_type=None,
        asset_type=None,
        purpose="FILE",
        retention_policy=PERMANENT,
        created_by=None,
        category=None,
        record=True,
    ):
        data = bytes(data or b"")
        original_filename = str(filename or "upload.bin")
        filename = cls.safe_filename(original_filename)
        content_type = content_type or mimetypes.guess_type(original_filename)[0]
        content_type = content_type or mimetypes.guess_type(filename)[0]
        asset_type = asset_type or cls.infer_asset_type(filename, content_type)
        category = category or cls.default_category(asset_type, purpose)
        stored = cls.client().upload_stream(
            io.BytesIO(data),
            filename,
            content_type=content_type,
            category=category,
            file_size=len(data),
            original_filename=original_filename,
        )
        if not record:
            return stored
        return cls.create_asset_record(
            stored,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention_policy,
            created_by=created_by,
        )

    @classmethod
    def upload_data_uri(
        cls,
        value,
        filename,
        asset_type,
        purpose="GENERATION_OUTPUT",
        retention_policy=TTL_7D,
        created_by=None,
        record=True,
    ):
        value = str(value or "")
        if "," not in value or not value.startswith("data:"):
            raise StorageError("invalid data URI")
        header, encoded = value.split(",", 1)
        content_type = header[5:].split(";", 1)[0] or "application/octet-stream"
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise StorageError("invalid base64 data URI") from exc
        return cls.upload_bytes(
            data,
            filename,
            content_type=content_type,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention_policy,
            created_by=created_by,
            record=record,
        )

    @classmethod
    def upload_from_url(
        cls,
        url,
        filename=None,
        asset_type=None,
        purpose="GENERATION_OUTPUT",
        retention_policy=TTL_7D,
        created_by=None,
        record=True,
    ):
        url = str(url or "").strip()
        if not url:
            raise StorageError("source URL is empty")
        if cls.client().is_managed_url(url):
            path = cls.client()._normalise_storage_path(url)
            stored = StoredFile(
                storage_path=path,
                public_url=cls.client().public_url_for(path),
                original_filename=filename or os.path.basename(urlparse(url).path),
                content_type=mimetypes.guess_type(urlparse(url).path)[0]
                or "application/octet-stream",
            )
            if not record:
                return stored
            return cls.create_asset_record(
                stored,
                asset_type=asset_type or cls.infer_asset_type(stored.original_filename, stored.content_type),
                purpose=purpose,
                retention_policy=retention_policy,
                created_by=created_by,
            )

        client = cls.client()
        client._require_internal_url()
        source_name = filename or os.path.basename(urlparse(url).path) or "remote.bin"
        content_type = ""
        response = None
        temp_path = None
        try:
            try:
                response = requests.get(
                    url,
                    stream=True,
                    timeout=(10, max(client.timeout, 30)),
                    headers={"User-Agent": "commerce-studio/0.1"},
                    verify=client.verify_ssl,
                )
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                content_type = content_type or mimetypes.guess_type(source_name)[0]
                content_length = response.headers.get("Content-Length")
                if content_length not in (None, ""):
                    try:
                        if int(content_length) > client.maximum_size:
                            raise StorageError("source URL file exceeds the configured upload size limit")
                    except ValueError:
                        pass
                if str(content_type or "").lower() in ("text/html", "application/json"):
                    raise StorageError("source URL did not return an image or video file")

                extension = os.path.splitext(source_name)[1]
                if not extension:
                    extension = mimetypes.guess_extension(content_type or "") or ""
                    source_name = source_name + extension

                # Download the short-lived provider URL first. This keeps the
                # provider URL lifetime independent from the go-fastdfs upload.
                with tempfile.NamedTemporaryFile(
                    prefix="commerce-studio-",
                    suffix=extension,
                    delete=False,
                ) as temporary_file:
                    temp_path = temporary_file.name
                    total_size = 0
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        total_size += len(chunk)
                        if total_size > client.maximum_size:
                            raise StorageError("source URL file exceeds the configured upload size limit")
                        temporary_file.write(chunk)
            except requests.RequestException as exc:
                raise StorageError(f"source URL download failed: {exc}") from exc

            with open(temp_path, "rb") as local_file:
                stored = client.upload_stream(
                    local_file,
                    cls.safe_filename(source_name),
                    content_type=content_type,
                    category=client_category(asset_type, purpose),
                    file_size=total_size,
                    original_filename=source_name,
                )
        finally:
            if response is not None:
                response.close()
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        if not record:
            return stored
        return cls.create_asset_record(
            stored,
            asset_type=asset_type or cls.infer_asset_type(source_name, content_type),
            purpose=purpose,
            retention_policy=retention_policy,
            created_by=created_by,
        )

    @classmethod
    def create_asset_record(
        cls,
        stored,
        asset_type,
        purpose,
        retention_policy=PERMANENT,
        created_by=None,
        **owners,
    ):
        if isinstance(stored, StudioAsset):
            return stored
        asset = StudioAsset(
            asset_type=str(asset_type or "FILE").upper(),
            purpose=str(purpose or "FILE").upper(),
            retention_policy=retention_policy,
            expires_at=cls.retention_expiry(retention_policy),
            storage_path=stored.storage_path,
            public_url=stored.public_url,
            original_filename=stored.original_filename,
            content_type=stored.content_type,
            file_size=stored.file_size,
            checksum=stored.checksum,
            created_by=created_by,
            status="ACTIVE",
        )
        for key in ("generation_task_id",):
            if key in owners:
                setattr(asset, key, owners[key])
        return asset

    @classmethod
    def delete_storage(cls, storage_path, checksum=None):
        return cls.client().delete(storage_path, checksum=checksum)

    @classmethod
    def delete_asset(cls, asset, status="DELETED"):
        if not asset or asset.status not in ("ACTIVE", "DELETE_FAILED"):
            return True
        try:
            cls.delete_storage(asset.storage_path, checksum=asset.checksum)
            asset.status = status
            asset.deleted_at = datetime.now()
            asset.error_message = None
            return True
        except Exception as exc:
            asset.status = "DELETE_FAILED"
            asset.error_message = str(exc)
            if has_app_context():
                current_app.logger.exception(
                    "failed to delete storage asset id=%s path=%s",
                    asset.id,
                    asset.storage_path,
                )
            return False

    @classmethod
    def mark_asset_deleted(cls, asset, error=None):
        """Mark an asset as deleted after an external cleanup has succeeded."""

        if not asset:
            return
        asset.status = "DELETED"
        asset.deleted_at = datetime.now()
        asset.error_message = error

    @staticmethod
    def default_category(asset_type, purpose):
        asset_type = str(asset_type or "FILE").upper()
        purpose = str(purpose or "FILE").upper()
        if purpose.startswith("PRODUCT"):
            return "images/products" if asset_type == "IMAGE" else "videos/products"
        if purpose == "SKILL":
            return "skills"
        if purpose == "GENERATION_OUTPUT":
            return "images/generated" if asset_type == "IMAGE" else "videos/generated"
        if purpose == "GENERATION_REFERENCE":
            return "images/references" if asset_type == "IMAGE" else "videos/references"
        return "files/uploads"


def client_category(asset_type, purpose):
    return FileService.default_category(asset_type, purpose)
