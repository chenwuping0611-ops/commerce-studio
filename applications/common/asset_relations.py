"""Normalized asset and task relation helpers.

The JSON columns and ``StudioAsset.generation_task_id`` remain compatibility
fallbacks for old rows. New code reads and writes the relation tables first so
asset reuse never overwrites an earlier task.
"""

import json

from datetime import datetime

from sqlalchemy import and_, or_

from applications.extensions import db
from applications.models import (
    AmazonAiTask,
    AmazonAiTaskAsset,
    AmazonAiTaskDependency,
    AmazonAiTaskSource,
    StudioAsset,
    StudioBatchPrompt,
    StudioGenerationTask,
    StudioGenerationTaskAsset,
    StudioProductAsset,
    StudioSkill,
)


GENERATION_REFERENCE_ROLES = frozenset(
    {"REFERENCE", "REFERENCE_IMAGE", "REFERENCE_VIDEO", "INPUT"}
)
GENERATION_OUTPUT_ROLES = frozenset({"OUTPUT", "RESULT", "THUMBNAIL"})
AMAZON_INPUT_ROLES = frozenset({"INPUT", "REFERENCE"})
AMAZON_RESULT_ROLES = frozenset(
    {"RESULT", "OUTPUT", "SOURCE_RESULT"}
)


def _json(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _unique_ints(values):
    result = []
    for value in values or []:
        value = _int_or_none(value)
        if value and value not in result:
            result.append(value)
    return result


def _legacy_generation_role(asset):
    if asset.purpose == "GENERATION_OUTPUT":
        return "OUTPUT"
    if asset.purpose == "GENERATION_REFERENCE":
        return (
            "REFERENCE_VIDEO"
            if asset.asset_type == "VIDEO"
            else "REFERENCE_IMAGE"
        )
    return "LEGACY"


def generation_task_asset_links(
    task_id,
    roles=None,
    include_legacy=True,
):
    """Return ``(relation, asset)`` pairs in stable task order."""

    query = (
        StudioGenerationTaskAsset.query.join(
            StudioAsset,
            StudioAsset.id == StudioGenerationTaskAsset.asset_id,
        )
        .filter(
            StudioGenerationTaskAsset.generation_task_id == int(task_id),
        )
        .order_by(
            StudioGenerationTaskAsset.sort.asc(),
            StudioGenerationTaskAsset.id.asc(),
        )
    )
    if roles:
        query = query.filter(StudioGenerationTaskAsset.role.in_(set(roles)))
    links = query.all()
    if links or not include_legacy:
        return [(link, link.asset) for link in links]

    legacy_query = StudioAsset.query.filter_by(
        generation_task_id=int(task_id),
    ).order_by(StudioAsset.id.asc())
    assets = legacy_query.all()
    return [
        (
            None,
            asset,
        )
        for asset in assets
        if not roles or _legacy_generation_role(asset) in set(roles)
    ]


def generation_task_assets(task_id, roles=None, include_legacy=True):
    return [
        asset
        for _link, asset in generation_task_asset_links(
            task_id,
            roles=roles,
            include_legacy=include_legacy,
        )
    ]


def generation_task_asset_links_for_task(
    task,
    roles=None,
    include_legacy=True,
):
    """Use an already-loaded task relationship before querying by task id."""

    if not task:
        return []
    all_links = list(getattr(task, "asset_links", ()) or ())
    if all_links or not include_legacy:
        allowed_roles = set(roles or ())
        return [
            (link, link.asset)
            for link in all_links
            if link.asset is not None
            and (not allowed_roles or link.role in allowed_roles)
        ]
    return generation_task_asset_links(
        task.id,
        roles=roles,
        include_legacy=True,
    )


def generation_task_assets_for_task(task, roles=None, include_legacy=True):
    return [
        asset
        for _link, asset in generation_task_asset_links_for_task(
            task,
            roles=roles,
            include_legacy=include_legacy,
        )
    ]


def ensure_generation_asset_links(task_id, assets, role, start_sort=0):
    """Add missing generation relations without changing legacy metadata."""

    asset_ids = _unique_ints(
        asset.id if isinstance(asset, StudioAsset) else asset
        for asset in (assets or [])
    )
    if not asset_ids:
        return []
    existing = {
        int(asset_id)
        for (asset_id,) in db.session.query(
            StudioGenerationTaskAsset.asset_id,
        )
        .filter(
            StudioGenerationTaskAsset.generation_task_id == int(task_id),
            StudioGenerationTaskAsset.asset_id.in_(asset_ids),
            StudioGenerationTaskAsset.role == str(role),
        )
        .all()
    }
    created = []
    for offset, asset_id in enumerate(asset_ids):
        if asset_id in existing:
            continue
        relation = StudioGenerationTaskAsset(
            generation_task_id=int(task_id),
            asset_id=asset_id,
            role=str(role),
            sort=int(start_sort) + offset,
        )
        db.session.add(relation)
        created.append(relation)
    return created


def generation_task_asset_ids(task_id, roles=None, include_legacy=True):
    return [
        int(asset.id)
        for asset in generation_task_assets(
            task_id,
            roles=roles,
            include_legacy=include_legacy,
        )
        if asset and asset.id
    ]


def amazon_task_asset_links(task_id, roles=None, include_legacy=True):
    query = (
        AmazonAiTaskAsset.query.join(
            StudioAsset,
            StudioAsset.id == AmazonAiTaskAsset.asset_id,
        )
        .filter(AmazonAiTaskAsset.task_id == int(task_id))
        .order_by(
            AmazonAiTaskAsset.sort.asc(),
            AmazonAiTaskAsset.id.asc(),
        )
    )
    if roles:
        query = query.filter(AmazonAiTaskAsset.role.in_(set(roles)))
    links = query.all()
    if links or not include_legacy:
        return [(link, link.asset) for link in links]

    task = AmazonAiTask.query.get(int(task_id))
    if not task:
        return []
    input_ids = _unique_ints(_json(task.input_asset_ids_json, []) or [])
    input_refs = _json(task.input_refs_json, {}) or {}
    input_ids.extend(
        item
        for item in _unique_ints(input_refs.get("asset_ids") or [])
        if item not in input_ids
    )
    result_refs = _json(task.result_refs_json, {}) or {}
    result_ids = _unique_ints([task.output_asset_id])
    for key in (
        "response_asset_id",
        "response_asset_ids",
        "result_asset_id",
        "result_asset_ids",
        "output_asset_id",
        "output_asset_ids",
    ):
        value = result_refs.get(key)
        result_ids.extend(
            item
            for item in _unique_ints(
                value if isinstance(value, list) else [value]
            )
            if item not in result_ids
        )
    ids = []
    if not roles or set(roles) & AMAZON_INPUT_ROLES:
        ids.extend(input_ids)
    if not roles or set(roles) & AMAZON_RESULT_ROLES:
        ids.extend(item for item in result_ids if item not in ids)
    if not ids:
        return []
    assets = StudioAsset.query.filter(StudioAsset.id.in_(ids)).all()
    by_id = {asset.id: asset for asset in assets}
    result = []
    for index, asset_id in enumerate(ids):
        asset = by_id.get(asset_id)
        if not asset:
            continue
        role = "INPUT" if asset_id in input_ids else "RESULT"
        result.append((None, asset))
    return result


def amazon_task_assets(task_id, roles=None, include_legacy=True):
    return [
        asset
        for _link, asset in amazon_task_asset_links(
            task_id,
            roles=roles,
            include_legacy=include_legacy,
        )
    ]


def amazon_task_asset_links_for_task(
    task,
    roles=None,
    include_legacy=True,
):
    """Use selectin-loaded Amazon asset links when a task row is available."""

    if not task:
        return []
    all_links = list(getattr(task, "asset_links", ()) or ())
    if all_links or not include_legacy:
        allowed_roles = set(roles or ())
        return [
            (link, link.asset)
            for link in all_links
            if link.asset is not None
            and (not allowed_roles or link.role in allowed_roles)
        ]
    return amazon_task_asset_links(
        task.id,
        roles=roles,
        include_legacy=True,
    )


def amazon_task_assets_for_task(task, roles=None, include_legacy=True):
    return [
        asset
        for _link, asset in amazon_task_asset_links_for_task(
            task,
            roles=roles,
            include_legacy=include_legacy,
        )
    ]


def amazon_task_asset_ids(task, roles=None, include_legacy=True):
    if not task:
        return []
    return [
        int(asset.id)
        for asset in amazon_task_assets(
            task.id,
            roles=roles,
            include_legacy=include_legacy,
        )
        if asset and asset.id
    ]


def ensure_amazon_asset_links(task_id, assets, role, start_sort=0):
    asset_ids = _unique_ints(
        asset.id if isinstance(asset, StudioAsset) else asset
        for asset in (assets or [])
    )
    if not asset_ids:
        return []
    existing = {
        int(asset_id)
        for (asset_id,) in db.session.query(AmazonAiTaskAsset.asset_id)
        .filter(
            AmazonAiTaskAsset.task_id == int(task_id),
            AmazonAiTaskAsset.asset_id.in_(asset_ids),
            AmazonAiTaskAsset.role == str(role),
        )
        .all()
    }
    created = []
    for offset, asset_id in enumerate(asset_ids):
        if asset_id in existing:
            continue
        relation = AmazonAiTaskAsset(
            task_id=int(task_id),
            asset_id=asset_id,
            role=str(role),
            sort=int(start_sort) + offset,
        )
        db.session.add(relation)
        created.append(relation)
    return created


def ensure_amazon_sources(task_id, source_urls=None, source_identifiers=None):
    values = []
    for sort, value in enumerate(source_urls or []):
        value = str(value or "").strip()
        if value:
            values.append(("URL", value, value, sort))
    offset = len(values)
    for sort, value in enumerate(source_identifiers or [], start=offset):
        value = str(value or "").strip()
        if value:
            values.append(("ASIN", value, None, sort))
    if not values:
        return []
    existing = {
        (str(source_type), str(source_key))
        for source_type, source_key in db.session.query(
            AmazonAiTaskSource.source_type,
            AmazonAiTaskSource.source_key,
        )
        .filter(AmazonAiTaskSource.task_id == int(task_id))
        .all()
    }
    created = []
    for source_type, source_key, source_url, sort in values:
        key = (source_type, source_key[:255])
        if key in existing:
            continue
        relation = AmazonAiTaskSource(
            task_id=int(task_id),
            source_type=source_type,
            source_key=source_key[:255],
            source_url=source_url[:2000] if source_url else None,
            sort=sort,
        )
        db.session.add(relation)
        existing.add(key)
        created.append(relation)
    return created


def ensure_amazon_dependencies(task_id, source_task_ids, relation_type="SOURCE_TASK"):
    ids = _unique_ints(source_task_ids)
    if not ids:
        return []
    existing = {
        int(source_task_id)
        for (source_task_id,) in db.session.query(
            AmazonAiTaskDependency.source_task_id,
        )
        .filter(
            AmazonAiTaskDependency.task_id == int(task_id),
            AmazonAiTaskDependency.source_task_id.in_(ids),
            AmazonAiTaskDependency.relation_type == relation_type,
        )
        .all()
    }
    created = []
    for source_task_id in ids:
        if source_task_id == int(task_id) or source_task_id in existing:
            continue
        relation = AmazonAiTaskDependency(
            task_id=int(task_id),
            source_task_id=source_task_id,
            relation_type=relation_type,
        )
        db.session.add(relation)
        created.append(relation)
    return created


def amazon_task_source_rows(task_id):
    return (
        AmazonAiTaskSource.query.filter_by(task_id=int(task_id))
        .order_by(AmazonAiTaskSource.sort.asc(), AmazonAiTaskSource.id.asc())
        .all()
    )


def amazon_task_dependency_rows(task_id):
    return (
        AmazonAiTaskDependency.query.filter_by(task_id=int(task_id))
        .order_by(AmazonAiTaskDependency.id.asc())
        .all()
    )


def generation_asset_referenced_by_other_task(
    asset_id,
    task_id=None,
    now=None,
):
    query = (
        db.session.query(StudioGenerationTaskAsset.id)
        .join(
            StudioGenerationTask,
            StudioGenerationTask.id
            == StudioGenerationTaskAsset.generation_task_id,
        )
        .filter(StudioGenerationTaskAsset.asset_id == int(asset_id))
    )
    if task_id is not None:
        query = query.filter(
            StudioGenerationTaskAsset.generation_task_id != int(task_id)
        )
    query = query.filter(
        or_(
            StudioGenerationTask.storage_cleanup_status.is_(None),
            StudioGenerationTask.storage_cleanup_status != "DELETED",
        )
    )
    if now is not None:
        query = query.filter(
            or_(
                StudioGenerationTask.expires_at.is_(None),
                StudioGenerationTask.expires_at > now,
            )
        )
    return query.first() is not None


def amazon_asset_referenced_by_other_task(
    asset_id,
    task_id=None,
    now=None,
):
    query = (
        db.session.query(AmazonAiTaskAsset.id)
        .join(
            AmazonAiTask,
            AmazonAiTask.id == AmazonAiTaskAsset.task_id,
        )
        .filter(AmazonAiTaskAsset.asset_id == int(asset_id))
    )
    if task_id is not None:
        query = query.filter(AmazonAiTaskAsset.task_id != int(task_id))
    query = query.filter(
        or_(
            AmazonAiTask.storage_cleanup_status.is_(None),
            AmazonAiTask.storage_cleanup_status != "DELETED",
        )
    )
    if now is not None:
        query = query.filter(
            or_(
                AmazonAiTask.expires_at.is_(None),
                AmazonAiTask.expires_at > now,
            )
        )
    return query.first() is not None


def asset_referenced_by_product_or_skill(asset_id):
    return bool(
        db.session.query(StudioProductAsset.id)
        .filter(
            StudioProductAsset.storage_asset_id == int(asset_id),
            StudioProductAsset.enabled != 0,
        )
        .first()
        or db.session.query(StudioSkill.id)
        .filter(
            StudioSkill.storage_asset_id == int(asset_id),
            StudioSkill.enabled != 0,
        )
        .first()
        or db.session.query(StudioBatchPrompt.id)
        .filter(
            StudioBatchPrompt.storage_asset_id == int(asset_id),
            StudioBatchPrompt.status != "DELETED",
        )
        .first()
    )


def referenced_asset_ids(
    asset_ids,
    generation_task_id=None,
    amazon_task_id=None,
    now=None,
):
    """Return all referenced assets in one batch of indexed relation queries."""

    ids = _unique_ints(asset_ids)
    if not ids:
        return set()
    referenced = set()

    generation_query = (
        db.session.query(StudioGenerationTaskAsset.asset_id)
        .join(
            StudioGenerationTask,
            StudioGenerationTask.id
            == StudioGenerationTaskAsset.generation_task_id,
        )
        .filter(StudioGenerationTaskAsset.asset_id.in_(ids))
    )
    if generation_task_id is not None:
        generation_query = generation_query.filter(
            StudioGenerationTaskAsset.generation_task_id
            != int(generation_task_id)
        )
    generation_query = generation_query.filter(
        or_(
            StudioGenerationTask.storage_cleanup_status.is_(None),
            StudioGenerationTask.storage_cleanup_status != "DELETED",
        )
    )
    if now is not None:
        generation_query = generation_query.filter(
            or_(
                StudioGenerationTask.expires_at.is_(None),
                StudioGenerationTask.expires_at > now,
            )
        )
    referenced.update(
        int(asset_id)
        for (asset_id,) in generation_query.distinct().all()
        if asset_id
    )

    amazon_query = (
        db.session.query(AmazonAiTaskAsset.asset_id)
        .join(
            AmazonAiTask,
            AmazonAiTask.id == AmazonAiTaskAsset.task_id,
        )
        .filter(AmazonAiTaskAsset.asset_id.in_(ids))
    )
    if amazon_task_id is not None:
        amazon_query = amazon_query.filter(
            AmazonAiTaskAsset.task_id != int(amazon_task_id)
        )
    amazon_query = amazon_query.filter(
        or_(
            AmazonAiTask.storage_cleanup_status.is_(None),
            AmazonAiTask.storage_cleanup_status != "DELETED",
        )
    )
    if now is not None:
        amazon_query = amazon_query.filter(
            or_(
                AmazonAiTask.expires_at.is_(None),
                AmazonAiTask.expires_at > now,
            )
        )
    referenced.update(
        int(asset_id)
        for (asset_id,) in amazon_query.distinct().all()
        if asset_id
    )

    product_query = db.session.query(StudioProductAsset.storage_asset_id).filter(
        StudioProductAsset.storage_asset_id.in_(ids),
        StudioProductAsset.enabled != 0,
    )
    referenced.update(
        int(asset_id)
        for (asset_id,) in product_query.distinct().all()
        if asset_id
    )
    skill_query = db.session.query(StudioSkill.storage_asset_id).filter(
        StudioSkill.storage_asset_id.in_(ids),
        StudioSkill.enabled != 0,
    )
    referenced.update(
        int(asset_id)
        for (asset_id,) in skill_query.distinct().all()
        if asset_id
    )
    batch_prompt_query = db.session.query(
        StudioBatchPrompt.storage_asset_id
    ).filter(
        StudioBatchPrompt.storage_asset_id.in_(ids),
        StudioBatchPrompt.status != "DELETED",
    )
    referenced.update(
        int(asset_id)
        for (asset_id,) in batch_prompt_query.distinct().all()
        if asset_id
    )
    return referenced


def asset_referenced(
    asset_id,
    generation_task_id=None,
    amazon_task_id=None,
    now=None,
):
    return int(asset_id) in referenced_asset_ids(
        [asset_id],
        generation_task_id=generation_task_id,
        amazon_task_id=amazon_task_id,
        now=now,
    )
