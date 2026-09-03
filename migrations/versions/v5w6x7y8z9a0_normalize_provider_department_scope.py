"""normalize all provider configuration to real department scopes

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-09-01 00:00:00.000000

Older deployments created a virtual SUPER_ADMIN provider scope with a NULL
department. The current organization uses ``总项目`` as admin's real
department, so provider rows and language-model settings must use that
department like every other business department.
"""

from alembic import op
import sqlalchemy as sa


revision = "v5w6x7y8z9a0"
down_revision = "u4v5w6x7y8z9"
branch_labels = None
depends_on = None


SETTING_KEY = "global_chat_model_id"
BUILTIN_PROVIDER_NAMES = ("ToAPIs", "快跑AI")
PROVIDER_COPY_COLUMNS = (
    "kind",
    "base_url",
    "generation_path",
    "result_path",
    "balance_path",
    "token_balance_path",
    "auth_header",
    "auth_prefix",
    "timeout",
    "description",
)
MODEL_REFERENCE_TABLES = (
    "studio_generation_task",
    "studio_generation_comment",
    "amazon_ai_workspace_task",
    "amazon_ai_task",
    "studio_asset",
    "studio_generation_audit_log",
)
PROVIDER_REFERENCE_TABLES = (
    "studio_generation_audit_log",
)


def _connection():
    return op.get_bind()


def _inspector():
    return sa.inspect(_connection())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _columns(table_name):
    if not _has_table(table_name):
        return set()
    return {
        item["name"]
        for item in _inspector().get_columns(table_name)
    }


def _has_column(table_name, column_name):
    return column_name in _columns(table_name)


def _root_department():
    connection = _connection()
    root_id = connection.execute(
        sa.text(
            "SELECT id FROM admin_dept "
            "WHERE dept_name = :name "
            "AND (parent_id = 0 OR parent_id IS NULL) "
            "ORDER BY id LIMIT 1"
        ),
        {"name": "总项目"},
    ).scalar()
    if root_id is not None:
        return root_id

    # u4v5w6x7y8z9 normally creates this row. Keep this migration safe for a
    # database upgraded from an incomplete deployment as well.
    if _has_table("admin_user") and _has_column("admin_user", "dept_id"):
        root_id = connection.execute(
            sa.text(
                "SELECT dept_id FROM admin_user "
                "WHERE username = 'admin' AND dept_id IS NOT NULL "
                "ORDER BY id LIMIT 1"
            )
        ).scalar()
        if root_id is not None:
            connection.execute(
                sa.text(
                    "UPDATE admin_dept SET dept_name = '总项目', parent_id = 0, "
                    "sort = 0 WHERE id = :root_id"
                ),
                {"root_id": root_id},
            )
            return root_id

    root_id = connection.execute(
        sa.text(
            "INSERT INTO admin_dept "
            "(parent_id, dept_name, sort, leader, status) "
            "VALUES (0, '总项目', 0, '', 1)"
        )
    ).lastrowid
    return root_id


def _set_model_reference(old_id, new_id):
    connection = _connection()
    for table_name in MODEL_REFERENCE_TABLES:
        if not _has_table(table_name) or not _has_column(table_name, "model_id"):
            continue
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET model_id = :new_id "
                "WHERE model_id = :old_id"
            ),
            {"new_id": new_id, "old_id": old_id},
        )

    if _has_table("studio_setting") and _has_column(
        "studio_setting",
        "setting_value",
    ):
        connection.execute(
            sa.text(
                "UPDATE studio_setting SET setting_value = :new_value "
                "WHERE setting_key = :setting_key "
                "AND setting_value = :old_value"
            ),
            {
                "new_value": str(new_id),
                "setting_key": SETTING_KEY,
                "old_value": str(old_id),
            },
        )


def _set_provider_reference(old_id, new_id):
    connection = _connection()
    for table_name in PROVIDER_REFERENCE_TABLES:
        if not _has_table(table_name) or not _has_column(
            table_name,
            "provider_id",
        ):
            continue
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET provider_id = :new_id "
                "WHERE provider_id = :old_id"
            ),
            {"new_id": new_id, "old_id": old_id},
        )


def _merge_provider_models(duplicate_provider_id, keeper_provider_id):
    connection = _connection()
    if not _has_table("studio_model"):
        return

    duplicate_models = connection.execute(
        sa.text(
            "SELECT * FROM studio_model "
            "WHERE provider_id = :provider_id ORDER BY id"
        ),
        {"provider_id": duplicate_provider_id},
    ).mappings().all()
    model_columns = _columns("studio_model")
    for duplicate in duplicate_models:
        model_id = duplicate["id"]
        model_code = duplicate["model_code"]
        keeper_model_id = connection.execute(
            sa.text(
                "SELECT id FROM studio_model "
                "WHERE provider_id = :provider_id "
                "AND model_code = :model_code "
                "ORDER BY id LIMIT 1"
            ),
            {
                "provider_id": keeper_provider_id,
                "model_code": model_code,
            },
        ).scalar()
        if keeper_model_id is None:
            connection.execute(
                sa.text(
                    "UPDATE studio_model SET provider_id = :provider_id "
                    "WHERE id = :model_id"
                ),
                {
                    "provider_id": keeper_provider_id,
                    "model_id": model_id,
                },
            )
            continue

        assignments = []
        params = {
            "keeper_id": keeper_model_id,
            "duplicate_id": model_id,
        }
        for column in (
            "name",
            "media_type",
            "generation_path",
            "result_path",
            "parameter_schema",
            "capabilities",
            "description",
        ):
            if column not in model_columns:
                continue
            if duplicate.get(column) in (None, ""):
                continue
            keeper_value = connection.execute(
                sa.text(
                    f"SELECT {column} FROM studio_model WHERE id = :keeper_id"
                ),
                {"keeper_id": keeper_model_id},
            ).scalar()
            if keeper_value in (None, ""):
                assignments.append(f"{column} = :duplicate_{column}")
                params[f"duplicate_{column}"] = duplicate[column]
        if (
            "enabled" in model_columns
            and duplicate.get("enabled") not in (None, 0)
        ):
            keeper_enabled = connection.execute(
                sa.text(
                    "SELECT enabled FROM studio_model WHERE id = :keeper_id"
                ),
                {"keeper_id": keeper_model_id},
            ).scalar()
            if keeper_enabled in (None, 0):
                assignments.append("enabled = :duplicate_enabled")
                params["duplicate_enabled"] = duplicate["enabled"]
        if assignments:
            connection.execute(
                sa.text(
                    "UPDATE studio_model SET "
                    + ", ".join(assignments)
                    + " WHERE id = :keeper_id"
                ),
                params,
            )
        _set_model_reference(model_id, keeper_model_id)
        connection.execute(
            sa.text("DELETE FROM studio_model WHERE id = :model_id"),
            {"model_id": model_id},
        )


def _copy_missing_provider_values(keeper, duplicate):
    connection = _connection()
    provider_columns = _columns("studio_provider")
    assignments = []
    params = {
        "keeper_id": keeper["id"],
        "duplicate_id": duplicate["id"],
    }
    for column in PROVIDER_COPY_COLUMNS:
        if column not in provider_columns:
            continue
        if keeper.get(column) not in (None, ""):
            continue
        if duplicate.get(column) in (None, ""):
            continue
        assignments.append(f"{column} = :duplicate_{column}")
        params[f"duplicate_{column}"] = duplicate[column]

    if "api_key" in provider_columns:
        if keeper.get("api_key") in (None, "") and duplicate.get("api_key") not in (
            None,
            "",
        ):
            assignments.append("api_key = :duplicate_api_key")
            params["duplicate_api_key"] = duplicate["api_key"]

    if "enabled" in provider_columns and keeper.get("enabled") in (None, 0):
        if duplicate.get("enabled") not in (None, 0):
            assignments.append("enabled = :duplicate_enabled")
            params["duplicate_enabled"] = duplicate["enabled"]

    if assignments:
        connection.execute(
            sa.text(
                "UPDATE studio_provider SET "
                + ", ".join(assignments)
                + " WHERE id = :keeper_id"
            ),
            params,
        )


def _normalize_providers(root_id):
    connection = _connection()
    if not _has_table("studio_provider"):
        return

    provider_columns = _columns("studio_provider")
    if "dept_id" in provider_columns:
        connection.execute(
            sa.text(
                "UPDATE studio_provider SET dept_id = :root_id "
                "WHERE dept_id IS NULL"
            ),
            {"root_id": root_id},
        )
    if "owner_type" in provider_columns:
        connection.execute(
            sa.text(
                "UPDATE studio_provider SET owner_type = 'DEPARTMENT' "
                "WHERE owner_type IS NULL OR TRIM(owner_type) <> 'DEPARTMENT'"
            )
        )

    # Only built-in defaults are merged. Two custom providers with the same
    # display name may intentionally point to different endpoints.
    for provider_name in BUILTIN_PROVIDER_NAMES:
        departments = connection.execute(
            sa.text(
                "SELECT DISTINCT dept_id FROM studio_provider "
                "WHERE name = :name AND dept_id IS NOT NULL "
                "ORDER BY dept_id"
            ),
            {"name": provider_name},
        ).scalars().all()
        for department_id in departments:
            rows = connection.execute(
                sa.text(
                    "SELECT * FROM studio_provider "
                    "WHERE name = :name AND dept_id = :dept_id "
                    "ORDER BY id"
                ),
                {
                    "name": provider_name,
                    "dept_id": department_id,
                },
            ).mappings().all()
            if len(rows) < 2:
                continue
            keeper = rows[0]
            for duplicate in rows[1:]:
                _copy_missing_provider_values(keeper, duplicate)
                _merge_provider_models(duplicate["id"], keeper["id"])
                _set_provider_reference(duplicate["id"], keeper["id"])
                connection.execute(
                    sa.text(
                        "DELETE FROM studio_provider WHERE id = :provider_id"
                    ),
                    {"provider_id": duplicate["id"]},
                )
                keeper = connection.execute(
                    sa.text(
                        "SELECT * FROM studio_provider WHERE id = :provider_id"
                    ),
                    {"provider_id": keeper["id"]},
                ).mappings().first()


def _normalize_settings(root_id):
    connection = _connection()
    if not _has_table("studio_setting"):
        return
    columns = _columns("studio_setting")
    if "dept_id" not in columns:
        return

    legacy_rows = connection.execute(
        sa.text(
            "SELECT * FROM studio_setting "
            "WHERE setting_key = :setting_key "
            "AND (dept_id IS NULL OR dept_id = 0) "
            "ORDER BY updated_at DESC, id DESC"
        ),
        {"setting_key": SETTING_KEY},
    ).mappings().all()
    if not legacy_rows:
        return

    root_row = connection.execute(
        sa.text(
            "SELECT * FROM studio_setting "
            "WHERE setting_key = :setting_key AND dept_id = :dept_id "
            "ORDER BY id LIMIT 1"
        ),
        {
            "setting_key": SETTING_KEY,
            "dept_id": root_id,
        },
    ).mappings().first()

    if root_row is None:
        keeper = legacy_rows[0]
        connection.execute(
            sa.text(
                "UPDATE studio_setting SET dept_id = :dept_id "
                "WHERE id = :setting_id"
            ),
            {"dept_id": root_id, "setting_id": keeper["id"]},
        )
        root_row = dict(keeper)
        root_row["dept_id"] = root_id
        legacy_rows = legacy_rows[1:]

    # Preserve the current root selection if it exists; otherwise use the
    # newest legacy value as the root selection.
    if not root_row.get("setting_value"):
        for legacy in legacy_rows:
            if legacy.get("setting_value"):
                connection.execute(
                    sa.text(
                        "UPDATE studio_setting SET setting_value = :value "
                        "WHERE id = :setting_id"
                    ),
                    {
                        "value": legacy["setting_value"],
                        "setting_id": root_row["id"],
                    },
                )
                break

    legacy_ids = [row["id"] for row in legacy_rows]
    if legacy_ids:
        connection.execute(
            sa.text(
                "DELETE FROM studio_setting WHERE id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": legacy_ids},
        )


def upgrade():
    if not _has_table("admin_dept") or not _has_table("studio_provider"):
        return
    root_id = _root_department()
    _normalize_providers(root_id)
    _normalize_settings(root_id)


def downgrade():
    # This is a data normalization migration. Recreating a virtual
    # SUPER_ADMIN provider scope on downgrade would reintroduce the security
    # issue that this revision removes.
    pass
