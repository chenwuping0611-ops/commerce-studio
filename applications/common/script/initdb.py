"""Database bootstrap helpers used by the Flask CLI.

The old project imported ``test/pear.sql`` during ``flask init``. That
created an incomplete, test-shaped database and bypassed the current Alembic
schema. New environments must be created from the migration chain instead.
"""

import os
import re

import pymysql
from flask import current_app
from flask_migrate import upgrade

from applications.extensions import db


DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_$]+$")


def _database_config():
    config = current_app.config
    database = str(config.get("MYSQL_DATABASE") or "").strip()
    if not database or not DATABASE_NAME_PATTERN.fullmatch(database):
        raise RuntimeError(
            "MYSQL_DATABASE 只能包含字母、数字、下划线或美元符号"
        )
    return {
        "host": config.get("MYSQL_HOST") or "127.0.0.1",
        "port": int(config.get("MYSQL_PORT") or 3306),
        "user": config.get("MYSQL_USERNAME") or "root",
        "password": config.get("MYSQL_PASSWORD") or "",
        "database": database,
    }


def _server_connection():
    settings = _database_config()
    return pymysql.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        charset="utf8mb4",
        autocommit=True,
    )


def _quoted_database_name(database):
    # The name has already passed the strict allow-list validation above.
    return f"`{database}`"


def database_exists():
    settings = _database_config()
    connection = _server_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.SCHEMATA
                WHERE SCHEMA_NAME = %s
                """,
                (settings["database"],),
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


def ensure_database():
    settings = _database_config()
    connection = _server_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE DATABASE IF NOT EXISTS "
                f"{_quoted_database_name(settings['database'])} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        connection.close()


def reset_database():
    """Drop and recreate only the configured application database."""

    settings = _database_config()
    # Dispose pooled connections before dropping the database they reference.
    db.session.remove()
    db.engine.dispose()

    connection = _server_connection()
    try:
        with connection.cursor() as cursor:
            database = _quoted_database_name(settings["database"])
            cursor.execute(f"DROP DATABASE IF EXISTS {database}")
            cursor.execute(
                f"CREATE DATABASE {database} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        connection.close()

    db.engine.dispose()


def migrate_schema():
    """Apply the complete current schema, including all relationship tables."""

    migrations_path = os.path.join(current_app.root_path, "migrations")
    upgrade(directory=migrations_path)


def initialize_full_database(
    *,
    fresh=False,
    seed_storage=False,
):
    """Create the current schema and seed only safe built-in configuration."""

    if fresh:
        reset_database()
    else:
        ensure_database()

    migrate_schema()

    # Importing the models ensures SQLAlchemy metadata is complete before the
    # idempotent bootstrap functions run. The migration chain remains the
    # source of truth for the physical schema.
    import applications.models  # noqa: F401

    from applications.amazon_ai.bootstrap import initialize_amazon_ai
    from applications.studio.bootstrap import initialize_studio

    studio_options = {
        "seed_credentials": False,
        "clear_credentials": fresh,
        "seed_storage": seed_storage,
    }
    initialize_studio(
        **studio_options,
    )
    initialize_amazon_ai(seed_storage=seed_storage)

    # This is deliberately enforced after every seed path. A new environment
    # must never inherit a local or deployment API key from process variables.
    from applications.models import StudioProvider

    if fresh:
        StudioProvider.query.update(
            {StudioProvider.api_key: None},
            synchronize_session=False,
        )
        db.session.commit()
