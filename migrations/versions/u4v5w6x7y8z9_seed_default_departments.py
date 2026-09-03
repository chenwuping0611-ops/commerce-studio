"""seed the default organization departments and bind admin

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-08-31 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "u4v5w6x7y8z9"
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def _root(connection):
    return connection.execute(
        sa.text(
            "SELECT id FROM admin_dept "
            "WHERE dept_name = :name AND (parent_id = 0 OR parent_id IS NULL) "
            "ORDER BY id LIMIT 1"
        ),
        {"name": "总项目"},
    ).scalar()


def _find_department(connection, name):
    return connection.execute(
        sa.text(
            "SELECT id FROM admin_dept "
            "WHERE dept_name = :name ORDER BY id LIMIT 1"
        ),
        {"name": name},
    ).scalar()


def _ensure_department(connection, name, parent_id, sort):
    department_id = _find_department(connection, name)
    if department_id is None:
        department_id = connection.execute(
            sa.text(
                "INSERT INTO admin_dept "
                "(parent_id, dept_name, sort, leader, status) "
                "VALUES (:parent_id, :dept_name, :sort, '', 1)"
            ),
            {
                "parent_id": parent_id,
                "dept_name": name,
                "sort": sort,
            },
        ).lastrowid
    else:
        connection.execute(
            sa.text(
                "UPDATE admin_dept SET parent_id = :parent_id, "
                "sort = COALESCE(sort, :sort), status = COALESCE(status, 1) "
                "WHERE id = :department_id"
            ),
            {
                "parent_id": parent_id,
                "sort": sort,
                "department_id": department_id,
            },
        )
    return department_id


def upgrade():
    connection = op.get_bind()
    root_id = _root(connection)
    if root_id is None:
        # Preserve the primary key and all ownership references from the
        # legacy deployment that used ``三部五组`` as its root.
        legacy_root_id = connection.execute(
            sa.text(
                "SELECT id FROM admin_dept "
                "WHERE dept_name = :name "
                "AND (parent_id = 0 OR parent_id IS NULL) "
                "ORDER BY id LIMIT 1"
            ),
            {"name": "三部五组"},
        ).scalar()
        if legacy_root_id is not None:
            root_id = legacy_root_id
            connection.execute(
                sa.text(
                    "UPDATE admin_dept SET dept_name = '总项目', "
                    "parent_id = 0, sort = 0, status = COALESCE(status, 1) "
                    "WHERE id = :root_id"
                ),
                {"root_id": root_id},
            )
        else:
            root_id = connection.execute(
                sa.text(
                    "INSERT INTO admin_dept "
                    "(parent_id, dept_name, sort, leader, status) "
                    "VALUES (0, '总项目', 0, '', 1)"
                )
            ).lastrowid
    else:
        connection.execute(
            sa.text(
                "UPDATE admin_dept SET parent_id = 0, sort = 0, "
                "status = COALESCE(status, 1) WHERE id = :root_id"
            ),
            {"root_id": root_id},
        )

    _ensure_department(connection, "三部五组", root_id, 10)
    _ensure_department(connection, "三部二组", root_id, 20)

    connection.execute(
        sa.text(
            "UPDATE admin_user SET dept_id = :root_id "
            "WHERE username = 'admin'"
        ),
        {"root_id": root_id},
    )


def downgrade():
    # These are deployment defaults, not disposable business rows. Keep them
    # during downgrade so ownership references and existing users remain safe.
    pass
