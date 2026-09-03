"""allow canonical storage assets without duplicating their URL

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-08-31 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "s2t3u4v5w6x7"
down_revision = "r1s2t3u4v5w6"
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
    if _has_column("studio_product_asset", "url"):
        op.alter_column(
            "studio_product_asset",
            "url",
            existing_type=sa.String(length=1000),
            nullable=True,
        )


def downgrade():
    if not _has_column("studio_product_asset", "url"):
        return
    # Older schemas require a URL. Preserve existing external URLs and leave
    # a harmless empty value for canonical storage rows during a downgrade.
    op.execute(
        sa.text(
            "UPDATE studio_product_asset "
            "SET url = COALESCE(NULLIF(url, ''), external_url, '') "
            "WHERE url IS NULL"
        )
    )
    op.alter_column(
        "studio_product_asset",
        "url",
        existing_type=sa.String(length=1000),
        nullable=False,
    )
