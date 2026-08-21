import base64
import binascii
import datetime
import json
import mimetypes
import os
import secrets
from types import SimpleNamespace

from flask import current_app

from applications.extensions import db
from applications.common.storage import FileService, StorageError
from applications.models import (
    StudioAsset,
    StudioGenerationTask,
    StudioModel,
    StudioProduct,
)

from .product_prompt import (
    compose_prompt,
    product_reference_descriptors,
    product_reference_urls,
    split_urls,
)
from .provider_client import ProviderClient, ProviderRequestError
from .request_builder import build_request_body, reference_roles


ACTIVE_STATUSES = ("SUBMITTED", "PROCESSING")
TASK_SYNC_FIELDS = (
    "provider_task_id",
    "status",
    "progress",
    "result_payload",
    "output_url",
    "output_format",
    "error_message",
    "completed_at",
    "updated_at",
)


def _provider_snapshot(provider):
    """Copy provider settings before an upstream request releases the DB session."""

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


def _model_snapshot(model):
    """Copy only model request settings needed by ProviderClient."""

    return SimpleNamespace(
        media_type=model.media_type,
        generation_path=model.generation_path,
        result_path=model.result_path,
    )


def _sync_task_state(target, source):
    """Keep the caller's task object useful after a session is deliberately removed."""

    for field in TASK_SYNC_FIELDS:
        setattr(target, field, getattr(source, field))
    return target


def _asset_is_active(asset):
    return bool(
        asset
        and asset.status == "ACTIVE"
        and not (
            asset.expires_at
            and asset.expires_at <= datetime.datetime.now()
        )
    )


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


def _extract_outputs(payload):
    """Extract URL and base64 outputs from common provider response wrappers."""

    outputs = []
    seen = set()

    def add_output(url=None, encoded=None, output_format=None, mime_type=None):
        value = str(url or encoded or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        outputs.append(
            {
                "url": str(url).strip() if isinstance(url, str) else None,
                "data": str(encoded).strip() if isinstance(encoded, str) else None,
                "format": output_format or mime_type,
            }
        )

    def walk(node):
        if isinstance(node, dict):
            output_format = node.get("format") or node.get("mime_type")
            for key in ("output_url", "outputUrl", "image_url", "video_url", "url"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    add_output(url=value, output_format=output_format)
            for key in ("b64_json", "base64", "base64_data", "data_uri"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    add_output(
                        encoded=value,
                        output_format=output_format,
                        mime_type=node.get("content_type"),
                    )
            for key in ("output", "result", "data", "images", "videos"):
                if key in node:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return outputs


def _extract_output(payload):
    """Backward-compatible helper returning the first provider output."""

    outputs = _extract_outputs(payload)
    if not outputs:
        return None, None
    return outputs[0].get("url") or outputs[0].get("data"), outputs[0].get("format")


def _provider_status(payload):
    raw = None
    if isinstance(payload, dict):
        raw = payload.get("status") or payload.get("state")
    if raw in (None, ""):
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


def _provider_error_message(payload, fallback="上游生成失败"):
    """Read a useful error message from a successful HTTP task response."""

    error = _find_nested_value(payload, ("error",))
    if isinstance(error, dict):
        message = error.get("message") or error.get("msg") or error.get("detail")
        if message:
            return str(message)
    elif error not in (None, ""):
        return str(error)
    message = _find_nested_value(payload, ("message", "msg", "detail"))
    return str(message or fallback)


def _is_placeholder_output(stored):
    """Prevent test placeholder URLs from becoming user-visible assets."""

    public_url = str(getattr(stored, "public_url", "") or "").lower()
    storage_path = str(getattr(stored, "storage_path", "") or "").lower()
    return (
        public_url.startswith("https://mock.invalid/")
        or public_url.startswith("http://mock.invalid/")
        or storage_path.startswith("/mock/")
    )


def _safe_progress(payload, fallback=0):
    value = _find_nested_value(payload, ("progress", "percent", "percentage"))
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return fallback


def _reference_assets(user_id, asset_ids, media_type, video_only=False):
    if not asset_ids:
        return []
    requested_ids = list(dict.fromkeys(int(item) for item in asset_ids))
    assets = (
        StudioAsset.query.filter(
            StudioAsset.id.in_(requested_ids),
            StudioAsset.status == "ACTIVE",
            StudioAsset.purpose == "GENERATION_REFERENCE",
        )
        .all()
    )
    active_by_id = {
        asset.id: asset for asset in assets if _asset_is_active(asset)
    }
    assets = [
        active_by_id[asset_id]
        for asset_id in requested_ids
        if asset_id in active_by_id
    ]
    if len(assets) != len(requested_ids):
        raise ValueError("参考文件不存在、已过期或不是生成参考文件")
    for asset in assets:
        if asset.created_by not in (None, user_id):
            raise ValueError("不能使用其他用户上传的参考文件")
        if video_only and asset.asset_type != "VIDEO":
            raise ValueError("视频参考文件类型不正确")
        if not video_only and media_type == "IMAGE" and asset.asset_type != "IMAGE":
            raise ValueError("图片参考文件类型不正确")
    return assets


def _output_extension(output, media_type):
    output_format = str(output.get("format") or "").lower().strip()
    if "/" in output_format:
        output_format = output_format.rsplit("/", 1)[-1]
    output_format = output_format.lstrip(".")
    if output_format == "jpeg":
        output_format = "jpg"
    if output_format == "quicktime":
        output_format = "mov"
    if output_format and output_format.isalnum():
        return output_format

    source_url = str(output.get("url") or "")
    extension = os.path.splitext(source_url.split("?", 1)[0])[1].lower().lstrip(".")
    if extension:
        return extension
    return "mp4" if media_type == "VIDEO" else "png"


def _persist_provider_outputs(task, payload):
    """Copy all provider outputs into go-fastdfs and keep the first URL compatible."""

    existing = (
        StudioAsset.query.filter_by(
            generation_task_id=task.id,
            purpose="GENERATION_OUTPUT",
            status="ACTIVE",
        )
        .order_by(StudioAsset.id.asc())
        .all()
    )
    existing = [asset for asset in existing if _asset_is_active(asset)]
    if existing:
        task.output_url = existing[0].public_url
        task.output_format = existing[0].content_type or task.output_format
        return existing

    outputs = _extract_outputs(payload)
    if not outputs:
        return []

    stored_files = []
    assets = []
    asset_type = "VIDEO" if task.media_type == "VIDEO" else "IMAGE"
    try:
        for index, output in enumerate(outputs, start=1):
            extension = _output_extension(output, task.media_type)
            filename = f"{task.task_code}-{index}.{extension}"
            output_value = output.get("url") or output.get("data")
            if not output_value:
                continue

            if output.get("data"):
                if str(output_value).startswith("data:"):
                    stored = FileService.upload_data_uri(
                        output_value,
                        filename,
                        asset_type=asset_type,
                        purpose="GENERATION_OUTPUT",
                        retention_policy=FileService.TTL_7D,
                        created_by=task.user_id,
                        record=False,
                    )
                else:
                    try:
                        raw = base64.b64decode(output_value, validate=True)
                    except (ValueError, binascii.Error) as exc:
                        raise StorageError("provider returned invalid base64 output") from exc
                    content_type = output.get("format")
                    if content_type and "/" not in str(content_type):
                        content_type = f"{'video' if asset_type == 'VIDEO' else 'image'}/{content_type}"
                    stored = FileService.upload_bytes(
                        raw,
                        filename,
                        content_type=content_type,
                        asset_type=asset_type,
                        purpose="GENERATION_OUTPUT",
                        retention_policy=FileService.TTL_7D,
                        created_by=task.user_id,
                        record=False,
                    )
            else:
                stored = FileService.upload_from_url(
                    output_value,
                    filename=filename,
                    asset_type=asset_type,
                    purpose="GENERATION_OUTPUT",
                    retention_policy=FileService.TTL_7D,
                    created_by=task.user_id,
                    record=False,
                )
            if _is_placeholder_output(stored):
                raise StorageError(
                    "生成结果未上传到 go-fastdfs，拒绝保存测试占位地址"
                )
            stored_files.append(stored)
            assets.append(
                FileService.create_asset_record(
                    stored,
                    asset_type=asset_type,
                    purpose="GENERATION_OUTPUT",
                    retention_policy=FileService.TTL_7D,
                    created_by=task.user_id,
                    generation_task_id=task.id,
                )
            )
    except Exception:
        for stored in stored_files:
            try:
                FileService.delete_storage(stored.storage_path, checksum=stored.checksum)
            except Exception:
                pass
        raise

    if not assets:
        return []
    try:
        db.session.add_all(assets)
        db.session.flush()
    except Exception:
        db.session.rollback()
        for stored in stored_files:
            try:
                FileService.delete_storage(stored.storage_path, checksum=stored.checksum)
            except Exception:
                pass
        raise

    task.output_url = assets[0].public_url
    task.output_format = assets[0].content_type
    return assets


def _has_provider_outputs(payload):
    return bool(_extract_outputs(payload))


def _reference_limit(model, media_type):
    """Read a per-model reference limit, falling back to the app default."""

    try:
        capabilities = json.loads(model.capabilities or "{}")
    except (TypeError, ValueError):
        capabilities = {}
    capability_key = (
        "max_reference_images"
        if media_type == "IMAGE"
        else "max_reference_videos"
    )
    configured = capabilities.get(capability_key)
    try:
        configured = int(configured)
    except (TypeError, ValueError):
        configured = 0
    if configured > 0:
        return configured
    fallback_key = (
        "STUDIO_MAX_IMAGE_REFERENCES"
        if media_type == "IMAGE"
        else "STUDIO_MAX_VIDEO_REFERENCES"
    )
    try:
        return max(1, int(current_app.config.get(fallback_key) or 10))
    except (TypeError, ValueError):
        return 10


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
    provider_api_key = str(model.provider.api_key or "").strip()
    if not provider_api_key:
        raise ValueError("请先在模型供应商中填写 API Key")
    if not str(prompt or "").strip():
        raise ValueError("创意描述不能为空")

    product = None
    if product_id:
        product = StudioProduct.query.filter_by(id=product_id, enabled=1).first()
        if not product:
            raise ValueError("产品不存在或已停用")

    reference_image_assets = _reference_assets(
        user_id,
        options.get("reference_asset_ids") or [],
        media_type,
        video_only=False,
    )
    reference_video_assets = _reference_assets(
        user_id,
        options.get("reference_video_asset_ids") or [],
        media_type,
        video_only=True,
    )
    extra_urls = [asset.public_url for asset in reference_image_assets]
    extra_urls.extend(split_urls(options.get("reference_images")))
    extra_videos = split_urls(options.get("reference_videos"))
    extra_videos.extend(asset.public_url for asset in reference_video_assets)
    product_descriptors = product_reference_descriptors(
        product,
        extra_urls,
        media_type,
    )
    product_urls = [descriptor["url"] for descriptor in product_descriptors]
    extra_videos = list(dict.fromkeys(extra_videos))
    max_references = _reference_limit(model, media_type)
    if len(product_urls) > max_references:
        raise ValueError(
            f"当前模型最多支持 {max_references} 张参考图片，请减少产品素材或本次上传的参考图"
        )
    if len(extra_videos) > _reference_limit(model, "VIDEO"):
        raise ValueError(
            f"当前模型最多支持 {_reference_limit(model, 'VIDEO')} 个参考视频，请减少本次上传的视频"
        )

    prepared_prompt = str(options.get("prepared_prompt") or "").strip()
    skill_prompt = str(options.get("skill_prompt") or "").strip()
    runtime = {
        "prompt": prepared_prompt or compose_prompt(
            product,
            prompt,
            product_descriptors,
            skill_prompt=skill_prompt,
            media_type=media_type,
            video_urls=extra_videos,
        ),
        "count": options.get("count", 1),
        "aspect_ratio": options.get("aspect_ratio"),
        "resolution": options.get("resolution"),
        "duration": options.get("duration"),
        "generate_audio": options.get("generate_audio"),
        "reference_images": product_urls,
        "reference_images_with_roles": reference_roles(
            product_descriptors,
            "reference_image",
        ),
        "reference_videos": extra_videos,
        "reference_videos_with_roles": reference_roles(extra_videos, "reference_video"),
    }
    body = build_request_body(model, runtime, options.get("extra_fields") or {})
    final_prompt = runtime["prompt"]
    provider_snapshot = _provider_snapshot(model.provider)
    provider_snapshot.api_key = provider_api_key
    model_snapshot = _model_snapshot(model)

    task = StudioGenerationTask(
        task_code=_new_task_code(),
        user_id=user_id,
        media_type=media_type,
        product_id=product.id if product else None,
        model_id=model.id,
        prompt=str(prompt).strip(),
        final_prompt=final_prompt,
        # Keep the nullable legacy column for existing records, but do not
        # accept or forward a separate negative prompt in the current flow.
        negative_prompt=None,
        request_body=_dump(body),
        status="PENDING",
        progress=0,
    )
    db.session.add(task)
    db.session.flush()
    for asset in reference_image_assets + reference_video_assets:
        asset.generation_task_id = task.id
    db.session.commit()

    try:
        response = ProviderClient(provider_snapshot).submit_generation(model_snapshot, body)
        provider_task_id = _extract_provider_task_id(response)
        output_url, output_format = _extract_output(response)
        state = _provider_status(response)
        task.result_payload = _dump(response)
        task.progress = _safe_progress(response)
        if (output_url and state == "completed") or (
            _has_provider_outputs(response) and not provider_task_id
        ):
            task.status = "SUCCEEDED"
            task.progress = 100
            persisted = _persist_provider_outputs(task, response)
            if not persisted:
                raise ProviderRequestError(
                    "任务已完成，但没有可持久化的输出资产",
                    payload=response,
                )
            task.completed_at = datetime.datetime.now()
        elif state == "failed":
            task.status = "FAILED"
            task.error_message = _provider_error_message(response)
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
    original_task = task
    task_id = task.id
    provider_task_id = task.provider_task_id
    media_type = task.media_type
    model = task.model
    if not model or not model.provider:
        task.status = "FAILED"
        task.error_message = "关联模型或供应商不存在"
        task.completed_at = datetime.datetime.now()
        db.session.commit()
        return task
    provider_snapshot = _provider_snapshot(model.provider)
    model_snapshot = _model_snapshot(model)

    try:
        # The upstream request can take seconds or minutes. Do not keep the
        # SQLAlchemy connection checked out while waiting on that network call.
        db.session.remove()
        payload = ProviderClient(provider_snapshot).fetch_generation_result(
            model_snapshot,
            provider_task_id,
            media_type,
        )
        task = StudioGenerationTask.query.get(task_id)
        if not task:
            return original_task
        task.result_payload = _dump(payload)
        task.progress = _safe_progress(payload, task.progress or 0)
        state = _provider_status(payload)
        if state == "completed" or (
            not state and _has_provider_outputs(payload)
        ):
            task.status = "SUCCEEDED"
            task.progress = 100
            task.error_message = None
            persisted = _persist_provider_outputs(task, payload)
            task.completed_at = datetime.datetime.now()
            if not persisted:
                task.status = "FAILED"
                task.error_message = "任务已完成，但响应中没有输出 URL"
        elif state == "failed":
            task.status = "FAILED"
            error = _provider_error_message(payload)
            task.error_message = (
                error.get("message") if isinstance(error, dict) else str(error or "上游生成失败")
            )
            task.completed_at = datetime.datetime.now()
        else:
            task.status = "SUBMITTED" if state == "submitted" else "PROCESSING"
            task.error_message = None
        db.session.commit()
    except StorageError as exc:
        task = StudioGenerationTask.query.get(task_id) or original_task
        task.status = "FAILED"
        task.error_message = str(exc)
        task.completed_at = datetime.datetime.now()
        db.session.commit()
    except Exception as exc:
        task = StudioGenerationTask.query.get(task_id) or original_task
        task.error_message = str(exc)
        db.session.commit()
    return _sync_task_state(original_task, task)


def poll_processing_tasks():
    """Poll at most twenty oldest active tasks per scheduler tick."""

    task_ids = [
        task.id
        for task in (
        StudioGenerationTask.query.filter(
            StudioGenerationTask.status.in_(ACTIVE_STATUSES)
        )
        .order_by(StudioGenerationTask.created_at.asc())
        .limit(20)
        .all()
        )
    ]
    # The list query is complete; release its connection before polling.
    db.session.remove()
    for task_id in task_ids:
        task = StudioGenerationTask.query.get(task_id)
        if not task:
            continue
        poll_task(task)
    return len(task_ids)
