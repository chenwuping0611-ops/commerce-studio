import json
import re
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
        "min": 1,
        "max": 60,
        "step": 1,
        "hint": "视频秒数",
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
        "options": ["480p", "720p", "1080p"],
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


def default_parameters_for_model(model_code, media_type):
    """Return the starter schema for a known model without changing custom schemas."""

    if str(model_code or "").strip().lower() == "gemini-3.1-flash-image-preview":
        return deepcopy(NANO_BANANA_IMAGE_PARAMETERS)
    return default_parameters(media_type)


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
    casted = cast_value(value, parameter.get("value_type", "string"))
    allowed = option_values(parameter)
    actual_value = (
        str(casted).lower()
        if isinstance(casted, bool)
        else str(casted)
    )
    allowed_values = (
        [item.lower() for item in allowed]
        if isinstance(casted, bool)
        else allowed
    )
    if allowed_values and actual_value not in allowed_values:
        raise ValueError(
            f"字段 {field} 的值必须是：{', '.join(allowed)}"
        )
    return casted


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
            _assign_field(body, field, value)

    for field, value in (extra_fields or {}).items():
        field = str(field or "").strip()
        if field and not is_empty_value(value):
            _assign_field(body, field, value)
    return body


def reference_roles(urls, role):
    result = []
    for item in urls or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            result.append(
                {
                    "url": url,
                    "role": item.get("role") or role,
                    "label": item.get("label") or "",
                    "source": item.get("source") or "",
                }
            )
        else:
            url = str(item or "").strip()
            if url:
                result.append({"url": url, "role": role})
    return result
