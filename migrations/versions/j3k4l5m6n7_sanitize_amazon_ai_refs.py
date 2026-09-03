"""sanitize stale GoFastDFS references after Amazon AI consolidation"""

import json

from alembic import op
import sqlalchemy as sa


revision = "j3k4l5m6n7"
down_revision = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None

TASK_TABLE = "amazon_ai_workspace_task"


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return _inspector().has_table(name)


def _json(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _int_or_none(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _referenced_ids(result_refs, file_refs):
    values = []
    for key in (
        "response_asset_id",
        "result_asset_id",
        "output_asset_id",
    ):
        values.append(result_refs.get(key))
    for key in (
        "response_asset_ids",
        "result_asset_ids",
        "output_asset_ids",
    ):
        values.extend(result_refs.get(key) or [])
    for group in ("inputs", "results"):
        for item in file_refs.get(group) or []:
            if isinstance(item, dict):
                values.append(item.get("asset_id"))
    result = []
    for value in values:
        asset_id = _int_or_none(value)
        if asset_id and asset_id not in result:
            result.append(asset_id)
    return result


def _existing_assets(connection, ids):
    if not ids or not _has_table("studio_asset"):
        return {}
    placeholders = ", ".join(
        f":asset_{index}" for index in range(len(ids))
    )
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


def _sanitize_result_refs(result_refs, existing_ids):
    result_refs = dict(result_refs)
    singular_keys = (
        "response_asset_id",
        "result_asset_id",
        "output_asset_id",
    )
    for key in singular_keys:
        value = _int_or_none(result_refs.get(key))
        if value and value not in existing_ids:
            result_refs.pop(key, None)

    list_keys = (
        "response_asset_ids",
        "result_asset_ids",
        "output_asset_ids",
    )
    for key in list_keys:
        values = result_refs.get(key)
        if values is None:
            continue
        if not isinstance(values, list):
            values = [values]
        result_refs[key] = [
            value
            for value in values
            if _int_or_none(value) in existing_ids
        ]
    return result_refs


def _sanitize_file_refs(file_refs, existing_ids):
    file_refs = dict(file_refs)
    for group in ("inputs", "results", "legacy_urls"):
        values = file_refs.get(group)
        if not isinstance(values, list):
            file_refs[group] = []
            continue
        cleaned = []
        for item in values:
            if not isinstance(item, dict):
                continue
            asset_id = _int_or_none(item.get("asset_id"))
            if asset_id and asset_id not in existing_ids:
                item = dict(item)
                item["status"] = "MISSING"
                item["cleanup_error"] = "Asset record no longer exists"
            cleaned.append(item)
        file_refs[group] = cleaned
    return file_refs


def upgrade():
    if not _has_table(TASK_TABLE):
        return
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, result_refs_json, file_refs_json, output_asset_id, "
            "output_url, output_filename, output_checksum, "
            "output_expires_at, storage_cleanup_status "
            f"FROM {TASK_TABLE} ORDER BY id"
        )
    ).mappings().all()

    for row in rows:
        result_refs = _json(row["result_refs_json"], {}) or {}
        file_refs = _json(row["file_refs_json"], {}) or {}
        if not isinstance(result_refs, dict):
            result_refs = {}
        if not isinstance(file_refs, dict):
            file_refs = {}
        ids = _referenced_ids(result_refs, file_refs)
        assets = _existing_assets(connection, ids)
        existing_ids = set(assets)
        result_refs = _sanitize_result_refs(result_refs, existing_ids)
        file_refs = _sanitize_file_refs(file_refs, existing_ids)

        output_asset_id = _int_or_none(row["output_asset_id"])
        if output_asset_id not in existing_ids:
            output_asset_id = None
        if output_asset_id is None:
            response_asset_id = _int_or_none(
                result_refs.get("response_asset_id")
            )
            if response_asset_id in existing_ids:
                output_asset_id = response_asset_id

        output_url = str(row["output_url"] or "").strip() or None
        output_filename = str(row["output_filename"] or "").strip() or None
        output_checksum = str(row["output_checksum"] or "").strip() or None
        output_expires_at = row["output_expires_at"]
        output_asset = assets.get(output_asset_id)
        if output_asset:
            output_url = output_url or str(
                output_asset["public_url"] or ""
            ).strip() or None
            output_filename = output_filename or str(
                output_asset["original_filename"] or ""
            ).strip() or None
            output_checksum = output_checksum or str(
                output_asset["checksum"] or ""
            ).strip() or None
            output_expires_at = (
                output_expires_at or output_asset["expires_at"]
            )

        has_asset_refs = bool(
            any(
                _int_or_none(item.get("asset_id")) in existing_ids
                for group in ("inputs", "results")
                for item in file_refs.get(group) or []
                if isinstance(item, dict)
            )
            or output_asset_id
        )
        has_legacy_refs = bool(file_refs.get("legacy_urls"))
        cleanup_status = row["storage_cleanup_status"]
        if not has_asset_refs and not has_legacy_refs:
            cleanup_status = "NONE"
        elif cleanup_status in (None, "", "NONE"):
            cleanup_status = "ACTIVE"

        connection.execute(
            sa.text(
                f"UPDATE {TASK_TABLE} SET "
                "result_refs_json=:result_refs_json, "
                "file_refs_json=:file_refs_json, "
                "output_asset_id=:output_asset_id, "
                "output_url=:output_url, "
                "output_filename=:output_filename, "
                "output_checksum=:output_checksum, "
                "output_expires_at=:output_expires_at, "
                "storage_cleanup_status=:storage_cleanup_status "
                "WHERE id=:id"
            ),
            {
                "id": row["id"],
                "result_refs_json": json.dumps(
                    result_refs,
                    ensure_ascii=False,
                    default=str,
                ),
                "file_refs_json": json.dumps(
                    file_refs,
                    ensure_ascii=False,
                    default=str,
                ),
                "output_asset_id": output_asset_id,
                "output_url": output_url,
                "output_filename": output_filename,
                "output_checksum": output_checksum,
                "output_expires_at": output_expires_at,
                "storage_cleanup_status": cleanup_status,
            },
        )


def downgrade():
    # Stale IDs cannot be restored without reintroducing invalid references.
    return
