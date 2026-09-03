"""replace the Amazon AI task table with a unified workspace task index

Revision ID: g0h1i2j3k4l5
Revises: f7b8c9d0e1f2
Create Date: 2026-08-27 00:00:00.000000
"""

import json
from datetime import timedelta

from alembic import op
import sqlalchemy as sa


revision = "g0h1i2j3k4l5"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


OLD_TABLE = "amazon_ai_task"
NEW_TABLE = "amazon_ai_workspace_task"
TARGET_TABLE = "amazon_ai_task_target"
TTL_DAYS = 7

TASK_TITLES = {
    "COMPETITOR_ANALYZE": "竞品分析",
    "KEYWORD_ANALYZE": "关键词分析",
    "REVIEW_ANALYZE": "Review分析",
    "DIFFERENTIATION_GENERATE": "差异化分析",
    "BASIC_INFO_CORRECT": "基础信息修正",
    "LISTING_GENERATE": "Listing创作",
    "LISTING_AUDIT": "Listing审核",
}


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _date_text(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _json(value):
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _asset_ids(input_refs, result_refs):
    values = list(input_refs.get("asset_ids") or [])
    for key in (
        "response_asset_id",
        "response_asset_ids",
        "result_asset_id",
        "result_asset_ids",
        "output_asset_id",
        "output_asset_ids",
    ):
        value = result_refs.get(key)
        values.extend(value if isinstance(value, list) else [value])
    result = []
    for value in values:
        try:
            asset_id = int(value)
        except (TypeError, ValueError):
            continue
        if asset_id > 0 and asset_id not in result:
            result.append(asset_id)
    return result


def _legacy_urls(result_refs):
    urls = []
    for key in (
        "response_download_url",
        "response_url",
        "output_url",
        "output_urls",
        "file_url",
        "file_urls",
    ):
        value = result_refs.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            url = str(item or "").strip()
            if url and url not in urls:
                urls.append(url)
    return urls


def _asset_snapshot(row, role):
    mapping = row._mapping
    filename = str(mapping.get("original_filename") or "").strip()
    return {
        "asset_id": int(mapping["id"]),
        "role": role,
        "url": str(mapping.get("public_url") or "").strip(),
        "public_url": str(mapping.get("public_url") or "").strip(),
        "storage_path": str(mapping.get("storage_path") or "").strip(),
        "filename": filename,
        "original_filename": filename,
        "content_type": str(mapping.get("content_type") or "").strip(),
        "file_size": mapping.get("file_size") or 0,
        "checksum": str(mapping.get("checksum") or "").strip() or None,
        "purpose": str(mapping.get("purpose") or "").strip(),
        "status": str(mapping.get("status") or "").strip(),
        "retention_policy": str(
            mapping.get("retention_policy") or ""
        ).strip(),
        "uploaded_at": _date_text(mapping.get("created_at")),
        "expires_at": _date_text(mapping.get("expires_at")),
    }


def _load_asset_snapshots(connection, asset_ids):
    if not asset_ids or not _has_table("studio_asset"):
        return {}
    placeholders = ", ".join(f":asset_{index}" for index in range(len(asset_ids)))
    params = {
        f"asset_{index}": asset_id
        for index, asset_id in enumerate(asset_ids)
    }
    rows = connection.execute(
        sa.text(
            "SELECT id, public_url, storage_path, original_filename, "
            "content_type, file_size, checksum, purpose, status, "
            "retention_policy, created_at, expires_at "
            f"FROM studio_asset WHERE id IN ({placeholders})"
        ),
        params,
    ).fetchall()
    return {int(row._mapping["id"]): row for row in rows}


def _create_table():
    if _has_table(NEW_TABLE):
        return
    op.create_table(
        NEW_TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dept_id", sa.Integer(), nullable=True),
        sa.Column("task_code", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("studio_product_id", sa.Integer(), nullable=True),
        sa.Column("input_refs_json", sa.Text(), nullable=True),
        sa.Column("result_refs_json", sa.Text(), nullable=True),
        sa.Column("file_refs_json", sa.Text(), nullable=True),
        sa.Column(
            "retention_policy",
            sa.String(length=20),
            nullable=False,
            server_default="TTL_7D",
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "storage_cleanup_status",
            sa.String(length=20),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("storage_cleanup_error", sa.Text(), nullable=True),
        sa.Column("storage_deleted_at", sa.DateTime(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_sections_json", sa.Text(), nullable=True),
        sa.Column("request_digest", sa.String(length=64), nullable=True),
        sa.Column("response_digest", sa.String(length=64), nullable=True),
        sa.Column("provider_task_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["admin_user.id"],
            ondelete="SET NULL",
            name="fk_amazon_ai_workspace_task_user",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["studio_model.id"],
            ondelete="SET NULL",
            name="fk_amazon_ai_workspace_task_model",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["studio_skill.id"],
            ondelete="SET NULL",
            name="fk_amazon_ai_workspace_task_skill",
        ),
        sa.ForeignKeyConstraint(
            ["studio_product_id"],
            ["studio_product.id"],
            ondelete="SET NULL",
            name="fk_amazon_ai_workspace_task_product",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_code",
            name="uq_amazon_ai_workspace_task_code",
        ),
    )


def _copy_rows():
    connection = op.get_bind()
    if not _has_table(OLD_TABLE):
        return

    old_count = connection.execute(
        sa.text(f"SELECT COUNT(*) FROM {OLD_TABLE}")
    ).scalar()
    new_count = connection.execute(
        sa.text(f"SELECT COUNT(*) FROM {NEW_TABLE}")
    ).scalar()
    if not old_count or new_count:
        return

    rows = connection.execute(
        sa.text(
            f"SELECT id, dept_id, task_code, task_type, status, priority, "
            f"progress, retry_count, max_retries, user_id, model_id, "
            f"skill_id, studio_product_id, input_refs_json, result_refs_json, "
            f"response_text, response_sections_json, request_digest, "
            f"response_digest, provider_task_id, error_code, error_message, "
            f"scheduled_at, started_at, heartbeat_at, finished_at, "
            f"created_at, updated_at FROM {OLD_TABLE} ORDER BY id"
        )
    ).fetchall()
    insert_sql = sa.text(
        f"INSERT INTO {NEW_TABLE} ("
        "id, dept_id, task_code, task_type, title, status, priority, "
        "progress, retry_count, max_retries, user_id, model_id, skill_id, "
        "studio_product_id, input_refs_json, result_refs_json, "
        "file_refs_json, retention_policy, expires_at, "
        "storage_cleanup_status, response_text, response_sections_json, "
        "request_digest, response_digest, provider_task_id, error_code, "
        "error_message, scheduled_at, started_at, heartbeat_at, finished_at, "
        "created_at, updated_at"
        ") VALUES ("
        ":id, :dept_id, :task_code, :task_type, :title, :status, :priority, "
        ":progress, :retry_count, :max_retries, :user_id, :model_id, "
        ":skill_id, :studio_product_id, :input_refs_json, :result_refs_json, "
        ":file_refs_json, :retention_policy, :expires_at, "
        ":storage_cleanup_status, :response_text, :response_sections_json, "
        ":request_digest, :response_digest, :provider_task_id, :error_code, "
        ":error_message, :scheduled_at, :started_at, :heartbeat_at, "
        ":finished_at, :created_at, :updated_at"
        ")"
    )

    for row in rows:
        mapping = row._mapping
        input_refs = _json(mapping.get("input_refs_json"))
        result_refs = _json(mapping.get("result_refs_json"))
        ids = _asset_ids(input_refs, result_refs)
        asset_rows = _load_asset_snapshots(connection, ids)
        input_ids = {
            int(value)
            for value in (input_refs.get("asset_ids") or [])
            if str(value).isdigit()
        }
        result_ids = set(ids) - input_ids
        file_refs = {
            "inputs": [
                _asset_snapshot(asset_rows[asset_id], "input")
                for asset_id in ids
                if asset_id in input_ids and asset_id in asset_rows
            ],
            "results": [
                _asset_snapshot(asset_rows[asset_id], "result")
                for asset_id in result_ids
                if asset_id in asset_rows
            ],
            "legacy_urls": [
                {
                    "role": "result",
                    "url": url,
                    "public_url": url,
                    "status": "ACTIVE",
                }
                for url in _legacy_urls(result_refs)
                if url
                and not any(
                    item.get("url") == url
                    for item in (
                        [
                            _asset_snapshot(asset_rows[asset_id], "result")
                            for asset_id in result_ids
                            if asset_id in asset_rows
                        ]
                    )
                )
            ],
        }
        expiry_values = []
        for group in ("inputs", "results"):
            for item in file_refs[group]:
                raw = item.get("expires_at")
                if raw and raw != "":
                    asset = asset_rows.get(int(item["asset_id"]))
                    if asset and asset._mapping.get("expires_at"):
                        expiry_values.append(asset._mapping["expires_at"])
        created_at = mapping.get("created_at")
        expires_at = min(expiry_values) if expiry_values else (
            created_at + timedelta(days=TTL_DAYS)
            if created_at
            else None
        )
        has_files = bool(
            file_refs["inputs"]
            or file_refs["results"]
            or file_refs["legacy_urls"]
        )
        params = {
            "id": mapping["id"],
            "dept_id": mapping.get("dept_id"),
            "task_code": mapping["task_code"],
            "task_type": mapping["task_type"],
            "title": TASK_TITLES.get(
                mapping["task_type"],
                mapping["task_type"],
            ),
            "status": mapping["status"],
            "priority": mapping.get("priority") or 0,
            "progress": mapping.get("progress") or 0,
            "retry_count": mapping.get("retry_count") or 0,
            "max_retries": mapping.get("max_retries") or 3,
            "user_id": mapping.get("user_id"),
            "model_id": mapping.get("model_id"),
            "skill_id": mapping.get("skill_id"),
            "studio_product_id": mapping.get("studio_product_id"),
            "input_refs_json": mapping.get("input_refs_json"),
            "result_refs_json": mapping.get("result_refs_json"),
            "file_refs_json": json.dumps(
                file_refs,
                ensure_ascii=False,
                default=str,
            ),
            "retention_policy": "TTL_7D",
            "expires_at": expires_at,
            "storage_cleanup_status": "ACTIVE" if has_files else "NONE",
            "storage_cleanup_error": None,
            "storage_deleted_at": None,
            "response_text": mapping.get("response_text"),
            "response_sections_json": mapping.get("response_sections_json"),
            "request_digest": mapping.get("request_digest"),
            "response_digest": mapping.get("response_digest"),
            "provider_task_id": mapping.get("provider_task_id"),
            "error_code": mapping.get("error_code"),
            "error_message": mapping.get("error_message"),
            "scheduled_at": mapping.get("scheduled_at"),
            "started_at": mapping.get("started_at"),
            "heartbeat_at": mapping.get("heartbeat_at"),
            "finished_at": mapping.get("finished_at"),
            "created_at": created_at,
            "updated_at": mapping.get("updated_at"),
        }
        connection.execute(insert_sql, params)

    max_id = connection.execute(
        sa.text(f"SELECT MAX(id) FROM {NEW_TABLE}")
    ).scalar()
    if max_id and connection.dialect.name == "mysql":
        connection.execute(
            sa.text(
                f"ALTER TABLE {NEW_TABLE} AUTO_INCREMENT = {int(max_id) + 1}"
            )
        )


def _create_indexes():
    inspector = _inspector()
    indexes = {
        index.get("name")
        for index in inspector.get_indexes(NEW_TABLE)
    }
    definitions = {
        "ix_amazon_ai_workspace_task_dept_created": [
            "dept_id",
            "created_at",
            "id",
        ],
        "ix_amazon_ai_workspace_task_dept_type_created": [
            "dept_id",
            "task_type",
            "created_at",
            "id",
        ],
        "ix_amazon_ai_workspace_task_dept_status_created": [
            "dept_id",
            "status",
            "created_at",
            "id",
        ],
        "ix_amazon_ai_workspace_task_retention_expiry": [
            "retention_policy",
            "storage_cleanup_status",
            "expires_at",
            "id",
        ],
        "ix_amazon_ai_workspace_task_user_created": [
            "user_id",
            "created_at",
            "id",
        ],
    }
    for name, columns in definitions.items():
        if name not in indexes:
            op.create_index(name, NEW_TABLE, columns)


def _repoint_target_fk():
    if not _has_table(TARGET_TABLE) or not _has_table(NEW_TABLE):
        return
    inspector = _inspector()
    for foreign_key in inspector.get_foreign_keys(TARGET_TABLE):
        if (
            foreign_key.get("referred_table") == OLD_TABLE
            and foreign_key.get("constrained_columns") == ["task_id"]
            and foreign_key.get("name")
        ):
            op.drop_constraint(
                foreign_key["name"],
                TARGET_TABLE,
                type_="foreignkey",
            )
    inspector = _inspector()
    has_new_fk = any(
        foreign_key.get("referred_table") == NEW_TABLE
        and foreign_key.get("constrained_columns") == ["task_id"]
        for foreign_key in inspector.get_foreign_keys(TARGET_TABLE)
    )
    if not has_new_fk:
        op.create_foreign_key(
            "fk_amazon_ai_task_target_workspace_task",
            TARGET_TABLE,
            NEW_TABLE,
            ["task_id"],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade():
    _create_table()
    _copy_rows()
    _repoint_target_fk()
    if _has_table(OLD_TABLE):
        op.drop_table(OLD_TABLE)
    _create_indexes()


def downgrade():
    if not _has_table(NEW_TABLE):
        return
    if _has_table(TARGET_TABLE):
        inspector = _inspector()
        for foreign_key in inspector.get_foreign_keys(TARGET_TABLE):
            if (
                foreign_key.get("referred_table") == NEW_TABLE
                and foreign_key.get("constrained_columns") == ["task_id"]
                and foreign_key.get("name")
            ):
                op.drop_constraint(
                    foreign_key["name"],
                    TARGET_TABLE,
                type_="foreignkey",
            )
    if not _has_table(OLD_TABLE):
        op.rename_table(NEW_TABLE, OLD_TABLE)
    if _has_table(TARGET_TABLE) and _has_table(OLD_TABLE):
        inspector = _inspector()
        has_old_fk = any(
            foreign_key.get("referred_table") == OLD_TABLE
            and foreign_key.get("constrained_columns") == ["task_id"]
            for foreign_key in inspector.get_foreign_keys(TARGET_TABLE)
        )
        if not has_old_fk:
            op.create_foreign_key(
                "fk_amazon_ai_task_target_task",
                TARGET_TABLE,
                OLD_TABLE,
                ["task_id"],
                ["id"],
                ondelete="CASCADE",
            )
