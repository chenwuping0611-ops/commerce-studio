from flask import current_app

from applications.extensions.init_apscheduler import scheduler
from applications.amazon_ai.retention import cleanup_expired_amazon_files
from applications.common.admin_log import cleanup_expired_admin_logs
from applications.common.cleanup_lock import mysql_named_lock
from applications.studio.generation_service import poll_processing_tasks
from applications.studio.retention import cleanup_expired_assets


def poll_generation_tasks():
    with scheduler.app.app_context():
        return poll_processing_tasks()


def cleanup_studio_assets():
    with scheduler.app.app_context():
        with mysql_named_lock("commerce-studio:cleanup:generation") as acquired:
            if not acquired:
                return {"skipped": True, "reason": "another worker owns the lock"}
            result = cleanup_expired_assets()
        if result["failed"]:
            current_app.logger.warning(
                "studio asset cleanup completed with failures: %s", result
            )
        return result


def cleanup_amazon_ai_files():
    with scheduler.app.app_context():
        with mysql_named_lock("commerce-studio:cleanup:amazon") as acquired:
            if not acquired:
                return {"skipped": True, "reason": "another worker owns the lock"}
            result = cleanup_expired_amazon_files()
        if (
            result["task_files_failed"]
            or result["orphan_assets_failed"]
        ):
            current_app.logger.warning(
                "Amazon AI file cleanup completed with failures: %s",
                result,
            )
        return result


def cleanup_admin_logs():
    with scheduler.app.app_context():
        with mysql_named_lock("commerce-studio:cleanup:admin-log") as acquired:
            if not acquired:
                return {"skipped": True, "reason": "another worker owns the lock"}
            result = cleanup_expired_admin_logs(
                limit=max(
                    1,
                    int(
                        scheduler.app.config.get("STUDIO_CLEANUP_BATCH_SIZE")
                        or 100
                    ),
                )
            )
        return result


def register_jobs():
    scheduler.add_job(
        id="studio-poll-generation-tasks",
        func=poll_generation_tasks,
        trigger="interval",
        seconds=30,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        id="studio-cleanup-expired-assets",
        func=cleanup_studio_assets,
        trigger="interval",
        seconds=max(
            300,
            int(scheduler.app.config.get("STUDIO_ASSET_CLEANUP_INTERVAL") or 3600),
        ),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        id="amazon-ai-cleanup-expired-files",
        func=cleanup_amazon_ai_files,
        trigger="interval",
        seconds=max(
            300,
            int(scheduler.app.config.get("STUDIO_ASSET_CLEANUP_INTERVAL") or 3600),
        ),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        id="admin-log-cleanup-expired",
        func=cleanup_admin_logs,
        trigger="interval",
        seconds=max(
            300,
            int(
                scheduler.app.config.get("ADMIN_LOG_CLEANUP_INTERVAL")
                or 86400
            ),
        ),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
