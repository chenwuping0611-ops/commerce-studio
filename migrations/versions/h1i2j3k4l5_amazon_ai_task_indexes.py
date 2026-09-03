"""add global Amazon AI task list indexes

Revision ID: h1i2j3k4l5
Revises: g0h1i2j3k4l5
Create Date: 2026-08-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "h1i2j3k4l5"
down_revision = "g0h1i2j3k4l5"
branch_labels = None
depends_on = None


TABLE = "amazon_ai_workspace_task"


def _has_table():
    return sa.inspect(op.get_bind()).has_table(TABLE)


def _index_names():
    return {
        index.get("name")
        for index in sa.inspect(op.get_bind()).get_indexes(TABLE)
    }


def upgrade():
    if not _has_table():
        return
    definitions = {
        "ix_amazon_ai_workspace_task_created_id": [
            "created_at",
            "id",
        ],
        "ix_amazon_ai_workspace_task_type_created_id": [
            "task_type",
            "created_at",
            "id",
        ],
        "ix_amazon_ai_workspace_task_type_status_finished": [
            "task_type",
            "status",
            "finished_at",
            "id",
        ],
    }
    existing = _index_names()
    for name, columns in definitions.items():
        if name not in existing:
            op.create_index(name, TABLE, columns)


def downgrade():
    if not _has_table():
        return
    existing = _index_names()
    for name in (
        "ix_amazon_ai_workspace_task_type_status_finished",
        "ix_amazon_ai_workspace_task_type_created_id",
        "ix_amazon_ai_workspace_task_created_id",
    ):
        if name in existing:
            op.drop_index(name, table_name=TABLE)
