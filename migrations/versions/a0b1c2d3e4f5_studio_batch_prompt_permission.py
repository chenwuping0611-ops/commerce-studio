"""add the independent batch prompt workspace menu

Revision ID: a0b1c2d3e4f5
Revises: z9a0b1c2d3e4
Create Date: 2026-09-02 12:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a0b1c2d3e4f5"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


POWER_CODE = "studio:batch_prompts"
POWER_NAME = "批量创作提示词"
POWER_URL = "/studio/batch-prompts"
POWER_ICON = "layui-icon layui-icon-edit"
STUDIO_ROOT_CODE = "studio:root"
ROLE_CODES = ("studio_user", "dept_admin")


def upgrade():
    connection = op.get_bind()
    power_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_power "
            "WHERE code = :code ORDER BY id LIMIT 1"
        ),
        {"code": POWER_CODE},
    ).scalar()
    if power_id is None:
        parent_id = connection.execute(
            sa.text(
                "SELECT id FROM admin_power "
                "WHERE code = :code ORDER BY id LIMIT 1"
            ),
            {"code": STUDIO_ROOT_CODE},
        ).scalar()
        if parent_id is None:
            parent_id = 0
        connection.execute(
            sa.text(
                "INSERT INTO admin_power "
                "(name, type, code, url, open_type, parent_id, icon, sort, "
                "enable, dept_id, created_by) "
                "VALUES (:name, '1', :code, :url, '_iframe', :parent_id, "
                ":icon, 4, 1, NULL, NULL)"
            ),
            {
                "name": POWER_NAME,
                "code": POWER_CODE,
                "url": POWER_URL,
                "parent_id": parent_id,
                "icon": POWER_ICON,
            },
        )
        power_id = connection.execute(
            sa.text(
                "SELECT id FROM admin_power "
                "WHERE code = :code ORDER BY id LIMIT 1"
            ),
            {"code": POWER_CODE},
        ).scalar()
    if power_id is None:
        return

    for role_code in ROLE_CODES:
        role_id = connection.execute(
            sa.text(
                "SELECT id FROM admin_role "
                "WHERE code = :code ORDER BY id LIMIT 1"
            ),
            {"code": role_code},
        ).scalar()
        if role_id is None:
            continue
        relation_exists = connection.execute(
            sa.text(
                "SELECT 1 FROM admin_role_power "
                "WHERE role_id = :role_id AND power_id = :power_id LIMIT 1"
            ),
            {"role_id": role_id, "power_id": power_id},
        ).first()
        if relation_exists is None:
            connection.execute(
                sa.text(
                    "INSERT INTO admin_role_power (power_id, role_id) "
                    "VALUES (:power_id, :role_id)"
                ),
                {"role_id": role_id, "power_id": power_id},
            )


def downgrade():
    connection = op.get_bind()
    power_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_power "
            "WHERE code = :code ORDER BY id LIMIT 1"
        ),
        {"code": POWER_CODE},
    ).scalar()
    if power_id is None:
        return
    connection.execute(
        sa.text(
            "DELETE FROM admin_role_power WHERE power_id = :power_id"
        ),
        {"power_id": power_id},
    )
    connection.execute(
        sa.text("DELETE FROM admin_power WHERE id = :power_id"),
        {"power_id": power_id},
    )
