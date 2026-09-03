import json
import mimetypes
import os
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from contextlib import contextmanager
from threading import Lock

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    jsonify,
    render_template,
    request,
)
from flask_login import current_user, login_required
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.datastructures import FileStorage

from applications.common.scope import (
    can_access_asset,
    can_access_resource,
    can_access_model,
    can_access_provider,
    can_access_skill,
    can_manage_provider,
    department_in_scope,
    has_effective_permission,
    is_department_admin_user,
    is_super_admin_user,
    managed_department_ids,
    PROVIDER_OWNER_DEPARTMENT,
    provider_owner_type,
    scope_query,
    user_department_id,
)
from applications.common.utils.rights import authorize, is_super_admin
from applications.common.db_session import release_db_connection
from applications.common.execution_context import (
    ModelExecutionContext,
    ProviderExecutionContext,
)
from applications.common.asset_relations import (
    asset_referenced,
    generation_task_asset_links_for_task,
)
from applications.extensions import db
from applications.models import (
    AmazonAiTask,
    Dept,
    StudioAsset,
    StudioBatchPrompt,
    StudioGenerationComment,
    StudioGenerationTask,
    StudioGenerationTaskAsset,
    StudioModel,
    StudioProduct,
    StudioProductAsset,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)
from applications.amazon_ai.service import (
    AmazonAiService,
    read_task_result_text,
)
from applications.amazon_ai.skill_catalog import (
    AMAZON_BUILTIN_SKILL_CODES,
    BATCH_DETAIL_IMAGE_SKILL_CODE,
    DETAIL_IMAGE_SKILL_CODE,
    PRODUCT_EXTRACTION_SKILL_CODE,
)
from applications.common.storage import FileService, StorageError
from applications.common.skill_storage import (
    clear_legacy_skill_body,
    read_skill_text,
    skill_file_url,
)
from applications.studio.generation_service import (
    complete_chat,
    create_generation,
    poll_task,
)
from applications.studio.feedback_skill import (
    FEEDBACK_SKILL_CODE,
    FEEDBACK_SKILL_NAME,
)
from applications.studio.batch_prompt import (
    BATCH_IMAGE_ASPECT_RATIO_OPTIONS,
    BATCH_PROMPT_STYLE_CUSTOM_VALUE,
    BATCH_PROMPT_STYLE_OPTIONS,
    DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
    DEFAULT_BATCH_IMAGE_RESOLUTION,
    MAX_BATCH_PROMPT_COUNT,
    MAX_BATCH_PROMPT_VERSION_BYTES,
    normalize_batch_image_resolution,
    normalize_image_aspect_ratio,
    normalize_prompt_newlines,
    batch_prompt_filename,
    parse_image_batch_versions,
    format_versions,
    normalize_batch_prompt_style,
    parse_batch_prompt_count,
    parse_model_versions,
    parse_version_document,
    version_label,
)
from applications.studio.product_prompt import (
    append_detail_image_output_contract,
    compose_prompt,
    detail_image_output_contract,
    product_identity_planner_contract,
    product_reference_descriptors,
    product_reference_urls,
    reference_instructions,
    split_urls,
    video_reference_instructions,
)
from applications.studio.provider_client import (
    ProviderClient,
    ProviderRequestError,
    extract_chat_content,
    is_responses_path,
    normalize_balance,
    redact_provider_payload,
)
from applications.studio.provider_catalog import (
    KUAIPAO_IMAGE_MODEL_CODE,
    catalog_for_provider,
    catalog_payload,
    model_spec_for,
    provider_catalog_key,
)
from applications.studio.retention import delete_generation_task
from applications.studio.request_builder import (
    build_request_body,
    split_option_tokens,
)
studio_bp = Blueprint("studio", __name__, url_prefix="/studio")
GLOBAL_CHAT_MODEL_SETTING_KEY = "global_chat_model_id"
STUDIO_MAX_FINAL_PROMPT_BYTES = 5000
STUDIO_MAX_PLANNER_CONTEXT_BYTES = 120000
BATCH_IMAGE_MAX_ATTEMPTS = 2
_provider_defaults_lock = Lock()


PRODUCT_UPDATE_FIELDS = (
    "description",
    "core_selling_points",
    "product_profile",
    "product_memory",
    "generation_rules",
    "forbidden_rules",
)

PRODUCT_UPDATE_LABELS = {
    "description": "产品资料",
    "core_selling_points": "核心卖点",
    "product_profile": "Product Profile",
    "product_memory": "产品记忆",
    "generation_rules": "生成规则",
    "forbidden_rules": "禁止修改规则",
}

PRODUCT_INLINE_FIELDS = (
    "name",
    "brand",
    "description",
    "product_profile",
    "core_selling_points",
    "product_memory",
    "generation_rules",
    "forbidden_rules",
)

FEEDBACK_BUILTIN_SKILL_CODES = AMAZON_BUILTIN_SKILL_CODES | {
    FEEDBACK_SKILL_CODE,
}

PRODUCT_EXTRACTION_FIELDS = (
    "name",
    "code",
    "brand",
    "description",
    "product_profile",
    "core_selling_points",
    "product_memory",
    "generation_rules",
    "forbidden_rules",
)

PRODUCT_EXTRACTION_ALIASES = {
    "name": (
        "product_name",
        "productName",
        "产品名称",
    ),
    "code": (
        "product_code",
        "productCode",
        "sku",
        "SKU",
        "model_number",
        "modelNumber",
        "mpn",
        "MPN",
        "产品编码",
    ),
    "brand": (
        "品牌",
    ),
    "description": (
        "product_description",
        "productDescription",
        "产品描述",
        "产品资料",
    ),
    "product_profile": (
        "productProfile",
        "profile",
        "Product Profile",
        "产品档案",
    ),
    "core_selling_points": (
        "coreSellingPoints",
        "selling_points",
        "sellingPoints",
        "core_selling_point",
        "核心卖点",
    ),
    "product_memory": (
        "productMemory",
        "memory",
        "产品记忆",
    ),
    "generation_rules": (
        "generationRules",
        "generation_rule",
        "生成规则",
    ),
    "forbidden_rules": (
        "forbiddenRules",
        "forbidden_rule",
        "禁止修改规则",
    ),
}

PRODUCT_EMPTY_MARKERS = frozenset(
    {
        "",
        "null",
        "none",
        "n/a",
        "na",
        "unknown",
        "not provided",
        "信息缺失",
        "未知",
        "暂无",
        "未提供",
        "未明确",
    }
)

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


def _limit_utf8(value, max_bytes):
    """Keep planner context within the configured byte budget."""

    text = str(value or "")
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = "\n[产品约束上下文已按字节限制截断]"
    suffix_bytes = suffix.encode("utf-8")
    if len(suffix_bytes) > max_bytes:
        return suffix_bytes[:max_bytes].decode("utf-8", errors="ignore")
    available = max(0, max_bytes - len(suffix_bytes))
    return encoded[:available].decode("utf-8", errors="ignore").rstrip() + suffix


def _truncate_utf8(value, max_bytes):
    """Truncate without adding a marker so a hard request budget is respected."""

    text = str(value or "")
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _dump(value):
    """Serialize request/response snapshots consistently for operation logs."""

    return (
        json.dumps(value, ensure_ascii=False, default=str)
        if value is not None
        else None
    )


def _strip_generated_reference_sections(value):
    """Remove reference chapters emitted by the planner before canonical append."""

    text = str(value or "").strip()
    if not text:
        return ""
    markers = (
        "参考素材顺序说明",
        "参考素材顺序与角色约束",
        "参考图必须按以下顺序理解",
        "参考视频必须按以下顺序理解",
    )
    positions = [
        text.find(marker)
        for marker in markers
        if text.find(marker) >= 0
    ]
    if positions:
        text = text[: min(positions)].rstrip()
    return text


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
    """Normalize complete product-field replacements returned by the model."""

    parsed = _parse_json_object(payload)
    source = parsed.get("product_updates")
    if not isinstance(source, dict):
        source = parsed.get("updates")
    if not isinstance(source, dict):
        source = {
            field: parsed.get(field)
            for field in PRODUCT_UPDATE_FIELDS
            if field in parsed
        }
    if not isinstance(source, dict):
        return {
            "analysis": str(parsed.get("analysis") or "").strip(),
            "updates": {},
        }

    aliases = {
        "product_description": "description",
        "productDescription": "description",
        "coreSellingPoints": "core_selling_points",
        "selling_points": "core_selling_points",
        "sellingPoints": "core_selling_points",
        "核心卖点": "core_selling_points",
        "profile": "product_profile",
        "productProfile": "product_profile",
        "memory": "product_memory",
        "productMemory": "product_memory",
        "generation_rule": "generation_rules",
        "generationRules": "generation_rules",
        "forbidden_rule": "forbidden_rules",
        "forbiddenRules": "forbidden_rules",
    }
    updates = {}
    for field in PRODUCT_UPDATE_FIELDS:
        raw = source.get(field)
        if raw is None:
            for alias, canonical in aliases.items():
                if canonical == field and alias in source:
                    raw = source.get(alias)
                    break
        reason = ""
        replace = False
        value = raw
        if isinstance(raw, dict):
            replace = str(raw.get("replace") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            value = raw.get(
                "value",
                raw.get(
                    "full_value",
                    raw.get("suggested", raw.get("content", raw.get("text"))),
                ),
            )
            reason = str(raw.get("reason") or raw.get("why") or "").strip()
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        value = str(value).strip()
        if not value and not replace:
            continue
        updates[field] = {
            "label": PRODUCT_UPDATE_LABELS[field],
            "value": value,
            "reason": reason,
            "replace": replace,
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


def _normalize_extracted_product(payload, listing_task=None):
    """Keep only evidence-backed product fields returned by the extractor."""

    parsed = _parse_json_object(payload)
    if not parsed:
        raise ValueError("产品提取 Skill 返回的内容不是有效 JSON")

    source = parsed.get("product")
    if not isinstance(source, dict):
        source = parsed.get("product_info")
    if not isinstance(source, dict):
        source = parsed

    values = {}
    for field in PRODUCT_EXTRACTION_FIELDS:
        raw = source.get(field)
        if raw is None:
            for alias in PRODUCT_EXTRACTION_ALIASES.get(field, ()):
                if alias in source:
                    raw = source.get(alias)
                    break
        if isinstance(raw, list):
            raw = "\n".join(
                str(item).strip()
                for item in raw
                if str(item).strip()
            )
        elif isinstance(raw, dict):
            raw = json.dumps(raw, ensure_ascii=False, default=str)
        if raw is None:
            values[field] = None
            continue
        text = str(raw).strip()
        if text.lower() in PRODUCT_EMPTY_MARKERS:
            values[field] = None
        else:
            values[field] = text

    # Product identity must never be synthesized from Listing plumbing.
    code = values.get("code")
    if code:
        forbidden_codes = {
            str(getattr(listing_task, "id", "") or "").strip(),
            str(getattr(listing_task, "task_code", "") or "").strip(),
            str(getattr(listing_task, "output_filename", "") or "")
            .rsplit(".", 1)[0]
            .strip(),
        }
        if (
            code in forbidden_codes
            or re.fullmatch(r"[A-Z0-9]{10}", code, flags=re.IGNORECASE)
            or re.search(r"\bASIN\b", code, flags=re.IGNORECASE)
        ):
            values["code"] = None

    return values


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


def _query_department_ids(raw=None):
    """Return department ids visible to the current account for a list query."""

    if raw in (None, ""):
        if is_super_admin_user():
            return None
        return [user_department_id()] if user_department_id() else [-1]
    department_id = _int_or_none(raw)
    if department_id is None:
        return [-1]
    if not Dept.query.filter_by(id=department_id).first():
        return [-1]
    if not is_super_admin_user() and not department_in_scope(
        department_id,
        include_descendants=False,
    ):
        return [-1]
    return [department_id]


def _write_department_id(data, required=True):
    """Resolve a department for a new row or a department-scoped setting."""

    data = data or {}
    raw = data.get("department_id", data.get("dept_id"))
    department_id = _int_or_none(raw) if raw not in (None, "") else None
    if not is_super_admin_user():
        department_id = user_department_id()
    elif department_id is None:
        department_id = user_department_id()
    if department_id is None:
        if required:
            raise ValueError("请先选择部门")
        return None
    if not Dept.query.filter_by(id=department_id).first():
        raise ValueError("部门不存在")
    if not is_super_admin_user() and not department_in_scope(
        department_id,
        include_descendants=False,
    ):
        raise ValueError("无权使用该部门")
    return department_id


def _department_query(query, column, raw=None):
    department_ids = _query_department_ids(raw)
    if department_ids is None:
        return query
    return query.filter(column.in_(department_ids))


def _normalized_owner_type(value):
    del value
    # ``SUPER_ADMIN`` was a legacy virtual provider scope. Every provider is
    # now attached to a real department, including the admin's ``总项目``.
    return PROVIDER_OWNER_DEPARTMENT


def _provider_scope_query(query, raw_department=None, owner_type=None):
    """Apply provider ownership scope after resolving browser selectors."""

    requested_owner = _normalized_owner_type(owner_type)
    query = query.filter(
        StudioProvider.dept_id.isnot(None),
        StudioProvider.owner_type == requested_owner,
    )
    if not is_super_admin_user():
        department_id = user_department_id()
        if department_id is None:
            return query.filter(False)
        if raw_department not in (None, ""):
            requested_department = _int_or_none(raw_department)
            if requested_department != department_id:
                return query.filter(False)
        return query.filter(StudioProvider.dept_id == department_id)

    if raw_department in (None, ""):
        return query
    department_id = _int_or_none(raw_department)
    if department_id is None:
        return query.filter(False)
    return query.filter(StudioProvider.dept_id == department_id)


def _scoped_provider_query(raw=None, owner_type=None):
    if not can_manage_provider():
        return StudioProvider.query.filter(False)
    return _provider_scope_query(
        StudioProvider.query,
        raw_department=raw,
        owner_type=owner_type,
    )


def _scoped_model_query(raw=None, owner_type=None):
    query = StudioModel.query.join(StudioProvider)
    return _provider_scope_query(
        query,
        raw_department=raw,
        owner_type=owner_type,
    )


def _scoped_product_query(raw=None):
    if is_super_admin_user():
        return _department_query(StudioProduct.query, StudioProduct.dept_id, raw)
    if is_department_admin_user():
        return StudioProduct.query.filter(
            StudioProduct.dept_id == user_department_id()
        )
    return scope_query(StudioProduct.query, StudioProduct)


def _scoped_skill_query(raw=None):
    if is_super_admin_user():
        return _department_query(StudioSkill.query, StudioSkill.dept_id, raw)
    if is_department_admin_user():
        return StudioSkill.query.filter(
            or_(
                StudioSkill.dept_id == user_department_id(),
                StudioSkill.code.in_(AMAZON_BUILTIN_SKILL_CODES),
            )
        )
    return StudioSkill.query.filter(
        or_(
            StudioSkill.code.in_(AMAZON_BUILTIN_SKILL_CODES),
            and_(
                StudioSkill.dept_id == user_department_id(),
                StudioSkill.created_by == current_user.id,
            ),
        )
    )


def _scoped_asset_query(raw=None):
    if is_super_admin_user():
        return _department_query(StudioAsset.query, StudioAsset.dept_id, raw)
    if is_department_admin_user():
        return StudioAsset.query.filter(
            StudioAsset.dept_id == user_department_id()
        )
    return scope_query(StudioAsset.query, StudioAsset)


def _scoped_task_query(raw=None):
    if is_super_admin_user():
        return _department_query(
            StudioGenerationTask.query,
            StudioGenerationTask.dept_id,
            raw,
        )
    if is_department_admin_user():
        return StudioGenerationTask.query.filter(
            StudioGenerationTask.dept_id == user_department_id()
        )
    return scope_query(StudioGenerationTask.query, StudioGenerationTask)


def _with_task_loaders(query, include_comments=False):
    options = [
        joinedload(StudioGenerationTask.model).joinedload(
            StudioModel.provider
        ),
        joinedload(StudioGenerationTask.product).selectinload(
            StudioProduct.assets
        ),
        joinedload(StudioGenerationTask.skill),
        selectinload(StudioGenerationTask.asset_links).joinedload(
            StudioGenerationTaskAsset.asset
        ),
    ]
    if include_comments:
        options.append(
            selectinload(StudioGenerationTask.comments).joinedload(
                StudioGenerationComment.model
            )
        )
    return query.options(*options)


def _can_access_department(department_id):
    return bool(
        department_id is not None
        and (
            is_super_admin_user()
            or department_in_scope(department_id, include_descendants=False)
        )
    )


def _department_label(department_id):
    try:
        department_id = int(department_id)
    except (TypeError, ValueError):
        return ""
    if department_id <= 0:
        return ""
    try:
        labels = getattr(g, "_studio_department_labels", None)
    except RuntimeError:
        labels = None
    if labels is None:
        labels = {}
        try:
            g._studio_department_labels = labels
        except RuntimeError:
            pass
    if department_id not in labels:
        labels[department_id] = (
            db.session.query(Dept.dept_name)
            .filter(Dept.id == department_id)
            .scalar()
            or ""
        )
    return labels[department_id]


def _studio_departments():
    query = Dept.query
    if not is_super_admin_user():
        query = query.filter(Dept.id == user_department_id())
    return query.order_by(Dept.sort.asc(), Dept.id.asc()).all()


def _ensure_visible_provider_defaults():
    """Repair the built-in provider/model pair for visible real departments.

    Existing deployments may have been initialized before department-scoped
    providers were introduced.  Keep this repair idempotent and limited to
    departments the current identity may manage.  The short process lock also
    prevents the providers and AI-config requests from creating duplicate
    seed rows when the page loads both endpoints at once.
    """

    departments = _studio_departments()
    if not departments:
        return
    from applications.studio.bootstrap import ensure_default_provider_configs

    with _provider_defaults_lock:
        for department in departments:
            try:
                ensure_default_provider_configs(department.id)
            except Exception:
                db.session.rollback()
                current_app.logger.exception(
                    "provider defaults repair failed: department_id=%s",
                    department.id,
                )


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


def _asset_dict(asset, fallback_filename=None):
    is_active = _asset_is_active(asset)
    public_url = (
        asset.public_url
        if is_active and _is_usable_asset_url(asset.public_url)
        else ""
    )
    original_filename = asset.original_filename or fallback_filename or ""
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "purpose": asset.purpose,
        "retention_policy": asset.retention_policy,
        "retention_days": current_app.config.get("STUDIO_ASSET_TTL_DAYS", 7)
        if asset.retention_policy == "TTL_7D"
        else None,
        "storage_path": asset.storage_path,
        "public_url": public_url,
        "download_url": (
            FileService.download_url(asset, original_filename)
            if public_url
            else ""
        ),
        "original_filename": original_filename,
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
    owner_type = provider_owner_type(provider)
    catalog = catalog_for_provider(provider)
    catalog_codes = {
        spec.code
        for spec in catalog.models()
    }
    provider_models = [
        model
        for model in provider.models
        if catalog.key == "custom"
        or str(getattr(model, "model_code", "") or "").strip()
        in catalog_codes
    ]
    return {
        "id": provider.id,
        "dept_id": provider.dept_id,
        "dept_name": _department_label(provider.dept_id),
        "owner_type": owner_type,
        "owner_label": "部门",
        "name": provider.name,
        "kind": provider.kind,
        "catalog_key": provider_catalog_key(provider),
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
        "models": [_model_dict(model) for model in provider_models],
    }


def _model_dict(model):
    provider = model.provider
    owner_type = provider_owner_type(provider) if provider else None
    catalog_key = provider_catalog_key(provider) if provider else "custom"
    provider_base_url = (
        str(getattr(provider, "base_url", "") or "")
        .strip()
        .rstrip("/")
        .lower()
        if provider
        else ""
    )
    model_group_key = (
        f"builtin:{catalog_key}:{provider_base_url}"
        if provider and catalog_key != "custom"
        else f"provider:{model.provider_id}"
    )
    spec = model_spec_for(
        provider,
        getattr(model, "model_code", ""),
    )
    return {
        "id": model.id,
        "provider_id": model.provider_id,
        "provider_name": provider.name if provider else "",
        "provider_base_url": provider_base_url,
        "model_group_key": model_group_key,
        "dept_id": provider.dept_id if provider else None,
        "dept_name": _department_label(provider.dept_id) if provider else "",
        "owner_type": owner_type,
        "name": model.name,
        "model_code": model.model_code,
        "media_type": model.media_type,
        "generation_path": (
            spec.generation_path
            if spec
            else model.generation_path or ""
        ),
        "result_path": (
            spec.result_path or ""
            if spec
            else model.result_path or ""
        ),
        "parameter_schema": _normalize_parameters(
            spec.parameter_schema()
            if spec
            else model.parameter_schema
        ),
        "capabilities": (
            spec.capability_data()
            if spec
            else _json(model.capabilities, {})
        ),
        "parameter_source": "code" if spec else "legacy",
        "catalog_key": catalog_key,
        "description": spec.description if spec else model.description or "",
        "enabled": bool(model.enabled),
    }


def _product_asset_dict(asset, department_id):
    storage_asset_id = asset.storage_asset_id
    storage_asset = getattr(asset, "storage_asset", None)
    if (
        storage_asset
        and department_id is not None
        and storage_asset.dept_id != department_id
    ):
        storage_asset = None
    storage_asset_allowed = bool(
        storage_asset
        and can_access_asset(current_user, storage_asset)
    )
    if storage_asset:
        available = (
            storage_asset_allowed
            and _asset_is_active(storage_asset)
            and _is_usable_asset_url(storage_asset.public_url)
        )
        public_url = storage_asset.public_url if available else ""
        original_filename = (
            storage_asset.original_filename or asset.name or ""
            if storage_asset_allowed
            else ""
        )
        download_url = (
            FileService.download_url(storage_asset, original_filename)
            if available
            else ""
        )
    elif storage_asset_id:
        # Do not fall back to a legacy URL when its canonical storage row is
        # missing or outside the current user's data scope.
        public_url = ""
        original_filename = ""
        download_url = ""
    else:
        public_url = asset.url or ""
        original_filename = asset.name or ""
        download_url = (
            FileService.download_url(public_url, original_filename)
            if public_url
            else ""
        )
    return {
        "id": asset.id,
        "name": asset.name,
        "original_filename": original_filename,
        "url": public_url,
        "download_url": download_url,
        "asset_type": asset.asset_type,
        "role": asset.role,
        "storage_asset_id": asset.storage_asset_id,
    }


def _product_asset_is_accessible(asset, user=None):
    """Keep product references tied to their canonical stored asset scope."""

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
        and can_access_asset(user or current_user, storage_asset)
    )


def _product_dict(product):
    return {
        "id": product.id,
        "dept_id": product.dept_id,
        "dept_name": _department_label(product.dept_id),
        "code": product.code or "",
        "name": product.name or "",
        "brand": product.brand or "",
        "description": product.description or "",
        "product_profile": product.product_profile or "",
        "core_selling_points": product.core_selling_points or "",
        "product_memory": product.product_memory or "",
        "generation_rules": product.generation_rules or "",
        "forbidden_rules": product.forbidden_rules or "",
        "asset_urls": split_urls(product.asset_urls),
        "assets": [
            _product_asset_dict(asset, product.dept_id)
            for asset in product.assets
            if asset.enabled
        ],
        "enabled": bool(product.enabled),
        "updated_at": product.updated_at.strftime("%Y-%m-%d %H:%M")
        if product.updated_at
        else "",
    }


def _task_dict(task, include_comments=True):
    relation_pairs = generation_task_asset_links_for_task(
        task,
        include_legacy=True,
    )

    def in_scope(asset):
        if not asset:
            return False
        if task.dept_id is not None and asset.dept_id != task.dept_id:
            return False
        return can_access_asset(current_user, asset)

    output_candidates = []
    reference_candidates = []
    seen_output_ids = set()
    seen_reference_ids = set()
    output_roles = {"OUTPUT", "RESULT", "THUMBNAIL"}
    reference_roles = {
        "REFERENCE",
        "REFERENCE_IMAGE",
        "REFERENCE_VIDEO",
        "INPUT",
    }
    for link, asset in relation_pairs:
        if not asset:
            continue
        role = str(getattr(link, "role", "") or "").upper()
        is_output = asset.purpose == "GENERATION_OUTPUT" or (
            role in output_roles
        )
        is_reference = asset.purpose == "GENERATION_REFERENCE" or (
            role in reference_roles
        )
        if is_output and asset.id not in seen_output_ids:
            seen_output_ids.add(asset.id)
            output_candidates.append(asset)
        if is_reference and asset.id not in seen_reference_ids:
            seen_reference_ids.add(asset.id)
            reference_candidates.append(asset)

    has_output_asset_rows = bool(output_candidates)
    output_assets = [
        asset for asset in output_candidates if in_scope(asset)
    ]
    reference_assets = [
        asset for asset in reference_candidates if in_scope(asset)
    ]
    output_expired = bool(output_assets) and not any(
        _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
        for asset in output_assets
    )
    reference_expired = bool(reference_assets) and not any(
        _asset_is_active(asset) for asset in reference_assets
    )
    active_output = next(
        (
            asset
            for asset in output_assets
            if _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
        ),
        None,
    )
    output_url = (
        active_output.public_url
        if active_output
        else (
            task.output_url
            if not has_output_asset_rows
            and _is_usable_asset_url(task.output_url)
            else ""
        )
    )
    output_filename = (
        active_output.original_filename
        if active_output
        else f"{task.task_code}.{('mp4' if task.media_type == 'VIDEO' else 'png')}"
    )
    comments = (
        sorted(
            list(getattr(task, "comments", ()) or ()),
            key=lambda item: (
                item.created_at or datetime.min,
                item.id or 0,
            ),
        )
        if include_comments
        else []
    )
    return {
        "id": task.id,
        "dept_id": task.dept_id,
        "dept_name": _department_label(task.dept_id),
        "task_code": task.task_code,
        "media_type": task.media_type,
        "product_id": task.product_id,
        "product_name": task.product.name if task.product else "",
        "model_id": task.model_id,
        "model_name": task.model.name if task.model else "",
        "skill_id": getattr(task, "skill_id", None),
        "skill_name": str(getattr(task, "skill_name", "") or ""),
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
        "output_url": output_url,
        "output_filename": output_filename,
        "output_download_url": (
            FileService.download_url(active_output)
            if active_output
            else FileService.download_url(output_url, output_filename)
            if output_url
            else ""
        ),
        "output_format": task.output_format or "",
        "output_assets": [
            _asset_dict(
                asset,
                f"{task.task_code}-{index}.{'mp4' if task.media_type == 'VIDEO' else 'png'}",
            )
            for index, asset in enumerate(output_assets, start=1)
        ],
        "reference_assets": [_asset_dict(asset) for asset in reference_assets],
        "comments": [_comment_dict(comment) for comment in comments],
        "output_expired": output_expired,
        "reference_expired": reference_expired,
        "asset_retention_days": current_app.config.get(
            "STUDIO_TEMPORARY_RETENTION_DAYS",
            current_app.config.get("STUDIO_ASSET_TTL_DAYS", 30),
        ),
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
        can_access_resource(current_user, task)
        and (
            _has_permission(required_permission)
            or _has_permission("studio:history")
        )
    )


def _chat_provider_snapshot(provider):
    """Materialize provider settings before releasing the MySQL session."""

    return ProviderExecutionContext(
        name=str(getattr(provider, "name", "") or ""),
        kind=str(getattr(provider, "kind", "") or ""),
        base_url=str(getattr(provider, "base_url", "") or ""),
        api_key=getattr(provider, "api_key", None),
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


def _config_scope(raw_department=None, raw_owner_type=None):
    """Resolve a real department setting scope from trusted identity."""

    del raw_owner_type
    if not is_super_admin_user():
        department_id = user_department_id()
        return PROVIDER_OWNER_DEPARTMENT, department_id

    if raw_department in (None, ""):
        raw_department = user_department_id()
    department_id = _int_or_none(raw_department)
    if department_id is None or not Dept.query.filter_by(id=department_id).first():
        return None, None
    return PROVIDER_OWNER_DEPARTMENT, department_id


def _config_department_id(raw=None):
    """Resolve the department whose language model setting is being edited."""

    _owner_type, department_id = _config_scope(raw)
    return department_id


def _prompt_department_id(data, product_id=None):
    """Resolve prompt-planner scope from an explicit or selected resource."""

    raw = data.get("department_id", data.get("dept_id"))
    if raw not in (None, ""):
        department_id = _config_department_id(raw)
        if department_id is None:
            raise ValueError("部门选择无效")
        return department_id
    if not is_super_admin_user():
        department_id = user_department_id()
        if department_id is None:
            raise ValueError("请先为当前管理员指定管理部门")
        return department_id
    if product_id:
        product = StudioProduct.query.filter_by(id=product_id).first()
        if product:
            return product.dept_id
    skill_id = _int_or_none(data.get("skill_id"))
    if skill_id:
        skill = StudioSkill.query.filter_by(id=skill_id).first()
        if skill:
            return skill.dept_id
    return user_department_id()


def _generation_product(product_id, department_id=None):
    """Resolve a product within the caller's trusted data scope.

    The super administrator can combine any visible product with any visible
    provider model. Department administrators and operators remain limited by
    their normal department/self product scope.
    """

    if not product_id:
        return None
    if is_super_admin_user():
        product = StudioProduct.query.filter_by(
            id=product_id,
            enabled=1,
        ).first()
    else:
        product = (
            _scoped_product_query(department_id)
            .filter_by(id=product_id, enabled=1)
            .first()
        )
    if product and can_access_resource(current_user, product):
        return product
    return None


def _generation_skill(skill_id, department_id=None):
    """Resolve a selected Skill without trusting a browser department id."""

    if not skill_id:
        return None
    if is_super_admin_user():
        skill = StudioSkill.query.filter_by(
            id=skill_id,
            enabled=1,
        ).first()
    else:
        skill = (
            _scoped_skill_query(department_id)
            .filter_by(id=skill_id, enabled=1)
            .first()
        )
    if skill and can_access_skill(
        current_user,
        skill,
        builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
    ):
        return skill
    return None


def _global_chat_models(department_id=None, owner_type=None):
    """Return enabled language models for one department."""

    owner_type, department_id = _config_scope(
        department_id,
        owner_type,
    )
    if owner_type is None:
        return []
    return (
        _scoped_model_query(
            department_id,
            owner_type=owner_type,
        )
        .filter(
            StudioModel.enabled == 1,
            StudioModel.media_type == "CHAT",
            StudioProvider.enabled == 1,
        )
        .order_by(StudioProvider.name.asc(), StudioModel.name.asc())
        .all()
    )


def _global_chat_model(department_id=None, owner_type=None):
    """Resolve the configured planner and feedback model for one department."""

    owner_type, department_id = _config_scope(
        department_id,
        owner_type,
    )
    models = _global_chat_models(department_id, owner_type=owner_type)
    setting = StudioSetting.query.filter_by(
        setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
        dept_id=department_id,
    ).first()
    selected_id = _int_or_none(setting.setting_value) if setting else None
    selected = next((model for model in models if model.id == selected_id), None)
    return selected


def _global_chat_model_payload(model):
    if not model:
        return None
    return {
        "id": model.id,
        "dept_id": model.provider.dept_id if model.provider else None,
        "owner_type": (
            provider_owner_type(model.provider)
            if model.provider
            else None
        ),
        "dept_name": (
            _department_label(model.provider.dept_id)
            if model.provider
            else ""
        ),
        "name": model.name,
        "model_code": model.model_code,
        "provider_id": model.provider_id,
        "provider_name": model.provider.name if model.provider else "",
        "enabled": bool(model.enabled and model.provider and model.provider.enabled),
    }


def _model_capabilities(model):
    """Return trusted capability flags for one planner model."""

    if not model:
        return {}
    spec = model_spec_for(
        getattr(model, "provider", None),
        getattr(model, "model_code", ""),
    )
    if spec:
        return spec.capability_data()
    raw = getattr(model, "capabilities", None)
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _product_usage_web_search_tools(model, product):
    """Enable hosted web search only when the model explicitly supports it."""

    if not product or str(getattr(model, "media_type", "")).upper() != "CHAT":
        return []
    if not _model_capabilities(model).get("supports_web_search"):
        return []
    spec = model_spec_for(
        getattr(model, "provider", None),
        getattr(model, "model_code", ""),
    )
    generation_path = (
        (spec.generation_path if spec else None)
        or getattr(model, "generation_path", None)
        or getattr(getattr(model, "provider", None), "generation_path", None)
        or ""
    )
    if not is_responses_path(generation_path):
        return []
    return [{"type": "web_search"}]


def _product_usage_research_instruction(enabled):
    """Keep usage research separate from product identity facts."""

    if enabled:
        return (
            "产品使用方式联网核验：本次请求已启用 web_search。请先搜索并核验该产品"
            "的官方说明、使用手册或其他可信资料，重点确认真实用途、正确握持/安装方式、"
            "动作方向和适用场景；只把被来源支持的使用方式写入最终 Prompt。"
            "联网结果只能补充使用方法，不能覆盖产品中心图片和资料中的产品名称、品牌、"
            "颜色、结构、比例、标签、Logo、按钮、电池或任何配件；不要把 URL 写入最终 Prompt，"
            "也不要把搜索结果中的其他型号或竞品当成当前产品。"
        )
    return (
        "产品使用方式联网核验：当前选定的全局语言模型没有声明 web_search 能力，"
        "不得声称已经联网核验，也不得猜测握持、安装、用途或动作；只能使用产品中心"
        "图片与资料中明确支持的使用方式。若业务要求联网核验，请先切换到支持 "
        "web_search 的全局语言模型。"
    )


def _has_permission(code):
    return has_effective_permission(code)


def _can_delete_history():
    return is_super_admin()


def _can_manage_skills():
    """Only global and department administrators may change Skill definitions."""

    return is_super_admin_user() or is_department_admin_user()


def _batch_prompt_required_permission(media_type):
    media_type = str(media_type or "").strip().upper()
    return "studio:video" if media_type == "VIDEO" else "studio:image"


def _batch_prompt_permission_response(media_type, require_media=True):
    media_type = str(media_type or "").strip().upper()
    if media_type == "ALL":
        if not _has_permission("studio:batch_prompts"):
            return jsonify(success=False, msg="没有批量创作提示词权限"), 403
        return None
    if media_type not in ("IMAGE", "VIDEO"):
        return jsonify(success=False, msg="不支持的批量提示词类型"), 400
    if not _has_permission("studio:batch_prompts"):
        return jsonify(success=False, msg="没有批量创作提示词权限"), 403
    if (
        require_media
        and not _has_permission(_batch_prompt_required_permission(media_type))
    ):
        return jsonify(success=False, msg="没有当前媒体类型的批量提示词权限"), 403
    return None


def _scoped_batch_prompt_query(media_type=None):
    query = StudioBatchPrompt.query
    if media_type in ("IMAGE", "VIDEO"):
        query = query.filter(StudioBatchPrompt.media_type == media_type)
    return scope_query(query, StudioBatchPrompt)


def _batch_prompt_asset(batch_prompt):
    asset = getattr(batch_prompt, "storage_asset", None)
    if asset is None and getattr(batch_prompt, "storage_asset_id", None):
        asset = StudioAsset.query.filter_by(
            id=batch_prompt.storage_asset_id,
            purpose="BATCH_PROMPT",
        ).first()
    if (
        not asset
        or asset.purpose != "BATCH_PROMPT"
        or not _asset_is_active(asset)
        or not can_access_asset(current_user, asset)
    ):
        return None
    return asset


def _batch_prompt_content(batch_prompt):
    asset = _batch_prompt_asset(batch_prompt)
    if not asset:
        if batch_prompt.status == "SUCCEEDED":
            return "", "批量提示词文件不存在、已过期或无权访问"
        return "", ""
    try:
        return (
            normalize_prompt_newlines(
                FileService.read_text(
                    asset,
                    filename=asset.original_filename,
                    maximum_size=(
                        MAX_BATCH_PROMPT_COUNT
                        * (MAX_BATCH_PROMPT_VERSION_BYTES + 64)
                    ),
                ),
            ),
            "",
        )
    except Exception:
        current_app.logger.exception(
            "batch prompt history file read failed: id=%s asset_id=%s",
            batch_prompt.id,
            asset.id,
        )
        return "", "批量提示词文件读取失败"


def _batch_prompt_version_settings(batch_prompt, content):
    """Expose the parameters parsed from each image version to the UI."""

    if (
        str(getattr(batch_prompt, "media_type", "") or "").upper() != "IMAGE"
        or not str(content or "").strip()
    ):
        return []
    try:
        default_resolution = normalize_batch_image_resolution(
            getattr(batch_prompt, "image_resolution", None),
            default=DEFAULT_BATCH_IMAGE_RESOLUTION,
        )
        default_aspect_ratio = normalize_image_aspect_ratio(
            getattr(batch_prompt, "image_aspect_ratio", None)
            or DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
        )
        versions = parse_image_batch_versions(
            content,
            batch_prompt.version_count,
            default_aspect_ratio=default_aspect_ratio,
            default_resolution=default_resolution,
        )
    except ValueError:
        # The history content and its error are already returned to the
        # caller. Do not make the whole history list fail just because an old
        # document cannot be previewed.
        return []
    return [
        {
            "version": index,
            "label": version_label(index),
            "aspect_ratio": item["aspect_ratio"],
            "resolution": item["resolution"],
            "image_quality": item["resolution"].upper(),
        }
        for index, item in enumerate(versions, start=1)
    ]


def _batch_prompt_dict(batch_prompt, include_content=True):
    content = ""
    content_error = ""
    if include_content:
        content, content_error = _batch_prompt_content(batch_prompt)
    try:
        image_resolution = normalize_batch_image_resolution(
            getattr(batch_prompt, "image_resolution", None),
            default=DEFAULT_BATCH_IMAGE_RESOLUTION,
        )
    except ValueError:
        image_resolution = DEFAULT_BATCH_IMAGE_RESOLUTION
    try:
        image_aspect_ratio = normalize_image_aspect_ratio(
            getattr(batch_prompt, "image_aspect_ratio", None),
        )
    except ValueError:
        image_aspect_ratio = DEFAULT_BATCH_IMAGE_ASPECT_RATIO
    product_name = (
        batch_prompt.product_name_snapshot
        or (
            batch_prompt.product.name
            if getattr(batch_prompt, "product", None)
            else ""
        )
        or ""
    )
    skill_name = (
        batch_prompt.skill_name_snapshot
        or (
            batch_prompt.skill.name
            if getattr(batch_prompt, "skill", None)
            else ""
        )
        or ""
    )
    asset = _batch_prompt_asset(batch_prompt)
    version_settings = _batch_prompt_version_settings(
        batch_prompt,
        content,
    )
    file_name = (
        batch_prompt.file_name
        or (asset.original_filename if asset else "")
        or ""
    )
    return {
        "id": batch_prompt.id,
        "dept_id": batch_prompt.dept_id,
        "dept_name": _department_label(batch_prompt.dept_id),
        "user_id": batch_prompt.user_id,
        "media_type": batch_prompt.media_type,
        "product_id": batch_prompt.product_id,
        "product_name": product_name,
        "skill_id": batch_prompt.skill_id,
        "skill_name": skill_name,
        "creative_prompt": batch_prompt.creative_prompt or "",
        "creative_style": batch_prompt.creative_style or "",
        "image_resolution": (
            image_resolution
            if batch_prompt.media_type == "IMAGE"
            else ""
        ),
        "image_quality": (
            image_resolution.upper()
            if batch_prompt.media_type == "IMAGE"
            else ""
        ),
        "image_aspect_ratio": (
            image_aspect_ratio
            if batch_prompt.media_type == "IMAGE"
            else ""
        ),
        "canvas_ratio": (
            image_aspect_ratio
            if batch_prompt.media_type == "IMAGE"
            else ""
        ),
        "file_name": file_name,
        "run_number": batch_prompt.run_number,
        "version_count": batch_prompt.version_count,
        "planner_model_id": batch_prompt.planner_model_id,
        "planner_model_code": batch_prompt.planner_model_code or "",
        "status": batch_prompt.status,
        "content": content,
        "content_error": content_error,
        "version_settings": version_settings,
        "storage_asset_id": asset.id if asset else None,
        "download_url": (
            FileService.download_url(asset, file_name)
            if asset and _is_usable_asset_url(
                asset.public_url or asset.storage_path
            )
            else ""
        ),
        "error_message": batch_prompt.error_message or "",
        "created_at": (
            batch_prompt.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if batch_prompt.created_at
            else ""
        ),
        "updated_at": (
            batch_prompt.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            if batch_prompt.updated_at
            else ""
        ),
        "completed_at": (
            batch_prompt.completed_at.strftime("%Y-%m-%d %H:%M:%S")
            if batch_prompt.completed_at
            else ""
        ),
    }


@contextmanager
def _temporary_batch_prompt_file(content, filename):
    """Create the requested local TXT name and remove it after the upload."""

    temporary_directory = tempfile.mkdtemp(prefix="studio-batch-prompt-")
    safe_name = str(filename or "batch-prompt.txt").strip()
    safe_name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", safe_name)
    safe_name = safe_name.strip(" .") or "batch-prompt.txt"
    temporary_path = os.path.join(temporary_directory, safe_name)
    try:
        with open(temporary_path, "wb") as temporary:
            temporary.write(str(content).encode("utf-8"))
        yield temporary_path, safe_name
    finally:
        try:
            shutil.rmtree(temporary_directory)
        except OSError:
            current_app.logger.warning(
                "failed to remove temporary batch prompt directory: %s",
                temporary_directory,
            )


def _upload_batch_prompt_text(content, filename, department_id, user_id):
    """Upload a local temporary TXT file and remove it after the upload."""

    with _temporary_batch_prompt_file(content, filename) as (
        temporary_path,
        stored_filename,
    ):
        with open(temporary_path, "rb") as stream:
            file_storage = FileStorage(
                stream=stream,
                filename=stored_filename,
                name="file",
                content_type="text/plain; charset=utf-8",
            )
            return FileService.upload_file(
                file_storage,
                asset_type="FILE",
                purpose="BATCH_PROMPT",
                retention_policy=FileService.PERMANENT,
                created_by=user_id,
                dept_id=department_id,
                record=False,
            )


def _allocate_batch_prompt_file_name(batch_prompt_id, product_id):
    """Reserve a product run number before uploading its history document."""

    batch_prompt = StudioBatchPrompt.query.get(batch_prompt_id)
    if not batch_prompt:
        raise ValueError("批量提示词历史记录不存在")

    product = None
    if product_id:
        product = (
            StudioProduct.query
            .filter_by(id=product_id)
            .with_for_update()
            .first()
        )
    product_name = str(getattr(product, "name", "") or "").strip()
    if product_name:
        latest_run = (
            db.session.query(func.max(StudioBatchPrompt.run_number))
            .filter(
                StudioBatchPrompt.product_id == product.id,
                StudioBatchPrompt.run_number.isnot(None),
            )
            .scalar()
        )
        previous_runs = (
            db.session.query(func.count(StudioBatchPrompt.id))
            .filter(
                StudioBatchPrompt.product_id == product.id,
                StudioBatchPrompt.id != batch_prompt.id,
            )
            .scalar()
        )
        run_number = max(
            int(latest_run or 0),
            int(previous_runs or 0),
        ) + 1
        file_name = batch_prompt_filename(product_name, run_number)
    else:
        run_number = None
        file_name = batch_prompt_filename()

    batch_prompt.file_name = file_name
    batch_prompt.run_number = run_number
    db.session.add(batch_prompt)
    db.session.commit()
    return file_name


def _batch_prompt_department(product, skill):
    """Choose the trusted department that owns the new prompt document."""

    if not is_super_admin_user():
        return user_department_id()
    if product and product.dept_id:
        return product.dept_id
    if skill and skill.dept_id:
        return skill.dept_id
    return user_department_id()


def _batch_prompt_context(
    product,
    skill,
    creative_prompt,
    creative_style,
    media_type,
    count,
    image_aspect_ratio=DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
    image_resolution=DEFAULT_BATCH_IMAGE_RESOLUTION,
    web_search_enabled=False,
):
    """Build one stateless multimodal planner request for batch versions."""

    media_label = "图片" if media_type == "IMAGE" else "视频"
    if media_type == "IMAGE":
        image_aspect_ratio = normalize_image_aspect_ratio(
            image_aspect_ratio,
        )
        image_resolution = normalize_batch_image_resolution(
            image_resolution,
            default=DEFAULT_BATCH_IMAGE_RESOLUTION,
        )
    skill_prompt = (
        read_skill_text(
            skill,
            user=current_user,
            builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
        )
        if skill
        else ""
    )
    descriptors = product_reference_descriptors(
        product,
        media_type=media_type,
        asset_filter=_product_asset_is_accessible,
    )
    context_parts = [
        f"任务：为电商{media_label}创作生成 {count} 个可直接使用的不同版本提示词。",
        "这是一次无会话状态的单次规划请求；请在本次响应中一次性生成全部版本。",
        "每个版本都必须针对同一个产品，不得生成多个不同产品。",
        "信息优先级必须严格遵守：用户本次批量创作要求最高；"
        "产品中心事实、产品图片和禁止修改规则是产品硬约束；"
        "选定 Skill 只能补充未定义的创作细节，不能覆盖用户要求或产品事实。",
        "每个版本需要有真实差异，例如场景、构图、镜头、光线、卖点表达或详情图模块"
        "的组合不同，但不能通过改变产品本体来制造差异。",
        "每个版本不能超过 5000 个 UTF-8 字节，内容完整、简洁，适合直接发送给上游"
        f"{media_label}模型。不得输出版本标题、解释、Markdown 或 JSON 以外的文字。",
    ]
    if product:
        context_parts.append(product_identity_planner_contract())
    if media_type == "IMAGE":
        context_parts.append(
            "图片版本参数规则：本次页面选择的图片质量默认为 "
            f"{image_resolution.upper()}；默认画布比例为 "
            f"{image_aspect_ratio}。"
            "如果用户本次批量创作要求明确写出画布尺寸或比例，"
            "每个版本可以按该明确要求覆盖默认画布比例；"
            "图片质量只有在用户明确要求时才覆盖页面选择值。"
            "每个版本字符串中必须明确包含两行参数标记："
            "“画布比例：<比例>”和“图片质量：<1K/2K/4K>”。"
            "这些标记仅供后端解析，绝不能要求图片模型把比例或质量文字渲染到图片中。"
        )
    if skill_prompt:
        context_parts.append(
            "第一优先输入：选定 Skill 文件原文。请完整读取并执行其中的约束：\n"
            + skill_prompt
        )
    else:
        context_parts.append(
            "第一优先输入：本次没有选择 Skill 文件，不要自行假设不存在的 Skill 规则。"
        )
    if product:
        context_parts.append(
            _product_usage_research_instruction(web_search_enabled)
        )
    context_parts.append(
        "第二优先输入：用户本次批量创作需求（如果为空，则没有额外需求）："
        + (
            creative_prompt
            or "未提供；请根据产品中心资料和选定 Skill 生成专业电商详情图提示词。"
        )
    )
    if creative_style:
        context_parts.append(
            "用户选择的创作风格（只约束视觉表达，不得改变产品本体）："
            + creative_style
        )
    if (
        media_type == "IMAGE"
        and skill
        and skill.code == BATCH_DETAIL_IMAGE_SKILL_CODE
    ):
        context_parts.append(
            "批量详情图 Skill 的默认画面比例是 2.44:1；"
            "本页面已选择的画布比例优先于 Skill 默认值。"
            "只有用户本次批量创作需求明确写出其他系统预设比例时才覆盖页面选择；"
            "没有明确覆盖时，每个版本都必须保留页面选择的比例。"
        )
    if product:
        context_parts.append(
            "第三优先输入：产品中心核心卖点（只能使用其中有依据的内容）："
            + (str(product.core_selling_points or "").strip() or "未提供")
        )
        context_parts.append(
            "第四优先输入：产品中心产品档案（只能使用其中有依据的内容）："
            + (str(product.product_profile or "").strip() or "未提供")
        )
        context_parts.append(
            "第五优先输入：产品中心产品记忆（用于保持长期一致性）："
            + (str(product.product_memory or "").strip() or "未提供")
        )
        for label, value in (
            ("产品名称", product.name),
            ("产品编码", product.code),
            ("品牌", product.brand),
            ("产品资料", product.description),
            ("生成规则", product.generation_rules),
            ("禁止修改规则", product.forbidden_rules),
        ):
            if str(value or "").strip():
                context_parts.append(
                    f"产品中心补充字段 {label}：{str(value).strip()}"
                )
    else:
        context_parts.append(
            "第三至第五优先输入：本次没有关联产品中心，不得虚构产品名称、参数、"
            "产品卖点、产品档案或产品记忆。"
        )
    if descriptors:
        context_parts.append(
            "产品中心图片 URL 与多模态图片：模型必须读取 URL 对应的真实图片，"
            "按顺序核对产品外观；图片中的背景、人物和其他物体不是产品本体：\n"
            + reference_instructions(descriptors, include_urls=True)
        )
    else:
        context_parts.append("本次没有可用的产品中心图片 URL。")

    planner_instruction = (
        "严格只返回合法 JSON，不要代码块。格式必须是："
        '{"versions":["第一版提示词内容","第二版提示词内容"]}。'
        f"versions 数组必须恰好包含 {count} 个字符串；不要返回其他字段。"
        "字符串中不要带“第一版”“第二版”等编号，Python 会自动添加。"
        "每个字符串不能超过 5000 个 UTF-8 字节，且版本之间不能完全重复。"
    )
    if media_type == "IMAGE":
        planner_instruction += (
            "每个字符串必须包含清晰的“画布比例：...”和“图片质量：...”标记，"
            f"没有用户明确覆盖时，画布比例使用页面选择的 {image_aspect_ratio}；"
            "比例必须使用系统预设值，质量只能是 1K、2K 或 4K；"
            "这些参数标记不是图片内文案。"
        )
    context_budget = 120000
    context_text = _limit_utf8(
        "\n".join(context_parts),
        max(0, context_budget - len(planner_instruction.encode("utf-8"))),
    )
    content_blocks = [
        {
            "type": "text",
            "text": context_text + "\n" + planner_instruction,
        }
    ]
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
                "你是电商图片与视频批量提示词规划器。"
                "只输出可执行的提示词 JSON，绝不虚构产品事实；"
                "收到的产品图片是身份核对依据。"
            ),
        },
        {"role": "user", "content": content_blocks},
    ]
    max_tokens = min(
        64000,
        max(2400, count * 900),
    )
    return messages, max_tokens, descriptors


def _mark_batch_prompt_failed(batch_id, message):
    """Keep a failed planner request visible without retaining credentials."""

    try:
        db.session.rollback()
        batch_prompt = StudioBatchPrompt.query.get(batch_id)
        if batch_prompt:
            batch_prompt.status = "FAILED"
            batch_prompt.error_message = str(message or "批量提示词生成失败")
            batch_prompt.completed_at = datetime.now()
            db.session.add(batch_prompt)
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "failed to persist batch prompt failure: id=%s",
            batch_id,
        )


def _skill_management_denied():
    return jsonify(
        success=False,
        msg="只有超级管理员或部门管理员可以修改 Skill",
    ), 403


def _provider_management_denied():
    return jsonify(
        success=False,
        msg="只有超级管理员或部门管理员可以管理模型供应商",
    ), 403


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
        can_batch_process=_has_permission("studio:batch_prompts"),
        is_super_admin=is_super_admin_user(),
    )


@studio_bp.get("/video")
@authorize("studio:video")
def video():
    return render_template(
        "studio/video.html",
        can_delete_history=_can_delete_history(),
        is_super_admin=is_super_admin_user(),
    )


@studio_bp.get("/batch-prompts")
@authorize("studio:batch_prompts")
def batch_prompts():
    return render_template(
        "studio/batch_prompts.html",
        batch_media_type="ALL",
        batch_prompt_style_options=BATCH_PROMPT_STYLE_OPTIONS,
        batch_prompt_aspect_ratio_options=BATCH_IMAGE_ASPECT_RATIO_OPTIONS,
        batch_prompt_default_aspect_ratio=DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
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
    return render_template(
        "studio/skills.html",
        can_manage_skills=_can_manage_skills(),
    )


@studio_bp.get("/forms/skill")
@authorize("studio:skills")
def skill_form():
    if not _can_manage_skills():
        abort(403)
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
    if not can_manage_provider():
        abort(403)
    return render_template(
        "studio/providers.html",
        departments=_studio_departments(),
        current_dept_id=user_department_id(),
        is_super_admin=is_super_admin_user(),
    )


@studio_bp.get("/forms/provider")
@authorize("studio:providers")
def provider_form():
    if not can_manage_provider():
        abort(403)
    return render_template(
        "studio/forms/provider.html",
        departments=_studio_departments(),
        current_dept_id=user_department_id(),
        is_super_admin=is_super_admin_user(),
    )


@studio_bp.get("/forms/model")
@authorize("studio:providers")
def model_form():
    if not can_manage_provider():
        abort(403)
    return render_template("studio/forms/model.html")


@studio_bp.get("/api/dashboard")
@authorize("studio:dashboard")
def dashboard_api():
    task_query = _scoped_task_query()
    total = task_query.count()
    processing = task_query.filter(
        StudioGenerationTask.status.in_(("PENDING", "SUBMITTED", "PROCESSING"))
    ).count()
    succeeded = task_query.filter_by(status="SUCCEEDED").count()
    products = _scoped_product_query().filter_by(enabled=1).count()
    models = (
        _scoped_model_query()
        .filter(StudioModel.enabled == 1, StudioProvider.enabled == 1)
        .count()
    )
    recent = (
        _with_task_loaders(
            task_query.order_by(
                desc(StudioGenerationTask.created_at),
                desc(StudioGenerationTask.id),
            ),
            include_comments=False,
        )
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
        _scoped_model_query()
        .filter(StudioModel.enabled == 1, StudioProvider.enabled == 1)
    )
    if media_type in ("IMAGE", "VIDEO"):
        model_query = model_query.filter(StudioModel.media_type == media_type)
    models = (
        model_query
        .join(Dept, Dept.id == StudioProvider.dept_id)
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
    products_data = (
        _scoped_product_query()
        .filter_by(enabled=1)
        .order_by(StudioProduct.name)
        .all()
    )
    skills = (
        _scoped_skill_query()
        .filter(
            StudioSkill.enabled == 1,
            StudioSkill.code != PRODUCT_EXTRACTION_SKILL_CODE,
        )
        .order_by(StudioSkill.name)
        .all()
    )
    return jsonify(
        success=True,
        data={
            "models": [_model_dict(model) for model in models],
            "products": [
                {
                    "id": product.id,
                    "name": product.name,
                    "code": product.code,
                    "dept_id": product.dept_id,
                    "dept_name": _department_label(product.dept_id),
                }
                for product in products_data
            ],
            "skills": [
                {
                    "id": skill.id,
                    "dept_id": skill.dept_id,
                    "dept_name": _department_label(skill.dept_id),
                    "is_builtin": skill.code in AMAZON_BUILTIN_SKILL_CODES,
                    "name": skill.name,
                    "media_type": skill.media_type,
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

    try:
        department_id = _write_department_id(_body())
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400
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
            dept_id=department_id,
            record=False,
        )
        asset = FileService.create_asset_record(
            stored,
            asset_type=asset_type,
            purpose=purpose,
            retention_policy=retention,
            created_by=current_user.id,
            dept_id=department_id,
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
                "generate_audio": (
                    data.get("generate_audio")
                    if data.get("generate_audio") is not None
                    else False
                ),
                "reference_images": data.get("reference_images"),
                "reference_videos": data.get("reference_videos"),
                "reference_asset_ids": _int_list(data.get("reference_asset_ids")),
                "reference_video_asset_ids": _int_list(
                    data.get("reference_video_asset_ids")
                ),
                "prepared_prompt": data.get("prepared_prompt"),
                "skill_id": _int_or_none(data.get("skill_id")),
                "skill_name": data.get("skill_name"),
                "skill_prompt": data.get("skill_prompt"),
                "extra_fields": _json(data.get("extra_fields"), {}),
                "department_id": _int_or_none(
                    data.get("department_id", data.get("dept_id"))
                ),
            },
        )
        return jsonify(success=True, msg="任务已提交", data=_task_dict(task))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "studio /api/generate failed: user_id=%s media_type=%s "
            "model_id=%s product_id=%s request_keys=%s error=%s",
            current_user.id,
            media_type,
            data.get("model_id"),
            data.get("product_id"),
            sorted(str(key) for key in data.keys()),
            str(exc),
        )
        message = str(exc) or "生成请求失败"
        if isinstance(exc, ProviderRequestError) and exc.status_code:
            message = f"{message}（上游 HTTP {exc.status_code}）"
        return jsonify(success=False, msg=message), 400


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
    try:
        department_id = _prompt_department_id(data, product_id)
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400
    product = _generation_product(product_id, department_id)
    if product_id and not product:
        return jsonify(success=False, msg="关联产品不存在或已停用"), 400

    selected_skill_id = _int_or_none(data.get("skill_id"))
    selected_skill = _generation_skill(selected_skill_id, department_id)
    if selected_skill_id and not selected_skill:
        return jsonify(success=False, msg="Skill 不存在、已停用或不属于当前部门"), 400

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
            StudioAsset.dept_id == department_id,
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
        if not can_access_asset(current_user, asset):
            return jsonify(success=False, msg="不能使用其他用户上传的参考图"), 403
        if not _asset_is_active(asset) or not _is_usable_asset_url(asset.public_url):
            return jsonify(success=False, msg="额外参考图已经失效，请重新上传"), 400

    requested_video_ids = (
        []
        if media_type == "IMAGE"
        else _int_list(data.get("reference_video_asset_ids"))
    )
    reference_videos = (
        StudioAsset.query.filter(
            StudioAsset.id.in_(requested_video_ids),
            StudioAsset.status == "ACTIVE",
            StudioAsset.purpose == "GENERATION_REFERENCE",
            StudioAsset.asset_type == "VIDEO",
            StudioAsset.dept_id == department_id,
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
        if not can_access_asset(current_user, asset):
            return jsonify(success=False, msg="不能使用其他用户上传的参考视频"), 403
        if not _asset_is_active(asset) or not _is_usable_asset_url(asset.public_url):
            return jsonify(success=False, msg="额外参考视频已经失效，请重新上传"), 400

    extra_image_urls = [asset.public_url for asset in reference_assets]
    extra_image_urls.extend(split_urls(data.get("reference_images")))
    extra_video_urls = []
    if media_type == "VIDEO":
        extra_video_urls = [asset.public_url for asset in reference_videos]
        extra_video_urls.extend(split_urls(data.get("reference_videos")))
    try:
        skill_prompt = (
            read_skill_text(
                selected_skill,
                user=current_user,
                builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
            )
            if selected_skill
            else str(data.get("skill_prompt") or "").strip()
        )
    except StorageError as exc:
        return jsonify(success=False, msg=str(exc)), 400
    descriptors = product_reference_descriptors(
        product,
        extra_image_urls,
        media_type=media_type,
        asset_filter=_product_asset_is_accessible,
    )
    planner_reference_parts = [
        reference_instructions(descriptors, include_urls=False),
    ]
    if media_type == "VIDEO":
        planner_reference_parts.append(
            video_reference_instructions(extra_video_urls, include_urls=False)
        )
    planner_reference_context = "\n".join(
        part for part in planner_reference_parts if part
    )
    final_reference_parts = [
        reference_instructions(descriptors, include_urls=True),
    ]
    if media_type == "VIDEO":
        final_reference_parts.append(
            video_reference_instructions(extra_video_urls, include_urls=True)
        )
    ordered_reference_context = "\n".join(
        part for part in final_reference_parts if part
    )
    # The selected Skill id is authoritative. The browser may intentionally
    # omit the file body because the canonical text lives in GoFastDFS.
    planning_required = bool(product or selected_skill or skill_prompt)

    if not planning_required:
        return jsonify(
            success=True,
            msg="未关联产品或 Skill，直接使用创意描述",
            data={
                "final_prompt": _truncate_utf8(
                    creative_prompt,
                    STUDIO_MAX_FINAL_PROMPT_BYTES,
                ),
                "product_name": "",
                "reference_instruction": ordered_reference_context,
                "planner_model": "",
                "planner_model_name": "",
                "references": descriptors,
            },
        )

    chat_model = _global_chat_model(department_id)
    if not chat_model or not chat_model.provider:
        return jsonify(success=False, msg="请先在模型供应商中选择启用的全局语言模型"), 400
    if not can_access_model(
        current_user,
        chat_model,
        department_id=department_id,
    ):
        return jsonify(success=False, msg="无权使用当前全局语言模型"), 403
    if not str(chat_model.provider.api_key or "").strip():
        return jsonify(
            success=False,
            msg="全局语言模型尚未配置 API Key，请先编辑对应供应商",
        ), 400

    planner_tools = _product_usage_web_search_tools(chat_model, product)
    media_label = "图片" if media_type == "IMAGE" else "视频"
    context_parts = [
        f"请为一次电商产品{media_label}生成任务规划最终 Prompt。",
        "提示词优先级必须严格遵守：第一层是用户创意描述，第二层是产品中心信息，第三层是 Skill 兜底。",
        "第一层用户创意描述优先决定场景、天气、动作、构图、镜头、光线和风格；必须准确提取，不得被产品中心或 Skill 改写。",
        "第二层产品中心信息用于确认产品名称并保护产品身份、外形结构、材质、颜色、品牌、关键接口和产品卖点；产品档案、Product Profile、产品记忆、生成规则和禁止修改规则对图片与视频通用。",
        "第三层 Skill 只能补充用户创意和产品中心都没有定义的细节；如果与前两层冲突，Skill 必须让位，不能覆盖用户创意、产品身份或禁止修改规则。",
        "固定产品结构和禁止修改规则属于硬约束；它们不能让产品变成另一种产品，也不能被场景需要随意改造。",
        "若创意涉及螺丝、螺栓、轮毂孔位、接口、插入或拆卸，工具前端必须准确接触并套住真实可见的目标位置；不能指向轮毂中心、中心盖、轮辐空隙或不存在的孔位；必须保持真实孔位数量和布局。",
        "禁止修改规则必须作为约束写入最终 Prompt，而不是被忽略。",
        f"用户创意描述：{creative_prompt}",
    ]
    if product:
        context_parts.append(product_identity_planner_contract())
        context_parts.append(
            _product_usage_research_instruction(bool(planner_tools))
        )
    if product:
        product_context = []
        for label, value in (
            ("关联产品名称", product.name),
            ("产品编码", product.code),
            ("品牌", product.brand),
            ("产品资料", product.description),
            ("核心卖点", product.core_selling_points),
            ("Product Profile", product.product_profile),
            ("产品记忆", product.product_memory),
            ("生成规则", product.generation_rules),
            ("禁止修改规则", product.forbidden_rules),
        ):
            if str(value or "").strip():
                product_context.append(f"{label}：{str(value).strip()}")
        context_parts.extend(product_context)
    if skill_prompt:
        context_parts.append(
            "第三层 Skill 兜底指令（只能补充未定义内容，不能覆盖上面两层）："
            + skill_prompt
        )
    if planner_reference_context:
        context_parts.append(
            "只使用以下实际存在的参考素材。产品中心素材在前，本次上传素材在后；"
            "图片按图片顺序理解，视频只作为动作、镜头和运动参考。"
            "URL 由系统在最终请求中统一补充，final_prompt 不要重复 URL 或参考章节：\n"
            + planner_reference_context
        )
    planner_instruction = (
        "请严格只返回 JSON，不要 Markdown 代码块，结构为："
        '{"final_prompt":"简洁、可直接发送给上游模型的完整中文 Prompt",'
        '"product_name":"识别出的产品名称",'
        '"reference_instruction":""}。'
        "final_prompt 必须按三层优先级组装：用户创意在最前，产品中心约束接在创意后面，Skill 只能作为最后的兜底补充；"
        "用户创意与产品中心在天气、场景、动作或风格上的普通冲突以用户创意为准，产品身份、固定结构和禁止修改规则仍作为硬约束；"
        "不要输出反向提示词，不要输出 URL，不要输出参考素材章节。"
    )
    content_blocks = [
        {
            "type": "text",
            "text": (
                _limit_utf8(
                    "\n".join(context_parts),
                    max(
                        0,
                        STUDIO_MAX_PLANNER_CONTEXT_BYTES
                        - len(planner_instruction.encode("utf-8")),
                    ),
                )
                + planner_instruction
            ),
        }
    ]
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
    if planner_tools:
        body["tools"] = planner_tools
    else:
        body.pop("tools", None)
    provider_snapshot = _chat_provider_snapshot(chat_model.provider)
    chat_spec = model_spec_for(
        getattr(chat_model, "provider", None),
        getattr(chat_model, "model_code", ""),
    )
    model_snapshot = ModelExecutionContext(
        id=getattr(chat_model, "id", None),
        name=str(getattr(chat_model, "name", "") or ""),
        media_type="CHAT",
        model_code=str(getattr(chat_model, "model_code", "") or ""),
        generation_path=(
            (chat_spec.generation_path if chat_spec else None)
            or chat_model.generation_path
            or getattr(chat_model.provider, "generation_path", None)
            or "/v1/chat/completions"
        ),
        result_path=None,
        provider_id=getattr(chat_model, "provider_id", None),
    )
    planner_request_log = json.dumps(
        redact_provider_payload(body),
        ensure_ascii=False,
        default=str,
    )
    current_app.logger.info(
        "studio prompt planner request: media_type=%s product_id=%s "
        "chat_model_id=%s chat_model_code=%s request_body=%s",
        media_type,
        product.id if product else None,
        chat_model.id,
        chat_model.model_code,
        planner_request_log,
    )
    try:
        client = ProviderClient(provider_snapshot)
        release_db_connection()
        response = client.complete(model_snapshot, body)
        content = extract_chat_content(response)
        parsed = _parse_json_object(content)
        final_prompt = str(
            parsed.get("final_prompt")
            or parsed.get("prompt")
            or content
            or ""
        ).strip()
        final_prompt = _strip_generated_reference_sections(final_prompt)
        if not final_prompt:
            raise ValueError("全局语言模型没有返回可用的最终 Prompt")
        # The planner must not own the reference chapter. Build it once from
        # the validated URLs so model verbosity cannot duplicate it.
        reference_instruction = ordered_reference_context
        if reference_instruction:
            reference_header = "\n\n参考素材顺序与角色约束：\n"
            reference_budget = max(
                0,
                STUDIO_MAX_FINAL_PROMPT_BYTES
                - len(reference_header.encode("utf-8")),
            )
            reference_instruction = _truncate_utf8(
                reference_instruction,
                reference_budget,
            )
            reference_suffix = (
                reference_header
                + reference_instruction
            )
            prompt_budget = max(
                0,
                STUDIO_MAX_FINAL_PROMPT_BYTES
                - len(reference_suffix.encode("utf-8")),
            )
            final_prompt = (
                _truncate_utf8(final_prompt, prompt_budget).rstrip()
                + reference_suffix
            )
        else:
            final_prompt = _truncate_utf8(
                final_prompt,
                STUDIO_MAX_FINAL_PROMPT_BYTES,
            )
        current_app.logger.info(
            "studio prompt planner completed: media_type=%s product_id=%s "
            "chat_model_code=%s final_prompt_bytes=%s final_prompt=%s "
            "reference_instruction=%s",
            media_type,
            product.id if product else None,
            chat_model.model_code,
            len(final_prompt.encode("utf-8")),
            final_prompt,
            reference_instruction,
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
                "usage_web_search_enabled": bool(planner_tools),
                "references": descriptors,
            },
        )
    except Exception as exc:
        current_app.logger.exception(
            "studio prompt planner failed: media_type=%s product_id=%s "
            "chat_model_code=%s request_body=%s response_content=%s",
            media_type,
            product.id if product else None,
            chat_model.model_code,
            planner_request_log,
            locals().get("content", ""),
        )
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.post("/api/prompt/prepare")
@login_required
def prepare_image_prompt():
    """Keep the original endpoint while using the global planner implementation."""

    return _prepare_prompt_request()


@studio_bp.get("/api/batch-prompts")
@login_required
def batch_prompts_api():
    """List GoFastDFS-backed batch prompt documents in the caller's scope."""

    media_type = str(request.args.get("media_type") or "ALL").upper()
    permission_error = _batch_prompt_permission_response(media_type)
    if permission_error:
        return permission_error
    page = max(_int_or_none(request.args.get("page")) or 1, 1)
    page_size = min(
        max(_int_or_none(request.args.get("page_size")) or 20, 1),
        50,
    )
    rows = (
        _scoped_batch_prompt_query(media_type)
        .order_by(
            desc(StudioBatchPrompt.created_at),
            desc(StudioBatchPrompt.id),
        )
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
        .all()
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    return jsonify(
        success=True,
        data=[_batch_prompt_dict(row) for row in rows],
        meta={
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        },
    )


@studio_bp.get("/api/batch-prompts/<int:batch_prompt_id>")
@login_required
def batch_prompt_detail_api(batch_prompt_id):
    batch_prompt = _scoped_batch_prompt_query().filter_by(
        id=batch_prompt_id,
    ).first()
    if not batch_prompt:
        return jsonify(success=False, msg="批量提示词历史不存在"), 404
    permission_error = _batch_prompt_permission_response(
        batch_prompt.media_type,
        require_media=False,
    )
    if permission_error:
        return permission_error
    return jsonify(
        success=True,
        data=_batch_prompt_dict(batch_prompt),
    )


@studio_bp.post("/api/batch-prompts")
@login_required
def create_batch_prompt_api():
    """Generate and persist one batch prompt document."""

    data = _body()
    media_type = str(data.get("media_type") or "IMAGE").strip().upper()
    permission_error = _batch_prompt_permission_response(media_type)
    if permission_error:
        return permission_error

    try:
        count = parse_batch_prompt_count(data.get("count"))
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400

    product_id = _int_or_none(data.get("product_id"))
    skill_id = _int_or_none(data.get("skill_id"))
    creative_prompt = str(
        data.get("creative_prompt", data.get("prompt")) or ""
    ).strip()
    submitted_style = str(
        data.get("creative_style", data.get("style")) or ""
    ).strip()
    raw_style = (
        data.get("custom_style")
        if submitted_style == BATCH_PROMPT_STYLE_CUSTOM_VALUE
        else submitted_style
    )
    creative_style = normalize_batch_prompt_style(raw_style)
    if submitted_style == BATCH_PROMPT_STYLE_CUSTOM_VALUE and not creative_style:
        return jsonify(success=False, msg="请输入自定义创作风格"), 400
    image_resolution = ""
    image_aspect_ratio = ""
    if media_type == "IMAGE":
        try:
            image_resolution = normalize_batch_image_resolution(
                data.get(
                    "image_resolution",
                    data.get("image_quality"),
                ),
                default=DEFAULT_BATCH_IMAGE_RESOLUTION,
            )
            image_aspect_ratio = normalize_image_aspect_ratio(
                data.get(
                    "image_aspect_ratio",
                    data.get("aspect_ratio"),
                )
                or DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
            )
        except ValueError as exc:
            return jsonify(success=False, msg=str(exc)), 400
    if not creative_prompt and not product_id and not skill_id:
        return jsonify(
            success=False,
            msg="请至少填写批量创作要求，或选择产品/Skill",
        ), 400

    department_id = user_department_id()
    product = (
        _generation_product(product_id, department_id)
        if product_id
        else None
    )
    if product_id and not product:
        return jsonify(success=False, msg="关联产品不存在、已停用或无权访问"), 400

    skill = (
        _generation_skill(skill_id, department_id)
        if skill_id
        else None
    )
    if skill_id and not skill:
        return jsonify(
            success=False,
            msg="Skill 不存在、已停用或不属于当前可用范围",
        ), 400

    department_id = _batch_prompt_department(product, skill)
    if department_id is None:
        return jsonify(success=False, msg="当前账号没有有效部门归属"), 400

    chat_model = _global_chat_model(department_id)
    if not chat_model or not chat_model.provider:
        return jsonify(
            success=False,
            msg="请先在模型供应商中选择启用的全局语言模型",
        ), 400
    if not can_access_model(
        current_user,
        chat_model,
        department_id=department_id,
    ):
        return jsonify(success=False, msg="无权使用当前全局语言模型"), 403
    if not str(chat_model.provider.api_key or "").strip():
        return jsonify(
            success=False,
            msg="全局语言模型尚未配置 API Key，请先编辑对应供应商",
        ), 400

    planner_tools = _product_usage_web_search_tools(chat_model, product)
    try:
        messages, max_tokens, _descriptors = _batch_prompt_context(
            product,
            skill,
            creative_prompt,
            creative_style,
            media_type,
            count,
            image_aspect_ratio=image_aspect_ratio,
            image_resolution=image_resolution,
            web_search_enabled=bool(planner_tools),
        )
    except (StorageError, ValueError) as exc:
        return jsonify(success=False, msg=str(exc)), 400
    runtime = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    body = build_request_body(chat_model, runtime)
    body.setdefault("model", chat_model.model_code)
    body.setdefault("messages", messages)
    body.setdefault("max_tokens", max_tokens)
    body.setdefault("temperature", 0.2)
    if planner_tools:
        body["tools"] = planner_tools
    else:
        body.pop("tools", None)

    planner_model_id = chat_model.id
    planner_model_code = str(chat_model.model_code or "")
    batch_prompt = StudioBatchPrompt(
        dept_id=department_id,
        user_id=current_user.id,
        media_type=media_type,
        product_id=product.id if product else None,
        skill_id=skill.id if skill else None,
        planner_model_id=planner_model_id,
        planner_model_code=planner_model_code,
        product_name_snapshot=product.name if product else None,
        skill_name_snapshot=skill.name if skill else None,
        # The Skill body is a GoFastDFS file. Keep this legacy column empty
        # for new records; old rows may still use it as a compatibility
        # fallback when no Skill id is available.
        skill_prompt_snapshot=None,
        creative_prompt=creative_prompt or None,
        creative_style=creative_style or None,
        image_aspect_ratio=image_aspect_ratio or None,
        image_resolution=image_resolution or None,
        version_count=count,
        status="PENDING",
    )
    db.session.add(batch_prompt)
    db.session.commit()
    batch_prompt_id = batch_prompt.id

    try:
        current_app.logger.info(
            "studio batch prompt request: id=%s media_type=%s dept_id=%s "
            "user_id=%s product_id=%s skill_id=%s count=%s model_id=%s "
            "model_code=%s request_body=%s",
            batch_prompt_id,
            media_type,
            department_id,
            current_user.id,
            product.id if product else None,
            skill.id if skill else None,
            count,
            planner_model_id,
            planner_model_code,
            _dump(redact_provider_payload(body)),
        )
        response = complete_chat(
            chat_model,
            body,
            department_id=department_id,
            user=current_user,
        )
        content = extract_chat_content(response)
        versions = parse_model_versions(content, count)
        document = format_versions(versions)
    except Exception as exc:
        _mark_batch_prompt_failed(batch_prompt_id, str(exc))
        current_app.logger.exception(
            "studio batch prompt planner failed: id=%s media_type=%s "
            "product_id=%s skill_id=%s count=%s error=%s",
            batch_prompt_id,
            media_type,
            product_id,
            skill_id,
            count,
            str(exc),
        )
        return jsonify(success=False, msg=str(exc)), 400

    stored = None
    try:
        file_name = _allocate_batch_prompt_file_name(
            batch_prompt_id,
            product.id if product else None,
        )
        stored = _upload_batch_prompt_text(
            document,
            file_name,
            department_id,
            current_user.id,
        )
        asset = FileService.create_asset_record(
            stored,
            asset_type="FILE",
            purpose="BATCH_PROMPT",
            retention_policy=FileService.PERMANENT,
            created_by=current_user.id,
            dept_id=department_id,
        )
        db.session.add(asset)
        db.session.flush()
        batch_prompt = StudioBatchPrompt.query.get(batch_prompt_id)
        if not batch_prompt:
            raise ValueError("批量提示词历史记录不存在")
        batch_prompt.storage_asset_id = asset.id
        batch_prompt.status = "SUCCEEDED"
        batch_prompt.error_message = None
        batch_prompt.completed_at = datetime.now()
        db.session.add(batch_prompt)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if stored:
            try:
                FileService.delete_storage(
                    stored.storage_path,
                    checksum=stored.checksum,
                )
            except Exception:
                current_app.logger.exception(
                    "failed to roll back batch prompt upload: id=%s",
                    batch_prompt_id,
                )
        _mark_batch_prompt_failed(batch_prompt_id, str(exc))
        current_app.logger.exception(
            "studio batch prompt persistence failed: id=%s error=%s",
            batch_prompt_id,
            str(exc),
        )
        return jsonify(success=False, msg=str(exc)), 400

    batch_prompt = StudioBatchPrompt.query.get(batch_prompt_id)
    return jsonify(
        success=True,
        msg="批量创作提示词已生成",
        data=_batch_prompt_dict(batch_prompt),
    )


@studio_bp.post("/api/image/batch-process")
@login_required
def process_image_batch_prompt_api():
    """Submit every image prompt version as an independent image task."""

    permission_error = _batch_prompt_permission_response("IMAGE")
    if permission_error:
        return permission_error

    data = _body()
    batch_prompt_id = _int_or_none(
        data.get("batch_prompt_id", data.get("id"))
    )
    model_id = _int_or_none(data.get("model_id"))
    if not batch_prompt_id:
        return jsonify(success=False, msg="请选择批量提示词历史"), 400
    if not model_id:
        return jsonify(success=False, msg="请选择快跑 AI gpt-image2 图片模型"), 400

    batch_prompt = (
        _scoped_batch_prompt_query("IMAGE")
        .filter_by(id=batch_prompt_id)
        .first()
    )
    if not batch_prompt:
        return jsonify(success=False, msg="批量提示词历史不存在或无权访问"), 404
    if batch_prompt.status != "SUCCEEDED":
        return jsonify(success=False, msg="只能处理已完成的批量提示词历史"), 400

    content, content_error = _batch_prompt_content(batch_prompt)
    if content_error or not content:
        return jsonify(
            success=False,
            msg=content_error or "批量提示词文件没有可处理的内容",
        ), 400
    try:
        stored_resolution = normalize_batch_image_resolution(
            getattr(batch_prompt, "image_resolution", None),
            default=DEFAULT_BATCH_IMAGE_RESOLUTION,
        )
        stored_aspect_ratio = normalize_image_aspect_ratio(
            getattr(batch_prompt, "image_aspect_ratio", None)
            or DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
        )
        versions = parse_image_batch_versions(
            content,
            batch_prompt.version_count,
            default_aspect_ratio=stored_aspect_ratio,
            default_resolution=stored_resolution,
        )
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400

    model = (
        _scoped_model_query()
        .filter(
            StudioModel.id == model_id,
            StudioModel.enabled == 1,
            StudioModel.media_type == "IMAGE",
            StudioProvider.enabled == 1,
        )
        .first()
    )
    if not model:
        return jsonify(success=False, msg="图片模型不存在、已停用或无权访问"), 404
    if (
        str(model.model_code or "").strip().lower()
        != KUAIPAO_IMAGE_MODEL_CODE
        or provider_catalog_key(model.provider) != "kuaipao"
    ):
        return jsonify(
            success=False,
            msg="批量图片处理只能使用快跑 AI 的 gpt-image2 模型",
        ), 400
    provider_department_id = getattr(model.provider, "dept_id", None)
    if provider_department_id is None:
        return jsonify(success=False, msg="图片模型供应商尚未归属部门"), 400
    if not can_access_model(
        current_user,
        model,
        department_id=provider_department_id,
        owner_type=PROVIDER_OWNER_DEPARTMENT,
    ):
        return jsonify(success=False, msg="无权使用该图片模型或供应商配置"), 403
    if (
        not is_super_admin_user()
        and int(batch_prompt.dept_id) != int(provider_department_id)
    ):
        return jsonify(
            success=False,
            msg="当前图片模型与批量提示词所属部门不一致",
        ), 403
    if not str(model.provider.api_key or "").strip():
        return jsonify(
            success=False,
            msg="快跑 AI 供应商尚未配置 API Key，请先编辑供应商",
        ), 400

    product_id = batch_prompt.product_id
    if product_id:
        product = _generation_product(
            product_id,
            provider_department_id,
        )
        if not product:
            return jsonify(
                success=False,
                msg="批量提示词关联产品不存在、已停用或无权访问",
            ), 400

    app = current_app._get_current_object()
    user_id = current_user.id
    product_name = batch_prompt.product_name_snapshot or ""
    generation_department_id = int(provider_department_id)
    generation_product_id = int(product_id) if product_id else None

    def process_one_version(version_number, version):
        errors = []
        for attempt in range(1, BATCH_IMAGE_MAX_ATTEMPTS + 1):
            with app.app_context():
                try:
                    acting_user = User.query.get(user_id)
                    if not acting_user:
                        raise ValueError("当前用户不存在")
                    task = create_generation(
                        user_id=user_id,
                        media_type="IMAGE",
                        model_id=model_id,
                        product_id=generation_product_id,
                        prompt=version["prompt"],
                        options={
                            "count": 1,
                            "aspect_ratio": version["aspect_ratio"],
                            "resolution": version["resolution"],
                            # The version is already the complete prompt from
                            # the selected batch-prompt history. Do not load
                            # or append a Skill during image batch processing.
                            # The product is still passed separately so its
                            # authorized reference images are resolved.
                            "prepared_prompt": version["prompt"],
                            "department_id": generation_department_id,
                        },
                        acting_user=acting_user,
                    )
                    return {
                        "version": version_number,
                        "task_id": task.id,
                        "attempts": attempt,
                    }
                except Exception as exc:
                    message = str(exc) or "图片任务提交失败"
                    errors.append(message)
                    app.logger.warning(
                        "studio image batch version failed: "
                        "batch_prompt_id=%s version=%s attempt=%s/%s "
                        "error=%s",
                        batch_prompt_id,
                        version_number,
                        attempt,
                        BATCH_IMAGE_MAX_ATTEMPTS,
                        message,
                    )
                    if getattr(exc, "_upstream_accepted", False):
                        app.logger.warning(
                            "studio image batch version will not retry because "
                            "the provider already accepted the request: "
                            "batch_prompt_id=%s version=%s task_id=%s",
                            batch_prompt_id,
                            version_number,
                            getattr(exc, "_generation_task_id", None),
                        )
                        break
                finally:
                    db.session.remove()
        return {
            "version": version_number,
            "attempts": len(errors),
            "error": errors[-1] if errors else "图片任务提交失败",
            "retry_errors": errors,
        }

    max_workers = min(max(1, len(versions)), 8)
    results = []
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="studio-image-batch",
    ) as executor:
        futures = [
            executor.submit(process_one_version, index, version)
            for index, version in enumerate(versions, start=1)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: int(item.get("version") or 0))
    successful_results = [
        item for item in results if item.get("task_id")
    ]
    failed_results = [
        item for item in results if not item.get("task_id")
    ]
    task_ids = [int(item["task_id"]) for item in successful_results]
    task_payloads = {}
    if task_ids:
        task_rows = (
            _with_task_loaders(
                _scoped_task_query().filter(
                    StudioGenerationTask.id.in_(task_ids)
                ),
                include_comments=True,
            )
            .all()
        )
        task_payloads = {
            int(task.id): _task_dict(task)
            for task in task_rows
            if _can_read_task(task)
        }

    tasks = []
    for item in successful_results:
        task = task_payloads.get(int(item["task_id"]))
        if not task:
            failed_results.append(
                {
                    "version": item["version"],
                    "attempts": item.get("attempts", 1),
                    "error": "任务已创建但当前数据范围无法读取任务历史",
                }
            )
            continue
        task["batch_prompt_id"] = batch_prompt.id
        task["batch_version"] = item["version"]
        task["batch_attempts"] = item.get("attempts", 1)
        task["batch_product_name"] = product_name
        tasks.append(task)

    if failed_results and tasks:
        message = (
            f"已提交 {len(tasks)} 个图片版本，"
            f"{len(failed_results)} 个版本失败并已重试"
        )
    elif failed_results:
        message = "所有图片版本生成失败，失败版本已自动重试"
    else:
        message = f"已提交 {len(tasks)} 个图片版本"
    return jsonify(
        success=True,
        msg=message,
        data={
            "batch_prompt_id": batch_prompt.id,
            "version_count": len(versions),
            "succeeded": len(tasks),
            "failed": len(failed_results),
            "tasks": tasks,
            "failures": failed_results,
        },
    )


@studio_bp.put("/api/batch-prompts/<int:batch_prompt_id>")
@login_required
def update_batch_prompt_api(batch_prompt_id):
    """Validate and atomically replace an edited GoFastDFS prompt document."""

    batch_prompt = _scoped_batch_prompt_query().filter_by(
        id=batch_prompt_id,
    ).first()
    if not batch_prompt:
        return jsonify(success=False, msg="批量提示词历史不存在"), 404
    permission_error = _batch_prompt_permission_response(
        batch_prompt.media_type,
        require_media=False,
    )
    if permission_error:
        return permission_error
    if batch_prompt.status != "SUCCEEDED":
        return jsonify(success=False, msg="只有已完成的批量提示词可以编辑"), 400

    content = str(_body().get("content") or "")
    try:
        versions = parse_version_document(
            content,
            batch_prompt.version_count,
        )
        if batch_prompt.media_type == "IMAGE":
            parse_image_batch_versions(
                content,
                batch_prompt.version_count,
                default_aspect_ratio=normalize_image_aspect_ratio(
                    getattr(batch_prompt, "image_aspect_ratio", None)
                    or DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
                ),
                default_resolution=normalize_batch_image_resolution(
                    getattr(batch_prompt, "image_resolution", None),
                    default=DEFAULT_BATCH_IMAGE_RESOLUTION,
                ),
            )
        document = format_versions(versions)
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400

    asset = _batch_prompt_asset(batch_prompt)
    if not asset:
        return jsonify(
            success=False,
            msg="批量提示词文件不存在、已过期或无权访问",
        ), 400

    file_name = (
        batch_prompt.file_name
        or asset.original_filename
        or f"batch-prompt-{batch_prompt.id}.txt"
    )
    pending = None
    try:
        with _temporary_batch_prompt_file(document, file_name) as (
            temporary_path,
            stored_filename,
        ):
            with open(temporary_path, "rb") as stream:
                replacement_bytes = stream.read()
                pending = FileService.stage_asset_update(
                    asset,
                    content=replacement_bytes,
                    filename=stored_filename,
                    content_type="text/plain; charset=utf-8",
                    category=FileService.default_category("FILE", "BATCH_PROMPT"),
                )
        batch_prompt.file_name = file_name
        batch_prompt.error_message = None
        batch_prompt.status = "SUCCEEDED"
        db.session.add(batch_prompt)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if pending:
            FileService.rollback_asset_update(pending)
        current_app.logger.exception(
            "studio batch prompt update failed: id=%s error=%s",
            batch_prompt_id,
            str(exc),
        )
        return jsonify(success=False, msg=str(exc)), 400

    FileService.finalize_asset_update(pending)
    batch_prompt = StudioBatchPrompt.query.get(batch_prompt_id)
    return jsonify(
        success=True,
        msg="批量提示词已保存",
        data=_batch_prompt_dict(batch_prompt),
    )


@studio_bp.get("/api/tasks/<task_code>")
@login_required
def task_status(task_code):
    task = _with_task_loaders(
        _scoped_task_query().filter_by(task_code=task_code),
        include_comments=True,
    ).first()
    if not task:
        return jsonify(success=False, msg="任务不存在"), 404
    if not _can_read_task(task):
        return jsonify(success=False, msg="权限不足"), 403
    if task.status in ("SUBMITTED", "PROCESSING"):
        poll_task(task)
        task = (
            _scoped_task_query(task.dept_id).filter_by(id=task.id).first()
            or task
        )
    return jsonify(success=True, data=_task_dict(task))


def _analyze_task_feedback(task_code):
    """Analyze operator feedback and propose product-center updates."""

    task = _with_task_loaders(
        _scoped_task_query().filter_by(task_code=task_code),
        include_comments=True,
    ).first()
    if not task:
        return jsonify(success=False, msg="任务不存在"), 404
    if not _can_read_task(task):
        return jsonify(success=False, msg="权限不足"), 403
    media_type = str(task.media_type or "IMAGE").upper()
    if media_type not in ("IMAGE", "VIDEO"):
        return jsonify(success=False, msg="当前任务类型不支持意见反馈"), 400
    required_permission = (
        "studio:video" if media_type == "VIDEO" else "studio:image"
    )
    if not _has_permission(required_permission):
        return jsonify(success=False, msg="没有当前媒体类型的反馈分析权限"), 403
    if task.status != "SUCCEEDED":
        media_label = "图片" if media_type == "IMAGE" else "视频"
        return jsonify(
            success=False,
            msg=f"{media_label}任务尚未完成，暂时不能提交意见反馈",
        ), 400

    feedback = str(_body().get("feedback") or "").strip()
    if not feedback:
        return jsonify(success=False, msg="请先填写本次生成的不满意、瑕疵或变形说明"), 400

    output_asset_type = "VIDEO" if media_type == "VIDEO" else "IMAGE"
    output_assets = [
        asset
        for _link, asset in generation_task_asset_links_for_task(
            task,
            roles={"OUTPUT", "RESULT", "THUMBNAIL"},
            include_legacy=True,
        )
        if asset
        and asset.purpose == "GENERATION_OUTPUT"
        and asset.asset_type == output_asset_type
        and asset.status == "ACTIVE"
        and (
            task.dept_id is None
            or asset.dept_id == task.dept_id
        )
    ]
    has_output_asset_rows = bool(output_assets)
    output_assets = [
        asset
        for asset in output_assets
        if can_access_asset(current_user, asset)
    ]
    output_urls = [
        asset.public_url
        for asset in output_assets
        if _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
    ]
    if (
        not output_urls
        and not has_output_asset_rows
        and _is_usable_asset_url(task.output_url)
    ):
        output_urls = [task.output_url]
    if not output_urls:
        media_label = "图片" if media_type == "IMAGE" else "视频"
        return jsonify(
            success=False,
            msg=f"没有可供意见反馈使用的{media_label}资产",
        ), 400

    chat_model = _global_chat_model(task.dept_id)
    if not chat_model or not chat_model.provider:
        return jsonify(success=False, msg="请先在模型供应商中选择启用的全局语言模型"), 400
    if not can_access_model(
        current_user,
        chat_model,
        department_id=task.dept_id,
    ):
        return jsonify(success=False, msg="无权使用当前全局语言模型"), 403
    if not str(chat_model.provider.api_key or "").strip():
        return jsonify(
            success=False,
            msg="全局语言模型尚未配置 API Key，请先编辑对应供应商",
        ), 400
    # The feedback Skill is a system-wide built-in resource. It is normally
    # stored under the seed department, so filtering it by the task's
    # department makes valid cross-department feedback fail for both admin
    # and department users.
    feedback_skill = (
        StudioSkill.query.filter_by(
            code=FEEDBACK_SKILL_CODE,
            enabled=1,
        )
        .order_by(StudioSkill.id.asc())
        .first()
    )
    if not feedback_skill:
        return jsonify(
            success=False,
            msg=f"{FEEDBACK_SKILL_NAME} Skill 尚未初始化，请先执行 flask studio-init",
        ), 400
    try:
        feedback_skill_prompt = read_skill_text(
            feedback_skill,
            user=current_user,
            builtin_codes=FEEDBACK_BUILTIN_SKILL_CODES,
        )
    except StorageError as exc:
        return jsonify(success=False, msg=str(exc)), 400
    if not feedback_skill_prompt:
        return jsonify(success=False, msg="意见反馈 Skill 内容为空，请重新导入 Skill"), 400
    if "core_selling_points" not in feedback_skill_prompt:
        feedback_skill_prompt += (
            "\n\n系统补充字段要求：关联产品时，如果视觉证据或操作者意见充分，"
            "请评估并在 product_updates 中返回 core_selling_points、"
            "product_profile 和 product_memory 的完整最终文本；没有充分证据的字段返回 null "
            "或省略，不要臆造。"
        )

    reference_assets = [
        asset
        for _link, asset in generation_task_asset_links_for_task(
            task,
            roles={"REFERENCE", "REFERENCE_IMAGE", "REFERENCE_VIDEO", "INPUT"},
            include_legacy=True,
        )
        if asset
        and asset.purpose == "GENERATION_REFERENCE"
        and asset.status == "ACTIVE"
        and (
            task.dept_id is None
            or asset.dept_id == task.dept_id
        )
    ]
    reference_assets = [
        asset
        for asset in reference_assets
        if can_access_asset(current_user, asset)
    ]
    generation_image_urls = [
        asset.public_url
        for asset in reference_assets
        if asset.asset_type in ("IMAGE", "BOTH")
        if _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
    ]
    generation_video_urls = [
        asset.public_url
        for asset in reference_assets
        if asset.asset_type == "VIDEO"
        if _asset_is_active(asset) and _is_usable_asset_url(asset.public_url)
    ]
    product = task.product
    product_descriptors = product_reference_descriptors(
        task.product,
        generation_image_urls,
        media_type=media_type,
        asset_filter=_product_asset_is_accessible,
    )
    product_urls = [
        descriptor["url"]
        for descriptor in product_descriptors
        if descriptor.get("url")
    ]
    if media_type == "IMAGE":
        image_urls = list(dict.fromkeys(output_urls + product_urls))[:14]
        video_urls = []
    else:
        image_urls = list(dict.fromkeys(product_urls))[:14]
        video_urls = list(dict.fromkeys(output_urls + generation_video_urls))[:6]
    product_id = task.product_id
    media_label = "图片" if media_type == "IMAGE" else "视频"
    clean_final_prompt = _strip_generated_reference_sections(
        task.final_prompt or task.prompt
    )
    reference_lines = []
    if media_type == "IMAGE":
        reference_lines.extend(
            f"第 {index} 张生成结果图片：本次反馈要检查的生成结果。"
            for index, _url in enumerate(output_urls, 1)
        )
        if product_descriptors:
            reference_lines.append(
                "生成结果之后的图片按以下产品/任务参考素材顺序提供：\n"
                + reference_instructions(
                    product_descriptors,
                    include_urls=False,
                )
            )
    else:
        if product_descriptors:
            reference_lines.append(
                "图片内容块是产品中心和本次任务的图片参考，顺序如下：\n"
                + reference_instructions(
                    product_descriptors,
                    include_urls=False,
                )
            )
        if video_urls:
            reference_lines.append(
                "视频内容块按顺序提供，第一项是生成结果，后续是任务参考视频：\n"
                + "\n".join(
                    (
                        f"第 {index} 个视频："
                        + (
                            "本次生成结果视频。"
                            if index == 1
                            else f"本次上传的参考视频 {index - 1}。"
                        )
                    )
                    for index, _url in enumerate(video_urls, 1)
                )
            )
    context_parts = [
        "请使用系统提供的意见反馈 Skill 分析以下任务，不要重复输出 Skill 原文。",
        f"媒体类型：{media_label}",
        f"生成任务编号：{task.task_code}",
        f"原始创意：{task.prompt}",
        f"最终提示词（已移除重复参考章节）：{clean_final_prompt}",
        f"操作者意见反馈：{feedback}",
    ]
    if reference_lines:
        context_parts.append(
            "视觉素材内容块顺序说明：\n" + "\n".join(reference_lines)
        )
    if product:
        for label, value in (
            ("产品名称", product.name),
            ("产品编码", product.code),
            ("品牌信息", product.brand),
            ("产品资料", product.description),
            ("核心卖点", product.core_selling_points),
            ("Product Profile", product.product_profile),
            ("产品记忆", product.product_memory),
            ("生成规则", product.generation_rules),
            ("禁止修改规则", product.forbidden_rules),
        ):
            if str(value or "").strip():
                context_parts.append(f"{label}：{str(value).strip()}")
    else:
        context_parts.append(
            f"本次任务没有关联产品中心；只分析生成{media_label}和操作者意见，"
            "不要提出或应用产品中心字段修改建议。"
        )
    skill_name = str(getattr(task, "skill_name", "") or "").strip()
    skill_prompt = str(getattr(task, "skill_prompt", "") or "").strip()
    if skill_name or skill_prompt:
        context_parts.append(
            "原任务创作 Skill 仅作为本次任务的背景信息，不能覆盖用户创意、"
            "产品中心信息或系统反馈 Skill。"
        )
    if skill_prompt:
        context_parts.append(f"原任务 Skill 指令摘要：{skill_prompt}")
    feedback_context = _limit_utf8(
        "\n".join(context_parts),
        12000,
    )
    content_blocks = [
        {
            "type": "text",
            "text": feedback_context,
        }
    ]
    content_blocks.extend(
        {
            "type": "image_url",
            "image_url": {"url": url},
        }
        for url in image_urls
    )
    content_blocks.extend(
        {
            "type": "video_url",
            "video_url": {"url": url},
        }
        for url in video_urls
    )
    messages = [
        {
            "role": "system",
            "content": feedback_skill_prompt,
        },
        {"role": "user", "content": content_blocks},
    ]
    runtime = {
        "messages": messages,
        "max_tokens": 1800,
        "temperature": 0.2,
    }
    body = build_request_body(chat_model, runtime)
    body.setdefault("model", chat_model.model_code)
    body.setdefault("messages", messages)
    body.setdefault("max_tokens", 1800)
    body.setdefault("temperature", 0.2)
    provider_snapshot = _chat_provider_snapshot(chat_model.provider)
    chat_spec = model_spec_for(
        getattr(chat_model, "provider", None),
        getattr(chat_model, "model_code", ""),
    )
    model_snapshot = ModelExecutionContext(
        id=getattr(chat_model, "id", None),
        name=str(getattr(chat_model, "name", "") or ""),
        media_type="CHAT",
        model_code=str(getattr(chat_model, "model_code", "") or ""),
        generation_path=(
            (chat_spec.generation_path if chat_spec else None)
            or chat_model.generation_path
            or getattr(chat_model.provider, "generation_path", None)
            or "/v1/chat/completions"
        ),
        result_path=None,
        provider_id=getattr(chat_model, "provider_id", None),
    )
    feedback_user_id = int(current_user.id)
    comment = StudioGenerationComment(
        generation_task_id=task.id,
        user_id=feedback_user_id,
        dept_id=task.dept_id,
        model_id=chat_model.id,
        comment_type="FEEDBACK",
        status="PENDING",
        request_body=json.dumps(body, ensure_ascii=False, default=str),
    )
    db.session.add(comment)
    db.session.commit()
    comment_id = comment.id
    current_app.logger.info(
        "studio feedback request: task_code=%s product_id=%s "
        "chat_model_id=%s chat_model_code=%s feedback_skill_id=%s "
        "feedback_skill_code=%s request_body=%s",
        task.task_code,
        product_id,
        chat_model.id,
        chat_model.model_code,
        feedback_skill.id,
        feedback_skill.code,
        _dump(redact_provider_payload(body)),
    )

    try:
        client = ProviderClient(provider_snapshot)
        release_db_connection()
        response = client.complete(model_snapshot, body)
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
        applied_fields = []
        product = _generation_product(product_id, task.dept_id)
        if product:
            for field in PRODUCT_UPDATE_FIELDS:
                update = normalized["updates"].get(field)
                value = (
                    update.get("value")
                    if isinstance(update, dict)
                    else None
                )
                replace_empty = (
                    isinstance(update, dict)
                    and bool(update.get("replace"))
                    and value == ""
                )
                if value is None or (value == "" and not replace_empty):
                    continue
                setattr(product, field, str(value).strip())
                applied_fields.append(field)
            if applied_fields:
                comment.applied_update_fields = json.dumps(
                    applied_fields,
                    ensure_ascii=False,
                )
                comment.applied_at = datetime.now()
                comment.applied_by = feedback_user_id
                db.session.add(product)
        current_app.logger.info(
            "studio feedback completed: task_code=%s product_id=%s "
            "model_id=%s feedback_skill_id=%s analysis=%s "
            "product_updates=%s applied_fields=%s",
            task.task_code,
            product_id,
            chat_model.id,
            feedback_skill.id,
            comment.content,
            json.dumps(normalized["updates"], ensure_ascii=False, default=str),
            ",".join(applied_fields),
        )
        db.session.commit()
        return jsonify(
            success=True,
            msg=(
                "意见反馈已完成，产品资料已自动更新"
                if applied_fields
                else "意见反馈已完成"
            ),
            data=_comment_dict(comment),
        )
    except Exception as exc:
        comment = StudioGenerationComment.query.get(comment_id)
        if comment:
            comment.status = "FAILED"
            comment.error_message = str(exc)
            db.session.commit()
        current_app.logger.exception(
            "studio feedback failed: task_code=%s product_id=%s "
            "chat_model_id=%s error=%s",
            task.task_code,
            product_id,
            chat_model.id,
            str(exc),
        )
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.post("/api/tasks/<task_code>/comments/analyze")
@login_required
def analyze_task(task_code):
    """Keep the original endpoint while using the feedback implementation."""

    return _analyze_task_feedback(task_code)


@studio_bp.post("/api/tasks/<task_code>/comments/<int:comment_id>/apply-product-updates")
@authorize("studio:products", log=True)
def apply_product_updates(task_code, comment_id):
    """Apply legacy or operator-selected AI suggestions to the linked product."""

    task = _scoped_task_query().filter_by(task_code=task_code).first()
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
    if not can_access_resource(current_user, task.product):
        return jsonify(success=False, msg="无权修改当前产品"), 403

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


def _studio_history_cursor():
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


def _next_studio_history_cursor(rows):
    if not rows:
        return None
    last = rows[-1]
    if not last.created_at or not last.id:
        return None
    return {
        "cursor": f"{last.created_at.isoformat(sep=' ')}|{last.id}",
        "cursor_created_at": last.created_at.isoformat(sep=" "),
        "cursor_id": int(last.id),
    }


@studio_bp.get("/api/history")
@authorize("studio:history")
def history_api():
    code = (request.args.get("code") or "").strip()
    media_type = str(request.args.get("media_type") or "").upper()
    page = max(_int_or_none(request.args.get("page")) or 1, 1)
    page_size = _int_or_none(request.args.get("page_size")) or 20
    page_size = min(max(page_size, 1), 50)
    query = _scoped_task_query()
    if code:
        query = query.filter_by(task_code=code)
    if media_type in ("IMAGE", "VIDEO"):
        query = query.filter_by(media_type=media_type)
    cursor_created_at, cursor_id = _studio_history_cursor()
    if cursor_created_at is not None and cursor_id is not None:
        query = query.filter(
            or_(
                StudioGenerationTask.created_at < cursor_created_at,
                and_(
                    StudioGenerationTask.created_at == cursor_created_at,
                    StudioGenerationTask.id < cursor_id,
                ),
            )
        )
        tasks = (
            _with_task_loaders(
                query.order_by(
                    desc(StudioGenerationTask.created_at),
                    desc(StudioGenerationTask.id),
                ),
                include_comments=False,
            )
            .limit(page_size + 1)
            .all()
        )
        has_more = len(tasks) > page_size
        tasks = tasks[:page_size]
        return jsonify(
            success=True,
            data=[
                _task_dict(task, include_comments=False)
                for task in tasks
            ],
            meta={
                "page_size": page_size,
                "has_more": has_more,
                "next_cursor": _next_studio_history_cursor(tasks)
                if has_more
                else None,
            },
        )

    tasks = (
        _with_task_loaders(
            query.order_by(
                desc(StudioGenerationTask.created_at),
                desc(StudioGenerationTask.id),
            ),
            include_comments=False,
        )
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
        .all()
    )
    has_more = len(tasks) > page_size
    tasks = tasks[:page_size]
    return jsonify(
        success=True,
        data=[_task_dict(task, include_comments=False) for task in tasks],
        meta={
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
        },
    )


@studio_bp.delete("/api/history/<int:task_id>")
@authorize("studio:history", log=True)
def delete_history_api(task_id):
    if not _can_delete_history():
        return jsonify(success=False, msg="仅超级管理员可以删除生成历史"), 403

    task = _scoped_task_query().filter_by(id=task_id).first()
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
        _scoped_product_query()
        .filter_by(enabled=1)
        .order_by(desc(StudioProduct.updated_at))
        .all()
    )
    return jsonify(success=True, data=[_product_dict(product) for product in products])


def _scoped_listing_history_query():
    """Return successful Listing histories within the caller's data scope."""

    query = AmazonAiTask.query.filter(
        AmazonAiTask.task_type == "LISTING_GENERATE",
        AmazonAiTask.status == "SUCCEEDED",
    )
    if is_super_admin_user():
        return query
    department_id = user_department_id()
    if department_id is None:
        return query.filter(False)
    if is_department_admin_user():
        return query.filter(AmazonAiTask.dept_id == department_id)
    return query.filter(
        AmazonAiTask.dept_id == department_id,
        AmazonAiTask.user_id == current_user.id,
    )


def _listing_history_filename(task):
    refs = _json(task.result_refs_json, {}) or {}
    return str(
        task.output_filename
        or refs.get("response_filename")
        or ""
    ).strip()


def _listing_history_dict(task):
    return {
        "id": task.id,
        "task_number": task.id,
        "task_code": task.task_code,
        "title": task.title or "Listing创作",
        "filename": _listing_history_filename(task),
        "status": task.status,
        "dept_id": task.dept_id,
        "finished_at": (
            task.finished_at.strftime("%Y-%m-%d %H:%M:%S")
            if task.finished_at
            else ""
        ),
    }


def _listing_history_by_ref(value):
    value = str(value or "").strip()
    query = _scoped_listing_history_query()
    if value.isdigit():
        return query.filter(AmazonAiTask.id == int(value)).first()
    return query.filter(AmazonAiTask.task_code == value).first()


@studio_bp.get("/api/products/listing-histories")
@authorize("studio:products")
def product_listing_histories_api():
    rows = (
        _scoped_listing_history_query()
        .order_by(
            desc(AmazonAiTask.finished_at),
            desc(AmazonAiTask.id),
        )
        .limit(300)
        .all()
    )
    return jsonify(
        success=True,
        data=[_listing_history_dict(task) for task in rows],
    )


@studio_bp.post("/api/products/from-listing")
@authorize("studio:products", log=True)
def create_product_from_listing():
    """Extract durable product fields from one completed Listing result."""

    data = _body()
    task = _listing_history_by_ref(
        data.get("listing_task_id")
        or data.get("task_id")
        or data.get("listing_task_code")
    )
    if not task:
        return jsonify(success=False, msg="Listing 创作历史不存在或无权访问"), 404
    if not task.dept_id:
        return jsonify(success=False, msg="Listing 历史没有有效的部门归属"), 400

    try:
        listing_content = str(
            read_task_result_text(
                task,
                maximum_size=int(
                    current_app.config.get(
                        "AMAZON_AI_MAX_COMBINED_CONTEXT_BYTES"
                    )
                    or 280000
                ),
                user=current_user,
            )
            or ""
        ).strip()
        if not listing_content:
            raise ValueError("Listing 创作历史结果为空")

        extraction_skill = StudioSkill.query.filter_by(
            code=PRODUCT_EXTRACTION_SKILL_CODE,
            enabled=1,
        ).first()
        if not extraction_skill or not can_access_skill(
            current_user,
            extraction_skill,
            builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
        ):
            raise ValueError(
                "产品提取 Skill 尚未初始化，请先执行 flask amazon-ai-init"
            )
        skill_prompt = read_skill_text(
            extraction_skill,
            user=current_user,
            builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
        )
        if not skill_prompt:
            raise ValueError("产品提取 Skill 内容为空，请重新导入 Skill")

        chat_model = AmazonAiService().require_global_model(
            task.dept_id,
            user=current_user,
        )
        user_prompt = (
            "以下内容是已经完成的 Listing 创作历史。"
            "请按照产品提取 Skill 只提取目标产品的明确事实。"
            "Listing 任务 ID、任务编号、文件名和来源 URL 仅用于定位，"
            "绝对不能写入 product_code。\n\n"
            "===== Listing 创作历史全文 =====\n"
            + listing_content
        )
        response = complete_chat(
            chat_model,
            {
                "model": chat_model.model_code,
                "messages": [
                    {"role": "system", "content": skill_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 2400,
                "temperature": 0.1,
            },
            department_id=task.dept_id,
            user=current_user,
        )
        extracted = _normalize_extracted_product(
            extract_chat_content(response),
            listing_task=task,
        )

        code = extracted.get("code")
        if code:
            duplicate = StudioProduct.query.filter(
                StudioProduct.code == code,
                StudioProduct.enabled == 1,
            ).first()
            if duplicate:
                raise ValueError(
                    f"提取到的产品编码 {code} 已存在，请修改后再创建产品"
                )

        product = StudioProduct(
            dept_id=task.dept_id,
            code=code,
            name=extracted.get("name"),
            brand=extracted.get("brand"),
            description=extracted.get("description"),
            product_profile=extracted.get("product_profile"),
            core_selling_points=extracted.get("core_selling_points"),
            product_memory=extracted.get("product_memory"),
            generation_rules=extracted.get("generation_rules"),
            forbidden_rules=extracted.get("forbidden_rules"),
            asset_urls=json.dumps([], ensure_ascii=False),
            enabled=1,
            created_by=current_user.id,
        )
        db.session.add(product)
        db.session.commit()
        current_app.logger.info(
            "studio product extracted from listing: product_id=%s "
            "listing_task_id=%s listing_task_code=%s model_id=%s",
            product.id,
            task.id,
            task.task_code,
            chat_model.id,
        )
        return jsonify(
            success=True,
            msg="已根据 Listing 历史创建产品，可继续编辑产品资料",
            data={
                "product": _product_dict(product),
                "listing_task": _listing_history_dict(task),
            },
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "studio product extraction failed: listing_task_id=%s error=%s",
            task.id,
            str(exc),
        )
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.post("/api/products")
@authorize("studio:products")
def save_product():
    data = _body()
    product_id = _int_or_none(data.get("id"))
    product = (
        _scoped_product_query().filter_by(id=product_id).first()
        if product_id
        else StudioProduct()
    )
    if product_id and not product:
        return jsonify(success=False, msg="产品不存在"), 404

    code = str(data.get("code") or "").strip() or None
    name = str(data.get("name") or "").strip() or None
    try:
        department_id = (
            product.dept_id
            if product_id
            else _write_department_id(data)
        )
        if product_id and not _can_access_department(product.dept_id):
            return jsonify(success=False, msg="产品不存在或无权访问"), 404
        if product_id and department_id is None:
            department_id = _write_department_id(data)
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400
    duplicate = (
        StudioProduct.query.filter(
            StudioProduct.code == code,
            StudioProduct.id != (product.id or 0),
        ).first()
        if code
        else None
    )
    if duplicate:
        return jsonify(success=False, msg="产品编码已经存在"), 400

    product.code = code
    product.name = name
    product.brand = str(data.get("brand") or "").strip() or None
    product.description = str(data.get("description") or "").strip() or None
    product.product_profile = (
        str(data.get("product_profile") or "").strip() or None
    )
    product.core_selling_points = (
        str(data.get("core_selling_points") or "").strip() or None
    )
    product.product_memory = (
        str(data.get("product_memory") or "").strip() or None
    )
    product.generation_rules = (
        str(data.get("generation_rules") or "").strip() or None
    )
    product.forbidden_rules = (
        str(data.get("forbidden_rules") or "").strip() or None
    )
    product.asset_urls = json.dumps(split_urls(data.get("asset_urls")), ensure_ascii=False)
    product.enabled = 1
    product.dept_id = department_id
    product.created_by = product.created_by or current_user.id
    db.session.add(product)
    db.session.commit()
    return jsonify(success=True, msg="产品已保存", data=_product_dict(product))


@studio_bp.post("/api/products/<int:product_id>/inline")
@authorize("studio:products", log=True)
def update_product_inline(product_id):
    """Save one editable product field without opening the full form."""

    product = _scoped_product_query().filter_by(
        id=product_id,
        enabled=1,
    ).first()
    if not product:
        return jsonify(success=False, msg="产品不存在或已停用"), 404

    data = _body()
    field = str(data.get("field") or "").strip()
    if field not in PRODUCT_INLINE_FIELDS:
        return jsonify(success=False, msg="不支持直接编辑的产品字段"), 400

    value = str(data.get("value") or "").strip()
    setattr(product, field, value)
    db.session.add(product)
    db.session.commit()
    return jsonify(success=True, msg="产品字段已保存", data=_product_dict(product))


@studio_bp.delete("/api/products/<int:product_id>")
@authorize("studio:products", log=True)
def delete_product(product_id):
    product = _scoped_product_query().filter_by(id=product_id).first()
    if not product:
        return jsonify(success=False, msg="产品不存在"), 404
    stored_assets = {}
    for asset in product.assets:
        asset.enabled = 0
        if asset.storage_asset_id:
            stored_asset = getattr(asset, "storage_asset", None)
            if (
                stored_asset
                and stored_asset.status in ("ACTIVE", "DELETE_FAILED")
                and stored_asset.dept_id == product.dept_id
                and can_access_asset(current_user, stored_asset)
            ):
                stored_assets[stored_asset.id] = stored_asset
    product.enabled = 0
    cleanup_failed = False
    cleanup_protected = 0
    for stored_asset in stored_assets.values():
        if asset_referenced(stored_asset.id, now=None):
            cleanup_protected += 1
            continue
        if not FileService.delete_asset(stored_asset):
            cleanup_failed = True
    db.session.commit()
    if cleanup_failed:
        message = "产品已停用，部分素材删除失败，已保留待重试"
    elif cleanup_protected:
        message = "产品已停用，仍被其他业务引用的素材已保留"
    else:
        message = "产品已停用"
    return jsonify(success=True, msg=message)


@studio_bp.post("/api/products/<int:product_id>/assets")
@authorize("studio:products")
def save_product_asset(product_id):
    product = _scoped_product_query().filter_by(
        id=product_id,
        enabled=1,
    ).first()
    if not product:
        return jsonify(success=False, msg="product not found or disabled"), 400

    data = _body()
    url = str(data.get("url") or "").strip()
    storage_asset_id = _int_or_none(data.get("storage_asset_id"))
    storage_asset = (
        StudioAsset.query.filter(
            StudioAsset.id == storage_asset_id,
            StudioAsset.status == "ACTIVE",
            StudioAsset.dept_id == product.dept_id,
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
        if not can_access_asset(current_user, storage_asset):
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
    previous_storage_assets = []
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
                    dept_id=product.dept_id,
                ).first()
                if (
                    previous_storage
                    and previous_storage.id != storage_asset_id
                    and can_access_asset(current_user, previous_storage)
                ):
                    previous_storage_assets.append(previous_storage)
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
    try:
        # Switch the product reference first. Old files are cleaned only
        # after this transaction succeeds, so a failed save keeps them usable.
        db.session.add(asset)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify(success=False, msg=str(exc)), 400

    cleanup_failed = False
    cleanup_protected = 0
    for previous_storage in previous_storage_assets:
        if asset_referenced(previous_storage.id, now=None):
            cleanup_protected += 1
            continue
        if not FileService.delete_asset(previous_storage):
            cleanup_failed = True
    if previous_storage_assets:
        db.session.commit()

    message = (
        "素材已添加，旧文件清理失败，已保留待后续重试"
        if cleanup_failed
        else "素材已添加，旧文件仍被其他业务引用，已保留"
        if cleanup_protected
        else "素材已添加"
    )
    return jsonify(success=True, msg=message, data=_product_dict(product))


@studio_bp.delete("/api/products/<int:product_id>/assets/<int:asset_id>")
@authorize("studio:products")
def delete_product_asset(product_id, asset_id):
    product = _scoped_product_query().filter_by(id=product_id).first()
    asset = (
        StudioProductAsset.query.filter_by(
            id=asset_id,
            product_id=product_id,
        ).first()
        if product
        else None
    )
    if not asset:
        return jsonify(success=False, msg="素材不存在"), 404
    asset.enabled = 0
    if asset.storage_asset_id:
        stored_asset = getattr(asset, "storage_asset", None)
        if (
            stored_asset
            and stored_asset.status in ("ACTIVE", "DELETE_FAILED")
            and stored_asset.dept_id == product.dept_id
            and can_access_asset(current_user, stored_asset)
            and not asset_referenced(stored_asset.id, now=None)
        ):
            FileService.delete_asset(stored_asset)
    db.session.commit()
    return jsonify(success=True, msg="素材已停用", data=_product_dict(product))


@studio_bp.get("/api/providers")
@authorize("studio:providers")
def providers_api():
    if not can_manage_provider():
        return _provider_management_denied()
    _ensure_visible_provider_defaults()
    providers = _scoped_provider_query(
        request.args.get("dept_id"),
        request.args.get("owner_type"),
    ).join(
        Dept,
        Dept.id == StudioProvider.dept_id,
    ).order_by(
        Dept.sort.asc(),
        Dept.id.asc(),
        StudioProvider.name.asc(),
        StudioProvider.id.asc(),
    ).all()
    return jsonify(success=True, data=[_provider_dict(provider) for provider in providers])


@studio_bp.get("/api/provider-catalog")
@authorize("studio:providers")
def provider_catalog_api():
    if not can_manage_provider():
        return _provider_management_denied()
    provider_id = _int_or_none(request.args.get("provider_id"))
    provider = (
        _scoped_provider_query().filter_by(id=provider_id).first()
        if provider_id
        else None
    )
    if not provider:
        return jsonify(success=False, msg="供应商不存在或无权访问"), 404
    return jsonify(
        success=True,
        data=catalog_payload(provider, provider.models),
    )


@studio_bp.get("/api/ai-config")
@authorize("studio:providers")
def ai_config_api():
    if not can_manage_provider():
        return _provider_management_denied()
    _ensure_visible_provider_defaults()
    raw_department_id = request.args.get("dept_id")
    owner_type, department_id = _config_scope(
        raw_department_id,
        request.args.get("owner_type"),
    )
    if owner_type is None:
        return jsonify(success=False, msg="部门选择无效"), 400
    models = _global_chat_models(
        department_id,
        owner_type=owner_type,
    )
    selected = _global_chat_model(
        department_id,
        owner_type=owner_type,
    )
    departments = (
        Dept.query.order_by(Dept.sort.asc(), Dept.id.asc()).all()
        if is_super_admin_user()
        else Dept.query.filter(
            Dept.id.in_(managed_department_ids() or [-1])
        ).order_by(Dept.sort.asc(), Dept.id.asc()).all()
    )
    department_options = [
        {
            "id": department.id,
            "name": department.dept_name,
            "owner_type": PROVIDER_OWNER_DEPARTMENT,
        }
        for department in departments
    ]
    return jsonify(
        success=True,
        data={
            "dept_id": department_id,
            "dept_name": _department_label(department_id),
            "departments": department_options,
            "owner_type": owner_type,
            "global_chat_model_id": selected.id if selected else None,
            "global_chat_model": _global_chat_model_payload(selected),
            "models": [_global_chat_model_payload(model) for model in models],
        },
    )


@studio_bp.post("/api/ai-config")
@authorize("studio:providers")
def save_ai_config():
    if not can_manage_provider():
        return _provider_management_denied()
    data = _body()
    owner_type, department_id = _config_scope(
        data.get("department_id", data.get("dept_id")),
        data.get("owner_type"),
    )
    if owner_type is None or (
        owner_type == PROVIDER_OWNER_DEPARTMENT
        and department_id is None
    ):
        return jsonify(success=False, msg="请选择有效部门"), 400
    model_id = _int_or_none(data.get("global_chat_model_id"))
    model = (
        _scoped_model_query(
            department_id,
            owner_type=owner_type,
        )
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
        setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
        dept_id=department_id,
    ).first()
    if not setting:
        setting = StudioSetting(
            setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
            dept_id=department_id,
            description="图片与视频创作在关联产品或 Skill 时使用的全局语言模型",
        )
    setting.setting_value = str(model.id)
    db.session.add(setting)
    db.session.commit()
    return jsonify(
        success=True,
        msg="全局语言模型已切换",
        data={
            "dept_id": department_id,
            "owner_type": owner_type,
            "global_chat_model_id": model.id,
            "global_chat_model": _global_chat_model_payload(model),
        },
    )


@studio_bp.post("/api/providers")
@authorize("studio:providers")
def save_provider():
    if not can_manage_provider():
        return _provider_management_denied()
    data = _body()
    provider_id = _int_or_none(data.get("id"))
    provider = (
        _scoped_provider_query().filter_by(id=provider_id).first()
        if provider_id
        else StudioProvider()
    )
    if provider_id and not provider:
        return jsonify(success=False, msg="供应商不存在"), 404

    name = str(data.get("name") or "").strip()
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url:
        return jsonify(success=False, msg="供应商名称和 Base URL 不能为空"), 400
    try:
        if provider_id:
            raw_department = (
                data.get("department_id", data.get("dept_id"))
                if is_super_admin_user()
                else None
            )
            department_id = (
                _int_or_none(raw_department)
                if raw_department not in (None, "")
                else provider.dept_id
            )
            if department_id is None:
                department_id = _write_department_id(data)
        else:
            department_id = _write_department_id(data)
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400

    if department_id is None or not _can_access_department(department_id):
        return jsonify(success=False, msg="供应商所属部门无效或无权访问"), 400

    if provider_id and not can_access_provider(
        current_user,
        provider,
    ):
        return jsonify(success=False, msg="供应商不存在或无权访问"), 404

    provider.owner_type = PROVIDER_OWNER_DEPARTMENT
    provider.dept_id = department_id
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
    if not can_manage_provider():
        return _provider_management_denied()
    provider = _scoped_provider_query().filter_by(
        id=provider_id,
        enabled=1,
    ).first()
    if not provider:
        return jsonify(success=False, msg="供应商不存在或已停用"), 404
    if not provider.api_key:
        return jsonify(success=False, msg="请先配置 API Key"), 400
    scope = request.args.get("scope") or "user"
    if scope not in ("user", "token"):
        return jsonify(success=False, msg="不支持的余额类型"), 400
    try:
        client = ProviderClient(provider)
        release_db_connection()
        data = client.get_balance(scope=scope)
        safe_data = redact_provider_payload(data)
        return jsonify(
            success=True,
            msg="余额已更新",
            data={
                "scope": scope,
                "balance": normalize_balance(safe_data),
                "payload": safe_data,
            },
        )
    except Exception as exc:
        return jsonify(success=False, msg=str(exc)), 400


@studio_bp.delete("/api/providers/<int:provider_id>")
@authorize("studio:providers")
def delete_provider(provider_id):
    if not can_manage_provider():
        return _provider_management_denied()
    provider = _scoped_provider_query().filter_by(id=provider_id).first()
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
    if not can_manage_provider():
        return _provider_management_denied()
    data = _body()
    model_id = _int_or_none(data.get("id"))
    model = (
        _scoped_model_query().filter_by(id=model_id).first()
        if model_id
        else StudioModel()
    )
    if model_id and not model:
        return jsonify(success=False, msg="模型不存在"), 404

    provider_id = _int_or_none(data.get("provider_id"))
    provider = _scoped_provider_query().filter_by(
        id=provider_id,
        enabled=1,
    ).first()
    if not provider:
        return jsonify(success=False, msg="供应商不存在或已停用"), 400

    catalog = catalog_for_provider(provider)
    requested_code = str(
        data.get("catalog_code")
        or data.get("model_code")
        or (model.model_code if model else "")
        or ""
    ).strip()
    spec = catalog.get(requested_code)
    if not spec:
        return jsonify(
            success=False,
            msg="该供应商没有这个模型目录项，请先在代码目录中登记模型",
        ), 400
    model_code = spec.code
    name = spec.name
    media_type = spec.media_type

    duplicate = StudioModel.query.filter(
        StudioModel.provider_id == provider.id,
        StudioModel.model_code == model_code,
        StudioModel.id != (model.id or 0),
    ).first()
    if duplicate:
        return jsonify(success=False, msg="该供应商下的模型标识已经存在"), 400

    model.provider_id = provider.id
    model.name = name
    model.model_code = model_code
    model.media_type = media_type
    model.generation_path = spec.generation_path
    model.result_path = spec.result_path
    model.parameter_schema = json.dumps(
        spec.parameter_schema(),
        ensure_ascii=False,
    )
    model.capabilities = json.dumps(
        spec.capability_data(),
        ensure_ascii=False,
    )
    model.description = spec.description
    model.enabled = 1 if _as_enabled(data.get("enabled"), True) else 0
    db.session.add(model)
    db.session.commit()
    return jsonify(success=True, msg="模型已启用", data=_model_dict(model))


@studio_bp.delete("/api/models/<int:model_id>")
@authorize("studio:providers")
def delete_model(model_id):
    if not can_manage_provider():
        return _provider_management_denied()
    model = _scoped_model_query().filter_by(id=model_id).first()
    if not model:
        return jsonify(success=False, msg="模型不存在"), 404
    model.enabled = 0
    db.session.commit()
    return jsonify(success=True, msg="模型已停用")


def _skill_dict(skill, include_content=False):
    builtin = skill.code in AMAZON_BUILTIN_SKILL_CODES
    storage_asset_id = skill.storage_asset_id
    storage_asset = (
        StudioAsset.query.filter_by(
            id=storage_asset_id,
            purpose="SKILL",
        ).first()
        if storage_asset_id
        else None
    )
    # Built-in Amazon Skills are system resources. Their canonical files may
    # be stored under the seed department, but every department can read and
    # use them; the owning department is still returned below for display.
    storage_asset_allowed = builtin or can_access_asset(
        current_user,
        storage_asset,
        allow_system=builtin,
    )
    download_url = ""
    file_error = ""
    if not storage_asset_id:
        file_status = "NO_ASSET_LINK"
        file_status_label = "数据库未关联 GoFastDFS 文件"
    elif not storage_asset:
        file_status = "ASSET_MISSING"
        file_status_label = "数据库资产记录不存在"
        file_error = "数据库资产记录不存在"
    elif not storage_asset_allowed:
        file_status = "FORBIDDEN"
        file_status_label = "当前用户无权访问文件"
        file_error = "当前用户无权访问文件"
    elif not _asset_is_active(storage_asset):
        file_status = "INACTIVE"
        file_status_label = "GoFastDFS 文件已失效"
        file_error = "GoFastDFS 文件已失效"
    elif not (
        str(storage_asset.public_url or "").strip()
        or str(storage_asset.storage_path or "").strip()
    ):
        file_status = "STORAGE_REFERENCE_MISSING"
        file_status_label = "数据库缺少 GoFastDFS 地址"
        file_error = "数据库缺少 GoFastDFS 地址"
    elif _is_usable_asset_url(
        storage_asset.public_url or storage_asset.storage_path
    ):
        try:
            download_url = skill_file_url(
                skill,
                user=current_user,
                builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
            )
        except Exception as exc:
            file_error = str(exc)
        if download_url:
            file_status = "AVAILABLE"
            file_status_label = "GoFastDFS 文件可用"
        else:
            file_status = "URL_BUILD_FAILED"
            file_status_label = "无法生成 GoFastDFS 下载地址"
            file_error = file_error or file_status_label
    else:
        file_status = "INVALID_STORAGE_REFERENCE"
        file_status_label = "GoFastDFS 地址不可用"
        file_error = "GoFastDFS 地址不可用"

    if not storage_asset or file_status != "AVAILABLE":
        # Keep the existing UI's short status while returning a precise
        # machine-readable reason for diagnostics and future clients.
        download_url = ""

    content = ""
    content_error = ""
    if include_content:
        try:
            content = read_skill_text(
                skill,
                user=current_user,
                builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
            )
        except StorageError as exc:
            content_error = str(exc)
    return {
        "id": skill.id,
        "dept_id": skill.dept_id,
        "dept_name": _department_label(skill.dept_id),
        "is_builtin": builtin,
        "name": skill.name,
        "code": skill.code,
        "media_type": skill.media_type,
        "version": skill.version,
        "tags": skill.tags or "",
        "prompt_template": content,
        "file_name": skill.file_name or "",
        "file_type": skill.file_type or "",
        "content": content,
        "content_error": content_error,
        "storage_asset_id": storage_asset_id,
        "download_url": download_url,
        "file_available": bool(download_url),
        "file_status": file_status,
        "file_status_label": file_status_label,
        "file_error": file_error,
        "enabled": bool(skill.enabled),
    }


@studio_bp.get("/api/skills")
@authorize("studio:skills")
def skills_api():
    include_content = str(
        request.args.get("include_content") or ""
    ).strip().lower() in ("1", "true", "yes", "on")
    requested_id = _int_or_none(request.args.get("id"))
    skills = (
        _scoped_skill_query()
        .filter_by(enabled=1)
        .filter(StudioSkill.id == requested_id)
        if requested_id
        else _scoped_skill_query().filter_by(enabled=1)
    )
    skills = (
        skills
        .order_by(desc(StudioSkill.updated_at))
        .all()
    )
    return jsonify(
        success=True,
        data=[
            _skill_dict(skill, include_content=include_content)
            for skill in skills
        ],
    )


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
    if not _can_manage_skills():
        return _skill_management_denied()
    data = _body()
    skill_id = _int_or_none(data.get("id"))
    skill = (
        _scoped_skill_query().filter_by(id=skill_id).first()
        if skill_id
        else StudioSkill()
    )
    if skill_id and not skill:
        return jsonify(success=False, msg="Skill 不存在"), 404
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify(success=False, msg="Skill 名称不能为空"), 400
    try:
        department_id = (
            skill.dept_id
            if skill_id
            else _write_department_id(data)
        )
        if skill_id and not _can_access_department(skill.dept_id):
            return jsonify(success=False, msg="Skill 不存在或无权访问"), 404
        if department_id is None:
            department_id = _write_department_id(data)
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400

    old_storage_asset = (
        StudioAsset.query.filter(
            StudioAsset.id == skill.storage_asset_id,
            StudioAsset.purpose == "SKILL",
            StudioAsset.status.in_(("ACTIVE", "DELETE_FAILED")),
        ).first()
        if skill.storage_asset_id
        else None
    )
    content_provided = "content" in data
    prompt_provided = "prompt_template" in data
    content_fields_provided = content_provided or prompt_provided
    requested_content = (
        str(data.get("content") or "")
        if content_provided
        else ""
    )
    requested_prompt = (
        str(data.get("prompt_template") or "")
        if prompt_provided
        else ""
    )
    old_content = None
    old_storage_read_failed = False
    if content_fields_provided:
        if old_storage_asset:
            try:
                old_content = FileService.read_text(
                    old_storage_asset,
                    filename=old_storage_asset.original_filename,
                    maximum_size=512000,
                )
            except Exception as exc:
                if not (requested_content.strip() or requested_prompt.strip()):
                    return jsonify(
                        success=False,
                        msg="Skill 关联的 GoFastDFS 文件无法读取，请重新上传 Skill 文件",
                    ), 400
                old_storage_read_failed = True
                current_app.logger.warning(
                    "existing Skill file could not be read during replacement: "
                    "skill_id=%s error=%s",
                    skill.id,
                    str(exc),
                )
        else:
            # Only old rows with no storage asset may use their legacy body.
            old_content = str(
                skill.content or skill.prompt_template or ""
            )
        new_content = (
            requested_content
            if content_provided and requested_content.strip()
            else requested_prompt
            if prompt_provided and requested_prompt.strip()
            else requested_content
            if content_provided
            else requested_prompt
        )
        if not new_content.strip():
            return jsonify(success=False, msg="Skill 文件内容不能为空"), 400
    else:
        new_content = None

    skill.name = name
    skill.dept_id = department_id
    skill.code = skill.code or _skill_code(name)
    skill.media_type = str(data.get("media_type") or "BOTH").upper()
    skill.version = data.get("version") or "1.0.0"
    skill.tags = data.get("tags") or ""
    # Skill text is stored in GoFastDFS. Keep these legacy columns empty for
    # new and edited rows; old no-file rows remain readable through the
    # compatibility fallback in read_skill_text().
    skill.prompt_template = None
    skill.negative_prompt = ""
    skill.content = None
    skill.enabled = 1
    skill.created_by = skill.created_by or current_user.id
    pending_update = None
    replacement = None
    stored = None
    should_sync_file = (
        content_fields_provided
        and (
            old_content is None
            or new_content != old_content
            or not skill.storage_asset_id
        )
        and bool(new_content)
    )
    if should_sync_file:
        filename = (
            skill.file_name
            or (old_storage_asset.original_filename if old_storage_asset else None)
            or f"{skill.code}.md"
        )
        content_type = mimetypes.guess_type(filename)[0] or "text/plain"
        try:
            if old_storage_asset and not old_storage_read_failed:
                # Keep the StudioAsset row as the business identity while
                # replacing its GoFastDFS version transactionally.
                pending_update = FileService.stage_asset_update(
                    old_storage_asset,
                    content=new_content.encode("utf-8"),
                    filename=filename,
                    content_type=content_type,
                    category=FileService.default_category("FILE", "SKILL"),
                )
            else:
                # If the old object cannot be read, upload a new permanent
                # asset and switch the Skill link after the database commit.
                # This keeps a possibly recoverable old storage object from
                # blocking an otherwise valid Skill edit.
                stored = FileService.upload_bytes(
                    new_content.encode("utf-8"),
                    filename,
                    content_type=content_type,
                    asset_type="FILE",
                    purpose="SKILL",
                    retention_policy=FileService.PERMANENT,
                    created_by=current_user.id,
                    dept_id=department_id,
                    record=False,
                )
                replacement = FileService.create_asset_record(
                    stored,
                    asset_type="FILE",
                    purpose="SKILL",
                    retention_policy=FileService.PERMANENT,
                    created_by=current_user.id,
                    dept_id=department_id,
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
        if pending_update:
            FileService.rollback_asset_update(pending_update)
        elif stored:
            try:
                FileService.delete_storage(stored.storage_path, checksum=stored.checksum)
            except Exception:
                current_app.logger.exception("failed to roll back Skill replacement upload")
        return jsonify(success=False, msg=str(exc)), 400

    if pending_update:
        FileService.finalize_asset_update(pending_update)
    return jsonify(
        success=True,
        msg="Skill 已保存",
        data=_skill_dict(skill, include_content=True),
    )


@studio_bp.post("/api/skills/upload")
@authorize("studio:skills")
def upload_skill():
    if not _can_manage_skills():
        return _skill_management_denied()
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
    try:
        department_id = _write_department_id(request.form.to_dict())
    except ValueError as exc:
        return jsonify(success=False, msg=str(exc)), 400
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
            dept_id=department_id,
            record=False,
        )
    except Exception as exc:
        return jsonify(success=False, msg=str(exc)), 400

    skill = StudioSkill(
        dept_id=department_id,
        name=name,
        code=_skill_code(name),
        media_type=str(metadata.get("media_type") or "BOTH").upper(),
        version=str(metadata.get("version") or "1.0.0"),
        tags=str(metadata.get("tags") or ""),
        file_name=file.filename,
        file_type=extension.lstrip("."),
        content=None,
        prompt_template=None,
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
            dept_id=department_id,
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
    return jsonify(
        success=True,
        msg="Skill 文件已导入",
        data=_skill_dict(skill, include_content=True),
    )


@studio_bp.delete("/api/skills/<int:skill_id>")
@authorize("studio:skills")
def delete_skill(skill_id):
    if not _can_manage_skills():
        return _skill_management_denied()
    skill = _scoped_skill_query().filter_by(id=skill_id).first()
    if not skill:
        return jsonify(success=False, msg="Skill 不存在"), 404
    skill.enabled = 0
    cleanup_protected = False
    if skill.storage_asset_id:
        stored_asset = getattr(skill, "storage_asset", None)
        if (
            stored_asset
            and stored_asset.status in ("ACTIVE", "DELETE_FAILED")
            and stored_asset.dept_id == skill.dept_id
            and not asset_referenced(stored_asset.id, now=None)
        ):
            FileService.delete_asset(stored_asset)
        elif stored_asset:
            cleanup_protected = True
    db.session.commit()
    return jsonify(
        success=True,
        msg=(
            "Skill 已删除，关联文件仍被其他业务引用，已保留"
            if cleanup_protected
            else "Skill 已删除"
        ),
    )
