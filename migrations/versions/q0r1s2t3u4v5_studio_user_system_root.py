"""attach the system root to the self-service studio role

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-08-28 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "q0r1s2t3u4v5"
down_revision = "p9q0r1s2t3u4"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    role_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_role "
            "WHERE code = 'studio_user' ORDER BY id LIMIT 1"
        )
    ).scalar()
    power_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_power "
            "WHERE code = 'admin:system:root' AND enable = 1 "
            "ORDER BY id LIMIT 1"
        )
    ).scalar()
    if role_id is None or power_id is None:
        return
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
    power_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_power "
            "WHERE code = 'admin:system:root' ORDER BY id LIMIT 1"
        )
    ).scalar()
    if role_id is None or power_id is None:
        return
    connection.execute(
        sa.text(
            "DELETE FROM admin_role_power "
            "WHERE role_id = :role_id AND power_id = :power_id"
        ),
        {"role_id": role_id, "power_id": power_id},
    )
