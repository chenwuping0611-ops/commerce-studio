"""seed the built-in department administrator role

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


DEPARTMENT_ADMIN_POWER_CODES = (
    "admin:user:main",
    "admin:user:add",
    "admin:user:edit",
    "admin:user:remove",
    "admin:role:main",
    "admin:role:add",
    "admin:role:edit",
    "admin:role:remove",
    "admin:role:power",
    "admin:power:main",
    "admin:power:add",
    "admin:power:edit",
    "admin:power:remove",
    "admin:dept:main",
    "admin:dept:add",
    "admin:dept:edit",
    "admin:dept:remove",
    "admin:log:main",
    "studio:dashboard",
    "studio:image",
    "studio:video",
    "studio:products",
    "studio:skills",
    "studio:history",
    "studio:providers",
    "amazon_ai:root",
    "amazon_ai:dashboard",
    "amazon_ai:history",
    "amazon_ai:competitor",
    "amazon_ai:keyword",
    "amazon_ai:review",
    "amazon_ai:listing_create",
    "amazon_ai:listing_review",
)


def upgrade():
    connection = op.get_bind()
    role_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_role "
            "WHERE code = 'dept_admin' ORDER BY id LIMIT 1"
        )
    ).scalar()
    if role_id is None:
        connection.execute(
            sa.text(
                "INSERT INTO admin_role "
                "(name, code, enable, remark, details, sort, dept_id, created_by) "
                "VALUES "
                "(:name, :code, 1, :remark, :details, 5, NULL, NULL)"
            ),
            {
                "name": "部门管理员",
                "code": "dept_admin",
                "remark": "部门范围管理员",
                "details": "只能管理自己部门及下属部门的数据，不能访问其他部门的 Key",
            },
        )
        role_id = connection.execute(
            sa.text(
                "SELECT id FROM admin_role "
                "WHERE code = 'dept_admin' ORDER BY id DESC LIMIT 1"
            )
        ).scalar()
    else:
        connection.execute(
            sa.text(
                "UPDATE admin_role SET "
                "name = :name, enable = 1, remark = :remark, "
                "details = :details, dept_id = NULL, created_by = NULL "
                "WHERE id = :role_id"
            ),
            {
                "name": "部门管理员",
                "remark": "部门范围管理员",
                "details": "只能管理自己部门及下属部门的数据，不能访问其他部门的 Key",
                "role_id": role_id,
            },
        )

    if role_id is None:
        return

    connection.execute(
        sa.text("DELETE FROM admin_role_power WHERE role_id = :role_id"),
        {"role_id": role_id},
    )
    powers = connection.execute(
        sa.text(
            "SELECT id, code FROM admin_power "
            "WHERE enable = 1 AND code IN :codes"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": list(DEPARTMENT_ADMIN_POWER_CODES)},
    ).all()
    insert_power = sa.text(
        "INSERT INTO admin_role_power (power_id, role_id) "
        "VALUES (:power_id, :role_id)"
    )
    for power_id, _code in powers:
        connection.execute(
            insert_power,
            {"power_id": int(power_id), "role_id": int(role_id)},
        )


def downgrade():
    connection = op.get_bind()
    role_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_role "
            "WHERE code = 'dept_admin' ORDER BY id LIMIT 1"
        )
    ).scalar()
    if role_id is not None:
        connection.execute(
            sa.text("DELETE FROM admin_user_role WHERE role_id = :role_id"),
            {"role_id": role_id},
        )
        connection.execute(
            sa.text("DELETE FROM admin_role_power WHERE role_id = :role_id"),
            {"role_id": role_id},
        )
        connection.execute(
            sa.text("DELETE FROM admin_role WHERE id = :role_id"),
            {"role_id": role_id},
        )
