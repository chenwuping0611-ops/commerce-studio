import datetime
import json
import secrets

from applications.extensions import db
from applications.models import StudioGenerationTask, StudioModel, StudioProduct

from .product_prompt import compose_prompt, product_reference_urls, split_urls
from .provider_client import ProviderClient, ProviderRequestError
from .request_builder import build_request_body, reference_roles


ACTIVE_STATUSES = ("SUBMITTED", "PROCESSING")


def _dump(value):
    return json.dumps(value, ensure_ascii=False, default=str) if value is not None else None


def _new_task_code():
    for _ in range(20):
        code = str(secrets.randbelow(9_000_000) + 1_000_000)
        if not StudioGenerationTask.query.filter_by(task_code=code).first():
            return code
    raise RuntimeError("无法生成唯一的 7 位任务编号")


def _find_nested_value(payload, keys):
    """Find a value in common ToAPIs response wrappers without assuming one shape."""

    if isinstance(payload, dict):
        for key in keys:
            if payload.get(key) not in (None, ""):
                return payload[key]
        for value in payload.values():
            found = _find_nested_value(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_nested_value(value, keys)
            if found not in (None, ""):
                return found
    return None


def _extract_provider_task_id(payload):
    return _find_nested_value(payload, ("task_id", "taskId", "id", "request_id", "requestId"))


def _extract_output(payload):
    """Extract the first output URL from image/video completion payloads."""

    if not isinstance(payload, (dict, list)):
        return None, None
    if isinstance(payload, dict):
        for url_key in ("output_url", "outputUrl", "image_url", "video_url", "url"):
            value = payload.get(url_key)
            if isinstance(value, str) and value.strip():
                return value.strip(), payload.get("format") or payload.get("mime_type")
        for key in ("output", "result", "data", "images", "videos"):
            if key in payload:
                url, output_format = _extract_output(payload[key])
                if url:
                    return url, output_format
    elif isinstance(payload, list):
        for item in payload:
            url, output_format = _extract_output(item)
            if url:
                return url, output_format
    return None, None


def _provider_status(payload):
    raw = _find_nested_value(payload, ("status", "state"))
    value = str(raw or "").strip().lower()
    if value in ("queued", "pending", "created", "submitted"):
        return "submitted"
    if value in ("running", "in_progress", "processing", "generating"):
        return "processing"
    if value in ("completed", "succeeded", "success", "done", "finished"):
        return "completed"
    if value in ("failed", "failure", "error", "cancelled", "canceled"):
        return "failed"
    return value


def _safe_progress(payload, fallback=0):
    value = _find_nested_value(payload, ("progress", "percent", "percentage"))
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return fallback


def create_generation(user_id, media_type, model_id, product_id, prompt, options=None):
    """Create a local task, submit it upstream, and persist the request snapshot."""

    options = options or {}
    media_type = str(media_type or "IMAGE").upper()
    if media_type not in ("IMAGE", "VIDEO"):
        raise ValueError("不支持的创作类型")

    try:
        model_id = int(model_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("请选择有效模型") from exc

    model = StudioModel.query.filter_by(id=model_id, enabled=1).first()
    if not model:
        raise ValueError("模型不存在或已停用")
    if model.media_type != media_type:
        raise ValueError("当前模型与创作类型不匹配")
    if not model.provider or not model.provider.enabled:
        raise ValueError("模型供应商不存在或已停用")
    if not model.provider.api_key:
        raise ValueError("请先在模型供应商中填写 API Key")
    if not str(prompt or "").strip():
        raise ValueError("创意描述不能为空")

    product = None
    if product_id:
        product = StudioProduct.query.filter_by(id=product_id, enabled=1).first()
        if not product:
            raise ValueError("产品不存在或已停用")

    extra_urls = options.get("reference_images") or []
    extra_videos = options.get("reference_videos") or []
    product_urls = product_reference_urls(product, extra_urls, media_type)
    if isinstance(extra_videos, str):
        extra_videos = split_urls(extra_videos)

    runtime = {
        "prompt": compose_prompt(product, prompt),
        "negative_prompt": options.get("negative_prompt"),
        "count": options.get("count", 1),
        "aspect_ratio": options.get("aspect_ratio"),
        "resolution": options.get("resolution"),
        "duration": options.get("duration"),
        "generate_audio": options.get("generate_audio"),
        "reference_images": product_urls,
        "reference_images_with_roles": reference_roles(product_urls, "reference_image"),
        "reference_videos": extra_videos,
        "reference_videos_with_roles": reference_roles(extra_videos, "reference_video"),
    }
    body = build_request_body(model, runtime, options.get("extra_fields") or {})
    final_prompt = runtime["prompt"]

    task = StudioGenerationTask(
        task_code=_new_task_code(),
        user_id=user_id,
        media_type=media_type,
        product_id=product.id if product else None,
        model_id=model.id,
        prompt=str(prompt).strip(),
        final_prompt=final_prompt,
        negative_prompt=options.get("negative_prompt"),
        request_body=_dump(body),
        status="PENDING",
        progress=0,
    )
    db.session.add(task)
    db.session.commit()

    try:
        response = ProviderClient(model.provider).submit_generation(model, body)
        provider_task_id = _extract_provider_task_id(response)
        output_url, output_format = _extract_output(response)
        state = _provider_status(response)
        task.result_payload = _dump(response)
        task.progress = _safe_progress(response)
        if output_url and state == "completed":
            task.status = "SUCCEEDED"
            task.progress = 100
            task.output_url = output_url
            task.output_format = output_format
            task.completed_at = datetime.datetime.now()
        elif not provider_task_id:
            raise ProviderRequestError("供应商响应中没有任务 ID", payload=response)
        else:
            task.provider_task_id = str(provider_task_id)
            task.status = "PROCESSING" if state == "processing" else "SUBMITTED"
        db.session.commit()
    except Exception as exc:
        task.status = "FAILED"
        task.error_message = str(exc)
        task.completed_at = datetime.datetime.now()
        db.session.commit()
        raise
    return task


def poll_task(task):
    """Query one active upstream task and normalize its status and output."""

    if not task.provider_task_id or task.status not in ACTIVE_STATUSES:
        return task
    model = task.model
    if not model or not model.provider:
        task.status = "FAILED"
        task.error_message = "关联模型或供应商不存在"
        task.completed_at = datetime.datetime.now()
        db.session.commit()
        return task

    try:
        payload = ProviderClient(model.provider).fetch_generation_result(
            model,
            task.provider_task_id,
            task.media_type,
        )
        task.result_payload = _dump(payload)
        task.progress = _safe_progress(payload, task.progress or 0)
        state = _provider_status(payload)
        if state == "completed":
            task.status = "SUCCEEDED"
            task.progress = 100
            task.output_url, task.output_format = _extract_output(payload)
            task.completed_at = datetime.datetime.now()
            if not task.output_url:
                task.status = "FAILED"
                task.error_message = "任务已完成，但响应中没有输出 URL"
        elif state == "failed":
            task.status = "FAILED"
            error = _find_nested_value(payload, ("error", "message", "msg"))
            task.error_message = (
                error.get("message") if isinstance(error, dict) else str(error or "上游生成失败")
            )
            task.completed_at = datetime.datetime.now()
        else:
            task.status = "PROCESSING"
        db.session.commit()
    except Exception as exc:
        task.error_message = str(exc)
        db.session.commit()
    return task


def poll_processing_tasks():
    """Poll at most twenty oldest active tasks per scheduler tick."""

    tasks = (
        StudioGenerationTask.query.filter(
            StudioGenerationTask.status.in_(ACTIVE_STATUSES)
        )
        .order_by(StudioGenerationTask.created_at.asc())
        .limit(20)
        .all()
    )
    for task in tasks:
        poll_task(task)
    return len(tasks)
