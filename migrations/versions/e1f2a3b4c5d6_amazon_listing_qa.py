"""add QA output to Amazon Listing versions

Revision ID: e1f2a3b4c5d6
Revises: c2d4e6f8a0b1
Create Date: 2026-08-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d6"
down_revision = "c2d4e6f8a0b1"
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
    if _has_table("amazon_listing_version") and not _has_column(
        "amazon_listing_version",
        "qa_json",
    ):
        op.add_column(
            "amazon_listing_version",
            sa.Column("qa_json", sa.Text(), nullable=True),
        )


def downgrade():
    if _has_table("amazon_listing_version") and _has_column(
        "amazon_listing_version",
        "qa_json",
    ):
        op.drop_column("amazon_listing_version", "qa_json")
