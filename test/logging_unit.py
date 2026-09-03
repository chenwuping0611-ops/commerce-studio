"""Focused tests for production and application file logging."""

import logging
import json
import sys
import tempfile
from pathlib import Path

from flask import Flask

# Keep the test runnable both as ``python test/logging_unit.py`` and with
# the project root already present in PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from applications.common.logging_config import (
    MANAGED_HANDLER_ATTR,
    configure_logging,
)


def _test_app(log_dir, strict=True):
    app = Flask(__name__)
    app.config.update(
        LOG_DIR=str(log_dir),
        APP_LOG_FILE="",
        LOG_LEVEL="INFO",
        LOG_STRICT=strict,
        LOG_TO_CONSOLE=False,
        ALEMBIC_LOG_LEVEL="INFO",
        SQLALCHEMY_LOG_LEVEL="WARNING",
    )
    return app


def _close_managed_handlers():
    loggers = [logging.getLogger()]
    loggers.extend(
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    )
    seen = set()
    for logger in loggers:
        for handler in list(logger.handlers):
            if not getattr(handler, MANAGED_HANDLER_ATTR, False):
                continue
            logger.removeHandler(handler)
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            handler.close()


def test_file_logging_and_reconfiguration():
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            log_dir = Path(temp_dir) / "logs"
            app = _test_app(log_dir)

            log_file = configure_logging(app)
            assert log_file == str(log_dir / "pear-ai.log")

            logging.getLogger("alembic.runtime.migration").info(
                "migration log test"
            )
            app.logger.info("application log test")
            for handler in logging.getLogger().handlers:
                handler.flush()

            contents = Path(log_file).read_text(encoding="utf-8")
            assert "migration log test" in contents
            assert "application log test" in contents

            configure_logging(app)
            managed_handlers = [
                handler
                for handler in logging.getLogger().handlers
                if getattr(handler, MANAGED_HANDLER_ATTR, False)
            ]
            assert len(managed_handlers) == 1
        finally:
            _close_managed_handlers()


def test_strict_logging_does_not_fallback_to_project_directory():
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            blocking_path = Path(temp_dir) / "not-a-directory"
            blocking_path.write_text("block", encoding="utf-8")
            app = _test_app(blocking_path, strict=True)

            try:
                configure_logging(app)
            except RuntimeError as exc:
                assert "无法创建项目日志目录" in str(exc)
            else:
                raise AssertionError(
                    "strict logging configuration unexpectedly passed"
                )
        finally:
            _close_managed_handlers()


def test_json_log_format():
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            app = _test_app(Path(temp_dir) / "logs")
            app.config["LOG_FORMAT"] = "json"
            log_file = configure_logging(app)

            app.logger.info("json log test")
            for handler in logging.getLogger().handlers:
                handler.flush()

            record = json.loads(
                Path(log_file).read_text(encoding="utf-8").splitlines()[-1]
            )
            assert record["level"] == "INFO"
            assert record["logger"] == app.name
            assert record["message"] == "json log test"
        finally:
            _close_managed_handlers()


if __name__ == "__main__":
    test_file_logging_and_reconfiguration()
    test_strict_logging_does_not_fallback_to_project_directory()
    test_json_log_format()
    print("logging unit tests passed")
