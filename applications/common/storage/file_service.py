import base64
import binascii
import io
import logging
import mimetypes
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from flask import current_app, has_app_context
from werkzeug.utils import secure_filename

from applications.extensions import db
from applications.models import StudioAsset

from .gofastdfs_client import GoFastDFSClient, StorageError, StoredFile


logger = logging.getLogger(__name__)


@dataclass
class PendingAssetUpdate:
    """A staged replacement waiting for the business row to commit."""

    asset: StudioAsset
    new_file: StoredFile
    old_storage_path: str
    old_checksum: str | None
    old_public_url: str
    old_original_filename: str | None
    old_content_type: str | None
    old_file_size: int | None


class FileService:
    """Application-level storage facade used by every media workflow."""

    PERMANENT = "PERMANENT"
    TEMPORARY = "TEMPORARY"
    # Kept for old callers and legacy rows. New code should use TEMPORARY.
    TTL_7D = "TTL_7D"
    _client_local = threading.local()

    @classmethod
    def client(cls):
        config = current_app.config if has_app_context() else {}
        key = (
            config.get("GOFASTDFS_INTERNAL_URL", ""),
            config.get("GOFASTDFS_PUBLIC_URL", ""),
            config.get("GOFASTDFS_GROUP", "group1"),
            config.get("GOFASTDFS_TIMEOUT", 120),
            config.get("GOFASTDFS_MAX_FILE_SIZE", 536870912),
            config.get("GOFASTDFS_VERIFY_SSL", "true"),
            config.get("GOFASTDFS_UPLOAD_ENDPOINT", "/{group}/upload"),
            config.get("GOFASTDFS_DELETE_ENDPOINT", "/{group}/delete"),
        )
        cached_key = getattr(cls._client_local, "key", None)
        client = getattr(cls._client_local, "client", None)
        if client is None or cached_key != key:
            client = GoFastDFSClient(config)
            cls._client_local.key = key
            cls._client_local.client = client
        return client

    @classmethod
    def file_info(cls, value, filename=None):
        """Return a compatibility-friendly business file record."""

        info = cls.client()._file_info(value)
        if isinstance(value, StudioAsset):
            info["file_id"] = str(value.id)
            info["public_url"] = value.public_url or info["public_url"]
            info["storage_path"] = value.storage_path or info["storage_path"]
            info["original_filename"] = (
                value.original_filename
                or filename
                or info["original_filename"]
            )
            info["checksum"] = value.checksum or info["checksum"]
            info["content_type"] = value.content_type or info["content_type"]
        elif isinstance(value, StoredFile):
            info["file_id"] = value.file_id or info["file_id"]
        if filename and not info["original_filename"]:
            info["original_filename"] = filename
        return {
            "file_id": info["file_id"],
            "original_name": info["original_filename"] or "",
            "original_filename": info["original_filename"] or "",
            "url": info["public_url"] or "",
            "public_url": info["public_url"] or "",
            "path": info["storage_path"] or "",
            "storage_path": info["storage_path"] or "",
            "md5": info["checksum"],
            "checksum": info["checksum"],
            "content_type": info["content_type"] or "",
        }

    @classmethod
    def upload(cls, *args, **kwargs):
        """Stable facade name for new uploads."""

        return cls.upload_file(*args, **kwargs)

    @classmethod
    def download(cls, value, filename=None):
        """Return a streamed download response through GoFastDFS."""

        return cls.download_response(value, filename=filename)

    @classmethod
    def download_url(cls, value, filename=None):
        """Return a browser download URL using the asset's original filename."""

        original_filename = filename
        if isinstance(value, StudioAsset):
            original_filename = original_filename or value.original_filename
            value = value.public_url or value.storage_path
        elif isinstance(value, StoredFile):
            original_filename = original_filename or value.original_filename
            value = value.public_url or value.storage_path
        return cls.client().download_url_for(value, original_filename)

    @classmethod
    def download_response(cls, value, filename=None):
        """Open a streamed download through the shared GoFastDFS client."""

        original_filename = filename
        if isinstance(value, StudioAsset):
            original_filename = original_filename or value.original_filename
            value = value.public_url or value.storage_path
        elif isinstance(value, StoredFile):
            original_filename = original_filename or value.original_filename
            value = value.public_url or value.storage_path
        return cls.client().download_response(value, original_filename)

    @classmethod
    def read_bytes(cls, value, filename=None, maximum_size=None):
        """Read binary content through the shared GoFastDFS client."""

        return cls.client().read_bytes(
            value,
            filename=filename,
            maximum_size=maximum_size,
        )

    @classmethod
    def read_text(
        cls,
        value,
        filename=None,
        encoding="utf-8-sig",
        errors="replace",
        maximum_size=None,
    ):
        """Read text content through the shared GoFastDFS client."""

        return cls.client().read_text(
            value,
            filename=filename,
            encoding=encoding,
            errors=errors,
            maximum_size=maximum_size,
        )

    @classmethod
    def exists(cls, value, filename=None):
        """Check a GoFastDFS file without exposing storage names to callers."""

        return cls.client().exists(value, filename=filename)

    @classmethod
    def is_managed_url(cls, value):
        """Return whether a URL belongs to the configured GoFastDFS service."""

        return cls.client().is_managed_url(value)

    @classmethod
    def _record_failed_cleanup(
        cls,
        source_asset,
        storage_path,
        public_url=None,
        original_filename=None,
        content_type=None,
        file_size=None,
        checksum=None,
        error_message="GoFastDFS 文件清理失败",
    ):
        """Keep an unreferenced storage object available for later retry."""

        storage_path = str(storage_path or "").strip()
        if not storage_path or not has_app_context():
            return False
        try:
            cleanup_asset = StudioAsset.query.filter_by(
                storage_path=storage_path,
                status="DELETE_FAILED",
            ).first()
            if cleanup_asset:
                cleanup_asset.error_message = error_message
                db.session.commit()
                return True

            public_url = str(public_url or "").strip()
            if not public_url:
                try:
                    public_url = cls.client().public_url_for(storage_path)
                except StorageError:
                    public_url = storage_path
            cleanup_asset = StudioAsset(
                dept_id=getattr(source_asset, "dept_id", None),
                asset_type=getattr(source_asset, "asset_type", None) or "FILE",
                purpose="CLEANUP_PENDING",
                # This row represents an obsolete storage object rather than
                # the current Product/Skill asset. It must be retryable even
                # when the source asset itself is permanent.
                retention_policy=cls.TEMPORARY,
                storage_path=storage_path,
                public_url=public_url,
                original_filename=(
                    original_filename
                    or getattr(source_asset, "original_filename", None)
                    or "upload.bin"
                ),
                content_type=(
                    content_type
                    or getattr(source_asset, "content_type", None)
                    or "application/octet-stream"
                ),
                file_size=(
                    file_size
                    if file_size is not None
                    else getattr(source_asset, "file_size", None)
                ),
                checksum=checksum,
                expires_at=cls.retention_expiry(cls.TEMPORARY),
                generation_task_id=None,
                created_by=getattr(source_asset, "created_by", None),
                status="DELETE_FAILED",
                error_message=error_message,
            )
            db.session.add(cleanup_asset)
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            logger.exception(
                "failed to persist GoFastDFS cleanup record path=%s",
                storage_path,
            )
            return False

    @classmethod
    def retention_expiry(cls, retention_policy):
        if str(retention_policy or "").upper() in {
            cls.TEMPORARY,
            cls.TTL_7D,
        }:
            days = int(
                (
                    current_app.config.get("STUDIO_TEMPORARY_RETENTION_DAYS")
                    if has_app_context()
                    else None
                )
                or (
                    current_app.config.get("STUDIO_ASSET_TTL_DAYS")
                    if has_app_context()
                    else None
                )
                or os.getenv("STUDIO_ASSET_TTL_DAYS")
                or 30
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
        dept_id=None,
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
            dept_id=dept_id,
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
        dept_id=None,
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
            dept_id=dept_id,
        )

    @classmethod
    def upload_local_file(
        cls,
        path,
        filename=None,
        content_type=None,
        asset_type=None,
        purpose="FILE",
        retention_policy=PERMANENT,
        created_by=None,
        category=None,
        dept_id=None,
        record=True,
    ):
        """Upload an already staged local file without storing its bytes in SQL."""

        path = os.fspath(path)
        if not os.path.isfile(path):
            raise StorageError("temporary upload file does not exist")

        original_filename = str(
            filename or os.path.basename(path) or "upload.bin"
        )
        safe_name = cls.safe_filename(original_filename)
        content_type = (
            content_type
            or mimetypes.guess_type(original_filename)[0]
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )
        asset_type = asset_type or cls.infer_asset_type(
            safe_name,
            content_type,
        )
        category = category or cls.default_category(asset_type, purpose)
        try:
            file_size = os.path.getsize(path)
            with open(path, "rb") as local_file:
                stored = cls.client().upload_stream(
                    local_file,
                    safe_name,
                    content_type=content_type,
                    category=category,
                    file_size=file_size,
                    original_filename=original_filename,
                )
        except OSError as exc:
            raise StorageError("temporary upload file could not be read") from exc

        if not record:
            return stored
        return cls.create_asset_record(
            stored,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention_policy,
            created_by=created_by,
            dept_id=dept_id,
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
        dept_id=None,
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
            dept_id=dept_id,
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
        dept_id=None,
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
                dept_id=dept_id,
            )

        client = cls.client()
        client._require_internal_url()
        source_name = filename or os.path.basename(urlparse(url).path) or "remote.bin"
        content_type = ""
        response = None
        temp_path = None
        try:
            try:
                response = client.session.get(
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
            dept_id=dept_id,
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
        for key in ("generation_task_id", "dept_id"):
            if key in owners:
                setattr(asset, key, owners[key])
        return asset

    @staticmethod
    def _apply_stored_to_asset(asset, stored):
        asset.storage_path = stored.storage_path
        asset.public_url = stored.public_url
        asset.original_filename = stored.original_filename
        asset.content_type = stored.content_type
        asset.file_size = stored.file_size
        asset.checksum = stored.checksum
        asset.status = "ACTIVE"
        asset.error_message = None
        asset.deleted_at = None
        return asset

    @classmethod
    def stage_asset_update(
        cls,
        asset,
        content,
        filename=None,
        content_type=None,
        category=None,
    ):
        """Upload and verify a replacement without deleting the old version."""

        if not isinstance(asset, StudioAsset):
            raise StorageError("asset update requires a StudioAsset record")
        if asset.status not in ("ACTIVE", "DELETE_FAILED"):
            raise StorageError("asset is not available for update")

        old_storage_path = asset.storage_path
        old_checksum = asset.checksum
        old_public_url = asset.public_url
        old_original_filename = asset.original_filename
        old_content_type = asset.content_type
        old_file_size = asset.file_size
        original_filename = (
            filename
            or asset.original_filename
            or "upload.bin"
        )
        asset_type = asset.asset_type or "FILE"
        purpose = asset.purpose or "FILE"
        stored = cls.client().update(
            asset,
            content=content,
            filename=original_filename,
            content_type=content_type or asset.content_type,
            category=category or cls.default_category(asset_type, purpose),
            delete_old=False,
        )
        cls._apply_stored_to_asset(asset, stored)
        return PendingAssetUpdate(
            asset=asset,
            new_file=stored,
            old_storage_path=old_storage_path,
            old_checksum=old_checksum,
            old_public_url=old_public_url,
            old_original_filename=old_original_filename,
            old_content_type=old_content_type,
            old_file_size=old_file_size,
        )

    @classmethod
    def finalize_asset_update(cls, pending):
        """Delete the old version after the business reference is committed."""

        if not pending or not pending.old_storage_path:
            return True
        if pending.old_storage_path == pending.new_file.storage_path:
            return True
        try:
            cls.delete_storage(
                pending.old_storage_path,
                checksum=pending.old_checksum,
            )
            return True
        except Exception as exc:
            cleanup_error = (
                "旧 GoFastDFS 文件清理失败: "
                + str(exc)
            )
            logger.warning(
                "old GoFastDFS version cleanup failed old_path=%s new_path=%s error=%s",
                pending.old_storage_path,
                pending.new_file.storage_path,
                str(exc),
            )
            cls._record_failed_cleanup(
                source_asset=pending.asset,
                storage_path=pending.old_storage_path,
                public_url=pending.old_public_url,
                original_filename=pending.old_original_filename,
                content_type=pending.old_content_type,
                file_size=pending.old_file_size,
                checksum=pending.old_checksum,
                error_message=cleanup_error,
            )
            return False

    @classmethod
    def rollback_asset_update(cls, pending):
        """Remove an uploaded replacement when the database transaction fails."""

        if not pending:
            return True
        asset = pending.asset
        asset.storage_path = pending.old_storage_path
        asset.public_url = pending.old_public_url
        asset.original_filename = pending.old_original_filename
        asset.content_type = pending.old_content_type
        asset.file_size = pending.old_file_size
        asset.checksum = pending.old_checksum
        try:
            if (
                pending.new_file.storage_path
                and pending.new_file.storage_path != pending.old_storage_path
            ):
                cls.delete_storage(
                    pending.new_file.storage_path,
                    checksum=pending.new_file.checksum,
                )
            return True
        except Exception as exc:
            cleanup_error = (
                "替换文件回滚清理失败: "
                + str(exc)
            )
            logger.warning(
                "replacement rollback cleanup failed path=%s error=%s",
                pending.new_file.storage_path,
                str(exc),
            )
            cls._record_failed_cleanup(
                source_asset=asset,
                storage_path=pending.new_file.storage_path,
                public_url=pending.new_file.public_url,
                original_filename=pending.new_file.original_filename,
                content_type=pending.new_file.content_type,
                file_size=pending.new_file.file_size,
                checksum=pending.new_file.checksum,
                error_message=cleanup_error,
            )
            return False

    @classmethod
    def update_asset(
        cls,
        asset,
        content,
        filename=None,
        content_type=None,
        category=None,
        commit=True,
    ):
        """Replace a DB-backed asset with commit-before-old-delete semantics."""

        pending = cls.stage_asset_update(
            asset,
            content=content,
            filename=filename,
            content_type=content_type,
            category=category,
        )
        if not commit:
            return pending
        try:
            db.session.add(asset)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            cls.rollback_asset_update(pending)
            raise StorageError(
                "database update failed; the previous GoFastDFS file was kept"
            ) from exc
        cls.finalize_asset_update(pending)
        return asset

    @classmethod
    def update(cls, old_file, content=None, **kwargs):
        """Update either a StudioAsset or a standalone file record."""

        if isinstance(old_file, StudioAsset):
            return cls.update_asset(old_file, content=content, **kwargs)
        return cls.client().update(old_file, content=content, **kwargs)

    @classmethod
    def update_text(cls, old_file, text, encoding="utf-8", **kwargs):
        """Replace text content while keeping the business file identity."""

        content = str(text).encode(encoding)
        return cls.update(old_file, content=content, **kwargs)

    @classmethod
    def update_bytes(cls, old_file, data, **kwargs):
        """Replace binary content while keeping the business file identity."""

        return cls.update(old_file, content=data, **kwargs)

    @classmethod
    def delete_storage(cls, storage_path, checksum=None):
        return cls.client().delete(storage_path, checksum=checksum)

    @classmethod
    def delete_asset(cls, asset, status="DELETED"):
        if not asset or asset.status not in ("ACTIVE", "DELETE_FAILED"):
            return True
        try:
            cls.delete_storage(
                asset.storage_path or asset.public_url,
                checksum=asset.checksum,
            )
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
        if purpose == "BATCH_PROMPT":
            return "files/batch-prompts"
        return "files/uploads"


def client_category(asset_type, purpose):
    return FileService.default_category(asset_type, purpose)
