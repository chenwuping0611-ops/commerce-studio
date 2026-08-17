from applications.extensions.init_apscheduler import scheduler
from applications.studio.generation_service import poll_processing_tasks


def poll_generation_tasks():
    with scheduler.app.app_context():
        return poll_processing_tasks()


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
