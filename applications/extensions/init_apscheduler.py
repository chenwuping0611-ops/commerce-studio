from flask import Flask
from flask_apscheduler import APScheduler


scheduler = APScheduler()


def init_scheduler(app: Flask):
    scheduler.init_app(app)
    with app.app_context():
        from applications.common.tasks import events, tasks  # noqa: F401
        from applications.studio.jobs import register_jobs

        if not scheduler.running:
            scheduler.start()
        register_jobs()
