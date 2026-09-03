"""store Skill snapshots on generation tasks

Revision ID: b7c9d1e2f3a4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7c9d1e2f3a4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def upgrade():
    if not _has_table("studio_generation_task"):
        return
    columns = (
        ("skill_id", sa.Integer()),
        ("skill_name", sa.String(length=160)),
        ("skill_prompt", sa.Text()),
    )
    for name, column_type in columns:
        if not _has_column("studio_generation_task", name):
            op.add_column(
                "studio_generation_task",
                sa.Column(name, column_type, nullable=True),
            )


def downgrade():
    if not _has_table("studio_generation_task"):
        return
    for name in ("skill_prompt", "skill_name", "skill_id"):
        if _has_column("studio_generation_task", name):
            op.drop_column("studio_generation_task", name)
