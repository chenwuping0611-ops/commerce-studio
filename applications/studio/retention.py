"""Retention cleanup for files stored through the Commerce Studio facade."""

from datetime import datetime, timedelta

from sqlalchemy import and_, or_

from applications.common.storage import FileService
from applications.extensions import db
from applications.models import StudioAsset, StudioGenerationTask


def _asset_expired_filter(now):
    """Match explicit expiry dates and legacy rows without an expiry date."""

    ttl_days = 7
    try:
        from flask import current_app

        ttl_days = int(current_app.config.get("STUDIO_ASSET_TTL_DAYS") or 7)
    except RuntimeError:
        pass
    fallback_date = now - timedelta(days=ttl_days)
    return or_(
        and_(
            StudioAsset.retention_policy == FileService.TTL_7D,
            StudioAsset.expires_at.isnot(None),
            StudioAsset.expires_at <= now,
        ),
        and_(
            StudioAsset.retention_policy == FileService.TTL_7D,
            StudioAsset.expires_at.is_(None),
            StudioAsset.created_at.isnot(None),
            StudioAsset.created_at <= fallback_date,
        ),
        StudioAsset.status == "DELETE_FAILED",
    )


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
        active_output = StudioAsset.query.filter_by(
            generation_task_id=task.id,
            purpose="GENERATION_OUTPUT",
            status="ACTIVE",
        ).first()
        if not active_output and task.output_url:
            task.output_url = None
            task.output_format = None
            cleared += 1
    return cleared


def delete_generation_task(task):
    """Delete one terminal generation task and its stored media assets.

    The caller is responsible for authorizing the operator. Storage objects
    are removed before their metadata and the task row are deleted so a
    failed GoFastDFS request leaves a retryable history record.
    """

    if not task:
        return {"deleted": False, "message": "任务不存在", "failed_assets": 0}
    if task.status in ("PENDING", "SUBMITTED", "PROCESSING"):
        return {
            "deleted": False,
            "message": "处理中任务不能删除，请等待任务结束",
            "failed_assets": 0,
        }

    assets = StudioAsset.query.filter_by(generation_task_id=task.id).all()
    failed_assets = 0
    for asset in assets:
        if asset.status in ("ACTIVE", "DELETE_FAILED"):
            if not FileService.delete_asset(asset):
                failed_assets += 1

    if failed_assets:
        db.session.commit()
        return {
            "deleted": False,
            "message": "部分生成资产删除失败，请稍后重试",
            "failed_assets": failed_assets,
        }

    for asset in assets:
        db.session.delete(asset)
    db.session.delete(task)
    db.session.commit()
    return {
        "deleted": True,
        "message": "历史任务已删除",
        "failed_assets": 0,
    }


def cleanup_expired_assets(limit=100, now=None):
    """Delete expired temporary assets and keep failed rows for retry."""

    now = now or datetime.now()
    assets = (
        StudioAsset.query.filter(
            StudioAsset.status.in_(("ACTIVE", "DELETE_FAILED")),
            _asset_expired_filter(now),
        )
        .order_by(StudioAsset.expires_at.asc(), StudioAsset.id.asc())
        .limit(limit)
        .all()
    )
    deleted = 0
    failed = 0
    affected_task_ids = set()

    for asset in assets:
        if asset.generation_task_id:
            affected_task_ids.add(asset.generation_task_id)
        if FileService.delete_asset(asset):
            deleted += 1
        else:
            failed += 1
        # Persist each result so a later failure does not roll back prior cleanup.
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            failed += 1

    cleared = clear_stale_task_outputs(affected_task_ids)
    db.session.commit()
    return {
        "scanned": len(assets),
        "deleted": deleted,
        "failed": failed,
        "cleared_task_outputs": cleared,
    }
