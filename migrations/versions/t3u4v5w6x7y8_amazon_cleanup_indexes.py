"""improve Amazon AI cleanup index selectivity

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-08-31 13:05:00.000000

The cleanup query now separates explicit expiry from the legacy created_at
fallback. Include terminal status in the existing expiry index so the
explicit-expiry path can discard active work earlier.
"""

from alembic import op
import sqlalchemy as sa


revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


TABLE_NAME = "amazon_ai_workspace_task"
INDEX_NAME = "ix_amazon_ai_workspace_task_retention_expiry"
INDEX_COLUMNS = [
    "retention_policy",
    "status",
    "storage_cleanup_status",
    "expires_at",
    "id",
]
LEGACY_INDEX_COLUMNS = [
    "retention_policy",
    "storage_cleanup_status",
    "expires_at",
    "id",
]


def _index_columns(index_name):
    inspector = sa.inspect(op.get_bind())
    for item in inspector.get_indexes(TABLE_NAME):
        if item.get("name") == index_name:
            return list(item.get("column_names") or ())
    return None


def _replace_index(columns):
    current = _index_columns(INDEX_NAME)
    if current == columns:
        return
    if current is not None:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.create_index(INDEX_NAME, TABLE_NAME, columns)


def upgrade():
    if sa.inspect(op.get_bind()).has_table(TABLE_NAME):
        _replace_index(INDEX_COLUMNS)


def downgrade():
    if sa.inspect(op.get_bind()).has_table(TABLE_NAME):
        _replace_index(LEGACY_INDEX_COLUMNS)
