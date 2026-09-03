"""allow Listing versions without a Listing project

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade():
    if _has_table("amazon_listing_version"):
        op.alter_column(
            "amazon_listing_version",
            "listing_project_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade():
    if _has_table("amazon_listing_version"):
        op.alter_column(
            "amazon_listing_version",
            "listing_project_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
