"""Central logging setup for the Flask application and CLI commands."""

import json
import logging
import os
from logging.handlers import WatchedFileHandler


MANAGED_HANDLER_ATTR = "_pear_ai_managed_handler"
DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s [%(process)d] "
    "[%(name)s] %(message)s"
)


class JsonFormatter(logging.Formatter):
    """Serialize records when LOG_FORMAT=json is selected."""

    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "process": record.process,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False)


def _as_bool(value, default=False):
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _log_level(value, default=logging.INFO):
    if isinstance(value, int):
        return value
    name = str(value or "").strip().upper()
    return getattr(logging, name, default)


def _absolute_path(app, value):
    path = str(value or "").strip()
    if not path:
        return ""
    if not os.path.isabs(path):
        path = os.path.join(app.root_path, path)
    return os.path.abspath(path)


def _remove_handlers(logger, seen):
    for handler in list(logger.handlers):
        if (
            getattr(handler, MANAGED_HANDLER_ATTR, False)
            or isinstance(handler, logging.StreamHandler)
        ):
            logger.removeHandler(handler)
            if id(handler) not in seen:
                seen.add(id(handler))
                try:
                    handler.close()
                except Exception:
                    pass


def _install_handler(logger, handler, level):
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def _formatter(value):
    format_value = str(value or "").strip()
    if format_value.lower() == "json":
        return JsonFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    return logging.Formatter(
        format_value or DEFAULT_LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure_logging(app):
    """Route application and migration logs to the configured file.

    Production defaults to ``/var/log/pear-ai/pear-ai.log``. A
    ``WatchedFileHandler`` is used so CentOS logrotate can rename/truncate the
    file without requiring an application restart.
    """

    log_dir = _absolute_path(app, app.config.get("LOG_DIR") or "logs")
    log_file = _absolute_path(
        app,
        app.config.get("APP_LOG_FILE")
        or os.path.join(log_dir, "pear-ai.log"),
    )
    if not log_file:
        raise RuntimeError("APP_LOG_FILE or LOG_DIR must be configured")

    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
    except OSError as exc:
        if app.config.get("LOG_STRICT", False):
            raise RuntimeError(
                f"无法创建项目日志目录: {os.path.dirname(log_file)}"
            ) from exc
        fallback = os.path.join(app.root_path, "logs", "pear-ai.log")
        os.makedirs(os.path.dirname(fallback), exist_ok=True)
        log_file = fallback

    formatter = _formatter(app.config.get("LOG_FORMAT"))
    handler = WatchedFileHandler(
        log_file,
        encoding="utf-8",
        delay=True,
    )
    setattr(handler, MANAGED_HANDLER_ATTR, True)
    handler.setFormatter(formatter)
    handler.setLevel(_log_level(app.config.get("LOG_LEVEL"), logging.INFO))

    loggers = [
        logging.getLogger(),
        app.logger,
        logging.getLogger("alembic"),
        logging.getLogger("sqlalchemy.engine"),
        logging.getLogger("sqlalchemy.pool"),
        logging.getLogger("apscheduler"),
        logging.getLogger("werkzeug"),
    ]
    seen = set()
    for logger in loggers:
        _remove_handlers(logger, seen)

    level = _log_level(app.config.get("LOG_LEVEL"), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)
    for logger in loggers[1:]:
        _install_handler(logger, handler, level)

    if _as_bool(
        app.config.get("LOG_TO_CONSOLE"),
        default=app.config.get("ENV") != "production",
    ):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(level)
        setattr(console, MANAGED_HANDLER_ATTR, True)
        root_logger.addHandler(console)

    # Migration output is useful during deploy, but SQLAlchemy request-level
    # chatter is intentionally kept at WARNING unless explicitly overridden.
    logging.getLogger("alembic").setLevel(
        _log_level(app.config.get("ALEMBIC_LOG_LEVEL"), logging.INFO)
    )
    logging.getLogger("sqlalchemy.engine").setLevel(
        _log_level(app.config.get("SQLALCHEMY_LOG_LEVEL"), logging.WARNING)
    )

    app.config["APP_LOG_FILE"] = log_file
    return log_file
