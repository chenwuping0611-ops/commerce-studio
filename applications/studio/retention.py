"""Retention cleanup for files and tasks owned by Studio generation."""

from datetime import datetime, timedelta

from sqlalchemy import and_, or_

from applications.common.asset_relations import (
    generation_task_assets,
    referenced_asset_ids,
)
from applications.common.storage import FileService
from applications.extensions import db
from sqlalchemy.orm import joinedload
from applications.models import (
    StudioAsset,
    StudioGenerationTask,
    StudioGenerationTaskAsset,
)


AMAZON_FILE_PURPOSES = ("AMAZON_INPUT", "AMAZON_RESULT")
ACTIVE_CLEANUP_STATES = ("ACTIVE", "DELETE_FAILED", "SHARED")


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


def _asset_expired_filter(now):
    """Match temporary assets with explicit or legacy derived expiry."""

    fallback_date = now - timedelta(days=_retention_days())
    non_amazon = or_(
        StudioAsset.purpose.is_(None),
        ~StudioAsset.purpose.in_(AMAZON_FILE_PURPOSES),
    )
    temporary = StudioAsset.retention_policy.in_(
        (FileService.TEMPORARY, FileService.TTL_7D)
    )
    explicit_or_legacy_expiry = or_(
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
    # DELETE_FAILED rows are retried even when an old row has no reliable
    # expiry timestamp. Product/Skill references are checked before deletion.
    return and_(
        non_amazon,
        StudioAsset.status.in_(("ACTIVE", "DELETE_FAILED")),
        or_(
            and_(temporary, explicit_or_legacy_expiry),
            StudioAsset.status == "DELETE_FAILED",
        ),
    )


def _generation_assets(task_id):
    """Return relation-table assets plus legacy rows missing a relation."""

    return _generation_assets_batch([task_id]).get(int(task_id), [])


def _generation_assets_batch(task_ids):
    """Load all assets for a cleanup batch with bounded relation queries."""

    task_ids = sorted({int(task_id) for task_id in task_ids if task_id})
    if not task_ids:
        return {}
    links = (
        StudioGenerationTaskAsset.query
        .filter(
            StudioGenerationTaskAsset.generation_task_id.in_(task_ids)
        )
        .options(joinedload(StudioGenerationTaskAsset.asset))
        .order_by(
            StudioGenerationTaskAsset.generation_task_id.asc(),
            StudioGenerationTaskAsset.sort.asc(),
            StudioGenerationTaskAsset.id.asc(),
        )
        .all()
    )
    assets_by_task = {}
    seen_by_task = {}
    for link in links:
        asset = link.asset
        if not asset:
            continue
        task_id = int(link.generation_task_id)
        if asset.id in seen_by_task.setdefault(task_id, set()):
            continue
        seen_by_task[task_id].add(asset.id)
        assets_by_task.setdefault(task_id, []).append(asset)

    legacy_assets = (
        StudioAsset.query.filter(
            StudioAsset.generation_task_id.in_(task_ids)
        )
        .order_by(StudioAsset.id.asc())
        .all()
    )
    for asset in legacy_assets:
        task_id = int(asset.generation_task_id)
        if asset.id not in seen_by_task.setdefault(task_id, set()):
            seen_by_task[task_id].add(asset.id)
            assets_by_task.setdefault(task_id, []).append(asset)
    return assets_by_task


def clear_stale_task_outputs(task_ids):
    """Remove URLs that no longer point at an active generated asset."""

    task_ids = list({int(task_id) for task_id in task_ids if task_id})
    if not task_ids:
        return 0
    cleared = 0
    tasks = StudioGenerationTask.query.filter(
        StudioGenerationTask.id.in_(task_ids)
    ).all()
    for task in tasks:
        active_output = next(
            (
                asset
                for asset in generation_task_assets(
                    task.id,
                    roles={"OUTPUT", "RESULT", "THUMBNAIL"},
                    include_legacy=True,
                )
                if asset
                and asset.purpose == "GENERATION_OUTPUT"
                and asset.status == "ACTIVE"
            ),
            None,
        )
        if not active_output and task.output_url:
            task.output_url = None
            task.output_format = None
            cleared += 1
    return cleared


def delete_generation_task(task, assets=None, referenced_ids=None):
    """Delete one terminal generation task without deleting shared assets."""

    if not task:
        return {"deleted": False, "message": "任务不存在", "failed_assets": 0}
    if task.status in ("PENDING", "SUBMITTED", "PROCESSING"):
        return {
            "deleted": False,
            "message": "处理中任务不能删除，请等待任务结束",
            "failed_assets": 0,
        }

    assets = (
        _generation_assets(task.id)
        if assets is None
        else list(assets)
    )
    if referenced_ids is None:
        referenced_ids = referenced_asset_ids(
            [asset.id for asset in assets],
            generation_task_id=task.id,
        )
    referenced_ids = set(referenced_ids or ())
    # A permanent asset is protected by its own retention policy even when a
    # legacy Product/Skill relation was not backfilled yet. Task cleanup may
    # remove the task link, but it must never remove the stored file.
    permanent_ids = {
        asset.id
        for asset in assets
        if str(asset.retention_policy or "").upper()
        == FileService.PERMANENT
    }
    failed_assets = []
    shared_assets = []
    protected_assets = []
    for asset in assets:
        if asset.id in permanent_ids:
            protected_assets.append(asset)
            continue
        is_shared = asset.id in referenced_ids
        if is_shared:
            shared_assets.append(asset)
            continue
        if asset.status not in ("ACTIVE", "DELETE_FAILED"):
            continue
        try:
            if not FileService.delete_asset(asset):
                failed_assets.append(asset)
        except Exception as exc:
            asset.error_message = str(exc)
            asset.status = "DELETE_FAILED"
            failed_assets.append(asset)

    if failed_assets:
        db.session.commit()
        return {
            "deleted": False,
            "message": "部分生成资产删除失败，请稍后重试",
            "failed_assets": len(failed_assets),
            "shared_assets": len(shared_assets),
            "protected_assets": len(protected_assets),
        }

    # Remove normalized links explicitly before deleting the task/assets. This
    # avoids double DELETE warnings when both sides of the relationship were
    # loaded and the database FK also has ON DELETE CASCADE.
    StudioGenerationTaskAsset.query.filter(
        StudioGenerationTaskAsset.generation_task_id == task.id,
    ).delete(synchronize_session=False)
    if "asset_links" in getattr(task, "__dict__", {}):
        db.session.expire(task, ["asset_links"])
    for asset in assets:
        if "generation_links" in getattr(asset, "__dict__", {}):
            db.session.expire(asset, ["generation_links"])
    for asset in assets:
        if asset.id in referenced_ids or asset.id in permanent_ids:
            if asset.generation_task_id == task.id:
                asset.generation_task_id = None
            continue
        db.session.delete(asset)
    db.session.delete(task)
    db.session.commit()
    return {
        "deleted": True,
        "message": "历史任务已删除",
        "failed_assets": 0,
        "shared_assets": len(shared_assets),
        "protected_assets": len(protected_assets),
    }


def _expired_generation_tasks(limit, now):
    fallback_date = now - timedelta(days=_retention_days())
    expiry = or_(
        and_(
            StudioGenerationTask.expires_at.isnot(None),
            StudioGenerationTask.expires_at <= now,
        ),
        and_(
            StudioGenerationTask.expires_at.is_(None),
            StudioGenerationTask.created_at.isnot(None),
            StudioGenerationTask.created_at <= fallback_date,
        ),
    )
    return (
        StudioGenerationTask.query.filter(
            StudioGenerationTask.status.in_(("SUCCEEDED", "FAILED", "CANCELLED")),
            StudioGenerationTask.retention_policy.in_(
                (FileService.TEMPORARY, FileService.TTL_7D)
            ),
            StudioGenerationTask.storage_cleanup_status.in_(
                ACTIVE_CLEANUP_STATES
            ),
            expiry,
        )
        .order_by(
            StudioGenerationTask.expires_at.asc(),
            StudioGenerationTask.id.asc(),
        )
        .limit(max(1, int(limit or 100)))
        .all()
    )


def _cleanup_orphan_assets(limit, now):
    """Delete expired unreferenced non-Amazon files and retry failures."""

    assets = (
        StudioAsset.query.filter(
            _asset_expired_filter(now),
        )
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
        and asset.status != "DELETE_FAILED"
    }
    deleted = 0
    failed = 0
    protected = 0
    affected_task_ids = set()
    for asset in assets:
        legacy_task_id = asset.generation_task_id
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
            if legacy_task_id:
                affected_task_ids.add(legacy_task_id)
            db.session.delete(asset)
        else:
            failed += 1
        # Persist every item independently so one failed remote deletion does
        # not roll back successful deletions from the same batch.
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
        "affected_task_ids": affected_task_ids,
    }


def cleanup_expired_assets(limit=100, now=None):
    """Clean expired generation tasks first, then unreferenced files."""

    now = now or datetime.now()
    batch_size = max(1, int(limit or 100))
    tasks = _expired_generation_tasks(batch_size, now)
    assets_by_task = _generation_assets_batch(
        [task.id for task in tasks]
    )
    tasks_deleted = 0
    tasks_failed = 0
    shared_assets = 0
    deleted_assets = 0
    failed_assets = 0
    affected_task_ids = set()

    for task in tasks:
        affected_task_ids.add(task.id)
        task_assets = assets_by_task.get(task.id, [])
        task_asset_count = len(task_assets)
        try:
            result = delete_generation_task(
                task,
                assets=task_assets,
            )
        except Exception as exc:
            db.session.rollback()
            current = StudioGenerationTask.query.get(task.id)
            if current:
                current.storage_cleanup_status = "DELETE_FAILED"
                current.storage_cleanup_error = str(exc)[:4000]
                db.session.commit()
            result = {
                "deleted": False,
                "failed_assets": 1,
                "shared_assets": 0,
                "protected_assets": 0,
            }
        if result.get("deleted"):
            tasks_deleted += 1
            deleted_assets += max(
                0,
                task_asset_count - int(result.get("shared_assets") or 0),
            )
        else:
            tasks_failed += 1
            failed_assets += int(result.get("failed_assets") or 0)
        shared_assets += int(result.get("shared_assets") or 0)

    orphan_result = _cleanup_orphan_assets(batch_size, now)
    affected_task_ids.update(orphan_result["affected_task_ids"])
    cleared = clear_stale_task_outputs(affected_task_ids)
    db.session.commit()
    return {
        "scanned": len(tasks) + orphan_result["scanned"],
        "deleted": deleted_assets + orphan_result["deleted"],
        "failed": failed_assets + orphan_result["failed"],
        "protected": shared_assets + orphan_result["protected"],
        "tasks_scanned": len(tasks),
        "tasks_deleted": tasks_deleted,
        "tasks_failed": tasks_failed,
        "orphan_assets_scanned": orphan_result["scanned"],
        "orphan_assets_deleted": orphan_result["deleted"],
        "orphan_assets_failed": orphan_result["failed"],
        "cleared_task_outputs": cleared,
    }
