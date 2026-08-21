"""add persistent Studio system settings

Revision ID: a1b2c3d4e5f6
Revises: 9e8b7c6d5a4f
Create Date: 2026-08-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "9e8b7c6d5a4f"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade():
    if _has_table("studio_setting"):
        return
    op.create_table(
        "studio_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setting_key", sa.String(length=120), nullable=False),
        sa.Column("setting_value", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setting_key"),
    )


def downgrade():
    if _has_table("studio_setting"):
        op.drop_table("studio_setting")
