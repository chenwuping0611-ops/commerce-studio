import json
import re
from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import contains_eager, joinedload, selectinload

from applications.amazon_ai.file_text import SUPPORTED_EXTENSIONS
from applications.amazon_ai.permissions import sync_amazon_permissions
from applications.amazon_ai.service import (
    AmazonAiModelError,
    AmazonAiService,
    _mark_terminal,
    _result_filename,
    _split_response_sections,
    global_chat_model_state,
    normalize_result_filename,
    read_task_result_text,
)
from applications.amazon_ai.skill_catalog import (
    AMAZON_BUILTIN_SKILL_CODES,
    PRODUCT_EXTRACTION_SKILL_CODE,
    TASK_SKILL_CODES,
)
from applications.common.scope import (
    can_access_asset,
    can_access_resource,
    department_in_scope,
    has_effective_permission,
    is_department_admin_user,
    is_super_admin_user,
    managed_department_ids,
    PROVIDER_OWNER_DEPARTMENT,
    user_department_id,
)
from applications.common.asset_relations import (
    amazon_task_assets,
    asset_referenced,
)
from applications.common.storage import FileService
from applications.common.utils.rights import authorize
from applications.extensions import db
from applications.models import (
    AMAZON_TASK_TITLES,
    AmazonAiTask,
    AmazonAiTaskAsset,
    Dept,
    StudioAsset,
    StudioModel,
    StudioProduct,
    StudioProvider,
    StudioSkill,
)


amazon_ai_bp = Blueprint("amazon_ai", __name__, url_prefix="/amazon-ai")


@amazon_ai_bp.before_request
def refresh_amazon_permissions():
    sync_amazon_permissions()


AMAZON_TASK_TYPES = {
    "COMPETITOR_ANALYZE",
    "KEYWORD_ANALYZE",
    "REVIEW_ANALYZE",
    "DIFFERENTIATION_GENERATE",
    "BASIC_INFO_CORRECT",
    "LISTING_GENERATE",
    "LISTING_AUDIT",
}
AMAZON_TASK_TYPE_LABELS = dict(AMAZON_TASK_TITLES)
AMAZON_TASK_TYPE_ORDER = (
    "COMPETITOR_ANALYZE",
    "DIFFERENTIATION_GENERATE",
    "BASIC_INFO_CORRECT",
    "LISTING_GENERATE",
)
AMAZON_TASK_PERMISSION_CODES = {
    "COMPETITOR_ANALYZE": "amazon_ai:competitor",
    "KEYWORD_ANALYZE": "amazon_ai:keyword",
    "REVIEW_ANALYZE": "amazon_ai:review",
    "DIFFERENTIATION_GENERATE": "amazon_ai:differentiation",
    "BASIC_INFO_CORRECT": "amazon_ai:basic_info",
    "LISTING_GENERATE": "amazon_ai:listing_create",
    "LISTING_AUDIT": "amazon_ai:listing_create",
}
AMAZON_ASIN_PATTERN = re.compile(
    r"/(?:dp|gp/product)/([A-Z0-9]{10})(?=[/?#&]|$)",
    re.IGNORECASE,
)
AMAZON_OPENAI_FILE_MAX_BYTES = 512 * 1024 * 1024


def _body():
    return request.get_json(silent=True) or request.form.to_dict()


def _json(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _requested_provider_owner_type(body=None):
    del body
    # Kept as a compatibility helper for old request builders. Provider
    # ownership is now always tied to a real department.
    return PROVIDER_OWNER_DEPARTMENT


def _task_permission_code(task_type):
    return AMAZON_TASK_PERMISSION_CODES.get(
        str(task_type or "").strip().upper()
    )


def _has_task_permission(task_type, include_history=False):
    required = _task_permission_code(task_type)
    if required and has_effective_permission(required):
        return True
    return bool(
        include_history
        and has_effective_permission("amazon_ai:history")
    )


def _visible_department_ids():
    if is_super_admin_user():
        return None
    department_id = user_department_id()
    return [department_id] if department_id else [-1]


def _request_department_id(body=None):
    body = body or {}
    requested = body.get("department_id")
    if requested in (None, ""):
        requested = body.get("dept_id")
    department_id = (
        _int_or_none(requested)
        if requested not in (None, "")
        else user_department_id()
    )
    if not is_super_admin_user():
        department_id = user_department_id()
    if department_id is None:
        raise ValueError("请先为当前用户指定部门")
    if not Dept.query.filter_by(id=department_id).first():
        raise ValueError("部门不存在")
    if not is_super_admin_user() and not department_in_scope(
        department_id,
        include_descendants=False,
    ):
        raise ValueError("无权使用该部门")
    return department_id


def _scoped_studio_model_query():
    query = (
        StudioModel.query
        .join(StudioProvider)
        .join(Dept, Dept.id == StudioProvider.dept_id)
        .options(contains_eager(StudioModel.provider))
        .filter(
            StudioProvider.dept_id.isnot(None),
            StudioProvider.owner_type == PROVIDER_OWNER_DEPARTMENT,
        )
    )
    visible = _visible_department_ids()
    if visible is not None:
        query = query.filter(StudioProvider.dept_id.in_(visible))
    return query


def _scoped_studio_skill_query():
    query = StudioSkill.query
    if is_super_admin_user():
        return query
    department_id = user_department_id()
    if department_id is None:
        return query.filter(False)
    if is_department_admin_user():
        return query.filter(
            or_(
                StudioSkill.dept_id == department_id,
                StudioSkill.code.in_(AMAZON_BUILTIN_SKILL_CODES),
            )
        )
    query = query.filter(
        or_(
            StudioSkill.code.in_(AMAZON_BUILTIN_SKILL_CODES),
            and_(
                StudioSkill.dept_id == department_id,
                StudioSkill.created_by == current_user.id,
            ),
        )
    )
    return query


def _scoped_studio_product_query():
    query = StudioProduct.query
    if is_super_admin_user():
        return query
    department_id = user_department_id()
    if department_id is None:
        return query.filter(False)
    if is_department_admin_user():
        return query.filter(StudioProduct.dept_id == department_id)
    query = query.filter(
        StudioProduct.dept_id == department_id,
        StudioProduct.created_by == current_user.id,
    )
    return query


def _scoped_studio_asset_query():
    query = StudioAsset.query
    if is_super_admin_user():
        return query
    department_id = user_department_id()
    if department_id is None:
        return query.filter(False)
    if is_department_admin_user():
        return query.filter(StudioAsset.dept_id == department_id)
    query = query.filter(
        StudioAsset.dept_id == department_id,
        StudioAsset.created_by == current_user.id,
    )
    return query


def _scoped_amazon_task_query():
    query = AmazonAiTask.query
    if is_super_admin_user():
        return query
    department_id = user_department_id()
    if department_id is None:
        return query.filter(False)
    if is_department_admin_user():
        return query.filter(AmazonAiTask.dept_id == department_id)
    query = query.filter(
        AmazonAiTask.dept_id == department_id,
        AmazonAiTask.user_id == current_user.id,
    )
    return query


def _scoped_task_by_ref(task_ref, **filters):
    value = str(task_ref or "").strip()
    query = _scoped_amazon_task_query()
    if filters:
        query = query.filter_by(**filters)
    if value.isdigit():
        task = query.filter(AmazonAiTask.id == int(value)).first()
        if task:
            return task
    return query.filter(AmazonAiTask.task_code == value).first()


def _locked_task_by_ref(task_ref, **filters):
    """Resolve and lock one visible task for a short state transition."""

    value = str(task_ref or "").strip()
    query = _scoped_amazon_task_query()
    if filters:
        query = query.filter_by(**filters)
    if value.isdigit():
        query = query.filter(AmazonAiTask.id == int(value))
    else:
        query = query.filter(AmazonAiTask.task_code == value)
    return query.with_for_update().first()


def _with_task_loaders(query):
    return query.options(
        joinedload(AmazonAiTask.model),
        joinedload(AmazonAiTask.skill),
        joinedload(AmazonAiTask.studio_product),
        selectinload(AmazonAiTask.asset_links).joinedload(
            AmazonAiTaskAsset.asset
        ),
    )


def _date_text(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def _task_file_refs(task):
    refs = _json(task.file_refs_json, {}) or {}
    if not isinstance(refs, dict):
        refs = {}
    for key in ("inputs", "results", "legacy_urls"):
        refs[key] = refs.get(key) if isinstance(refs.get(key), list) else []
    return refs


def _file_ref_asset_id(item):
    return _int_or_none(item.get("asset_id")) if isinstance(item, dict) else None


def _file_ref_url(item):
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("public_url")
        or item.get("url")
        or item.get("storage_path")
        or ""
    ).strip()


def _file_ref_filename(item):
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("original_filename")
        or item.get("filename")
        or ""
    ).strip()


def _file_ref_is_active(item):
    if not isinstance(item, dict):
        return False
    if str(item.get("status") or "ACTIVE").upper() not in (
        "ACTIVE",
        "DELETE_FAILED",
    ):
        return False
    raw = str(item.get("expires_at") or "").strip()
    if not raw:
        return True
    try:
        expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if expiry.tzinfo:
            expiry = expiry.replace(tzinfo=None)
        return expiry > datetime.now()
    except ValueError:
        return True


def _task_response_filename(task):
    refs = _json(task.result_refs_json, {}) or {}
    return str(
        getattr(task, "output_filename", None)
        or refs.get("response_filename")
        or ""
    ).strip()


def _asset_is_active(asset):
    return bool(
        asset
        and asset.status == "ACTIVE"
        and not (asset.expires_at and asset.expires_at <= datetime.now())
    )


def _task_result_file_ref(task):
    refs = _task_file_refs(task)
    output_asset_id = _int_or_none(task.output_asset_id)
    for item in refs["results"]:
        if output_asset_id and _file_ref_asset_id(item) == output_asset_id:
            return item
    return next(
        (item for item in refs["results"] if _file_ref_url(item)),
        None,
    )


def _task_result_storage(task, user=None):
    filename = _task_response_filename(task) or None
    if str(task.storage_cleanup_status or "").upper() == "DELETED":
        return "", filename or "", ""

    asset = None
    if task.output_asset_id:
        asset = next(
            (
                link.asset
                for link in (getattr(task, "asset_links", ()) or ())
                if link.asset and link.asset.id == task.output_asset_id
            ),
            None,
        )
        if asset is None:
            asset = StudioAsset.query.filter_by(
                id=task.output_asset_id
            ).first()
    if _asset_is_active(asset) and can_access_asset(user, asset):
        try:
            return FileService.download_url(asset, filename), (
                filename or asset.original_filename or ""
            ), ""
        except Exception as exc:
            return "", filename or "", str(exc)

    snapshot = _task_result_file_ref(task)
    if snapshot and _file_ref_is_active(snapshot):
        url = _file_ref_url(snapshot)
        snapshot_asset_id = _file_ref_asset_id(snapshot)
        snapshot_asset = None
        if snapshot_asset_id:
            snapshot_asset = next(
                (
                    link.asset
                    for link in (getattr(task, "asset_links", ()) or ())
                    if link.asset and link.asset.id == snapshot_asset_id
                ),
                None,
            )
            if snapshot_asset is None:
                snapshot_asset = StudioAsset.query.filter_by(
                    id=snapshot_asset_id
                ).first()
        if snapshot_asset_id and (
            not snapshot_asset
            or not can_access_asset(user, snapshot_asset)
        ):
            return "", filename or "", "关联结果文件无权访问"
        if url:
            try:
                return FileService.download_url(
                    snapshot_asset or url,
                    filename or _file_ref_filename(snapshot) or None,
                ), filename or _file_ref_filename(snapshot) or "", ""
            except Exception as exc:
                return "", filename or "", str(exc)

    refs = _json(task.result_refs_json, {}) or {}
    for key in ("response_download_url", "response_url", "output_url"):
        value = str(refs.get(key) or task.output_url or "").strip()
        if value and FileService.is_managed_url(value):
            try:
                return FileService.download_url(value, filename), filename or "", ""
            except Exception as exc:
                return "", filename or "", str(exc)
    return "", filename or "", ""


def _task_display_id(task):
    if getattr(task, "task_type", "") == "BASIC_INFO_CORRECT":
        return _task_response_filename(task) or str(task.id)
    task_id = getattr(task, "id", None)
    return str(task_id) if task_id is not None else getattr(
        task,
        "task_code",
        "",
    )


def _task_title(task):
    return str(
        task.title
        or AMAZON_TASK_TYPE_LABELS.get(task.task_type, "Amazon AI任务")
    )


def _asset_dict(asset, fallback_filename=None):
    active = _asset_is_active(asset)
    filename = asset.original_filename or fallback_filename or ""
    return {
        "id": asset.id,
        "filename": filename,
        "purpose": asset.purpose,
        "public_url": asset.public_url if active else "",
        "download_url": FileService.download_url(asset, filename) if active else "",
        "status": asset.status,
        "file_size": asset.file_size or 0,
        "content_type": asset.content_type or "",
        "created_at": _date_text(asset.created_at),
        "expires_at": _date_text(asset.expires_at),
    }


def _amazon_upload_max_bytes():
    configured = current_app.config.get("AMAZON_AI_MAX_UPLOAD_FILE_BYTES")
    try:
        configured = int(configured)
    except (TypeError, ValueError):
        configured = AMAZON_OPENAI_FILE_MAX_BYTES
    return min(
        max(configured, 1),
        AMAZON_OPENAI_FILE_MAX_BYTES,
    )


def _file_storage_size(file_storage):
    """Read a multipart file size without consuming its upload stream."""

    declared_size = getattr(file_storage, "content_length", None)
    try:
        declared_size = int(declared_size)
    except (TypeError, ValueError):
        declared_size = 0
    if declared_size > 0:
        return declared_size

    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return None
    try:
        position = stream.tell()
        stream.seek(0, 2)
        size = int(stream.tell())
        stream.seek(position)
        return size
    except (AttributeError, OSError, ValueError):
        return None


def _format_file_size(size):
    megabytes = float(size) / (1024 * 1024)
    if megabytes.is_integer():
        return f"{int(megabytes)} MB"
    return f"{megabytes:.1f} MB"


def _task_dict(task, include_result=False):
    refs = _json(task.result_refs_json, {}) or {}
    input_refs = _json(task.input_refs_json, {}) or {}
    file_refs = _task_file_refs(task)
    download_url, filename, storage_error = _task_result_storage(
        task,
        user=current_user,
    )
    result = {
        "id": task.id,
        "task_number": task.id,
        "task_code": task.task_code,
        "display_id": _task_display_id(task),
        "title": _task_title(task),
        "task_type": task.task_type,
        "task_type_label": AMAZON_TASK_TYPE_LABELS.get(
            task.task_type,
            task.task_type,
        ),
        "status": task.status,
        "priority": task.priority,
        "progress": task.progress,
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "user_id": task.user_id,
        "model_id": task.model_id,
        "model_code": task.model.model_code if task.model else "",
        "skill_id": task.skill_id,
        "skill_name": task.skill.name if task.skill else "",
        "studio_product_id": task.studio_product_id,
        "source_key": task.source_key or "",
        "source_urls": _json(task.source_urls_json, []) or [],
        "source_identifiers": _json(task.source_identifiers_json, []) or [],
        "source_task_codes": _json(task.source_task_codes_json, []) or [],
        "input_asset_ids": _json(task.input_asset_ids_json, []) or [],
        "input_refs": input_refs,
        "result_refs": {
            key: value
            for key, value in refs.items()
            if key != "sections"
        },
        "file_refs": file_refs,
        "output_asset_id": task.output_asset_id,
        "output_url": task.output_url or "",
        "output_filename": filename or task.output_filename or "",
        "response_filename": filename or task.output_filename or "",
        "request_digest": task.request_digest or "",
        "response_digest": task.response_digest or "",
        "provider_task_id": task.provider_task_id or "",
        "error_code": task.error_code or "",
        "error_message": task.error_message or "",
        "scheduled_at": _date_text(task.scheduled_at),
        "started_at": _date_text(task.started_at),
        "heartbeat_at": _date_text(task.heartbeat_at),
        "finished_at": _date_text(task.finished_at),
        "created_at": _date_text(task.created_at),
        "updated_at": _date_text(task.updated_at),
        "retention_policy": task.retention_policy or "",
        "expires_at": _date_text(task.expires_at),
        "storage_cleanup_status": task.storage_cleanup_status or "",
        "storage_cleanup_error": task.storage_cleanup_error or "",
        "storage_deleted_at": _date_text(task.storage_deleted_at),
    }
    if include_result:
        content = ""
        result_error = storage_error
        if task.status == "SUCCEEDED":
            try:
                content = read_task_result_text(
                    task,
                    user=current_user,
                )
            except Exception as exc:
                result_error = str(exc)
        result["response_text"] = content
        result["response_sections"] = _split_response_sections(content) if content else []
        result["response_download_url"] = download_url
        result["response_filename"] = filename or task.output_filename or ""
        result["response_storage_error"] = result_error or ""
    return result


def _set_task_result_refs(task, **refs):
    current = _json(task.result_refs_json, {}) or {}
    if not isinstance(current, dict):
        current = {}
    current.update(
        {
            key: value
            for key, value in refs.items()
            if value not in (None, "")
        }
    )
    task.result_refs_json = json.dumps(
        current,
        ensure_ascii=False,
        default=str,
    )


def _split_urls(value):
    values = value if isinstance(value, (list, tuple)) else [value]
    urls = []
    for raw in values:
        text = str(raw or "").replace("\\&", "&")
        matches = re.findall(
            r"https?://[^\s<>\[\]\"'，,；;）)]+",
            text,
            flags=re.IGNORECASE,
        )
        for item in matches or re.split(r"[\r\n,，；;]+", text):
            url = str(item or "").strip().strip("<>\"' ")
            url = url.rstrip(").]，；;")
            if url and url not in urls:
                urls.append(url)
    return urls


def _extract_asin(url):
    match = AMAZON_ASIN_PATTERN.search(str(url or ""))
    return match.group(1).upper() if match else ""


def _file_base_name(asset):
    name = str(asset.original_filename or "").strip()
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name.strip()


def _timestamp_filename():
    return datetime.now().strftime("%Y-%m-%d-%H-%M")


def _next_competitor_title(department_id, asin):
    pattern = re.compile(
        rf"^{re.escape(asin)}-竞品分析-R(\d+)$",
        re.IGNORECASE,
    )
    maximum = 0
    rows = (
        _scoped_amazon_task_query()
        .filter(
            AmazonAiTask.dept_id == department_id,
            AmazonAiTask.task_type == "COMPETITOR_ANALYZE",
            AmazonAiTask.source_key == asin,
        )
        .with_entities(AmazonAiTask.title)
        .all()
    )
    for (title,) in rows:
        match = pattern.match(str(title or "").strip())
        if match:
            maximum = max(maximum, int(match.group(1)))
    return f"{asin}-竞品分析-R{maximum + 1:02d}"


def _source_task_codes(body):
    value = body.get("source_task_codes")
    if value is None:
        value = body.get("analysis_task_codes")
    if isinstance(value, str):
        parsed = _json(value, None)
        value = parsed if isinstance(parsed, list) else value.split(",")
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []
    return list(
        dict.fromkeys(
            str(item).strip() for item in value if str(item).strip()
        )
    )


def _validate_source_tasks(codes, department_id, expected_types=None):
    if not codes:
        return []
    query = _scoped_amazon_task_query().filter(
        AmazonAiTask.task_code.in_(codes),
        AmazonAiTask.status == "SUCCEEDED",
    )
    if department_id is not None:
        query = query.filter(AmazonAiTask.dept_id == department_id)
    rows = query.all()
    by_code = {row.task_code: row for row in rows}
    missing = [code for code in codes if code not in by_code]
    if missing:
        raise ValueError(
            "所选分析任务不存在、未成功或不属于当前部门："
            + ", ".join(missing)
        )
    if expected_types:
        wrong = [
            f"{row.id}（{row.task_type}）"
            for row in rows
            if row.task_type != expected_types.get(row.task_code)
        ]
        if wrong:
            raise ValueError("所选任务类型与用途不匹配：" + ", ".join(wrong))
    return [by_code[code] for code in codes]


def _asset_ids(body):
    value = body.get("input_asset_ids", body.get("file_ids"))
    if isinstance(value, str):
        parsed = _json(value, None)
        value = parsed if isinstance(parsed, list) else value.split(",")
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []
    result = []
    for item in value:
        normalized = _int_or_none(item)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _validate_input_assets(asset_ids, department_id):
    if not asset_ids:
        return []
    filters = [
        StudioAsset.id.in_(asset_ids),
        StudioAsset.purpose == "AMAZON_INPUT",
        StudioAsset.status == "ACTIVE",
    ]
    if department_id is not None:
        filters.append(StudioAsset.dept_id == department_id)
    assets = _scoped_studio_asset_query().filter(*filters).all()
    by_id = {asset.id: asset for asset in assets if _asset_is_active(asset)}
    missing = [item for item in asset_ids if item not in by_id]
    if missing:
        raise ValueError("输入文件不存在、已过期或不是 Amazon AI 输入文件")
    return [by_id[item] for item in asset_ids]


def _create_service_task(
    body,
    task_type,
    *,
    title=None,
    source_urls=None,
    source_identifiers=None,
    source_key=None,
    output_filename=None,
    source_task_codes=None,
    product_id=None,
    task_metadata=None,
):
    body = dict(body or {})
    provider_owner_type = _requested_provider_owner_type(body)
    department_id = _request_department_id(
        body,
    )
    skill_id = _int_or_none(body.get("skill_id"))
    if task_type not in {"BASIC_INFO_CORRECT", "LISTING_GENERATE"} and not skill_id:
        raise ValueError("请选择本次使用的 Skill")
    asset_ids = _asset_ids(body)
    _validate_input_assets(asset_ids, department_id)
    selected_product_id = (
        _int_or_none(product_id)
        if product_id is not None
        else _int_or_none(body.get("studio_product_id"))
    )
    product_query = _scoped_studio_product_query().filter_by(
        id=selected_product_id,
        enabled=1,
    )
    if selected_product_id and department_id is not None:
        product_query = product_query.filter(
            StudioProduct.dept_id == department_id
        )
    if selected_product_id and not product_query.first():
        raise ValueError("关联的 Studio 产品不存在或未启用")
    codes = source_task_codes if source_task_codes is not None else _source_task_codes(body)
    if codes:
        _validate_source_tasks(codes, department_id)
    return AmazonAiService().create_task(
        user_id=current_user.id,
        task_type=task_type,
        model_id=_int_or_none(body.get("model_id")),
        skill_id=skill_id,
        studio_product_id=selected_product_id,
        input_asset_ids=asset_ids,
        source_task_codes=codes,
        strategy_skill_id=_int_or_none(body.get("strategy_skill_id")),
        title=title,
        source_urls=source_urls,
        source_identifiers=source_identifiers,
        source_key=source_key,
        output_filename=output_filename,
        task_metadata=task_metadata,
        department_id=department_id,
        provider_owner_type=provider_owner_type,
    )


def _context(body, default=""):
    return str(body.get("context") or body.get("prompt") or default).strip()


def _execute_task(task, body, web_search=None):
    return AmazonAiService().execute_task(
        task.id,
        _context(body),
        _asset_ids(body),
        web_search=web_search,
    )["content"]


def _api_error(exc):
    if isinstance(exc, AmazonAiModelError):
        current_app.logger.warning(
            "amazon ai request rejected: code=%s error=%s",
            exc.code,
            str(exc),
        )
        return jsonify(success=False, msg=str(exc), code=exc.code), 409
    if isinstance(exc, ValueError):
        current_app.logger.warning(
            "amazon ai request rejected: error=%s",
            str(exc),
        )
        return jsonify(success=False, msg=str(exc)), 400
    current_app.logger.exception("amazon ai request failed")
    return jsonify(success=False, msg=str(exc)), 400


def _task_asset_ids(task):
    ids = []

    def add(value):
        value = _int_or_none(value)
        if value and value not in ids:
            ids.append(value)

    for asset in amazon_task_assets(task.id, include_legacy=False):
        add(asset.id)
    add(task.output_asset_id)
    for value in _json(task.input_asset_ids_json, []) or []:
        add(value)
    refs = _task_file_refs(task)
    for group in ("inputs", "results"):
        for item in refs[group]:
            add(_file_ref_asset_id(item))
    input_refs = _json(task.input_refs_json, {}) or {}
    for value in input_refs.get("asset_ids") or []:
        add(value)
    return ids


def _referenced_by_other_task(asset_id, task_id=None):
    # New rows are protected through indexed relation tables. Legacy JSON is
    # still read for the current task's own fallback IDs, but never scanned
    # across every Amazon task.
    return asset_referenced(
        asset_id,
        amazon_task_id=task_id,
        now=None,
    )


def _legacy_storage_refs(task, asset_ids):
    refs = _task_file_refs(task)
    result_refs = _json(task.result_refs_json, {}) or {}
    candidates = []
    seen = set()

    def add(value, checksum=None):
        value = str(value or "").strip()
        if value and value not in seen and FileService.is_managed_url(value):
            seen.add(value)
            candidates.append((value, checksum))

    for group in ("inputs", "results", "legacy_urls"):
        for item in refs[group]:
            if not isinstance(item, dict):
                continue
            if _file_ref_asset_id(item) in asset_ids:
                continue
            add(item.get("public_url") or item.get("url"), item.get("checksum"))
    if _int_or_none(task.output_asset_id) not in asset_ids:
        add(
            task.output_url,
            task.output_checksum or result_refs.get("response_checksum"),
        )
    return candidates


def _delete_amazon_task(task):
    if task.status in ("PENDING", "RUNNING"):
        return {"deleted": False, "message": "执行中的任务不能删除"}
    asset_ids = _task_asset_ids(task)
    assets = (
        StudioAsset.query.filter(StudioAsset.id.in_(asset_ids)).all()
        if asset_ids
        else []
    )
    all_asset_ids = [asset.id for asset in assets]
    assets = [
        asset
        for asset in assets
        if can_access_asset(current_user, asset)
    ]
    permanent_ids = {
        asset.id
        for asset in assets
        if str(asset.retention_policy or "").upper()
        == FileService.PERMANENT
    }
    protected = [
        asset
        for asset in assets
        if asset.id in permanent_ids
        or _referenced_by_other_task(asset.id, task.id)
    ]
    protected_ids = {asset.id for asset in protected}
    deletable = [
        asset
        for asset in assets
        if asset.id not in protected_ids
    ]
    failed = []
    for asset in deletable:
        if asset.status not in ("ACTIVE", "DELETE_FAILED"):
            continue
        try:
            if not FileService.delete_asset(asset):
                failed.append(asset.id)
        except Exception as exc:
            asset.error_message = str(exc)
            failed.append(asset.id)
    legacy_failed = []
    for url, checksum in _legacy_storage_refs(
        task,
        all_asset_ids,
    ):
        try:
            if not FileService.delete_storage(url, checksum=checksum):
                legacy_failed.append(url)
        except Exception:
            legacy_failed.append(url)
    if failed or legacy_failed:
        db.session.commit()
        return {"deleted": False, "message": "GoFastDFS 文件删除失败，请稍后重试"}
    # Remove normalized links explicitly before deleting task/assets to avoid
    # ORM/database cascade double-deletes when collections are loaded.
    AmazonAiTaskAsset.query.filter(
        AmazonAiTaskAsset.task_id == task.id,
    ).delete(synchronize_session=False)
    if "asset_links" in getattr(task, "__dict__", {}):
        db.session.expire(task, ["asset_links"])
    for asset in deletable:
        db.session.delete(asset)
    db.session.delete(task)
    db.session.commit()
    return {"deleted": True, "message": "任务及关联 GoFastDFS 文件已删除"}


def _required_source_map(body, fields, messages):
    result = {}
    for task_type, aliases in fields.items():
        value = next(
            (
                str(body.get(alias) or "").strip()
                for alias in aliases
                if str(body.get(alias) or "").strip()
            ),
            "",
        )
        if value:
            result[task_type] = value
        elif messages.get(task_type):
            raise ValueError(messages[task_type])
    return result


def _listing_source_map(body):
    return _required_source_map(
        body,
        {
            "COMPETITOR_ANALYZE": ("competitor_task_code", "competitor_task_id"),
            "DIFFERENTIATION_GENERATE": (
                "differentiation_task_code",
                "differentiation_task_id",
            ),
            "BASIC_INFO_CORRECT": ("basic_info_task_code", "basic_info_task_id"),
        },
        {},
    )


def _basic_source_map(body):
    result = _required_source_map(
        body,
        {
            "COMPETITOR_ANALYZE": ("competitor_task_code", "competitor_task_id"),
            "DIFFERENTIATION_GENERATE": (
                "differentiation_task_code",
                "differentiation_task_id",
            ),
        },
        {},
    )
    if not result:
        raise ValueError("请选择竞品分析或差异化分析任务")
    return result


def _parse_model_json(content):
    value = _json(content, None)
    if isinstance(value, dict):
        return value
    text = str(content or "")
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        value = _json(text[start : end + 1], None)
        if isinstance(value, dict):
            return value
    return {}


def _heading_block(content, heading):
    match = re.search(
        rf"(?ims)^\s*#+\s*(?:\d+[.)]\s*)?{re.escape(heading)}\s*$"
        rf"(.*?)(?=^\s*#+\s+\S|\Z)",
        str(content or ""),
    )
    return match.group(1).strip() if match else ""


def _parse_listing_output(content):
    parsed = _parse_model_json(content)
    if parsed:
        item_name = str(
            parsed.get("item_name")
            or parsed.get("itemName")
            or parsed.get("title")
            or ""
        ).strip()
        highlights = str(
            parsed.get("item_highlights")
            or parsed.get("itemHighlights")
            or parsed.get("highlights")
            or ""
        ).strip()
        description = str(parsed.get("description") or "").strip()
        qa = parsed.get("qa") or parsed.get("questions_and_answers") or []
    else:
        item_name = _heading_block(content, "Item Name")
        highlights = _heading_block(content, "Item Highlights")
        description = _heading_block(content, "Product Description")
        qa = []
        for match in re.finditer(
            r"(?ims)^\s*###\s*Q\d+\.\s*(.+?)\s*$"
            r"(.*?)(?=^\s*###\s*Q\d+\.|\Z)",
            str(content or ""),
        ):
            answer = re.search(
                r"(?ims)^\s*(?:\*\*A:\*\*|A\s*:)\s*(.*)",
                match.group(2),
            )
            qa.append(
                {
                    "question": match.group(1).strip(),
                    "answer": (
                        answer.group(1).strip()
                        if answer
                        else match.group(2).strip()
                    ),
                }
            )
    if not item_name or not highlights or not description:
        raise ValueError(
            "Listing 输出缺少 Item Name、Item Highlights 或 Product Description"
        )
    if not isinstance(qa, list) or len(qa) != 20:
        raise ValueError(
            "Listing QA 必须正好 20 个，当前识别到 "
            f"{len(qa) if isinstance(qa, list) else 0} 个"
        )
    return {
        "item_name": item_name,
        "item_highlights": highlights,
        "title": item_name,
        "bullet_points": [],
        "description": description,
        "qa": qa,
        "search_terms": str(parsed.get("search_terms") or "").strip() if parsed else "",
        "backend_keywords": str(parsed.get("backend_keywords") or "").strip() if parsed else "",
        "raw": str(content or ""),
        "version_no": 1,
    }


def _generate_listing(body, department_id):
    source_by_type = _listing_source_map(body)
    codes = list(source_by_type.values())
    _validate_source_tasks(
        codes,
        department_id,
        expected_types={
            code: task_type
            for task_type, code in source_by_type.items()
        },
    )
    product_id = _int_or_none(body.get("studio_product_id"))
    assets = _validate_input_assets(_asset_ids(body), department_id)
    context = _context(body)
    skill_id = _int_or_none(body.get("skill_id"))
    if not any((skill_id, source_by_type, product_id, context, assets)):
        raise ValueError(
            "请至少提供一项 Listing 输入：Skill、产品、来源任务、"
            "补充文件或创作要求"
        )
    listing_body = dict(body)
    listing_body["department_id"] = department_id
    listing_body["source_task_codes"] = codes
    listing_body["context"] = (
        "请将以下已完成分析结果与所选产品核心卖点整合成长上下文，"
        "只使用我方产品核心卖点中确认的事实，不要把竞品事实写成我方参数。\n"
        + context
    )
    timestamp = _timestamp_filename()
    task = _create_service_task(
        listing_body,
        "LISTING_GENERATE",
        title=f"Listing创作-{timestamp}",
        output_filename=f"Listing创作-{timestamp}.txt",
        source_task_codes=codes,
        product_id=product_id,
        task_metadata={"source_task_codes": source_by_type},
    )
    content = _execute_task(task, listing_body)
    parsed = _parse_listing_output(content)
    _set_task_result_refs(
        task,
        source_task_codes=source_by_type,
        business_type="listing",
        output_fields=["item_name", "item_highlights", "description", "qa"],
    )
    db.session.commit()
    return {
        "task": _task_dict(task),
        "source_task_codes": source_by_type,
        "version_summary": {
            "item_name": parsed["item_name"],
            "qa_count": len(parsed["qa"]),
        },
    }


@amazon_ai_bp.get("/")
@authorize("amazon_ai:dashboard")
def dashboard():
    return render_template("amazon_ai/dashboard.html")


@amazon_ai_bp.get("/dashboard")
@authorize("amazon_ai:dashboard")
def dashboard_page():
    return render_template("amazon_ai/dashboard.html")


@amazon_ai_bp.get("/history")
@authorize("amazon_ai:history")
def history_page():
    return render_template("amazon_ai/history.html")


@amazon_ai_bp.get("/competitor")
@authorize("amazon_ai:competitor")
def competitor_page():
    return render_template("amazon_ai/competitor.html")


@amazon_ai_bp.get("/keyword")
@authorize("amazon_ai:differentiation")
def keyword_page():
    return render_template("amazon_ai/differentiation.html")


@amazon_ai_bp.get("/review")
@authorize("amazon_ai:basic_info")
def review_page():
    return render_template("amazon_ai/basic_info.html")


@amazon_ai_bp.get("/differentiation")
@authorize("amazon_ai:differentiation")
def differentiation_page():
    return render_template("amazon_ai/differentiation.html")


@amazon_ai_bp.get("/basic-info")
@authorize("amazon_ai:basic_info")
def basic_info_page():
    return render_template("amazon_ai/basic_info.html")


@amazon_ai_bp.get("/listing/create")
@authorize("amazon_ai:listing_create")
def listing_create_page():
    return render_template("amazon_ai/listing_create.html")


@amazon_ai_bp.get("/api/options")
@login_required
def options():
    if not any(
        has_effective_permission(code)
        for code in (
            "amazon_ai:dashboard",
            "amazon_ai:competitor",
            "amazon_ai:differentiation",
            "amazon_ai:basic_info",
            "amazon_ai:listing_create",
        )
    ):
        return jsonify(success=False, msg="权限不足"), 403
    chat_models = (
        _scoped_studio_model_query()
        .filter(
            StudioModel.media_type == "CHAT",
            StudioModel.enabled == 1,
            StudioProvider.enabled == 1,
        )
        .order_by(
            Dept.sort.asc(),
            Dept.id.asc(),
            StudioProvider.name.asc(),
            StudioProvider.id.asc(),
            StudioModel.name.asc(),
            StudioModel.id.asc(),
        )
        .all()
    )
    department_ids = {
        model.provider.dept_id
        for model in chat_models
        if model.provider and model.provider.dept_id
    }
    departments = (
        Dept.query.filter(Dept.id.in_(department_ids)).all()
        if department_ids
        else []
    )
    department_names = {
        department.id: department.dept_name for department in departments
    }
    skills = (
        _scoped_studio_skill_query()
        .filter(
            StudioSkill.enabled == 1,
            StudioSkill.code != PRODUCT_EXTRACTION_SKILL_CODE,
            StudioSkill.media_type.in_(("TEXT", "BOTH")),
        )
        .order_by(StudioSkill.name)
        .all()
    )
    products = (
        _scoped_studio_product_query()
        .filter_by(enabled=1)
        .order_by(StudioProduct.name)
        .all()
    )
    state = global_chat_model_state()
    return jsonify(
        success=True,
        data={
            "global_chat_model": {
                key: value
                for key, value in state.items()
                if key != "has_api_key"
            },
            "chat_models": [
                {
                    "id": model.id,
                    "name": model.name,
                    "model_code": model.model_code,
                    "media_type": model.media_type,
                    "provider_id": model.provider_id,
                    "provider_name": model.provider.name if model.provider else "",
                    "dept_id": model.provider.dept_id if model.provider else None,
                    "dept_name": department_names.get(
                        model.provider.dept_id if model.provider else None,
                        "",
                    ),
                    "enabled": bool(model.enabled),
                }
                for model in chat_models
            ],
            "skills": [
                {
                    "id": skill.id,
                    "name": skill.name,
                    "code": skill.code,
                    "media_type": skill.media_type,
                    "task_type": next(
                        (
                            task_type
                            for task_type, code in TASK_SKILL_CODES.items()
                            if code == skill.code
                        ),
                        "",
                    ),
                    "is_amazon": skill.code in AMAZON_BUILTIN_SKILL_CODES,
                }
                for skill in skills
            ],
            "products": [
                {
                    "id": product.id,
                    "name": product.name,
                    "code": product.code,
                    "has_core_selling_points": bool(
                        str(product.core_selling_points or "").strip()
                    ),
                }
                for product in products
            ],
        },
    )


@amazon_ai_bp.get("/api/dashboard")
@authorize("amazon_ai:dashboard")
def dashboard_api():
    today_start = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    query = _scoped_amazon_task_query()
    grouped = dict(
        query.with_entities(
            AmazonAiTask.task_type,
            func.count(AmazonAiTask.id),
        ).group_by(AmazonAiTask.task_type).all()
    )
    recent = _with_task_loaders(
        query.order_by(desc(AmazonAiTask.created_at), desc(AmazonAiTask.id))
    ).limit(8).all()
    return jsonify(
        success=True,
        data={
            "tasks": query.count(),
            "today_tasks": query.filter(
                AmazonAiTask.created_at >= today_start
            ).count(),
            "running": query.filter_by(status="RUNNING").count(),
            "succeeded": query.filter_by(status="SUCCEEDED").count(),
            "failed": query.filter_by(status="FAILED").count(),
            "task_type_stats": [
                {
                    "task_type": task_type,
                    "title": AMAZON_TASK_TYPE_LABELS[task_type],
                    "count": int(grouped.get(task_type, 0)),
                }
                for task_type in AMAZON_TASK_TYPE_ORDER
            ],
            "recent_tasks": [_task_dict(task) for task in recent],
            "global_chat_model": {
                key: value
                for key, value in global_chat_model_state().items()
                if key != "has_api_key"
            },
        },
    )


def _history_cursor():
    """Read the optional keyset cursor while retaining old page parameters."""

    raw_created_at = str(
        request.args.get("cursor_created_at") or ""
    ).strip()
    raw_id = request.args.get("cursor_id")
    raw_cursor = str(request.args.get("cursor") or "").strip()
    if raw_cursor and (not raw_created_at or raw_id in (None, "")):
        parts = raw_cursor.rsplit("|", 1)
        if len(parts) == 2:
            raw_created_at = raw_created_at or parts[0].strip()
            raw_id = raw_id if raw_id not in (None, "") else parts[1].strip()

    cursor_id = _int_or_none(raw_id)
    if cursor_id is None:
        return None, None
    try:
        cursor_created_at = datetime.fromisoformat(
            raw_created_at.replace("Z", "+00:00")
        )
        if cursor_created_at.tzinfo:
            cursor_created_at = cursor_created_at.replace(tzinfo=None)
    except (TypeError, ValueError):
        return None, None
    return cursor_created_at, cursor_id


def _apply_history_cursor(query, model, cursor_created_at, cursor_id):
    if cursor_created_at is None or cursor_id is None:
        return query
    return query.filter(
        or_(
            model.created_at < cursor_created_at,
            and_(
                model.created_at == cursor_created_at,
                model.id < cursor_id,
            ),
        )
    )


def _next_history_cursor(rows):
    if not rows:
        return None
    last = rows[-1]
    created_at = getattr(last, "created_at", None)
    task_id = getattr(last, "id", None)
    if not created_at or not task_id:
        return None
    return {
        "cursor": f"{created_at.isoformat(sep=' ')}|{task_id}",
        "cursor_created_at": created_at.isoformat(sep=" "),
        "cursor_id": int(task_id),
    }


def _history_page_size(default=20, maximum=100):
    return min(
        maximum,
        max(
            1,
            _int_or_none(request.args.get("page_size")) or default,
        ),
    )


def _tasks_api_response():
    page = max(1, _int_or_none(request.args.get("page")) or 1)
    page_size = min(
        100,
        max(1, _int_or_none(request.args.get("page_size")) or 20),
    )
    query = _scoped_amazon_task_query()
    task_type = str(request.args.get("task_type") or "").strip().upper()
    status = str(request.args.get("status") or "").strip().upper()
    if task_type in AMAZON_TASK_TYPES:
        query = query.filter_by(task_type=task_type)
    if status:
        query = query.filter_by(status=status)
    cursor_created_at, cursor_id = _history_cursor()
    ordered_query = query.order_by(
        desc(AmazonAiTask.created_at),
        desc(AmazonAiTask.id),
    )
    if cursor_created_at is not None and cursor_id is not None:
        rows = (
            _with_task_loaders(
                _apply_history_cursor(
                    query,
                    AmazonAiTask,
                    cursor_created_at,
                    cursor_id,
                ).order_by(
                    desc(AmazonAiTask.created_at),
                    desc(AmazonAiTask.id),
                )
            )
            .limit(page_size + 1)
            .all()
        )
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        next_cursor = _next_history_cursor(rows)
        return jsonify(
            success=True,
            data=[_task_dict(task) for task in rows],
            meta={
                "page": page,
                "page_size": page_size,
                "total": None,
                "has_more": has_more,
                "next_cursor": next_cursor if has_more else None,
            },
        )

    pagination = _with_task_loaders(ordered_query).paginate(
        page=page,
        per_page=page_size,
        error_out=False,
    )
    return jsonify(
        success=True,
        data=[_task_dict(task) for task in pagination.items],
        meta={
            "page": page,
            "page_size": page_size,
            "total": pagination.total,
            "has_more": pagination.has_next,
            "next_cursor": (
                _next_history_cursor(pagination.items)
                if pagination.has_next
                else None
            ),
        },
    )


@amazon_ai_bp.get("/api/tasks")
@authorize("amazon_ai:dashboard")
def tasks_api():
    return _tasks_api_response()


@amazon_ai_bp.get("/api/history")
@authorize("amazon_ai:history")
def history_api():
    return _tasks_api_response()


@amazon_ai_bp.get("/api/tasks/<task_ref>")
@authorize("amazon_ai:dashboard")
def task_api(task_ref):
    task = _scoped_task_by_ref(task_ref)
    if not task:
        return jsonify(success=False, msg="Amazon AI 任务不存在"), 404
    return jsonify(success=True, data=_task_dict(task))


@amazon_ai_bp.get("/api/tasks/<task_ref>/result")
@authorize("amazon_ai:history")
def task_result_api(task_ref):
    task = _scoped_task_by_ref(task_ref)
    if not task:
        return jsonify(success=False, msg="Amazon AI 任务不存在"), 404
    if task.status != "SUCCEEDED":
        return jsonify(success=False, msg="任务尚未成功完成"), 409
    return jsonify(success=True, data=_task_dict(task, include_result=True))


@amazon_ai_bp.get("/api/result-tasks")
@authorize("amazon_ai:listing_create")
def result_tasks_api():
    allowed = (
        "COMPETITOR_ANALYZE",
        "DIFFERENTIATION_GENERATE",
        "BASIC_INFO_CORRECT",
    )
    task_type = str(request.args.get("task_type") or "").strip().upper()
    query = _scoped_amazon_task_query().filter(
        AmazonAiTask.status == "SUCCEEDED",
        (
            AmazonAiTask.task_type == task_type
            if task_type in allowed
            else AmazonAiTask.task_type.in_(allowed)
        ),
    )
    rows = _with_task_loaders(
        query.order_by(
            desc(AmazonAiTask.finished_at),
            desc(AmazonAiTask.id),
        )
    ).limit(300).all()
    return jsonify(
        success=True,
        data=[
            {
                "id": task.id,
                "task_number": task.id,
                "task_code": task.task_code,
                "display_id": _task_display_id(task),
                "title": _task_title(task),
                "task_type": task.task_type,
                "task_type_label": AMAZON_TASK_TYPE_LABELS.get(
                    task.task_type,
                    task.task_type,
                ),
                "skill_name": task.skill.name if task.skill else "",
                "finished_at": _date_text(task.finished_at),
                "response_filename": _task_response_filename(task),
                "response_download_url": _task_result_storage(
                    task,
                    user=current_user,
                )[0],
            }
            for task in rows
        ],
    )


@amazon_ai_bp.post("/api/tasks")
@authorize("amazon_ai:dashboard")
def create_task_api():
    body = _body()
    task_type = str(body.get("task_type") or "").upper()
    if task_type in AMAZON_TASK_TYPES and not _has_task_permission(task_type):
        return jsonify(success=False, msg="没有该 Amazon AI 任务类型的权限"), 403
    try:
        task = _create_service_task(
            body,
            task_type,
        )
        return jsonify(
            success=True,
            msg="Amazon AI 任务已创建",
            data=_task_dict(task),
        )
    except Exception as exc:
        db.session.rollback()
        return _api_error(exc)


@amazon_ai_bp.post("/api/tasks/<task_ref>/run")
@authorize("amazon_ai:dashboard")
def run_task_api(task_ref):
    task = _scoped_task_by_ref(task_ref)
    if not task:
        return jsonify(success=False, msg="Amazon AI 任务不存在"), 404
    if not _has_task_permission(task.task_type):
        return jsonify(success=False, msg="没有执行该 Amazon AI 任务的权限"), 403
    try:
        content = _execute_task(task, _body())
        task = _scoped_task_by_ref(task.id) or task
        return jsonify(
            success=True,
            msg="Amazon AI 任务执行完成",
            data={
                "task": _task_dict(task),
            },
        )
    except Exception as exc:
        return _api_error(exc)


@amazon_ai_bp.post("/api/tasks/<task_ref>/cancel")
@authorize("amazon_ai:dashboard")
def cancel_task_api(task_ref):
    task = _locked_task_by_ref(task_ref)
    if not task:
        return jsonify(success=False, msg="Amazon AI 任务不存在"), 404
    if not _has_task_permission(task.task_type):
        return jsonify(success=False, msg="没有取消该 Amazon AI 任务的权限"), 403
    if task.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
        db.session.rollback()
        return jsonify(success=False, msg="当前任务状态不可取消"), 400
    now = datetime.now()
    task.status = "CANCELLED"
    task.finished_at = now
    task.error_code = "CANCELLED_BY_USER"
    task.error_message = "任务由用户取消"
    _mark_terminal(task, now)
    db.session.commit()
    # Re-query after the commit so the response reflects the winning
    # transition rather than a possibly stale ORM snapshot.
    current = _scoped_task_by_ref(task.id)
    return jsonify(
        success=True,
        msg="任务已取消",
        data=_task_dict(current or task),
    )


@amazon_ai_bp.delete("/api/tasks/<task_ref>")
@login_required
def delete_task_api(task_ref):
    task = _scoped_task_by_ref(task_ref)
    if not task:
        return jsonify(success=False, msg="Amazon AI 任务不存在"), 404
    if not _has_task_permission(task.task_type, include_history=True):
        return jsonify(success=False, msg="权限不足"), 403
    try:
        result = _delete_amazon_task(task)
    except Exception as exc:
        db.session.rollback()
        return jsonify(success=False, msg=str(exc)), 400
    if not result["deleted"]:
        return jsonify(success=False, msg=result["message"]), 400
    return jsonify(success=True, msg=result["message"])


@amazon_ai_bp.post("/api/tasks/batch-delete")
@login_required
def batch_delete_tasks_api():
    body = _body()
    raw_ids = body.get("task_ids", body.get("ids", []))
    raw_codes = body.get("task_codes", body.get("codes", []))
    if isinstance(raw_ids, str):
        raw_ids = _json(raw_ids, raw_ids.split(","))
    if isinstance(raw_codes, str):
        raw_codes = _json(raw_codes, raw_codes.split(","))
    raw_ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
    raw_codes = raw_codes if isinstance(raw_codes, list) else [raw_codes]
    ids = list(
        dict.fromkeys(
            value
            for value in (_int_or_none(item) for item in raw_ids)
            if value
        )
    )
    codes = list(
        dict.fromkeys(
            str(item).strip() for item in raw_codes if str(item).strip()
        )
    )
    if not ids and not codes:
        return jsonify(success=False, msg="请选择要删除的任务"), 400
    filters = []
    if ids:
        filters.append(AmazonAiTask.id.in_(ids))
    if codes:
        filters.append(AmazonAiTask.task_code.in_(codes))
    tasks = _scoped_amazon_task_query().filter(or_(*filters)).all()
    deleted, failed = [], []
    for task in tasks:
        if not _has_task_permission(task.task_type, include_history=True):
            failed.append({"id": task.id, "message": "权限不足"})
            continue
        try:
            result = _delete_amazon_task(task)
        except Exception as exc:
            db.session.rollback()
            result = {"deleted": False, "message": str(exc)}
        if result.get("deleted"):
            deleted.append({"id": task.id, "task_code": task.task_code})
        else:
            failed.append(
                {
                    "id": task.id,
                    "task_code": task.task_code,
                    "message": result.get("message") or "删除失败",
                }
            )
    if failed:
        return jsonify(
            success=False,
            msg=f"已删除 {len(deleted)} 条，{len(failed)} 条失败",
            data={"deleted": deleted, "failed": failed},
        ), 400
    return jsonify(
        success=True,
        msg=f"已删除 {len(deleted)} 条任务及其关联文件",
        data={"deleted": deleted, "failed": []},
    )


def _upload_input_file_response():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(success=False, msg="请选择支持的输入文件"), 400
    extension = (
        "." + file.filename.rsplit(".", 1)[-1].lower()
        if "." in file.filename
        else ""
    )
    if extension not in SUPPORTED_EXTENSIONS:
        return jsonify(success=False, msg="文件格式不受支持"), 400
    maximum_size = _amazon_upload_max_bytes()
    actual_size = _file_storage_size(file)
    if actual_size is not None and actual_size > maximum_size:
        return jsonify(
            success=False,
            msg=(
                f"文件“{file.filename}”大小为 {_format_file_size(actual_size)}，"
                f"超过单个文件最大限制 {_format_file_size(maximum_size)}，"
                "文件未上传"
            ),
            code="AMAZON_INPUT_FILE_TOO_LARGE",
            data={
                "filename": file.filename,
                "file_size": actual_size,
                "max_file_size": maximum_size,
            },
        ), 413
    asset = None
    committed = False
    try:
        asset = FileService.upload_file(
            file,
            asset_type="FILE",
            purpose="AMAZON_INPUT",
            retention_policy=FileService.TTL_7D,
            created_by=current_user.id,
            dept_id=_request_department_id(request.form.to_dict()),
        )
        db.session.add(asset)
        db.session.flush()
        db.session.commit()
        committed = True
        return jsonify(
            success=True,
            msg="输入文件上传成功",
            data=_asset_dict(asset),
        )
    except Exception as exc:
        db.session.rollback()
        if not committed and asset is not None:
            try:
                FileService.delete_storage(
                    asset.storage_path,
                    checksum=asset.checksum,
                )
            except Exception:
                current_app.logger.exception(
                    "amazon input storage rollback failed"
                )
        return _api_error(exc)


def _delete_input_file_result(asset_id):
    """Delete one uncommitted Amazon input asset through FileService."""

    asset = StudioAsset.query.filter_by(id=asset_id).first()
    if not asset or str(asset.purpose or "").upper() != "AMAZON_INPUT":
        return {
            "success": False,
            "status_code": 404,
            "msg": "输入文件不存在或用途不正确",
            "asset_id": asset_id,
        }
    if not can_access_asset(current_user, asset):
        return {
            "success": False,
            "status_code": 403,
            "msg": "无权删除该输入文件",
            "asset_id": asset.id,
        }
    if asset.status == "DELETED":
        return {
            "success": True,
            "status_code": 200,
            "msg": "输入文件已删除",
            "asset_id": asset.id,
            "filename": asset.original_filename or "",
            "status": asset.status,
        }
    if asset.status not in ("ACTIVE", "DELETE_FAILED"):
        return {
            "success": False,
            "status_code": 400,
            "msg": "当前输入文件状态不允许删除",
            "asset_id": asset.id,
            "status": asset.status,
        }
    if _referenced_by_other_task(asset.id):
        return {
            "success": False,
            "status_code": 409,
            "msg": "该输入文件已被 Amazon AI 任务引用，不能删除",
            "asset_id": asset.id,
            "status": asset.status,
        }

    try:
        if not FileService.delete_asset(asset):
            db.session.commit()
            return {
                "success": False,
                "status_code": 502,
                "msg": "GoFastDFS 文件删除失败，请稍后重试",
                "asset_id": asset.id,
                "status": asset.status,
            }
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "amazon input asset delete failed: asset_id=%s",
            asset_id,
        )
        return {
            "success": False,
            "status_code": 400,
            "msg": str(exc),
            "asset_id": asset_id,
        }
    return {
        "success": True,
        "status_code": 200,
        "msg": "输入文件及其 GoFastDFS 文件已删除",
        "asset_id": asset.id,
        "filename": asset.original_filename or "",
        "status": asset.status,
    }


def _delete_input_file_response(asset_id):
    result = _delete_input_file_result(asset_id)
    payload = {
        key: value
        for key, value in result.items()
        if key not in {"status_code", "success"}
    }
    return jsonify(
        success=result["success"],
        msg=result["msg"],
        data=payload,
    ), result["status_code"]


def _cleanup_input_files_response():
    body = _body()
    raw_ids = body.get(
        "asset_ids",
        body.get("input_asset_ids", body.get("file_ids", [])),
    )
    if isinstance(raw_ids, str):
        parsed = _json(raw_ids, None)
        raw_ids = parsed if isinstance(parsed, list) else raw_ids.split(",")
    raw_ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
    asset_ids = list(
        dict.fromkeys(
            value
            for value in (_int_or_none(item) for item in raw_ids)
            if value
        )
    )
    if not asset_ids:
        return jsonify(
            success=True,
            msg="没有需要清理的上传文件",
            data={"results": [], "retry_asset_ids": []},
        )

    results = []
    retry_asset_ids = []
    for asset_id in asset_ids:
        result = _delete_input_file_result(asset_id)
        results.append(
            {
                key: value
                for key, value in result.items()
                if key not in {"status_code", "success"}
            }
            | {"success": result["success"]},
        )
        if result["status_code"] >= 500:
            retry_asset_ids.append(asset_id)
    return jsonify(
        success=True,
        msg=(
            "上传草稿文件清理完成"
            if not retry_asset_ids
            else "部分文件清理失败，将在下次进入页面时重试"
        ),
        data={
            "results": results,
            "retry_asset_ids": retry_asset_ids,
        },
    )


@amazon_ai_bp.post("/api/input-files")
@authorize("amazon_ai:dashboard")
def upload_input_file():
    return _upload_input_file_response()


@amazon_ai_bp.post("/api/input-files/cleanup")
@authorize("amazon_ai:dashboard")
def cleanup_input_files():
    return _cleanup_input_files_response()


@amazon_ai_bp.delete("/api/input-files/<int:asset_id>")
@authorize("amazon_ai:dashboard")
def delete_input_file(asset_id):
    return _delete_input_file_response(asset_id)


@amazon_ai_bp.post("/api/competitors/input-files")
@authorize("amazon_ai:competitor")
def upload_competitor_input_file():
    return _upload_input_file_response()


@amazon_ai_bp.post("/api/competitors/input-files/cleanup")
@authorize("amazon_ai:competitor")
def cleanup_competitor_input_files():
    return _cleanup_input_files_response()


@amazon_ai_bp.delete("/api/competitors/input-files/<int:asset_id>")
@authorize("amazon_ai:competitor")
def delete_competitor_input_file(asset_id):
    return _delete_input_file_response(asset_id)


@amazon_ai_bp.post("/api/keywords/input-files")
@authorize("amazon_ai:differentiation")
def upload_keyword_input_file():
    return _upload_input_file_response()


@amazon_ai_bp.post("/api/keywords/input-files/cleanup")
@authorize("amazon_ai:differentiation")
def cleanup_keyword_input_files():
    return _cleanup_input_files_response()


@amazon_ai_bp.delete("/api/keywords/input-files/<int:asset_id>")
@authorize("amazon_ai:differentiation")
def delete_keyword_input_file(asset_id):
    return _delete_input_file_response(asset_id)


@amazon_ai_bp.post("/api/differentiation/input-files")
@authorize("amazon_ai:differentiation")
def upload_differentiation_input_file():
    return _upload_input_file_response()


@amazon_ai_bp.post("/api/differentiation/input-files/cleanup")
@authorize("amazon_ai:differentiation")
def cleanup_differentiation_input_files():
    return _cleanup_input_files_response()


@amazon_ai_bp.delete("/api/differentiation/input-files/<int:asset_id>")
@authorize("amazon_ai:differentiation")
def delete_differentiation_input_file(asset_id):
    return _delete_input_file_response(asset_id)


@amazon_ai_bp.post("/api/reviews/input-files")
@authorize("amazon_ai:basic_info")
def upload_review_input_file():
    return _upload_input_file_response()


@amazon_ai_bp.post("/api/reviews/input-files/cleanup")
@authorize("amazon_ai:basic_info")
def cleanup_review_input_files():
    return _cleanup_input_files_response()


@amazon_ai_bp.delete("/api/reviews/input-files/<int:asset_id>")
@authorize("amazon_ai:basic_info")
def delete_review_input_file(asset_id):
    return _delete_input_file_response(asset_id)


@amazon_ai_bp.post("/api/listing/input-files")
@authorize("amazon_ai:listing_create")
def upload_listing_input_file():
    return _upload_input_file_response()


@amazon_ai_bp.post("/api/listing/input-files/cleanup")
@authorize("amazon_ai:listing_create")
def cleanup_listing_input_files():
    return _cleanup_input_files_response()


@amazon_ai_bp.delete("/api/listing/input-files/<int:asset_id>")
@authorize("amazon_ai:listing_create")
def delete_listing_input_file(asset_id):
    return _delete_input_file_response(asset_id)


def _history_for(task_type):
    query = _scoped_amazon_task_query().filter_by(
        task_type=task_type
    )
    cursor_created_at, cursor_id = _history_cursor()
    if cursor_created_at is not None and cursor_id is not None:
        page_size = _history_page_size()
        rows = (
            _with_task_loaders(
                _apply_history_cursor(
                    query,
                    AmazonAiTask,
                    cursor_created_at,
                    cursor_id,
                ).order_by(
                    desc(AmazonAiTask.created_at),
                    desc(AmazonAiTask.id),
                )
            )
            .limit(page_size + 1)
            .all()
        )
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        return jsonify(
            success=True,
            data=[_task_dict(row) for row in rows],
            meta={
                "page_size": page_size,
                "has_more": has_more,
                "next_cursor": _next_history_cursor(rows)
                if has_more
                else None,
            },
        )

    rows = _with_task_loaders(query.order_by(
        desc(AmazonAiTask.created_at),
        desc(AmazonAiTask.id),
    )).limit(300).all()
    return jsonify(success=True, data=[_task_dict(row) for row in rows])


@amazon_ai_bp.get("/api/competitors")
@authorize("amazon_ai:competitor")
def competitors_api():
    return _history_for("COMPETITOR_ANALYZE")


@amazon_ai_bp.get("/api/competitors/history")
@authorize("amazon_ai:competitor")
def competitor_history_api():
    return _history_for("COMPETITOR_ANALYZE")


@amazon_ai_bp.get("/api/competitors/history/<task_ref>/result")
@authorize("amazon_ai:competitor")
def competitor_history_result_api(task_ref):
    task = _scoped_task_by_ref(task_ref, task_type="COMPETITOR_ANALYZE")
    if not task:
        return jsonify(success=False, msg="竞品分析历史不存在"), 404
    return jsonify(success=True, data=_task_dict(task, include_result=True))


@amazon_ai_bp.get("/api/differentiation/history")
@authorize("amazon_ai:differentiation")
def differentiation_history_api():
    return _history_for("DIFFERENTIATION_GENERATE")


@amazon_ai_bp.get("/api/differentiation/history/<task_ref>/result")
@authorize("amazon_ai:differentiation")
def differentiation_history_result_api(task_ref):
    task = _scoped_task_by_ref(task_ref, task_type="DIFFERENTIATION_GENERATE")
    if not task:
        return jsonify(success=False, msg="差异化分析历史不存在"), 404
    return jsonify(success=True, data=_task_dict(task, include_result=True))


@amazon_ai_bp.get("/api/basic-info/history")
@authorize("amazon_ai:basic_info")
def basic_info_history_api():
    return _history_for("BASIC_INFO_CORRECT")


@amazon_ai_bp.get("/api/basic-info/history/<task_ref>/result")
@authorize("amazon_ai:basic_info")
def basic_info_history_result_api(task_ref):
    task = _scoped_task_by_ref(task_ref, task_type="BASIC_INFO_CORRECT")
    if not task:
        return jsonify(success=False, msg="基础信息修正历史不存在"), 404
    return jsonify(success=True, data=_task_dict(task, include_result=True))


@amazon_ai_bp.get("/api/listing/history")
@authorize("amazon_ai:listing_create")
def listing_history_api():
    return _history_for("LISTING_GENERATE")


@amazon_ai_bp.get("/api/listing/history/<task_ref>/result")
@authorize("amazon_ai:listing_create")
def listing_history_result_api(task_ref):
    task = _scoped_task_by_ref(task_ref, task_type="LISTING_GENERATE")
    if not task:
        return jsonify(success=False, msg="Listing 创作历史不存在"), 404
    return jsonify(success=True, data=_task_dict(task, include_result=True))


@amazon_ai_bp.post("/api/competitors/analyze")
@authorize("amazon_ai:competitor")
def analyze_competitor_api():
    body = _body()
    try:
        department_id = _request_department_id(body)
        urls = _split_urls(
            body.get("product_urls")
            or body.get("urls")
            or body.get("product_url")
            or body.get("source_url")
        )
        first_url = urls[0] if urls else ""
        asin = _extract_asin(first_url)
        asset_ids = _asset_ids(body)
        if not first_url and not asset_ids:
            raise ValueError("请提供 Amazon 竞品链接或竞品资料文件")
        if first_url and not asin:
            raise ValueError("无法从第一条 Amazon 链接提取 ASIN")
        title = (
            _next_competitor_title(department_id, asin)
            if asin
            else f"{_timestamp_filename()}-竞品分析"
        )
        context = (
            "请严格按照当前选择的竞品分析 Skill 执行。"
            "本次只分析第一条 Amazon 商品链接，不要分析后续链接：\n"
            + (
                f"Amazon 商品链接：{first_url}\nASIN：{asin}"
                if first_url
                else ""
            )
        )
        task = _create_service_task(
            body,
            "COMPETITOR_ANALYZE",
            title=title,
            source_urls=[first_url] if first_url else [],
            source_identifiers=[asin] if asin else [],
            source_key=asin or None,
            output_filename=normalize_result_filename(title),
            task_metadata={"ignored_url_count": max(0, len(urls) - 1)},
        )
        content = _execute_task(
            task,
            {"context": context, "input_asset_ids": asset_ids},
            web_search=bool(first_url),
        )
        _set_task_result_refs(
            task,
            business_type="competitor",
            source_url=first_url,
            asin=asin,
        )
        db.session.commit()
        return jsonify(
            success=True,
            msg="竞品分析完成",
            data={
                "task": _task_dict(task),
            },
        )
    except Exception as exc:
        db.session.rollback()
        return _api_error(exc)


@amazon_ai_bp.post("/api/differentiation/analyze")
@authorize("amazon_ai:differentiation")
def analyze_differentiation_api():
    body = _body()
    try:
        department_id = _request_department_id(body)
        asset_ids = _asset_ids(body)
        assets = _validate_input_assets(asset_ids, department_id)
        if not assets:
            raise ValueError("请上传西柚、卖家精灵、Helium10 等关键词反查文件")
        base_name = _file_base_name(assets[0]) or _timestamp_filename()
        task = _create_service_task(
            body,
            "DIFFERENTIATION_GENERATE",
            title=base_name,
            source_key=base_name,
            output_filename=normalize_result_filename(base_name),
            task_metadata={
                "input_filenames": [
                    asset.original_filename for asset in assets
                ]
            },
        )
        content = _execute_task(
            task,
            {
                "context": (
                    "当前输入是西柚、卖家精灵、Helium10 或其他工具的"
                    "关键词反查数据。请严格执行当前差异化 Skill。"
                ),
                "input_asset_ids": asset_ids,
            },
        )
        _set_task_result_refs(task, business_type="differentiation")
        db.session.commit()
        return jsonify(
            success=True,
            msg="差异化分析完成",
            data={
                "task": _task_dict(task),
            },
        )
    except Exception as exc:
        db.session.rollback()
        return _api_error(exc)


@amazon_ai_bp.get("/api/basic-info/source-tasks")
@authorize("amazon_ai:basic_info")
def basic_info_source_tasks_api():
    rows = _scoped_amazon_task_query().filter(
        AmazonAiTask.status == "SUCCEEDED",
        AmazonAiTask.task_type.in_(
            ("COMPETITOR_ANALYZE", "DIFFERENTIATION_GENERATE")
        ),
    ).order_by(
        desc(AmazonAiTask.finished_at),
        desc(AmazonAiTask.id),
    ).limit(300).all()
    return jsonify(
        success=True,
        data=[
            {
                "id": row.id,
                "task_code": row.task_code,
                "display_id": _task_display_id(row),
                "title": _task_title(row),
                "task_type": row.task_type,
                "task_type_label": AMAZON_TASK_TYPE_LABELS.get(
                    row.task_type,
                    row.task_type,
                ),
                "skill_name": row.skill.name if row.skill else "",
                "finished_at": _date_text(row.finished_at),
                "response_filename": _task_response_filename(row),
            }
            for row in rows
        ],
    )


@amazon_ai_bp.get("/api/basic-info/source-tasks/<task_ref>/result")
@authorize("amazon_ai:basic_info")
def basic_info_source_task_result_api(task_ref):
    task = _scoped_task_by_ref(task_ref, status="SUCCEEDED")
    if not task or task.task_type not in {
        "COMPETITOR_ANALYZE",
        "DIFFERENTIATION_GENERATE",
    }:
        return jsonify(success=False, msg="可编辑的分析任务不存在"), 404
    return jsonify(success=True, data=_task_dict(task, include_result=True))


@amazon_ai_bp.post("/api/basic-info/save")
@authorize("amazon_ai:basic_info")
def save_basic_info_api():
    body = _body()
    content = str(
        body.get("content")
        or body.get("context")
        or body.get("prompt")
        or ""
    ).strip()
    if not content:
        return jsonify(success=False, msg="请先填写基础信息修正内容"), 400
    try:
        department_id = _request_department_id(body)
        selected_product_id = _int_or_none(body.get("studio_product_id"))
        selected_product_query = _scoped_studio_product_query().filter_by(
            id=selected_product_id,
            enabled=1,
        )
        if selected_product_id and department_id is not None:
            selected_product_query = selected_product_query.filter(
                StudioProduct.dept_id == department_id
            )
        selected_product = (
            selected_product_query.first()
            if selected_product_id
            else None
        )
        if selected_product_id and not selected_product:
            raise ValueError("关联的 Studio 产品不存在或未启用")
        source_by_type = _basic_source_map(body)
        _validate_source_tasks(
            list(source_by_type.values()),
            department_id,
            expected_types={
                code: task_type for task_type, code in source_by_type.items()
            },
        )
        result_filename = normalize_result_filename(
            body.get("result_filename")
            or body.get("file_name")
            or body.get("filename")
        )
        task = _create_service_task(
            {
                **body,
                "department_id": department_id,
                "source_task_codes": list(source_by_type.values()),
                "skill_id": "",
            },
            "BASIC_INFO_CORRECT",
            title=result_filename,
            output_filename=result_filename,
            source_task_codes=list(source_by_type.values()),
            task_metadata={"source_task_codes": source_by_type},
        )
        if selected_product:
            # 基础信息修正保存后，核心卖点按当前编辑内容整段覆盖。
            selected_product.core_selling_points = content
            db.session.add(selected_product)
        task = AmazonAiService().save_manual_result(
            task.id,
            content,
            filename=result_filename,
        )
        _set_task_result_refs(
            task,
            business_type="basic_info",
            source_task_codes=source_by_type,
        )
        db.session.commit()
        return jsonify(
            success=True,
            msg="基础信息修正已保存",
            data={
                "task": _task_dict(task),
                "source_task_codes": source_by_type,
                "core_selling_points_product_id": (
                    selected_product.id if selected_product else None
                ),
            },
        )
    except Exception as exc:
        db.session.rollback()
        return _api_error(exc)


@amazon_ai_bp.get("/api/keywords")
@authorize("amazon_ai:keyword")
def keywords_api():
    return _history_for("DIFFERENTIATION_GENERATE")


@amazon_ai_bp.post("/api/keywords/analyze")
@authorize("amazon_ai:keyword")
def analyze_keyword_api():
    return analyze_differentiation_api()


@amazon_ai_bp.get("/api/reviews")
@authorize("amazon_ai:review")
def reviews_api():
    return _history_for("DIFFERENTIATION_GENERATE")


@amazon_ai_bp.post("/api/reviews/analyze")
@authorize("amazon_ai:review")
def analyze_review_api():
    return analyze_differentiation_api()


@amazon_ai_bp.get("/api/listing-projects")
@authorize("amazon_ai:listing_create")
def listing_projects_api():
    return jsonify(success=True, data=[])


@amazon_ai_bp.post("/api/listing-projects")
@authorize("amazon_ai:listing_create")
def create_listing_project_api():
    return jsonify(
        success=False,
        msg="Listing 项目已取消，请直接使用 Listing 创作",
    ), 410


@amazon_ai_bp.post("/api/listing/generate")
@authorize("amazon_ai:listing_create")
def generate_standalone_listing_api():
    body = _body()
    try:
        department_id = _request_department_id(body)
        return jsonify(
            success=True,
            msg="Listing 创作完成",
            data=_generate_listing(body, department_id),
        )
    except Exception as exc:
        db.session.rollback()
        return _api_error(exc)


@amazon_ai_bp.get("/api/listing-projects/<int:project_id>")
@amazon_ai_bp.get("/api/listing-projects/<int:project_id>/versions")
@amazon_ai_bp.get("/api/listing-versions/<int:version_id>")
@amazon_ai_bp.get("/api/listing-versions/<int:version_id>/audits")
@amazon_ai_bp.post("/api/listing-projects/<int:project_id>/generate")
@amazon_ai_bp.post("/api/listing-versions/<int:version_id>/audit")
@authorize("amazon_ai:listing_create")
def removed_listing_endpoint(**kwargs):
    return jsonify(
        success=False,
        msg="旧 Listing 项目/版本表已移除，请使用统一任务历史",
    ), 410
