"""add Amazon AI core selling points to Studio products

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-08-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "l5m6n7o8p9q0"
down_revision = "k4l5m6n7o8p9"
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
        "studio_product",
        "core_selling_points",
    ):
        op.add_column(
            "studio_product",
            sa.Column(
                "core_selling_points",
                sa.Text(),
                nullable=True,
                comment="Amazon AI 基础信息修正后确认的核心卖点",
            ),
        )


def downgrade():
    if _has_table("studio_product") and _has_column(
        "studio_product",
        "core_selling_points",
    ):
        op.drop_column("studio_product", "core_selling_points")
