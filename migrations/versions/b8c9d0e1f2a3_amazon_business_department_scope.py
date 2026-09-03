"""add department ownership to Amazon business records

Revision ID: b8c9d0e1f2a3
Revises: a6b7c8d9e0f1
Create Date: 2026-08-25 00:00:00.000000
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


SCOPED_TABLES = (
    "amazon_listing_project",
    "amazon_competitor",
    "amazon_keyword",
    "amazon_review",
    "amazon_listing_version",
    "amazon_listing_audit",
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _has_column(table_name, column_name):
    return _has_table(table_name) and any(
        column["name"] == column_name
        for column in _inspector().get_columns(table_name)
    )


def _default_department_id(connection):
    preferred_name = os.getenv("STUDIO_DEFAULT_DEPT_NAME", "三部五组")
    row = connection.execute(
        sa.text(
            "SELECT id FROM admin_dept "
            "WHERE dept_name = :name ORDER BY id LIMIT 1"
        ),
        {"name": preferred_name},
    ).first()
    if row:
        return row[0]
    row = connection.execute(
        sa.text(
            "SELECT id FROM admin_dept "
            "WHERE parent_id = 0 OR parent_id IS NULL "
            "ORDER BY sort, id LIMIT 1"
        )
    ).first()
    return row[0] if row else None


def _add_columns():
    for table_name in SCOPED_TABLES:
        if _has_table(table_name) and not _has_column(table_name, "dept_id"):
            op.add_column(
                table_name,
                sa.Column("dept_id", sa.Integer(), nullable=True),
            )


def _backfill_scope(connection, default_department_id):
    if _has_table("amazon_listing_project"):
        connection.execute(
            sa.text(
                "UPDATE amazon_listing_project project "
                "LEFT JOIN admin_user owner_user "
                "ON owner_user.id = project.owner_id "
                "SET project.dept_id = owner_user.dept_id "
                "WHERE project.dept_id IS NULL "
                "AND owner_user.dept_id IS NOT NULL"
            )
        )

    for table_name in (
        "amazon_competitor",
        "amazon_keyword",
        "amazon_review",
        "amazon_listing_version",
        "amazon_listing_audit",
    ):
        if not _has_table(table_name):
            continue
        connection.execute(
            sa.text(
                f"UPDATE {table_name} item "
                "JOIN amazon_listing_project project "
                "ON project.id = item.listing_project_id "
                "SET item.dept_id = project.dept_id "
                "WHERE item.dept_id IS NULL "
                "AND project.dept_id IS NOT NULL"
            )
        )

    # Standalone analysis rows can still be linked to a task even without a
    # Listing project. Use that task's department before the default fallback.
    for table_name, target_column in (
        ("amazon_competitor", "competitor_id"),
        ("amazon_keyword", "keyword_id"),
        ("amazon_review", "review_id"),
    ):
        if not _has_table(table_name):
            continue
        connection.execute(
            sa.text(
                f"UPDATE {table_name} item "
                "JOIN amazon_ai_task_target target "
                f"ON target.{target_column} = item.id "
                "JOIN amazon_ai_task task ON task.id = target.task_id "
                "SET item.dept_id = task.dept_id "
                "WHERE item.dept_id IS NULL "
                "AND task.dept_id IS NOT NULL"
            )
        )

    if default_department_id is None:
        return
    for table_name in SCOPED_TABLES:
        if _has_table(table_name):
            connection.execute(
                sa.text(
                    f"UPDATE {table_name} SET dept_id = :dept_id "
                    "WHERE dept_id IS NULL"
                ),
                {"dept_id": default_department_id},
            )


def _add_indexes():
    inspector = _inspector()
    for table_name in SCOPED_TABLES:
        if not _has_table(table_name) or not _has_column(table_name, "dept_id"):
            continue
        index_name = f"ix_{table_name}_dept_id"
        if not any(
            index.get("name") == index_name
            for index in inspector.get_indexes(table_name)
        ):
            op.create_index(index_name, table_name, ["dept_id"])


def upgrade():
    _add_columns()
    connection = op.get_bind()
    _backfill_scope(connection, _default_department_id(connection))
    _add_indexes()


def downgrade():
    for table_name in reversed(SCOPED_TABLES):
        if not _has_table(table_name) or not _has_column(table_name, "dept_id"):
            continue
        index_name = f"ix_{table_name}_dept_id"
        if any(
            index.get("name") == index_name
            for index in _inspector().get_indexes(table_name)
        ):
            op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, "dept_id")
