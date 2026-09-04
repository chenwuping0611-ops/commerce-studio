from types import SimpleNamespace
from unittest.mock import patch

from applications.studio.provider_catalog import (
    JIEKOU_RESPONSES_TEXT_MODEL_CODES,
    catalog_for_provider,
    provider_catalog_key,
)
from applications.studio.provider_client import (
    JiekouClient,
    ProviderClient,
    ProviderRequestError,
    extract_chat_content,
)
from applications.studio.generation_service import _extract_outputs
from applications.studio.request_builder import build_request_body


def _provider():
    return SimpleNamespace(
        name="接口AI",
        base_url="https://api.jiekou.ai/openai/v1",
        api_key=None,
        generation_path="/responses",
        result_path=None,
        balance_path="/v1/user/balance",
        token_balance_path="/v1/balance",
        auth_header="Authorization",
        auth_prefix="Bearer",
        timeout=600,
    )


def _model(code):
    return SimpleNamespace(
        model_code=code,
        media_type="CHAT",
        generation_path="/responses",
        provider=_provider(),
    )


def main():
    provider = _provider()
    assert provider_catalog_key(provider) == "jiekou"
    catalog = catalog_for_provider(provider)
    catalog_models = catalog.models()
    assert [
        item.code
        for item in catalog_models
        if item.media_type == "CHAT"
    ] == list(JIEKOU_RESPONSES_TEXT_MODEL_CODES)
    assert [
        item.code
        for item in catalog_models
        if item.media_type == "IMAGE"
    ] == ["gpt-image2"]
    assert all(
        item.generation_path == "/responses"
        and item.result_path is None
        and item.capabilities["supports_input_file"] is True
        and item.capabilities["supports_web_search"] is True
        for item in catalog_models
        if item.media_type == "CHAT"
    )

    assert extract_chat_content(
        {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [
                        {"type": "summary_text", "text": "内部推理不应展示"},
                    ],
                },
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "text": "工具调用内容不应展示",
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "# 最终竞品分析报告",
                        },
                        {
                            "type": "output_text",
                            "text": "\n\n第二段",
                        },
                    ],
                },
            ],
        }
    ) == "# 最终竞品分析报告\n\n第二段"
    assert extract_chat_content(
        {
            "output_text": None,
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "中转响应正文"},
                    ],
                },
            ],
        }
    ) == "中转响应正文"
    assert extract_chat_content(
        SimpleNamespace(output_text="SDK output_text 正文")
    ) == "SDK output_text 正文"

    client = ProviderClient(provider)
    assert isinstance(client, JiekouClient)
    assert client._url("/responses") == (
        "https://api.jiekou.ai/openai/v1/responses"
    )

    native_body = {
        "model": "gpt-5.5",
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "file_url": "https://files.example/skill.md",
                    },
                    {
                        "type": "input_image",
                        "image_url": "https://files.example/product.jpg",
                        "detail": "high",
                    },
                    {
                        "type": "input_text",
                        "text": "执行竞品分析",
                    },
                ],
            }
        ],
        "tools": [{"type": "web_search"}],
        "store": True,
        "max_output_tokens": 128000,
    }
    with patch.object(client, "_request", return_value={}) as request:
        client.complete(_model("gpt-5.5"), native_body)
    sent = request.call_args.args[2]
    assert request.call_args.args[:2] == ("POST", "/responses")
    assert sent["model"] == "gpt-5.5"
    assert sent["input"] == native_body["input"]
    assert sent["tools"] == [{"type": "web_search"}]
    assert sent["store"] is False
    assert sent["max_output_tokens"] == 128000

    with patch.object(client, "_request", return_value={}) as request:
        client.complete(
            _model("gpt-5.6-sol"),
            {
                "model": "gpt-5.6-sol",
                "messages": [
                    {"role": "system", "content": "遵守 Skill"},
                    {"role": "user", "content": "分析产品"},
                ],
                "max_tokens": 1200,
                "temperature": 0.2,
                "top_p": 1,
            },
        )
    sent = request.call_args.args[2]
    assert sent["model"] == "gpt-5.6-sol"
    assert sent["instructions"] == "遵守 Skill"
    assert sent["input"][0]["content"] == [
        {"type": "input_text", "text": "分析产品"}
    ]
    assert sent["max_output_tokens"] == 1200
    assert sent["reasoning_effort"] == "medium"
    assert "messages" not in sent
    assert "temperature" not in sent
    assert "top_p" not in sent

    try:
        client.complete(
            _model("gpt-5.7"),
            {"model": "gpt-5.7", "input": [{"role": "user", "content": []}]},
        )
    except ProviderRequestError as exc:
        assert "gpt-5.5" in str(exc)
        assert "gpt-5.4-mini" in str(exc)
        assert "gpt-5.6-luna" in str(exc)
    else:
        raise AssertionError("接口AI接受了目录之外的模型")

    try:
        client.submit_generation(_model("gpt-5.5"), {})
    except ProviderRequestError as exc:
        assert "只支持文本 Responses 模型" in str(exc)
    else:
        raise AssertionError("接口AI接受了图片或视频任务提交")

    image_model = SimpleNamespace(
        model_code="gpt-image2",
        media_type="IMAGE",
        generation_path=(
            "https://api.jiekou.ai/v3/gpt-image-2-edit"
        ),
        provider=provider,
    )
    image_body = build_request_body(
        image_model,
        {
            "prompt": "生成产品主图",
            "count": 1,
            "aspect_ratio": "1:1",
            "resolution": "4k",
            "reference_images": [
                "https://files.example/product.png",
            ],
        },
    )
    assert "model" not in image_body
    assert image_body["n"] == 1
    assert image_body["image"] == [
        "https://files.example/product.png",
    ]
    assert image_body["size"] == "auto"
    assert image_body["quality"] == "high"
    assert image_body["background"] == "opaque"
    assert image_body["output_format"] == "png"
    assert image_body["prompt"].endswith(
        "输出规格：画布分辨率必须为4096X4096像素，宽高比约为1:1。"
    )

    with patch.object(client, "_request", return_value={"images": ["url"]}) as request:
        client.complete(image_model, image_body)
    assert request.call_args.args[:2] == (
        "POST",
        "https://api.jiekou.ai/v3/gpt-image-2-edit",
    )
    sent = request.call_args.args[2]
    assert sent == image_body
    assert _extract_outputs(
        {
            "size": "1959x803",
            "images": [
                "https://signed.example/generated.png?signature=redacted",
            ],
        }
    ) == [
        {
            "url": "https://signed.example/generated.png?signature=redacted",
            "data": None,
            "format": None,
        }
    ]

    print("jiekou provider unit passed")


if __name__ == "__main__":
    main()
