"""Unit checks for batch prompt count and document parsing."""

import json
import re

from applications.studio.batch_prompt import (
    BATCH_PROMPT_STYLE_CUSTOM_VALUE,
    MAX_BATCH_PROMPT_VERSION_BYTES,
    batch_prompt_filename,
    extract_image_batch_settings,
    format_versions,
    normalize_batch_prompt_style,
    parse_batch_prompt_count,
    parse_image_batch_versions,
    parse_model_versions,
    parse_version_document,
    strip_image_batch_settings,
    version_label,
)
from applications.studio.request_builder import image_size_for_aspect_ratio


def main():
    assert batch_prompt_filename("产品/名称", 1) == "产品_名称\u00b7R01.txt"
    assert batch_prompt_filename("产品/名称", 12) == "产品_名称\u00b7R12.txt"
    random_name = batch_prompt_filename()
    assert re.fullmatch(r"[A-Za-z0-9]{6}\.txt", random_name)

    assert parse_batch_prompt_count("1") == 1
    assert parse_batch_prompt_count(7) == 7
    assert parse_batch_prompt_count(10) == 10
    assert parse_batch_prompt_count(" 50 ") == 50
    assert parse_batch_prompt_count(0) == 10
    assert parse_batch_prompt_count(" 0 ") == 10

    for value in (None, "", "abc", -1, 51):
        try:
            parse_batch_prompt_count(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"count should be rejected: {value!r}")

    assert version_label(1) == "第一版"
    assert version_label(10) == "第十版"
    assert version_label(21) == "第二十一版"

    json_document = (
        '{"versions":["保持产品颜色一致的主图提示词",'
        '"展示背面结构的详情图提示词"]}'
    )
    assert parse_model_versions(json_document, 2) == [
        "保持产品颜色一致的主图提示词",
        "展示背面结构的详情图提示词",
    ]

    text_document = "第一版：主图构图\n\n第二版：背面细节"
    parsed = parse_version_document(text_document, 2)
    assert parsed == ["主图构图", "背面细节"]
    assert format_versions(parsed) == text_document
    escaped_document = format_versions(
        ["第一行\\n第二行\\n画布比例：2.44:1\\n图片质量：2K"]
    )
    assert "\\n" not in escaped_document
    assert "第一行\n第二行\n画布比例：2.44:1\n图片质量：2K" in (
        escaped_document
    )

    image_version = (
        "画布比例：16:9\n"
        "图片质量：4K\n"
        "保持产品颜色、结构和配件一致，生成横向电商详情图。"
    )
    assert extract_image_batch_settings(image_version) == {
        "aspect_ratio": "16:9",
        "resolution": "4k",
    }
    assert strip_image_batch_settings(image_version) == (
        "保持产品颜色、结构和配件一致，生成横向电商详情图。"
    )
    image_versions = parse_image_batch_versions(
        "第一版：" + image_version + "\n\n"
        "第二版：画布比例：1:1\n图片质量：1K\n正方形产品主视觉",
        2,
    )
    assert image_versions[0]["aspect_ratio"] == "16:9"
    assert image_versions[0]["resolution"] == "4k"
    assert image_versions[0]["prompt"] == (
        "保持产品颜色、结构和配件一致，生成横向电商详情图。"
    )
    assert image_versions[1]["aspect_ratio"] == "1:1"
    assert image_versions[1]["resolution"] == "1k"
    assert image_versions[1]["prompt"] == "正方形产品主视觉"
    inline_versions = parse_image_batch_versions(
        "第一版：画布比例：2.44:1\n图片质量：2K\n横向主视觉  "
        "第二版：画布比例：16:9\n图片质量：4K\n生活方式场景",
        2,
    )
    assert inline_versions[0]["aspect_ratio"] == "2.44:1"
    assert inline_versions[0]["resolution"] == "2k"
    assert inline_versions[0]["prompt"] == "横向主视觉"
    assert inline_versions[1]["aspect_ratio"] == "16:9"
    assert inline_versions[1]["resolution"] == "4k"
    assert inline_versions[1]["prompt"] == "生活方式场景"
    legacy_image = parse_image_batch_versions(
        "第一版：只包含产品信息，没有参数标记",
        1,
    )
    assert legacy_image[0]["aspect_ratio"] == "2.44:1"
    assert legacy_image[0]["resolution"] == "2k"
    assert image_size_for_aspect_ratio("1:1") == "4096x4096"
    assert image_size_for_aspect_ratio("16:9") == "3840x2160"
    assert image_size_for_aspect_ratio("9:16") == "2160x3840"
    assert image_size_for_aspect_ratio("2.44:1") == "4096x1680"

    for invalid in (
        "第二版：缺少第一版",
        "第一版：重复\n\n第二版：重复",
        "第一版：只有一个版本",
    ):
        try:
            parse_version_document(invalid, 2)
        except ValueError:
            pass
        else:
            raise AssertionError(f"document should be rejected: {invalid!r}")

    exact_limit = "a" * MAX_BATCH_PROMPT_VERSION_BYTES
    assert parse_model_versions(
        json.dumps({"versions": [exact_limit]}, ensure_ascii=False),
        1,
    ) == [exact_limit]

    oversized = exact_limit + "b"
    try:
        parse_model_versions(
            json.dumps({"versions": [oversized]}, ensure_ascii=False),
            1,
        )
    except ValueError as exc:
        assert "字节限制" in str(exc)
    else:
        raise AssertionError("5001-byte version should be rejected")

    assert normalize_batch_prompt_style("") == ""
    assert normalize_batch_prompt_style("  高端商业摄影  ") == "高端商业摄影"
    assert normalize_batch_prompt_style(BATCH_PROMPT_STYLE_CUSTOM_VALUE) == (
        BATCH_PROMPT_STYLE_CUSTOM_VALUE
    )


if __name__ == "__main__":
    main()
