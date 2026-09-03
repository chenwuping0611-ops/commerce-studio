import os
import json
import re
import tempfile
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from sqlalchemy import inspect

from applications import create_app
from applications.amazon_ai.file_text import (
    read_excel_file,
    read_text_file,
    SUPPORTED_EXTENSIONS,
)
from applications.amazon_ai.competitor_text import fetch_competitor_pages
from applications.amazon_ai.permissions import AMAZON_AI_PERMISSION_CODES
from applications.amazon_ai.service import (
    AMAZON_GLOBAL_CHAT_MODEL_CODE,
    _build_responses_body,
    _product_context,
    _model_snapshot,
    _result_filename,
    global_chat_model_state,
)
from applications.extensions import db
from applications.view.amazon_ai.routes import _task_display_id
from applications.studio.provider_client import (
    KuaipaoClient,
    ProviderClient,
    ProviderRequestError,
    ToApisClient,
    extract_chat_content,
)
from applications.studio.provider_catalog import (
    KUAIPAO_IMAGE_EDIT_URL,
    KUAIPAO_IMAGE_GENERATION_URL,
)
from applications.models import (
    AmazonAiTask,
    Power,
    Role,
    StudioModel,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)
from sqlalchemy.orm import configure_mappers
import pandas


def _model(code, enabled=1, provider_enabled=1, api_key="test-key"):
    provider = SimpleNamespace(
        id=11,
        name="Smoke Provider",
        enabled=provider_enabled,
        api_key=api_key,
        dept_id=7,
    )
    return SimpleNamespace(
        id=22,
        name="Smoke Chat",
        model_code=code,
        media_type="CHAT",
        enabled=enabled,
        provider_id=provider.id,
        provider=provider,
    )


def _state_for(model):
    setting_query = MagicMock()
    setting_query.filter_by.return_value.first.return_value = SimpleNamespace(
        setting_value=str(model.id)
    )
    model_query = MagicMock()
    model_query.join.return_value.filter.return_value.first.return_value = model
    model_class = SimpleNamespace(
        id=MagicMock(name="StudioModel.id"),
        media_type=MagicMock(name="StudioModel.media_type"),
        query=model_query,
    )
    return patch.multiple(
        "applications.amazon_ai.service",
        StudioSetting=SimpleNamespace(query=setting_query),
        StudioModel=model_class,
        StudioProvider=SimpleNamespace(dept_id=MagicMock(name="provider_dept_id")),
    )


def main():
    app = create_app()
    with app.app_context():
        configure_mappers()
        display_time = SimpleNamespace(
            id=123,
            finished_at=datetime(2026, 8, 27, 11, 2),
            created_at=datetime(2026, 8, 27, 10, 58),
            updated_at=datetime(2026, 8, 27, 11, 3),
            task_code="internal-display-test",
        )
        assert _task_display_id(display_time) == "123"
        assert _task_display_id(
            SimpleNamespace(
                id=None,
                finished_at=None,
                created_at=datetime(2026, 8, 27, 10, 58),
                updated_at=None,
                task_code="internal-display-test",
            )
        ) == "internal-display-test"
        assert _task_display_id(
            SimpleNamespace(
                id=124,
                task_type="BASIC_INFO_CORRECT",
                result_refs_json=json.dumps(
                    {"response_filename": "暴风机.txt"},
                    ensure_ascii=False,
                ),
                finished_at=datetime(2026, 8, 27, 11, 2),
                created_at=datetime(2026, 8, 27, 10, 58),
                updated_at=None,
                task_code="internal-basic-info-test",
            )
        ) == "暴风机.txt"
        assert _result_filename(
            SimpleNamespace(
                id=125,
                task_type="COMPETITOR_ANALYZE",
                title="125",
                finished_at=datetime(2026, 8, 27, 11, 2),
                created_at=datetime(2026, 8, 27, 10, 58),
                updated_at=None,
                task_code="internal-display-test",
            )
        ) == "125.txt"
        assert "amazon_ai_workspace_task" in db.metadata.tables
        assert any(
            rule.rule == "/amazon-ai/api/tasks"
            for rule in app.url_map.iter_rules()
        )
        powers = Power.query.filter(
            Power.code.in_(AMAZON_AI_PERMISSION_CODES)
        ).all()
        assert {power.code for power in powers} == set(AMAZON_AI_PERMISSION_CODES)
        admin_role = Role.query.filter_by(code="admin").first()
        assert admin_role is not None
        assert AMAZON_AI_PERMISSION_CODES <= {
            power.code
            for power in admin_role.power
            if power and power.enable != 0
        }

        no_model_setting = MagicMock()
        no_model_setting.filter_by.return_value.first.return_value = None
        with patch(
            "applications.amazon_ai.service.StudioSetting",
            SimpleNamespace(query=no_model_setting),
        ):
            state = global_chat_model_state()
            assert state["allowed"] is False
            assert state["configured"] is False

        wrong_model = _model("gpt-5.5")
        with _state_for(wrong_model):
            state = global_chat_model_state()
            assert state["code_matches"] is True
            assert state["allowed"] is True

        correct_model = _model(AMAZON_GLOBAL_CHAT_MODEL_CODE)
        with _state_for(correct_model):
            state = global_chat_model_state()
            assert state["code_matches"] is True
            assert state["allowed"] is True

        product = SimpleNamespace(
            name="核心卖点测试产品",
            code="CORE-001",
            brand="测试品牌",
            description="完整产品资料",
            product_profile="完整产品档案",
            core_selling_points="只允许引用的核心卖点",
            product_memory="完整产品记忆",
            generation_rules="完整生成规则",
            forbidden_rules="完整禁止规则",
        )
        core_context = _product_context(
            product,
            core_selling_points_only=True,
        )
        assert core_context == "核心卖点：只允许引用的核心卖点"
        assert "完整产品资料" not in core_context
        assert "完整产品档案" not in core_context
        assert "完整产品记忆" not in core_context
        # The default context is used by competitor/basic-info flows and
        # intentionally contains the full product fact set.
        assert "只允许引用的核心卖点" in _product_context(product)

        responses_body = ProviderClient._chat_body_to_responses(
            {
                "model": "gpt-5.4",
                "messages": [
                    {"role": "system", "content": "遵守 Skill 规则"},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "分析这个 Amazon 链接：https://www.amazon.com/dp/B000000001",
                            },
                            {
                                "type": "input_file",
                                "file_url": "https://files.example/skill.md",
                            },
                        ],
                    },
                ],
                "max_tokens": 1200,
                "temperature": 0.2,
                "tools": [{"type": "web_search"}],
            }
        )
        assert responses_body["model"] == "gpt-5.4"
        assert responses_body["instructions"] == "遵守 Skill 规则"
        assert responses_body["tools"] == [{"type": "web_search"}]
        assert responses_body["max_output_tokens"] == 1200
        assert "temperature" not in responses_body
        response_content = responses_body["input"][0]["content"]
        assert response_content[0]["type"] == "input_text"
        assert response_content[1]["type"] == "input_file"

        response_skill = SimpleNamespace(
            id=101,
            content="# 竞品分析 Skill 规则",
            prompt_template="",
            storage_asset_id=None,
        )
        response_asset = SimpleNamespace(
            status="ACTIVE",
            expires_at=None,
            public_url="https://files.example/competitor-data.md",
        )
        with patch(
            "applications.amazon_ai.service._skill_file_url",
            return_value="https://files.example/skill.md",
        ):
            competitor_body = _build_responses_body(
                SimpleNamespace(model_code="gpt-5.4"),
                response_skill,
                [response_asset],
                (
                    "竞品 A：https://www.amazon.com/dp/B000000001\n"
                    "竞品 B：https://www.amazon.com/dp/B000000002"
                ),
                web_search=True,
            )
        competitor_content = competitor_body["input"][0]["content"]
        assert [item["type"] for item in competitor_content] == [
            "input_file",
            "input_file",
            "input_text",
        ]
        assert (
            competitor_content[0]["file_url"]
            == "https://files.example/skill.md"
        )
        assert (
            competitor_content[1]["file_url"]
            == "https://files.example/competitor-data.md"
        )
        assert competitor_body["tools"] == [{"type": "web_search"}]
        assert "B000000001" in competitor_content[2]["text"]
        assert "B000000002" in competitor_content[2]["text"]
        inline_skill_body = _build_responses_body(
            SimpleNamespace(model_code="gpt-5.4"),
            SimpleNamespace(
                id=102,
                content="# 数据库中的自定义 Skill",
                prompt_template="",
                storage_asset_id=None,
            ),
            [],
            "使用这个自定义 Skill。",
            user=User.query.filter_by(username="admin").first(),
        )
        assert inline_skill_body["input"][0]["content"][0]["type"] == (
            "input_text"
        )
        assert "数据库中的自定义 Skill" in (
            inline_skill_body["input"][0]["content"][0]["text"]
        )
        toapis_client = ProviderClient(
            SimpleNamespace(
                base_url="https://toapis.com",
                api_key="test-key",
                generation_path="/v1/images/generations",
                result_path=None,
                balance_path=None,
                token_balance_path=None,
                auth_header="Authorization",
                auth_prefix="Bearer",
                timeout=180,
            )
        )
        assert isinstance(toapis_client, ToApisClient)
        with patch.object(toapis_client, "_request", return_value={}) as request:
            toapis_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.6-sol",
                    generation_path="/v1/chat/completions",
                ),
                {
                    "model": "gpt-5.6-sol",
                    "messages": [{"role": "user", "content": "测试"}],
                    "max_tokens": 800,
                    "temperature": 0.2,
                    "top_p": 1,
                },
            )
            gpt56_body = request.call_args.args[2]
            assert request.call_args.args[1] == "/v1/chat/completions"
            assert gpt56_body["max_completion_tokens"] == 800
            assert "max_tokens" not in gpt56_body
            assert "temperature" not in gpt56_body
            assert "top_p" not in gpt56_body
            assert gpt56_body["reasoning_effort"] == "medium"

            request.reset_mock()
            toapis_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.5",
                    generation_path="/v1/chat/completions",
                ),
                {
                    "model": "gpt-5.5",
                    "messages": [{"role": "user", "content": "测试"}],
                    "max_tokens": 128001,
                },
            )
            gpt55_body = request.call_args.args[2]
            assert gpt55_body["max_completion_tokens"] == 128000
            assert "max_tokens" not in gpt55_body

            request.reset_mock()
            stateful_chat_body = {
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "新的独立请求"}],
                "max_tokens": 800,
                "previous_response_id": "resp_old",
                "conversation": "conv_old",
                "session_id": "session_old",
                "store": True,
            }
            toapis_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.5",
                    generation_path="/v1/chat/completions",
                ),
                stateful_chat_body,
            )
            fresh_chat_body = request.call_args.args[2]
            assert "previous_response_id" not in fresh_chat_body
            assert "conversation" not in fresh_chat_body
            assert "session_id" not in fresh_chat_body
            assert "store" not in fresh_chat_body
            assert stateful_chat_body["previous_response_id"] == "resp_old"

        kuaipao_client = ProviderClient(
            SimpleNamespace(
                base_url="https://kuaipao.pro/v1",
                api_key="test-key",
                generation_path="/responses",
                result_path=None,
                balance_path=None,
                token_balance_path=None,
                auth_header="Authorization",
                auth_prefix="Bearer",
                timeout=180,
            )
        )
        assert isinstance(kuaipao_client, KuaipaoClient)
        with patch.object(kuaipao_client, "_request", return_value={}) as request:
            for model_code in (
                "gpt-5.4",
                "gpt-5.5",
                "gpt-5.6-sol",
                "gpt-5.6-terra",
            ):
                request.reset_mock()
                kuaipao_client.complete(
                    SimpleNamespace(
                        model_code=model_code,
                        media_type="CHAT",
                        generation_path="/v1/chat/completions",
                    ),
                    {
                        "model": model_code,
                        "messages": [{"role": "user", "content": "测试"}],
                        "max_tokens": 800,
                        "temperature": 0.2,
                        "top_p": 1,
                        "tools": [{"type": "web_search"}],
                    },
                )
                kuaipao_body = request.call_args.args[2]
                assert request.call_args.args[0] == "POST"
                assert request.call_args.args[1] == "/responses"
                assert kuaipao_body["model"] == model_code
                assert kuaipao_body["tools"] == [{"type": "web_search"}]
                assert kuaipao_body["input"][0]["role"] == "user"
                assert (
                    kuaipao_body["input"][0]["content"][0]["type"]
                    == "input_text"
                )
                assert kuaipao_body["max_output_tokens"] == 800
                assert "messages" not in kuaipao_body
                assert "temperature" not in kuaipao_body
                assert "top_p" not in kuaipao_body

            request.reset_mock()
            kuaipao_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.4",
                    media_type="CHAT",
                    generation_path="/responses",
                ),
                {
                    "model": "gpt-5.4",
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "测试"}
                            ],
                        }
                    ],
                    "max_output_tokens": 128000,
                },
            )
            assert request.call_args.args[2]["max_output_tokens"] == 128000

            request.reset_mock()
            kuaipao_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.4",
                    media_type="CHAT",
                    generation_path="/responses",
                ),
                {
                    "model": "gpt-5.4",
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "测试"}
                            ],
                        }
                    ],
                    "max_output_tokens": 128001,
                },
            )
            assert request.call_args.args[2]["max_output_tokens"] == 128000

            request.reset_mock()
            kuaipao_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.6-sol",
                    media_type="CHAT",
                    generation_path="/responses",
                ),
                {
                    "model": "gpt-5.6-sol",
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "测试"}
                            ],
                        }
                    ],
                    "max_output_tokens": 1200,
                    "temperature": 0.2,
                    "top_p": 1,
                },
            )
            direct_responses_body = request.call_args.args[2]
            assert "temperature" not in direct_responses_body
            assert "top_p" not in direct_responses_body
            assert direct_responses_body["reasoning_effort"] == "medium"

            request.reset_mock()
            stateful_response_body = {
                "model": "gpt-5.4",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "新的独立请求"}
                        ],
                    }
                ],
                "max_output_tokens": 1200,
                "previous_response_id": "resp_old",
                "conversation": {"id": "conv_old"},
                "thread_id": "thread_old",
                "store": True,
            }
            kuaipao_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.4",
                    media_type="CHAT",
                    generation_path="/responses",
                ),
                stateful_response_body,
            )
            fresh_response_body = request.call_args.args[2]
            assert "previous_response_id" not in fresh_response_body
            assert "conversation" not in fresh_response_body
            assert "thread_id" not in fresh_response_body
            assert fresh_response_body["store"] is False
            assert stateful_response_body["previous_response_id"] == "resp_old"

        with patch.object(
            kuaipao_client,
            "_download_reference_image",
            side_effect=[
                (b"image-one", "one.jpg", "image/jpeg"),
                (b"image-two", "two.png", "image/png"),
            ],
        ) as download_reference, patch.object(
            kuaipao_client,
            "_multipart_request",
            return_value={"data": [{"b64_json": "ZmFrZQ=="}]},
        ) as multipart_request:
            kuaipao_client.submit_generation(
                SimpleNamespace(
                    model_code="gpt-image2",
                    media_type="IMAGE",
                    generation_path=KUAIPAO_IMAGE_EDIT_URL,
                ),
                {
                    "model": "gpt-image2",
                    "prompt": "商品主图",
                    "n": 1,
                    "size": "4096x1680",
                    "resolution": "4k",
                    "reference_images": [
                        "https://cdn.example/one.jpg",
                        "https://cdn.example/two.png",
                    ],
                },
            )
            assert download_reference.call_count == 2
            assert multipart_request.call_args.args[:2] == (
                "POST",
                KUAIPAO_IMAGE_EDIT_URL,
            )
            multipart_kwargs = multipart_request.call_args.kwargs
            assert multipart_kwargs["data"]["model"] == "gpt-image-2-4k"
            assert multipart_kwargs["data"]["size"] == "4096x1680"
            assert "resolution" not in multipart_kwargs["data"]
            files = multipart_kwargs["files"]
            assert [item[0] for item in files] == ["image", "image"]
            assert [item[1][0] for item in files] == ["one.jpg", "two.png"]
            assert all(item[1][1].closed for item in files)

        with patch.object(
            kuaipao_client,
            "_request",
            return_value={},
        ) as image_request:
            kuaipao_client.submit_generation(
                SimpleNamespace(
                    model_code="gpt-image2",
                    media_type="IMAGE",
                    generation_path=KUAIPAO_IMAGE_EDIT_URL,
                ),
                {
                    "model": "gpt-image2",
                    "prompt": "无参考图生图",
                    "n": 1,
                    "size": "4096x4096",
                    "resolution": "1k",
                },
            )
            assert image_request.call_args.args[:2] == (
                "POST",
                KUAIPAO_IMAGE_GENERATION_URL,
            )
            assert image_request.call_args.args[2]["model"] == "gpt-image-2-1k"
            assert image_request.call_args.args[2]["size"] == "4096x4096"
            assert "resolution" not in image_request.call_args.args[2]
        try:
            kuaipao_client.complete(
                SimpleNamespace(
                    model_code="gpt-5.7",
                    media_type="CHAT",
                    generation_path="/v1/chat/completions",
                ),
                {
                    "model": "gpt-5.7",
                    "messages": [{"role": "user", "content": "不支持"}],
                },
            )
        except ProviderRequestError as exc:
            assert "gpt-5.4" in str(exc)
            assert "gpt-5.6-terra" in str(exc)
        else:
            raise AssertionError("Kuaipao accepted an unsupported model code")
        assert kuaipao_client._url("/responses") == (
            "https://kuaipao.pro/v1/responses"
        )
        assert kuaipao_client._url("/v1/responses") == (
            "https://kuaipao.pro/v1/responses"
        )
        fallback_model = SimpleNamespace(
            media_type="CHAT",
            generation_path=None,
            provider=SimpleNamespace(generation_path="/responses"),
        )
        assert _model_snapshot(fallback_model).generation_path == "/responses"
        assert extract_chat_content(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "Responses 正常"},
                        ],
                    }
                ]
            }
        ) == "Responses 正常"

        with tempfile.TemporaryDirectory(prefix="amazon-ai-smoke-") as directory:
            text_path = os.path.join(directory, "input.txt")
            with open(text_path, "w", encoding="utf-8") as file:
                file.write("产品标题\n手持冲击扳手")
            assert "手持冲击扳手" in read_text_file(text_path)
            markdown_path = os.path.join(directory, "competitor.md")
            with open(markdown_path, "w", encoding="utf-8") as file:
                file.write("# 竞品页面\n\n页面事实")
            assert "页面事实" in read_text_file(markdown_path)
            assert {
                ".md",
                ".txt",
                ".csv",
                ".tsv",
                ".xls",
                ".xlsx",
                ".xlsm",
                ".json",
                ".html",
                ".htm",
            } <= SUPPORTED_EXTENSIONS

            excel_path = os.path.join(directory, "input.xlsx")
            pandas.DataFrame(
                [{"关键词": "impact wrench", "搜索量": 100}]
            ).to_excel(excel_path, index=False)
            excel_text = read_excel_file(excel_path)
            assert "impact wrench" in excel_text
            assert "搜索量" in excel_text

        def fake_amazon_get(url, **kwargs):
            return SimpleNamespace(
                content=(
                    b"<html><head><title>Test Product</title></head>"
                    b"<body><h1>Test Product</h1><p>Visible page fact</p>"
                    b"</body></html>"
                ),
                encoding="utf-8",
                apparent_encoding="utf-8",
                raise_for_status=lambda: None,
                close=lambda: None,
            )

        with patch(
            "applications.amazon_ai.competitor_text.requests.Session.get",
            side_effect=fake_amazon_get,
        ):
            rendered = fetch_competitor_pages(
                [
                    "https://www.amazon.com/dp/B0FMK5TSC5",
                    "https://www.amazon.com/dp/B0FT37QK1V",
                ]
            )
        assert "# 竞品 A" in rendered
        assert "# 竞品 B" in rendered
        assert "Test Product" in rendered
        assert "Visible page fact" in rendered

        with patch(
            "applications.amazon_ai.competitor_text.requests.Session.get"
        ) as fetch:
            fetch.side_effect = RuntimeError("network not used in smoke")
            assert "HTTPS Amazon" in fetch_competitor_pages(
                ["https://example.com/product"]
            )

        admin = User.query.filter_by(username="admin").first()
        assert admin is not None
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(admin.id)
            session["_fresh"] = True
            # Simulate a browser session created before Amazon permissions
            # were initialized.
            session["permissions"] = ["studio:dashboard"]
        for path in (
            "/amazon-ai/",
            "/amazon-ai/dashboard",
            "/amazon-ai/competitor",
            "/amazon-ai/keyword",
            "/amazon-ai/review",
            "/amazon-ai/differentiation",
            "/amazon-ai/basic-info",
            "/amazon-ai/listing/create",
        ):
            assert client.get(path).status_code == 200, path
        for path in (
            "/amazon-ai/competitor",
            "/amazon-ai/keyword",
            "/amazon-ai/review",
            "/amazon-ai/differentiation",
            "/amazon-ai/basic-info",
            "/amazon-ai/listing/create",
        ):
            page = client.get(path).get_data(as_text=True)
            assert "listing_project_id" not in page
            assert "amazon-option-project" not in page
        listing_page = client.get(
            "/amazon-ai/listing/create"
        ).get_data(as_text=True)
        assert 'name="skill_id"' in listing_page
        assert client.get("/amazon-ai/listing/review").status_code == 404

        options_response = client.get("/amazon-ai/api/options")
        assert options_response.status_code == 200
        options_payload = options_response.json
        assert options_payload["success"] is True
        assert {"chat_models", "skills", "products"} <= set(
            options_payload["data"]
        )
        assert "api_key" not in json.dumps(
            options_payload,
            ensure_ascii=False,
        ).lower()
        assert "projects" not in options_payload["data"]
        expected_skill_codes = {
            "Amazon_Competitor_Analysis_Skill.md",
            "Amazon_Light_Differentiation_Skill.md",
            "Amazon_Listing_Writer_Skill.md",
        }
        retired_skill_codes = {
            "Amazon_Keyword_Analysis_Skill.md",
            "Amazon_Review_Analysis_Skill.md",
            "Amazon_Listing_Strategy_Integration.md",
            "Amazon_Listing_Audit_Skill.md",
        }
        actual_skill_codes = {
            skill.code
            for skill in StudioSkill.query.filter(
                StudioSkill.code.in_(
                    expected_skill_codes | retired_skill_codes
                )
            ).all()
            if skill.enabled == 1
        }
        assert actual_skill_codes == expected_skill_codes
        assert not StudioSkill.query.filter(
            StudioSkill.code.in_(retired_skill_codes)
        ).first()

        history_response = client.get("/amazon-ai/history")
        assert history_response.status_code == 200
        history_api_response = client.get(
            "/amazon-ai/api/history?page=1&page_size=1"
        )
        assert history_api_response.status_code == 200
        assert history_api_response.json["success"] is True
        assert AmazonAiTask.__tablename__ == "amazon_ai_workspace_task"
        amazon_tables = {
            name for name in inspect(db.engine).get_table_names()
            if name.startswith("amazon_")
        }
        assert amazon_tables == {
            "amazon_ai_workspace_task",
            "amazon_ai_task_source",
            "amazon_ai_task_dependency",
            "amazon_ai_task_asset",
        }

        ordinary = (
            User.query.filter(User.username != "admin")
            .order_by(User.id.asc())
            .first()
        )
        if ordinary:
            ordinary_has_amazon = any(
                power.code in AMAZON_AI_PERMISSION_CODES
                for role in ordinary.role
                if role.enable != 0
                for power in role.power
                if power.enable != 0
            )
            if not ordinary_has_amazon:
                with client.session_transaction() as session:
                    session["_user_id"] = str(ordinary.id)
                    session["_fresh"] = True
                    # A stale or manually tampered session must not grant
                    # Amazon access; the blueprint refreshes it from RBAC.
                    session["permissions"] = list(AMAZON_AI_PERMISSION_CODES)
                assert client.get("/amazon-ai/competitor").status_code == 403

    print("amazon ai smoke test passed")


if __name__ == "__main__":
    main()
