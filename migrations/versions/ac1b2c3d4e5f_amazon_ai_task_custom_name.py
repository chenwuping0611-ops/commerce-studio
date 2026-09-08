"""add editable names to Amazon AI analysis tasks

Revision ID: ac1b2c3d4e5f
Revises: ab1c2d3e4f5g
Create Date: 2026-09-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ac1b2c3d4e5f"
down_revision = "ab1c2d3e4f5g"
branch_labels = None
depends_on = None


TABLE_NAME = "amazon_ai_workspace_task"
COLUMN_NAME = "custom_name"


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
                comment="用户自定义任务名称",
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
