"""normalize the admin-only global model setting to a non-null scope

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-08-28 13:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "p9q0r1s2t3u4"
down_revision = "o8p9q0r1s2t3"
branch_labels = None
depends_on = None


SETTING_KEY = "global_chat_model_id"
SUPER_ADMIN_SETTING_DEPT_ID = 0


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, dept_id FROM studio_setting "
            "WHERE setting_key = :setting_key "
            "AND (dept_id IS NULL OR dept_id = :super_dept_id) "
            "ORDER BY updated_at DESC, id DESC"
        ),
        {
            "setting_key": SETTING_KEY,
            "super_dept_id": SUPER_ADMIN_SETTING_DEPT_ID,
        },
    ).all()
    if not rows:
        return

    keep_id = rows[0][0]
    connection.execute(
        sa.text(
            "UPDATE studio_setting SET dept_id = :super_dept_id "
            "WHERE id = :setting_id"
        ),
        {
            "super_dept_id": SUPER_ADMIN_SETTING_DEPT_ID,
            "setting_id": keep_id,
        },
    )
    duplicate_ids = [row[0] for row in rows[1:]]
    if duplicate_ids:
        connection.execute(
            sa.text(
                "DELETE FROM studio_setting WHERE id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": duplicate_ids},
        )


def downgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE studio_setting SET dept_id = NULL "
            "WHERE setting_key = :setting_key AND dept_id = :super_dept_id"
        ),
        {
            "setting_key": SETTING_KEY,
            "super_dept_id": SUPER_ADMIN_SETTING_DEPT_ID,
        },
    )
