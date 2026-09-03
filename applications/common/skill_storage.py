"""Read Skill bodies from GoFastDFS while keeping legacy rows compatible.

Skill metadata belongs in MySQL, but the editable instruction document is a
stored file. New callers should use this module instead of reading
``StudioSkill.content`` or ``StudioSkill.prompt_template`` directly.
"""

import datetime

from applications.common.scope import can_access_asset, can_access_skill
from applications.common.storage import FileService, StorageError
from applications.models import StudioAsset


DEFAULT_MAX_SKILL_BYTES = 512000


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
