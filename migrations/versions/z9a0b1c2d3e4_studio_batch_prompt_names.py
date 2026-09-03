"""add stable batch prompt file names and run numbers

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
Create Date: 2026-09-02 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "z9a0b1c2d3e4"
down_revision = "y8z9a0b1c2d3"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_batch_prompt"
INDEX_NAME = "ix_studio_batch_prompt_product_run"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        return

    columns = {
        column["name"]
        for column in inspector.get_columns(TABLE_NAME)
    }
    if "file_name" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("file_name", sa.String(length=255), nullable=True),
        )
    if "run_number" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("run_number", sa.Integer(), nullable=True),
        )

    indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(TABLE_NAME)
    }
    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            TABLE_NAME,
            ["product_id", "run_number"],
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        return

    indexes = {
        index["name"]
        for index in inspector.get_indexes(TABLE_NAME)
    }
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)

    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(TABLE_NAME)
    }
    if "run_number" in columns:
        op.drop_column(TABLE_NAME, "run_number")
    if "file_name" in columns:
        op.drop_column(TABLE_NAME, "file_name")
