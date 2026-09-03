"""persist Amazon text results and two-part Listing fields

Revision ID: f6a7b8c9d0e1
Revises: e1f2a3b4c5d6
Create Date: 2026-08-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "c9d0e1f2a3b4"
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


def _add_column(table_name, column):
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def upgrade():
    _add_column(
        "amazon_ai_task",
        sa.Column("response_text", sa.Text(), nullable=True),
    )
    _add_column(
        "amazon_ai_task",
        sa.Column("response_sections_json", sa.Text(), nullable=True),
    )
    _add_column(
        "amazon_listing_version",
        sa.Column("item_name", sa.String(length=500), nullable=True),
    )
    _add_column(
        "amazon_listing_version",
        sa.Column("item_highlights", sa.String(length=500), nullable=True),
    )


def downgrade():
    if _has_table("amazon_listing_version") and _has_column(
        "amazon_listing_version",
        "item_highlights",
    ):
        op.drop_column("amazon_listing_version", "item_highlights")
    if _has_table("amazon_listing_version") and _has_column(
        "amazon_listing_version",
        "item_name",
    ):
        op.drop_column("amazon_listing_version", "item_name")
    if _has_table("amazon_ai_task") and _has_column(
        "amazon_ai_task",
        "response_sections_json",
    ):
        op.drop_column("amazon_ai_task", "response_sections_json")
    if _has_table("amazon_ai_task") and _has_column(
        "amazon_ai_task",
        "response_text",
    ):
        op.drop_column("amazon_ai_task", "response_text")
