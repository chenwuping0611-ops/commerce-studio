"""Parsing and validation helpers for batch prompt documents.

The language model is asked for JSON, but the parser intentionally accepts a
small set of human-readable fallbacks so an otherwise useful response is not
lost when an OpenAI-compatible relay adds formatting around the answer.
"""

import json
import math
import re
import secrets
import string

from .provider_catalog import KUAIPAO_IMAGE_ASPECT_RATIOS


DEFAULT_BATCH_PROMPT_COUNT = 10
MIN_BATCH_PROMPT_COUNT = 1
MAX_BATCH_PROMPT_COUNT = 50
MAX_BATCH_PROMPT_VERSION_BYTES = 5000
MAX_BATCH_PROMPT_STYLE_LENGTH = 160
DEFAULT_BATCH_IMAGE_ASPECT_RATIO = "2.44:1"
BATCH_IMAGE_ASPECT_RATIO_OPTIONS = tuple(KUAIPAO_IMAGE_ASPECT_RATIOS)
DEFAULT_BATCH_IMAGE_RESOLUTION = "2k"
BATCH_IMAGE_RESOLUTION_OPTIONS = ("1k", "2k", "4k")
RANDOM_BATCH_PROMPT_NAME_LENGTH = 6
_BATCH_PROMPT_RANDOM_ALPHABET = string.ascii_letters + string.digits
_INVALID_FILENAME_CHARS_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')
BATCH_PROMPT_STYLE_CUSTOM_VALUE = "__custom__"
BATCH_PROMPT_STYLE_OPTIONS = (
    {"value": "", "label": "跟随 Skill"},
    {"value": "专业电商详情图", "label": "专业电商详情图"},
    {"value": "高端商业摄影", "label": "高端商业摄影"},
    {"value": "简约现代", "label": "简约现代"},
    {"value": "生活方式场景", "label": "生活方式场景"},
    {"value": "科技产品广告", "label": "科技产品广告"},
    {
        "value": BATCH_PROMPT_STYLE_CUSTOM_VALUE,
        "label": "自定义风格",
    },
)

_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_BATCH_HEADING_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:第\s*(?P<chinese>[零一二三四五六七八九十百两]+|\d+)\s*版"
    r"|版本\s*(?P<number>\d+))\s*[：:]\s*",
    re.IGNORECASE,
)
# Older model responses sometimes place the next version after spaces on the
# same physical line. Keep the strict line-start parser above as the first
# choice, then use this boundary-aware fallback only when needed.
_BATCH_INLINE_HEADING_RE = re.compile(
    r"(?<!\S)\s*"
    r"(?:第\s*(?P<chinese>[零一二三四五六七八九十百两]+|\d+)\s*版"
    r"|版本\s*(?P<number>\d+))\s*[：:]\s*",
    re.IGNORECASE,
)
_IMAGE_ASPECT_TOKEN_RE = re.compile(
    r"(?P<width>\d+(?:\.\d+)?)\s*[:x×]\s*"
    r"(?P<height>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_IMAGE_ASPECT_LABEL_RE = re.compile(
    r"(?:画布|画面|输出画面|图片|canvas|image)\s*"
    r"(?:比例|ratio|aspect(?:\s+ratio)?)"
    r"\s*(?:约\s*)?(?:为|是|设为|设置为|=|:|：)?\s*"
    r"(?P<ratio>\d+(?:\.\d+)?\s*[:x×]\s*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_IMAGE_RESOLUTION_LABEL_RE = re.compile(
    r"(?:图片|图像|输出|生成|画面)?\s*"
    r"(?:质量|画质|分辨率|resolution|quality)"
    r"\s*(?:约\s*)?(?:为|是|设为|设置为|=|:|：)?\s*"
    r"(?P<resolution>[124]\s*[kK])\b",
    re.IGNORECASE,
)
_IMAGE_ASPECT_SETTING_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:[-*]\s*)?"
    r"(?:画布|画面|输出画面|图片|canvas|image)\s*"
    r"(?:比例|ratio|aspect(?:\s+ratio)?)"
    r"\s*(?:约\s*)?(?:为|是|设为|设置为|=|:|：)?\s*"
    r"\d+(?:\.\d+)?\s*[:x×]\s*\d+(?:\.\d+)?[ \t]*$"
)
_IMAGE_RESOLUTION_SETTING_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:[-*]\s*)?"
    r"(?:图片|图像|输出|生成|画面)?\s*"
    r"(?:质量|画质|分辨率|resolution|quality)"
    r"\s*(?:约\s*)?(?:为|是|设为|设置为|=|:|：)?\s*"
    r"[124]\s*[kK][ \t]*$"
)


def batch_prompt_filename(product_name=None, run_number=None):
    """Return the stable TXT name used by one batch-prompt history record."""

    stem = _INVALID_FILENAME_CHARS_RE.sub(
        "_",
        str(product_name or "").strip(),
    )
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    stem = stem[:180].rstrip(" .")
    if not stem:
        stem = "".join(
            secrets.choice(_BATCH_PROMPT_RANDOM_ALPHABET)
            for _ in range(RANDOM_BATCH_PROMPT_NAME_LENGTH)
        )
    if run_number is None:
        return f"{stem}.txt"
    return f"{stem}\u00b7R{int(run_number):02d}.txt"


def parse_batch_prompt_count(value):
    """Normalize the slider/input value and enforce the server-side limit."""

    if value in (None, ""):
        raise ValueError("批量创作数量不能为空")
    try:
        count = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("批量创作数量必须是整数") from exc
    if count == 0:
        return DEFAULT_BATCH_PROMPT_COUNT
    if count < MIN_BATCH_PROMPT_COUNT:
        raise ValueError("批量创作数量只能为 0 或 1-50")
    if count > MAX_BATCH_PROMPT_COUNT:
        raise ValueError(
            f"批量创作数量不能超过 {MAX_BATCH_PROMPT_COUNT}"
        )
    return count


def normalize_batch_prompt_style(value):
    """Normalize the optional style control before storing it in the history."""

    text = str(value or "").strip()
    if not text:
        return ""
    return text[:MAX_BATCH_PROMPT_STYLE_LENGTH].strip()


def normalize_batch_image_resolution(value, default=DEFAULT_BATCH_IMAGE_RESOLUTION):
    """Normalize the quality selector used by image batch processing."""

    text = str(value or "").strip().lower().replace(" ", "")
    if not text:
        text = str(default or DEFAULT_BATCH_IMAGE_RESOLUTION).strip().lower()
    if text not in BATCH_IMAGE_RESOLUTION_OPTIONS:
        raise ValueError("图片质量只能选择 1K、2K 或 4K")
    return text


def normalize_image_aspect_ratio(value):
    """Return one of the code-owned image aspect-ratio presets."""

    match = _IMAGE_ASPECT_TOKEN_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("图片画布比例必须从预设比例中选择")
    width = float(match.group("width"))
    height = float(match.group("height"))
    if (
        not math.isfinite(width)
        or not math.isfinite(height)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("图片画布比例必须是大于 0 的正数宽:高")
    ratio = width / height
    for preset in KUAIPAO_IMAGE_ASPECT_RATIOS:
        preset_width, preset_height = (
            float(item) for item in preset.split(":")
        )
        if math.isclose(
            ratio,
            preset_width / preset_height,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return preset
    raise ValueError("图片画布比例必须从预设比例中选择")


def normalize_prompt_newlines(value):
    """Turn escaped newline markers from stored/model text into real lines."""

    text = str(value or "")
    # Some provider responses and old GoFastDFS documents contain the two
    # literal characters ``\n`` instead of an actual line break.
    return re.sub(r"\\r\\n|\\n|\\r", "\n", text)


def strip_image_batch_settings(prompt):
    """Remove backend-only ratio and quality marker lines from one prompt."""

    text = normalize_prompt_newlines(prompt).strip()
    text = _IMAGE_ASPECT_SETTING_LINE_RE.sub("", text)
    text = _IMAGE_RESOLUTION_SETTING_LINE_RE.sub("", text)
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    return text.strip()


def extract_image_batch_settings(
    prompt,
    *,
    default_aspect_ratio=DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
    default_resolution=DEFAULT_BATCH_IMAGE_RESOLUTION,
):
    """Extract the image parameters embedded in one prompt version.

    The planner Skill is asked to mark the canvas ratio and quality explicitly.
    Older documents may not contain those labels, so the batch record's stored
    quality and aspect-ratio defaults remain backward compatible.
    """

    text = normalize_prompt_newlines(prompt).strip()
    aspect_ratio = normalize_image_aspect_ratio(
        default_aspect_ratio or DEFAULT_BATCH_IMAGE_ASPECT_RATIO
    )
    labelled_aspects = list(_IMAGE_ASPECT_LABEL_RE.finditer(text))
    if labelled_aspects:
        try:
            aspect_ratio = normalize_image_aspect_ratio(
                labelled_aspects[-1].group("ratio")
            )
        except ValueError as exc:
            raise ValueError(
                f"提示词中的画布比例不是系统预设："
                f"{labelled_aspects[-1].group('ratio')}"
            ) from exc
    else:
        # A legacy prompt may only contain a bare preset such as ``16:9``.
        # Ignore product dimensions such as ``2.7 x 2.5`` unless they match a
        # known ratio preset.
        for match in reversed(list(_IMAGE_ASPECT_TOKEN_RE.finditer(text))):
            try:
                aspect_ratio = normalize_image_aspect_ratio(match.group(0))
            except ValueError:
                continue
            break

    resolution = normalize_batch_image_resolution(default_resolution)
    resolution_matches = list(_IMAGE_RESOLUTION_LABEL_RE.finditer(text))
    if resolution_matches:
        resolution = normalize_batch_image_resolution(
            resolution_matches[-1].group("resolution")
        )
    return {
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }


def parse_image_batch_versions(
    text,
    expected_count,
    *,
    default_aspect_ratio=DEFAULT_BATCH_IMAGE_ASPECT_RATIO,
    default_resolution=DEFAULT_BATCH_IMAGE_RESOLUTION,
):
    """Parse prompt versions and attach one validated image config to each."""

    versions = parse_version_document(text, expected_count)
    cleaned_versions = [
        strip_image_batch_settings(prompt)
        for prompt in versions
    ]
    validate_versions(cleaned_versions, expected_count=expected_count)
    return [
        {
            "prompt": cleaned_prompt,
            **extract_image_batch_settings(
                raw_prompt,
                default_aspect_ratio=default_aspect_ratio,
                default_resolution=default_resolution,
            ),
        }
        for raw_prompt, cleaned_prompt in zip(versions, cleaned_versions)
    ]


def chinese_number(value):
    """Render the small Chinese ordinal range used by the history document."""

    number = int(value)
    if number <= 0 or number > MAX_BATCH_PROMPT_COUNT:
        raise ValueError("版本编号超出支持范围")
    if number < 10:
        return _digit_name(number)
    if number < 20:
        return "十" if number == 10 else "十" + _digit_name(number % 10)
    tens, remainder = divmod(number, 10)
    return _digit_name(tens) + "十" + (
        _digit_name(remainder) if remainder else ""
    )


def version_label(value):
    return f"第{chinese_number(value)}版"


def _digit_name(value):
    for name, number in _CHINESE_DIGITS.items():
        if number == value:
            return name
    raise ValueError("版本编号不是有效数字")


def _chinese_to_int(value):
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    if not text:
        return None
    if text == "十":
        return 10
    if "百" in text:
        hundreds, remainder = text.split("百", 1)
        hundred_value = _CHINESE_DIGITS.get(hundreds or "一")
        if hundred_value is None:
            return None
        tail = _chinese_to_int(remainder) if remainder else 0
        return hundred_value * 100 + (tail or 0)
    if "十" in text:
        tens, remainder = text.split("十", 1)
        tens_value = _CHINESE_DIGITS.get(tens or "一")
        if tens_value is None:
            return None
        tail = _CHINESE_DIGITS.get(remainder, 0) if remainder else 0
        return tens_value * 10 + tail
    if len(text) == 1:
        return _CHINESE_DIGITS.get(text)
    return None


def validate_versions(
    versions,
    expected_count=None,
    max_bytes=MAX_BATCH_PROMPT_VERSION_BYTES,
):
    """Return clean versions or raise a user-facing validation error."""

    if not isinstance(versions, (list, tuple)):
        raise ValueError("模型返回的批量提示词不是版本列表")
    normalized = [str(item or "").strip() for item in versions]
    if expected_count is not None and len(normalized) != int(expected_count):
        raise ValueError(
            f"模型返回了 {len(normalized)} 个版本，期望 {int(expected_count)} 个"
        )
    if not normalized or any(not item for item in normalized):
        raise ValueError("批量提示词版本不能是空内容")
    duplicate_indexes = {
        item
        for item in normalized
        if normalized.count(item) > 1
    }
    if duplicate_indexes:
        raise ValueError("批量提示词版本不能完全重复")
    for index, item in enumerate(normalized, start=1):
        size = len(item.encode("utf-8"))
        if size > max_bytes:
            raise ValueError(
                f"{version_label(index)}超过 {max_bytes} 字节限制"
            )
    return normalized


def format_versions(versions):
    """Format validated versions for the GoFastDFS text document."""

    # Model relays occasionally double-escape line breaks as the two literal
    # characters ``\n``. Store real newlines so the history file remains
    # readable and the parameter lines can be edited without ambiguity.
    normalized = validate_versions(
        [normalize_prompt_newlines(item) for item in versions]
    )
    return "\n\n".join(
        f"{version_label(index)}：{content}"
        for index, content in enumerate(normalized, start=1)
    )


def _strip_code_fence(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json|text|markdown)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _json_candidates(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        yield value


def _value_from_item(item):
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    for key in (
        "prompt",
        "content",
        "text",
        "value",
        "final_prompt",
        "description",
    ):
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _versions_from_json(value):
    if isinstance(value, list):
        return [
            extracted
            for item in value
            if (extracted := _value_from_item(item)) not in (None, "")
        ]
    if not isinstance(value, dict):
        return None
    for key in ("versions", "prompts", "items", "results", "data"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return _versions_from_json(candidate)
    numbered = []
    for key, item in value.items():
        match = re.search(
            r"(?:第\s*(\d+|[零一二三四五六七八九十百两]+)\s*版|"
            r"version\s*(\d+))",
            str(key),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        raw_number = match.group(1) or match.group(2)
        number = _chinese_to_int(raw_number)
        content = _value_from_item(item)
        if number is not None and content not in (None, ""):
            numbered.append((number, content))
    if numbered:
        return [item for _number, item in sorted(numbered)]
    single = _value_from_item(value)
    return [single] if single not in (None, "") else None


def parse_version_document(text, expected_count):
    """Parse an edited GoFastDFS document with canonical version headings."""

    expected_count = parse_batch_prompt_count(expected_count)
    value = _strip_code_fence(normalize_prompt_newlines(text))
    matches = list(_BATCH_HEADING_RE.finditer(value))
    if not matches:
        if expected_count == 1 and value:
            return validate_versions([value], expected_count=1)
        matches = list(_BATCH_INLINE_HEADING_RE.finditer(value))
        if not matches:
            raise ValueError("请使用“第一版：...”格式编辑批量提示词")

    def parse_matches(heading_matches):
        if len(heading_matches) != expected_count:
            raise ValueError(
                f"批量提示词版本数为 {len(heading_matches)}，"
                f"期望 {expected_count} 个"
            )
        versions = []
        for index, match in enumerate(heading_matches):
            start = match.end()
            end = (
                heading_matches[index + 1].start()
                if index + 1 < len(heading_matches)
                else len(value)
            )
            content = value[start:end].strip()
            raw_number = match.group("chinese") or match.group("number")
            number = _chinese_to_int(raw_number)
            if number != index + 1:
                raise ValueError("批量提示词版本编号必须从第一版连续排列")
            versions.append(content)
        return validate_versions(versions, expected_count=expected_count)

    try:
        return parse_matches(matches)
    except ValueError as strict_error:
        # Preserve the strict parser's error for ordinary malformed content,
        # but accept a legacy single-line document when the fallback contains
        # the complete continuous version sequence.
        inline_matches = list(_BATCH_INLINE_HEADING_RE.finditer(value))
        if inline_matches and inline_matches != matches:
            try:
                return parse_matches(inline_matches)
            except ValueError:
                pass
        raise strict_error


def parse_model_versions(text, expected_count):
    """Parse a model response into exactly ``expected_count`` prompt versions."""

    expected_count = parse_batch_prompt_count(expected_count)
    value = _strip_code_fence(text)
    for candidate in _json_candidates(value):
        versions = _versions_from_json(candidate)
        if versions is None:
            continue
        try:
            return validate_versions(versions, expected_count=expected_count)
        except ValueError:
            raise
    return parse_version_document(value, expected_count)
