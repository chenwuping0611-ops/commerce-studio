"""add dynamic batch prompt style options

Revision ID: ad2b3c4d5e6f
Revises: ac1b2c3d4e5f
Create Date: 2026-09-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ad2b3c4d5e6f"
down_revision = "ad1b2c3d4e5f"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_batch_prompt_style"
DEFAULT_STYLES = (
    "专业电商详情图",
    "高端商业摄影",
    "简约现代",
    "生活方式场景",
    "科技产品广告",
)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        op.create_table(
            TABLE_NAME,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "name",
                name="uq_studio_batch_prompt_style_name",
            ),
        )

    style_table = sa.table(
        TABLE_NAME,
        sa.column("name", sa.String(length=160)),
        sa.column("sort", sa.Integer()),
    )
    connection = op.get_bind()
    existing = {
        row[0]
        for row in connection.execute(
            sa.select(style_table.c.name)
        ).fetchall()
    }
    rows = [
        {"name": name, "sort": index}
        for index, name in enumerate(DEFAULT_STYLES, start=1)
        if name not in existing
    ]
    if rows:
        op.bulk_insert(style_table, rows)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE_NAME):
        op.drop_table(TABLE_NAME)
