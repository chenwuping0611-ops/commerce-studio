"""remove duplicated Skill bodies when a canonical file is available

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-02 00:00:00.000000

Skill instructions are stored as permanent GoFastDFS files. Keep only the
metadata and storage_asset_id in MySQL when the linked file is active.
"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return column_name in {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade():
    if not all(
        (
            _has_table("studio_skill"),
            _has_table("studio_asset"),
            _has_column("studio_skill", "storage_asset_id"),
            _has_column("studio_skill", "content"),
            _has_column("studio_skill", "prompt_template"),
            _has_column("studio_asset", "purpose"),
            _has_column("studio_asset", "status"),
        )
    ):
        return

    op.execute(
        sa.text(
            "UPDATE studio_skill "
            "SET content = NULL, prompt_template = NULL "
            "WHERE storage_asset_id IS NOT NULL "
            "AND EXISTS ("
            "    SELECT 1 "
            "    FROM studio_asset "
            "    WHERE studio_asset.id = studio_skill.storage_asset_id "
            "      AND studio_asset.purpose = 'SKILL' "
            "      AND studio_asset.status = 'ACTIVE' "
            "      AND ("
            "          studio_asset.expires_at IS NULL "
            "          OR studio_asset.expires_at > CURRENT_TIMESTAMP"
            "      )"
            ")"
        )
    )


def downgrade():
    # The previous bodies cannot be reconstructed safely from a file without
    # reintroducing duplicate or stale text into MySQL.
    pass
