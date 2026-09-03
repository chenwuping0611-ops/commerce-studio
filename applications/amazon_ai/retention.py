"""Retention cleanup for Amazon AI tasks and their stored files."""

import json
from datetime import datetime, timedelta

from sqlalchemy import and_, or_

from applications.common.asset_relations import (
    referenced_asset_ids,
)
from applications.common.storage import FileService
from applications.extensions import db
from applications.models import AmazonAiTask, StudioAsset
from applications.models.amazon_ai import AmazonAiTaskAsset
from sqlalchemy.orm import joinedload, noload


AMAZON_FILE_PURPOSES = ("AMAZON_INPUT", "AMAZON_RESULT")
ACTIVE_TASK_CLEANUP_STATES = (
    "ACTIVE",
    "DELETE_FAILED",
    "SHARED",
    "NONE",
)


def _json(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _unique_asset_ids(values):
    result = []
    for value in values or ():
        asset_id = _int_or_none(value)
        if asset_id and asset_id not in result:
            result.append(asset_id)
    return result


def _retention_days():
    try:
        from flask import current_app

        return max(
            1,
            int(
                current_app.config.get("STUDIO_TEMPORARY_RETENTION_DAYS")
                or current_app.config.get("STUDIO_ASSET_TTL_DAYS")
                or 30
            ),
        )
    except (RuntimeError, TypeError, ValueError):
        return 30


def _task_file_refs(task):
    refs = _json(task.file_refs_json, {}) or {}
    if not isinstance(refs, dict):
        refs = {}
    for key in ("inputs", "results", "legacy_urls"):
        value = refs.get(key)
        refs[key] = value if isinstance(value, list) else []
    return refs


def _snapshot_asset_ids(task):
    """Read legacy JSON ids only to complete pre-normalization rows."""

    refs = _task_file_refs(task)
    ids = []
    for group in ("inputs", "results"):
        for item in refs[group]:
            if isinstance(item, dict):
                asset_id = _int_or_none(item.get("asset_id"))
                if asset_id and asset_id not in ids:
                    ids.append(asset_id)

    input_refs = _json(task.input_refs_json, {}) or {}
    for value in input_refs.get("asset_ids") or []:
        asset_id = _int_or_none(value)
        if asset_id and asset_id not in ids:
            ids.append(asset_id)

    result_refs = _json(task.result_refs_json, {}) or {}
    for key in (
        "response_asset_id",
        "response_asset_ids",
        "result_asset_id",
        "result_asset_ids",
        "output_asset_id",
        "output_asset_ids",
    ):
        values = result_refs.get(key)
        values = values if isinstance(values, (list, tuple, set)) else [values]
        for value in values:
            asset_id = _int_or_none(value)
            if asset_id and asset_id not in ids:
                ids.append(asset_id)
    output_asset_id = _int_or_none(task.output_asset_id)
    if output_asset_id and output_asset_id not in ids:
        ids.append(output_asset_id)
    return ids


def _asset_expired_filter(now):
    """Match temporary Amazon assets with explicit or legacy expiry."""

    fallback_date = now - timedelta(days=_retention_days())
    temporary = StudioAsset.retention_policy.in_(
        (FileService.TEMPORARY, FileService.TTL_7D)
    )
    expiry = or_(
        and_(
            StudioAsset.expires_at.isnot(None),
            StudioAsset.expires_at <= now,
        ),
        and_(
            StudioAsset.expires_at.is_(None),
            StudioAsset.created_at.isnot(None),
            StudioAsset.created_at <= fallback_date,
        ),
    )
    return and_(
        StudioAsset.purpose.in_(AMAZON_FILE_PURPOSES),
        StudioAsset.status.in_(("ACTIVE", "DELETE_FAILED")),
        or_(
            and_(temporary, expiry),
            StudioAsset.status == "DELETE_FAILED",
        ),
    )


def _cleanup_task_filters():
    cleanup_state = or_(
        AmazonAiTask.storage_cleanup_status.is_(None),
        AmazonAiTask.storage_cleanup_status.in_(ACTIVE_TASK_CLEANUP_STATES),
    )
    return (
        AmazonAiTask.status.in_(("SUCCEEDED", "FAILED", "CANCELLED")),
        AmazonAiTask.retention_policy.in_(
            (FileService.TEMPORARY, FileService.TTL_7D)
        ),
        cleanup_state,
    )


def _expired_task_candidates(limit, now):
    """Fetch both expiry paths independently so MySQL can use each index."""

    limit = max(1, int(limit or 100))
    fallback_date = now - timedelta(days=_retention_days())
    relationship_options = (
        noload(AmazonAiTask.source_links),
        noload(AmazonAiTask.asset_links),
    )
    common_filters = _cleanup_task_filters()
    explicit_expiry = (
        AmazonAiTask.query
        .filter(
            *common_filters,
            AmazonAiTask.expires_at.isnot(None),
            AmazonAiTask.expires_at <= now,
        )
        .options(*relationship_options)
        .order_by(
            AmazonAiTask.expires_at.asc(),
            AmazonAiTask.id.asc(),
        )
        .limit(limit)
        .all()
    )
    legacy_expiry = (
        AmazonAiTask.query
        .filter(
            *common_filters,
            AmazonAiTask.expires_at.is_(None),
            AmazonAiTask.created_at.isnot(None),
            AmazonAiTask.created_at <= fallback_date,
        )
        .options(*relationship_options)
        .order_by(
            AmazonAiTask.created_at.asc(),
            AmazonAiTask.id.asc(),
        )
        .limit(limit)
        .all()
    )
    candidates = explicit_expiry + legacy_expiry
    candidates.sort(
        key=lambda task: (
            0 if task.expires_at is None else 1,
            task.expires_at or task.created_at or datetime.max,
            task.id,
        )
    )
    return candidates[:limit]


def _snapshot_url(item):
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("public_url")
        or item.get("url")
        or item.get("storage_path")
        or ""
    ).strip()


def _snapshot_asset_id(item):
    return _int_or_none(item.get("asset_id")) if isinstance(item, dict) else None


def _mark_snapshot(item, status, now, error=None):
    if not isinstance(item, dict):
        return
    item["status"] = status
    item["cleanup_at"] = now.isoformat()
    if error:
        item["cleanup_error"] = str(error)
    elif status != "DELETE_FAILED":
        item.pop("cleanup_error", None)
    if status in ("DELETED", "SHARED", "MISSING"):
        item["download_url"] = ""


def _legacy_storage_refs(task, resolved_asset_ids):
    """Return managed URLs not represented by a normalized asset row."""

    refs = _task_file_refs(task)
    resolved_ids = set(resolved_asset_ids or [])
    result_refs = _json(task.result_refs_json, {}) or {}
    checksum = (
        result_refs.get("response_checksum")
        or result_refs.get("response_md5")
        or result_refs.get("checksum")
        or result_refs.get("md5")
    )
    candidates = []
    seen = set()

    def add(url, value_checksum=None):
        url = str(url or "").strip()
        if (
            not url
            or url in seen
            or not FileService.is_managed_url(url)
        ):
            return
        seen.add(url)
        candidates.append((url, value_checksum))

    for group in ("inputs", "results", "legacy_urls"):
        for item in refs[group]:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "ACTIVE").upper() in (
                "DELETED",
                "SHARED",
                "MISSING",
            ):
                continue
            if _snapshot_asset_id(item) in resolved_ids:
                continue
            add(
                _snapshot_url(item),
                item.get("checksum") or item.get("md5") or checksum,
            )

    for key in (
        "response_download_url",
        "response_url",
        "output_url",
        "output_urls",
        "file_url",
        "file_urls",
    ):
        values = result_refs.get(key)
        values = values if isinstance(values, (list, tuple, set)) else [values]
        response_asset_id = _int_or_none(
            result_refs.get("response_asset_id")
        )
        if response_asset_id in resolved_ids:
            continue
        for value in values:
            add(value, checksum)
    return candidates


def _task_assets(task):
    """Load normalized task assets and add legacy ids missing a relation."""

    return _task_assets_batch([task]).get(int(task.id), [])


def _task_assets_batch(tasks):
    """Load all normalized and legacy assets for a cleanup batch."""

    tasks = list(tasks or ())
    task_ids = sorted(
        {
            int(task.id if hasattr(task, "id") else task)
            for task in tasks
            if getattr(task, "id", task)
        }
    )
    if not task_ids:
        return {}

    links = (
        AmazonAiTaskAsset.query
        .filter(AmazonAiTaskAsset.task_id.in_(task_ids))
        .options(joinedload(AmazonAiTaskAsset.asset))
        .order_by(
            AmazonAiTaskAsset.task_id.asc(),
            AmazonAiTaskAsset.sort.asc(),
            AmazonAiTaskAsset.id.asc(),
        )
        .all()
    )
    assets_by_task = {}
    seen_by_task = {}
    for link in links:
        asset = link.asset
        if not asset:
            continue
        task_id = int(link.task_id)
        if asset.id in seen_by_task.setdefault(task_id, set()):
            continue
        seen_by_task[task_id].add(asset.id)
        assets_by_task.setdefault(task_id, []).append(asset)

    task_by_id = {
        int(task.id): task
        for task in tasks
        if getattr(task, "id", None)
    }
    legacy_ids_by_task = {}
    for task_id, task in task_by_id.items():
        existing_ids = set(seen_by_task.get(task_id, set()))
        missing_ids = [
            asset_id
            for asset_id in _snapshot_asset_ids(task)
            if asset_id not in existing_ids
        ]
        if missing_ids:
            legacy_ids_by_task[task_id] = missing_ids
    all_legacy_ids = _unique_asset_ids(
        asset_id
        for values in legacy_ids_by_task.values()
        for asset_id in values
    )
    if all_legacy_ids:
        legacy_assets = StudioAsset.query.filter(
            StudioAsset.id.in_(all_legacy_ids),
        ).all()
        by_id = {int(asset.id): asset for asset in legacy_assets}
        for task_id, asset_ids in legacy_ids_by_task.items():
            assets_by_task.setdefault(task_id, []).extend(
                by_id[asset_id]
                for asset_id in asset_ids
                if asset_id in by_id
            )
    return assets_by_task


def _cleanup_task(task, now, assets=None, referenced_ids=None):
    refs = _task_file_refs(task)
    assets = _task_assets(task) if assets is None else list(assets)
    if referenced_ids is None:
        referenced_ids = referenced_asset_ids(
            [asset.id for asset in assets],
            amazon_task_id=task.id,
        )
    referenced_ids = set(referenced_ids or ())
    # Retention is an invariant of the asset itself. A permanent Product or
    # Skill file must survive task cleanup even if its business relation is
    # temporarily absent from the normalized tables.
    permanent_ids = {
        asset.id
        for asset in assets
        if str(asset.retention_policy or "").upper()
        == FileService.PERMANENT
    }
    failed = []
    deleted = 0
    protected = 0

    for asset in assets:
        if asset.id in referenced_ids or asset.id in permanent_ids:
            protected += 1
            continue
        if asset.status not in ("ACTIVE", "DELETE_FAILED"):
            continue
        try:
            is_deleted = FileService.delete_asset(asset)
        except Exception as exc:
            is_deleted = False
            asset.error_message = str(exc)
            asset.status = "DELETE_FAILED"
        if is_deleted:
            deleted += 1
        else:
            failed.append(str(asset.id))

    resolved_ids = [asset.id for asset in assets]
    legacy_refs = _legacy_storage_refs(task, resolved_ids)
    for storage_url, checksum in legacy_refs:
        try:
            is_deleted = FileService.delete_storage(
                storage_url,
                checksum=checksum,
            )
            error = "GoFastDFS 文件删除失败"
        except Exception as exc:
            is_deleted = False
            error = str(exc)
        if not is_deleted:
            failed.append(storage_url)
            for group in ("inputs", "results", "legacy_urls"):
                for item in refs[group]:
                    if (
                        isinstance(item, dict)
                        and _snapshot_url(item) == storage_url
                    ):
                        _mark_snapshot(item, "DELETE_FAILED", now, error)
        else:
            for group in ("inputs", "results", "legacy_urls"):
                for item in refs[group]:
                    if (
                        isinstance(item, dict)
                        and _snapshot_url(item) == storage_url
                    ):
                        _mark_snapshot(item, "DELETED", now)

    if failed:
        task.storage_cleanup_status = "DELETE_FAILED"
        task.storage_cleanup_error = "；".join(failed)[:4000]
        task.file_refs_json = json.dumps(
            refs,
            ensure_ascii=False,
            default=str,
        )
        return {
            "deleted": False,
            "files_deleted": deleted,
            "protected": protected,
            "failed": len(failed),
        }

    # Remove normalized asset links explicitly before deleting the task/assets.
    # This prevents ORM/database cascade double-deletes when a relationship
    # collection was already loaded.
    AmazonAiTaskAsset.query.filter(
        AmazonAiTaskAsset.task_id == task.id,
    ).delete(synchronize_session=False)
    if "asset_links" in getattr(task, "__dict__", {}):
        db.session.expire(task, ["asset_links"])
    for asset in assets:
        if asset.id in referenced_ids or asset.id in permanent_ids:
            continue
        db.session.delete(asset)
    db.session.delete(task)
    return {
        "deleted": True,
        "files_deleted": deleted,
        "protected": protected,
        "failed": 0,
    }


def _cleanup_orphan_assets(limit, now):
    """Clean expired Amazon uploads that never reached a durable task."""

    assets = (
        StudioAsset.query.filter(_asset_expired_filter(now))
        .order_by(StudioAsset.expires_at.asc(), StudioAsset.id.asc())
        .limit(max(1, int(limit or 100)))
        .all()
    )
    referenced_ids = referenced_asset_ids(
        [asset.id for asset in assets],
        now=None,
    )
    permanent_ids = {
        asset.id
        for asset in assets
        if str(asset.retention_policy or "").upper()
        == FileService.PERMANENT
    }
    deleted = 0
    failed = 0
    protected = 0
    for asset in assets:
        if asset.id in referenced_ids or asset.id in permanent_ids:
            protected += 1
            continue
        try:
            is_deleted = FileService.delete_asset(asset)
        except Exception as exc:
            is_deleted = False
            asset.error_message = str(exc)
            asset.status = "DELETE_FAILED"
        if is_deleted:
            deleted += 1
            db.session.delete(asset)
        else:
            failed += 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            failed += 1
    return {
        "scanned": len(assets),
        "deleted": deleted,
        "failed": failed,
        "protected": protected,
    }


def cleanup_expired_amazon_files(limit=100, now=None):
    """Delete expired Amazon tasks in batches, then unreferenced assets."""

    now = now or datetime.now()
    batch_size = max(1, int(limit or 100))
    tasks = _expired_task_candidates(batch_size, now)
    assets_by_task = _task_assets_batch(tasks)
    task_files_deleted = 0
    task_files_failed = 0
    task_files_protected = 0
    tasks_deleted = 0
    for task in tasks:
        try:
            result = _cleanup_task(
                task,
                now,
                assets=assets_by_task.get(task.id, []),
            )
            task_files_deleted += result["files_deleted"]
            task_files_failed += result["failed"]
            task_files_protected += result["protected"]
            if result["deleted"]:
                tasks_deleted += 1
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current = AmazonAiTask.query.get(task.id)
            if current:
                current.storage_cleanup_status = "DELETE_FAILED"
                current.storage_cleanup_error = str(exc)[:4000]
                db.session.commit()
            task_files_failed += 1

    orphan_result = _cleanup_orphan_assets(batch_size, now)
    return {
        "tasks_scanned": len(tasks),
        "tasks_deleted": tasks_deleted,
        "task_files_deleted": task_files_deleted,
        "task_files_protected": task_files_protected,
        "task_files_failed": task_files_failed,
        "orphan_assets_scanned": orphan_result["scanned"],
        "orphan_assets_deleted": orphan_result["deleted"],
        "orphan_assets_protected": orphan_result["protected"],
        "orphan_assets_failed": orphan_result["failed"],
    }
