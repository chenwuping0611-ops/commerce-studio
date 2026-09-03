"""scope Amazon AI execution tasks by department

Revision ID: a6b7c8d9e0f1
Revises: f2a4b6c8d0e2
Create Date: 2026-08-25 00:00:00.000000
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f1"
down_revision = "f2a4b6c8d0e2"
branch_labels = None
depends_on = None


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    ) if inspector.has_table(table_name) else False


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


def upgrade():
    if not _has_column("amazon_ai_task", "dept_id"):
        op.add_column(
            "amazon_ai_task",
            sa.Column("dept_id", sa.Integer(), nullable=True),
        )
    connection = op.get_bind()
    department_id = _default_department_id(connection)
    if department_id is not None:
        connection.execute(
            sa.text(
                "UPDATE amazon_ai_task SET dept_id = :dept_id "
                "WHERE dept_id IS NULL"
            ),
            {"dept_id": department_id},
        )
    inspector = sa.inspect(connection)
    index_name = "ix_amazon_ai_task_dept_id"
    if not any(
        index.get("name") == index_name
        for index in inspector.get_indexes("amazon_ai_task")
    ):
        op.create_index(index_name, "amazon_ai_task", ["dept_id"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("amazon_ai_task"):
        return
    if any(
        index.get("name") == "ix_amazon_ai_task_dept_id"
        for index in inspector.get_indexes("amazon_ai_task")
    ):
        op.drop_index("ix_amazon_ai_task_dept_id", table_name="amazon_ai_task")
    if _has_column("amazon_ai_task", "dept_id"):
        op.drop_column("amazon_ai_task", "dept_id")
