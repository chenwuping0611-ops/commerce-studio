from flask import current_app

from applications.extensions.init_apscheduler import scheduler
from applications.studio.generation_service import poll_processing_tasks
from applications.studio.retention import cleanup_expired_assets


def poll_generation_tasks():
    with scheduler.app.app_context():
        return poll_processing_tasks()


def cleanup_studio_assets():
    with scheduler.app.app_context():
        result = cleanup_expired_assets()
        if result["failed"]:
            current_app.logger.warning(
                "studio asset cleanup completed with failures: %s", result
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
