"""Small MySQL advisory-lock helper for scheduled maintenance jobs."""

from contextlib import contextmanager

from sqlalchemy import text

from applications.extensions import db


@contextmanager
def mysql_named_lock(name, timeout=0):
    """Yield whether a non-blocking MySQL named lock was acquired.

    MySQL named locks belong to one physical connection, so the connection
    stays open for the duration of the maintenance operation and is released
    in the same ``finally`` block. Non-MySQL test databases do not need the
    lock and continue normally.
    """

    connection = None
    acquired = False
    lock_name = str(name or "commerce-studio-cleanup")[:64]
    dialect = getattr(getattr(db, "engine", None), "dialect", None)
    is_mysql = str(getattr(dialect, "name", "")).lower() == "mysql"
    try:
        if not is_mysql:
            yield True
            return

        connection = db.engine.connect()
        result = connection.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout)"),
            {"lock_name": lock_name, "timeout": max(0, int(timeout or 0))},
        ).scalar()
        acquired = str(result) == "1"
        yield acquired
    finally:
        if connection is not None:
            if acquired:
                try:
                    connection.execute(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": lock_name},
                    )
                except Exception:
                    # The connection may already be broken; closing it still
                    # releases the server-side named lock.
                    pass
            connection.close()
