import json
from types import SimpleNamespace

from applications.studio.provider_client import (
    ProviderClient,
    is_responses_path,
)
from applications.view.studio.routes import (
    _product_usage_research_instruction,
    _product_usage_web_search_tools,
)


def main():
    product = SimpleNamespace(id=1, name="测试产品")

    kuaipao_model = SimpleNamespace(
        media_type="CHAT",
        model_code="gpt-5.4",
        generation_path="/responses",
        provider=SimpleNamespace(
            name="快跑AI",
            base_url="https://kuaipao.pro/v1",
            generation_path="/responses",
        ),
    )
    assert _product_usage_web_search_tools(kuaipao_model, product) == [
        {"type": "web_search"}
    ]
    assert "已启用 web_search" in _product_usage_research_instruction(True)

    chat_only_model = SimpleNamespace(
        media_type="CHAT",
        model_code="custom-chat",
        generation_path="/v1/chat/completions",
        capabilities=json.dumps({"supports_web_search": True}),
        provider=SimpleNamespace(
            name="自定义供应商",
            base_url="https://provider.example/v1",
            generation_path="/v1/chat/completions",
        ),
    )
    assert _product_usage_web_search_tools(chat_only_model, product) == []
    assert "没有声明 web_search 能力" in _product_usage_research_instruction(False)

    no_product_model = SimpleNamespace(
        media_type="CHAT",
        model_code="gpt-5.4",
        generation_path="/responses",
        provider=kuaipao_model.provider,
    )
    assert _product_usage_web_search_tools(no_product_model, None) == []

    response_body = ProviderClient._chat_body_to_responses(
        {
            "model": "gpt-5.4",
            "messages": [
                {"role": "system", "content": "只核验真实使用方式"},
                {"role": "user", "content": "分析产品握持方式"},
            ],
            "tools": [{"type": "web_search"}],
        }
    )
    assert response_body["tools"] == [{"type": "web_search"}]
    assert response_body["instructions"] == "只核验真实使用方式"
    assert is_responses_path("/responses") is True

    print("studio usage search smoke passed")


if __name__ == "__main__":
    main()
