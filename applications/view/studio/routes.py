import json
import os
import re
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, session
from flask_login import current_user, login_required
from sqlalchemy import desc

from applications.common.utils.rights import authorize
from applications.extensions import db
from applications.models import (
    StudioGenerationTask,
    StudioModel,
    StudioProduct,
    StudioProductAsset,
    StudioProvider,
    StudioSkill,
)
from applications.studio.generation_service import create_generation, poll_task
from applications.studio.product_prompt import split_urls
from applications.studio.provider_client import ProviderClient
from applications.studio.request_builder import default_parameters, parse_parameters


studio_bp = Blueprint("studio", __name__, url_prefix="/studio")


def _json(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _body():
    return request.get_json(silent=True) or request.form.to_dict()


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_enabled(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "off", "no")


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
            }
        )
    return normalized


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
        "parameter_schema": parse_parameters(model.parameter_schema),
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
                "url": asset.url,
                "asset_type": asset.asset_type,
                "role": asset.role,
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
    return {
        "id": task.id,
        "task_code": task.task_code,
        "media_type": task.media_type,
        "product_id": task.product_id,
        "product_name": task.product.name if task.product else "",
        "model_id": task.model_id,
        "model_name": task.model.name if task.model else "",
        "provider_task_id": task.provider_task_id or "",
        "prompt": task.prompt,
        "final_prompt": task.final_prompt or "",
        "status": task.status,
        "progress": task.progress or 0,
        "output_url": task.output_url or "",
        "output_format": task.output_format or "",
        "error_message": task.error_message or "",
        "created_at": task.created_at.strftime("%Y-%m-%d %H:%M:%S")
        if task.created_at
        else "",
        "completed_at": task.completed_at.strftime("%Y-%m-%d %H:%M:%S")
        if task.completed_at
        else "",
    }


def _has_permission(code):
    return code in session.get("permissions", [])


@studio_bp.get("/")
@authorize("studio:dashboard")
def dashboard():
    return render_template("studio/dashboard.html")


@studio_bp.get("/image")
@authorize("studio:image")
def image():
    return render_template("studio/image.html")


@studio_bp.get("/video")
@authorize("studio:video")
def video():
    return render_template("studio/video.html")


@studio_bp.get("/products")
@authorize("studio:products")
def products():
    return render_template("studio/products.html")


@studio_bp.get("/skills")
@authorize("studio:skills")
def skills():
    return render_template("studio/skills.html")


@studio_bp.get("/history")
@authorize("studio:history")
def history():
    return render_template("studio/history.html")


@studio_bp.get("/providers")
@authorize("studio:providers")
def providers():
    return render_template("studio/providers.html")


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
                    "prompt_template": skill.prompt_template or "",
                    "negative_prompt": skill.negative_prompt or "",
                }
                for skill in skills
            ],
        },
    )


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
                "negative_prompt": data.get("negative_prompt"),
                "reference_images": data.get("reference_images"),
                "reference_videos": data.get("reference_videos"),
                "extra_fields": _json(data.get("extra_fields"), {}),
            },
        )
        return jsonify(success=True, msg="任务已提交", data=_task_dict(task))
    except Exception as exc:
        db.session.rollback()
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.get("/api/tasks/<task_code>")
@login_required
def task_status(task_code):
    task = StudioGenerationTask.query.filter_by(task_code=task_code).first()
    if not task:
        return jsonify(success=False, msg="任务不存在"), 404
    required_permission = "studio:video" if task.media_type == "VIDEO" else "studio:image"
    can_read = (
        _has_permission(required_permission)
        or _has_permission("studio:history")
        or task.user_id == current_user.id
    )
    if not can_read:
        return jsonify(success=False, msg="权限不足"), 403
    if task.status in ("SUBMITTED", "PROCESSING"):
        poll_task(task)
    return jsonify(success=True, data=_task_dict(task))


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
    product.enabled = 0
    db.session.commit()
    return jsonify(success=True, msg="产品已停用")


@studio_bp.post("/api/products/<int:product_id>/assets")
@authorize("studio:products")
def save_product_asset(product_id):
    product = StudioProduct.query.filter_by(id=product_id, enabled=1).first()
    data = _body()
    url = str(data.get("url") or "").strip()
    if not product or not url:
        return jsonify(success=False, msg="产品或素材 URL 不正确"), 400
    asset = StudioProductAsset(
        product_id=product.id,
        name=str(data.get("name") or "产品参考素材").strip(),
        url=url,
        asset_type=str(data.get("asset_type") or "IMAGE").upper(),
        role=str(data.get("role") or "reference").strip(),
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
    asset.enabled = 0
    db.session.commit()
    product = StudioProduct.query.filter_by(id=product_id).first()
    return jsonify(success=True, msg="素材已停用", data=_product_dict(product))


@studio_bp.get("/api/providers")
@authorize("studio:providers")
def providers_api():
    providers = StudioProvider.query.order_by(StudioProvider.name).all()
    return jsonify(success=True, data=[_provider_dict(provider) for provider in providers])


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
    if str(data.get("api_key") or "").strip():
        provider.api_key = str(data["api_key"]).strip()
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
        data = ProviderClient(provider).get_balance(scope=scope)
        return jsonify(success=True, msg="连接成功", data={"scope": scope, "payload": data})
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
    if media_type not in ("IMAGE", "VIDEO"):
        return jsonify(success=False, msg="模型类型必须是图片或视频"), 400

    duplicate = StudioModel.query.filter(
        StudioModel.provider_id == provider.id,
        StudioModel.model_code == model_code,
        StudioModel.id != (model.id or 0),
    ).first()
    if duplicate:
        return jsonify(success=False, msg="该供应商下的模型标识已经存在"), 400

    parameters = _normalize_parameters(data.get("parameter_schema"))
    if not parameters:
        parameters = default_parameters(media_type)
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
    return {
        "id": skill.id,
        "name": skill.name,
        "code": skill.code,
        "media_type": skill.media_type,
        "version": skill.version,
        "tags": skill.tags or "",
        "prompt_template": skill.prompt_template or "",
        "negative_prompt": skill.negative_prompt or "",
        "file_name": skill.file_name or "",
        "file_type": skill.file_type or "",
        "content": skill.content or "",
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

    skill.name = name
    skill.code = skill.code or _skill_code(name)
    skill.media_type = str(data.get("media_type") or "BOTH").upper()
    skill.version = data.get("version") or "1.0.0"
    skill.tags = data.get("tags") or ""
    skill.prompt_template = data.get("prompt_template") or ""
    skill.negative_prompt = data.get("negative_prompt") or ""
    skill.content = data.get("content") or skill.content or ""
    skill.enabled = 1
    skill.created_by = skill.created_by or current_user.id
    db.session.add(skill)
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

    content = file.read().decode("utf-8-sig", errors="replace")
    metadata = {}
    if extension == ".json":
        parsed = _json(content, {})
        if isinstance(parsed, dict):
            metadata = parsed

    base_name = os.path.splitext(file.filename)[0]
    name = str(metadata.get("name") or base_name).strip()
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
        negative_prompt=str(metadata.get("negative_prompt") or ""),
        created_by=current_user.id,
        enabled=1,
    )
    db.session.add(skill)
    db.session.commit()
    return jsonify(success=True, msg="Skill 文件已导入", data=_skill_dict(skill))


@studio_bp.delete("/api/skills/<int:skill_id>")
@authorize("studio:skills")
def delete_skill(skill_id):
    skill = StudioSkill.query.filter_by(id=skill_id).first()
    if not skill:
        return jsonify(success=False, msg="Skill 不存在"), 404
    skill.enabled = 0
    db.session.commit()
    return jsonify(success=True, msg="Skill 已停用")
