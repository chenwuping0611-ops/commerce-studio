"""add log department snapshots and provider ownership

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-08-28 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "m6n7o8p9q0r1"
down_revision = "l5m6n7o8p9q0"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _has_column(table_name, column_name):
    return _has_table(table_name) and any(
        column["name"] == column_name
        for column in _inspector().get_columns(table_name)
    )


def _has_index(table_name, index_name):
    return any(
        index.get("name") == index_name
        for index in _inspector().get_indexes(table_name)
    )


def upgrade():
    if _has_table("admin_admin_log") and not _has_column(
        "admin_admin_log",
        "dept_id",
    ):
        op.add_column(
            "admin_admin_log",
            sa.Column(
                "dept_id",
                sa.Integer(),
                nullable=True,
                comment="操作人部门快照",
            ),
        )

    connection = op.get_bind()
    if (
        _has_table("admin_admin_log")
        and _has_column("admin_admin_log", "dept_id")
        and _has_table("admin_user")
    ):
        connection.execute(
            sa.text(
                "UPDATE admin_admin_log log_item "
                "JOIN admin_user owner_user "
                "ON owner_user.id = log_item.uid "
                "SET log_item.dept_id = owner_user.dept_id "
                "WHERE log_item.dept_id IS NULL "
                "AND owner_user.dept_id IS NOT NULL"
            )
        )

    if (
        _has_table("admin_admin_log")
        and _has_column("admin_admin_log", "dept_id")
        and not _has_index(
            "admin_admin_log",
            "ix_admin_admin_log_dept_id",
        )
    ):
        op.create_index(
            "ix_admin_admin_log_dept_id",
            "admin_admin_log",
            ["dept_id"],
        )

    if _has_table("studio_provider") and not _has_column(
        "studio_provider",
        "owner_type",
    ):
        op.add_column(
            "studio_provider",
            sa.Column(
                "owner_type",
                sa.String(length=20),
                nullable=False,
                server_default="DEPARTMENT",
                comment="供应商所有权：DEPARTMENT 或 SUPER_ADMIN",
            ),
        )

    if _has_table("studio_provider") and _has_column(
        "studio_provider",
        "owner_type",
    ):
        connection.execute(
            sa.text(
                "UPDATE studio_provider "
                "SET owner_type = 'DEPARTMENT' "
                "WHERE owner_type IS NULL OR owner_type = ''"
            )
        )
        if not _has_index(
            "studio_provider",
            "ix_studio_provider_owner_scope",
        ):
            op.create_index(
                "ix_studio_provider_owner_scope",
                "studio_provider",
                ["owner_type", "dept_id", "enabled", "id"],
            )


def downgrade():
    if _has_table("studio_provider") and _has_index(
        "studio_provider",
        "ix_studio_provider_owner_scope",
    ):
        op.drop_index(
            "ix_studio_provider_owner_scope",
            table_name="studio_provider",
        )
    if _has_table("studio_provider") and _has_column(
        "studio_provider",
        "owner_type",
    ):
        op.drop_column("studio_provider", "owner_type")

    if _has_table("admin_admin_log") and _has_index(
        "admin_admin_log",
        "ix_admin_admin_log_dept_id",
    ):
        op.drop_index(
            "ix_admin_admin_log_dept_id",
            table_name="admin_admin_log",
        )
    if _has_table("admin_admin_log") and _has_column(
        "admin_admin_log",
        "dept_id",
    ):
        op.drop_column("admin_admin_log", "dept_id")
