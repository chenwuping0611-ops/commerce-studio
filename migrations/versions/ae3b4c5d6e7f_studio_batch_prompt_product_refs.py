"""save product-center image references on batch prompt histories

Revision ID: ae3b4c5d6e7f
Revises: ad2b3c4d5e6f
Create Date: 2026-09-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ae3b4c5d6e7f"
down_revision = "ad2b3c4d5e6f"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_batch_prompt"
COLUMN_NAME = "product_reference_images_snapshot"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        return
    columns = {
        column["name"]
        for column in inspector.get_columns(TABLE_NAME)
    }
    if COLUMN_NAME not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column(
                COLUMN_NAME,
                sa.Text(),
                nullable=True,
                comment="创建批量提示词时使用的产品中心图片 URL 快照",
            ),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        return
    columns = {
        column["name"]
        for column in inspector.get_columns(TABLE_NAME)
    }
    if COLUMN_NAME in columns:
        op.drop_column(TABLE_NAME, COLUMN_NAME)
