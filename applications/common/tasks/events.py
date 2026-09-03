from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED,
)

from applications.extensions.init_apscheduler import scheduler


def job_missed(event):
    """Job missed event."""
    with scheduler.app.app_context():
        scheduler.app.logger.warning("APScheduler job missed: %s", event)


def job_error(event):
    """Job error event."""
    with scheduler.app.app_context():
        scheduler.app.logger.error("APScheduler job error: %s", event)


scheduler.add_listener(job_missed, EVENT_JOB_MISSED)
scheduler.add_listener(job_error, EVENT_JOB_ERROR)
