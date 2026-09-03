"""restore the original built-in provider model set

Revision ID: w6x7y8z9a0
Revises: v5w6x7y8z9a0
Create Date: 2026-09-01 00:00:00.000000

The provider catalog was temporarily expanded with experimental ToAPIs model
variants. Keep existing rows for task/history references, but stop exposing
those variants as active models. Kuaipao's existing four text models remain
available.
"""

from alembic import op
import sqlalchemy as sa


revision = "w6x7y8z9a0"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


SETTING_KEY = "global_chat_model_id"
TOAPIS_DEFAULT_CODES = (
    "gpt-image-2",
    "gemini-3.1-flash-image-preview",
    "seedance-2",
    "gpt-5.5",
)


def _connection():
    return op.get_bind()


def _has_table(table_name):
    return sa.inspect(_connection()).has_table(table_name)


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return column_name in {
        item["name"]
        for item in sa.inspect(_connection()).get_columns(table_name)
    }


def _disable_extra_toapis_models():
    connection = _connection()
    if not _has_table("studio_provider") or not _has_table("studio_model"):
        return

    placeholders = ", ".join(
        f":code_{index}" for index in range(len(TOAPIS_DEFAULT_CODES))
    )
    params = {
        f"code_{index}": code
        for index, code in enumerate(TOAPIS_DEFAULT_CODES)
    }
    connection.execute(
        sa.text(
            "UPDATE studio_model AS model "
            "JOIN studio_provider AS provider "
            "ON provider.id = model.provider_id "
            "SET model.enabled = 0 "
            "WHERE LOWER(TRIM(provider.name)) = 'toapis' "
            f"AND model.model_code NOT IN ({placeholders})"
        ),
        params,
    )


def _repair_global_model_settings():
    connection = _connection()
    if not _has_table("studio_setting") or not _has_column(
        "studio_setting",
        "dept_id",
    ):
        return
    if not _has_table("studio_model") or not _has_table("studio_provider"):
        return

    settings = connection.execute(
        sa.text(
            "SELECT id, dept_id, setting_value "
            "FROM studio_setting "
            "WHERE setting_key = :setting_key"
        ),
        {"setting_key": SETTING_KEY},
    ).mappings().all()
    for setting in settings:
        try:
            selected_id = int(setting["setting_value"])
        except (TypeError, ValueError):
            selected_id = None

        selected_is_valid = False
        if selected_id:
            selected_is_valid = bool(
                connection.execute(
                    sa.text(
                        "SELECT model.id "
                        "FROM studio_model AS model "
                        "JOIN studio_provider AS provider "
                        "ON provider.id = model.provider_id "
                        "WHERE model.id = :model_id "
                        "AND model.enabled = 1 "
                        "AND model.media_type = 'CHAT' "
                        "AND provider.enabled = 1 "
                        "AND provider.dept_id = :dept_id "
                        "LIMIT 1"
                    ),
                    {
                        "model_id": selected_id,
                        "dept_id": setting["dept_id"],
                    },
                ).scalar()
            )
        if selected_is_valid:
            continue

        replacement_id = connection.execute(
            sa.text(
                "SELECT model.id "
                "FROM studio_model AS model "
                "JOIN studio_provider AS provider "
                "ON provider.id = model.provider_id "
                "WHERE model.enabled = 1 "
                "AND model.media_type = 'CHAT' "
                "AND provider.enabled = 1 "
                "AND provider.dept_id = :dept_id "
                "ORDER BY provider.id ASC, model.id ASC "
                "LIMIT 1"
            ),
            {"dept_id": setting["dept_id"]},
        ).scalar()
        connection.execute(
            sa.text(
                "UPDATE studio_setting "
                "SET setting_value = :setting_value "
                "WHERE id = :setting_id"
            ),
            {
                "setting_id": setting["id"],
                "setting_value": (
                    str(replacement_id) if replacement_id else None
                ),
            },
        )


def upgrade():
    _disable_extra_toapis_models()
    _repair_global_model_settings()


def downgrade():
    # Disabled legacy rows remain disabled on downgrade so a rollback cannot
    # silently expose model variants the administrator did not request.
    pass
