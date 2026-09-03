"""add normalized asset/task relations and execution lifecycle metadata

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-08-31 00:00:00.000000

This is the first stage of the execution/data optimization.  Legacy JSON
columns and the old StudioAsset.generation_task_id column intentionally
remain in place for compatibility and rollback.
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "r1s2t3u4v5w6"
down_revision = "q0r1s2t3u4v5"
branch_labels = None
depends_on = None


GENERATION_TASK_DETAIL = "studio_generation_task_detail"
GENERATION_TASK_ASSET = "studio_generation_task_asset"
AMAZON_TASK_SOURCE = "amazon_ai_task_source"
AMAZON_TASK_DEPENDENCY = "amazon_ai_task_dependency"
AMAZON_TASK_ASSET = "amazon_ai_task_asset"


def _connection():
    return op.get_bind()


def _inspector():
    return sa.inspect(_connection())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _columns(table_name):
    if not _has_table(table_name):
        return set()
    return {item["name"] for item in _inspector().get_columns(table_name)}


def _has_column(table_name, column_name):
    return column_name in _columns(table_name)


def _index_names(table_name):
    if not _has_table(table_name):
        return set()
    return {
        item.get("name")
        for item in _inspector().get_indexes(table_name)
        if item.get("name")
    }


def _unique_names(table_name):
    if not _has_table(table_name):
        return set()
    return {
        item.get("name")
        for item in _inspector().get_unique_constraints(table_name)
        if item.get("name")
    }


def _foreign_keys(table_name):
    if not _has_table(table_name):
        return []
    return _inspector().get_foreign_keys(table_name)


def _add_column(table_name, column):
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_index(name, table_name, columns, unique=False):
    if not _has_table(table_name) or name in _index_names(table_name):
        return
    op.create_index(name, table_name, columns, unique=unique)


def _drop_index(name, table_name):
    if _has_table(table_name) and name in _index_names(table_name):
        op.drop_index(name, table_name=table_name)


def _create_fk(name, table_name, columns, referred_table, referred_columns, ondelete):
    if not _has_table(table_name):
        return
    for item in _foreign_keys(table_name):
        if item.get("name") == name:
            return
        if (
            item.get("constrained_columns") == list(columns)
            and item.get("referred_table") == referred_table
        ):
            return
    op.create_foreign_key(
        name,
        table_name,
        referred_table,
        columns,
        referred_columns,
        ondelete=ondelete,
    )


def _drop_fk(name, table_name):
    if not _has_table(table_name):
        return
    if any(item.get("name") == name for item in _foreign_keys(table_name)):
        op.drop_constraint(name, table_name, type_="foreignkey")


def _drop_unique(name, table_name):
    if _has_table(table_name) and name in _unique_names(table_name):
        op.drop_constraint(name, table_name, type_="unique")


def _create_unique_if_safe(name, table_name, columns):
    """Add a DB constraint only when historical duplicate data is absent."""

    if not _has_table(table_name):
        return False
    if name in _unique_names(table_name) or name in _index_names(table_name):
        return True
    quoted = ", ".join(f"`{column}`" for column in columns)
    duplicate = _connection().execute(
        sa.text(
            f"SELECT 1 FROM `{table_name}` "
            f"GROUP BY {quoted} HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        return False
    op.create_unique_constraint(name, table_name, columns)
    return True


def _as_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _as_dict(value):
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _positive_int(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _unique_ints(values):
    result = []
    for value in values or []:
        value = _positive_int(value)
        if value and value not in result:
            result.append(value)
    return result


def _result_asset_ids(result_refs, file_refs, output_asset_id):
    values = [_positive_int(output_asset_id)]
    for key in (
        "response_asset_id",
        "response_asset_ids",
        "result_asset_id",
        "result_asset_ids",
        "output_asset_id",
        "output_asset_ids",
    ):
        raw = result_refs.get(key)
        values.extend(raw if isinstance(raw, list) else [raw])
    for group in ("results",):
        for item in file_refs.get(group) or []:
            if isinstance(item, dict):
                values.append(item.get("asset_id"))
    return _unique_ints(values)


def _input_asset_ids(input_refs, input_asset_ids, file_refs):
    values = list(input_refs.get("asset_ids") or [])
    values.extend(input_asset_ids)
    for item in file_refs.get("inputs") or []:
        if isinstance(item, dict):
            values.append(item.get("asset_id"))
    return _unique_ints(values)


def _add_generation_detail_backfill():
    if not _has_table(GENERATION_TASK_DETAIL) or not _has_table(
        "studio_generation_task"
    ):
        return
    connection = _connection()
    last_id = 0
    while True:
        rows = connection.execute(
            sa.text(
                "SELECT id, skill_prompt, prompt, final_prompt, "
                "negative_prompt, request_body, result_payload, "
                "error_message, created_at, updated_at "
                "FROM studio_generation_task "
                "WHERE id > :last_id ORDER BY id LIMIT 500"
            ),
            {"last_id": last_id},
        ).fetchall()
        if not rows:
            break
        payload = [
            {
                "task_id": row._mapping["id"],
                "skill_prompt": row._mapping.get("skill_prompt"),
                "prompt": row._mapping.get("prompt"),
                "final_prompt": row._mapping.get("final_prompt"),
                "negative_prompt": row._mapping.get("negative_prompt"),
                "request_body": row._mapping.get("request_body"),
                "result_payload": row._mapping.get("result_payload"),
                "error_message": row._mapping.get("error_message"),
                "created_at": row._mapping.get("created_at"),
                "updated_at": row._mapping.get("updated_at"),
            }
            for row in rows
        ]
        connection.execute(
            sa.text(
                "INSERT INTO studio_generation_task_detail "
                "(task_id, skill_prompt, prompt, final_prompt, "
                "negative_prompt, request_body, result_payload, "
                "error_message, created_at, updated_at) "
                "VALUES (:task_id, :skill_prompt, :prompt, :final_prompt, "
                ":negative_prompt, :request_body, :result_payload, "
                ":error_message, :created_at, :updated_at) "
                "ON DUPLICATE KEY UPDATE "
                "updated_at = COALESCE(VALUES(updated_at), updated_at)"
            ),
            payload,
        )
        last_id = int(rows[-1]._mapping["id"])


def _add_generation_asset_backfill():
    if not _has_table(GENERATION_TASK_ASSET):
        return
    connection = _connection()
    connection.execute(
        sa.text(
            "INSERT IGNORE INTO studio_generation_task_asset "
            "(generation_task_id, asset_id, role, sort, created_at) "
            "SELECT a.generation_task_id, a.id, "
            "CASE "
            "WHEN a.purpose = 'GENERATION_OUTPUT' THEN 'OUTPUT' "
            "WHEN a.purpose = 'GENERATION_REFERENCE' "
            "AND a.asset_type = 'VIDEO' THEN 'REFERENCE_VIDEO' "
            "WHEN a.purpose = 'GENERATION_REFERENCE' THEN 'REFERENCE_IMAGE' "
            "ELSE 'LEGACY' END, a.id, a.created_at "
            "FROM studio_asset a "
            "INNER JOIN studio_generation_task t "
            "ON t.id = a.generation_task_id "
            "WHERE a.generation_task_id IS NOT NULL"
        )
    )


def _add_amazon_relation_backfill():
    if not _has_table("amazon_ai_workspace_task"):
        return
    connection = _connection()
    last_id = 0
    while True:
        rows = connection.execute(
            sa.text(
                "SELECT id, task_code, source_urls_json, "
                "source_identifiers_json, source_task_codes_json, "
                "input_asset_ids_json, input_refs_json, result_refs_json, "
                "file_refs_json, output_asset_id "
                "FROM amazon_ai_workspace_task "
                "WHERE id > :last_id ORDER BY id LIMIT 500"
            ),
            {"last_id": last_id},
        ).fetchall()
        if not rows:
            break

        source_values = []
        dependency_codes = []
        input_values = []
        result_values = []
        for row in rows:
            mapping = row._mapping
            task_id = int(mapping["id"])
            urls = [
                str(item).strip()
                for item in _as_list(mapping.get("source_urls_json"))
                if str(item).strip()
            ]
            identifiers = [
                str(item).strip()
                for item in _as_list(mapping.get("source_identifiers_json"))
                if str(item).strip()
            ]
            for sort, value in enumerate(urls):
                source_values.append(
                    {
                        "task_id": task_id,
                        "source_type": "URL",
                        "source_key": value[:255],
                        "source_url": value[:2000],
                        "sort": sort,
                    }
                )
            for sort, value in enumerate(identifiers, start=len(urls)):
                source_values.append(
                    {
                        "task_id": task_id,
                        "source_type": "ASIN",
                        "source_key": value[:255],
                        "source_url": None,
                        "sort": sort,
                    }
                )

            input_refs = _as_dict(mapping.get("input_refs_json"))
            result_refs = _as_dict(mapping.get("result_refs_json"))
            file_refs = _as_dict(mapping.get("file_refs_json"))
            input_ids = _input_asset_ids(
                input_refs,
                _as_list(mapping.get("input_asset_ids_json")),
                file_refs,
            )
            result_ids = _result_asset_ids(
                result_refs,
                file_refs,
                mapping.get("output_asset_id"),
            )
            input_values.extend((task_id, value, "INPUT", index) for index, value in enumerate(input_ids))
            result_values.extend((task_id, value, "RESULT", index) for index, value in enumerate(result_ids))
            codes = _as_list(mapping.get("source_task_codes_json"))
            codes.extend(input_refs.get("source_task_codes") or [])
            for code in codes:
                code = str(code or "").strip()
                if code and code not in dependency_codes:
                    dependency_codes.append(code)

        if source_values and _has_table(AMAZON_TASK_SOURCE):
            connection.execute(
                sa.text(
                    "INSERT IGNORE INTO amazon_ai_task_source "
                    "(task_id, source_type, source_key, source_url, sort) "
                    "VALUES (:task_id, :source_type, :source_key, "
                    ":source_url, :sort)"
                ),
                source_values,
            )

        task_ids_by_code = {}
        if dependency_codes:
            placeholders = ", ".join(
                f":code_{index}" for index in range(len(dependency_codes))
            )
            params = {
                f"code_{index}": code
                for index, code in enumerate(dependency_codes)
            }
            for item in connection.execute(
                sa.text(
                    "SELECT id, task_code FROM amazon_ai_workspace_task "
                    f"WHERE task_code IN ({placeholders})"
                ),
                params,
            ):
                task_ids_by_code[str(item._mapping["task_code"])] = int(
                    item._mapping["id"]
                )

        dependency_values = []
        for row in rows:
            mapping = row._mapping
            codes = _as_list(mapping.get("source_task_codes_json"))
            input_refs = _as_dict(mapping.get("input_refs_json"))
            codes.extend(input_refs.get("source_task_codes") or [])
            seen = set()
            for code in codes:
                code = str(code or "").strip()
                source_task_id = task_ids_by_code.get(code)
                if (
                    not source_task_id
                    or source_task_id == int(mapping["id"])
                    or code in seen
                ):
                    continue
                seen.add(code)
                dependency_values.append(
                    {
                        "task_id": int(mapping["id"]),
                        "source_task_id": source_task_id,
                        "relation_type": "SOURCE_TASK",
                    }
                )
        if dependency_values and _has_table(AMAZON_TASK_DEPENDENCY):
            connection.execute(
                sa.text(
                    "INSERT IGNORE INTO amazon_ai_task_dependency "
                    "(task_id, source_task_id, relation_type) "
                    "VALUES (:task_id, :source_task_id, :relation_type)"
                ),
                dependency_values,
            )

        if input_values or result_values:
            existing_asset_ids = set()
            all_asset_ids = _unique_ints(
                [item[1] for item in input_values]
                + [item[1] for item in result_values]
            )
            if all_asset_ids:
                placeholders = ", ".join(
                    f":asset_{index}" for index in range(len(all_asset_ids))
                )
                params = {
                    f"asset_{index}": asset_id
                    for index, asset_id in enumerate(all_asset_ids)
                }
                existing_asset_ids = {
                    int(item[0])
                    for item in connection.execute(
                        sa.text(
                            "SELECT id FROM studio_asset "
                            f"WHERE id IN ({placeholders})"
                        ),
                        params,
                    ).fetchall()
                }
            asset_values = [
                {
                    "task_id": task_id,
                    "asset_id": asset_id,
                    "role": role,
                    "sort": sort,
                }
                for task_id, asset_id, role, sort in input_values + result_values
                if asset_id in existing_asset_ids
            ]
            if asset_values and _has_table(AMAZON_TASK_ASSET):
                connection.execute(
                    sa.text(
                        "INSERT IGNORE INTO amazon_ai_task_asset "
                        "(task_id, asset_id, role, sort) "
                        "VALUES (:task_id, :asset_id, :role, :sort)"
                    ),
                    asset_values,
                )

        last_id = int(rows[-1]._mapping["id"])


def _normalize_retention_values():
    connection = _connection()
    if _has_table("studio_asset"):
        connection.execute(
            sa.text(
                "UPDATE studio_asset "
                "SET retention_policy = 'PERMANENT', expires_at = NULL "
                "WHERE purpose IN ('PRODUCT', 'SKILL')"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE studio_asset "
                "SET retention_policy = 'TEMPORARY', "
                "expires_at = CASE "
                "WHEN created_at IS NOT NULL "
                "THEN DATE_ADD(created_at, INTERVAL 30 DAY) "
                "ELSE expires_at END "
                "WHERE purpose NOT IN ('PRODUCT', 'SKILL') "
                "AND retention_policy IN ('TTL_7D', 'TEMPORARY')"
            )
        )

    if _has_table("studio_generation_task"):
        connection.execute(
            sa.text(
                "UPDATE studio_generation_task "
                "SET retention_policy = 'TEMPORARY' "
                "WHERE retention_policy IS NULL OR retention_policy = 'TTL_7D'"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE studio_generation_task "
                "SET expires_at = DATE_ADD("
                "COALESCE(completed_at, updated_at, created_at), "
                "INTERVAL 30 DAY) "
                "WHERE status IN ('SUCCEEDED', 'FAILED', 'CANCELLED') "
                "AND expires_at IS NULL "
                "AND COALESCE(completed_at, updated_at, created_at) IS NOT NULL"
            )
        )

    if _has_table("amazon_ai_workspace_task"):
        connection.execute(
            sa.text(
                "UPDATE amazon_ai_workspace_task "
                "SET retention_policy = 'TEMPORARY' "
                "WHERE retention_policy IS NULL OR retention_policy = 'TTL_7D'"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE amazon_ai_workspace_task "
                "SET expires_at = DATE_ADD("
                "COALESCE(finished_at, updated_at, created_at), "
                "INTERVAL 30 DAY) "
                "WHERE status IN ('SUCCEEDED', 'FAILED', 'CANCELLED') "
                "AND expires_at IS NULL "
                "AND COALESCE(finished_at, updated_at, created_at) IS NOT NULL"
            )
        )

    if _has_table("admin_admin_log") and _has_column(
        "admin_admin_log",
        "expires_at",
    ):
        connection.execute(
            sa.text(
                "UPDATE admin_admin_log "
                "SET expires_at = DATE_ADD("
                "COALESCE(create_time, NOW()), INTERVAL 90 DAY) "
                "WHERE expires_at IS NULL"
            )
        )


def _normalize_provider_scope():
    if not _has_table("studio_provider") or not _has_column(
        "studio_provider",
        "owner_type",
    ):
        return
    _connection().execute(
        sa.text(
            "UPDATE studio_provider SET owner_type = 'DEPARTMENT' "
            "WHERE owner_type IS NULL OR TRIM(owner_type) = ''"
        )
    )


def upgrade():
    _add_column(
        "studio_product_asset",
        sa.Column("external_url", sa.String(length=1000), nullable=True),
    )
    _add_column(
        "studio_generation_task",
        sa.Column(
            "retention_policy",
            sa.String(length=20),
            nullable=False,
            server_default="TEMPORARY",
        ),
    )
    _add_column(
        "studio_generation_task",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    _add_column(
        "studio_generation_task",
        sa.Column(
            "storage_cleanup_status",
            sa.String(length=20),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    _add_column(
        "studio_generation_task",
        sa.Column("storage_cleanup_error", sa.Text(), nullable=True),
    )
    _add_column(
        "studio_generation_task",
        sa.Column("storage_deleted_at", sa.DateTime(), nullable=True),
    )
    _add_column(
        "studio_generation_task",
        sa.Column("poll_claim_token", sa.String(length=64), nullable=True),
    )
    _add_column(
        "studio_generation_task",
        sa.Column("poll_claimed_at", sa.DateTime(), nullable=True),
    )
    _add_column(
        "studio_generation_comment",
        sa.Column("dept_id", sa.Integer(), nullable=True),
    )
    _add_column(
        "admin_admin_log",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )

    if not _has_table(GENERATION_TASK_DETAIL):
        op.create_table(
            GENERATION_TASK_DETAIL,
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("skill_prompt", sa.Text(), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=True),
            sa.Column("final_prompt", sa.Text(), nullable=True),
            sa.Column("negative_prompt", sa.Text(), nullable=True),
            sa.Column("request_body", sa.Text(), nullable=True),
            sa.Column("result_payload", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["studio_generation_task.id"],
                ondelete="CASCADE",
                name="fk_generation_task_detail_task",
            ),
            sa.PrimaryKeyConstraint("task_id"),
        )

    if not _has_table(GENERATION_TASK_ASSET):
        op.create_table(
            GENERATION_TASK_ASSET,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("generation_task_id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["generation_task_id"],
                ["studio_generation_task.id"],
                ondelete="CASCADE",
                name="fk_generation_task_asset_task",
            ),
            sa.ForeignKeyConstraint(
                ["asset_id"],
                ["studio_asset.id"],
                ondelete="RESTRICT",
                name="fk_generation_task_asset_asset",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "generation_task_id",
                "asset_id",
                "role",
                name="uq_studio_generation_task_asset_role",
            ),
        )

    if not _has_table(AMAZON_TASK_SOURCE):
        op.create_table(
            AMAZON_TASK_SOURCE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("source_type", sa.String(length=30), nullable=False),
            sa.Column("source_key", sa.String(length=255), nullable=False),
            sa.Column("source_url", sa.String(length=2000), nullable=True),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["amazon_ai_workspace_task.id"],
                ondelete="CASCADE",
                name="fk_amazon_ai_task_source_task",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_id",
                "source_type",
                "source_key",
                name="uq_amazon_ai_task_source_key",
            ),
        )

    if not _has_table(AMAZON_TASK_DEPENDENCY):
        op.create_table(
            AMAZON_TASK_DEPENDENCY,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("source_task_id", sa.Integer(), nullable=False),
            sa.Column("relation_type", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["amazon_ai_workspace_task.id"],
                ondelete="CASCADE",
                name="fk_amazon_ai_task_dependency_task",
            ),
            sa.ForeignKeyConstraint(
                ["source_task_id"],
                ["amazon_ai_workspace_task.id"],
                ondelete="CASCADE",
                name="fk_amazon_ai_task_dependency_source",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_id",
                "source_task_id",
                "relation_type",
                name="uq_amazon_ai_task_dependency",
            ),
        )

    if not _has_table(AMAZON_TASK_ASSET):
        op.create_table(
            AMAZON_TASK_ASSET,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=30), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["amazon_ai_workspace_task.id"],
                ondelete="CASCADE",
                name="fk_amazon_ai_task_asset_task",
            ),
            sa.ForeignKeyConstraint(
                ["asset_id"],
                ["studio_asset.id"],
                ondelete="RESTRICT",
                name="fk_amazon_ai_task_asset_asset",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_id",
                "asset_id",
                "role",
                name="uq_amazon_ai_task_asset_role",
            ),
        )

    # Clean invalid optional references before enforcing the new FKs.
    if _has_table("studio_product_asset") and _has_column(
        "studio_product_asset",
        "storage_asset_id",
    ):
        _connection().execute(
            sa.text(
                "UPDATE studio_product_asset p "
                "LEFT JOIN studio_asset a ON a.id = p.storage_asset_id "
                "SET p.storage_asset_id = NULL "
                "WHERE p.storage_asset_id IS NOT NULL AND a.id IS NULL"
            )
        )
    if _has_table("studio_skill") and _has_column(
        "studio_skill",
        "storage_asset_id",
    ):
        _connection().execute(
            sa.text(
                "UPDATE studio_skill s "
                "LEFT JOIN studio_asset a ON a.id = s.storage_asset_id "
                "SET s.storage_asset_id = NULL "
                "WHERE s.storage_asset_id IS NOT NULL AND a.id IS NULL"
            )
        )
    if _has_table("studio_generation_task") and _has_column(
        "studio_generation_task",
        "skill_id",
    ):
        _connection().execute(
            sa.text(
                "UPDATE studio_generation_task t "
                "LEFT JOIN studio_skill s ON s.id = t.skill_id "
                "SET t.skill_id = NULL "
                "WHERE t.skill_id IS NOT NULL AND s.id IS NULL"
            )
        )

    _create_fk(
        "fk_studio_product_asset_storage_asset",
        "studio_product_asset",
        ["storage_asset_id"],
        "studio_asset",
        ["id"],
        "SET NULL",
    )
    _create_fk(
        "fk_studio_skill_storage_asset",
        "studio_skill",
        ["storage_asset_id"],
        "studio_asset",
        ["id"],
        "SET NULL",
    )
    _create_fk(
        "fk_studio_generation_task_skill",
        "studio_generation_task",
        ["skill_id"],
        "studio_skill",
        ["id"],
        "SET NULL",
    )

    _create_index(
        "ix_studio_asset_expiry_status",
        "studio_asset",
        ["expires_at", "status", "id"],
    )
    _create_index(
        "ix_studio_asset_checksum_status",
        "studio_asset",
        ["checksum", "status", "id"],
    )
    _create_index(
        "ix_studio_generation_task_user_created",
        "studio_generation_task",
        ["user_id", "created_at", "id"],
    )
    _create_index(
        "ix_studio_generation_task_dept_created",
        "studio_generation_task",
        ["dept_id", "created_at", "id"],
    )
    _create_index(
        "ix_studio_generation_task_status_created",
        "studio_generation_task",
        ["status", "created_at", "id"],
    )
    _create_index(
        "ix_studio_generation_task_expiry_status",
        "studio_generation_task",
        ["expires_at", "status", "id"],
    )
    _create_index(
        "ix_studio_generation_task_provider_status",
        "studio_generation_task",
        ["provider_task_id", "status", "id"],
    )
    _create_index(
        "ix_studio_generation_task_asset_task_role_sort",
        GENERATION_TASK_ASSET,
        ["generation_task_id", "role", "sort", "asset_id"],
    )
    _create_index(
        "ix_studio_generation_task_asset_asset_task",
        GENERATION_TASK_ASSET,
        ["asset_id", "generation_task_id"],
    )
    _create_index(
        "ix_amazon_ai_task_source_type_key_task",
        AMAZON_TASK_SOURCE,
        ["source_type", "source_key", "task_id"],
    )
    _create_index(
        "ix_amazon_ai_task_source_task_sort",
        AMAZON_TASK_SOURCE,
        ["task_id", "sort", "id"],
    )
    _create_index(
        "ix_amazon_ai_task_dependency_source_task",
        AMAZON_TASK_DEPENDENCY,
        ["source_task_id", "task_id"],
    )
    _create_index(
        "ix_amazon_ai_task_dependency_task",
        AMAZON_TASK_DEPENDENCY,
        ["task_id", "source_task_id"],
    )
    _create_index(
        "ix_amazon_ai_task_asset_task_role_sort",
        AMAZON_TASK_ASSET,
        ["task_id", "role", "sort", "asset_id"],
    )
    _create_index(
        "ix_amazon_ai_task_asset_asset_task_role",
        AMAZON_TASK_ASSET,
        ["asset_id", "task_id", "role"],
    )
    _create_index(
        "ix_admin_admin_log_expiry",
        "admin_admin_log",
        ["expires_at", "id"],
    )
    _create_index(
        "ix_studio_product_asset_storage_asset",
        "studio_product_asset",
        ["storage_asset_id", "product_id"],
    )
    _create_index(
        "ix_studio_skill_storage_asset",
        "studio_skill",
        ["storage_asset_id", "id"],
    )
    _create_index(
        "ix_studio_generation_comment_task_created",
        "studio_generation_comment",
        ["generation_task_id", "created_at", "id"],
    )
    _create_index(
        "ix_studio_generation_task_poll_claim",
        "studio_generation_task",
        ["status", "poll_claimed_at", "id"],
    )

    # Constraints are added only after historical duplicates are checked.
    _create_unique_if_safe(
        "uq_admin_user_username",
        "admin_user",
        ["username"],
    )
    _create_unique_if_safe(
        "uq_admin_role_code",
        "admin_role",
        ["code"],
    )
    _create_unique_if_safe(
        "uq_studio_model_provider_code",
        "studio_model",
        ["provider_id", "model_code"],
    )
    _create_unique_if_safe(
        "uq_admin_user_role_pair",
        "admin_user_role",
        ["user_id", "role_id"],
    )
    _create_unique_if_safe(
        "uq_admin_role_power_pair",
        "admin_role_power",
        ["role_id", "power_id"],
    )

    _normalize_provider_scope()
    _add_generation_detail_backfill()
    _add_generation_asset_backfill()
    _add_amazon_relation_backfill()
    _normalize_retention_values()

    if _has_table("studio_generation_comment") and _has_column(
        "studio_generation_comment",
        "dept_id",
    ):
        _connection().execute(
            sa.text(
                "UPDATE studio_generation_comment c "
                "INNER JOIN studio_generation_task t "
                "ON t.id = c.generation_task_id "
                "SET c.dept_id = t.dept_id "
                "WHERE c.dept_id IS NULL"
            )
        )


def downgrade():
    _drop_unique("uq_admin_role_power_pair", "admin_role_power")
    _drop_unique("uq_admin_user_role_pair", "admin_user_role")
    _drop_unique("uq_studio_model_provider_code", "studio_model")
    _drop_unique("uq_admin_role_code", "admin_role")
    _drop_unique("uq_admin_user_username", "admin_user")

    _drop_index("ix_studio_generation_task_poll_claim", "studio_generation_task")
    _drop_index(
        "ix_studio_generation_comment_task_created",
        "studio_generation_comment",
    )
    _drop_index("ix_studio_skill_storage_asset", "studio_skill")
    _drop_index(
        "ix_studio_product_asset_storage_asset",
        "studio_product_asset",
    )
    _drop_index("ix_admin_admin_log_expiry", "admin_admin_log")
    _drop_index(
        "ix_amazon_ai_task_asset_asset_task_role",
        AMAZON_TASK_ASSET,
    )
    _drop_index(
        "ix_amazon_ai_task_asset_task_role_sort",
        AMAZON_TASK_ASSET,
    )
    _drop_index(
        "ix_amazon_ai_task_dependency_task",
        AMAZON_TASK_DEPENDENCY,
    )
    _drop_index(
        "ix_amazon_ai_task_dependency_source_task",
        AMAZON_TASK_DEPENDENCY,
    )
    _drop_index("ix_amazon_ai_task_source_task_sort", AMAZON_TASK_SOURCE)
    _drop_index("ix_amazon_ai_task_source_type_key_task", AMAZON_TASK_SOURCE)
    _drop_index(
        "ix_studio_generation_task_asset_asset_task",
        GENERATION_TASK_ASSET,
    )
    _drop_index(
        "ix_studio_generation_task_asset_task_role_sort",
        GENERATION_TASK_ASSET,
    )
    _drop_index(
        "ix_studio_generation_task_provider_status",
        "studio_generation_task",
    )
    _drop_index(
        "ix_studio_generation_task_expiry_status",
        "studio_generation_task",
    )
    _drop_index(
        "ix_studio_generation_task_status_created",
        "studio_generation_task",
    )
    _drop_index(
        "ix_studio_generation_task_dept_created",
        "studio_generation_task",
    )
    _drop_index(
        "ix_studio_generation_task_user_created",
        "studio_generation_task",
    )
    _drop_index("ix_studio_asset_checksum_status", "studio_asset")
    _drop_index("ix_studio_asset_expiry_status", "studio_asset")

    if _has_table(AMAZON_TASK_ASSET):
        op.drop_table(AMAZON_TASK_ASSET)
    if _has_table(AMAZON_TASK_DEPENDENCY):
        op.drop_table(AMAZON_TASK_DEPENDENCY)
    if _has_table(AMAZON_TASK_SOURCE):
        op.drop_table(AMAZON_TASK_SOURCE)
    if _has_table(GENERATION_TASK_ASSET):
        op.drop_table(GENERATION_TASK_ASSET)
    if _has_table(GENERATION_TASK_DETAIL):
        op.drop_table(GENERATION_TASK_DETAIL)

    _drop_fk(
        "fk_studio_generation_task_skill",
        "studio_generation_task",
    )
    _drop_fk(
        "fk_studio_skill_storage_asset",
        "studio_skill",
    )
    _drop_fk(
        "fk_studio_product_asset_storage_asset",
        "studio_product_asset",
    )

    for table_name, column_name in (
        ("admin_admin_log", "expires_at"),
        ("studio_generation_comment", "dept_id"),
        ("studio_generation_task", "poll_claimed_at"),
        ("studio_generation_task", "poll_claim_token"),
        ("studio_generation_task", "storage_deleted_at"),
        ("studio_generation_task", "storage_cleanup_error"),
        ("studio_generation_task", "storage_cleanup_status"),
        ("studio_generation_task", "expires_at"),
        ("studio_generation_task", "retention_policy"),
        ("studio_product_asset", "external_url"),
    ):
        if _has_column(table_name, column_name):
            op.drop_column(table_name, column_name)
