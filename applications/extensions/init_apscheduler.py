import os

from flask import Flask
from flask_apscheduler import APScheduler


scheduler = APScheduler()


def init_scheduler(app: Flask):
    scheduler.init_app(app)

    # Flask's debug reloader creates a parent watcher and a child server.
    # Starting database jobs in both processes doubles polling and can exhaust
    # a small MySQL pool before the first page is rendered.
    if (
        os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
        and os.getenv("WERKZEUG_RUN_MAIN") != "true"
    ):
        return

    with app.app_context():
        from applications.common.tasks import events, tasks  # noqa: F401
        from applications.studio.jobs import register_jobs

        if not scheduler.running:
            scheduler.start()
        register_jobs()
