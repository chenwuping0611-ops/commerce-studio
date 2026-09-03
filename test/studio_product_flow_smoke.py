"""Smoke checks for product selection, prompt context, and feedback updates."""

import json
from unittest.mock import patch

from applications import create_app
from applications.extensions import db
from applications.models import (
    StudioGenerationComment,
    StudioGenerationTask,
    StudioModel,
    StudioProduct,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)
from applications.studio import generation_service
from applications.studio.product_prompt import compose_prompt
from applications.view.studio import routes as studio_routes


class FakeGenerationClient:
    def __init__(self, provider):
        self.provider = provider

    def submit_generation(self, model, body):
        return {"id": "local-product-flow-smoke", "status": "queued"}


class FakeFeedbackClient:
    def __init__(self, provider):
        self.provider = provider

    def complete(self, model, body):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "analysis": "反馈确认产品字段需要更新",
                                "product_updates": {
                                    "core_selling_points": {
                                        "value": "反馈后的核心卖点",
                                        "reason": "操作者反馈",
                                    },
                                    "product_profile": {
                                        "value": "反馈后的产品档案",
                                        "reason": "视觉证据",
                                    },
                                    "product_memory": {
                                        "value": "反馈后的产品记忆",
                                        "reason": "长期约束",
                                    },
                                },
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


class FakePromptPlannerClient:
    last_body = None

    def __init__(self, provider):
        self.provider = provider

    def complete(self, model, body):
        type(self).last_body = body
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "final_prompt": "模型规划后的图片创作提示词",
                                "product_name": "本地测试产品",
                                "reference_instruction": "",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def _login_as(client, username, password="123456"):
    response = client.post(
        "/passport/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.data
    assert response.json["success"] is True, response.json


def main():
    app = create_app()
    client = app.test_client()

    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        product = StudioProduct.query.filter_by(
            code="LOCAL-LEAFBLOWER",
            enabled=1,
        ).first()
        assert admin is not None and product is not None

        root_image = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.model_code == "gpt-image-2",
                StudioModel.media_type == "IMAGE",
                StudioModel.enabled == 1,
                StudioProvider.dept_id == admin.dept_id,
                StudioProvider.enabled == 1,
            )
            .first()
        )
        root_video = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.model_code == "seedance-2",
                StudioModel.media_type == "VIDEO",
                StudioModel.enabled == 1,
                StudioProvider.dept_id == admin.dept_id,
                StudioProvider.enabled == 1,
            )
            .first()
        )
        assert root_image is not None and root_video is not None
        product_id = product.id
        product_core_selling_points = product.core_selling_points or ""
        root_image_id = root_image.id
        root_video_id = root_video.id
        root_image_provider_id = root_image.provider_id
        root_image_department_id = root_image.provider.dept_id
        root_video_department_id = root_video.provider.dept_id
        provider = StudioProvider.query.get(root_image_provider_id)
        assert provider is not None
        original_key = provider.api_key
        chat_setting = StudioSetting.query.filter_by(
            setting_key=studio_routes.GLOBAL_CHAT_MODEL_SETTING_KEY,
            dept_id=root_image_department_id,
        ).first()
        assert chat_setting is not None and chat_setting.setting_value
        chat_model_id = int(chat_setting.setting_value)
        chat_model = StudioModel.query.get(chat_model_id)
        assert chat_model is not None and chat_model.provider is not None
        chat_provider_id = chat_model.provider_id
        original_chat_key = chat_model.provider.api_key
        chat_model.provider.api_key = "local-product-flow-planner-key"
        generation_skill = (
            StudioSkill.query.filter(
                StudioSkill.enabled == 1,
                StudioSkill.media_type.in_(("IMAGE", "BOTH")),
                StudioSkill.code != "studio-feedback-quality",
            )
            .order_by(StudioSkill.id.asc())
            .first()
        )
        generation_skill_id = generation_skill.id if generation_skill else None
        generation_skill_prompt = (
            str(
                generation_skill.prompt_template
                or generation_skill.content
                or ""
            ).strip()
            if generation_skill
            else ""
        )
        generation_skill_marker = " ".join(
            generation_skill_prompt.split()
        )[:80]

        prompt = compose_prompt(
            product,
            "在庭院中展示产品",
            skill_prompt="保持真实商业摄影质感",
            media_type="IMAGE",
        )
        assert "核心卖点：" in prompt
        assert product.core_selling_points in prompt
        assert product.product_profile in prompt
        assert product.product_memory in prompt

        normalized = studio_routes._normalize_suggested_updates(
            json.dumps(
                {
                    "product_updates": {
                        "core_selling_points": {
                            "value": "规范化后的核心卖点",
                            "reason": "测试",
                        }
                    }
                },
                ensure_ascii=False,
            )
        )
        assert normalized["updates"]["core_selling_points"]["value"] == (
            "规范化后的核心卖点"
        )

        provider = StudioProvider.query.get(root_image_provider_id)
        provider.api_key = "local-product-flow-smoke-key"
        db.session.commit()

    _login_as(client, "admin")

    for path in ("/studio/image", "/studio/video"):
        page = client.get(path)
        assert page.status_code == 200, path
        page_text = page.get_data(as_text=True)
        assert "var isSuperAdmin = true;" in page_text
        if path.endswith("/image"):
            assert 'id="imageProduct" lay-ignore' in page_text
            assert 'id="imageSkill" lay-ignore' in page_text
        else:
            assert 'id="videoProduct" lay-ignore' in page_text
            assert 'id="videoSkill" lay-ignore' in page_text

    created_task_ids = []
    try:
        with patch.object(studio_routes, "ProviderClient", FakePromptPlannerClient):
            response = client.post(
                "/studio/api/prompt/prepare",
                json={
                    "media_type": "IMAGE",
                    "department_id": root_image_department_id,
                    "product_id": product_id,
                    "skill_id": generation_skill_id,
                    "skill_prompt": "浏览器伪造的 Skill 文本",
                    "prompt": "请生成一张产品广告图",
                },
            )
        assert response.status_code == 200, response.json
        planner_request = json.dumps(
            FakePromptPlannerClient.last_body,
            ensure_ascii=False,
        )
        planner_text = str(
            (FakePromptPlannerClient.last_body or {})
            .get("messages", [{}])[1]
            .get("content", [{}])[0]
            .get("text", "")
        )
        assert " ".join(product_core_selling_points.split()) in " ".join(
            planner_text.split()
        ), planner_request
        if generation_skill_prompt:
            assert generation_skill_marker in " ".join(
                planner_text.split()
            ), planner_request
            assert "浏览器伪造的 Skill 文本" not in planner_text

        for model_id, media_type, department_id in (
            (root_image_id, "IMAGE", root_image_department_id),
            (root_video_id, "VIDEO", root_video_department_id),
        ):
            response = None
            with patch.object(
                generation_service,
                "ProviderClient",
                FakeGenerationClient,
            ):
                response = client.post(
                    "/studio/api/generate",
                    json={
                        "media_type": media_type,
                        "model_id": model_id,
                        "department_id": department_id,
                        "product_id": product_id,
                        "prompt": f"{media_type} 产品关联测试",
                        "prepared_prompt": f"{media_type} 产品关联测试",
                    },
                )
            assert response.status_code == 200, response.json
            task = response.json["data"]
            assert task["product_id"] == product_id
            created_task_ids.append(task["id"])

        with app.app_context():
            feedback_task = StudioGenerationTask.query.filter_by(
                task_code="LIMG001",
                status="SUCCEEDED",
            ).first()
            assert feedback_task is not None and feedback_task.product_id == product_id
            feedback_task_code = feedback_task.task_code
            feedback_task_id = feedback_task.id
            feedback_model_id = feedback_task.model_id
            feedback_provider = StudioProvider.query.filter_by(
                id=StudioModel.query.get(
                    feedback_model_id
                ).provider_id
            ).first()
            feedback_provider_id = feedback_provider.id
            original_feedback_key = feedback_provider.api_key
            feedback_provider.api_key = "local-feedback-flow-smoke-key"
            original_fields = {
                field: getattr(
                    StudioProduct.query.get(product_id),
                    field,
                )
                for field in (
                    "core_selling_points",
                    "product_profile",
                    "product_memory",
                )
            }
            existing_comment_ids = {
                comment.id
                for comment in StudioGenerationComment.query.filter_by(
                    generation_task_id=feedback_task_id
                ).all()
            }
            db.session.commit()

        with patch.object(studio_routes, "ProviderClient", FakeFeedbackClient):
            response = client.post(
                f"/studio/api/tasks/{feedback_task_code}/comments/analyze",
                json={"feedback": "请修正产品卖点、档案和长期记忆"},
            )
        assert response.status_code == 200, response.json

        with app.app_context():
            refreshed_product = StudioProduct.query.get(product_id)
            assert refreshed_product.core_selling_points == "反馈后的核心卖点"
            assert refreshed_product.product_profile == "反馈后的产品档案"
            assert refreshed_product.product_memory == "反馈后的产品记忆"
    finally:
        with app.app_context():
            if created_task_ids:
                StudioGenerationTask.query.filter(
                    StudioGenerationTask.id.in_(created_task_ids)
                ).delete(synchronize_session=False)

            if "existing_comment_ids" in locals():
                StudioGenerationComment.query.filter(
                    StudioGenerationComment.generation_task_id == feedback_task_id,
                    ~StudioGenerationComment.id.in_(existing_comment_ids or {-1}),
                ).delete(synchronize_session=False)
            if "original_fields" in locals():
                restored_product = StudioProduct.query.get(product_id)
                for field, value in original_fields.items():
                    setattr(restored_product, field, value)
            if "original_feedback_key" in locals():
                feedback_provider = StudioProvider.query.get(feedback_provider_id)
                feedback_provider.api_key = original_feedback_key
            chat_provider = StudioProvider.query.get(chat_provider_id)
            if chat_provider:
                chat_provider.api_key = original_chat_key
            provider = StudioProvider.query.get(root_image_provider_id)
            if provider:
                provider.api_key = original_key
            db.session.commit()

    print("studio product flow smoke test passed")


if __name__ == "__main__":
    main()
