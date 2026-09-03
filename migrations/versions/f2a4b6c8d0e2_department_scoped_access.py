"""add department-scoped RBAC and Studio provider routing

Revision ID: f2a4b6c8d0e2
Revises: e1f2a3b4c5d6
Create Date: 2026-08-25 00:00:00.000000
"""

import os

from alembic import op
import sqlalchemy as sa


revision = "f2a4b6c8d0e2"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


SCOPED_COLUMNS = {
    "admin_role": (
        ("dept_id", sa.Integer()),
        ("created_by", sa.Integer()),
    ),
    "admin_power": (
        ("dept_id", sa.Integer()),
        ("created_by", sa.Integer()),
    ),
    "studio_setting": (("dept_id", sa.Integer()),),
    "studio_provider": (("dept_id", sa.Integer()),),
    "studio_product": (("dept_id", sa.Integer()),),
    "studio_skill": (("dept_id", sa.Integer()),),
    "studio_generation_task": (("dept_id", sa.Integer()),),
    "studio_asset": (("dept_id", sa.Integer()),),
}


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return any(
        column["name"] == column_name
        for column in _inspector().get_columns(table_name)
    )


def _default_department_id(connection):
    preferred_name = os.getenv("STUDIO_DEFAULT_DEPT_NAME", "三部五组")
    row = connection.execute(
        sa.text(
            "SELECT id FROM admin_dept "
            "WHERE dept_name = :name "
            "ORDER BY id LIMIT 1"
        ),
        {"name": preferred_name},
    ).first()
    if row:
        return row[0]
    row = connection.execute(
        sa.text(
            "SELECT id FROM admin_dept "
            "WHERE parent_id = 0 OR parent_id IS NULL "
            "ORDER BY sort, id LIMIT 1"
        )
    ).first()
    return row[0] if row else None


def _add_columns():
    for table_name, columns in SCOPED_COLUMNS.items():
        if not _has_table(table_name):
            continue
        for column_name, column_type in columns:
            if not _has_column(table_name, column_name):
                op.add_column(
                    table_name,
                    sa.Column(column_name, column_type, nullable=True),
                )


def _drop_legacy_setting_unique_constraint():
    if not _has_table("studio_setting"):
        return
    inspector = _inspector()
    for constraint in inspector.get_unique_constraints("studio_setting"):
        columns = tuple(constraint.get("column_names") or ())
        if columns == ("setting_key",) and constraint.get("name"):
            op.drop_constraint(
                constraint["name"],
                "studio_setting",
                type_="unique",
            )
    # MySQL exposes a single-column UNIQUE constraint both as a constraint
    # and, on some connector versions, as a synthetic index.  The synthetic
    # index can disappear after the preceding column DDL, so dropping it
    # independently produces a false "can't drop index" error.  The
    # constraint branch above is the only required operation; the next
    # composite constraint supersedes the legacy uniqueness.


def _has_unique_scope_constraint():
    if not _has_table("studio_setting"):
        return False
    target = {"setting_key", "dept_id"}
    for constraint in _inspector().get_unique_constraints("studio_setting"):
        if set(constraint.get("column_names") or ()) == target:
            return True
    for index in _inspector().get_indexes("studio_setting"):
        if index.get("unique") and set(index.get("column_names") or ()) == target:
            return True
    return False


def _backfill_scope(connection, default_department_id):
    if default_department_id is None:
        return

    if _has_table("admin_user") and _has_column("admin_user", "dept_id"):
        connection.execute(
            sa.text(
                "UPDATE admin_user SET dept_id = :dept_id "
                "WHERE dept_id IS NULL"
            ),
            {"dept_id": default_department_id},
        )

    for table_name in (
        "studio_provider",
        "studio_product",
        "studio_skill",
        "studio_generation_task",
        "studio_asset",
    ):
        if not _has_table(table_name) or not _has_column(table_name, "dept_id"):
            continue
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET dept_id = :dept_id "
                "WHERE dept_id IS NULL"
            ),
            {"dept_id": default_department_id},
        )

    if _has_table("studio_setting") and _has_column("studio_setting", "dept_id"):
        connection.execute(
            sa.text(
                "UPDATE studio_setting SET dept_id = :dept_id "
                "WHERE dept_id IS NULL"
            ),
            {"dept_id": default_department_id},
        )


def upgrade():
    _add_columns()
    connection = op.get_bind()
    default_department_id = _default_department_id(connection)
    _backfill_scope(connection, default_department_id)
    _drop_legacy_setting_unique_constraint()
    if _has_table("studio_setting") and not _has_unique_scope_constraint():
        op.create_unique_constraint(
            "uq_studio_setting_key_dept",
            "studio_setting",
            ["setting_key", "dept_id"],
        )

    inspector = _inspector()
    for table_name in SCOPED_COLUMNS:
        if not _has_table(table_name) or not _has_column(table_name, "dept_id"):
            continue
        index_name = f"ix_{table_name}_dept_id"
        existing = {
            index.get("name") for index in inspector.get_indexes(table_name)
        }
        if index_name not in existing:
            op.create_index(index_name, table_name, ["dept_id"])


def downgrade():
    if _has_table("studio_setting"):
        for constraint in _inspector().get_unique_constraints("studio_setting"):
            if set(constraint.get("column_names") or ()) == {
                "setting_key",
                "dept_id",
            }:
                if constraint.get("name"):
                    op.drop_constraint(
                        constraint["name"],
                        "studio_setting",
                        type_="unique",
                    )
        if not any(
            tuple(index.get("column_names") or ()) == ("setting_key",)
            and index.get("unique")
            for index in _inspector().get_indexes("studio_setting")
        ):
            op.create_unique_constraint(
                "uq_studio_setting_key_legacy",
                "studio_setting",
                ["setting_key"],
            )

    for table_name in reversed(tuple(SCOPED_COLUMNS)):
        if not _has_table(table_name) or not _has_column(table_name, "dept_id"):
            continue
        index_name = f"ix_{table_name}_dept_id"
        if any(
            index.get("name") == index_name
            for index in _inspector().get_indexes(table_name)
        ):
            op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, "dept_id")
        if table_name in ("admin_role", "admin_power") and _has_column(
            table_name,
            "created_by",
        ):
            op.drop_column(table_name, "created_by")
