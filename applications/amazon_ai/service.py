import datetime
import hashlib
import json
import re
import secrets
import string

from flask import current_app
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from applications.extensions import db
from applications.common.asset_relations import (
    AMAZON_RESULT_ROLES,
    ensure_amazon_asset_links,
    ensure_amazon_dependencies,
    ensure_amazon_sources,
    amazon_task_dependency_rows,
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
from applications.common.storage import FileService, StorageError
from applications.common.skill_storage import read_skill_text
from applications.common.scope import (
    can_access_asset,
    can_access_model,
    can_access_resource,
    can_access_skill,
    is_super_admin_user,
    PROVIDER_OWNER_DEPARTMENT,
    provider_owner_type,
    user_department_id,
)
from applications.models import (
    AmazonAiTask,
    AmazonAiTaskAsset,
    AMAZON_TASK_TITLES,
    StudioAsset,
    StudioModel,
    StudioProvider,
    StudioProduct,
    StudioSetting,
    StudioSkill,
    User,
)
from applications.studio.provider_client import (
    ProviderClient,
    extract_chat_content,
    is_responses_path,
    provider_retry_call,
)
from applications.studio.provider_catalog import model_spec_for
from applications.amazon_ai.file_text import read_assets_text
from applications.amazon_ai.skill_catalog import (
    AMAZON_BUILTIN_SKILL_CODES,
    TASK_SKILL_CODES,
)


AMAZON_GLOBAL_CHAT_MODEL_SETTING_KEY = "global_chat_model_id"
# Kept as a compatibility constant for older callers. Amazon AI no longer
# restricts execution to this one model code; the department setting selects
# any enabled CHAT model with a configured provider key.
AMAZON_GLOBAL_CHAT_MODEL_CODE = "gpt-5.4"
AMAZON_TASK_CODE_ALPHABET = string.ascii_letters + string.digits
AMAZON_RESULT_ASSET_PURPOSE = "AMAZON_RESULT"
AMAZON_RESULT_FILENAME = "amazon-ai-result.txt"
AMAZON_CORE_SELLING_POINT_TASK_TYPES = frozenset(
    {
        "DIFFERENTIATION_GENERATE",
        "LISTING_GENERATE",
    }
)


class AmazonAiModelError(RuntimeError):
    """Raised when the currently configured global model cannot run Amazon AI."""

    def __init__(self, message, code="AMAZON_GLOBAL_MODEL_INVALID"):
        super().__init__(message)
        self.code = code


def _json(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


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


def _mark_terminal(task, now=None):
    """Apply the shared temporary retention policy to an Amazon task."""

    now = now or datetime.datetime.now()
    task.retention_policy = FileService.TEMPORARY
    task.expires_at = now + datetime.timedelta(
        days=_temporary_retention_days()
    )
    task.finished_at = task.finished_at or now
    return task


def _discard_uploaded_assets(assets):
    """Remove result files uploaded before a competing state transition won."""

    for asset in assets or ():
        if not asset or not getattr(asset, "storage_path", None):
            continue
        path = str(asset.storage_path or asset.public_url or "").strip()
        if not path:
            continue
        checksum = getattr(asset, "checksum", None)
        try:
            deleted = FileService.delete_storage(path, checksum=checksum)
            if deleted is False:
                raise StorageError("GoFastDFS 返回删除失败")
        except Exception:
            try:
                FileService._record_failed_cleanup(
                    source_asset=asset,
                    storage_path=path,
                    public_url=getattr(asset, "public_url", None),
                    original_filename=getattr(
                        asset,
                        "original_filename",
                        None,
                    ),
                    content_type=getattr(asset, "content_type", None),
                    file_size=getattr(asset, "file_size", None),
                    checksum=checksum,
                    error_message="Amazon AI 任务结果清理失败",
                )
            except Exception:
                current_app.logger.exception(
                    "failed to record discarded Amazon result path=%s",
                    path,
                )
            current_app.logger.exception(
                "failed to discard Amazon result path=%s",
                path,
            )


def _asset_snapshot(asset, role):
    """Keep the GoFastDFS identity needed by task reads and cleanup."""

    filename = str(asset.original_filename or "").strip()
    return {
        "asset_id": asset.id,
        "role": role,
        "url": str(asset.public_url or "").strip(),
        "public_url": str(asset.public_url or "").strip(),
        "download_url": (
            FileService.download_url(asset, filename)
            if asset.public_url
            else ""
        ),
        "storage_path": str(asset.storage_path or "").strip(),
        "filename": filename,
        "original_filename": filename,
        "content_type": str(asset.content_type or "").strip(),
        "file_size": asset.file_size or 0,
        "checksum": str(asset.checksum or "").strip() or None,
        "purpose": str(asset.purpose or "").strip(),
        "status": str(asset.status or "").strip(),
        "retention_policy": str(asset.retention_policy or "").strip(),
        "uploaded_at": (
            asset.created_at.isoformat() if asset.created_at else ""
        ),
        "expires_at": (
            asset.expires_at.isoformat() if asset.expires_at else ""
        ),
    }


def _task_file_refs(task):
    refs = _json(getattr(task, "file_refs_json", None), {}) or {}
    if not isinstance(refs, dict):
        refs = {}
    refs.setdefault("inputs", [])
    refs.setdefault("results", [])
    return refs


def _unique_asset_ids(values):
    result = []
    for value in values or []:
        try:
            asset_id = int(value)
        except (TypeError, ValueError):
            continue
        if asset_id > 0 and asset_id not in result:
            result.append(asset_id)
    return result


def _sync_task_file_refs(task, input_asset_ids=None, result_asset_ids=None):
    """Snapshot task files into the unified task row."""

    refs = _task_file_refs(task)
    if input_asset_ids is not None:
        ids = _unique_asset_ids(input_asset_ids)
        task.input_asset_ids_json = json.dumps(
            ids,
            ensure_ascii=False,
        )
        asset_query = StudioAsset.query.filter(StudioAsset.id.in_(ids))
        if task.dept_id is not None:
            asset_query = asset_query.filter(
                StudioAsset.dept_id == task.dept_id
            )
        assets = asset_query.all() if ids else []
        by_id = {asset.id: asset for asset in assets}
        refs["inputs"] = [
            _asset_snapshot(by_id[asset_id], "input")
            for asset_id in ids
            if asset_id in by_id
        ]
        ensure_amazon_asset_links(
            task.id,
            [by_id[asset_id] for asset_id in ids if asset_id in by_id],
            "INPUT",
        )

    if result_asset_ids is not None:
        ids = _unique_asset_ids(result_asset_ids)
        asset_query = StudioAsset.query.filter(StudioAsset.id.in_(ids))
        if task.dept_id is not None:
            asset_query = asset_query.filter(
                StudioAsset.dept_id == task.dept_id
            )
        assets = asset_query.all() if ids else []
        by_id = {asset.id: asset for asset in assets}
        existing = [
            item
            for item in refs.get("results", [])
            if isinstance(item, dict)
        ]
        existing_by_id = {
            int(item["asset_id"]): item
            for item in existing
            if str(item.get("asset_id") or "").isdigit()
        }
        for asset_id in ids:
            if asset_id in by_id:
                existing_by_id[asset_id] = _asset_snapshot(
                    by_id[asset_id],
                    "result",
                )
        refs["results"] = list(existing_by_id.values())
        ensure_amazon_asset_links(
            task.id,
            [by_id[asset_id] for asset_id in ids if asset_id in by_id],
            "RESULT",
        )
        task.output_asset_id = ids[0] if ids else None
        if ids:
            output_asset = by_id.get(ids[0])
            if output_asset:
                task.output_url = output_asset.public_url
                task.output_filename = output_asset.original_filename
                task.output_checksum = output_asset.checksum
                task.output_expires_at = output_asset.expires_at

    refs["updated_at"] = datetime.datetime.now().isoformat()
    task.file_refs_json = json.dumps(
        refs,
        ensure_ascii=False,
        default=str,
    )
    task.source_urls_json = task.source_urls_json or "[]"
    task.source_identifiers_json = task.source_identifiers_json or "[]"
    task.source_task_codes_json = task.source_task_codes_json or "[]"

    expiries = []
    for group in ("inputs", "results"):
        for item in refs.get(group, []):
            value = str(item.get("expires_at") or "").strip()
            if not value:
                continue
            try:
                expiries.append(datetime.datetime.fromisoformat(value))
            except ValueError:
                continue
    if task.retention_policy in (
        FileService.TEMPORARY,
        FileService.TTL_7D,
    ):
        task.expires_at = min(expiries) if expiries else (
            (task.created_at or datetime.datetime.now())
            + datetime.timedelta(
                days=int(
                    current_app.config.get(
                        "STUDIO_TEMPORARY_RETENTION_DAYS"
                    )
                    or current_app.config.get("STUDIO_ASSET_TTL_DAYS")
                    or 30
                )
            )
        )
        task.storage_cleanup_status = (
            "ACTIVE" if expiries or refs["inputs"] or refs["results"] else "NONE"
        )


def _product_context(product, core_selling_points_only=False):
    if not product:
        return ""
    if core_selling_points_only:
        core_selling_points = str(
            getattr(product, "core_selling_points", "") or ""
        ).strip()
        return (
            "核心卖点：" + core_selling_points
            if core_selling_points
            else ""
        )
    fields = (
        ("产品名称", product.name),
        ("产品编码", product.code),
        ("品牌", product.brand),
        ("产品资料", product.description),
        ("核心卖点", product.core_selling_points),
        ("Product Profile", product.product_profile),
        ("产品记忆", product.product_memory),
        ("生成规则", product.generation_rules),
        ("禁止修改规则", product.forbidden_rules),
    )
    return "\n".join(
        f"{label}：{str(value).strip()}"
        for label, value in fields
        if str(value or "").strip()
    )


TASK_OUTPUT_INSTRUCTIONS = {
    "COMPETITOR_ANALYZE": (
        "必须按照当前竞品分析 Skill 的完整中文报告结构输出。"
        "所有不可见或未提供的页面内容标记为信息缺失，不能编造。"
    ),
    "KEYWORD_ANALYZE": (
        "当前是 Listing 创作前的关键词数据分析阶段，不是最终文案生成阶段。"
        "请严格使用 Listing Skill 中的关键词来源优先级、归属清洗、"
        "Product Relevance、Search Intent、Search Volume、Conversion Intent、"
        "Competitor Coverage、Keyword Map 和语义地图规则，读取上传的西柚、"
        "卖家精灵、Helium10 或其他反查报告。输出可供后续 Listing 任务引用的"
        "结构化关键词证据、字段解释、关键词分类、优先级、归属关系、"
        "不应使用的词及原因。不要生成 Item Name、Item Highlights、Description "
        "或 QA，不要虚构搜索量、排名、竞争度或关键词归属。"
    ),
    "REVIEW_ANALYZE": (
        "当前是 Listing 创作前的 Review 证据分析阶段，不是最终轻差异化方案阶段。"
        "请严格使用轻差异化 Skill 的 Review 规则：多个 ASIN 先分组，重点提取 "
        "1-3 星评论，合并同义问题并保留样本数量、比例、评分和日期依据；"
        "同时记录可用于购买疑虑和 QA 的正负面信息。输出结构化 Review 证据和"
        "可供后续任务引用的洞察，不要把 4-5 星评论写成改进痛点，不要把样本"
        "结论写成全量市场事实，不要在这一阶段输出现货微改、配件搭配或 Listing 成稿。"
    ),
    "DIFFERENTIATION_GENERATE": (
        "必须严格只输出：高转化轻差异化方案、现货微改、配件搭配、"
        "低成本升级方案。不要输出 Listing 成稿或广告方案。"
    ),
    "BASIC_INFO_CORRECT": (
        "这是人工修正结果保存任务，不需要调用模型。"
    ),
    "LISTING_GENERATE": (
        "必须按照 Listing 创作 Skill 的 Markdown 结构输出。"
        "最终 QA 数量必须正好为 20。不要返回 JSON 代码围栏。"
    ),
    "LISTING_AUDIT": (
        "必须只返回一个 JSON 对象，字段为 score、issues、suggestions、summary。"
        "不要返回 Markdown 代码围栏。"
    ),
}


def _split_response_sections(content, max_section_bytes=24000):
    """Split a Markdown response into copyable UI sections without losing raw text."""

    text = str(content or "").strip()
    if not text:
        return []
    lines = text.splitlines()
    sections = []
    current_title = "完整结果"
    current_lines = []
    heading_pattern = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")

    def flush():
        nonlocal current_lines, current_title
        value = "\n".join(current_lines).strip()
        if not value:
            return
        encoded = value.encode("utf-8")
        if len(encoded) <= max_section_bytes:
            sections.append({"title": current_title, "content": value})
            return
        start = 0
        while start < len(encoded):
            chunk = encoded[start : start + max_section_bytes]
            chunk_text = chunk.decode("utf-8", errors="ignore").strip()
            if chunk_text:
                suffix = f" ({len(sections) + 1})"
                sections.append(
                    {
                        "title": current_title + suffix,
                        "content": chunk_text,
                    }
                )
            start += max_section_bytes

    for line in lines:
        match = heading_pattern.match(line)
        if match:
            flush()
            current_title = match.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    flush()
    return sections or [{"title": "完整结果", "content": text}]


def normalize_result_filename(filename):
    """Normalize an operator-provided TXT name without losing Chinese text."""

    value = str(filename or "").strip()
    if value.lower().endswith(".txt"):
        value = value[:-4].rstrip()
    value = value.rstrip(". ")
    if not value:
        raise ValueError("基础信息修正文件未命名，请输入文件名")
    if len(value) > 180:
        raise ValueError("基础信息修正文件名不能超过 180 个字符")
    if value in {".", ".."} or any(
        ord(char) < 32 or char in '/\\<>:"|?*'
        for char in value
    ):
        raise ValueError(
            "文件名只能包含中英文、数字、空格、短横线、下划线、括号或点"
        )
    return value + ".txt"


def _result_filename(task, filename=None):
    if filename:
        return normalize_result_filename(filename)
    stored_filename = str(
        getattr(task, "output_filename", None) or ""
    ).strip()
    if stored_filename:
        return normalize_result_filename(stored_filename)
    if getattr(task, "task_type", "") == "BASIC_INFO_CORRECT":
        existing_refs = _json(
            getattr(task, "result_refs_json", None),
            {},
        ) or {}
        existing_filename = str(
            existing_refs.get("response_filename") or ""
        ).strip()
        if existing_filename:
            return normalize_result_filename(existing_filename)
    title = str(getattr(task, "title", None) or "").strip()
    if title and title not in AMAZON_TASK_TITLES.values():
        return normalize_result_filename(title)
    return datetime.datetime.now().strftime("%Y-%m-%d-%H-%M") + ".txt"


def _persist_text_result(task, content, filename=None):
    """Upload the complete result TXT and keep only its storage metadata."""

    refs = _json(task.result_refs_json, {}) or {}
    refs["response_filename"] = _result_filename(task, filename)
    stored = FileService.upload_bytes(
        str(content or "").encode("utf-8"),
        refs["response_filename"],
        content_type="text/plain; charset=utf-8",
        asset_type="FILE",
        purpose=AMAZON_RESULT_ASSET_PURPOSE,
        retention_policy=FileService.TEMPORARY,
        created_by=task.user_id,
        dept_id=task.dept_id,
        record=False,
    )
    asset = FileService.create_asset_record(
        stored,
        asset_type="FILE",
        purpose=AMAZON_RESULT_ASSET_PURPOSE,
        retention_policy=FileService.TEMPORARY,
        created_by=task.user_id,
        dept_id=task.dept_id,
    )
    asset._storage_uploaded_in_operation = True
    try:
        db.session.add(asset)
        db.session.flush()
        _sync_task_file_refs(
            task,
            result_asset_ids=[asset.id],
        )
        task.output_asset_id = asset.id
        task.output_url = asset.public_url
        task.output_filename = asset.original_filename
        task.output_checksum = asset.checksum
        task.output_expires_at = asset.expires_at
        refs.update(
            {
                "response_asset_id": asset.id,
                "response_download_url": FileService.download_url(asset),
                "response_expires_at": (
                    asset.expires_at.isoformat() if asset.expires_at else ""
                ),
                "response_checksum": asset.checksum or "",
            }
        )
        task.result_refs_json = json.dumps(
            refs,
            ensure_ascii=False,
            default=str,
        )
    except Exception:
        db.session.rollback()
        _discard_uploaded_assets([asset])
        raise
    return asset


def _loaded_task_asset(task, asset_id):
    try:
        asset_id = int(asset_id)
    except (TypeError, ValueError):
        return None
    return next(
        (
            link.asset
            for link in (getattr(task, "asset_links", ()) or ())
            if link.asset and int(link.asset.id) == asset_id
        ),
        None,
    )


def read_task_result_text(task, maximum_size=None, user=None):
    """Read a task's complete result TXT through the shared FileService."""

    refs = _json(getattr(task, "result_refs_json", None), {}) or {}
    filename = (
        str(getattr(task, "output_filename", None) or "").strip()
        or str(refs.get("response_filename") or "").strip()
        or None
    )
    candidates = []
    candidate_keys = set()

    def add_candidate(value, candidate_filename=None):
        if isinstance(value, StudioAsset):
            key = str(
                value.public_url
                or value.storage_path
                or ""
            ).strip()
        else:
            key = str(value or "").strip()
        if not key or key in candidate_keys:
            return
        candidate_keys.add(key)
        candidates.append((value, candidate_filename))

    output_asset_id = getattr(task, "output_asset_id", None)
    if output_asset_id:
        asset = _loaded_task_asset(task, output_asset_id)
        if asset is None:
            asset = StudioAsset.query.filter_by(
                id=int(output_asset_id),
                dept_id=task.dept_id,
            ).first()
        if (
            asset
            and asset.status == "ACTIVE"
            and can_access_asset(user, asset)
        ):
            add_candidate(asset, filename)

    file_refs = _task_file_refs(task)
    for item in file_refs.get("results") or []:
        if not isinstance(item, dict):
            continue
        asset_id = item.get("asset_id")
        url = str(
            item.get("public_url")
            or item.get("url")
            or item.get("storage_path")
            or ""
        ).strip()
        candidate_filename = (
            filename
            or str(
                item.get("original_filename")
                or item.get("filename")
                or ""
            ).strip()
            or None
        )
        if asset_id:
            try:
                asset = _loaded_task_asset(task, asset_id)
                if asset is None:
                    asset = StudioAsset.query.filter_by(
                        id=int(asset_id),
                    ).first()
            except (TypeError, ValueError):
                asset = None
            if (
                not asset
                or asset.status != "ACTIVE"
                or not can_access_asset(user, asset)
            ):
                continue
            add_candidate(asset, candidate_filename)
        elif url:
            add_candidate(url, candidate_filename)

    for key in ("response_download_url", "response_url", "output_url"):
        value = str(refs.get(key) or "").strip()
        if value and FileService.is_managed_url(value):
            add_candidate(value, filename)

    last_error = None
    for candidate, candidate_filename in candidates:
        try:
            return FileService.read_text(
                candidate,
                filename=candidate_filename,
                maximum_size=maximum_size,
            )
        except Exception as exc:
            last_error = exc
    if last_error:
        raise StorageError(str(last_error)) from last_error
    raise StorageError("任务没有可读取的 GoFastDFS 结果文件")


def _resolve_source_tasks(task, source_task_codes, user=None):
    """Resolve source task references once and enforce the caller's scope."""

    codes = []
    for value in source_task_codes or []:
        code = str(value or "").strip()
        if code and code not in codes:
            codes.append(code)
    dependency_rows = amazon_task_dependency_rows(task.id)
    dependency_ids = [
        int(row.source_task_id)
        for row in dependency_rows
        if row.source_task_id
    ]

    query = AmazonAiTask.query.filter(AmazonAiTask.status == "SUCCEEDED")
    if dependency_ids:
        query = query.filter(AmazonAiTask.id.in_(dependency_ids))
    elif codes:
        query = query.filter(AmazonAiTask.task_code.in_(codes))
    else:
        return [], []
    rows = (
        query
        .options(
            selectinload(AmazonAiTask.asset_links).joinedload(
                AmazonAiTaskAsset.asset
            )
        )
        .order_by(AmazonAiTask.created_at.asc())
        .all()
    )
    if dependency_ids and not codes:
        codes = [
            row.task_code
            for relation in dependency_rows
            for row in rows
            if row.id == relation.source_task_id
        ]
    by_code = {
        row.task_code: row
        for row in rows
        if can_access_resource(user, row)
        and (
            task.dept_id is None
            or row.dept_id == task.dept_id
        )
    }
    missing = [code for code in codes if code not in by_code]
    if missing:
        raise ValueError(
            "所选分析任务不存在、未成功或不属于当前部门："
            + ", ".join(missing)
        )
    return codes, [by_code[code] for code in codes]


def _source_result_assets(rows, user=None):
    """Batch-load normalized source result assets for Responses input_file."""

    rows = list(rows or ())
    task_ids = [int(row.id) for row in rows if getattr(row, "id", None)]
    if not task_ids:
        return [], set()

    links = (
        AmazonAiTaskAsset.query
        .filter(
            AmazonAiTaskAsset.task_id.in_(task_ids),
            AmazonAiTaskAsset.role.in_(list(AMAZON_RESULT_ROLES)),
        )
        .options(joinedload(AmazonAiTaskAsset.asset))
        .order_by(
            AmazonAiTaskAsset.task_id.asc(),
            AmazonAiTaskAsset.sort.asc(),
            AmazonAiTaskAsset.id.asc(),
        )
        .all()
    )
    assets_by_task = {}
    for link in links:
        asset = link.asset
        if (
            asset
            and _active_asset_url(asset)
            and can_access_asset(user, asset)
        ):
            assets_by_task.setdefault(int(link.task_id), []).append(asset)

    # Old rows may not have a normalized relation yet. Derive their result
    # IDs and resolve them with one batched asset query instead of one query
    # per source task.
    legacy_ids_by_task = {}
    for row in rows:
        task_id = int(row.id)
        if assets_by_task.get(task_id):
            continue
        ids = []
        refs = _task_file_refs(row)
        for item in refs.get("results") or []:
            if isinstance(item, dict):
                ids.extend([item.get("asset_id")])
        result_refs = _json(row.result_refs_json, {}) or {}
        for key in (
            "response_asset_id",
            "response_asset_ids",
            "result_asset_id",
            "result_asset_ids",
            "output_asset_id",
            "output_asset_ids",
        ):
            value = result_refs.get(key)
            ids.extend(value if isinstance(value, list) else [value])
        ids.append(row.output_asset_id)
        ids = _unique_asset_ids(ids)
        if ids:
            legacy_ids_by_task[task_id] = ids

    all_legacy_ids = _unique_asset_ids(
        asset_id
        for values in legacy_ids_by_task.values()
        for asset_id in values
    )
    if all_legacy_ids:
        legacy_assets = StudioAsset.query.filter(
            StudioAsset.id.in_(all_legacy_ids),
        ).all()
        by_id = {
            int(asset.id): asset
            for asset in legacy_assets
            if _active_asset_url(asset) and can_access_asset(user, asset)
        }
        for task_id, asset_ids in legacy_ids_by_task.items():
            if not assets_by_task.get(task_id):
                assets_by_task[task_id] = [
                    by_id[asset_id]
                    for asset_id in asset_ids
                    if asset_id in by_id
                ]

    result = []
    covered_task_ids = set()
    for row in rows:
        assets = assets_by_task.get(int(row.id), [])
        if assets:
            covered_task_ids.add(int(row.id))
            result.extend(assets)
    return result, covered_task_ids


def _source_tasks_context(
    task,
    source_task_codes,
    user=None,
    resolved_rows=None,
):
    """Resolve source tasks into one bounded fallback text block."""

    if resolved_rows is None:
        codes, rows = _resolve_source_tasks(
            task,
            source_task_codes,
            user=user,
        )
    else:
        codes, rows = resolved_rows

    parts = []
    rows_by_code = {
        row.task_code: row
        for row in rows
        if getattr(row, "task_code", None)
    }
    for code in codes:
        row = rows_by_code[code]
        content = str(
            read_task_result_text(row, user=user) or ""
        ).strip()
        if not content:
            raise ValueError(f"分析任务 {code} 没有可组合的文本结果")
        parts.append(
            f"===== 来源任务 {row.id} | "
            f"{row.task_type} | {_result_filename(row)} =====\n"
            + content
        )
    maximum = int(
        current_app.config.get("AMAZON_AI_MAX_COMBINED_CONTEXT_BYTES")
        or 280000
    )
    return _limit_utf8("\n\n".join(parts), maximum)


def _limit_utf8(value, maximum):
    encoded = str(value or "").encode("utf-8")
    if len(encoded) <= maximum:
        return str(value or "")
    return encoded[:maximum].decode("utf-8", errors="ignore").rstrip() + (
        "\n\n[组合上下文已按系统上限截断]"
    )


def _provider_snapshot(provider, api_key=None):
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


def _active_asset_url(asset):
    if not asset or asset.status != "ACTIVE":
        return ""
    if asset.expires_at and asset.expires_at <= datetime.datetime.now():
        return ""
    return str(asset.public_url or "").strip()


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


def _skill_execution_snapshot(skill, file_url="", prompt=""):
    if not skill:
        return None
    return SkillExecutionContext(
        id=getattr(skill, "id", None),
        name=str(getattr(skill, "name", "") or ""),
        prompt=str(prompt or ""),
        file_url=str(file_url or ""),
    )


def _product_execution_snapshot(product, context=""):
    if not product:
        return None
    return ProductExecutionContext(
        id=getattr(product, "id", None),
        code=str(getattr(product, "code", "") or ""),
        name=str(getattr(product, "name", "") or ""),
        context=str(context or ""),
    )


def _skill_file_url(skill, user=None):
    """Return the permanent GoFastDFS URL for a Skill when available."""

    if not skill or not skill.storage_asset_id:
        return ""
    builtin = getattr(skill, "code", None) in AMAZON_BUILTIN_SKILL_CODES
    if not can_access_skill(
        user,
        skill,
        builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
    ):
        return ""
    asset = getattr(skill, "storage_asset", None)
    if asset is None:
        asset = StudioAsset.query.filter_by(
            id=skill.storage_asset_id,
            purpose="SKILL",
            status="ACTIVE",
        ).first()
    if not can_access_asset(user, asset, allow_system=builtin):
        return ""
    return _active_asset_url(asset)


def _input_assets(asset_ids, department_id, user=None):
    """Resolve Amazon input files in their caller-provided order."""

    ids = []
    for value in asset_ids or []:
        try:
            asset_id = int(value)
        except (TypeError, ValueError):
            continue
        if asset_id not in ids:
            ids.append(asset_id)
    if not ids:
        return []
    filters = [
        StudioAsset.id.in_(ids),
        StudioAsset.purpose == "AMAZON_INPUT",
        StudioAsset.status == "ACTIVE",
    ]
    if department_id is not None:
        filters.append(StudioAsset.dept_id == department_id)
    assets = StudioAsset.query.filter(*filters).all()
    by_id = {
        asset.id: asset
        for asset in assets
        if _active_asset_url(asset) and can_access_asset(user, asset)
    }
    missing = [asset_id for asset_id in ids if asset_id not in by_id]
    if missing:
        raise ValueError(
            "输入文件不存在、已过期或不属于当前部门："
            + ", ".join(str(item) for item in missing)
        )
    return [by_id[asset_id] for asset_id in ids]


def _contains_url(value):
    return bool(re.search(r"https?://[^\s<>\"]+", str(value or ""), re.I))


def _build_responses_body(
    model,
    skill,
    input_assets,
    user_prompt,
    strategy_skill=None,
    web_search=None,
    user=None,
    source_assets=None,
    skill_text=None,
    strategy_text=None,
):
    """Build a native Responses request with Skills and file attachments."""

    content = []
    skill_url = _skill_file_url(skill, user=user)
    if skill_url:
        content.append({"type": "input_file", "file_url": skill_url})
    elif skill:
        if skill_text is None:
            skill_text = read_skill_text(
                skill,
                user=user,
                builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
            )
        skill_text = str(skill_text or "").strip()
        if skill_text:
            content.append(
                {
                    "type": "input_text",
                    "text": "以下是本任务选择的 Skill 配置：\n" + skill_text,
                }
            )

    for asset in input_assets:
        asset_url = _active_asset_url(asset)
        if asset_url:
            content.append({"type": "input_file", "file_url": asset_url})

    for asset in source_assets or ():
        asset_url = _active_asset_url(asset)
        if asset_url:
            content.append({"type": "input_file", "file_url": asset_url})

    if strategy_skill and strategy_skill.id != getattr(skill, "id", None):
        if strategy_text is None:
            strategy_text = read_skill_text(
                strategy_skill,
                user=user,
                builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
            )
        strategy_text = str(strategy_text or "").strip()
        if strategy_text:
            content.append(
                {
                    "type": "input_text",
                    "text": "以下是策略层 Skill 的补充规则：\n" + strategy_text,
                }
            )

    content.append({"type": "input_text", "text": str(user_prompt or "").strip()})
    body = {
        "model": model.model_code,
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "max_output_tokens": int(
            current_app.config.get("AMAZON_AI_MAX_OUTPUT_TOKENS")
            or 128000
        ),
    }
    if web_search is None:
        use_web_search = _contains_url(user_prompt)
    else:
        use_web_search = bool(web_search)
    body["tools"] = [{"type": "web_search"}] if use_web_search else []
    return body


def _model_snapshot(model):
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
            (spec.generation_path if spec else None)
            or model.generation_path
            or getattr(model.provider, "generation_path", None)
            or "/v1/chat/completions"
        ),
        result_path=None,
        provider_id=getattr(model, "provider_id", None),
    )


def _new_task_code():
    for _ in range(50):
        value = "AMZ-" + "".join(
            secrets.choice(AMAZON_TASK_CODE_ALPHABET)
            for _ in range(12)
        )
        if not AmazonAiTask.query.filter_by(task_code=value).first():
            return value
    raise RuntimeError("无法生成唯一的 Amazon AI 任务编号")


def _current_department_id(user=None):
    user = user or (
        current_user
        if getattr(current_user, "is_authenticated", False)
        else None
    )
    return user_department_id(user)


def _normalize_provider_owner_type(value):
    """Normalize legacy ownership input to the only supported scope.

    Older clients stored ``SUPER_ADMIN`` in task metadata. That value no
    longer represents a virtual provider scope: admin is attached to the real
    ``总项目`` department, so all new and replayed requests use department
    ownership.
    """

    del value
    return PROVIDER_OWNER_DEPARTMENT


def _resolve_model_scope(department_id=None, owner_type=None, user=None):
    """Resolve model-setting scope from trusted identity and optional admin selector."""

    user = user or (
        current_user
        if getattr(current_user, "is_authenticated", False)
        else None
    )
    del owner_type
    if user and not is_super_admin_user(user):
        return PROVIDER_OWNER_DEPARTMENT, user_department_id(user)
    if department_id not in (None, ""):
        try:
            return PROVIDER_OWNER_DEPARTMENT, int(department_id)
        except (TypeError, ValueError):
            return None, None
    if user:
        return PROVIDER_OWNER_DEPARTMENT, user_department_id(user)
    # Keep pure service helpers usable by bootstrap/tests that do not have a
    # Flask-Login identity. The authenticated request paths always resolve a
    # concrete scope before a model is used.
    return None, None


def _setting_department_id(owner_type, department_id):
    del owner_type
    return department_id


def global_chat_model_state(department_id=None, owner_type=None, user=None):
    """Return the exact model selected for one department or admin scope."""

    owner_type, department_id = _resolve_model_scope(
        department_id,
        owner_type,
        user=user,
    )

    setting = StudioSetting.query.filter_by(
        setting_key=AMAZON_GLOBAL_CHAT_MODEL_SETTING_KEY,
        dept_id=_setting_department_id(owner_type, department_id),
    ).first()
    selected_id = None
    try:
        selected_id = int(setting.setting_value) if setting else None
    except (TypeError, ValueError):
        selected_id = None

    model_query = None
    if selected_id:
        filters = [
            StudioModel.id == selected_id,
            StudioModel.media_type == "CHAT",
            StudioProvider.dept_id == department_id,
        ]
        model_query = StudioModel.query.join(StudioProvider).filter(*filters)
    model = model_query.first() if model_query is not None else None
    enabled = bool(
        model
        and model.enabled == 1
        and model.provider
        and model.provider.enabled == 1
    )
    # The model code is intentionally not hard-coded. Different departments
    # may select different compatible relay models, including Responses models.
    code_matches = bool(model)
    has_key = bool(model and model.provider and str(model.provider.api_key or "").strip())
    return {
        "configured": bool(model),
        "enabled": enabled,
        "code_matches": code_matches,
        "has_api_key": has_key,
        "allowed": bool(enabled and has_key),
        "required_model_code": None,
        "owner_type": owner_type,
        "dept_id": department_id,
        "model": (
            {
                "id": model.id,
                "name": model.name,
                "model_code": model.model_code,
                "provider_id": model.provider_id,
                "provider_name": model.provider.name if model.provider else "",
                "dept_id": (
                    getattr(model.provider, "dept_id", None)
                    if model.provider
                    else None
                ),
                "owner_type": (
                    provider_owner_type(model.provider)
                    if model.provider
                    else None
                ),
            }
            if model
            else None
        ),
    }


class AmazonAiService:
    """Amazon AI orchestration on top of the existing Studio provider stack."""

    @staticmethod
    def _current_actor():
        return (
            current_user
            if getattr(current_user, "is_authenticated", False)
            else None
        )

    @classmethod
    def _accessible_task(cls, task_id):
        task = AmazonAiTask.query.get(task_id)
        actor = cls._current_actor()
        if not task:
            raise ValueError("Amazon AI 任务不存在")
        if not actor or not can_access_resource(actor, task):
            raise ValueError("无权访问该 Amazon AI 任务")
        return task, actor

    @staticmethod
    def _locked_task(task_id):
        """Lock one task row for a short terminal state transition."""

        return (
            AmazonAiTask.query
            .filter(AmazonAiTask.id == int(task_id))
            .with_for_update()
            .first()
        )

    @classmethod
    def _claim_execution_task(cls, task_id):
        """Atomically claim a task before preparing or calling the provider."""

        now = datetime.datetime.now()
        claimed = (
            AmazonAiTask.query
            .filter(
                AmazonAiTask.id == int(task_id),
                AmazonAiTask.status.in_(("PENDING", "FAILED")),
            )
            .update(
                {
                    AmazonAiTask.status: "RUNNING",
                    AmazonAiTask.progress: 5,
                    AmazonAiTask.started_at: now,
                    AmazonAiTask.heartbeat_at: now,
                    AmazonAiTask.finished_at: None,
                    AmazonAiTask.error_code: None,
                    AmazonAiTask.error_message: None,
                },
                synchronize_session=False,
            )
        )
        if claimed:
            db.session.commit()
            db.session.expire_all()
            task = AmazonAiTask.query.get(int(task_id))
            if task:
                return task
        else:
            db.session.rollback()

        db.session.expire_all()
        current = AmazonAiTask.query.get(int(task_id))
        if not current:
            raise ValueError("Amazon AI 任务不存在")
        if current.status == "RUNNING":
            raise ValueError("任务正在执行，请勿重复提交")
        raise ValueError("任务当前状态不允许执行")

    def require_global_model(
        self,
        department_id=None,
        owner_type=None,
        user=None,
    ):
        state = global_chat_model_state(
            department_id,
            owner_type=owner_type,
            user=user,
        )
        if not state["configured"]:
            raise AmazonAiModelError(
                "Amazon AI 已禁止执行：当前没有配置全局语言模型。"
                "请先在模型供应商页面选择一个启用的 CHAT 语言模型。"
            )
        if not state["enabled"]:
            raise AmazonAiModelError(
                "Amazon AI 已禁止执行：全局语言模型或其供应商未启用。"
            )
        if not state["has_api_key"]:
            raise AmazonAiModelError(
                "Amazon AI 已禁止执行：全局语言模型所属供应商尚未配置 API Key。"
            )

        setting = StudioSetting.query.filter_by(
            setting_key=AMAZON_GLOBAL_CHAT_MODEL_SETTING_KEY,
            dept_id=_setting_department_id(
                state["owner_type"],
                state["dept_id"],
            ),
        ).first()
        model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.id == int(setting.setting_value),
                StudioModel.media_type == "CHAT",
                StudioProvider.dept_id == state["dept_id"],
            )
            .first()
            if setting and setting.setting_value
            else None
        )
        acting_user = user or (
            current_user
            if getattr(current_user, "is_authenticated", False)
            else None
        )
        if not model or not can_access_model(
            acting_user,
            model,
            department_id=state["dept_id"],
            owner_type=state["owner_type"],
        ):
            raise AmazonAiModelError(
                "Amazon AI 已禁止执行：无权使用当前语言模型配置。",
                code="AMAZON_GLOBAL_MODEL_FORBIDDEN",
            )
        return model

    @staticmethod
    def validate_skill(skill_id, department_id=None, user=None):
        if not skill_id:
            return None
        skill_query = StudioSkill.query.filter_by(
            id=int(skill_id),
            enabled=1,
        )
        skill = skill_query.first()
        if skill and not can_access_skill(
            user,
            skill,
            builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
        ):
            skill = None
        if (
            skill
            and department_id is not None
            and skill.code not in AMAZON_BUILTIN_SKILL_CODES
            and skill.dept_id != department_id
        ):
            skill = None
        if not skill:
            raise ValueError("Skill 不存在或未启用")
        return skill

    def create_task(
        self,
        *,
        user_id,
        task_type,
        model_id=None,
        skill_id=None,
        studio_product_id=None,
        input_asset_ids=None,
        source_task_codes=None,
        strategy_skill_id=None,
        target_links=None,
        title=None,
        source_urls=None,
        source_identifiers=None,
        source_key=None,
        output_filename=None,
        task_metadata=None,
        priority=0,
        max_retries=3,
        department_id=None,
        provider_owner_type=None,
    ):
        task_type = str(task_type or "").strip().upper()
        allowed_types = {
            "COMPETITOR_ANALYZE",
            "KEYWORD_ANALYZE",
            "REVIEW_ANALYZE",
            "DIFFERENTIATION_GENERATE",
            "BASIC_INFO_CORRECT",
            "LISTING_GENERATE",
            "LISTING_AUDIT",
        }
        if task_type not in allowed_types:
            raise ValueError("不支持的 Amazon AI 任务类型")

        if getattr(current_user, "is_authenticated", False):
            if current_user.id != user_id:
                raise ValueError("不能代表其他用户创建 Amazon AI 任务")
            user = current_user
        else:
            user = User.query.get(user_id)
        if not user:
            raise ValueError("当前用户不存在")

        owner_type = PROVIDER_OWNER_DEPARTMENT
        if not is_super_admin_user(user):
            department_id = user_department_id(user)
        elif department_id is None:
            department_id = user_department_id(user)

        if department_id is None:
            raise ValueError("请先为当前用户指定部门")

        if studio_product_id:
            product_filters = {
                "id": int(studio_product_id),
                "enabled": 1,
            }
            if department_id is not None:
                product_filters["dept_id"] = department_id
            product = StudioProduct.query.filter_by(**product_filters).first()
            if not product or not can_access_resource(user, product):
                raise ValueError("关联的 Studio 产品不存在或不属于当前部门")
            if (
                task_type in AMAZON_CORE_SELLING_POINT_TASK_TYPES
                and not str(product.core_selling_points or "").strip()
            ):
                raise ValueError(
                    "所选产品尚未维护核心卖点，请先在基础信息修正中保存，"
                    "或到产品中心补充核心卖点"
                )

        if task_type not in {"BASIC_INFO_CORRECT", "LISTING_GENERATE"} and not skill_id:
            raise ValueError("请选择本次使用的 Skill")
        skill = self.validate_skill(
            skill_id,
            department_id,
            user=user,
        )
        if skill and str(skill.media_type or "BOTH").upper() not in (
            "TEXT",
            "BOTH",
        ):
            raise ValueError("当前 Skill 仅适用于图片或视频创作")
        if strategy_skill_id:
            strategy_skill = self.validate_skill(
                strategy_skill_id,
                department_id,
                user=user,
            )
            if (
                strategy_skill
                and str(strategy_skill.media_type or "BOTH").upper()
                not in ("TEXT", "BOTH")
            ):
                raise ValueError("当前策略 Skill 仅适用于图片或视频创作")

        asset_ids = _unique_asset_ids(input_asset_ids)
        input_assets = []
        if asset_ids:
            input_assets = _input_assets(
                asset_ids,
                department_id,
                user=user,
            )

        source_codes = [
            str(item).strip()
            for item in (source_task_codes or [])
            if str(item).strip()
        ]
        source_task_rows = []
        if source_codes:
            source_task_rows = (
                AmazonAiTask.query.filter(
                    AmazonAiTask.task_code.in_(source_codes),
                    AmazonAiTask.status == "SUCCEEDED",
                )
                .all()
            )
            accessible_codes = {
                row.task_code
                for row in source_task_rows
                if can_access_resource(user, row)
                and (
                    department_id is None
                    or row.dept_id == department_id
                )
            }
            if any(code not in accessible_codes for code in source_codes):
                raise ValueError("来源分析任务不存在、未成功或无权访问")

        model = None
        if task_type != "BASIC_INFO_CORRECT":
            # All model-backed Amazon AI work follows the department-level
            # selection in Model Providers. Keep ``model_id`` as a legacy
            # argument for API compatibility, but never let a request body
            # override that single source of truth.
            model = self.require_global_model(
                department_id,
                owner_type=owner_type,
                user=user,
            )

        task_metadata_value = (
            dict(task_metadata)
            if isinstance(task_metadata, dict)
            else {}
        )
        task_metadata_value.setdefault("provider_owner_type", owner_type)

        created_at = datetime.datetime.now()
        task = None
        retention_days = int(
            current_app.config.get("STUDIO_TEMPORARY_RETENTION_DAYS")
            or current_app.config.get("STUDIO_ASSET_TTL_DAYS")
            or 30
        )
        for attempt in range(5):
            candidate = AmazonAiTask(
            task_code=_new_task_code(),
            dept_id=department_id,
            task_type=task_type,
            status="PENDING",
            priority=max(0, int(priority or 0)),
            max_retries=max(0, int(max_retries or 3)),
            user_id=user_id,
            # Store the selected model as a useful creation-time snapshot.
            # Execution resolves the current department selection again.
            model_id=model.id if model else None,
            skill_id=skill.id if skill else None,
            studio_product_id=studio_product_id,
            title=str(
                title
                or AMAZON_TASK_TITLES.get(task_type, task_type)
            )[:180],
            source_key=str(source_key or "").strip()[:120] or None,
            source_urls_json=json.dumps(
                [
                    str(item).strip()
                    for item in (source_urls or [])
                    if str(item).strip()
                ],
                ensure_ascii=False,
            ),
            source_identifiers_json=json.dumps(
                [
                    str(item).strip()
                    for item in (source_identifiers or [])
                    if str(item).strip()
                ],
                ensure_ascii=False,
            ),
            source_task_codes_json=json.dumps(
                [
                    str(item).strip()
                    for item in (source_task_codes or [])
                    if str(item).strip()
                ],
                ensure_ascii=False,
            ),
            input_asset_ids_json=json.dumps(
                asset_ids,
                ensure_ascii=False,
            ),
            task_metadata_json=json.dumps(
                task_metadata_value,
                ensure_ascii=False,
                default=str,
            ),
            output_filename=(
                normalize_result_filename(output_filename)
                if output_filename
                else None
            ),
            input_refs_json=json.dumps(
                {
                    "asset_ids": [
                        int(item) for item in asset_ids
                    ],
                    "source_task_codes": [
                        str(item).strip()
                        for item in (source_task_codes or [])
                        if str(item).strip()
                    ],
                    "strategy_skill_id": (
                        int(strategy_skill_id)
                        if strategy_skill_id
                        else None
                    ),
                },
                ensure_ascii=False,
            ),
            retention_policy=FileService.TEMPORARY,
            expires_at=created_at + datetime.timedelta(days=retention_days),
            storage_cleanup_status="ACTIVE",
            scheduled_at=created_at,
            created_at=created_at,
            )
            db.session.add(candidate)
            try:
                db.session.flush()
            except IntegrityError:
                db.session.rollback()
                if attempt == 4:
                    raise RuntimeError("无法生成唯一的 Amazon AI 任务编号")
                continue
            task = candidate
            break
        if task is None:
            raise RuntimeError("无法创建 Amazon AI 任务")
        ensure_amazon_sources(
            task.id,
            source_urls=source_urls,
            source_identifiers=source_identifiers,
        )
        ensure_amazon_dependencies(
            task.id,
            [row.id for row in source_task_rows],
        )
        ensure_amazon_asset_links(task.id, input_assets, "INPUT")
        _sync_task_file_refs(task, input_asset_ids=asset_ids)
        db.session.commit()
        return task

    def save_manual_result(self, task_id, content, filename=None):
        """Persist an operator-edited result without invoking a model."""

        task, _actor = self._accessible_task(task_id)
        if task.status in ("CANCELLED", "SUCCEEDED"):
            raise ValueError("任务当前状态不允许保存")

        now = datetime.datetime.now()
        task.status = "SUCCEEDED"
        task.progress = 100
        task.started_at = task.started_at or now
        task.heartbeat_at = now
        task.finished_at = now
        task.error_code = None
        task.error_message = None
        _mark_terminal(task, now)
        task.response_digest = _hash(str(content or ""))
        task.result_refs_json = json.dumps(
            {"response_digest": task.response_digest},
            ensure_ascii=False,
        )
        _persist_text_result(
            task,
            str(content or ""),
            filename=filename,
        )
        db.session.commit()
        return task

    def execute_task(
        self,
        task_id,
        context="",
        input_asset_ids=None,
        web_search=None,
    ):
        """Run a text-only Amazon analysis through the configured global model."""

        task, actor = self._accessible_task(task_id)
        if task.task_type == "BASIC_INFO_CORRECT":
            raise ValueError("基础信息修正任务需要通过保存按钮提交人工修正结果")
        # Always resolve the current department-level selection. This keeps
        # every Amazon AI call aligned with the Model Providers page even when
        # a queued task was created before the operator switched models.
        task_metadata = _json(task.task_metadata_json, {}) or {}
        owner_type = _normalize_provider_owner_type(
            task_metadata.get("provider_owner_type")
        )
        task = self._claim_execution_task(task.id)
        task_code = task.task_code
        uploaded_assets = []
        try:
            model = self.require_global_model(
                task.dept_id,
                owner_type=owner_type,
                user=actor,
            )
            task.model_id = model.id
            stored_refs = _json(task.input_refs_json, {}) or {}
            asset_ids = input_asset_ids
            if asset_ids is None or (
                not asset_ids and stored_refs.get("asset_ids")
            ):
                asset_ids = stored_refs.get("asset_ids") or []
            if not asset_ids:
                file_refs = _json(task.file_refs_json, {}) or {}
                snapshot_ids = [
                    item.get("asset_id")
                    for item in (file_refs.get("inputs") or [])
                    if isinstance(item, dict) and item.get("asset_id")
                ]
                asset_ids = _unique_asset_ids(snapshot_ids)
            skill = task.skill
            if skill and not can_access_skill(
                actor,
                skill,
                builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
            ):
                raise ValueError("任务关联的 Skill 不存在、已停用或无权访问")
            if (
                skill
                and task.dept_id is not None
                and skill.code not in AMAZON_BUILTIN_SKILL_CODES
                and skill.dept_id != task.dept_id
            ):
                raise ValueError("任务关联的 Skill 不属于当前部门")
            if task.studio_product and not can_access_resource(
                actor,
                task.studio_product,
            ):
                raise ValueError("任务关联的产品不属于当前数据范围")
            strategy_skill_id = stored_refs.get("strategy_skill_id")
            strategy_skill = None
            if strategy_skill_id:
                strategy_skill = self.validate_skill(
                    strategy_skill_id,
                    task.dept_id,
                    user=actor,
                )
            try:
                skill_prompt = (
                    read_skill_text(
                        skill,
                        user=actor,
                        builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
                    )
                    if skill
                    else ""
                )
                strategy_prompt = (
                    read_skill_text(
                        strategy_skill,
                        user=actor,
                        builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
                    )
                    if strategy_skill
                    else ""
                )
            except StorageError as exc:
                raise ValueError(str(exc)) from exc
            primary_prompt = (
                skill_prompt
                or "你是 Amazon 电商业务分析助手。请基于输入事实输出结构化、可执行的分析。"
            )
            system_prompt = primary_prompt
            if strategy_skill and strategy_skill.id != getattr(skill, "id", None):
                system_prompt += (
                    "\n\n以下是策略层 Skill。它用于提出轻差异化判断，"
                    "但最终输出必须服从主 Skill 的任务类型和输出格式：\n"
                    + strategy_prompt
                )
            user_prompt = (
                f"任务类型：{task.task_type}\n"
                "请只分析当前 Amazon AI 业务，不要执行文件上传，不要调用其他模型。\n"
                f"业务上下文：{str(context or '').strip()}\n"
            )
            core_selling_points_only = (
                task.task_type in AMAZON_CORE_SELLING_POINT_TASK_TYPES
            )
            product_text = _product_context(
                task.studio_product,
                core_selling_points_only=core_selling_points_only,
            )
            if product_text:
                if core_selling_points_only:
                    user_prompt += (
                        "\n以下是所选产品的核心卖点。它是我方产品事实，"
                        "本任务只能引用这部分产品信息，不得自行补充完整产品档案：\n"
                        + product_text
                        + "\n"
                    )
                else:
                    user_prompt += (
                        "\n以下是关联 Studio 产品信息。它是事实约束，"
                        "请保留其中可确认的信息，不要臆造：\n"
                        + product_text
                        + "\n"
                    )
            source_codes = (
                stored_refs.get("source_task_codes")
                or _json(task.source_task_codes_json, [])
                or []
            )
            use_responses = is_responses_path(
                model.generation_path
                or getattr(model.provider, "generation_path", None)
            )
            resolved_source = _resolve_source_tasks(
                task,
                source_codes,
                user=actor,
            )
            resolved_codes, source_rows = resolved_source
            source_assets = []
            covered_source_task_ids = set()
            if use_responses and source_rows:
                source_assets, covered_source_task_ids = _source_result_assets(
                    source_rows,
                    user=actor,
                )
            source_text = ""
            source_row_ids = {
                int(row.id)
                for row in source_rows
                if getattr(row, "id", None)
            }
            if (
                source_rows
                and (
                    not use_responses
                    or covered_source_task_ids != source_row_ids
                )
            ):
                source_text = _source_tasks_context(
                    task,
                    resolved_codes,
                    user=actor,
                    resolved_rows=resolved_source,
                )
            if source_text:
                user_prompt += (
                    "\n以下是操作者选择的已完成分析任务结果。"
                    "请保留来源边界，不要把竞品事实当成我方产品事实：\n"
                    + source_text
                    + "\n"
                )
            elif source_rows and source_assets:
                user_prompt += (
                    "\n以下来源分析任务的完整结果已按独立 input_file "
                    "附件传入。请按文件名区分来源任务，不能混淆不同任务的事实：\n"
                    + "\n".join(
                        f"- {_result_filename(row)}"
                        for row in source_rows
                    )
                    + "\n"
                )
            if task.task_type == "COMPETITOR_ANALYZE":
                if web_search is None:
                    web_search = True
                user_prompt += (
                    "\n竞品网页读取执行要求：\n"
                    "1. 当前请求的第一个 input_file 是本任务选择的完整主 Skill，"
                    "请先完整读取并严格执行其中的规则。\n"
                    "2. 必须使用 web_search 逐条访问用户提供的 Amazon 链接，"
                    "按竞品 A、竞品 B、竞品 C 的顺序分别分析，不得跨 ASIN "
                    "合并事实。\n"
                    "3. 必须按每个竞品分别分析标题、五点、"
                    "产品详情、主图与辅图、A+、评分、评论、QA、售后等 Skill 要求的"
                    "板块。\n"
                    "4. 只有网页真实无法访问或对应板块确实未展示时才写"
                    "“信息缺失”，不得编造数据或把 Skill 中的占位符当成事实。\n"
                )
            output_instruction = TASK_OUTPUT_INSTRUCTIONS.get(task.task_type)
            if output_instruction:
                user_prompt += "\n输出要求：" + output_instruction

            input_assets = _input_assets(
                asset_ids,
                task.dept_id,
                user=actor,
            )
            if use_responses:
                body = _build_responses_body(
                    model,
                    skill,
                    input_assets,
                    user_prompt,
                    strategy_skill=strategy_skill,
                    web_search=web_search,
                    user=actor,
                    source_assets=source_assets,
                    skill_text=skill_prompt,
                    strategy_text=strategy_prompt,
                )
            else:
                file_text = read_assets_text(asset_ids, user=actor)
                if file_text:
                    user_prompt += (
                        "\n以下是系统从 TXT/Excel 转换出的文本：\n"
                        + file_text
                    )
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                body = {
                    "model": model.model_code,
                    "messages": messages,
                    "max_tokens": int(
                        current_app.config.get("AMAZON_AI_MAX_OUTPUT_TOKENS")
                        or 128000
                    ),
                    "temperature": 0.2,
                }
            request_digest = _hash(body)
            provider_snapshot = _provider_snapshot(model.provider)
            model_snapshot = _model_snapshot(model)
            execution_context = ExecutionContext(
                task_id=task.id,
                task_code=task.task_code,
                user_id=task.user_id,
                dept_id=task.dept_id,
                provider=provider_snapshot,
                model=model_snapshot,
                skill=_skill_execution_snapshot(
                    skill,
                    file_url=(
                        _skill_file_url(skill, user=actor)
                        if use_responses
                        else ""
                    ),
                    prompt=skill_prompt,
                ),
                product=_product_execution_snapshot(
                    task.studio_product,
                    context=product_text,
                ),
                input_assets=tuple(
                    _asset_execution_snapshot(asset)
                    for asset in input_assets
                ),
                source_result_urls=tuple(
                    _active_asset_url(asset)
                    for asset in source_assets
                    if _active_asset_url(asset)
                ),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                metadata={
                    "task_type": task.task_type,
                    "web_search": bool(web_search),
                },
            )
            task.request_digest = request_digest
            task.error_code = None
            task.error_message = None
            db.session.commit()
            # Materialize the provider relationship before detaching the ORM
            # graph. The long model request must not retain a DB connection.
            _ = model.provider
            release_db_connection()
            current_app.logger.info(
                "amazon ai request: task_code=%s task_type=%s "
                "model_id=%s model_code=%s request_digest=%s",
                task_code,
                task.task_type,
                model.id,
                model.model_code,
                request_digest,
            )
            client = ProviderClient(execution_context.provider)

            def complete_once():
                response = client.complete(
                    execution_context.model,
                    body,
                )
                content = extract_chat_content(response)
                if not content:
                    raise ValueError("全局语言模型没有返回分析内容")
                return response, content

            response, content = provider_retry_call(
                complete_once,
                operation_name=f"amazon ai {task_code}",
            )
            response_digest = _hash(response)
            task = AmazonAiTask.query.get(task_id)
            if not task or not can_access_resource(actor, task):
                raise ValueError("Amazon AI 任务已不存在或无权访问")
            task.result_refs_json = json.dumps(
                {"response_digest": response_digest},
                ensure_ascii=False,
            )
            result_asset = _persist_text_result(task, content)
            uploaded_assets = (
                [result_asset]
                if getattr(
                    result_asset,
                    "_storage_uploaded_in_operation",
                    False,
                )
                else []
            )

            # The model response and the GoFastDFS upload happen outside the
            # state lock. Re-check RUNNING under a short row lock before
            # making the result durable, so a concurrent cancellation wins
            # cleanly and the newly uploaded object can be discarded.
            locked_task = self._locked_task(task_id)
            if not locked_task or locked_task.status != "RUNNING":
                db.session.rollback()
                _discard_uploaded_assets(uploaded_assets)
                uploaded_assets = []
                current_task = AmazonAiTask.query.get(task_id)
                if current_task and current_task.status == "CANCELLED":
                    raise ValueError("任务已取消，已丢弃模型结果")
                raise ValueError("任务当前状态已改变，已丢弃模型结果")

            locked_task.status = "SUCCEEDED"
            locked_task.progress = 100
            locked_task.response_digest = response_digest
            now = datetime.datetime.now()
            locked_task.finished_at = now
            locked_task.heartbeat_at = now
            _mark_terminal(locked_task, now)
            db.session.commit()
            current_app.logger.info(
                "amazon ai completed: task_code=%s response_digest=%s",
                task_code,
                response_digest,
            )
            return {
                "task": locked_task,
                "content": content,
                "response": response,
                "model": execution_context.model,
            }
        except Exception as exc:
            db.session.rollback()
            _discard_uploaded_assets(uploaded_assets)
            uploaded_assets = []
            task = self._locked_task(task_id)
            if task and task.status == "RUNNING":
                task.status = "FAILED"
                task.error_code = (
                    getattr(exc, "code", None)
                    or "AMAZON_AI_FAILED"
                )
                task.error_message = str(exc)
                now = datetime.datetime.now()
                task.finished_at = now
                task.heartbeat_at = now
                _mark_terminal(task, now)
                db.session.commit()
            else:
                db.session.rollback()
            current_app.logger.exception(
                "amazon ai failed: task_code=%s status_code=%s "
                "request_id=%s error=%s",
                task_code,
                getattr(exc, "status_code", None),
                getattr(exc, "request_id", None),
                str(exc),
            )
            raise
