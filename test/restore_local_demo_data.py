"""Restore a small, real-storage local demo dataset.

This utility is intentionally opt-in. It is meant for the development
database configured by ``.flaskenv`` after the schema/bootstrap commands have
run. It never creates API keys and never calls an AI provider.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import struct
import sys
import zlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from applications import create_app
from applications.amazon_ai.service import (
    AmazonAiService,
    _persist_text_result,
    _sync_task_file_refs,
)
from applications.common.asset_relations import (
    ensure_amazon_dependencies,
    ensure_amazon_sources,
    ensure_generation_asset_links,
)
from applications.common.storage import FileService
from applications.extensions import db
from applications.models import (
    AdminLog,
    AmazonAiTask,
    Dept,
    Power,
    Role,
    StudioAsset,
    StudioGenerationTask,
    StudioGenerationTaskAsset,
    StudioGenerationTaskDetail,
    StudioModel,
    StudioProduct,
    StudioProductAsset,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)
from applications.studio.bootstrap import (
    ensure_default_departments,
    ensure_default_provider_configs,
)


LOCAL_MARKER = "local-demo-20260901"
DEFAULT_PASSWORD = "123456"

# A valid 1x1 PNG used only as a tiny local test fixture.
DEMO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _rgb_png(red, green, blue):
    """Create a tiny valid RGB PNG with deterministic, unique content."""

    raw = b"\x00" + bytes((red, green, blue))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# Do not reuse the product image bytes for a generation result. GoFastDFS
# deduplicates identical content and would otherwise return the product path.
DEMO_OUTPUT_PNG = _rgb_png(31, 117, 214)

# A one-second 320x240 H.264 MP4 generated for the local video history row.
DEMO_MP4 = base64.b64decode(
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAPDbW9vdgAAAGxt"
    "dmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAAAAAAAAAAAAAAAAEAAAA"
    "AAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAu10cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAA"
    "AAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAA"
    "UAAAADwAAAAAAAkZlZHQAAAABAAAEAAAAAAEAAAABAAAAAAJlbWRpYQAAACBt"
    "ZGhkAAAAAAAAAAAAAAAAAAAwAAAAMABVxAAAAAAALWhkbHIAAAAAAAAAAHZp"
    "ZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAACEG1pbmYAAAAUdm1oZAAAA"
    "AEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQ"
    "AAAdBzdGJsAAAAwHN0c2QAAAAAAAAAAQAAALBhdmMxAAAAAAAAAAEAAAAAAAAA"
    "AAAAAAAAAAAAAAUAA8ABIAAAASAAAAAAAAAABFUxhdmM2Mi4zMC4xMDAgbGli"
    "eDI2NAAAAAAAAAAAAAAAGP//AAAANmF2Y0MBZAAM/+EAGWdkAAys2UFB+wEQAA"
    "ADABAAAAMBgPFCmWABAAZo6+PLIsD9+PgAAAAAEHBhc3AAAAABAAAAAQAAABRi"
    "dHJ0AAAAAAAAHNgAAAAAAAAAGHN0c3MAAAAAAAAAAQAAAAwAAAQAAAAAFHN0c3"
    "MAAAAAAAAAAQAAAAEAAABoY3R0cwAAAAAAAAALAAAAAQAACAAAAAABAAAUAAAA"
    "AAEAAAgAAAAAAQAAAAAAAAABAAAEAAAAAAEAABQAAAAAAQAACAAAAAABAAAAAAAA"
    "AAEAAAQAAAAAAQAAEAAAAAACAAAEAAAAABxzdHNjAAAAAAAAAAEAAAABAAAADA"
    "AAAAEAAABEc3RzegAAAAAAAAAAAAAADAAAAukAAAARAAAADgAAAA4AAAAOAAAA"
    "FwAAABAAAAAOAAAADgAAABYAAAAQAAAADgAAABRzdGNvAAAAAAAAAAEAAAPzAAA"
    "AYnVkdGEAAABabWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAA"
    "AAAAAAAAtaWxzdAAAACWpdG9vAAAAHWRhdGEAAAABAAAAAExhdmY2Mi4xMy4xMDIA"
    "AAAIZnJlZQAAA6NtZGF0AAACoAYF//+c3EXpvebZSLeWLNgg2SPu73gyNjQgLSBj"
    "b3JlIDE2NSAtIEguMjY0L01QRUctNCBBVkMgY29kZWMgLSBDb3B5bGVmdCAyMDAz"
    "LTIwMjUgLSBodHRwOi8vd3d3LnZpZGVvbGFuLm9yZy94MjY0Lmh0bWwgLSBvcHRp"
    "b25zOiBjYWJhYz0xIHJlZj0zIGRlYmxvY2s9MTowOjAgYW5hbHlzZT0weDM6MHgx"
    "MTMgbWU9aGV4IHN1Ym1lPTcgcHN5PTEgcHN5X3JkPTEuMDA6MC4wMCBtaXhlZF9y"
    "ZWY9MSBtZV9yYW5nZT0xNiBjaHJvbWFfbWU9MSB0cmVsbGlzPTEgOHg4ZGN0PTEg"
    "Y3FtPTAgZGVhZHpvbmU9MjEsMTEgZmFzdF9wc2tpcD0xIGNocm9tYV9xcF9vZmZz"
    "ZXQ9LTIgdGhyZWFkcz03IGxvb2thaGVhZF90aHJlYWRzPTEgc2xpY2VkX3RocmVh"
    "ZHM9MCBucj0wIGRlY2ltYXRlPTEgaW50ZXJsYWNlZD0wIGJsdXJheV9jb21wYXQ9"
    "MCBjb25zdHJhaW5lZF9pbnRyYT0wIGJmcmFtZXM9MyBiX3B5cmFtaWQ9MiBiX2Fk"
    "YXB0PTEgYl9iaWFzPTAgZGlyZWN0PTEgd2VpZ2h0Yj0xIG9wZW5fZ29wPTAgd2Vp"
    "Z2h0cD0yIGtleWludD0yNTAga2V5aW50X21pbj0xMiBzY2VuZWN1dD00MCBpbnRy"
    "YV9yZWZyZXNoPTAgcmNfbG9va2FoZD00MCByYz1jcmYgbWJ0cmVlPTEgY3JmPTIz"
    "LjAgcWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IGlwX3JhdGlv"
    "PTEuNDAgYXQ9MToxLjAwAgAAAAEFliIQAEP/+5sD5ljKA4AmQW76By0i5SXikwyt"
    "4PpxAMuQ0PLnwACepTr3FxEIsVwtgIsAAAdENiArZTJZvFhJOZwAAAA1BmiRsQQ"
    "/+qlUAABywAAAACkGeQniG/wAAUEEAAAAKAZ5hdEM/AABiwAAAAAoBnmNqQz8AAG"
    "LBAAAAE0GaaEmoQWiZTAh///6plgAAb8EAAAAMQZ6GRREsN/8AAFBBAAAACgGep"
    "XRDPwAAYsEAAAAKAZ6nakM/AABiwAAAABJBmqtJqEFsmUwIZ//+nhAAA2YAAAAMQ"
    "Z7JRRUsN/8AAFBBAAAACgGe6mpDPwAAYsA="
)

_DEMO_OUTPUT_MP4_TAG = b"local-demo-generation-output"
DEMO_OUTPUT_MP4 = DEMO_MP4 + struct.pack(
    ">I4s",
    8 + len(_DEMO_OUTPUT_MP4_TAG),
    b"free",
) + _DEMO_OUTPUT_MP4_TAG


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _expiry():
    return FileService.retention_expiry(FileService.TEMPORARY)


def _find_department(name, parent_id=None):
    query = Dept.query.filter_by(dept_name=name)
    if parent_id is not None:
        query = query.filter_by(parent_id=parent_id)
    return query.order_by(Dept.id.asc()).first()


def _remove_stale_operator_departments():
    """Remove only known empty legacy user-as-department nodes."""

    removed = []
    candidates = Dept.query.filter(Dept.dept_name == "五组操作员").all()
    for department in candidates:
        department_id = department.id
        blockers = {
            "children": Dept.query.filter_by(parent_id=department_id).count(),
            "users": User.query.filter_by(dept_id=department_id).count(),
            "assets": StudioAsset.query.filter_by(dept_id=department_id).count(),
            "products": StudioProduct.query.filter_by(dept_id=department_id).count(),
            "skills": StudioSkill.query.filter_by(dept_id=department_id).count(),
            "studio_tasks": StudioGenerationTask.query.filter_by(
                dept_id=department_id
            ).count(),
            "amazon_tasks": AmazonAiTask.query.filter_by(
                dept_id=department_id
            ).count(),
            "logs": AdminLog.query.filter_by(dept_id=department_id).count(),
        }
        if any(blockers.values()):
            print(
                "保留有业务引用的旧部门 "
                f"id={department_id}: {_json(blockers)}"
            )
            continue

        StudioSetting.query.filter_by(dept_id=department_id).delete(
            synchronize_session=False
        )
        providers = StudioProvider.query.filter_by(
            dept_id=department_id
        ).all()
        for provider in providers:
            db.session.delete(provider)
        db.session.flush()
        db.session.delete(department)
        removed.append(department_id)

    if removed:
        db.session.commit()
    return removed


def _remove_stale_provider_scopes(valid_department_ids):
    """Remove unreferenced provider rows left by old local smoke runs."""

    valid_department_ids = {
        int(value)
        for value in (valid_department_ids or ())
        if str(value).isdigit()
    }
    removed = []
    disabled = []
    for provider in StudioProvider.query.order_by(StudioProvider.id.asc()).all():
        if provider.dept_id in valid_department_ids:
            continue

        model_ids = [model.id for model in provider.models if model.id]
        referenced_model_ids = set()
        if model_ids:
            referenced_model_ids.update(
                model_id
                for (model_id,) in db.session.query(
                    StudioGenerationTask.model_id,
                )
                .filter(StudioGenerationTask.model_id.in_(model_ids))
                .all()
                if model_id
            )
            referenced_model_ids.update(
                model_id
                for (model_id,) in db.session.query(
                    AmazonAiTask.model_id,
                )
                .filter(AmazonAiTask.model_id.in_(model_ids))
                .all()
                if model_id
            )

        if referenced_model_ids:
            # Preserve historical model references, but hide the old scope
            # from all active provider and model selectors.
            provider.enabled = 0
            for model in provider.models:
                model.enabled = 0
            disabled.append(provider.id)
            continue

        db.session.delete(provider)
        removed.append(provider.id)

    if removed or disabled:
        db.session.commit()
    return {
        "removed": removed,
        "disabled": disabled,
    }


def _remove_stale_settings(valid_department_ids):
    """Remove settings that point to departments no longer in the local tree."""

    valid_department_ids = {
        int(value)
        for value in (valid_department_ids or ())
        if str(value).isdigit()
    }
    stale = StudioSetting.query.filter(
        StudioSetting.dept_id.isnot(None),
        ~StudioSetting.dept_id.in_(valid_department_ids or {-1}),
    ).all()
    removed = [setting.id for setting in stale]
    for setting in stale:
        db.session.delete(setting)
    if removed:
        db.session.commit()
    return removed


def _ensure_local_amazon_permissions():
    """Give the local demo operator role access to Amazon AI pages."""

    from applications.amazon_ai.permissions import AMAZON_AI_PERMISSION_CODES

    role = Role.query.filter_by(code="studio_user", enable=1).first()
    if not role:
        raise RuntimeError("默认 AI 创作用户角色尚未初始化")
    powers = Power.query.filter(
        Power.code.in_(AMAZON_AI_PERMISSION_CODES),
        Power.enable == 1,
    ).all()
    found_codes = {power.code for power in powers}
    missing_codes = set(AMAZON_AI_PERMISSION_CODES) - found_codes
    if missing_codes:
        raise RuntimeError(
            "Amazon AI 权限尚未初始化: "
            + ",".join(sorted(missing_codes))
        )
    existing_ids = {power.id for power in role.power if power}
    for power in powers:
        if power.id not in existing_ids:
            role.power.append(power)
    db.session.commit()
    return sorted(found_codes)


def _ensure_user(username, realname, department_id, role_code):
    from applications.models import Role

    role = Role.query.filter_by(code=role_code, enable=1).first()
    if not role:
        raise RuntimeError(f"角色不存在或未启用: {role_code}")
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(
            username=username,
            realname=realname,
            remark=f"{LOCAL_MARKER} 本地演示账号",
            enable=1,
            dept_id=department_id,
        )
        user.set_password(os.getenv("LOCAL_DEMO_PASSWORD", DEFAULT_PASSWORD))
        db.session.add(user)
        db.session.flush()
    else:
        user.realname = user.realname or realname
        user.enable = 1
        user.dept_id = department_id
    roles = user.role.all() if hasattr(user.role, "all") else list(user.role)
    if role not in roles:
        user.role.append(role)
    db.session.commit()
    return user


def _existing_asset(filename, purpose, department_id, created_by):
    query = StudioAsset.query.filter_by(
        original_filename=filename,
        purpose=purpose,
        dept_id=department_id,
        status="ACTIVE",
    )
    if created_by is not None:
        query = query.filter_by(created_by=created_by)
    return query.order_by(StudioAsset.id.asc()).first()


def _ensure_uploaded_asset(
    data,
    filename,
    content_type,
    asset_type,
    purpose,
    retention_policy,
    department_id,
    created_by,
):
    existing = _existing_asset(
        filename,
        purpose,
        department_id,
        created_by,
    )
    if existing:
        return existing

    stored = None
    try:
        stored = FileService.upload_bytes(
            data,
            filename,
            content_type=content_type,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention_policy,
            created_by=created_by,
            dept_id=department_id,
            record=False,
        )
        asset = FileService.create_asset_record(
            stored,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention_policy,
            created_by=created_by,
            dept_id=department_id,
        )
        db.session.add(asset)
        db.session.commit()
        return asset
    except Exception:
        db.session.rollback()
        if stored:
            try:
                FileService.delete_storage(
                    stored.storage_path,
                    checksum=stored.checksum,
                )
            except Exception:
                pass
        raise


def _ensure_product(product_department_id, owner_id, image_asset, video_asset):
    product = StudioProduct.query.filter_by(code="LOCAL-LEAFBLOWER").first()
    if not product:
        product = StudioProduct(
            dept_id=product_department_id,
            code="LOCAL-LEAFBLOWER",
            name="LeafBlow 本地演示吹风机",
            brand="LeafBlow",
            description="用于验证产品中心、图片创作、视频创作和 Amazon AI 关联流程的本地演示产品。",
            product_profile="便携式无绳吹风机，适合庭院清理和日常维护场景。",
            core_selling_points="轻量机身；无绳使用；可调风速；适合庭院清理。",
            product_memory="本地演示数据，不代表真实商品参数。",
            generation_rules="只使用产品中心已确认的事实。",
            forbidden_rules="不要虚构电池容量、风速数值和认证信息。",
            asset_urls="[]",
            enabled=1,
            created_by=owner_id,
        )
        db.session.add(product)
        db.session.flush()
    else:
        product.dept_id = product_department_id
        product.enabled = 1
        product.created_by = product.created_by or owner_id

    desired_assets = (
        (
            "正面产品图",
            "IMAGE",
            "front",
            image_asset,
            10,
        ),
        (
            "产品演示视频",
            "VIDEO",
            "360",
            video_asset,
            20,
        ),
    )
    for name, asset_type, role, storage_asset, sort in desired_assets:
        link = StudioProductAsset.query.filter_by(
            product_id=product.id,
            role=role,
            enabled=1,
        ).first()
        if not link:
            link = StudioProductAsset(
                product_id=product.id,
                name=name,
                url=storage_asset.public_url,
                asset_type=asset_type,
                role=role,
                sort=sort,
                enabled=1,
                storage_asset_id=storage_asset.id,
            )
            db.session.add(link)
        else:
            link.url = storage_asset.public_url
            link.asset_type = asset_type
            link.storage_asset_id = storage_asset.id
            link.enabled = 1
    db.session.commit()
    return product


def _provider_model(department_id, provider_name, model_code):
    provider = (
        StudioProvider.query.filter_by(
            dept_id=department_id,
            name=provider_name,
            enabled=1,
        )
        .order_by(StudioProvider.id.asc())
        .first()
    )
    if not provider:
        raise RuntimeError(
            f"缺少供应商配置: {provider_name}, department_id={department_id}"
        )
    model = StudioModel.query.filter_by(
        provider_id=provider.id,
        model_code=model_code,
        enabled=1,
    ).first()
    if not model:
        raise RuntimeError(
            f"缺少启用模型: {provider_name}/{model_code}, "
            f"department_id={department_id}"
        )
    return model


def _retire_local_output_asset(asset, reason):
    """Retire a stale demo row without deleting a possibly shared object."""

    if not asset:
        return
    asset.status = "DELETED"
    asset.deleted_at = datetime.datetime.now()
    asset.error_message = reason


def _repair_generation_output(
    task,
    *,
    output_filename,
    output_format,
    output_data,
    content_type,
    owner_id,
    department_id,
):
    """Replace a stale local demo output while preserving product assets."""

    stored = None
    old_links = (
        StudioGenerationTaskAsset.query.filter_by(
            generation_task_id=task.id,
            role="OUTPUT",
        )
        .order_by(StudioGenerationTaskAsset.id.asc())
        .all()
    )
    old_assets = [link.asset for link in old_links if link.asset]
    legacy_assets = (
        StudioAsset.query.filter_by(
            generation_task_id=task.id,
            purpose="GENERATION_OUTPUT",
        )
        .order_by(StudioAsset.id.asc())
        .all()
    )
    for legacy_asset in legacy_assets:
        if legacy_asset not in old_assets:
            old_assets.append(legacy_asset)

    try:
        stored = FileService.upload_bytes(
            output_data,
            output_filename,
            content_type=content_type,
            asset_type=task.media_type,
            purpose="GENERATION_OUTPUT",
            retention_policy=FileService.TEMPORARY,
            created_by=owner_id,
            dept_id=department_id,
            record=False,
        )
        output_asset = FileService.create_asset_record(
            stored,
            asset_type=task.media_type,
            purpose="GENERATION_OUTPUT",
            retention_policy=FileService.TEMPORARY,
            created_by=owner_id,
            dept_id=department_id,
            generation_task_id=task.id,
        )
        db.session.add(output_asset)
        db.session.flush()

        for link in old_links:
            db.session.delete(link)
        for old_asset in old_assets:
            if old_asset.id != output_asset.id:
                # Do not call delete_asset here. The old row can point to the
                # same GoFastDFS object as a permanent product asset.
                _retire_local_output_asset(
                    old_asset,
                    "本地演示输出已修复，旧记录可能与产品文件共用 GoFastDFS 对象",
                )

        ensure_generation_asset_links(task.id, [output_asset], "OUTPUT")
        task.output_url = output_asset.public_url
        task.output_filename = output_asset.original_filename
        task.output_format = output_format
        db.session.commit()
        return task
    except Exception:
        db.session.rollback()
        if stored:
            try:
                FileService.delete_storage(
                    stored.storage_path,
                    checksum=stored.checksum,
                )
            except Exception:
                pass
        raise


def _ensure_generation_task(
    *,
    task_code,
    department_id,
    owner_id,
    media_type,
    model,
    product,
    output_filename,
    output_format,
    output_data,
    content_type,
    prompt,
    reference_assets,
    created_at,
):
    task = StudioGenerationTask.query.filter_by(task_code=task_code).first()
    if task:
        current_link = (
            StudioGenerationTaskAsset.query.filter_by(
                generation_task_id=task.id,
                role="OUTPUT",
            )
            .order_by(StudioGenerationTaskAsset.id.asc())
            .first()
        )
        current_asset = current_link.asset if current_link else None
        if not current_asset:
            current_asset = (
                StudioAsset.query.filter_by(
                    generation_task_id=task.id,
                    purpose="GENERATION_OUTPUT",
                    status="ACTIVE",
                )
                .order_by(StudioAsset.id.asc())
                .first()
            )
        expected_checksum = hashlib.md5(bytes(output_data)).hexdigest()
        if (
            current_asset
            and current_asset.status == "ACTIVE"
            and current_asset.original_filename == output_filename
            and current_asset.checksum == expected_checksum
        ):
            return task
        return _repair_generation_output(
            task,
            output_filename=output_filename,
            output_format=output_format,
            output_data=output_data,
            content_type=content_type,
            owner_id=owner_id,
            department_id=department_id,
        )

    task = StudioGenerationTask(
        dept_id=department_id,
        task_code=task_code,
        user_id=owner_id,
        media_type=media_type,
        product_id=product.id if product else None,
        model_id=model.id,
        skill_id=None,
        skill_name="本地演示创作 Skill",
        skill_prompt="只使用本地演示产品的已确认事实。",
        prompt=prompt,
        final_prompt=prompt,
        request_body=_json({"model": model.model_code, "prompt": prompt}),
        result_payload=_json({"local_demo": LOCAL_MARKER}),
        status="SUCCEEDED",
        progress=100,
        output_format=output_format,
        retention_policy=FileService.TEMPORARY,
        expires_at=_expiry(),
        created_at=created_at,
        completed_at=created_at + datetime.timedelta(minutes=2),
    )
    db.session.add(task)
    db.session.flush()

    stored = None
    try:
        stored = FileService.upload_bytes(
            output_data,
            output_filename,
            content_type=content_type,
            asset_type=media_type,
            purpose="GENERATION_OUTPUT",
            retention_policy=FileService.TEMPORARY,
            created_by=owner_id,
            dept_id=department_id,
            record=False,
        )
        output_asset = FileService.create_asset_record(
            stored,
            asset_type=media_type,
            purpose="GENERATION_OUTPUT",
            retention_policy=FileService.TEMPORARY,
            created_by=owner_id,
            dept_id=department_id,
            generation_task_id=task.id,
        )
        db.session.add(output_asset)
        db.session.flush()
        ensure_generation_asset_links(task.id, [output_asset], "OUTPUT")
        if reference_assets:
            ensure_generation_asset_links(
                task.id,
                reference_assets,
                "REFERENCE_IMAGE",
            )
        task.output_url = output_asset.public_url
        detail = StudioGenerationTaskDetail(
            task_id=task.id,
            skill_prompt=task.skill_prompt,
            prompt=task.prompt,
            final_prompt=task.final_prompt,
            request_body=task.request_body,
            result_payload=task.result_payload,
            created_at=created_at,
        )
        db.session.add(detail)
        db.session.commit()
        return task
    except Exception:
        db.session.rollback()
        if stored:
            try:
                FileService.delete_storage(
                    stored.storage_path,
                    checksum=stored.checksum,
                )
            except Exception:
                pass
        raise


def _listing_result():
    questions = "\n\n".join(
        f"### Q{index}. 本地演示客户问题 {index}\n"
        f"**A:** 请依据已确认的产品事实使用 LeafBlow 吹风机。"
        for index in range(1, 21)
    )
    return (
        "# Amazon Listing 本地演示结果\n\n"
        "## Item Name\n\n"
        "LeafBlow Cordless Blower for Yard Cleanup\n\n"
        "## Item Highlights\n\n"
        "Lightweight cordless design; adjustable airflow; practical yard cleanup support.\n\n"
        "## Product Description\n\n"
        "A concise local demo listing based only on the confirmed product profile.\n\n"
        "## Customer FAQ / QA\n\n"
        + questions
    )


def _ensure_amazon_task(
    *,
    task_code,
    task_type,
    title,
    source_key,
    department_id,
    owner_id,
    model_id,
    skill_id,
    product_id,
    input_assets,
    source_urls,
    source_identifiers,
    source_task_ids,
    source_task_codes,
    output_filename,
    content,
    metadata,
    created_at,
):
    task = AmazonAiTask.query.filter_by(task_code=task_code).first()
    if task:
        return task

    task = AmazonAiTask(
        dept_id=department_id,
        task_code=task_code,
        task_type=task_type,
        title=title,
        source_key=source_key,
        status="SUCCEEDED",
        progress=100,
        user_id=owner_id,
        model_id=model_id,
        skill_id=skill_id,
        studio_product_id=product_id,
        source_urls_json=_json(source_urls),
        source_identifiers_json=_json(source_identifiers),
        source_task_codes_json=_json(source_task_codes),
        input_asset_ids_json=_json([asset.id for asset in input_assets]),
        task_metadata_json=_json(
            {
                "marker": LOCAL_MARKER,
                **(metadata or {}),
            }
        ),
        retention_policy=FileService.TEMPORARY,
        expires_at=_expiry(),
        storage_cleanup_status="ACTIVE",
        request_digest=_digest(
            {
                "task_type": task_type,
                "source_key": source_key,
                "input_assets": [asset.original_filename for asset in input_assets],
            }
        ),
        response_digest=_digest(content),
        output_filename=output_filename,
        created_at=created_at,
        started_at=created_at,
        finished_at=created_at + datetime.timedelta(minutes=3),
        heartbeat_at=created_at + datetime.timedelta(minutes=1),
    )
    db.session.add(task)
    db.session.flush()

    if input_assets:
        _sync_task_file_refs(
            task,
            input_asset_ids=[asset.id for asset in input_assets],
        )
    ensure_amazon_sources(
        task.id,
        source_urls=source_urls,
        source_identifiers=source_identifiers,
    )
    ensure_amazon_dependencies(task.id, source_task_ids)
    task.result_refs_json = _json(
        {
            "marker": LOCAL_MARKER,
            "business_type": task_type.lower(),
            "source_task_codes": source_task_codes,
        }
    )
    db.session.commit()

    _persist_text_result(task, content, filename=output_filename)
    db.session.commit()
    return task


def restore():
    root, children = ensure_default_departments()
    db.session.commit()
    removed_departments = _remove_stale_operator_departments()

    # Repair only the three intended real departments after stale nodes are
    # removed. Each department keeps its own provider/API-key scope.
    real_departments = {
        "root": root,
        "jinan": _find_department("三部五组", parent_id=root.id),
        "tangshan": _find_department("三部二组", parent_id=root.id),
    }
    if not all(real_departments.values()):
        raise RuntimeError("默认部门树不完整，无法恢复本地演示数据")
    provider_cleanup = _remove_stale_provider_scopes(
        department.id for department in real_departments.values()
    )
    setting_cleanup = _remove_stale_settings(
        department.id for department in real_departments.values()
    )
    local_amazon_permissions = _ensure_local_amazon_permissions()
    for department in real_departments.values():
        ensure_default_provider_configs(department.id)

    jinan_id = real_departments["jinan"].id
    tangshan_id = real_departments["tangshan"].id
    department_admin = _ensure_user(
        "local_dept_admin",
        "本地部门管理员",
        jinan_id,
        "dept_admin",
    )
    operator_a = _ensure_user(
        "local_operator_a",
        "本地操作员A",
        jinan_id,
        "studio_user",
    )
    operator_b = _ensure_user(
        "local_operator_b",
        "本地操作员B",
        jinan_id,
        "studio_user",
    )
    other_department_operator = _ensure_user(
        "other_dept_op",
        "其他部门操作员",
        tangshan_id,
        "studio_user",
    )

    product_image = _ensure_uploaded_asset(
        DEMO_PNG,
        "local-demo-product.png",
        "image/png",
        "IMAGE",
        "PRODUCT",
        FileService.PERMANENT,
        jinan_id,
        operator_a.id,
    )
    product_video = _ensure_uploaded_asset(
        DEMO_MP4,
        "local-demo-product.mp4",
        "video/mp4",
        "VIDEO",
        "PRODUCT",
        FileService.PERMANENT,
        jinan_id,
        operator_a.id,
    )
    product = _ensure_product(
        jinan_id,
        operator_a.id,
        product_image,
        product_video,
    )

    image_model = _provider_model(jinan_id, "ToAPIs", "gpt-image-2")
    video_model = _provider_model(jinan_id, "ToAPIs", "seedance-2")
    image_task = _ensure_generation_task(
        task_code="LIMG001",
        department_id=jinan_id,
        owner_id=operator_a.id,
        media_type="IMAGE",
        model=image_model,
        product=product,
        output_filename="local-demo-image.png",
        output_format="png",
        output_data=DEMO_OUTPUT_PNG,
        content_type="image/png",
        prompt="本地演示：展示 LeafBlow 无绳吹风机的庭院清理使用场景。",
        reference_assets=[product_image],
        created_at=datetime.datetime(2026, 9, 1, 9, 0, 0),
    )
    video_task = _ensure_generation_task(
        task_code="LVID001",
        department_id=jinan_id,
        owner_id=operator_a.id,
        media_type="VIDEO",
        model=video_model,
        product=product,
        output_filename="local-demo-video.mp4",
        output_format="mp4",
        output_data=DEMO_OUTPUT_MP4,
        content_type="video/mp4",
        prompt="本地演示：展示 LeafBlow 在庭院清理中的短视频动作。",
        reference_assets=[product_image],
        created_at=datetime.datetime(2026, 9, 1, 9, 5, 0),
    )

    competitor_input = _ensure_uploaded_asset(
        (
            "# 本地竞品资料\n\n"
            "用于恢复竞品分析页面的输入文件。\n"
            "只作为本地演示，不代表真实页面事实。\n"
        ).encode("utf-8"),
        "local-demo-competitor-notes.md",
        "text/markdown",
        "FILE",
        "AMAZON_INPUT",
        FileService.TTL_7D,
        jinan_id,
        operator_a.id,
    )
    differentiation_input = _ensure_uploaded_asset(
        (
            "keyword,volume,source\n"
            "cordless blower,100,local-demo\n"
            "yard cleanup,80,local-demo\n"
        ).encode("utf-8"),
        "local-demo-keywords.csv",
        "text/csv",
        "FILE",
        "AMAZON_INPUT",
        FileService.TTL_7D,
        jinan_id,
        operator_a.id,
    )

    chat_model = _provider_model(jinan_id, "快跑AI", "gpt-5.4")
    competitor_skill = StudioSkill.query.filter_by(
        code="Amazon_Competitor_Analysis_Skill.md",
        enabled=1,
    ).first()
    differentiation_skill = StudioSkill.query.filter_by(
        code="Amazon_Light_Differentiation_Skill.md",
        enabled=1,
    ).first()
    listing_skill = StudioSkill.query.filter_by(
        code="Amazon_Listing_Writer_Skill.md",
        enabled=1,
    ).first()
    if not all((competitor_skill, differentiation_skill, listing_skill)):
        raise RuntimeError("Amazon AI 内置 Skill 尚未恢复")

    competitor_content = (
        "# 竞品分析报告\n\n"
        "## 商品识别\n\n"
        "- ASIN：B0FQW461RN\n"
        "- 本地演示链接：https://www.amazon.com/dp/B0FQW461RN\n\n"
        "## 页面事实\n\n"
        "这是用于检查完整结果滚动展示、下载文件名和基础信息修正的本地演示结果。\n"
    )
    competitor_task = _ensure_amazon_task(
        task_code="LOCAL-AMZ-COMP-01",
        task_type="COMPETITOR_ANALYZE",
        title="B0FQW461RN-竞品分析-R01",
        source_key="B0FQW461RN",
        department_id=jinan_id,
        owner_id=operator_a.id,
        model_id=chat_model.id,
        skill_id=competitor_skill.id,
        product_id=None,
        input_assets=[competitor_input],
        source_urls=["https://www.amazon.com/dp/B0FQW461RN"],
        source_identifiers=["B0FQW461RN"],
        source_task_ids=[],
        source_task_codes=[],
        output_filename="B0FQW461RN-竞品分析-R01.txt",
        content=competitor_content,
        metadata={"ignored_url_count": 0},
        created_at=datetime.datetime(2026, 9, 1, 9, 10, 0),
    )

    differentiation_content = (
        "# 差异化分析报告\n\n"
        "## 高转化轻差异化方案\n\n"
        "基于本地关键词反查文件整理可验证的改进方向。\n\n"
        "## 现货微改\n\n"
        "优先验证包装、配件和使用场景表达。\n\n"
        "## 配件搭配\n\n"
        "只引用产品中心已确认的核心卖点。\n"
    )
    differentiation_task = _ensure_amazon_task(
        task_code="LOCAL-AMZ-DIFF-01",
        task_type="DIFFERENTIATION_GENERATE",
        title="local-demo-keywords",
        source_key="local-demo-keywords",
        department_id=jinan_id,
        owner_id=operator_a.id,
        model_id=chat_model.id,
        skill_id=differentiation_skill.id,
        product_id=product.id,
        input_assets=[differentiation_input],
        source_urls=[],
        source_identifiers=[],
        source_task_ids=[],
        source_task_codes=[],
        output_filename="local-demo-keywords.txt",
        content=differentiation_content,
        metadata={"input_filenames": [differentiation_input.original_filename]},
        created_at=datetime.datetime(2026, 9, 1, 9, 15, 0),
    )

    basic_content = (
        "LeafBlow 本地演示基础信息\n\n"
        "核心卖点：轻量机身；无绳使用；可调风速；适合庭院清理。\n"
        "确认规则：只使用已确认的产品事实，不虚构参数。\n"
    )
    basic_task = _ensure_amazon_task(
        task_code="LOCAL-AMZ-BASIC-01",
        task_type="BASIC_INFO_CORRECT",
        title="暴风机.txt",
        source_key="暴风机",
        department_id=jinan_id,
        owner_id=operator_a.id,
        model_id=chat_model.id,
        skill_id=None,
        product_id=product.id,
        input_assets=[],
        source_urls=[],
        source_identifiers=[],
        source_task_ids=[competitor_task.id],
        source_task_codes=[competitor_task.task_code],
        output_filename="暴风机.txt",
        content=basic_content,
        metadata={"source_task_codes": {"COMPETITOR_ANALYZE": competitor_task.task_code}},
        created_at=datetime.datetime(2026, 9, 1, 9, 20, 0),
    )

    listing_content = _listing_result()
    listing_task = _ensure_amazon_task(
        task_code="LOCAL-AMZ-LIST-01",
        task_type="LISTING_GENERATE",
        title="Listing创作-2026-09-01-LOCAL",
        source_key="LOCAL-LEAFBLOWER",
        department_id=jinan_id,
        owner_id=operator_a.id,
        model_id=chat_model.id,
        skill_id=listing_skill.id,
        product_id=product.id,
        input_assets=[competitor_input, differentiation_input],
        source_urls=[],
        source_identifiers=[],
        source_task_ids=[
            competitor_task.id,
            differentiation_task.id,
            basic_task.id,
        ],
        source_task_codes=[
            competitor_task.task_code,
            differentiation_task.task_code,
            basic_task.task_code,
        ],
        output_filename="Listing创作-2026-09-01-LOCAL.txt",
        content=listing_content,
        metadata={
            "source_task_codes": {
                "COMPETITOR_ANALYZE": competitor_task.task_code,
                "DIFFERENTIATION_GENERATE": differentiation_task.task_code,
                "BASIC_INFO_CORRECT": basic_task.task_code,
            }
        },
        created_at=datetime.datetime(2026, 9, 1, 9, 25, 0),
    )

    # Keep the demo product aligned with the saved basic-info result. This is
    # the same whole-field replacement behavior used by the real endpoint.
    product.core_selling_points = basic_content
    db.session.commit()

    return {
        "removed_legacy_departments": removed_departments,
        "provider_cleanup": provider_cleanup,
        "setting_cleanup": setting_cleanup,
        "local_amazon_permissions": local_amazon_permissions,
        "departments": {
            key: value.id for key, value in real_departments.items()
        },
        "users": [
            department_admin.username,
            operator_a.username,
            operator_b.username,
            other_department_operator.username,
        ],
        "product_id": product.id,
        "studio_task_codes": [image_task.task_code, video_task.task_code],
        "amazon_task_codes": [
            competitor_task.task_code,
            differentiation_task.task_code,
            basic_task.task_code,
            listing_task.task_code,
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Restore real GoFastDFS-backed local demo data."
    )
    parser.add_argument(
        "--confirm-local",
        action="store_true",
        help="Confirm that the configured database is the local development database.",
    )
    args = parser.parse_args()
    if not args.confirm_local:
        parser.error("请使用 --confirm-local，避免误写线上数据库")
    if str(os.getenv("FLASK_CONFIG") or "development").lower() == "production":
        parser.error("生产配置禁止执行本地演示数据恢复")

    app = create_app()
    with app.app_context():
        result = restore()
        print(_json(result))


if __name__ == "__main__":
    main()
