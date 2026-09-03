"""store the selected image aspect ratio on batch prompt histories

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-09-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_batch_prompt"
COLUMN_NAME = "image_aspect_ratio"
DEFAULT_VALUE = "2.44:1"


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
                sa.String(length=20),
                nullable=True,
                server_default=DEFAULT_VALUE,
            ),
        )
    op.execute(
        sa.text(
            f"UPDATE {TABLE_NAME} "
            f"SET {COLUMN_NAME} = :default_value "
            f"WHERE {COLUMN_NAME} IS NULL OR {COLUMN_NAME} = ''"
        ).bindparams(default_value=DEFAULT_VALUE)
    )
    try:
        op.alter_column(
            TABLE_NAME,
            COLUMN_NAME,
            server_default=None,
            existing_type=sa.String(length=20),
        )
    except Exception:
        # Keep the additive migration compatible with older MySQL variants.
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
