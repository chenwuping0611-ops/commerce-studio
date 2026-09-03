"""grant self-service system menu access to the studio user role

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-08-28 13:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "o8p9q0r1s2t3"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None


POWER_CODES = (
    "admin:user:main",
    "admin:log:main",
)


def upgrade():
    connection = op.get_bind()
    role_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_role "
            "WHERE code = 'studio_user' ORDER BY id LIMIT 1"
        )
    ).scalar()
    if role_id is None:
        return

    for code in POWER_CODES:
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
                {"role_id": role_id, "power_id": power_id},
            )


def downgrade():
    connection = op.get_bind()
    role_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_role "
            "WHERE code = 'studio_user' ORDER BY id LIMIT 1"
        )
    ).scalar()
    if role_id is None:
        return
    power_ids = connection.execute(
        sa.text(
            "SELECT id FROM admin_power WHERE code IN :codes"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": list(POWER_CODES)},
    ).scalars().all()
    if power_ids:
        connection.execute(
            sa.text(
                "DELETE FROM admin_role_power "
                "WHERE role_id = :role_id AND power_id IN :power_ids"
            ).bindparams(sa.bindparam("power_ids", expanding=True)),
            {"role_id": role_id, "power_ids": power_ids},
        )
