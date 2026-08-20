"""store product update suggestions from image analysis

Revision ID: 9e8b7c6d5a4f
Revises: f17a6c5e8d42
Create Date: 2026-08-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9e8b7c6d5a4f"
down_revision = "f17a6c5e8d42"
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
    if not _has_table("studio_generation_comment"):
        return

    columns = (
        ("suggested_updates", sa.Text()),
        ("applied_update_fields", sa.Text()),
        ("applied_at", sa.DateTime()),
        ("applied_by", sa.Integer()),
    )
    for name, column_type in columns:
        if not _has_column("studio_generation_comment", name):
            op.add_column(
                "studio_generation_comment",
                sa.Column(name, column_type, nullable=True),
            )


def downgrade():
    if not _has_table("studio_generation_comment"):
        return
    for name in ("applied_by", "applied_at", "applied_update_fields", "suggested_updates"):
        if _has_column("studio_generation_comment", name):
            op.drop_column("studio_generation_comment", name)
