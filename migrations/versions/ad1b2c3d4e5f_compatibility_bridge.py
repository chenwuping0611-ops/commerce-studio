"""restore the migration node used by an older rolled-back deployment

Revision ID: ad1b2c3d4e5f
Revises: ac1b2c3d4e5f
Create Date: 2026-09-08 00:00:00.000000

The previous deployment recorded this revision in ``alembic_version`` but
the corresponding code revision was later rolled back from the repository.
This no-op node keeps existing databases upgradeable without recreating or
modifying any of the rolled-back schema changes.
"""


revision = "ad1b2c3d4e5f"
down_revision = "ac1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
