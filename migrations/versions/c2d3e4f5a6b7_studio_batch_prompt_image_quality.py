"""store the selected image quality on batch prompt histories

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_batch_prompt"
COLUMN_NAME = "image_resolution"


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
                sa.String(length=10),
                nullable=True,
                server_default="2k",
            ),
        )
    op.execute(
        sa.text(
            f"UPDATE {TABLE_NAME} "
            f"SET {COLUMN_NAME} = '2k' "
            f"WHERE {COLUMN_NAME} IS NULL OR {COLUMN_NAME} = ''"
        )
    )
    # Keep the default in application code so future writes remain explicit.
    try:
        op.alter_column(
            TABLE_NAME,
            COLUMN_NAME,
            server_default=None,
            existing_type=sa.String(length=10),
        )
    except Exception:
        # Some older MySQL variants do not accept removing a default during
        # an additive migration. The persisted value is already normalized.
        pass


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
