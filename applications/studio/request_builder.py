import json
import math
import re
from copy import deepcopy

from .provider_catalog import (
    JIEKOU_IMAGE_MODEL_CODE,
    KUAIPAO_IMAGE_ASPECT_RATIOS,
    KUAIPAO_IMAGE_MODEL_CODES,
    KUAIPAO_IMAGE_MODEL_CODE,
    KUAIPAO_LEGACY_IMAGE_MODEL_CODES,
    kuaipao_image_api_model_code,
    model_spec_for,
    provider_catalog_key,
)


SEEDANCE_MODEL_CODES = frozenset(
    {
        "seedance-2-mini",
        "seedance-2-fast",
        "seedance-2",
    }
)
SEEDANCE_RESOLUTION_OPTIONS = {
    "seedance-2-mini": ["480p", "720p"],
    "seedance-2-fast": ["480p", "720p"],
    "seedance-2": ["480p", "720p", "1080p", "4k"],
}
SEEDANCE_DEFAULT_RESOLUTION = "720p"
SEEDANCE_IMAGE_REFERENCE_ROLE = "reference_image"
SEEDANCE_FORBIDDEN_IMAGE_FIELDS = frozenset(
    {
        "first_frame",
        "last_frame",
        "first_frame_image",
        "last_frame_image",
        "input_reference",
        "input_references",
        "image",
        "image_url",
        "image_urls",
    }
)


IMAGE_MAX_DIMENSION = 4096
IMAGE_DIMENSION_ALIGNMENT = 8
JIEKOU_IMAGE_QUALITY_BY_RESOLUTION = {
    "1k": "low",
    "2k": "medium",
    "4k": "high",
}
JIEKOU_IMAGE_MAX_DIMENSION_BY_RESOLUTION = {
    "1k": 1024,
    "2k": 2048,
    "4k": 4096,
}
KUAIPAO_IMAGE_ALL_MODEL_CODES = frozenset(
    KUAIPAO_IMAGE_MODEL_CODES + KUAIPAO_LEGACY_IMAGE_MODEL_CODES
)


IMAGE_DEFAULT_PARAMETERS = [
    {
        "field": "model",
        "label": "模型标识",
        "value": "gpt-image-2",
        "runtime_key": "",
        "value_type": "string",
        "enabled": True,
        "hint": "发送给供应商的模型名称",
    },
    {
        "field": "prompt",
        "label": "提示词",
        "value": "",
        "runtime_key": "prompt",
        "value_type": "string",
        "enabled": True,
        "hint": "由创作页和产品记忆拼接",
    },
    {
        "field": "n",
        "label": "生成数量",
        "value": "1",
        "runtime_key": "count",
        "value_type": "number",
        "enabled": True,
        "min": 1,
        "max": 8,
        "step": 1,
        "hint": "图片生成数量",
    },
    {
        "field": "size",
        "label": "画面比例",
        "value": "1:1",
        "runtime_key": "aspect_ratio",
        "value_type": "string",
        "enabled": True,
        "options": ["1:1", "4:3", "16:9", "9:16"],
        "hint": "例如 1:1、4:3、16:9",
    },
    {
        "field": "resolution",
        "label": "分辨率",
        "value": "1k",
        "runtime_key": "resolution",
        "value_type": "string",
        "enabled": True,
        "options": ["1k", "2k", "4k"],
        "hint": "例如 1k、2k、4k",
    },
    {
        "field": "image_urls",
        "label": "参考图片",
        "value": "",
        "runtime_key": "reference_images",
        "value_type": "json",
        "enabled": True,
        "hint": "URL 数组，没有时不发送",
    },
    {
        "field": "response_format",
        "label": "返回格式",
        "value": "url",
        "runtime_key": "",
        "value_type": "string",
        "enabled": True,
        "hint": "通常填写 url",
    },
]


VIDEO_DEFAULT_PARAMETERS = [
    {
        "field": "model",
        "label": "模型标识",
        "value": "seedance-2-mini",
        "runtime_key": "",
        "value_type": "string",
        "enabled": True,
        "hint": "发送给供应商的模型名称",
    },
    {
        "field": "prompt",
        "label": "提示词",
        "value": "",
        "runtime_key": "prompt",
        "value_type": "string",
        "enabled": True,
        "hint": "由创作页和产品记忆拼接",
    },
    {
        "field": "duration",
        "label": "时长",
        "value": "5",
        "runtime_key": "duration",
        "value_type": "number",
        "enabled": True,
        "min": 4,
        "max": 15,
        "step": 1,
        "hint": "Seedance 视频时长为 4-15 秒",
    },
    {
        "field": "aspect_ratio",
        "label": "画面比例",
        "value": "16:9",
        "runtime_key": "aspect_ratio",
        "value_type": "string",
        "enabled": True,
        "options": ["16:9", "9:16", "1:1", "4:3"],
        "hint": "例如 16:9、9:16",
    },
    {
        "field": "resolution",
        "label": "分辨率",
        "value": "720p",
        "runtime_key": "resolution",
        "value_type": "string",
        "enabled": True,
        "options": ["480p", "720p", "1080p", "4k"],
        "hint": "不同 Seedance 版本支持的分辨率不同",
    },
    {
        "field": "image_with_roles",
        "label": "参考图片",
        "value": "",
        "runtime_key": "reference_images_with_roles",
        "value_type": "json",
        "enabled": True,
        "hint": "仅发送多模态参考图角色 reference_image，不使用首帧或尾帧角色",
    },
    {
        "field": "video_with_roles",
        "label": "参考视频",
        "value": "",
        "runtime_key": "reference_videos_with_roles",
        "value_type": "json",
        "enabled": True,
        "hint": "ToAPIs 角色数组",
    },
    {
        "field": "generate_audio",
        "label": "生成音频",
        "value": "false",
        "runtime_key": "generate_audio",
        "value_type": "boolean",
        "enabled": True,
        "hint": "模型支持时发送",
    },
]


CHAT_DEFAULT_PARAMETERS = [
    {
        "field": "model",
        "label": "模型标识",
        "value": "gpt-5.5",
        "runtime_key": "",
        "value_type": "string",
        "enabled": True,
        "hint": "发送给供应商的语言模型标识",
    },
    {
        "field": "messages",
        "label": "消息内容",
        "value": "",
        "runtime_key": "messages",
        "value_type": "json",
        "enabled": True,
        "hint": "OpenAI Chat Completions 格式的消息数组",
    },
    {
        "field": "max_tokens",
        "label": "最大输出 Token",
        "value": "800",
        "runtime_key": "max_tokens",
        "value_type": "number",
        "enabled": True,
        "min": 1,
        "max": 8192,
        "step": 1,
        "hint": "分析结果的最大输出长度",
    },
    {
        "field": "temperature",
        "label": "温度",
        "value": "0.2",
        "runtime_key": "temperature",
        "value_type": "number",
        "enabled": True,
        "min": 0,
        "max": 2,
        "step": 0.1,
        "hint": "分析任务建议使用较低温度",
    },
]


NANO_BANANA_IMAGE_PARAMETERS = [
    {
        "field": "model",
        "label": "模型标识",
        "value": "gemini-3.1-flash-image-preview",
        "runtime_key": "",
        "value_type": "string",
        "enabled": True,
        "hint": "Nano Banana 2 对应的 ToAPIs 模型标识",
    },
    {
        "field": "prompt",
        "label": "提示词",
        "value": "",
        "runtime_key": "prompt",
        "value_type": "string",
        "enabled": True,
        "hint": "由创作页面和产品记忆拼接后的提示词",
    },
    {
        "field": "n",
        "label": "生成数量",
        "value": "1",
        "runtime_key": "count",
        "value_type": "number",
        "enabled": True,
        "min": 1,
        "max": 8,
        "step": 1,
        "hint": "图片生成数量",
    },
    {
        "field": "size",
        "label": "画面比例",
        "value": "1:1",
        "runtime_key": "aspect_ratio",
        "value_type": "string",
        "enabled": True,
        "options": [
            "1:1",
            "4:3",
            "16:9",
            "9:16",
            "1:4",
            "4:1",
            "1:8",
            "8:1",
        ],
        "hint": "ToAPIs size 字段支持的画面比例",
    },
    {
        "field": "metadata.resolution",
        "label": "分辨率",
        "value": "2K",
        "runtime_key": "resolution",
        "value_type": "string",
        "enabled": True,
        "options": ["1K", "2K", "4K"],
        "hint": "Nano Banana 2 的分辨率位于 metadata.resolution",
    },
    {
        "field": "image_urls",
        "label": "参考图片",
        "value": "",
        "runtime_key": "reference_images",
        "value_type": "json",
        "enabled": True,
        "hint": "支持产品素材和本次上传的多张参考图",
    },
]


def default_parameters(media_type):
    """Return a detached starter schema for a new image or video model."""

    media_type = str(media_type).upper()
    if media_type == "VIDEO":
        parameters = VIDEO_DEFAULT_PARAMETERS
    elif media_type == "CHAT":
        parameters = CHAT_DEFAULT_PARAMETERS
    else:
        parameters = IMAGE_DEFAULT_PARAMETERS
    return deepcopy(parameters)


def is_seedance_model(model_code):
    return str(model_code or "").strip().lower() in SEEDANCE_MODEL_CODES


def seedance_capabilities(model_code):
    """Return the non-negotiable capabilities for a Seedance model version."""

    code = str(model_code or "").strip().lower()
    if not is_seedance_model(code):
        return {}
    return {
        "supports_multimodal_reference": True,
        "image_reference_roles": [SEEDANCE_IMAGE_REFERENCE_ROLE],
        "max_reference_images": 9,
        "duration_min": 4,
        "duration_max": 15,
        "resolution_options": list(
            SEEDANCE_RESOLUTION_OPTIONS.get(
                code,
                SEEDANCE_RESOLUTION_OPTIONS["seedance-2"],
            )
        ),
    }


def seedance_parameters(model_code, existing=None):
    """Build a safe schema for one Seedance version.

    Existing non-protocol fields are retained so an administrator's harmless
    custom settings are not discarded, while protocol fields that could select
    first/last-frame image modes are removed.
    """

    code = str(model_code or "").strip().lower()
    if not is_seedance_model(code):
        return deepcopy(existing or VIDEO_DEFAULT_PARAMETERS)

    base = deepcopy(VIDEO_DEFAULT_PARAMETERS)
    base_by_field = {item["field"]: item for item in base}
    current = parse_parameters(existing)
    current_by_field = {
        str(item.get("field") or "").strip(): deepcopy(item)
        for item in current
        if isinstance(item, dict) and str(item.get("field") or "").strip()
    }
    result = []

    for field in (
        "model",
        "prompt",
        "duration",
        "aspect_ratio",
        "resolution",
        "image_with_roles",
        "video_with_roles",
        "generate_audio",
    ):
        template = deepcopy(base_by_field[field])
        item = current_by_field.pop(field, template)
        item.update(
            {
                "field": field,
                "enabled": True,
                "value_type": template["value_type"],
                "runtime_key": template["runtime_key"],
            }
        )
        if field == "model":
            item["value"] = code
            item["runtime_key"] = ""
        elif field == "duration":
            item["min"] = 4
            item["max"] = 15
            item["step"] = 1
            try:
                value = int(float(item.get("value", 5)))
            except (TypeError, ValueError):
                value = 5
            item["value"] = str(value) if 4 <= value <= 15 else "5"
            item["hint"] = "Seedance 视频时长为 4-15 秒"
        elif field == "resolution":
            options = list(SEEDANCE_RESOLUTION_OPTIONS[code])
            value = str(item.get("value") or SEEDANCE_DEFAULT_RESOLUTION).strip()
            item["options"] = options
            item["value"] = (
                value if value.lower() in {option.lower() for option in options}
                else SEEDANCE_DEFAULT_RESOLUTION
            )
            item["hint"] = "当前版本支持：" + "、".join(options)
        elif field == "image_with_roles":
            item["options"] = []
            item["value"] = ""
            item["hint"] = (
                "仅发送多模态参考图角色 reference_image，不使用首帧或尾帧角色"
            )
        elif field == "generate_audio":
            item["value"] = "false"
            item["hint"] = "默认关闭生成音频"
        result.append(item)

    for item in current_by_field.values():
        field = str(item.get("field") or "").strip()
        if field and field not in SEEDANCE_FORBIDDEN_IMAGE_FIELDS:
            result.append(item)
    return result


def default_parameters_for_model(model_code, media_type):
    """Return the starter schema for a known model without changing custom schemas."""

    if is_seedance_model(model_code):
        return seedance_parameters(model_code)
    if str(model_code or "").strip().lower() == "gemini-3.1-flash-image-preview":
        return deepcopy(NANO_BANANA_IMAGE_PARAMETERS)
    return default_parameters(media_type)


def model_parameter_schema(model):
    """Return the code-owned schema for catalog models.

    Legacy/custom models still fall back to their stored schema so existing
    department data keeps working while ToAPIs and Kuaipao use immutable
    provider definitions.
    """

    spec = model_spec_for(
        getattr(model, "provider", None),
        getattr(model, "model_code", ""),
    )
    if spec:
        return spec.parameter_schema()
    return parse_parameters(getattr(model, "parameter_schema", None))


def parse_parameters(raw):
    """Read a parameter schema stored as JSON, a list, or a wrapped object."""

    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("parameters", parsed.get("fields", []))
    return parsed if isinstance(parsed, list) else []


def parse_json_value(value):
    if isinstance(value, (list, dict, int, float, bool)):
        return value
    if value is None:
        return None
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return value


def cast_value(value, value_type):
    if value is None:
        return None
    value_type = str(value_type or "string").lower()
    if value_type in ("json", "array", "object"):
        return parse_json_value(value)
    if value_type in ("number", "integer", "int"):
        try:
            number = float(value)
            return int(number) if number.is_integer() else number
        except (TypeError, ValueError):
            return value
    if value_type in ("float", "decimal"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if value_type in ("boolean", "bool"):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return str(value)


def is_empty_value(value):
    return value in ("", None, [], {})


def is_kuaipao_image_model(model):
    """Return whether a model uses the Kuaipao multipart image contract."""

    code = str(getattr(model, "model_code", "") or "").strip().lower()
    if code not in KUAIPAO_IMAGE_ALL_MODEL_CODES:
        return False
    provider = getattr(model, "provider", None)
    return (
        provider is None
        or provider_catalog_key(provider) == "kuaipao"
    )


def is_jiekou_image_model(model):
    """Return whether a model uses the Interface AI JSON image contract."""

    code = str(getattr(model, "model_code", "") or "").strip().lower()
    provider = getattr(model, "provider", None)
    return (
        code == JIEKOU_IMAGE_MODEL_CODE
        and provider is not None
        and provider_catalog_key(provider) == "jiekou"
    )


def _canonical_image_aspect_ratio(value):
    """Return the matching preset ratio and reject unlisted ratios."""

    text = str(value or "").strip().lower()
    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*[:x]\s*(\d+(?:\.\d+)?)",
        text,
    )
    if not match:
        raise ValueError("图片比例必须从预设比例中选择")
    width_ratio = float(match.group(1))
    height_ratio = float(match.group(2))
    if (
        not math.isfinite(width_ratio)
        or not math.isfinite(height_ratio)
        or width_ratio <= 0
        or height_ratio <= 0
    ):
        raise ValueError("图片比例必须是大于 0 的正数宽:高")

    ratio = width_ratio / height_ratio
    for preset in KUAIPAO_IMAGE_ASPECT_RATIOS:
        preset_width, preset_height = (
            float(part) for part in preset.split(":")
        )
        if math.isclose(
            ratio,
            preset_width / preset_height,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return preset
    raise ValueError("图片比例必须从预设比例中选择")


def image_size_for_aspect_ratio(
    value,
    *,
    max_dimension=IMAGE_MAX_DIMENSION,
    alignment=IMAGE_DIMENSION_ALIGNMENT,
):
    """Convert one configured preset ratio into a 4K ``widthxheight`` size.

    Kuaipao accepts the actual pixel size. Use the standard UHD canvas for
    16:9 and 9:16, and keep the long edge at 4096 for the remaining presets.
    The quality choice (1K/2K/4K) is mapped to the model name separately.
    """

    canonical_ratio = _canonical_image_aspect_ratio(value)
    width_ratio, height_ratio = (
        float(part) for part in canonical_ratio.split(":")
    )

    try:
        max_dimension = int(max_dimension)
        alignment = max(1, int(alignment))
    except (TypeError, ValueError) as exc:
        raise ValueError("图片尺寸配置无效") from exc
    if max_dimension < 1:
        raise ValueError("图片最大尺寸配置无效")

    if max_dimension == IMAGE_MAX_DIMENSION:
        if canonical_ratio == "16:9":
            return "3840x2160"
        if canonical_ratio == "9:16":
            return "2160x3840"

    if width_ratio >= height_ratio:
        width = max_dimension
        short_dimension = max_dimension * height_ratio / width_ratio
        height = int(round(short_dimension / alignment) * alignment)
    else:
        height = max_dimension
        short_dimension = max_dimension * width_ratio / height_ratio
        width = int(round(short_dimension / alignment) * alignment)

    width = max(alignment, min(max_dimension, width))
    height = max(alignment, min(max_dimension, height))
    return f"{width}x{height}"


def image_dimensions_for_resolution(value, resolution):
    """Return the requested canvas dimensions for an Interface AI quality."""

    normalized_resolution = (
        str(resolution or "1k").strip().lower().replace(" ", "")
    )
    try:
        max_dimension = JIEKOU_IMAGE_MAX_DIMENSION_BY_RESOLUTION[
            normalized_resolution
        ]
    except KeyError as exc:
        raise ValueError("图片分辨率只能选择 1K、2K 或 4K") from exc
    return image_size_for_aspect_ratio(
        value,
        max_dimension=max_dimension,
    )


def _truncate_prompt_utf8(value, max_bytes):
    text = str(value or "").strip()
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


_JIEKOU_OUTPUT_CONTRACT_RE = re.compile(
    r"(?:^|\n)\s*输出规格：画布分辨率必须为"
    r"\d+\s*[xX×]\s*\d+像素，宽高比约为"
    r"\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?。?\s*",
    re.IGNORECASE,
)


def append_jiekou_image_output_contract(
    prompt,
    aspect_ratio,
    resolution,
    *,
    max_bytes=5000,
):
    """Append the selected Interface AI canvas contract to one image prompt."""

    canonical_ratio = _canonical_image_aspect_ratio(aspect_ratio or "1:1")
    normalized_resolution = (
        str(resolution or "1k").strip().lower().replace(" ", "")
    )
    dimensions = image_dimensions_for_resolution(
        canonical_ratio,
        normalized_resolution,
    ).replace("x", "X")
    suffix = (
        f"输出规格：画布分辨率必须为{dimensions}像素，"
        f"宽高比约为{canonical_ratio}。"
    )
    base = _JIEKOU_OUTPUT_CONTRACT_RE.sub("\n", str(prompt or "")).strip()
    separator = "\n\n" if base else ""
    suffix_bytes = len((separator + suffix).encode("utf-8"))
    if suffix_bytes >= max_bytes:
        raise ValueError("接口AI图片输出规格超过提示词长度限制")
    available = max_bytes - suffix_bytes
    base = _truncate_prompt_utf8(base, available)
    return (base + separator + suffix).strip()


def split_option_tokens(value):
    """Split accidentally concatenated ratio options without changing free text."""

    text = str(value or "").strip()
    if not text:
        return []
    ratio_pattern = r"\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?"
    if re.fullmatch(rf"{ratio_pattern}(?:\s+{ratio_pattern})+", text):
        return re.findall(ratio_pattern, text)
    return [text]


def _assign_field(target, field, value):
    """Assign flat or dotted fields, e.g. metadata.resolution, into a JSON body."""

    parts = [part.strip() for part in str(field or "").split(".") if part.strip()]
    if not parts:
        return
    node = target
    for part in parts[:-1]:
        current = node.get(part)
        if not isinstance(current, dict):
            current = {}
            node[part] = current
        node = current
    node[parts[-1]] = value


def option_values(parameter):
    """Return configured option values as strings for runtime validation."""

    options = parameter.get("options") or []
    if isinstance(options, str):
        try:
            parsed = json.loads(options)
            options = parsed if isinstance(parsed, list) else re.split(r"[,\n]", options)
        except (TypeError, ValueError):
            options = re.split(r"[,\n]", options)
    if not isinstance(options, (list, tuple)):
        return []
    values = []
    for option in options:
        if isinstance(option, dict):
            option = option.get("value", option.get("key", option.get("id")))
        values.extend(split_option_tokens(option))
    return values


def _runtime_value(parameter, runtime, model_code, model=None):
    field = parameter.get("field")
    runtime_key = parameter.get("runtime_key")
    if field == "model":
        value = model_code
    elif runtime_key and runtime_key in runtime:
        value = runtime.get(runtime_key)
    else:
        value = parameter.get("value")

    if is_empty_value(value):
        return None
    casted = cast_value(value, parameter.get("value_type", "string"))
    allowed = option_values(parameter)
    actual_value = (
        str(casted).lower()
        if isinstance(casted, bool)
        else str(casted)
    )
    if isinstance(casted, bool):
        allowed_values = [item.lower() for item in allowed]
    elif isinstance(casted, str):
        allowed_values = [str(item).lower() for item in allowed]
        actual_value = actual_value.lower()
    else:
        allowed_values = allowed
    if (
        allowed_values
        and actual_value not in allowed_values
    ):
        raise ValueError(
            f"字段 {field} 的值必须是：{', '.join(allowed)}"
        )
    return casted


def build_request_body(model, runtime, extra_fields=None):
    """Build the final provider body from the catalog or legacy schema."""

    runtime = runtime or {}
    body = {}
    for parameter in model_parameter_schema(model):
        if not parameter.get("enabled", True):
            continue
        field = str(parameter.get("field") or "").strip()
        if not field:
            continue
        value = _runtime_value(
            parameter,
            runtime,
            model.model_code,
            model=model,
        )
        if not is_empty_value(value):
            _assign_field(body, field, value)

    for field, value in (extra_fields or {}).items():
        field = str(field or "").strip()
        if field and not is_empty_value(value):
            _assign_field(body, field, value)
    return normalize_provider_request_body(
        model,
        body,
    )


def normalize_provider_request_body(model, body):
    """Apply provider-specific invariants after the generic field builder."""

    model_code = str(getattr(model, "model_code", "") or "").strip().lower()
    provider = getattr(model, "provider", None)
    spec = model_spec_for(provider, model_code)
    if spec:
        body["model"] = spec.code

    if is_seedance_model(model_code):
        return normalize_seedance_request_body(model_code, body)

    if is_kuaipao_image_model(model):
        return normalize_kuaipao_image_request_body(model, body)

    if is_jiekou_image_model(model):
        return normalize_jiekou_image_request_body(model, body)

    if model_code == "gemini-3.1-flash-image-preview":
        metadata = body.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if body.get("image_urls") in (None, "", []):
            body.pop("image_urls", None)
        google_image_search = metadata.get("google_image_search")
        if google_image_search and not metadata.get("google_search"):
            metadata.pop("google_image_search", None)
        if metadata:
            body["metadata"] = metadata
        else:
            body.pop("metadata", None)
        return body

    if model_code == "gpt-image-2":
        # The current ToAPIs contract uses reference_images. Accept the old
        # compatibility field when a legacy caller still supplies it.
        if body.get("reference_images") in (None, "", []):
            legacy_urls = body.pop("image_urls", None)
            if legacy_urls not in (None, "", []):
                body["reference_images"] = legacy_urls
        body.setdefault("response_format", "url")
        return body

    return body


def normalize_kuaipao_image_request_body(model, body):
    """Normalize Kuaipao image fields before JSON or multipart transport."""

    references = body.get("reference_images")
    if references in (None, "", []):
        legacy_urls = body.pop("image_urls", None)
        if legacy_urls not in (None, "", []):
            body["reference_images"] = legacy_urls

    ratio = body.get("size") or "1:1"
    body["size"] = image_size_for_aspect_ratio(ratio)
    model_code = str(
        getattr(model, "model_code", "") or ""
    ).strip().lower()
    if model_code == KUAIPAO_IMAGE_MODEL_CODE:
        # The database/UI keeps one stable image model identity. Kuaipao
        # receives the quality-specific model code only at the last step.
        body["model"] = kuaipao_image_api_model_code(
            body.get("resolution") or "1k"
        )
    elif model_code in KUAIPAO_LEGACY_IMAGE_MODEL_CODES:
        # Keep old task/request rows readable without exposing them as new
        # selectable models after studio-init.
        body["model"] = model_code
    body.pop("resolution", None)
    # Kuaipao returns b64_json by default; response_format is not part of its
    # multipart contract and must not force a URL response.
    body.pop("response_format", None)
    return body


def normalize_jiekou_image_request_body(model, body):
    """Normalize Interface AI gpt-image2 into its fixed JSON request body."""

    references = body.get("image")
    if references in (None, "", []):
        references = body.pop("reference_images", None)
    if references in (None, "", []):
        references = body.pop("image_urls", None)
    if references not in (None, "", []):
        body["image"] = references
    else:
        body.pop("image", None)

    ratio = body.get("size") or body.get("aspect_ratio") or "1:1"
    resolution = body.get("resolution") or "1k"
    body["prompt"] = append_jiekou_image_output_contract(
        body.get("prompt") or "",
        ratio,
        resolution,
    )
    body["size"] = "auto"
    normalized_resolution = (
        str(resolution).strip().lower().replace(" ", "")
    )
    try:
        body["quality"] = JIEKOU_IMAGE_QUALITY_BY_RESOLUTION[
            normalized_resolution
        ]
    except KeyError as exc:
        raise ValueError("图片分辨率只能选择 1K、2K 或 4K") from exc
    body["background"] = "opaque"
    body["output_format"] = "png"
    body.pop("model", None)
    body.pop("aspect_ratio", None)
    body.pop("resolution", None)
    return body


def normalize_seedance_request_body(model_code, body):
    """Validate Seedance constraints and normalize its multimodal image roles."""

    if not is_seedance_model(model_code):
        return body

    code = str(model_code).strip().lower()
    body["model"] = code

    duration = body.get("duration")
    if duration not in (None, ""):
        try:
            numeric_duration = float(duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("Seedance 视频时长必须是 4-15 秒的整数") from exc
        if not numeric_duration.is_integer() or not 4 <= numeric_duration <= 15:
            raise ValueError("Seedance 视频时长必须是 4-15 秒的整数")
        body["duration"] = int(numeric_duration)

    resolution = body.get("resolution")
    allowed_resolutions = SEEDANCE_RESOLUTION_OPTIONS[code]
    if resolution not in (None, ""):
        normalized_resolution = str(resolution).strip().lower()
        matched = next(
            (
                option
                for option in allowed_resolutions
                if option.lower() == normalized_resolution
            ),
            None,
        )
        if not matched:
            raise ValueError(
                f"{code} 仅支持分辨率：{', '.join(allowed_resolutions)}"
            )
        body["resolution"] = matched

    for field in SEEDANCE_FORBIDDEN_IMAGE_FIELDS:
        body.pop(field, None)

    image_roles = body.get("image_with_roles")
    if image_roles not in (None, "", []):
        if isinstance(image_roles, dict):
            image_roles = [image_roles]
        if not isinstance(image_roles, list):
            raise ValueError("Seedance 参考图片必须是 image_with_roles 数组")
        normalized_roles = []
        for item in image_roles:
            url = (
                item.get("url")
                if isinstance(item, dict)
                else item
            )
            url = str(url or "").strip()
            if url:
                normalized_roles.append(
                    {
                        "url": url,
                        "role": SEEDANCE_IMAGE_REFERENCE_ROLE,
                    }
                )
        if len(normalized_roles) > 9:
            raise ValueError("Seedance 多模态参考图片最多支持 9 张")
        if normalized_roles:
            body["image_with_roles"] = normalized_roles
        else:
            body.pop("image_with_roles", None)
    return body


def reference_roles(urls, role):
    """Build the provider-facing reference array.

    Product roles such as ``front`` and ``left`` are useful to the prompt
    planner, but they are not provider protocol values.  Keep those semantic
    labels in the final prompt and send the configured API role here so a
    product reference cannot make a video request invalid.
    """

    result = []
    for item in urls or []:
        url = (
            str(item.get("url") or "").strip()
            if isinstance(item, dict)
            else str(item or "").strip()
        )
        if url:
            result.append({"url": url, "role": role})
    return result
