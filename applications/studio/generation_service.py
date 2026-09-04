import base64
import binascii
import datetime
import json
import mimetypes
import os
import secrets
import string
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from flask import current_app, has_request_context
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from applications.extensions import db
from applications.common.storage import FileService, StorageError
from applications.common.asset_relations import (
    ensure_generation_asset_links,
    generation_task_assets,
)
from applications.common.db_session import release_db_connection
from applications.common.execution_context import (
    AssetExecutionContext,
    ExecutionContext,
    ModelExecutionContext,
    ProductExecutionContext,
    ProviderExecutionContext,
    SkillExecutionContext,
)
from applications.common.skill_storage import read_skill_text
from applications.models import (
    Dept,
    StudioAsset,
    StudioGenerationTaskDetail,
    StudioGenerationTask,
    StudioModel,
    StudioProvider,
    StudioProduct,
    StudioSkill,
    User,
)
from applications.common.scope import (
    can_access_asset,
    can_access_model,
    can_access_resource,
    can_access_skill,
    department_in_scope,
    is_super_admin_user,
    PROVIDER_OWNER_DEPARTMENT,
    provider_owner_type,
    user_department_id,
)

from .product_prompt import (
    append_detail_image_output_contract,
    compose_prompt,
    product_reference_descriptors,
    product_reference_urls,
    split_urls,
)
from .provider_client import (
    ProviderClient,
    ProviderRequestError,
    provider_retry_call,
    redact_provider_payload,
)
from .provider_catalog import model_spec_for
from .request_builder import build_request_body, reference_roles
from applications.amazon_ai.skill_catalog import (
    AMAZON_BUILTIN_SKILL_CODES,
    DETAIL_IMAGE_SKILL_CODE,
)


ACTIVE_STATUSES = ("SUBMITTED", "PROCESSING")
EXECUTION_ACTIVE_STATUSES = ("PENDING", "SUBMITTED", "PROCESSING")
TERMINAL_STATUSES = ("SUCCEEDED", "FAILED", "CANCELLED")
TASK_CODE_ALPHABET = string.ascii_letters + string.digits
TASK_CODE_LENGTH = 7
MAX_FINAL_PROMPT_BYTES = 5000
MAX_RESULT_PAYLOAD_BYTES = 60000
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
    "expires_at",
    "retention_policy",
    "poll_claim_token",
    "poll_claimed_at",
)


def _temporary_retention_days():
    try:
        return max(
            1,
            int(
                current_app.config.get("STUDIO_TEMPORARY_RETENTION_DAYS")
                or current_app.config.get("STUDIO_ASSET_TTL_DAYS")
                or 30
            ),
        )
    except (TypeError, ValueError, RuntimeError):
        return 30


def _truncate_utf8(value, max_bytes):
    """Keep the provider prompt below the hard byte budget."""

    text = str(value or "")
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _terminal_expiry(now=None):
    now = now or datetime.datetime.now()
    return now + datetime.timedelta(days=_temporary_retention_days())


def _mark_terminal(task, now=None):
    """Apply the shared temporary-task retention policy to a terminal row."""

    now = now or datetime.datetime.now()
    task.retention_policy = FileService.TEMPORARY
    task.expires_at = _terminal_expiry(now)
    task.completed_at = task.completed_at or now
    return task


def _sync_generation_detail(task, **values):
    """Dual-write cold fields while the legacy columns remain compatible."""

    detail = task.detail
    if detail is None:
        detail = StudioGenerationTaskDetail(
            task_id=task.id,
            created_at=task.created_at,
        )
        db.session.add(detail)
        task.detail = detail
    for field, value in values.items():
        if value is not None:
            setattr(detail, field, value)
    detail.updated_at = datetime.datetime.now()
    return detail


def _provider_snapshot(provider, api_key=None):
    """Copy provider settings before an upstream request releases the DB session."""

    return ProviderExecutionContext(
        name=str(getattr(provider, "name", "") or ""),
        kind=str(getattr(provider, "kind", "") or ""),
        base_url=str(getattr(provider, "base_url", "") or ""),
        api_key=(
            getattr(provider, "api_key", None)
            if api_key is None
            else api_key
        ),
        generation_path=str(getattr(provider, "generation_path", "") or ""),
        result_path=str(getattr(provider, "result_path", "") or ""),
        balance_path=str(getattr(provider, "balance_path", "") or ""),
        token_balance_path=str(
            getattr(provider, "token_balance_path", "") or ""
        ),
        auth_header=str(getattr(provider, "auth_header", "") or ""),
        auth_prefix=str(getattr(provider, "auth_prefix", "") or ""),
        timeout=getattr(provider, "timeout", 120) or 120,
        owner_type=provider_owner_type(provider),
        dept_id=getattr(provider, "dept_id", None),
    )


def _model_snapshot(model):
    """Copy catalog-owned endpoint settings needed by ProviderClient."""

    spec = model_spec_for(
        getattr(model, "provider", None),
        getattr(model, "model_code", ""),
    )
    return ModelExecutionContext(
        id=getattr(model, "id", None),
        name=str(getattr(model, "name", "") or ""),
        media_type=str(getattr(model, "media_type", "") or ""),
        model_code=str(getattr(model, "model_code", "") or ""),
        generation_path=(
            spec.generation_path
            if spec
            else getattr(model, "generation_path", "")
        )
        or "",
        result_path=(
            spec.result_path
            if spec
            else getattr(model, "result_path", "")
        )
        or "",
        provider_id=getattr(model, "provider_id", None),
    )


def _asset_execution_snapshot(asset):
    return AssetExecutionContext(
        id=getattr(asset, "id", None),
        public_url=str(getattr(asset, "public_url", "") or ""),
        storage_path=str(getattr(asset, "storage_path", "") or ""),
        original_filename=str(
            getattr(asset, "original_filename", "") or ""
        ),
        content_type=str(getattr(asset, "content_type", "") or ""),
        checksum=getattr(asset, "checksum", None),
        purpose=str(getattr(asset, "purpose", "") or ""),
        retention_policy=str(
            getattr(asset, "retention_policy", "") or ""
        ),
        expires_at=(
            getattr(asset, "expires_at", None).isoformat()
            if getattr(asset, "expires_at", None)
            else ""
        ),
    )


def _skill_execution_snapshot(skill, prompt=""):
    if not skill:
        return None
    return SkillExecutionContext(
        id=getattr(skill, "id", None),
        name=str(getattr(skill, "name", "") or ""),
        prompt=str(prompt or ""),
    )


def _product_execution_snapshot(product, context=""):
    if not product:
        return None
    if not context:
        context = "\n".join(
            f"{label}：{str(getattr(product, field, '') or '').strip()}"
            for field, label in (
                ("name", "产品名称"),
                ("code", "产品编码"),
                ("brand", "品牌"),
                ("description", "产品资料"),
                ("core_selling_points", "核心卖点"),
                ("product_profile", "Product Profile"),
                ("product_memory", "产品记忆"),
                ("generation_rules", "生成规则"),
                ("forbidden_rules", "禁止修改规则"),
            )
            if str(getattr(product, field, "") or "").strip()
        )
    return ProductExecutionContext(
        id=getattr(product, "id", None),
        code=str(getattr(product, "code", "") or ""),
        name=str(getattr(product, "name", "") or ""),
        context=str(context or ""),
    )


def _resolve_generation_product(product_id, department_id, user):
    """Load a selected product using the caller's trusted data scope."""

    if not product_id:
        return None
    query = StudioProduct.query.filter_by(
        id=product_id,
        enabled=1,
    )
    if not is_super_admin_user(user):
        query = query.filter(StudioProduct.dept_id == department_id)
    product = query.first()
    if product and can_access_resource(user, product):
        return product
    return None


def _resolve_generation_skill(skill_id, department_id, user):
    """Load a selected Skill without allowing department spoofing."""

    if not skill_id:
        return None
    query = StudioSkill.query.filter_by(
        id=skill_id,
        enabled=1,
    )
    if not is_super_admin_user(user):
        query = query.filter(
            or_(
                StudioSkill.dept_id == department_id,
                StudioSkill.code.in_(AMAZON_BUILTIN_SKILL_CODES),
            )
        )
    skill = query.first()
    if skill and can_access_skill(
        user,
        skill,
        builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
    ):
        return skill
    return None


def complete_chat(model, body, department_id=None, user=None):
    """Call the existing provider stack for a text or vision chat model."""

    if not model or not model.provider:
        raise ValueError("语言模型或供应商不存在")
    acting_user = user
    if acting_user is None and getattr(
        current_user,
        "is_authenticated",
        False,
    ):
        acting_user = current_user
    if not can_access_model(
        acting_user,
        model,
        department_id=department_id,
    ):
        raise ValueError("无权使用该语言模型或供应商配置")
    provider_snapshot = _provider_snapshot(
        model.provider,
        api_key=str(model.provider.api_key or "").strip(),
    )
    spec = model_spec_for(
        getattr(model, "provider", None),
        getattr(model, "model_code", ""),
    )
    model_snapshot = ModelExecutionContext(
        id=getattr(model, "id", None),
        name=str(getattr(model, "name", "") or ""),
        media_type="CHAT",
        model_code=str(getattr(model, "model_code", "") or ""),
        generation_path=str(
            (spec.generation_path if spec else None)
            or model.generation_path
            or provider_snapshot.generation_path
            or "/v1/chat/completions"
        ),
        result_path=None,
        provider_id=getattr(model, "provider_id", None),
    )
    execution_context = ExecutionContext(
        user_id=getattr(acting_user, "id", None),
        dept_id=department_id,
        provider=provider_snapshot,
        model=model_snapshot,
    )
    # The provider call can take minutes. Return the checked-out connection
    # before entering the network operation; snapshots above keep the request
    # independent from SQLAlchemy's session lifecycle.
    client = ProviderClient(execution_context.provider)
    release_db_connection()
    return provider_retry_call(
        lambda: client.complete(execution_context.model, body),
        operation_name="studio chat completion",
    )


def _sync_task_state(target, source):
    """Keep the caller's task object useful after a session is deliberately removed."""

    for field in TASK_SYNC_FIELDS:
        setattr(target, field, getattr(source, field))
    return target


def _task_state_for_update(task_id, claim_token=None):
    """Read and lock one task for the short final state transition."""

    query = StudioGenerationTask.query.filter(
        StudioGenerationTask.id == int(task_id),
    )
    if claim_token is not None:
        query = query.filter(
            StudioGenerationTask.poll_claim_token == claim_token,
        )
    return query.with_for_update().first()


def _uploaded_asset_paths(assets, existing_ids=None):
    existing_ids = {int(value) for value in (existing_ids or ())}
    result = []
    for asset in assets or ():
        if not asset or not getattr(asset, "id", None):
            continue
        if int(asset.id) in existing_ids:
            continue
        # Only assets uploaded by the current persistence attempt are safe to
        # remove after a cancellation. Existing assets returned by the
        # idempotent path must never be mistaken for newly uploaded files.
        if not getattr(asset, "_storage_uploaded_in_operation", False):
            continue
        path = str(
            getattr(asset, "storage_path", None)
            or getattr(asset, "public_url", None)
            or ""
        ).strip()
        if path:
            result.append(
                (
                    path,
                    getattr(asset, "checksum", None),
                    SimpleNamespace(
                        dept_id=getattr(asset, "dept_id", None),
                        asset_type=getattr(asset, "asset_type", None),
                        purpose=getattr(asset, "purpose", None),
                        retention_policy=getattr(
                            asset,
                            "retention_policy",
                            FileService.TEMPORARY,
                        ),
                        original_filename=getattr(
                            asset,
                            "original_filename",
                            None,
                        ),
                        content_type=getattr(asset, "content_type", None),
                        file_size=getattr(asset, "file_size", None),
                        checksum=getattr(asset, "checksum", None),
                        generation_task_id=getattr(
                            asset,
                            "generation_task_id",
                            None,
                        ),
                        created_by=getattr(asset, "created_by", None),
                    ),
                )
            )
    return result


def _discard_uploaded_storage(paths):
    """Best-effort cleanup for a result uploaded before a cancellation won."""

    for item in paths or ():
        path, checksum = item[:2]
        source_asset = item[2] if len(item) > 2 else None
        try:
            deleted = FileService.delete_storage(path, checksum=checksum)
            if deleted is False:
                raise StorageError("GoFastDFS 返回删除失败")
        except Exception:
            if source_asset is not None:
                try:
                    FileService._record_failed_cleanup(
                        source_asset=source_asset,
                        storage_path=path,
                        checksum=checksum,
                        error_message="取消任务后的生成结果清理失败",
                    )
                except Exception:
                    current_app.logger.exception(
                        "failed to record discarded generation output path=%s",
                        path,
                    )
            current_app.logger.exception(
                "failed to discard cancelled generation output path=%s",
                path,
            )


def _asset_is_active(asset):
    return bool(
        asset
        and asset.status == "ACTIVE"
        and not (
            asset.expires_at
            and asset.expires_at <= datetime.datetime.now()
        )
    )


def _product_asset_is_accessible(asset, user):
    """Use only canonical product assets inside the caller's data scope."""

    if not asset or not asset.storage_asset_id:
        return True
    storage_asset = getattr(asset, "storage_asset", None)
    if storage_asset is None:
        storage_asset = StudioAsset.query.filter_by(
            id=asset.storage_asset_id,
        ).first()
    return bool(
        storage_asset
        and _asset_is_active(storage_asset)
        and can_access_asset(user, storage_asset)
    )


def _dump(value):
    return json.dumps(value, ensure_ascii=False, default=str) if value is not None else None


def _result_payload_snapshot(value):
    """Persist a bounded response summary without storing returned image bytes."""

    serialized = _dump(redact_provider_payload(value))
    if serialized is None:
        return None
    encoded = serialized.encode("utf-8")
    if len(encoded) <= MAX_RESULT_PAYLOAD_BYTES:
        return serialized

    preview = _truncate_utf8(serialized, 40000)
    return _dump(
        {
            "summary": "provider response snapshot truncated",
            "original_bytes": len(encoded),
            "preview": preview,
        }
    )


def _new_task_code():
    for _ in range(50):
        # Keep one character from each class so new identifiers are visibly
        # different from the legacy all-numeric task codes.
        chars = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
        ]
        chars.extend(
            secrets.choice(TASK_CODE_ALPHABET)
            for _ in range(TASK_CODE_LENGTH - len(chars))
        )
        for index in range(len(chars) - 1, 0, -1):
            swap_index = secrets.randbelow(index + 1)
            chars[index], chars[swap_index] = chars[swap_index], chars[index]
        code = "".join(chars)
        if not StudioGenerationTask.query.filter_by(task_code=code).first():
            return code
    raise RuntimeError("无法生成唯一的 7 位字母数字任务编号")


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

    def walk(node, allow_scalar=False):
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
                    walk(node[key], allow_scalar=True)
        elif isinstance(node, list):
            for item in node:
                walk(item, allow_scalar=allow_scalar)
        elif allow_scalar and isinstance(node, str):
            value = node.strip()
            if value.startswith(("http://", "https://")):
                add_output(url=value)
            elif value.startswith("data:image/"):
                add_output(encoded=value)

    walk(payload, allow_scalar=False)
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


def _reference_assets(
    user_id,
    asset_ids,
    media_type,
    video_only=False,
    department_id=None,
    user=None,
):
    if not asset_ids:
        return []
    requested_ids = list(dict.fromkeys(int(item) for item in asset_ids))
    filters = [
        StudioAsset.id.in_(requested_ids),
        StudioAsset.status == "ACTIVE",
        StudioAsset.purpose == "GENERATION_REFERENCE",
    ]
    if department_id is not None:
        filters.append(StudioAsset.dept_id == department_id)
    assets = StudioAsset.query.filter(*filters).all()
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
        if not can_access_asset(user, asset):
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


def _upload_provider_output(task, output, filename, asset_type):
    """Stage one provider output locally, then upload it to GoFastDFS."""

    output_value = output.get("url") or output.get("data")
    if not output_value:
        return None

    attempts = 2
    try:
        attempts = max(
            1,
            int(
                current_app.config.get("STUDIO_OUTPUT_UPLOAD_ATTEMPTS")
                or 2
            ),
        )
    except (TypeError, ValueError, RuntimeError):
        attempts = 2

    temporary_path = None
    try:
        content_type = output.get("format")
        if output.get("data"):
            encoded = str(output_value)
            if encoded.startswith("data:"):
                header, encoded = encoded.split(",", 1)
                content_type = (
                    header[5:].split(";", 1)[0].strip()
                    or content_type
                )
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise StorageError(
                    "provider returned invalid base64 output"
                ) from exc

            if content_type and "/" not in str(content_type):
                content_type = (
                    f"{'video' if asset_type == 'VIDEO' else 'image'}"
                    f"/{content_type}"
                )
            suffix = os.path.splitext(filename)[1] or ".bin"
            try:
                with tempfile.NamedTemporaryFile(
                    prefix="commerce-studio-provider-",
                    suffix=suffix,
                    delete=False,
                ) as temporary_file:
                    temporary_path = temporary_file.name
                    temporary_file.write(raw)
            except OSError as exc:
                raise StorageError(
                    "provider output temporary file could not be created"
                ) from exc

        for attempt in range(1, attempts + 1):
            try:
                if temporary_path:
                    return FileService.upload_local_file(
                        temporary_path,
                        filename=filename,
                        content_type=content_type,
                        asset_type=asset_type,
                        purpose="GENERATION_OUTPUT",
                        retention_policy=FileService.TEMPORARY,
                        created_by=task.user_id,
                        dept_id=task.dept_id,
                        record=False,
                    )

                # upload_from_url already downloads the short-lived provider
                # URL into a local temporary file before GoFastDFS receives it.
                return FileService.upload_from_url(
                    output_value,
                    filename=filename,
                    asset_type=asset_type,
                    purpose="GENERATION_OUTPUT",
                    retention_policy=FileService.TEMPORARY,
                    created_by=task.user_id,
                    dept_id=task.dept_id,
                    record=False,
                )
            except StorageError as exc:
                if attempt >= attempts:
                    raise
                current_app.logger.warning(
                    "provider output upload retry: task_code=%s "
                    "output=%s attempt=%s/%s error=%s",
                    getattr(task, "task_code", ""),
                    filename,
                    attempt,
                    attempts,
                    str(exc),
                )
        return None
    finally:
        if temporary_path:
            try:
                os.remove(temporary_path)
            except OSError:
                pass


def _persist_provider_outputs(task, payload):
    """Copy all provider outputs into go-fastdfs and keep the first URL compatible."""

    existing = generation_task_assets(
        task.id,
        roles={"OUTPUT", "RESULT", "THUMBNAIL"},
        include_legacy=True,
    )
    existing = [
        asset
        for asset in existing
        if asset.purpose == "GENERATION_OUTPUT"
        and asset.status == "ACTIVE"
    ]
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
            stored = _upload_provider_output(
                task,
                output,
                filename,
                asset_type,
            )
            if not stored:
                continue
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
                    retention_policy=FileService.TEMPORARY,
                    created_by=task.user_id,
                    dept_id=task.dept_id,
                    generation_task_id=task.id,
                )
            )
            assets[-1]._storage_uploaded_in_operation = True
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
        ensure_generation_asset_links(
            task.id,
            assets,
            "OUTPUT",
        )
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


def _requested_department_id(user_id, options, acting_user=None):
    """Resolve a requested department without trusting a normal user."""

    requested = options.get("department_id", options.get("dept_id"))
    requested_id = None
    if requested not in (None, ""):
        try:
            requested_id = int(requested)
        except (TypeError, ValueError) as exc:
            raise ValueError("部门选择无效") from exc

    request_user = None
    if has_request_context() and getattr(
        current_user,
        "is_authenticated",
        False,
    ):
        request_user = current_user
    if request_user:
        if request_user.id != user_id:
            raise ValueError("不能代表其他用户发起创作请求")
        user = request_user
    elif acting_user is not None:
        if getattr(acting_user, "id", None) != user_id:
            raise ValueError("不能代表其他用户发起创作请求")
        user = acting_user
    else:
        user = User.query.get(user_id)
    if not user:
        raise ValueError("当前用户不存在")

    if not is_super_admin_user(user):
        requested_id = user_department_id(user)
        if requested_id is None:
            raise ValueError("请先为当前管理员或用户指定管理部门")
    elif requested_id is None:
        requested_id = user_department_id(user)
        if requested_id is None:
            raise ValueError("请先为当前管理员指定默认部门")
    elif not Dept.query.filter_by(id=requested_id).first():
        raise ValueError("部门不存在")
    return requested_id


def create_generation(
    user_id,
    media_type,
    model_id,
    product_id,
    prompt,
    options=None,
    acting_user=None,
):
    """Create a local task, submit it upstream, and persist the request snapshot."""

    options = options or {}
    media_type = str(media_type or "IMAGE").upper()
    if media_type not in ("IMAGE", "VIDEO"):
        raise ValueError("不支持的创作类型")
    try:
        model_id = int(model_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("请选择有效模型") from exc

    requesting_user = (
        current_user
        if has_request_context()
        and getattr(current_user, "is_authenticated", False)
        else acting_user
    )
    if requesting_user is None:
        requesting_user = User.query.get(user_id)
    if not requesting_user:
        raise ValueError("当前用户不存在")
    requested_department_id = _requested_department_id(
        user_id,
        options,
        acting_user=requesting_user,
    )
    # Provider ownership is always a real department. The legacy
    # ``provider_owner_type`` option remains accepted for old clients, but it
    # cannot create a virtual super-admin scope or bypass department checks.
    requested_owner_type = PROVIDER_OWNER_DEPARTMENT
    model_query = (
        StudioModel.query.join(StudioProvider)
        .filter(
            StudioModel.id == model_id,
            StudioModel.enabled == 1,
            StudioProvider.enabled == 1,
            StudioProvider.dept_id == requested_department_id,
        )
    )
    model = model_query.first()
    if not model:
        raise ValueError("模型不存在或已停用")
    department_id = getattr(model.provider, "dept_id", None)
    if department_id is None:
        raise ValueError("模型供应商尚未归属部门")
    if not can_access_model(
        requesting_user,
        model,
        department_id=department_id,
        owner_type=requested_owner_type,
    ):
        raise ValueError("无权使用该语言模型或供应商配置")
    if model.media_type != media_type:
        raise ValueError("当前模型与创作类型不匹配")
    if not model.provider or not model.provider.enabled:
        raise ValueError("模型供应商不存在或已停用")
    provider_api_key = str(model.provider.api_key or "").strip()
    if not provider_api_key:
        raise ValueError("请先在模型供应商中填写 API Key")
    if not str(prompt or "").strip():
        raise ValueError("创意描述不能为空")

    product = _resolve_generation_product(
        product_id,
        department_id,
        requesting_user,
    )
    if product_id and not product:
        raise ValueError("产品不存在、已停用或不属于当前部门")

    skill_id = options.get("skill_id")
    try:
        skill_id = int(skill_id) if skill_id not in (None, "") else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Skill 不存在或已停用") from exc
    skill = _resolve_generation_skill(
        skill_id,
        department_id,
        requesting_user,
    )
    if skill_id and not skill:
        raise ValueError("Skill 不存在、已停用或不属于当前部门")
    if skill:
        if skill.media_type not in ("BOTH", media_type):
            raise ValueError("当前 Skill 与创作类型不匹配")

    reference_image_assets = _reference_assets(
        user_id,
        options.get("reference_asset_ids") or [],
        media_type,
        video_only=False,
        department_id=department_id,
        user=requesting_user,
    )
    reference_video_assets = (
        []
        if media_type == "IMAGE"
        else _reference_assets(
            user_id,
            options.get("reference_video_asset_ids") or [],
            media_type,
            video_only=True,
            department_id=department_id,
            user=requesting_user,
        )
    )
    extra_urls = [asset.public_url for asset in reference_image_assets]
    extra_urls.extend(split_urls(options.get("reference_images")))
    extra_videos = []
    if media_type == "VIDEO":
        extra_videos = split_urls(options.get("reference_videos"))
        extra_videos.extend(asset.public_url for asset in reference_video_assets)
    product_descriptors = product_reference_descriptors(
        product,
        extra_urls,
        media_type,
        asset_filter=lambda asset: _product_asset_is_accessible(
            asset,
            requesting_user,
        ),
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
    if skill:
        skill_prompt = read_skill_text(
            skill,
            user=requesting_user,
            builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
        )
    else:
        skill_prompt = str(options.get("skill_prompt") or "").strip()
    skill_name = (
        str(skill.name or "").strip()
        if skill
        else str(options.get("skill_name") or "").strip()
    )
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
        "generate_audio": (
            options.get("generate_audio")
            if options.get("generate_audio") is not None
            else False
        ),
        "reference_images": product_urls,
        "reference_images_with_roles": reference_roles(
            product_descriptors,
            "reference_image",
        ),
        "reference_videos": extra_videos,
        "reference_videos_with_roles": reference_roles(extra_videos, "reference_video"),
    }
    if (
        media_type == "IMAGE"
        and skill
        and str(getattr(skill, "code", "") or "").strip()
        == DETAIL_IMAGE_SKILL_CODE
    ):
        # A planner may return a concise prompt that omits part of the
        # reusable detail-image rules. Keep the hard visual contract in the
        # actual provider request, while preserving the 5000-byte limit.
        runtime["prompt"] = append_detail_image_output_contract(
            runtime["prompt"],
            MAX_FINAL_PROMPT_BYTES,
        )
    # Keep direct submissions and planner-assisted submissions consistent.
    # The prompt starts with the operator's creative request, so truncating
    # from the end preserves the highest-priority creative instruction.
    runtime["prompt"] = _truncate_utf8(
        runtime["prompt"],
        MAX_FINAL_PROMPT_BYTES,
    )
    body = build_request_body(model, runtime, options.get("extra_fields") or {})
    if media_type == "IMAGE":
        # Image providers must never receive video-reference fields, even if
        # a stale dynamic model schema or client payload includes them.
        body.pop("reference_videos", None)
        body.pop("video_with_roles", None)
    final_prompt = runtime["prompt"]
    provider_id = model.provider.id
    product_record_id = product.id if product else None
    model_record_id = model.id
    model_code = model.model_code
    current_app.logger.info(
        "studio generation request prepared: media_type=%s model_id=%s "
        "model_code=%s provider_id=%s product_id=%s task_prompt=%s "
        "final_prompt=%s request_body=%s",
        media_type,
        model_record_id,
        model_code,
        provider_id,
        product_record_id,
        str(prompt).strip(),
        final_prompt,
        _dump(redact_provider_payload(body)),
    )
    provider_snapshot = _provider_snapshot(
        model.provider,
        api_key=provider_api_key,
    )
    model_snapshot = _model_snapshot(model)
    execution_context = ExecutionContext(
        user_id=user_id,
        dept_id=department_id,
        provider=provider_snapshot,
        model=model_snapshot,
        skill=_skill_execution_snapshot(skill, prompt=skill_prompt),
        product=_product_execution_snapshot(product),
        input_assets=tuple(
            _asset_execution_snapshot(asset)
            for asset in (
                list(reference_image_assets)
                + list(reference_video_assets)
            )
        ),
        reference_image_urls=tuple(product_urls),
        reference_video_urls=tuple(extra_videos),
        final_prompt=final_prompt,
        metadata={"media_type": media_type},
    )

    created_at = datetime.datetime.now()
    expires_at = _terminal_expiry(created_at)
    task = None
    for attempt in range(5):
        candidate = StudioGenerationTask(
            task_code=_new_task_code(),
            dept_id=department_id,
            user_id=user_id,
            media_type=media_type,
            product_id=product.id if product else None,
            model_id=model.id,
            skill_id=skill.id if skill else skill_id,
            skill_name=skill_name or None,
            skill_prompt=skill_prompt or None,
            prompt=str(prompt).strip(),
            final_prompt=final_prompt,
            # Keep the nullable legacy columns for old readers. New code also
            # stores these fields in studio_generation_task_detail.
            negative_prompt=None,
            request_body=_dump(redact_provider_payload(body)),
            status="PENDING",
            progress=0,
            retention_policy=FileService.TEMPORARY,
            expires_at=expires_at,
        )
        db.session.add(candidate)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            if attempt == 4:
                raise RuntimeError("无法生成唯一的创作任务编号")
            continue
        task = candidate
        break
    if task is None:
        raise RuntimeError("无法创建创作任务")
    execution_context.task_id = task.id
    execution_context.task_code = task.task_code

    _sync_generation_detail(
        task,
        skill_prompt=skill_prompt or None,
        prompt=str(prompt).strip(),
        final_prompt=final_prompt,
        negative_prompt=None,
        request_body=_dump(redact_provider_payload(body)),
    )
    ensure_generation_asset_links(
        task.id,
        reference_image_assets,
        "REFERENCE_IMAGE",
    )
    ensure_generation_asset_links(
        task.id,
        reference_video_assets,
        "REFERENCE_VIDEO",
    )
    db.session.commit()
    task_id = task.id
    task_code = task.task_code
    # No database connection is needed while the provider performs the
    # network request. Reload the row only after the response arrives.
    release_db_connection()

    uploaded_paths = []
    upstream_accepted = False
    try:
        client = ProviderClient(execution_context.provider)

        def submit_once():
            response = client.submit_generation(
                execution_context.model,
                body,
            )
            provider_task_id = _extract_provider_task_id(response)
            provider_outputs = _has_provider_outputs(response)
            state = _provider_status(response)
            if state == "failed":
                raise ProviderRequestError(
                    _provider_error_message(response),
                    payload=response,
                )
            if not (
                provider_outputs
                or bool(provider_task_id)
                or state in ("submitted", "processing", "completed")
            ):
                raise ProviderRequestError(
                    "供应商响应中没有任务 ID 或图片输出",
                    payload=response,
                )
            return (
                response,
                provider_task_id,
                provider_outputs,
                state,
            )

        # Release the checked-out database connection before every potentially
        # long provider request. All retries reuse the one local task row.
        release_db_connection()
        (
            response,
            provider_task_id,
            provider_outputs,
            state,
        ) = provider_retry_call(
            submit_once,
            operation_name=f"studio generation {task_code}",
        )
        upstream_accepted = True
        sync_output = provider_outputs and state not in (
            "submitted",
            "processing",
            "failed",
        )
        working_task = StudioGenerationTask.query.get(task_id)
        if not working_task:
            raise ProviderRequestError("创作任务已不存在")
        if sync_output:
            persisted = _persist_provider_outputs(working_task, response)
            uploaded_paths = _uploaded_asset_paths(persisted)
            if not persisted:
                raise ProviderRequestError(
                    "任务已完成，但没有可持久化的输出资产",
                    payload=response,
                )
        elif not provider_task_id:
            raise ProviderRequestError("供应商响应中没有任务 ID", payload=response)

        # The remote request is complete, but cancellation may have committed
        # while the provider was processing it. Resolve the final state under
        # a short row lock so the first committed transition wins.
        locked_task = _task_state_for_update(task_id)
        if not locked_task:
            db.session.rollback()
            _discard_uploaded_storage(uploaded_paths)
            raise ProviderRequestError("创作任务已不存在")
        if locked_task.status not in EXECUTION_ACTIVE_STATUSES:
            db.session.rollback()
            _discard_uploaded_storage(uploaded_paths)
            current_task = StudioGenerationTask.query.get(task_id)
            if current_task:
                return _sync_task_state(task, current_task)
            raise ProviderRequestError("创作任务已不存在")

        result_payload = _result_payload_snapshot(response)
        locked_task.result_payload = result_payload
        locked_task.progress = _safe_progress(response)
        _sync_generation_detail(
            locked_task,
            result_payload=result_payload,
            error_message=None,
        )
        if sync_output:
            locked_task.status = "SUCCEEDED"
            locked_task.progress = 100
            _mark_terminal(locked_task)
        elif state == "failed":
            locked_task.status = "FAILED"
            locked_task.error_message = _provider_error_message(response)
            _sync_generation_detail(
                locked_task,
                error_message=locked_task.error_message,
            )
            _mark_terminal(locked_task)
        else:
            locked_task.provider_task_id = str(provider_task_id)
            locked_task.status = (
                "PROCESSING" if state == "processing" else "SUBMITTED"
            )
        db.session.commit()
        return _sync_task_state(task, locked_task)
    except Exception as exc:
        if upstream_accepted:
            # The provider already accepted or completed this request. A
            # storage/database failure must not cause the batch caller to
            # spend credits on a second provider request.
            setattr(exc, "_upstream_accepted", True)
            setattr(exc, "_generation_task_id", task_id)
        db.session.rollback()
        _discard_uploaded_storage(uploaded_paths)
        current_task = _task_state_for_update(task_id)
        if current_task and current_task.status in EXECUTION_ACTIVE_STATUSES:
            current_task.status = "FAILED"
            current_task.error_message = str(exc)
            _sync_generation_detail(
                current_task,
                result_payload=None,
                error_message=str(exc),
            )
            _mark_terminal(current_task)
            db.session.commit()
        else:
            db.session.rollback()
        current_app.logger.exception(
            "studio generation request failed: task_code=%s media_type=%s "
            "model_id=%s model_code=%s provider_id=%s product_id=%s "
            "request_body=%s upstream_payload=%s",
            task_code,
            media_type,
            model_record_id,
            model_code,
            provider_id,
            product_record_id,
            _dump(redact_provider_payload(body)),
            _dump(getattr(exc, "payload", None)),
        )
        raise


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
        locked_task = _task_state_for_update(task_id)
        if locked_task and locked_task.status in ACTIVE_STATUSES:
            locked_task.status = "FAILED"
            locked_task.error_message = "关联模型或供应商不存在"
            _mark_terminal(locked_task)
            db.session.commit()
            return _sync_task_state(original_task, locked_task)
        db.session.rollback()
        return original_task
    execution_context = ExecutionContext(
        task_id=task_id,
        task_code=getattr(task, "task_code", ""),
        user_id=getattr(task, "user_id", None),
        dept_id=getattr(task, "dept_id", None),
        provider=_provider_snapshot(model.provider),
        model=_model_snapshot(model),
    )
    claim_token = secrets.token_hex(24)
    now = datetime.datetime.now()
    stale_at = now - datetime.timedelta(minutes=5)
    claimed = (
        db.session.query(StudioGenerationTask)
        .filter(
            StudioGenerationTask.id == task_id,
            StudioGenerationTask.status.in_(ACTIVE_STATUSES),
            StudioGenerationTask.provider_task_id == provider_task_id,
            (
                StudioGenerationTask.poll_claimed_at.is_(None)
                | (StudioGenerationTask.poll_claimed_at < stale_at)
            ),
        )
        .update(
            {
                StudioGenerationTask.poll_claim_token: claim_token,
                StudioGenerationTask.poll_claimed_at: now,
            },
            synchronize_session=False,
        )
    )
    db.session.commit()
    if not claimed:
        return original_task

    uploaded_paths = []
    try:
        # The upstream request can take seconds or minutes. Do not keep the
        # SQLAlchemy connection checked out while waiting on that network call.
        release_db_connection()
        client = ProviderClient(execution_context.provider)
        payload = provider_retry_call(
            lambda: client.fetch_generation_result(
                execution_context.model,
                provider_task_id,
                media_type,
            ),
            operation_name=f"studio polling {getattr(original_task, 'task_code', '')}",
        )
        working_task = StudioGenerationTask.query.get(task_id)
        if not working_task:
            db.session.rollback()
            return original_task
        state = _provider_status(payload)
        if state == "completed" or (
            not state and _has_provider_outputs(payload)
        ):
            persisted = _persist_provider_outputs(working_task, payload)
            uploaded_paths = _uploaded_asset_paths(persisted)

        # Output files are uploaded before this lock is taken so the DB
        # transaction stays short. If cancellation or another poller won
        # first, the current transaction is rolled back and only files marked
        # by this attempt are removed.
        locked_task = _task_state_for_update(task_id, claim_token)
        if (
            not locked_task
            or locked_task.status not in ACTIVE_STATUSES
            or locked_task.poll_claim_token != claim_token
        ):
            db.session.rollback()
            _discard_uploaded_storage(uploaded_paths)
            current_task = StudioGenerationTask.query.get(task_id)
            return (
                _sync_task_state(original_task, current_task)
                if current_task
                else original_task
            )

        result_payload = _result_payload_snapshot(payload)
        locked_task.result_payload = result_payload
        locked_task.progress = _safe_progress(
            payload,
            locked_task.progress or 0,
        )
        _sync_generation_detail(
            locked_task,
            result_payload=result_payload,
            error_message=None,
        )
        if state == "completed" or (
            not state and _has_provider_outputs(payload)
        ):
            locked_task.status = "SUCCEEDED"
            locked_task.progress = 100
            locked_task.error_message = None
            if not persisted:
                locked_task.status = "FAILED"
                locked_task.error_message = (
                    "任务已完成，但响应中没有输出 URL"
                )
            _mark_terminal(locked_task)
        elif state == "failed":
            locked_task.status = "FAILED"
            error = _provider_error_message(payload)
            locked_task.error_message = (
                error.get("message")
                if isinstance(error, dict)
                else str(error or "上游生成失败")
            )
            _sync_generation_detail(
                locked_task,
                error_message=locked_task.error_message,
            )
            _mark_terminal(locked_task)
        else:
            locked_task.status = (
                "SUBMITTED" if state == "submitted" else "PROCESSING"
            )
            locked_task.error_message = None
        locked_task.poll_claim_token = None
        locked_task.poll_claimed_at = None
        db.session.commit()
        return _sync_task_state(original_task, locked_task)
    except StorageError as exc:
        db.session.rollback()
        _discard_uploaded_storage(uploaded_paths)
        task = _task_state_for_update(task_id, claim_token)
        if task and (
            task.status in ACTIVE_STATUSES
            and task.poll_claim_token == claim_token
        ):
            task.status = "FAILED"
            task.error_message = str(exc)
            _sync_generation_detail(
                task,
                error_message=str(exc),
            )
            _mark_terminal(task)
            task.poll_claim_token = None
            task.poll_claimed_at = None
            db.session.commit()
        else:
            db.session.rollback()
        current_app.logger.exception(
            "studio generation output persistence failed: task_code=%s "
            "provider_task_id=%s media_type=%s error=%s",
            getattr(task, "task_code", None) or getattr(
                original_task,
                "task_code",
                "",
            ),
            provider_task_id,
            media_type,
            str(exc),
        )
    except Exception as exc:
        db.session.rollback()
        _discard_uploaded_storage(uploaded_paths)
        task = _task_state_for_update(task_id, claim_token)
        if task and (
            task.status in ACTIVE_STATUSES
            and task.poll_claim_token == claim_token
        ):
            task.error_message = str(exc)
            task.poll_claim_token = None
            task.poll_claimed_at = None
            db.session.commit()
        else:
            db.session.rollback()
        current_app.logger.exception(
            "studio generation polling failed: task_code=%s "
            "provider_task_id=%s media_type=%s error=%s",
            getattr(task, "task_code", None) or getattr(
                original_task,
                "task_code",
                "",
            ),
            provider_task_id,
            media_type,
            str(exc),
        )
    current_task = StudioGenerationTask.query.get(task_id)
    return (
        _sync_task_state(original_task, current_task)
        if current_task
        else original_task
    )


def poll_processing_tasks():
    """Poll a bounded batch with one SQLAlchemy Session per worker thread."""

    batch_size = 20
    try:
        batch_size = max(
            1,
            int(current_app.config.get("STUDIO_POLL_BATCH_SIZE") or 20),
        )
    except (TypeError, ValueError):
        pass
    task_ids = [
        int(task_id)
        for (task_id,) in (
            db.session.query(StudioGenerationTask.id)
            .filter(StudioGenerationTask.status.in_(ACTIVE_STATUSES))
            .order_by(StudioGenerationTask.created_at.asc())
            .limit(batch_size)
            .all()
        )
    ]
    # The list query is complete; release its connection before polling.
    db.session.remove()

    if not task_ids:
        return 0

    app = current_app._get_current_object()

    def poll_one(task_id):
        # Flask-SQLAlchemy's scoped session is thread-local. Create the task
        # and all provider/asset ORM state inside the worker's app context.
        with app.app_context():
            try:
                task = (
                    StudioGenerationTask.query.filter_by(id=task_id)
                    .options(
                        joinedload(StudioGenerationTask.model).joinedload(
                            StudioModel.provider
                        )
                    )
                    .first()
                )
                if task:
                    poll_task(task)
            except Exception:
                app.logger.exception(
                    "generation polling worker failed: task_id=%s",
                    task_id,
                )
            finally:
                db.session.remove()

    try:
        max_workers = max(
            1,
            int(
                current_app.config.get("STUDIO_POLL_MAX_WORKERS")
                or 5
            ),
        )
    except (TypeError, ValueError):
        max_workers = 5
    max_workers = min(max_workers, len(task_ids))

    if max_workers == 1:
        for task_id in task_ids:
            poll_one(task_id)
        return len(task_ids)

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="studio-poll",
    ) as executor:
        futures = [
            executor.submit(poll_one, task_id)
            for task_id in task_ids
        ]
        for future in futures:
            future.result()
    return len(task_ids)
