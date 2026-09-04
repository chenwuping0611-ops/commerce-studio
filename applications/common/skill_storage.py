"""Read Skill bodies from GoFastDFS while keeping legacy rows compatible.

Skill metadata belongs in MySQL, but the editable instruction document is a
stored file. New callers should use this module instead of reading
``StudioSkill.content`` or ``StudioSkill.prompt_template`` directly.
"""

import datetime

from applications.common.asset_relations import asset_referenced
from applications.common.scope import can_access_asset, can_access_skill
from applications.common.storage import FileService, StorageError
from applications.extensions import db
from applications.models import StudioAsset


DEFAULT_MAX_SKILL_BYTES = 512000


def _linked_skill_asset(skill):
    """Return the current Skill asset, including rows awaiting cleanup."""

    storage_asset_id = getattr(skill, "storage_asset_id", None)
    asset = getattr(skill, "storage_asset", None)
    if asset is None and storage_asset_id:
        asset = StudioAsset.query.filter_by(
            id=storage_asset_id,
            purpose="SKILL",
        ).first()
    if not asset or str(getattr(asset, "purpose", "") or "").upper() != "SKILL":
        return None
    return asset


def _cleanup_replaced_skill_asset(asset):
    """Delete an obsolete fallback asset after the Skill points elsewhere."""

    if not asset or not getattr(asset, "id", None):
        return
    if asset_referenced(asset.id):
        return
    deleted = FileService.delete_asset(asset)
    if deleted:
        db.session.delete(asset)
    # A failed delete leaves DELETE_FAILED on the row for the scheduler.
    db.session.commit()


def force_replace_skill_storage(
    skill,
    content,
    filename,
    *,
    content_type="text/markdown",
    created_by=None,
    dept_id=None,
):
    """Upload one built-in Skill again and switch its canonical asset.

    An active, readable asset keeps its database identity and uses the normal
    replacement protocol. If the old object cannot be read, a new asset is
    created, the Skill reference is switched, and the old object is deleted
    only after the database commit succeeds.
    """

    if not skill:
        raise StorageError("Skill 记录不存在")
    content_bytes = str(content or "").encode("utf-8")
    if not content_bytes:
        raise StorageError("Skill 内容不能为空")

    previous_asset = _linked_skill_asset(skill)
    pending_update = None
    stored = None
    replacement_asset = None
    obsolete_asset = None

    if previous_asset and str(
        getattr(previous_asset, "status", "") or ""
    ).upper() in ("ACTIVE", "DELETE_FAILED"):
        try:
            stored_content = FileService.read_text(
                previous_asset,
                filename=previous_asset.original_filename,
                maximum_size=DEFAULT_MAX_SKILL_BYTES,
            )
        except Exception:
            # A missing old object cannot be staged through the update API.
            # Upload a fresh object and clean the obsolete row afterwards.
            obsolete_asset = previous_asset
        else:
            # GoFastDFS may return the existing object path when the uploaded
            # content is identical. Treat that case as an idempotent sync and
            # avoid an unnecessary replacement request.
            if str(stored_content or "").strip() == str(content).strip():
                skill.prompt_template = None
                skill.content = None
                db.session.add(skill)
                db.session.commit()
                return previous_asset
            pending_update = FileService.stage_asset_update(
                previous_asset,
                content=content_bytes,
                filename=filename,
                content_type=content_type,
                category=FileService.default_category("FILE", "SKILL"),
            )

    try:
        if pending_update is None:
            stored = FileService.upload_bytes(
                content_bytes,
                filename,
                content_type=content_type,
                asset_type="FILE",
                purpose="SKILL",
                retention_policy=FileService.PERMANENT,
                created_by=(
                    created_by
                    if created_by is not None
                    else getattr(skill, "created_by", None)
                ),
                dept_id=(
                    dept_id
                    if dept_id is not None
                    else getattr(skill, "dept_id", None)
                ),
                record=False,
            )
            replacement_asset = FileService.create_asset_record(
                stored,
                asset_type="FILE",
                purpose="SKILL",
                retention_policy=FileService.PERMANENT,
                created_by=(
                    created_by
                    if created_by is not None
                    else getattr(skill, "created_by", None)
                ),
                dept_id=(
                    dept_id
                    if dept_id is not None
                    else getattr(skill, "dept_id", None)
                ),
            )
            db.session.add(replacement_asset)
            db.session.flush()
            skill.storage_asset_id = replacement_asset.id

        skill.prompt_template = None
        skill.content = None
        db.session.add(skill)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if pending_update:
            FileService.rollback_asset_update(pending_update)
        elif stored:
            try:
                FileService.delete_storage(
                    stored.storage_path,
                    checksum=stored.checksum,
                )
            except Exception:
                pass
        raise

    if pending_update:
        FileService.finalize_asset_update(pending_update)
    elif obsolete_asset and replacement_asset:
        _cleanup_replaced_skill_asset(obsolete_asset)

    return replacement_asset or previous_asset


def _builtin(skill, builtin_codes):
    return bool(
        builtin_codes
        and getattr(skill, "code", None) in set(builtin_codes)
    )


def skill_storage_asset(
    skill,
    *,
    user=None,
    builtin_codes=None,
    enforce_access=True,
):
    """Return the active GoFastDFS asset linked to one authorized Skill."""

    if not skill:
        return None
    if enforce_access and not can_access_skill(
        user,
        skill,
        builtin_codes=builtin_codes,
    ):
        raise StorageError("Skill 不存在、已停用或无权访问")

    storage_asset_id = getattr(skill, "storage_asset_id", None)
    asset = getattr(skill, "storage_asset", None)
    if asset is None and storage_asset_id:
        asset = StudioAsset.query.filter_by(
            id=storage_asset_id,
            purpose="SKILL",
        ).first()

    if not asset:
        if storage_asset_id:
            raise StorageError("Skill 关联的 GoFastDFS 文件不存在")
        return None
    if str(getattr(asset, "purpose", "") or "").upper() != "SKILL":
        raise StorageError("Skill 关联的文件用途无效")
    if str(getattr(asset, "status", "") or "").upper() != "ACTIVE":
        raise StorageError("Skill 关联的 GoFastDFS 文件已失效")
    expires_at = getattr(asset, "expires_at", None)
    if expires_at and expires_at <= datetime.datetime.now():
        raise StorageError("Skill 关联的 GoFastDFS 文件已过期")

    # Built-in Skills are system resources and may be stored under the root
    # department. Their Skill-level authorization already grants global use.
    if (
        enforce_access
        and not _builtin(skill, builtin_codes)
        and not can_access_asset(user, asset)
    ):
        raise StorageError("无权读取当前 Skill 文件")
    return asset


def read_skill_text(
    skill,
    *,
    user=None,
    builtin_codes=None,
    maximum_size=DEFAULT_MAX_SKILL_BYTES,
    allow_legacy=True,
):
    """Read the canonical Skill file, falling back only for old no-file rows."""

    asset = skill_storage_asset(
        skill,
        user=user,
        builtin_codes=builtin_codes,
        enforce_access=True,
    )
    if asset:
        try:
            return str(
                FileService.read_text(
                    asset,
                    filename=asset.original_filename,
                    maximum_size=maximum_size,
                )
                or ""
            ).strip()
        except Exception as exc:
            raise StorageError("Skill GoFastDFS 文件读取失败") from exc

    if not allow_legacy:
        return ""
    # Compatibility is intentionally limited to rows with no storage asset.
    # Once a file is linked, stale MySQL text must never override it.
    return str(
        getattr(skill, "content", None)
        or getattr(skill, "prompt_template", None)
        or ""
    ).strip()


def skill_file_url(
    skill,
    *,
    user=None,
    builtin_codes=None,
):
    """Return a download URL for the authorized canonical Skill file."""

    asset = skill_storage_asset(
        skill,
        user=user,
        builtin_codes=builtin_codes,
        enforce_access=True,
    )
    if not asset:
        return ""
    return FileService.download_url(
        asset,
        getattr(skill, "file_name", None) or asset.original_filename,
    )


def clear_legacy_skill_body(skill):
    """Remove duplicated file text from a Skill metadata row."""

    if not skill:
        return skill
    skill.content = None
    skill.prompt_template = None
    return skill
