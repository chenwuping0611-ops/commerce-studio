"""consolidate Amazon AI data into the workspace task table

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5
Create Date: 2026-08-27 00:00:00.000000

The migration keeps only ``amazon_ai_workspace_task`` for Amazon AI business
records. The old detail tables are intentionally removed after their small
amount of metadata is copied into the task row.
"""

import json
import re
from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "i2j3k4l5m6n7"
down_revision = "h1i2j3k4l5"
branch_labels = None
depends_on = None


TASK_TABLE = "amazon_ai_workspace_task"
COMPETITOR_TABLE = "amazon_competitor"
DROP_TABLES = (
    "amazon_ai_task_target",
    "amazon_listing_audit",
    "amazon_listing_version",
    "amazon_review",
    "amazon_keyword",
    "amazon_competitor",
    "amazon_listing_project",
)
ASIN_PATTERN = re.compile(
    r"/(?:dp|gp/product)/([A-Z0-9]{10})(?=[/?#&]|$)",
    re.IGNORECASE,
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return _inspector().has_table(name)


def _has_column(table, column):
    return column in {
        item["name"] for item in _inspector().get_columns(table)
    }


def _has_index(table, name):
    return name in {
        item.get("name") for item in _inspector().get_indexes(table)
    }


def _json(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _asin(value):
    match = ASIN_PATTERN.search(str(value or ""))
    return match.group(1).upper() if match else ""


def _base_name(value):
    value = str(value or "").strip()
    if "." in value:
        value = value.rsplit(".", 1)[0]
    return value.strip()


def _safe_filename(value):
    value = str(value or "").strip()
    if value.lower().endswith(".txt"):
        value = value[:-4].rstrip()
    value = value.rstrip(". ")
    return (value or "amazon-ai-result")[:180] + ".txt"


def _asset_rows(connection, ids):
    if not ids or not _has_table("studio_asset"):
        return {}
    placeholders = ", ".join(f":asset_{index}" for index in range(len(ids)))
    params = {
        f"asset_{index}": asset_id
        for index, asset_id in enumerate(ids)
    }
    rows = connection.execute(
        sa.text(
            "SELECT id, public_url, original_filename, checksum, "
            "expires_at FROM studio_asset "
            f"WHERE id IN ({placeholders})"
        ),
        params,
    ).mappings()
    return {int(row["id"]): row for row in rows}


def _result_asset_ids(result_refs, file_refs):
    values = []
    for key in (
        "response_asset_id",
        "result_asset_id",
        "output_asset_id",
    ):
        value = result_refs.get(key)
        values.extend(value if isinstance(value, list) else [value])
    for item in (file_refs.get("results") or []):
        if isinstance(item, dict):
            values.append(item.get("asset_id"))
    result = []
    for value in values:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in result:
            result.append(value)
    return result


def _input_asset_ids(input_refs, file_refs):
    values = list(input_refs.get("asset_ids") or [])
    for item in (file_refs.get("inputs") or []):
        if isinstance(item, dict):
            values.append(item.get("asset_id"))
    result = []
    for value in values:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in result:
            result.append(value)
    return result


def _load_competitor_map(connection):
    if not _has_table(COMPETITOR_TABLE):
        return {}
    rows = connection.execute(
        sa.text(
            "SELECT id, product_url, source_url FROM amazon_competitor "
            "ORDER BY id"
        )
    ).mappings()
    return {
        int(row["id"]): (
            str(row.get("product_url") or row.get("source_url") or "").strip()
        )
        for row in rows
    }


def _add_columns():
    columns = (
        ("source_key", sa.String(length=120)),
        ("source_urls_json", sa.Text()),
        ("source_identifiers_json", sa.Text()),
        ("source_task_codes_json", sa.Text()),
        ("input_asset_ids_json", sa.Text()),
        ("task_metadata_json", sa.Text()),
        ("output_asset_id", sa.Integer()),
        ("output_url", sa.String(length=1200)),
        ("output_filename", sa.String(length=255)),
        ("output_checksum", sa.String(length=128)),
        ("output_expires_at", sa.DateTime()),
    )
    for name, column_type in columns:
        if not _has_column(TASK_TABLE, name):
            op.add_column(TASK_TABLE, sa.Column(name, column_type, nullable=True))


def _create_output_asset_foreign_key():
    """Create the output Asset FK only after legacy IDs have been cleaned."""

    if _has_table("studio_asset") and not any(
        item.get("name") == "fk_amazon_ai_workspace_task_output_asset"
        for item in _inspector().get_foreign_keys(TASK_TABLE)
    ):
        op.create_foreign_key(
            "fk_amazon_ai_workspace_task_output_asset",
            TASK_TABLE,
            "studio_asset",
            ["output_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def _copy_task_metadata():
    connection = op.get_bind()
    competitor_urls = _load_competitor_map(connection)
    rows = connection.execute(
        sa.text(
            "SELECT id, dept_id, task_type, title, input_refs_json, "
            "result_refs_json, file_refs_json, response_text, "
            "response_sections_json, created_at FROM amazon_ai_workspace_task "
            "ORDER BY id"
        )
    ).mappings().all()
    counters = defaultdict(int)

    for row in rows:
        input_refs = _json(row["input_refs_json"], {}) or {}
        result_refs = _json(row["result_refs_json"], {}) or {}
        file_refs = _json(row["file_refs_json"], {}) or {}
        if not isinstance(file_refs, dict):
            file_refs = {}
        input_ids = _input_asset_ids(input_refs, file_refs)
        result_ids = _result_asset_ids(result_refs, file_refs)
        assets = _asset_rows(connection, list(dict.fromkeys(input_ids + result_ids)))
        # Some legacy rows contain stale Asset IDs in result_refs_json. They
        # must never be copied into the relational FK column. Keep the legacy
        # JSON/URL metadata below, but only use rows that still exist.
        result_ids = [
            asset_id for asset_id in result_ids
            if asset_id in assets
        ]

        source_urls = []
        source_identifiers = []
        source_task_codes = [
            str(value).strip()
            for value in (input_refs.get("source_task_codes") or [])
            if str(value).strip()
        ]
        business_ids = result_refs.get("business_ids") or []
        if not isinstance(business_ids, list):
            business_ids = [business_ids]
        for business_id in business_ids:
            try:
                url = competitor_urls.get(int(business_id), "")
            except (TypeError, ValueError):
                url = ""
            if url and url not in source_urls:
                source_urls.append(url)
            asin = _asin(url)
            if asin and asin not in source_identifiers:
                source_identifiers.append(asin)

        if row["task_type"] == "COMPETITOR_ANALYZE" and not source_urls:
            source_url = str(result_refs.get("source_url") or "").strip()
            if source_url:
                source_urls.append(source_url)
                asin = _asin(source_url)
                if asin:
                    source_identifiers.append(asin)

        first_result_asset = assets.get(result_ids[0]) if result_ids else None
        output_filename = str(
            result_refs.get("response_filename")
            or (first_result_asset or {}).get("original_filename")
            or ""
        ).strip()
        output_url = str(
            (first_result_asset or {}).get("public_url")
            or ""
        ).strip()
        output_checksum = str(
            (first_result_asset or {}).get("checksum")
            or result_refs.get("response_checksum")
            or ""
        ).strip()
        output_expires_at = (
            (first_result_asset or {}).get("expires_at")
            if first_result_asset
            else None
        )
        source_key = source_identifiers[0] if source_identifiers else None
        title = str(row["title"] or "").strip()

        if row["task_type"] == "COMPETITOR_ANALYZE" and source_key:
            counters[(row["dept_id"], source_key)] += 1
            title = (
                f"{source_key}-竞品分析-"
                f"R{counters[(row['dept_id'], source_key)]:02d}"
            )
            output_filename = _safe_filename(title)
        elif row["task_type"] == "DIFFERENTIATION_GENERATE":
            if not title or title == "差异化分析":
                input_asset = assets.get(input_ids[0]) if input_ids else None
                title = _base_name(
                    (input_asset or {}).get("original_filename")
                ) or str(row["created_at"] or "")[:16].replace(":", "-")
            output_filename = _safe_filename(output_filename or title)

        if output_filename:
            output_filename = _safe_filename(output_filename)

        cleaned_refs = dict(result_refs)
        cleaned_refs.pop("sections", None)
        cleaned_refs.pop("raw", None)
        if output_filename:
            cleaned_refs["response_filename"] = output_filename
        if output_url:
            cleaned_refs["response_url"] = output_url

        updates = {
            "title": title or row["task_type"],
            "source_key": source_key,
            "source_urls_json": json.dumps(source_urls, ensure_ascii=False),
            "source_identifiers_json": json.dumps(
                source_identifiers,
                ensure_ascii=False,
            ),
            "source_task_codes_json": json.dumps(
                source_task_codes,
                ensure_ascii=False,
            ),
            "input_asset_ids_json": json.dumps(
                input_ids,
                ensure_ascii=False,
            ),
            "task_metadata_json": json.dumps(
                {
                    "migrated_from_legacy_amazon_tables": True,
                    "legacy_business_ids": business_ids,
                },
                ensure_ascii=False,
            ),
            "output_asset_id": result_ids[0] if result_ids else None,
            "output_url": output_url or None,
            "output_filename": output_filename or None,
            "output_checksum": output_checksum or None,
            "output_expires_at": output_expires_at,
            "result_refs_json": json.dumps(
                cleaned_refs,
                ensure_ascii=False,
                default=str,
            ),
            "response_text": None,
            "response_sections_json": None,
        }
        connection.execute(
            sa.text(
                "UPDATE amazon_ai_workspace_task SET "
                "title=:title, source_key=:source_key, "
                "source_urls_json=:source_urls_json, "
                "source_identifiers_json=:source_identifiers_json, "
                "source_task_codes_json=:source_task_codes_json, "
                "input_asset_ids_json=:input_asset_ids_json, "
                "task_metadata_json=:task_metadata_json, "
                "output_asset_id=:output_asset_id, output_url=:output_url, "
                "output_filename=:output_filename, "
                "output_checksum=:output_checksum, "
                "output_expires_at=:output_expires_at, "
                "result_refs_json=:result_refs_json, "
                "response_text=:response_text, "
                "response_sections_json=:response_sections_json "
                "WHERE id=:id"
            ),
            {**updates, "id": row["id"]},
        )
        if result_ids and output_filename and _has_table("studio_asset"):
            connection.execute(
                sa.text(
                    "UPDATE studio_asset SET original_filename=:filename "
                    "WHERE id=:asset_id"
                ),
                {
                    "filename": output_filename,
                    "asset_id": result_ids[0],
                },
            )


def _drop_redundant_columns():
    for column in ("response_sections_json", "response_text"):
        if _has_column(TASK_TABLE, column):
            op.drop_column(TASK_TABLE, column)


def _create_indexes():
    if not _has_index(
        TASK_TABLE,
        "ix_amazon_ai_workspace_task_dept_type_source",
    ):
        op.create_index(
            "ix_amazon_ai_workspace_task_dept_type_source",
            TASK_TABLE,
            ["dept_id", "task_type", "source_key", "id"],
        )


def _drop_old_tables():
    for table in DROP_TABLES:
        if _has_table(table):
            op.drop_table(table)


def upgrade():
    if not _has_table(TASK_TABLE):
        return
    _add_columns()
    _copy_task_metadata()
    _drop_redundant_columns()
    _create_output_asset_foreign_key()
    _create_indexes()
    _drop_old_tables()


def downgrade():
    # The deleted legacy tables contain denormalized business rows and cannot
    # be reconstructed losslessly from the unified task index.
    if not _has_table(TASK_TABLE):
        return
    for index_name in (
        "ix_amazon_ai_workspace_task_dept_type_source",
    ):
        if _has_index(TASK_TABLE, index_name):
            op.drop_index(index_name, table_name=TASK_TABLE)
    for name in (
        "output_expires_at",
        "output_checksum",
        "output_filename",
        "output_url",
        "output_asset_id",
        "task_metadata_json",
        "input_asset_ids_json",
        "source_task_codes_json",
        "source_identifiers_json",
        "source_urls_json",
        "source_key",
    ):
        if _has_column(TASK_TABLE, name):
            op.drop_column(TASK_TABLE, name)
