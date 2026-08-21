import json
import mimetypes
import os
import re
from types import SimpleNamespace
from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, request, session
from flask_login import current_user, login_required
from sqlalchemy import desc

from applications.common.utils.rights import authorize, is_super_admin
from applications.extensions import db
from applications.models import (
    StudioAsset,
    StudioGenerationComment,
    StudioGenerationTask,
    StudioModel,
    StudioProduct,
    StudioProductAsset,
    StudioProvider,
    StudioSetting,
    StudioSkill,
)
from applications.common.storage import FileService, StorageError
from applications.studio.generation_service import create_generation, poll_task
from applications.studio.product_prompt import (
    compose_prompt,
    product_reference_descriptors,
    product_reference_urls,
    reference_instructions,
    split_urls,
    video_reference_instructions,
)
from applications.studio.provider_client import (
    ProviderClient,
    extract_chat_content,
    normalize_balance,
)
from applications.studio.retention import delete_generation_task
from applications.studio.request_builder import (
    build_request_body,
    default_parameters_for_model,
    split_option_tokens,
)


studio_bp = Blueprint("studio", __name__, url_prefix="/studio")
GLOBAL_CHAT_MODEL_SETTING_KEY = "global_chat_model_id"


PRODUCT_UPDATE_FIELDS = (
    "description",
    "product_profile",
    "product_memory",
    "generation_rules",
    "forbidden_rules",
)

PRODUCT_UPDATE_LABELS = {
    "description": "产品资料",
    "product_profile": "Product Profile",
    "product_memory": "产品记忆",
    "generation_rules": "生成规则",
    "forbidden_rules": "禁止修改规则",
}

PRODUCT_ASSET_ROLES = {
    "cover",
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "detail",
    "scene",
    "360",
    "reference",
}

FIXED_PRODUCT_ASSET_ROLES = {
    "cover",
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "360",
}

PRODUCT_ASSET_ROLE_SORT = {
    "front": 10,
    "back": 20,
    "left": 30,
    "right": 40,
    "top": 50,
    "bottom": 60,
    "cover": 70,
    "detail": 80,
    "scene": 90,
    "reference": 100,
    "360": 110,
}


def _json(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _parse_json_object(value):
    """Parse a JSON object returned by a chat model, including code fences."""

    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    candidates = [text]
    if text.startswith("```"):
        fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
        candidates.insert(0, fenced.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _normalize_suggested_updates(payload):
    """Keep only complete, human-reviewable product field suggestions."""

    parsed = _parse_json_object(payload)
    source = parsed.get("product_updates")
    if not isinstance(source, dict):
        source = parsed.get("updates")
    if not isinstance(source, dict):
        return {
            "analysis": str(parsed.get("analysis") or "").strip(),
            "updates": {},
        }

    updates = {}
    for field in PRODUCT_UPDATE_FIELDS:
        raw = source.get(field)
        reason = ""
        value = raw
        if isinstance(raw, dict):
            value = raw.get("value", raw.get("suggested", raw.get("content", "")))
            reason = str(raw.get("reason") or raw.get("why") or "").strip()
        if value in (None, ""):
            continue
        value = str(value).strip()
        if not value:
            continue
        updates[field] = {
            "label": PRODUCT_UPDATE_LABELS[field],
            "value": value,
            "reason": reason,
        }
    return {
        "analysis": str(
            parsed.get("analysis")
            or parsed.get("summary")
            or parsed.get("review")
            or ""
        ).strip(),
        "updates": updates,
    }


def _comment_suggested_updates(comment):
    parsed = _json(comment.suggested_updates, {})
    if not isinstance(parsed, dict):
        return {"analysis": "", "updates": {}}
    return {
        "analysis": str(parsed.get("analysis") or "").strip(),
        "updates": parsed.get("updates")
        if isinstance(parsed.get("updates"), dict)
        else {},
    }


def _body():
    return request.get_json(silent=True) or request.form.to_dict()


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_api_key(value):
    """Normalize a submitted provider token without exposing it to the client."""

    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _as_enabled(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "off", "no")


def _int_list(value):
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        values = value
    else:
        values = _json(value, None)
        if not isinstance(values, list):
            values = str(value).replace(",", "\n").splitlines()
    result = []
    for item in values:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(result))


def _asset_is_active(asset):
    return bool(
        asset
        and asset.status == "ACTIVE"
        and not (asset.expires_at and asset.expires_at <= datetime.now())
    )


def _is_usable_asset_url(value):
    """Hide development placeholder URLs from media previews and history."""

    value = str(value or "").strip().lower()
    return bool(value) and not (
        value.startswith("https://mock.invalid/")
        or value.startswith("http://mock.invalid/")
    )


def _asset_dict(asset):
    is_active = _asset_is_active(asset)
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "purpose": asset.purpose,
        "retention_policy": asset.retention_policy,
        "retention_days": current_app.config.get("STUDIO_ASSET_TTL_DAYS", 7)
        if asset.retention_policy == "TTL_7D"
        else None,
        "storage_path": asset.storage_path,
        "public_url": asset.public_url
        if is_active and _is_usable_asset_url(asset.public_url)
        else "",
        "original_filename": asset.original_filename or "",
        "content_type": asset.content_type or "",
        "file_size": asset.file_size or 0,
        "status": asset.status,
        "is_expired": not is_active,
        "created_at": asset.created_at.strftime("%Y-%m-%d %H:%M:%S")
        if asset.created_at
        else "",
        "expires_at": asset.expires_at.strftime("%Y-%m-%d %H:%M:%S")
        if asset.expires_at
        else "",
    }


def _normalize_parameters(raw):
    parameters = raw if isinstance(raw, list) else _json(raw, [])
    if not isinstance(parameters, list):
        return []
    normalized = []
    for item in parameters:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if not field:
            continue
        normalized.append(
            {
                "field": field,
                "label": str(item.get("label") or field),
                "runtime_key": str(item.get("runtime_key") or "").strip(),
                "value": item.get("value", ""),
                "value_type": str(item.get("value_type") or "string").lower(),
                "enabled": _as_enabled(item.get("enabled"), True),
                "hint": str(item.get("hint") or ""),
                "options": _parameter_options(item.get("options")),
                "min": _parameter_number(item.get("min")),
                "max": _parameter_number(item.get("max")),
                "step": _parameter_number(item.get("step")),
            }
        )
    return normalized


def _parameter_options(value):
    """Normalize configured select values into value/label pairs."""

    if isinstance(value, str):
        parsed = _json(value, None)
        value = parsed if isinstance(parsed, list) else re.split(r"[,\n]", value)
    if not isinstance(value, (list, tuple)):
        return []

    normalized = []
    for option in value:
        if isinstance(option, dict):
            option_value = option.get(
                "value",
                option.get("key", option.get("id")),
            )
            option_label = option.get(
                "label",
                option.get("name", option_value),
            )
        else:
            option_value = option
            option_label = option
        expanded = split_option_tokens(option_value)
        for item in expanded:
            normalized.append(
                {
                    "value": str(item),
                    "label": str(
                        item
                        if len(expanded) > 1
                        else (
                            option_label
                            if option_label not in (None, "")
                            else option_value
                        )
                    ),
                }
            )
    return normalized


def _parameter_number(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _provider_dict(provider):
    api_key_configured = bool(provider.api_key)
    return {
        "id": provider.id,
        "name": provider.name,
        "kind": provider.kind,
        "base_url": provider.base_url,
        "api_key_configured": api_key_configured,
        "api_key_masked": "••••••••" if api_key_configured else "",
        "generation_path": provider.generation_path or "",
        "result_path": provider.result_path or "",
        "balance_path": provider.balance_path or "",
        "token_balance_path": getattr(provider, "token_balance_path", None) or "",
        "auth_header": getattr(provider, "auth_header", None) or "Authorization",
        "auth_prefix": getattr(provider, "auth_prefix", None) or "Bearer",
        "timeout": provider.timeout,
        "enabled": bool(provider.enabled),
        "description": provider.description or "",
        "models": [_model_dict(model) for model in provider.models],
    }


def _model_dict(model):
    return {
        "id": model.id,
        "provider_id": model.provider_id,
        "provider_name": model.provider.name if model.provider else "",
        "name": model.name,
        "model_code": model.model_code,
        "media_type": model.media_type,
        "generation_path": model.generation_path or "",
        "result_path": model.result_path or "",
        "parameter_schema": _normalize_parameters(model.parameter_schema),
        "capabilities": _json(model.capabilities, {}),
        "description": model.description or "",
        "enabled": bool(model.enabled),
    }


def _product_dict(product):
    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "brand": product.brand or "",
        "description": product.description or "",
        "product_profile": product.product_profile or "",
        "product_memory": product.product_memory or "",
        "generation_rules": product.generation_rules or "",
        "forbidden_rules": product.forbidden_rules or "",
        "asset_urls": split_urls(product.asset_urls),
        "assets": [
            {
                "id": asset.id,
                "name": asset.name,
                "url": asset.url
                if not asset.storage_asset_id
                or (
                    asset.storage_asset_id
                    and _asset_is_active(
                        StudioAsset.query.filter_by(
                            id=asset.storage_asset_id,
                        ).first()
                    )
                )
                else "",
                "asset_type": asset.asset_type,
                "role": asset.role,
                "storage_asset_id": asset.storage_asset_id,
            }
            for asset in product.assets
            if asset.enabled
        ],
        "enabled": bool(product.enabled),
        "updated_at": product.updated_at.strftime("%Y-%m-%d %H:%M")
        if product.updated_at
        else "",
    }


def _task_dict(task):
    output_assets = (
        StudioAsset.query.filter_by(
            generation_task_id=task.id,
            purpose="GENERATION_OUTPUT",
        )
        .order_by(StudioAsset.id.asc())
        .all()
    )
    reference_assets = (
        StudioAsset.query.filter_by(
            generation_task_id=task.id,
            purpose="GENERATION_REFERENCE",
        )
        .order_by(StudioAsset.id.asc())
        .all()
    )
    output_expired = bool(output_assets) and not any(
        _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
        for asset in output_assets
    )
    reference_expired = bool(reference_assets) and not any(
        _asset_is_active(asset) for asset in reference_assets
    )
    comments = (
        StudioGenerationComment.query.filter_by(generation_task_id=task.id)
        .order_by(StudioGenerationComment.created_at.asc())
        .all()
    )
    return {
        "id": task.id,
        "task_code": task.task_code,
        "media_type": task.media_type,
        "product_id": task.product_id,
        "product_name": task.product.name if task.product else "",
        "model_id": task.model_id,
        "model_name": task.model.name if task.model else "",
        "provider_id": task.model.provider_id if task.model and task.model.provider else None,
        "provider_name": (
            task.model.provider.name
            if task.model and task.model.provider
            else ""
        ),
        "provider_task_id": task.provider_task_id or "",
        "prompt": task.prompt,
        "final_prompt": task.final_prompt or "",
        "status": task.status,
        "progress": task.progress or 0,
        "output_url": (
            next(
                (
                    asset.public_url
                    for asset in output_assets
                    if _asset_is_active(asset)
                    and _is_usable_asset_url(asset.public_url)
                ),
                task.output_url if not output_assets and _is_usable_asset_url(task.output_url) else "",
            )
        ),
        "output_format": task.output_format or "",
        "output_assets": [_asset_dict(asset) for asset in output_assets],
        "reference_assets": [_asset_dict(asset) for asset in reference_assets],
        "comments": [_comment_dict(comment) for comment in comments],
        "output_expired": output_expired,
        "reference_expired": reference_expired,
        "asset_retention_days": current_app.config.get("STUDIO_ASSET_TTL_DAYS", 7),
        "error_message": task.error_message or "",
        "created_at": task.created_at.strftime("%Y-%m-%d %H:%M:%S")
        if task.created_at
        else "",
        "completed_at": task.completed_at.strftime("%Y-%m-%d %H:%M:%S")
        if task.completed_at
        else "",
    }


def _comment_dict(comment):
    suggested_updates = _comment_suggested_updates(comment)
    applied_fields = _json(comment.applied_update_fields, [])
    if not isinstance(applied_fields, list):
        applied_fields = []
    return {
        "id": comment.id,
        "task_code": comment.task.task_code if comment.task else "",
        "user_id": comment.user_id,
        "model_id": comment.model_id,
        "model_name": comment.model.name if comment.model else "",
        "model_code": comment.model.model_code if comment.model else "",
        "comment_type": comment.comment_type,
        "status": comment.status,
        "content": comment.content or "",
        "suggested_updates": suggested_updates,
        "applied_update_fields": [
            field for field in applied_fields if field in PRODUCT_UPDATE_FIELDS
        ],
        "applied_at": comment.applied_at.strftime("%Y-%m-%d %H:%M:%S")
        if comment.applied_at
        else "",
        "applied_by": comment.applied_by,
        "error_message": comment.error_message or "",
        "created_at": comment.created_at.strftime("%Y-%m-%d %H:%M:%S")
        if comment.created_at
        else "",
        "updated_at": comment.updated_at.strftime("%Y-%m-%d %H:%M:%S")
        if comment.updated_at
        else "",
    }


def _can_read_task(task):
    required_permission = "studio:video" if task.media_type == "VIDEO" else "studio:image"
    return (
        _has_permission(required_permission)
        or _has_permission("studio:history")
        or task.user_id == current_user.id
    )


def _chat_provider_snapshot(provider):
    """Materialize provider settings before releasing the MySQL session."""

    return SimpleNamespace(
        base_url=provider.base_url,
        api_key=provider.api_key,
        generation_path=provider.generation_path,
        result_path=provider.result_path,
        balance_path=provider.balance_path,
        token_balance_path=getattr(provider, "token_balance_path", None),
        auth_header=getattr(provider, "auth_header", None),
        auth_prefix=getattr(provider, "auth_prefix", None),
        timeout=provider.timeout,
    )


def _global_chat_models():
    """Return enabled language models that can be selected system-wide."""

    return (
        StudioModel.query.join(StudioProvider)
        .filter(
            StudioModel.enabled == 1,
            StudioModel.media_type == "CHAT",
            StudioProvider.enabled == 1,
        )
        .order_by(StudioProvider.name.asc(), StudioModel.name.asc())
        .all()
    )


def _global_chat_model():
    """Resolve the configured global planner and feedback language model."""

    models = _global_chat_models()
    setting = StudioSetting.query.filter_by(
        setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY
    ).first()
    selected_id = _int_or_none(setting.setting_value) if setting else None
    selected = next((model for model in models if model.id == selected_id), None)
    return selected or (models[0] if models else None)


def _global_chat_model_payload(model):
    if not model:
        return None
    return {
        "id": model.id,
        "name": model.name,
        "model_code": model.model_code,
        "provider_id": model.provider_id,
        "provider_name": model.provider.name if model.provider else "",
        "enabled": bool(model.enabled and model.provider and model.provider.enabled),
    }


def _has_permission(code):
    return code in session.get("permissions", [])


def _can_delete_history():
    return is_super_admin()


@studio_bp.get("/")
@authorize("studio:dashboard")
def dashboard():
    return render_template("studio/dashboard.html")


@studio_bp.get("/image")
@authorize("studio:image")
def image():
    return render_template(
        "studio/image.html",
        can_delete_history=_can_delete_history(),
    )


@studio_bp.get("/video")
@authorize("studio:video")
def video():
    return render_template(
        "studio/video.html",
        can_delete_history=_can_delete_history(),
    )


@studio_bp.get("/products")
@authorize("studio:products")
def products():
    return render_template("studio/products.html")


@studio_bp.get("/forms/product")
@authorize("studio:products")
def product_form():
    return render_template("studio/forms/product.html")


@studio_bp.get("/forms/asset")
@authorize("studio:products")
def asset_form():
    return render_template("studio/forms/asset.html")


@studio_bp.get("/skills")
@authorize("studio:skills")
def skills():
    return render_template("studio/skills.html")


@studio_bp.get("/forms/skill")
@authorize("studio:skills")
def skill_form():
    return render_template("studio/forms/skill.html")


@studio_bp.get("/history")
@authorize("studio:history")
def history():
    return render_template(
        "studio/history.html",
        can_delete_history=_can_delete_history(),
    )


@studio_bp.get("/providers")
@authorize("studio:providers")
def providers():
    return render_template("studio/providers.html")


@studio_bp.get("/forms/provider")
@authorize("studio:providers")
def provider_form():
    return render_template("studio/forms/provider.html")


@studio_bp.get("/forms/model")
@authorize("studio:providers")
def model_form():
    return render_template("studio/forms/model.html")


@studio_bp.get("/api/dashboard")
@authorize("studio:dashboard")
def dashboard_api():
    total = StudioGenerationTask.query.count()
    processing = StudioGenerationTask.query.filter(
        StudioGenerationTask.status.in_(("PENDING", "SUBMITTED", "PROCESSING"))
    ).count()
    succeeded = StudioGenerationTask.query.filter_by(status="SUCCEEDED").count()
    products = StudioProduct.query.filter_by(enabled=1).count()
    models = (
        StudioModel.query.join(StudioProvider)
        .filter(StudioModel.enabled == 1, StudioProvider.enabled == 1)
        .count()
    )
    recent = (
        StudioGenerationTask.query.order_by(desc(StudioGenerationTask.created_at))
        .limit(6)
        .all()
    )
    return jsonify(
        success=True,
        data={
            "total": total,
            "processing": processing,
            "succeeded": succeeded,
            "products": products,
            "models": models,
            "recent": [_task_dict(task) for task in recent],
        },
    )


@studio_bp.get("/api/options")
@login_required
def options():
    media_type = str(request.args.get("media_type") or "IMAGE").upper()
    required_permission = "studio:video" if media_type == "VIDEO" else "studio:image"
    if not _has_permission(required_permission):
        return jsonify(success=False, msg="权限不足"), 403

    model_query = (
        StudioModel.query.join(StudioProvider)
        .filter(StudioModel.enabled == 1, StudioProvider.enabled == 1)
    )
    if media_type in ("IMAGE", "VIDEO"):
        model_query = model_query.filter(StudioModel.media_type == media_type)
    models = model_query.order_by(StudioModel.name).all()
    products_data = (
        StudioProduct.query.filter_by(enabled=1)
        .order_by(StudioProduct.name)
        .all()
    )
    skills = (
        StudioSkill.query.filter_by(enabled=1)
        .order_by(StudioSkill.name)
        .all()
    )
    return jsonify(
        success=True,
        data={
            "models": [_model_dict(model) for model in models],
            "products": [
                {"id": product.id, "name": product.name, "code": product.code}
                for product in products_data
            ],
            "skills": [
                {
                    "id": skill.id,
                    "name": skill.name,
                    "media_type": skill.media_type,
                    "prompt_template": skill.prompt_template or skill.content or "",
                }
                for skill in skills
            ],
        },
    )


def _asset_permission(asset_type, purpose):
    purpose = str(purpose or "").upper()
    asset_type = str(asset_type or "FILE").upper()
    if purpose.startswith("PRODUCT"):
        return "studio:products"
    if purpose == "SKILL":
        return "studio:skills"
    if asset_type == "VIDEO":
        return "studio:video"
    return "studio:image"


@studio_bp.post("/api/assets/upload")
@login_required
def upload_asset():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(success=False, msg="请选择要上传的文件"), 400

    purpose = str(
        request.args.get("purpose")
        or request.form.get("purpose")
        or "GENERATION_REFERENCE"
    ).upper()
    asset_type = str(
        request.args.get("asset_type")
        or request.form.get("asset_type")
        or FileService.infer_asset_type(file.filename, file.mimetype)
    ).upper()
    permission = _asset_permission(asset_type, purpose)
    if not _has_permission(permission):
        return jsonify(success=False, msg="权限不足"), 403
    if asset_type not in ("IMAGE", "VIDEO", "FILE"):
        return jsonify(success=False, msg="不支持的文件类型"), 400
    if purpose not in (
        "GENERATION_REFERENCE",
        "PRODUCT_PENDING",
        "PRODUCT",
        "SKILL",
    ):
        return jsonify(success=False, msg="不支持的文件用途"), 400

    retention = (
        FileService.PERMANENT
        if purpose in ("PRODUCT", "SKILL")
        else FileService.TTL_7D
    )
    try:
        stored = FileService.upload_file(
            file,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention,
            created_by=current_user.id,
            record=False,
        )
        asset = FileService.create_asset_record(
            stored,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention,
            created_by=current_user.id,
        )
        db.session.add(asset)
        db.session.commit()
        return jsonify(
            success=True,
            msg="文件上传成功",
            data=_asset_dict(asset),
        )
    except Exception as exc:
        db.session.rollback()
        try:
            if "stored" in locals():
                FileService.delete_storage(stored.storage_path, checksum=stored.checksum)
        except Exception:
            current_app.logger.exception("failed to roll back uploaded asset")
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.post("/api/generate")
@login_required
def generate():
    data = _body()
    media_type = str(data.get("media_type") or "IMAGE").upper()
    required_permission = "studio:video" if media_type == "VIDEO" else "studio:image"
    if not _has_permission(required_permission):
        return jsonify(success=False, msg="权限不足"), 403
    try:
        task = create_generation(
            user_id=current_user.id,
            media_type=media_type,
            model_id=data.get("model_id"),
            product_id=_int_or_none(data.get("product_id")),
            prompt=data.get("prompt") or "",
            options={
                "count": data.get("count", 1),
                "aspect_ratio": data.get("aspect_ratio"),
                "resolution": data.get("resolution"),
                "duration": data.get("duration"),
                "generate_audio": data.get("generate_audio"),
                "reference_images": data.get("reference_images"),
                "reference_videos": data.get("reference_videos"),
                "reference_asset_ids": _int_list(data.get("reference_asset_ids")),
                "reference_video_asset_ids": _int_list(
                    data.get("reference_video_asset_ids")
                ),
                "prepared_prompt": data.get("prepared_prompt"),
                "skill_prompt": data.get("skill_prompt"),
                "extra_fields": _json(data.get("extra_fields"), {}),
            },
        )
        return jsonify(success=True, msg="任务已提交", data=_task_dict(task))
    except Exception as exc:
        db.session.rollback()
        return jsonify(success=False, msg=str(exc)), 400


def _prepare_prompt_request():
    """Build a prompt directly or plan it with the selected global chat model."""

    data = _body()
    media_type = str(data.get("media_type") or "IMAGE").upper()
    if media_type not in ("IMAGE", "VIDEO"):
        return jsonify(success=False, msg="不支持的创作类型"), 400
    required_permission = "studio:video" if media_type == "VIDEO" else "studio:image"
    if not _has_permission(required_permission):
        return jsonify(success=False, msg="权限不足"), 403

    product_id = _int_or_none(data.get("product_id"))
    product = (
        StudioProduct.query.filter_by(id=product_id, enabled=1).first()
        if product_id
        else None
    )
    if product_id and not product:
        return jsonify(success=False, msg="关联产品不存在或已停用"), 400

    creative_prompt = str(data.get("prompt") or "").strip()
    if not creative_prompt:
        return jsonify(success=False, msg="创意描述不能为空"), 400

    requested_image_ids = _int_list(data.get("reference_asset_ids"))
    reference_assets = (
        StudioAsset.query.filter(
            StudioAsset.id.in_(requested_image_ids),
            StudioAsset.status == "ACTIVE",
            StudioAsset.purpose == "GENERATION_REFERENCE",
            StudioAsset.asset_type == "IMAGE",
        ).all()
        if requested_image_ids
        else []
    )
    image_assets_by_id = {asset.id: asset for asset in reference_assets}
    reference_assets = [
        image_assets_by_id[asset_id]
        for asset_id in requested_image_ids
        if asset_id in image_assets_by_id
    ]
    if len(reference_assets) != len(set(requested_image_ids)):
        return jsonify(success=False, msg="额外参考图不存在、已过期或用途不正确"), 400
    for asset in reference_assets:
        if asset.created_by not in (None, current_user.id):
            return jsonify(success=False, msg="不能使用其他用户上传的参考图"), 403
        if not _asset_is_active(asset) or not _is_usable_asset_url(asset.public_url):
            return jsonify(success=False, msg="额外参考图已经失效，请重新上传"), 400

    requested_video_ids = _int_list(data.get("reference_video_asset_ids"))
    reference_videos = (
        StudioAsset.query.filter(
            StudioAsset.id.in_(requested_video_ids),
            StudioAsset.status == "ACTIVE",
            StudioAsset.purpose == "GENERATION_REFERENCE",
            StudioAsset.asset_type == "VIDEO",
        ).all()
        if requested_video_ids
        else []
    )
    video_assets_by_id = {asset.id: asset for asset in reference_videos}
    reference_videos = [
        video_assets_by_id[asset_id]
        for asset_id in requested_video_ids
        if asset_id in video_assets_by_id
    ]
    if len(reference_videos) != len(set(requested_video_ids)):
        return jsonify(success=False, msg="额外参考视频不存在、已过期或用途不正确"), 400
    for asset in reference_videos:
        if asset.created_by not in (None, current_user.id):
            return jsonify(success=False, msg="不能使用其他用户上传的参考视频"), 403
        if not _asset_is_active(asset) or not _is_usable_asset_url(asset.public_url):
            return jsonify(success=False, msg="额外参考视频已经失效，请重新上传"), 400

    extra_image_urls = [asset.public_url for asset in reference_assets]
    extra_image_urls.extend(split_urls(data.get("reference_images")))
    extra_video_urls = [asset.public_url for asset in reference_videos]
    extra_video_urls.extend(split_urls(data.get("reference_videos")))
    skill_prompt = str(data.get("skill_prompt") or "").strip()
    descriptors = product_reference_descriptors(
        product,
        extra_image_urls,
        media_type=media_type,
    )
    ordered_references = reference_instructions(descriptors)
    ordered_video_references = video_reference_instructions(extra_video_urls)
    ordered_reference_context = "\n".join(
        part for part in (ordered_references, ordered_video_references) if part
    )
    planning_required = bool(product or skill_prompt)

    if not planning_required:
        return jsonify(
            success=True,
            msg="未关联产品或 Skill，直接使用创意描述",
            data={
                "final_prompt": creative_prompt,
                "product_name": "",
                "reference_instruction": ordered_reference_context,
                "planner_model": "",
                "planner_model_name": "",
                "references": descriptors,
            },
        )

    chat_model = _global_chat_model()
    if not chat_model or not chat_model.provider:
        return jsonify(success=False, msg="请先在模型供应商中选择启用的全局语言模型"), 400
    if not str(chat_model.provider.api_key or "").strip():
        return jsonify(
            success=False,
            msg="全局语言模型尚未配置 API Key，请先编辑对应供应商",
        ), 400

    media_label = "图片" if media_type == "IMAGE" else "视频"
    context_parts = [
        f"请为一次电商产品{media_label}生成任务规划最终 Prompt。",
        "用户创意描述是最高优先级，必须先准确提取并保留创意目标、主体、场景、构图、镜头、光线、动作和风格。",
        (
            "然后识别关联产品，明确生成的产品名称；视频只读取产品名称、品牌、"
            "Product Profile、产品记忆、生成规则和禁止修改规则作为固定约束。"
            if media_type == "VIDEO"
            else "然后识别关联产品，明确生成的产品名称；再结合产品资料、Product Profile、产品记忆、生成规则和禁止修改规则。"
        ),
        "产品身份、外形结构、材质、颜色、品牌和关键接口不能被创意描述随意改变。",
        "禁止修改规则必须作为约束写入最终 Prompt，而不是被忽略。",
        f"用户创意描述：{creative_prompt}",
    ]
    if skill_prompt:
        context_parts.append(f"创作 Skill 指令：{skill_prompt}")
    if product:
        product_context = [
            f"关联产品名称：{product.name or ''}",
            f"产品编码：{product.code or ''}",
            f"品牌：{product.brand or ''}",
        ]
        if media_type != "VIDEO":
            product_context.append(f"产品资料：{product.description or ''}")
        product_context.extend(
            [
                f"Product Profile：{product.product_profile or ''}",
                f"产品记忆：{product.product_memory or ''}",
                f"生成规则：{product.generation_rules or ''}",
                f"禁止修改规则：{product.forbidden_rules or ''}",
            ]
        )
        context_parts.extend(product_context)
    if ordered_reference_context:
        context_parts.append(
            "本次请求会按顺序把产品中心素材放在前面，再放入本次上传的额外素材。"
            "图片和视频的顺序、URL、角色必须明确写入最终 Prompt；视频只允许作为"
            "动作与镜头参考，不能改变产品固定结构：\n"
            + ordered_reference_context
        )
    context_parts.append(
        "请严格只返回 JSON，不要 Markdown 代码块，结构为："
        '{"final_prompt":"可直接发送给上游模型的完整中文 Prompt",'
        '"product_name":"识别出的产品名称",'
        '"reference_instruction":"参考素材顺序说明"}。'
        "final_prompt 必须以用户创意为主线，产品约束接在创意后面，"
        "并包含每个参考图片和参考视频的 URL 及顺序说明；不要输出反向提示词。"
    )
    content_blocks = [{"type": "text", "text": "\n".join(context_parts)}]
    content_blocks.extend(
        {
            "type": "image_url",
            "image_url": {"url": descriptor["url"]},
        }
        for descriptor in descriptors
        if descriptor.get("asset_type", "IMAGE") in ("IMAGE", "BOTH")
        and descriptor.get("role") != "360"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是电商产品视觉生成规划器。"
                "你的职责是把创意描述、产品固定信息、Skill 和参考素材整理成一个可执行 Prompt。"
                "优先保护产品身份，不要自行捏造产品规格。"
            ),
        },
        {"role": "user", "content": content_blocks},
    ]

    runtime = {
        "messages": messages,
        "max_tokens": 1200,
        "temperature": 0.1,
    }
    body = build_request_body(chat_model, runtime)
    body.setdefault("model", chat_model.model_code)
    body.setdefault("messages", messages)
    body.setdefault("max_tokens", 1200)
    body.setdefault("temperature", 0.1)
    provider_snapshot = _chat_provider_snapshot(chat_model.provider)
    model_snapshot = SimpleNamespace(
        media_type="CHAT",
        generation_path=chat_model.generation_path or "/v1/chat/completions",
        result_path=None,
    )
    try:
        client = ProviderClient(provider_snapshot)
        db.session.remove()
        response = client.chat_completion(model_snapshot, body)
        content = extract_chat_content(response)
        parsed = _parse_json_object(content)
        final_prompt = str(
            parsed.get("final_prompt")
            or parsed.get("prompt")
            or content
            or ""
        ).strip()
        if not final_prompt:
            raise ValueError("全局语言模型没有返回可用的最终 Prompt")
        reference_instruction = str(
            parsed.get("reference_instruction") or ordered_reference_context
        ).strip()
        if (
            ordered_reference_context
            and ordered_reference_context not in reference_instruction
        ):
            reference_instruction = (
                reference_instruction.rstrip()
                + ("\n" if reference_instruction else "")
                + ordered_reference_context
            )
        if reference_instruction and reference_instruction not in final_prompt:
            final_prompt = (
                final_prompt.rstrip()
                + "\n\n参考素材顺序与角色约束：\n"
                + reference_instruction
            )
        return jsonify(
            success=True,
            msg="创作 Prompt 已完成规划",
            data={
                "final_prompt": final_prompt,
                "product_name": str(
                    parsed.get("product_name") or (product.name if product else "")
                ),
                "reference_instruction": reference_instruction,
                "planner_model": chat_model.model_code,
                "planner_model_name": chat_model.name,
                "references": descriptors,
            },
        )
    except Exception as exc:
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.post("/api/prompt/prepare")
@login_required
def prepare_image_prompt():
    """Keep the original endpoint while using the global planner implementation."""

    return _prepare_prompt_request()


@studio_bp.get("/api/tasks/<task_code>")
@login_required
def task_status(task_code):
    task = StudioGenerationTask.query.filter_by(task_code=task_code).first()
    if not task:
        return jsonify(success=False, msg="任务不存在"), 404
    if not _can_read_task(task):
        return jsonify(success=False, msg="权限不足"), 403
    if task.status in ("SUBMITTED", "PROCESSING"):
        poll_task(task)
        task = StudioGenerationTask.query.get(task.id) or task
    return jsonify(success=True, data=_task_dict(task))


def _analyze_task_feedback(task_code):
    """Analyze operator feedback and propose product-center updates."""

    task = StudioGenerationTask.query.filter_by(task_code=task_code).first()
    if not task:
        return jsonify(success=False, msg="任务不存在"), 404
    if not _can_read_task(task):
        return jsonify(success=False, msg="权限不足"), 403
    if task.media_type != "IMAGE":
        return jsonify(success=False, msg="当前仅支持图片生成结果的意见反馈"), 400
    if task.status != "SUCCEEDED":
        return jsonify(success=False, msg="图片任务尚未完成，暂时不能提交意见反馈"), 400

    feedback = str(_body().get("feedback") or "").strip()
    if not feedback:
        return jsonify(success=False, msg="请先填写本次生成的不满意、瑕疵或变形说明"), 400

    output_assets = (
        StudioAsset.query.filter_by(
            generation_task_id=task.id,
            purpose="GENERATION_OUTPUT",
            asset_type="IMAGE",
            status="ACTIVE",
        )
        .order_by(StudioAsset.id.asc())
        .all()
    )
    output_urls = [
        asset.public_url
        for asset in output_assets
        if _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
    ]
    if not output_urls and _is_usable_asset_url(task.output_url):
        output_urls = [task.output_url]
    if not output_urls:
        return jsonify(success=False, msg="没有可供意见反馈使用的图片资产"), 400

    chat_model = _global_chat_model()
    if not chat_model or not chat_model.provider:
        return jsonify(success=False, msg="请先在模型供应商中选择启用的全局语言模型"), 400
    if not str(chat_model.provider.api_key or "").strip():
        return jsonify(
            success=False,
            msg="全局语言模型尚未配置 API Key，请先编辑对应供应商",
        ), 400

    reference_assets = (
        StudioAsset.query.filter_by(
            generation_task_id=task.id,
            purpose="GENERATION_REFERENCE",
            asset_type="IMAGE",
            status="ACTIVE",
        )
        .order_by(StudioAsset.id.asc())
        .all()
    )
    generation_reference_urls = [
        asset.public_url
        for asset in reference_assets
        if _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
    ]
    product_urls = product_reference_urls(
        task.product,
        generation_reference_urls,
        media_type="IMAGE",
    )
    image_urls = list(dict.fromkeys(output_urls + product_urls))[:14]
    product = task.product
    context_parts = [
        "请分析这次电商图片生成结果，并以中文给出可执行的意见反馈。",
        "请重点检查：产品主体是否保持一致、结构和材质是否跑偏、品牌信息是否正确、画面是否符合创意要求、是否违反禁止修改规则，以及下一轮生成可以怎样改进。",
        f"生成任务编号：{task.task_code}",
        f"原始创意：{task.prompt}",
        f"最终提示词：{task.final_prompt or task.prompt}",
        f"操作者意见反馈：{feedback}",
        "下面先提供生成结果图片，再提供本次任务引用的产品/参考图片。",
    ]
    if product:
        context_parts.extend(
            [
                f"产品名称：{product.name or ''}",
                f"品牌信息：{product.brand or ''}",
                f"产品资料：{product.description or ''}",
                f"Product Profile：{product.product_profile or ''}",
                f"产品记忆：{product.product_memory or ''}",
                f"生成规则：{product.generation_rules or ''}",
                f"禁止修改规则：{product.forbidden_rules or ''}",
            ]
        )
    else:
        context_parts.append(
            "本次任务没有关联产品中心；只分析生成图片和操作者意见，"
            "不要提出或应用产品中心字段修改建议。"
        )
    content_blocks = [{"type": "text", "text": "\n".join(context_parts)}]
    content_blocks.extend(
        {
            "type": "image_url",
            "image_url": {"url": url},
        }
        for url in image_urls
    )
    if product:
        content_blocks[0]["text"] += (
            "\n请严格只返回 JSON，不要使用 Markdown 代码块，结构如下："
            "\n{"
            '"analysis":"中文意见反馈与下一轮调整建议",'
            '"product_updates":{'
            '"description":{"value":"产品资料完整建议值","reason":"依据"},'
            '"product_profile":{"value":"Product Profile完整建议值","reason":"依据"},'
            '"product_memory":{"value":"产品记忆完整建议值","reason":"依据"},'
            '"generation_rules":{"value":"可选的生成规则完整建议值","reason":"依据"},'
            '"forbidden_rules":{"value":"可选的禁止修改规则完整建议值","reason":"依据"}'
            "}"
            "}"
            "\n没有足够证据修改的字段不要返回。建议值必须是可直接替换该字段的完整文本，"
            "而不是零散片段。"
        )
    else:
        content_blocks[0]["text"] += (
            '\n请严格只返回 JSON，不要使用 Markdown 代码块，结构如下：'
            '{"analysis":"中文意见反馈与下一轮调整建议","product_updates":{}}。'
        )
    messages = [
        {
            "role": "system",
            "content": (
                "你是电商视觉质检与产品记忆维护助手。"
                "请基于产品字段、图片证据和操作者意见回答，不要臆造图片中看不到的信息。"
                "你不负责生成图片，只负责分析生成结果是否保持产品一致性，"
                + (
                    "并在证据充分时提出产品字段的完整改写建议。"
                    if product
                    else "当前没有关联产品，只给出图片质量和下一轮创作建议，不提出产品字段改写。"
                )
            ),
        },
        {"role": "user", "content": content_blocks},
    ]
    runtime = {
        "messages": messages,
        "max_tokens": 800,
        "temperature": 0.2,
    }
    body = build_request_body(chat_model, runtime)
    body.setdefault("model", chat_model.model_code)
    body.setdefault("messages", messages)
    body.setdefault("max_tokens", 800)
    body.setdefault("temperature", 0.2)
    provider_snapshot = _chat_provider_snapshot(chat_model.provider)
    model_snapshot = SimpleNamespace(
        media_type="CHAT",
        generation_path=chat_model.generation_path or "/v1/chat/completions",
        result_path=None,
    )
    comment = StudioGenerationComment(
        generation_task_id=task.id,
        user_id=current_user.id,
        model_id=chat_model.id,
        comment_type="FEEDBACK",
        status="PENDING",
        request_body=json.dumps(body, ensure_ascii=False, default=str),
    )
    db.session.add(comment)
    db.session.commit()
    comment_id = comment.id

    try:
        client = ProviderClient(provider_snapshot)
        db.session.remove()
        response = client.chat_completion(model_snapshot, body)
        content = extract_chat_content(response)
        if not content:
            raise ValueError("全局语言模型返回了空的意见反馈")
        comment = StudioGenerationComment.query.get(comment_id)
        if not comment:
            return jsonify(success=False, msg="意见反馈记录不存在"), 500
        comment.status = "SUCCEEDED"
        normalized = _normalize_suggested_updates(content)
        comment.content = normalized["analysis"] or content
        comment.suggested_updates = json.dumps(
            normalized,
            ensure_ascii=False,
            default=str,
        )
        comment.response_payload = json.dumps(
            response,
            ensure_ascii=False,
            default=str,
        )
        comment.error_message = None
        db.session.commit()
        return jsonify(success=True, msg="意见反馈已完成", data=_comment_dict(comment))
    except Exception as exc:
        comment = StudioGenerationComment.query.get(comment_id)
        if comment:
            comment.status = "FAILED"
            comment.error_message = str(exc)
            db.session.commit()
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.post("/api/tasks/<task_code>/comments/analyze")
@login_required
def analyze_task(task_code):
    """Keep the original endpoint while using the feedback implementation."""

    return _analyze_task_feedback(task_code)


@studio_bp.post("/api/tasks/<task_code>/comments/<int:comment_id>/apply-product-updates")
@authorize("studio:products", log=True)
def apply_product_updates(task_code, comment_id):
    """Apply only operator-selected AI suggestions to the linked product."""

    task = StudioGenerationTask.query.filter_by(task_code=task_code).first()
    if not task:
        return jsonify(success=False, msg="任务不存在"), 404
    if not task.product:
        return jsonify(success=False, msg="当前任务没有关联产品"), 400

    comment = StudioGenerationComment.query.filter_by(
        id=comment_id,
        generation_task_id=task.id,
    ).first()
    if not comment:
        return jsonify(success=False, msg="分析记录不存在"), 404
    if comment.status != "SUCCEEDED":
        return jsonify(success=False, msg="只有成功的分析结果才能应用"), 400

    data = _body()
    selected = data.get("fields", [])
    if isinstance(selected, str):
        selected = _json(selected, [])
    if not isinstance(selected, list):
        return jsonify(success=False, msg="请选择要应用的产品字段"), 400
    selected = list(dict.fromkeys(
        field for field in selected if field in PRODUCT_UPDATE_FIELDS
    ))
    if not selected:
        return jsonify(success=False, msg="请选择要应用的产品字段"), 400

    suggestion = _comment_suggested_updates(comment)
    updates = suggestion["updates"]
    missing = [field for field in selected if field not in updates]
    if missing:
        return jsonify(
            success=False,
            msg="所选字段没有可应用的分析建议：" +
            "、".join(PRODUCT_UPDATE_LABELS[field] for field in missing),
        ), 400

    product = task.product
    for field in selected:
        value = updates[field].get("value") if isinstance(updates[field], dict) else None
        if value is not None:
            setattr(product, field, str(value).strip())

    applied_fields = _json(comment.applied_update_fields, [])
    if not isinstance(applied_fields, list):
        applied_fields = []
    comment.applied_update_fields = json.dumps(
        list(dict.fromkeys(applied_fields + selected)),
        ensure_ascii=False,
    )
    comment.applied_at = datetime.now()
    comment.applied_by = current_user.id
    db.session.add(product)
    db.session.add(comment)
    db.session.commit()
    return jsonify(
        success=True,
        msg="已将选中的分析建议应用到产品中心",
        data={
            "comment": _comment_dict(comment),
            "product": _product_dict(product),
        },
    )


@studio_bp.get("/api/history")
@authorize("studio:history")
def history_api():
    code = (request.args.get("code") or "").strip()
    media_type = str(request.args.get("media_type") or "").upper()
    query = StudioGenerationTask.query.order_by(desc(StudioGenerationTask.created_at))
    if code:
        query = query.filter_by(task_code=code)
    if media_type in ("IMAGE", "VIDEO"):
        query = query.filter_by(media_type=media_type)
    tasks = query.limit(100).all()
    return jsonify(success=True, data=[_task_dict(task) for task in tasks])


@studio_bp.delete("/api/history/<int:task_id>")
@authorize("studio:history", log=True)
def delete_history_api(task_id):
    if not _can_delete_history():
        return jsonify(success=False, msg="仅超级管理员可以删除生成历史"), 403

    task = StudioGenerationTask.query.filter_by(id=task_id).first()
    if not task:
        return jsonify(success=False, msg="历史任务不存在"), 404

    try:
        result = delete_generation_task(task)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("failed to delete generation task id=%s", task_id)
        return jsonify(success=False, msg=str(exc)), 400
    if not result["deleted"]:
        return jsonify(success=False, msg=result["message"]), 400
    return jsonify(success=True, msg=result["message"])


@studio_bp.get("/api/products")
@authorize("studio:products")
def products_api():
    products = (
        StudioProduct.query.filter_by(enabled=1)
        .order_by(desc(StudioProduct.updated_at))
        .all()
    )
    return jsonify(success=True, data=[_product_dict(product) for product in products])


@studio_bp.post("/api/products")
@authorize("studio:products")
def save_product():
    data = _body()
    product_id = _int_or_none(data.get("id"))
    product = (
        StudioProduct.query.filter_by(id=product_id).first()
        if product_id
        else StudioProduct()
    )
    if product_id and not product:
        return jsonify(success=False, msg="产品不存在"), 404

    code = str(data.get("code") or "").strip()
    name = str(data.get("name") or "").strip()
    if not code or not name:
        return jsonify(success=False, msg="产品编码和名称不能为空"), 400
    duplicate = StudioProduct.query.filter(
        StudioProduct.code == code,
        StudioProduct.id != (product.id or 0),
    ).first()
    if duplicate:
        return jsonify(success=False, msg="产品编码已经存在"), 400

    product.code = code
    product.name = name
    product.brand = data.get("brand") or ""
    product.description = data.get("description") or ""
    product.product_profile = data.get("product_profile") or ""
    product.product_memory = data.get("product_memory") or ""
    product.generation_rules = data.get("generation_rules") or ""
    product.forbidden_rules = data.get("forbidden_rules") or ""
    product.asset_urls = json.dumps(split_urls(data.get("asset_urls")), ensure_ascii=False)
    product.enabled = 1
    product.created_by = product.created_by or current_user.id
    db.session.add(product)
    db.session.commit()
    return jsonify(success=True, msg="产品已保存", data=_product_dict(product))


@studio_bp.delete("/api/products/<int:product_id>")
@authorize("studio:products")
def delete_product(product_id):
    product = StudioProduct.query.filter_by(id=product_id).first()
    if not product:
        return jsonify(success=False, msg="产品不存在"), 404
    for asset in product.assets:
        asset.enabled = 0
        if asset.storage_asset_id:
            stored_asset = StudioAsset.query.filter_by(
                id=asset.storage_asset_id,
                status="ACTIVE",
            ).first()
            if stored_asset:
                FileService.delete_asset(stored_asset)
    product.enabled = 0
    db.session.commit()
    return jsonify(success=True, msg="产品已停用")


@studio_bp.post("/api/products/<int:product_id>/assets")
@authorize("studio:products")
def save_product_asset(product_id):
    product = StudioProduct.query.filter_by(id=product_id, enabled=1).first()
    if not product:
        return jsonify(success=False, msg="product not found or disabled"), 400

    data = _body()
    url = str(data.get("url") or "").strip()
    storage_asset_id = _int_or_none(data.get("storage_asset_id"))
    storage_asset = (
        StudioAsset.query.filter(
            StudioAsset.id == storage_asset_id,
            StudioAsset.status == "ACTIVE",
        ).first()
        if storage_asset_id
        else None
    )
    if storage_asset:
        if storage_asset.purpose not in ("PRODUCT_PENDING", "PRODUCT"):
            return jsonify(success=False, msg="文件用途不允许作为产品素材"), 400
        requested_type = str(data.get("asset_type") or "").upper()
        if requested_type not in ("", "BOTH") and storage_asset.asset_type != requested_type:
            return jsonify(success=False, msg="素材类型与上传文件类型不匹配"), 400
        if storage_asset.created_by not in (None, current_user.id):
            return jsonify(success=False, msg="不能使用其他用户上传的产品素材"), 403
        storage_asset.purpose = "PRODUCT"
        storage_asset.retention_policy = FileService.PERMANENT
        storage_asset.expires_at = None
        url = storage_asset.public_url
    asset_role = str(data.get("role") or "reference").strip().lower()
    asset_type = str(data.get("asset_type") or "IMAGE").strip().upper()
    if asset_role not in PRODUCT_ASSET_ROLES:
        return jsonify(success=False, msg="不支持的产品素材位置"), 400
    if asset_type not in ("IMAGE", "VIDEO", "BOTH"):
        return jsonify(success=False, msg="不支持的产品素材类型"), 400
    if asset_role == "360" and asset_type not in ("VIDEO", "BOTH"):
        return jsonify(success=False, msg="360 视频素材必须是视频类型"), 400
    if not product or not url:
        return jsonify(success=False, msg="产品或素材 URL 不正确"), 400
    replace_requested = data.get("replace_existing")
    replace_requested = (
        replace_requested is True
        or str(replace_requested or "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    replace_existing = asset_role in FIXED_PRODUCT_ASSET_ROLES or replace_requested
    if replace_existing:
        previous_assets = StudioProductAsset.query.filter_by(
            product_id=product.id,
            role=asset_role,
            enabled=1,
        ).all()
        for previous in previous_assets:
            if previous.storage_asset_id:
                previous_storage = StudioAsset.query.filter_by(
                    id=previous.storage_asset_id,
                    status="ACTIVE",
                ).first()
                if previous_storage:
                    # The new slot value wins. Remove the old managed file
                    # before the replacement becomes visible to generation.
                    FileService.delete_asset(previous_storage)
            previous.enabled = 0

    asset = StudioProductAsset(
        product_id=product.id,
        name=str(data.get("name") or "产品参考素材").strip(),
        url=url,
        asset_type=asset_type,
        role=asset_role,
        sort=PRODUCT_ASSET_ROLE_SORT.get(asset_role, 100),
        storage_asset_id=storage_asset.id if storage_asset else None,
    )
    db.session.add(asset)
    db.session.commit()
    return jsonify(success=True, msg="素材已添加", data=_product_dict(product))


@studio_bp.delete("/api/products/<int:product_id>/assets/<int:asset_id>")
@authorize("studio:products")
def delete_product_asset(product_id, asset_id):
    asset = StudioProductAsset.query.filter_by(
        id=asset_id,
        product_id=product_id,
    ).first()
    if not asset:
        return jsonify(success=False, msg="素材不存在"), 404
    if asset.storage_asset_id:
        stored_asset = StudioAsset.query.filter_by(
            id=asset.storage_asset_id,
            status="ACTIVE",
        ).first()
        if stored_asset:
            FileService.delete_asset(stored_asset)
    asset.enabled = 0
    db.session.commit()
    product = StudioProduct.query.filter_by(id=product_id).first()
    return jsonify(success=True, msg="素材已停用", data=_product_dict(product))


@studio_bp.get("/api/providers")
@authorize("studio:providers")
def providers_api():
    providers = StudioProvider.query.order_by(StudioProvider.name).all()
    return jsonify(success=True, data=[_provider_dict(provider) for provider in providers])


@studio_bp.get("/api/ai-config")
@authorize("studio:providers")
def ai_config_api():
    models = _global_chat_models()
    selected = _global_chat_model()
    return jsonify(
        success=True,
        data={
            "global_chat_model_id": selected.id if selected else None,
            "global_chat_model": _global_chat_model_payload(selected),
            "models": [_global_chat_model_payload(model) for model in models],
        },
    )


@studio_bp.post("/api/ai-config")
@authorize("studio:providers")
def save_ai_config():
    model_id = _int_or_none(_body().get("global_chat_model_id"))
    model = (
        StudioModel.query.join(StudioProvider)
        .filter(
            StudioModel.id == model_id,
            StudioModel.enabled == 1,
            StudioModel.media_type == "CHAT",
            StudioProvider.enabled == 1,
        )
        .first()
        if model_id
        else None
    )
    if not model:
        return jsonify(success=False, msg="请选择启用的语言模型"), 400

    setting = StudioSetting.query.filter_by(
        setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY
    ).first()
    if not setting:
        setting = StudioSetting(
            setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
            description="图片与视频创作在关联产品或 Skill 时使用的全局语言模型",
        )
    setting.setting_value = str(model.id)
    db.session.add(setting)
    db.session.commit()
    return jsonify(
        success=True,
        msg="全局语言模型已切换",
        data={
            "global_chat_model_id": model.id,
            "global_chat_model": _global_chat_model_payload(model),
        },
    )


@studio_bp.post("/api/providers")
@authorize("studio:providers")
def save_provider():
    data = _body()
    provider_id = _int_or_none(data.get("id"))
    provider = (
        StudioProvider.query.filter_by(id=provider_id).first()
        if provider_id
        else StudioProvider()
    )
    if provider_id and not provider:
        return jsonify(success=False, msg="供应商不存在"), 404

    name = str(data.get("name") or "").strip()
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url:
        return jsonify(success=False, msg="供应商名称和 Base URL 不能为空"), 400

    provider.name = name
    provider.kind = data.get("kind") or "relay"
    provider.base_url = base_url
    submitted_api_key = _clean_api_key(data.get("api_key"))
    # An empty password field during edit means "keep the existing token".
    # A non-empty value is written to StudioProvider.api_key and committed
    # together with the rest of the provider configuration.
    if submitted_api_key is not None:
        provider.api_key = submitted_api_key
    provider.generation_path = data.get("generation_path") or "/v1/images/generations"
    provider.result_path = data.get("result_path") or "/v1/images/generations/{task_id}"
    provider.balance_path = data.get("balance_path") or "/v1/user/balance"
    provider.token_balance_path = data.get("token_balance_path") or "/v1/balance"
    provider.auth_header = data.get("auth_header") or "Authorization"
    provider.auth_prefix = data.get("auth_prefix") or "Bearer"
    provider.timeout = max(30, _int_or_none(data.get("timeout")) or 120)
    provider.enabled = 1 if _as_enabled(data.get("enabled"), True) else 0
    provider.description = data.get("description") or ""
    db.session.add(provider)
    db.session.commit()
    return jsonify(success=True, msg="供应商已保存", data=_provider_dict(provider))


@studio_bp.post("/api/providers/<int:provider_id>/balance")
@authorize("studio:providers")
def provider_balance(provider_id):
    provider = StudioProvider.query.filter_by(id=provider_id, enabled=1).first()
    if not provider:
        return jsonify(success=False, msg="供应商不存在或已停用"), 404
    if not provider.api_key:
        return jsonify(success=False, msg="请先配置 API Key"), 400
    scope = request.args.get("scope") or "user"
    if scope not in ("user", "token"):
        return jsonify(success=False, msg="不支持的余额类型"), 400
    try:
        client = ProviderClient(provider)
        db.session.remove()
        data = client.get_balance(scope=scope)
        return jsonify(
            success=True,
            msg="余额已更新",
            data={
                "scope": scope,
                "balance": normalize_balance(data),
                "payload": data,
            },
        )
    except Exception as exc:
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.delete("/api/providers/<int:provider_id>")
@authorize("studio:providers")
def delete_provider(provider_id):
    provider = StudioProvider.query.filter_by(id=provider_id).first()
    if not provider:
        return jsonify(success=False, msg="供应商不存在"), 404
    provider.enabled = 0
    for model in provider.models:
        model.enabled = 0
    db.session.commit()
    return jsonify(success=True, msg="供应商已停用")


@studio_bp.post("/api/models")
@authorize("studio:providers")
def save_model():
    data = _body()
    model_id = _int_or_none(data.get("id"))
    model = (
        StudioModel.query.filter_by(id=model_id).first()
        if model_id
        else StudioModel()
    )
    if model_id and not model:
        return jsonify(success=False, msg="模型不存在"), 404

    provider_id = _int_or_none(data.get("provider_id"))
    provider = StudioProvider.query.filter_by(id=provider_id, enabled=1).first()
    if not provider:
        return jsonify(success=False, msg="供应商不存在或已停用"), 400

    name = str(data.get("name") or "").strip()
    model_code = str(data.get("model_code") or "").strip()
    media_type = str(data.get("media_type") or "IMAGE").upper()
    if not name or not model_code:
        return jsonify(success=False, msg="模型名称和模型标识不能为空"), 400
    if media_type not in ("IMAGE", "VIDEO", "CHAT"):
        return jsonify(success=False, msg="模型类型必须是图片、视频或语言模型"), 400

    duplicate = StudioModel.query.filter(
        StudioModel.provider_id == provider.id,
        StudioModel.model_code == model_code,
        StudioModel.id != (model.id or 0),
    ).first()
    if duplicate:
        return jsonify(success=False, msg="该供应商下的模型标识已经存在"), 400

    parameters = _normalize_parameters(data.get("parameter_schema"))
    if not parameters:
        parameters = default_parameters_for_model(model_code, media_type)
    model.provider_id = provider.id
    model.name = name
    model.model_code = model_code
    model.media_type = media_type
    model.generation_path = data.get("generation_path") or None
    model.result_path = data.get("result_path") or None
    model.parameter_schema = json.dumps(parameters, ensure_ascii=False)
    model.capabilities = json.dumps(_json(data.get("capabilities"), {}), ensure_ascii=False)
    model.description = data.get("description") or ""
    model.enabled = 1
    db.session.add(model)
    db.session.commit()
    return jsonify(success=True, msg="模型已保存", data=_model_dict(model))


@studio_bp.delete("/api/models/<int:model_id>")
@authorize("studio:providers")
def delete_model(model_id):
    model = StudioModel.query.filter_by(id=model_id).first()
    if not model:
        return jsonify(success=False, msg="模型不存在"), 404
    model.enabled = 0
    db.session.commit()
    return jsonify(success=True, msg="模型已停用")


def _skill_dict(skill):
    storage_asset = (
        StudioAsset.query.filter_by(id=skill.storage_asset_id).first()
        if skill.storage_asset_id
        else None
    )
    download_url = (
        storage_asset.public_url
        if storage_asset
        and _asset_is_active(storage_asset)
        and _is_usable_asset_url(storage_asset.public_url)
        else ""
    )
    return {
        "id": skill.id,
        "name": skill.name,
        "code": skill.code,
        "media_type": skill.media_type,
        "version": skill.version,
        "tags": skill.tags or "",
        "prompt_template": skill.prompt_template or "",
        "file_name": skill.file_name or "",
        "file_type": skill.file_type or "",
        "content": skill.content or "",
        "storage_asset_id": skill.storage_asset_id,
        "download_url": download_url,
        "enabled": bool(skill.enabled),
    }


@studio_bp.get("/api/skills")
@authorize("studio:skills")
def skills_api():
    skills = (
        StudioSkill.query.filter_by(enabled=1)
        .order_by(desc(StudioSkill.updated_at))
        .all()
    )
    return jsonify(success=True, data=[_skill_dict(skill) for skill in skills])


def _skill_code(name):
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.lower()).strip("-") or "skill"
    code = base
    index = 1
    while StudioSkill.query.filter_by(code=code).first():
        index += 1
        code = f"{base}-{index}"
    return code


@studio_bp.post("/api/skills")
@authorize("studio:skills")
def save_skill():
    data = _body()
    skill_id = _int_or_none(data.get("id"))
    skill = (
        StudioSkill.query.filter_by(id=skill_id).first()
        if skill_id
        else StudioSkill()
    )
    if skill_id and not skill:
        return jsonify(success=False, msg="Skill 不存在"), 404
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify(success=False, msg="Skill 名称不能为空"), 400

    old_storage_asset = (
        StudioAsset.query.filter_by(id=skill.storage_asset_id).first()
        if skill.storage_asset_id
        else None
    )
    old_content = skill.content or ""
    old_prompt = skill.prompt_template or ""
    content_provided = "content" in data
    requested_prompt = str(data.get("prompt_template") or "")
    new_content = (
        str(data.get("content") or "")
        if content_provided
        else old_content
    )
    text_file_types = {"md", "txt", "yaml", "yml"}
    is_text_skill = (skill.file_type or "").lower() in text_file_types

    skill.name = name
    skill.code = skill.code or _skill_code(name)
    skill.media_type = str(data.get("media_type") or "BOTH").upper()
    skill.version = data.get("version") or "1.0.0"
    skill.tags = data.get("tags") or ""
    skill.prompt_template = requested_prompt
    # Keep the legacy column for schema compatibility. The current workflow
    # has no separate negative-prompt field.
    skill.negative_prompt = ""
    if (
        content_provided
        and is_text_skill
        and new_content == old_content
        and requested_prompt != old_prompt
    ):
        new_content = requested_prompt
    elif (
        content_provided
        and is_text_skill
        and new_content != old_content
        and requested_prompt == old_prompt
    ):
        skill.prompt_template = new_content
    skill.content = new_content
    skill.enabled = 1
    skill.created_by = skill.created_by or current_user.id
    replacement = None
    stored = None
    should_sync_file = (
        content_provided
        and (
            new_content != old_content
            or not skill.storage_asset_id
        )
        and bool(new_content or skill.storage_asset_id or skill.file_name)
    )
    if should_sync_file:
        filename = skill.file_name or f"{skill.code}.md"
        content_type = mimetypes.guess_type(filename)[0] or "text/plain"
        try:
            stored = FileService.upload_bytes(
                new_content.encode("utf-8"),
                filename,
                content_type=content_type,
                asset_type="FILE",
                purpose="SKILL",
                retention_policy=FileService.PERMANENT,
                created_by=current_user.id,
                record=False,
            )
            replacement = FileService.create_asset_record(
                stored,
                asset_type="FILE",
                purpose="SKILL",
                retention_policy=FileService.PERMANENT,
                created_by=current_user.id,
            )
            skill.file_name = skill.file_name or filename
            skill.file_type = skill.file_type or os.path.splitext(filename)[1].lstrip(".")
        except Exception as exc:
            return jsonify(success=False, msg=str(exc)), 400

    try:
        db.session.add(skill)
        if replacement:
            db.session.add(replacement)
            db.session.flush()
            skill.storage_asset_id = replacement.id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if stored:
            try:
                FileService.delete_storage(stored.storage_path, checksum=stored.checksum)
            except Exception:
                current_app.logger.exception("failed to roll back Skill replacement upload")
        return jsonify(success=False, msg=str(exc)), 400

    if replacement and old_storage_asset and old_storage_asset.id != replacement.id:
        FileService.delete_asset(old_storage_asset)
        db.session.commit()
    return jsonify(success=True, msg="Skill 已保存", data=_skill_dict(skill))


@studio_bp.post("/api/skills/upload")
@authorize("studio:skills")
def upload_skill():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(success=False, msg="请选择 Skill 文件"), 400

    allowed = {".md", ".json", ".txt", ".yaml", ".yml"}
    extension = os.path.splitext(file.filename)[1].lower()
    if extension not in allowed:
        return jsonify(success=False, msg="仅支持 md、json、txt、yaml、yml 文件"), 400

    raw_bytes = file.read()
    content = raw_bytes.decode("utf-8-sig", errors="replace")
    metadata = {}
    if extension == ".json":
        parsed = _json(content, {})
        if isinstance(parsed, dict):
            metadata = parsed

    base_name = os.path.splitext(file.filename)[0]
    name = str(metadata.get("name") or base_name).strip()
    stored = None
    try:
        stored = FileService.upload_bytes(
            raw_bytes,
            file.filename,
            content_type=file.mimetype,
            asset_type="FILE",
            purpose="SKILL",
            retention_policy=FileService.PERMANENT,
            created_by=current_user.id,
            record=False,
        )
    except Exception as exc:
        return jsonify(success=False, msg=str(exc)), 400

    skill = StudioSkill(
        name=name,
        code=_skill_code(name),
        media_type=str(metadata.get("media_type") or "BOTH").upper(),
        version=str(metadata.get("version") or "1.0.0"),
        tags=str(metadata.get("tags") or ""),
        file_name=file.filename,
        file_type=extension.lstrip("."),
        content=content,
        prompt_template=str(
            metadata.get("prompt_template")
            or metadata.get("prompt")
            or (content if extension != ".json" else "")
        ),
        negative_prompt="",
        created_by=current_user.id,
        enabled=1,
    )
    try:
        db.session.add(skill)
        db.session.flush()
        storage_asset = FileService.create_asset_record(
            stored,
            asset_type="FILE",
            purpose="SKILL",
            retention_policy=FileService.PERMANENT,
            created_by=current_user.id,
        )
        db.session.add(storage_asset)
        db.session.flush()
        skill.storage_asset_id = storage_asset.id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        try:
            FileService.delete_storage(stored.storage_path, checksum=stored.checksum)
        except Exception:
            current_app.logger.exception("failed to roll back Skill storage upload")
        return jsonify(success=False, msg=str(exc)), 400
    return jsonify(success=True, msg="Skill 文件已导入", data=_skill_dict(skill))


@studio_bp.delete("/api/skills/<int:skill_id>")
@authorize("studio:skills")
def delete_skill(skill_id):
    skill = StudioSkill.query.filter_by(id=skill_id).first()
    if not skill:
        return jsonify(success=False, msg="Skill 不存在"), 404
    if skill.storage_asset_id:
        stored_asset = StudioAsset.query.filter_by(
            id=skill.storage_asset_id,
            status="ACTIVE",
        ).first()
        if stored_asset:
            FileService.delete_asset(stored_asset)
    skill.enabled = 0
    db.session.commit()
    return jsonify(success=True, msg="Skill 已停用")
