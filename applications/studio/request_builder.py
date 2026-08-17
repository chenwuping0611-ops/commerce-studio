import json
from copy import deepcopy


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
        "hint": "图片生成数量",
    },
    {
        "field": "size",
        "label": "画面比例",
        "value": "1:1",
        "runtime_key": "aspect_ratio",
        "value_type": "string",
        "enabled": True,
        "hint": "例如 1:1、4:3、16:9",
    },
    {
        "field": "resolution",
        "label": "分辨率",
        "value": "1k",
        "runtime_key": "resolution",
        "value_type": "string",
        "enabled": True,
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
        "value": "seedance-2",
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
        "hint": "视频秒数",
    },
    {
        "field": "aspect_ratio",
        "label": "画面比例",
        "value": "16:9",
        "runtime_key": "aspect_ratio",
        "value_type": "string",
        "enabled": True,
        "hint": "例如 16:9、9:16",
    },
    {
        "field": "resolution",
        "label": "分辨率",
        "value": "720p",
        "runtime_key": "resolution",
        "value_type": "string",
        "enabled": True,
        "hint": "例如 720p、1080p",
    },
    {
        "field": "image_with_roles",
        "label": "参考图片",
        "value": "",
        "runtime_key": "reference_images_with_roles",
        "value_type": "json",
        "enabled": True,
        "hint": "ToAPIs 角色数组",
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
        "value": "true",
        "runtime_key": "generate_audio",
        "value_type": "boolean",
        "enabled": True,
        "hint": "模型支持时发送",
    },
]


def default_parameters(media_type):
    """Return a detached starter schema for a new image or video model."""

    return deepcopy(
        VIDEO_DEFAULT_PARAMETERS if str(media_type).upper() == "VIDEO" else IMAGE_DEFAULT_PARAMETERS
    )


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


def _runtime_value(parameter, runtime, model_code):
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
    return cast_value(value, parameter.get("value_type", "string"))


def build_request_body(model, runtime, extra_fields=None):
    """Build the final provider body from the model's configurable schema."""

    runtime = runtime or {}
    body = {}
    for parameter in parse_parameters(model.parameter_schema):
        if not parameter.get("enabled", True):
            continue
        field = str(parameter.get("field") or "").strip()
        if not field:
            continue
        value = _runtime_value(parameter, runtime, model.model_code)
        if not is_empty_value(value):
            body[field] = value

    for field, value in (extra_fields or {}).items():
        field = str(field or "").strip()
        if field and not is_empty_value(value):
            body[field] = value
    return body


def reference_roles(urls, role):
    return [{"url": url, "role": role} for url in urls if url]
