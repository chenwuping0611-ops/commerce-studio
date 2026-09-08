"""add editable display names to batch prompt histories

Revision ID: aa1b2c3d4e5f
Revises: e5f6a7b8c9d0
Create Date: 2026-09-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "aa1b2c3d4e5f"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_batch_prompt"
COLUMN_NAME = "name"
DEFAULT_NAME = "批量提示词"


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
                sa.String(length=160),
                nullable=True,
            ),
        )

    batch_prompt_table = sa.table(
        TABLE_NAME,
        sa.column(COLUMN_NAME, sa.String(length=160)),
    )
    op.get_bind().execute(
        batch_prompt_table.update()
        .where(
            sa.or_(
                batch_prompt_table.c.name.is_(None),
                sa.func.trim(batch_prompt_table.c.name) == "",
            )
        )
        .values(name=DEFAULT_NAME)
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
