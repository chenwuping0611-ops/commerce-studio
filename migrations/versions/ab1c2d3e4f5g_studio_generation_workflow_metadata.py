"""persist generation workflow metadata

Revision ID: ab1c2d3e4f5g
Revises: aa1b2c3d4e5f
Create Date: 2026-09-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ab1c2d3e4f5g"
down_revision = "aa1b2c3d4e5f"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_generation_task"
COLUMN_NAME = "workflow_metadata"


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
            sa.Column(COLUMN_NAME, sa.Text(), nullable=True),
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
