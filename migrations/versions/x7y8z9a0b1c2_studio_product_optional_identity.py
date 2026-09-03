"""allow Listing-derived products to keep unknown identity fields empty

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0
Create Date: 2026-09-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "x7y8z9a0b1c2"
down_revision = "w6x7y8z9a0"
branch_labels = None
depends_on = None


def _columns(table_name):
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return {}
    return {
        column["name"]: column
        for column in inspector.get_columns(table_name)
    }


def upgrade():
    columns = _columns("studio_product")
    code = columns.get("code")
    if code and not code.get("nullable", True):
        op.alter_column(
            "studio_product",
            "code",
            existing_type=sa.String(length=80),
            existing_nullable=False,
            nullable=True,
        )

    name = columns.get("name")
    if name and not name.get("nullable", True):
        op.alter_column(
            "studio_product",
            "name",
            existing_type=sa.String(length=160),
            existing_nullable=False,
            nullable=True,
        )


def downgrade():
    # Existing rows may legitimately contain an unknown identity. Do not
    # make a downgrade fail by converting those values to arbitrary text.
    pass
