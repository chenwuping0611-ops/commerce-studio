"""attach menu roots to the built-in department administrator role

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-08-28 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "n7o8p9q0r1s2"
down_revision = "m6n7o8p9q0r1"
branch_labels = None
depends_on = None


ROOT_CODES = (
    "admin:system:root",
    "studio:root",
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
        return

    for code in ROOT_CODES:
        power_id = connection.execute(
            sa.text(
                "SELECT id FROM admin_power "
                "WHERE code = :code AND enable = 1 "
                "ORDER BY id LIMIT 1"
            ),
            {"code": code},
        ).scalar()
        if power_id is None:
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
                {"power_id": power_id, "role_id": role_id},
            )


def downgrade():
    connection = op.get_bind()
    role_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_role "
            "WHERE code = 'dept_admin' ORDER BY id LIMIT 1"
        )
    ).scalar()
    if role_id is None:
        return
    power_ids = connection.execute(
        sa.text(
            "SELECT id FROM admin_power WHERE code IN :codes"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": list(ROOT_CODES)},
    ).scalars().all()
    if power_ids:
        connection.execute(
            sa.text(
                "DELETE FROM admin_role_power "
                "WHERE role_id = :role_id AND power_id IN :power_ids"
            ).bindparams(sa.bindparam("power_ids", expanding=True)),
            {"role_id": role_id, "power_ids": power_ids},
        )
