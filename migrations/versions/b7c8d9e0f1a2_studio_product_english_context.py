"""store translated English product constraints

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
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
    if _has_table("studio_product") and not _has_column(
        "studio_product", "english_context"
    ):
        op.add_column(
            "studio_product",
            sa.Column("english_context", sa.Text(), nullable=True),
        )


def downgrade():
    if _has_table("studio_product") and _has_column(
        "studio_product", "english_context"
    ):
        op.drop_column("studio_product", "english_context")
