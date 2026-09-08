"""Domain service for white-background product image refinement."""

import datetime
import io
import math
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import current_app
from PIL import Image, UnidentifiedImageError

from applications.amazon_ai.skill_catalog import (
    AMAZON_BUILTIN_SKILL_CODES,
    WHITE_BACKGROUND_IMAGE_SKILL_CODE,
)
from applications.common.db_session import release_db_connection
from applications.common.scope import (
    can_access_asset,
    can_access_model,
    can_access_skill,
    is_super_admin_user,
    user_department_id,
)
from applications.common.storage import FileService, StorageError
from applications.extensions import db
from applications.models import (
    StudioAsset,
    StudioModel,
    StudioProvider,
    StudioSkill,
    User,
)

from .generation_service import create_generation
from .provider_catalog import provider_catalog_key
from .request_builder import (
    image_dimensions_for_resolution,
    image_size_for_aspect_ratio,
    model_parameter_schema,
    option_values,
)


IMAGE_MAX_DIMENSION = 4096
QUALITY_MAX_DIMENSIONS = {
    "1k": 1024,
    "2k": 2048,
    "4k": 4096,
}
WHITE_BACKGROUND_GRID_LAYOUTS = {
    2: (2, 1, "2宫格"),
    3: (3, 1, "三宫格"),
    4: (2, 2, "4宫格"),
    5: (3, 2, "5宫格"),
    6: (3, 2, "6宫格"),
    7: (3, 3, "7宫格"),
    8: (3, 3, "8宫格"),
    9: (3, 3, "9宫格"),
}
RATIO_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*[:xX]\s*(\d+(?:\.\d+)?)\s*$"
)


def _unique_ids(values):
    result = []
    for value in values or ():
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in result:
            result.append(value)
    return result


def _parse_ratio(value):
    match = RATIO_PATTERN.fullmatch(str(value or ""))
    if not match:
        raise ValueError("图片比例必须是有效的宽高比")
    width = float(match.group(1))
    height = float(match.group(2))
    if not math.isfinite(width) or not math.isfinite(height):
        raise ValueError("图片比例必须是有效的宽高比")
    if width <= 0 or height <= 0:
        raise ValueError("图片比例必须大于 0")
    return width / height


def _fit_dimensions(width, height, max_dimension=IMAGE_MAX_DIMENSION):
    width = max(1, int(width))
    height = max(1, int(height))
    max_dimension = max(1, int(max_dimension))
    longest = max(width, height)
    if longest <= max_dimension:
        return width, height
    scale = max_dimension / float(longest)
    return (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )


def _dimensions_for_ratio(ratio, max_dimension):
    ratio = float(ratio)
    max_dimension = max(1, int(max_dimension))
    if ratio >= 1:
        width = max_dimension
        height = max(1, int(round(max_dimension / ratio)))
    else:
        height = max_dimension
        width = max(1, int(round(max_dimension * ratio)))
    return _fit_dimensions(width, height, max_dimension)


def _ratio_text(width, height):
    width = max(1, int(width))
    height = max(1, int(height))
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _normalise_quality(value, source_max):
    value = str(value or "auto").strip().lower().replace(" ", "")
    if value == "auto":
        # 白底图不再暴露“自动分辨率”。兼容旧客户端时统一按默认
        # 1K 处理，避免同一任务因上传图片尺寸而偷偷改变计费档位。
        return "1k"
    if value in QUALITY_MAX_DIMENSIONS:
        return value
    raise ValueError("图片分辨率只能选择 1K、2K 或 4K")


def _model_options(model, fields):
    values = []
    fields = set(fields)
    for parameter in model_parameter_schema(model):
        if (
            parameter.get("field") not in fields
            and parameter.get("runtime_key") not in fields
        ):
            continue
        for value in option_values(parameter):
            value = str(value or "").strip()
            if value and value.lower() not in {
                item.lower() for item in values
            }:
                values.append(value)
    return values


def _nearest_aspect(value, options):
    if not options:
        return str(value or "1:1").strip() or "1:1"
    target = _parse_ratio(value)
    parsed = []
    for option in options:
        try:
            parsed.append(
                (
                    abs(math.log(_parse_ratio(option) / target)),
                    option,
                )
            )
        except ValueError:
            continue
    if not parsed:
        return options[0]
    return min(parsed, key=lambda item: item[0])[1]


def _resolution_option(model, quality, source_max):
    options = _model_options(model, {"resolution"})
    quality = _normalise_quality(quality, source_max)
    for option in options:
        if str(option).strip().lower().replace(" ", "") == quality:
            return option
    if options:
        return options[0]
    return quality


def _aspect_option(model, ratio_text):
    options = _model_options(model, {"size", "aspect_ratio"})
    return _nearest_aspect(ratio_text, options)


def _read_image_dimensions(asset):
    """Read the actual uploaded image dimensions through FileService."""

    try:
        image_bytes = FileService.read_bytes(
            asset,
            filename=asset.original_filename,
            maximum_size=current_app.config.get(
                "GOFASTDFS_MAX_FILE_SIZE",
                536870912,
            ),
        )
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
    except (StorageError, OSError, UnidentifiedImageError, ValueError) as exc:
        raise ValueError(
            f"参考图片 {asset.original_filename or asset.id} 无法读取有效尺寸"
        ) from exc
    if not width or not height:
        raise ValueError(
            f"参考图片 {asset.original_filename or asset.id} 的尺寸无效"
        )
    return int(width), int(height)


def _target_plan(
    model,
    source_width,
    source_height,
    aspect,
    resolution,
    merge_ratio=None,
):
    """Resolve provider-neutral dimensions and model-schema values."""

    original_width = max(1, int(source_width))
    original_height = max(1, int(source_height))
    source_width, source_height = _fit_dimensions(
        original_width,
        original_height,
    )
    source_max = max(source_width, source_height)
    bounded_source_max = min(source_max, IMAGE_MAX_DIMENSION)
    aspect_text = str(aspect or "auto").strip()
    aspect_is_auto = aspect_text.lower() == "auto"
    source_ratio_text = _ratio_text(original_width, original_height)
    target_ratio_text = (
        str(merge_ratio or "").strip()
        if merge_ratio
        else source_ratio_text
        if aspect_is_auto
        else aspect_text
    )
    target_ratio = _parse_ratio(target_ratio_text)
    quality = _normalise_quality(resolution, source_max)
    # 白底图分辨率只有 1K、2K、4K；“auto”仅作为旧请求的兼容输入，
    # 已在 _normalise_quality 中归一为 1K。
    resolution_is_auto = False
    provider_key = provider_catalog_key(model.provider)

    if (
        not merge_ratio
        and aspect_is_auto
        and resolution_is_auto
    ):
        # Auto/auto means a transparent pass-through of the uploaded canvas.
        # Do not resize it merely because another provider path has a 4K
        # maximum for manually selected quality presets.
        target_width, target_height = original_width, original_height
    elif provider_key == "kuaipao" and not resolution_is_auto:
        try:
            size = image_size_for_aspect_ratio(target_ratio_text)
            target_width, target_height = (
                int(item) for item in size.split("x", 1)
            )
        except ValueError:
            target_width, target_height = _dimensions_for_ratio(
                target_ratio,
                IMAGE_MAX_DIMENSION,
            )
    elif provider_key == "jiekou" and not resolution_is_auto:
        try:
            size = image_dimensions_for_resolution(
                target_ratio_text,
                quality,
            )
            target_width, target_height = (
                int(item) for item in size.split("x", 1)
            )
        except ValueError:
            target_width, target_height = _dimensions_for_ratio(
                target_ratio,
                QUALITY_MAX_DIMENSIONS[quality],
            )
    else:
        target_width, target_height = _dimensions_for_ratio(
            target_ratio,
            bounded_source_max
            if resolution_is_auto
            else QUALITY_MAX_DIMENSIONS[quality],
        )

    if not (
        not merge_ratio
        and aspect_is_auto
        and resolution_is_auto
    ):
        target_width, target_height = _fit_dimensions(
            target_width,
            target_height,
        )
    return {
        "aspect_ratio": _aspect_option(
            model,
            target_ratio_text,
        ),
        "resolution": _resolution_option(
            model,
            quality,
            source_max,
        ),
        "target_dimensions": f"{target_width}x{target_height}",
        "target_aspect_ratio": target_ratio_text,
        "quality": quality,
    }


def _resolve_model(user, model_id):
    try:
        model_id = int(model_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("请选择有效的图片模型") from exc
    model = (
        StudioModel.query.join(StudioProvider)
        .filter(
            StudioModel.id == model_id,
            StudioModel.enabled == 1,
            StudioModel.media_type == "IMAGE",
            StudioProvider.enabled == 1,
        )
        .first()
    )
    if not model:
        raise ValueError("图片模型不存在、已停用或无权访问")
    department_id = getattr(model.provider, "dept_id", None)
    if department_id is None:
        raise ValueError("图片模型供应商尚未归属部门")
    if not can_access_model(
        user,
        model,
        department_id=department_id,
    ):
        raise ValueError("无权使用该图片模型或供应商配置")
    if (
        not is_super_admin_user(user)
        and user_department_id(user) != int(department_id)
    ):
        raise ValueError("当前图片模型不属于当前部门")
    if not str(model.provider.api_key or "").strip():
        raise ValueError("当前图片供应商尚未配置 API Key，请先编辑供应商")
    return model, int(department_id)


def _resolve_assets(user, asset_ids, department_id):
    requested_ids = _unique_ids(asset_ids)
    if not requested_ids:
        raise ValueError("精修白底图至少需要上传一张图片")
    assets = (
        StudioAsset.query.filter(
            StudioAsset.id.in_(requested_ids),
            StudioAsset.status == "ACTIVE",
            StudioAsset.purpose == "GENERATION_REFERENCE",
            StudioAsset.asset_type == "IMAGE",
            StudioAsset.dept_id == department_id,
        )
        .all()
    )
    by_id = {int(asset.id): asset for asset in assets}
    ordered = [by_id[item] for item in requested_ids if item in by_id]
    if len(ordered) != len(requested_ids):
        raise ValueError("精修白底图参考图片不存在、已过期或用途不正确")
    for asset in ordered:
        if not can_access_asset(user, asset):
            raise ValueError("不能使用其他用户上传的参考图片")
        if (
            asset.expires_at
            and asset.expires_at <= datetime.datetime.now()
        ):
            raise ValueError("精修白底图参考图片已经过期，请重新上传")
    return ordered


def _resolve_skill(user, skill_id=None):
    if skill_id not in (None, ""):
        try:
            requested_skill_id = int(skill_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("请选择有效的图片 Skill") from exc
        skill = StudioSkill.query.filter_by(
            id=requested_skill_id,
            enabled=1,
        ).first()
        if not skill:
            raise ValueError("图片 Skill 不存在、已停用或无权访问")
    else:
        skill = StudioSkill.query.filter_by(
            code=WHITE_BACKGROUND_IMAGE_SKILL_CODE,
            enabled=1,
        ).first()
    if not skill:
        raise ValueError(
            "精修白底图 Skill 尚未初始化，请先执行 flask amazon-ai-init --seed-storage"
        )
    if not can_access_skill(
        user,
        skill,
        builtin_codes=AMAZON_BUILTIN_SKILL_CODES,
    ):
        raise ValueError("无权使用精修白底图 Skill")
    if skill.media_type not in ("BOTH", "IMAGE"):
        raise ValueError("精修白底图 Skill 与图片创作类型不匹配")
    return skill


def _white_background_prompt(index, total, merge, layout_label, layout=None):
    if merge:
        opening = (
            f"为本次提供的{total}张产品图片制作成{layout_label}的纯白底电商图。"
            "每张输入图片对应一个独立宫格位置，必须按输入顺序排列。"
        )
        grid_instruction = ""
        if layout:
            columns, rows, _ = layout
            empty_slots = columns * rows - total
            grid_instruction = (
                f"宫格布局为{columns}列{rows}行。"
            )
            if empty_slots > 0:
                grid_instruction += (
                    f"未占用的{empty_slots}个宫格位置必须保持纯白空白，"
                    "不得添加产品、文字、道具或其他内容。"
                )
    else:
        opening = (
            f"以本次提供的第{index}张产品图片为唯一产品身份依据，"
            "制作一张精修纯白底电商图。"
        )
        grid_instruction = ""
    return (
        opening
        + grid_instruction
        + "只移除与产品无关的背景，保留产品完整外观、结构、颜色、比例、"
        "材质、纹理、文字、标签、配件和连接关系；进行专业锐化和细节美化，"
        "但不得变形、换色、增删或重绘产品。背景必须干净纯白，产品完整入画，"
        "只允许保留极轻微自然接触阴影，不添加人物、道具、场景或其他产品。"
    )


def create_white_background_generations(
    *,
    user_id,
    model_id,
    reference_asset_ids,
    aspect_ratio="auto",
    resolution="1k",
    merge=False,
    client_batch_id=None,
    acting_user=None,
    skill_id=None,
):
    """Create one independent generation task per image, or one grid task."""

    user = acting_user or User.query.get(user_id)
    if not user or int(getattr(user, "id", 0) or 0) != int(user_id):
        raise ValueError("当前用户不存在")
    model, department_id = _resolve_model(user, model_id)
    assets = _resolve_assets(user, reference_asset_ids, department_id)
    skill = _resolve_skill(user, skill_id)
    merge = bool(merge)
    if merge and len(assets) not in WHITE_BACKGROUND_GRID_LAYOUTS:
        raise ValueError("合并宫格图仅支持上传 2 至 9 张图片")

    image_dimensions = []
    for asset in assets:
        # Dimension inspection is a storage network operation. The database
        # row is already validated and the request connection can be idle.
        release_db_connection()
        width, height = _read_image_dimensions(asset)
        image_dimensions.append((width, height))

    layout = WHITE_BACKGROUND_GRID_LAYOUTS.get(len(assets)) if merge else None
    merge_ratio = (
        _ratio_text(layout[0], layout[1])
        if layout
        else None
    )
    plans = []
    for index, (width, height) in enumerate(image_dimensions, start=1):
        plan = _target_plan(
            model,
            width,
            height,
            aspect_ratio,
            resolution,
            merge_ratio=merge_ratio,
        )
        plans.append(
            {
                "index": index,
                "asset_ids": (
                    [asset.id for asset in assets]
                    if merge
                    else [assets[index - 1].id]
                ),
                "plan": plan,
            }
        )
        if merge:
            break

    batch_id = str(client_batch_id or "").strip() or (
        "white-" + uuid.uuid4().hex
    )
    app = current_app._get_current_object()
    user_id = int(user_id)
    model_id = int(model_id)
    product_count = len(assets)
    layout_label = layout[2] if layout else ""

    def process_one(item):
        with app.app_context():
            try:
                worker_user = User.query.get(user_id)
                prompt = _white_background_prompt(
                    item["index"],
                    product_count,
                    merge,
                    layout_label,
                    layout=layout,
                )
                task = create_generation(
                    user_id=user_id,
                    media_type="IMAGE",
                    model_id=model_id,
                    product_id=None,
                    prompt=prompt,
                    options={
                        "count": 1,
                        "aspect_ratio": item["plan"]["aspect_ratio"],
                        "resolution": item["plan"]["resolution"],
                        "reference_asset_ids": item["asset_ids"],
                        "skill_id": skill.id,
                        "department_id": department_id,
                        "extra_fields": {},
                        "target_dimensions": item["plan"]["target_dimensions"],
                        "target_aspect_ratio": item["plan"][
                            "target_aspect_ratio"
                        ],
                        "workflow_metadata": {
                            "type": "WHITE_BACKGROUND",
                            "batch_id": batch_id,
                            "index": item["index"],
                            "count": product_count,
                            "merge": merge,
                            "asset_ids": item["asset_ids"],
                            "target_dimensions": item["plan"][
                                "target_dimensions"
                            ],
                            "target_aspect_ratio": item["plan"][
                                "target_aspect_ratio"
                            ],
                            "quality": item["plan"]["quality"],
                        },
                    },
                    acting_user=worker_user,
                )
                return {
                    "index": item["index"],
                    "asset_ids": item["asset_ids"],
                    "task_id": int(task.id),
                    "target_dimensions": item["plan"]["target_dimensions"],
                    "target_aspect_ratio": item["plan"][
                        "target_aspect_ratio"
                    ],
                    "quality": item["plan"]["quality"],
                }
            except Exception as exc:
                return {
                    "index": item["index"],
                    "asset_ids": item["asset_ids"],
                    "error": str(exc) or "精修白底图任务提交失败",
                    "generation_task_id": getattr(
                        exc,
                        "_generation_task_id",
                        None,
                    ),
                }
            finally:
                db.session.remove()

    max_workers = 1 if merge else min(max(1, len(plans)), 8)
    results = []
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="studio-white-background",
    ) as executor:
        futures = [executor.submit(process_one, item) for item in plans]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: int(item.get("index") or 0))
    return {
        "batch_id": batch_id,
        "merge": merge,
        "count": product_count,
        "tasks": results,
    }
