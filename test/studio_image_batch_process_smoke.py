"""Integration smoke checks for image batch prompt processing."""

import threading
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.common.storage import StorageError
from applications.common.scope import effective_permission_codes
from applications.extensions import db
from applications.models import (
    StudioBatchPrompt,
    StudioModel,
    StudioProvider,
    User,
)
from applications.view.studio import routes as studio_routes


def _set_session(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = sorted(effective_permission_codes(user))


def main():
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        assert admin is not None
        model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.model_code == "gpt-image2",
                StudioModel.media_type == "IMAGE",
                StudioModel.enabled == 1,
                StudioProvider.enabled == 1,
                StudioProvider.name == "快跑AI",
                StudioProvider.dept_id == admin.dept_id,
            )
            .order_by(StudioModel.id.asc())
            .first()
        )
        assert model is not None
        provider = model.provider
        original_key = provider.api_key
        provider.api_key = "image-batch-process-smoke-key"

        batch_prompt = StudioBatchPrompt(
            dept_id=admin.dept_id,
            user_id=admin.id,
            media_type="IMAGE",
            image_aspect_ratio="2.44:1",
            image_resolution="2k",
            skill_prompt_snapshot=(
                "严格保持产品真实颜色、结构和两个钥匙扣，不得遗漏、变形或增加配件。"
            ),
            skill_name_snapshot="Amazon 电商批量详情图提示词 Skill",
            version_count=2,
            status="SUCCEEDED",
        )
        db.session.add(batch_prompt)
        db.session.commit()
        batch_prompt_id = batch_prompt.id

        document = (
            "第一版：画布比例：16:9\n图片质量：1K\n版本一产品详情图\n\n"
            "第二版：画布比例：1:1\n图片质量：4K\n版本二产品详情图"
        )
        calls = []
        call_counts = {}
        successful_ids = []
        lock = threading.Lock()

        def fake_create_generation(**kwargs):
            prompt = kwargs["prompt"]
            with lock:
                call_counts[prompt] = call_counts.get(prompt, 0) + 1
                calls.append(kwargs)
            task_id = 1000 + len(calls)
            successful_ids.append(task_id)
            return SimpleNamespace(
                id=task_id,
                task_code="fake-task-" + str(task_id),
            )

        class FakeTaskQuery:
            def all(self):
                return [
                    SimpleNamespace(
                        id=task_id,
                        task_code="fake-task-" + str(task_id),
                    )
                    for task_id in successful_ids
                ]

        def fake_task_dict(task):
            return {
                "id": task.id,
                "task_code": task.task_code,
                "media_type": "IMAGE",
                "status": "SUCCEEDED",
                "output_url": "https://files.example/" + task.task_code + ".png",
                "output_assets": [],
            }

        client = app.test_client()
        _set_session(client, admin)
        try:
            with patch.object(
                studio_routes,
                "_batch_prompt_content",
                return_value=(document, ""),
            ), patch.object(
                studio_routes,
                "complete_chat",
                side_effect=AssertionError(
                    "图片批量处理阶段不应再次调用语言模型"
                ),
            ), patch.object(
                studio_routes,
                "_generation_skill",
                side_effect=AssertionError(
                    "图片批量处理阶段不应读取 Skill"
                ),
            ), patch.object(
                studio_routes,
                "read_skill_text",
                side_effect=AssertionError(
                    "图片批量处理阶段不应读取 Skill 文件"
                ),
            ), patch.object(
                studio_routes,
                "create_generation",
                side_effect=fake_create_generation,
            ), patch.object(
                studio_routes,
                "_with_task_loaders",
                return_value=FakeTaskQuery(),
            ), patch.object(
                studio_routes,
                "_task_dict",
                side_effect=fake_task_dict,
            ), patch.object(
                studio_routes,
                "_can_read_task",
                return_value=True,
            ):
                response = client.post(
                    "/studio/api/image/batch-process",
                    json={
                        "batch_prompt_id": batch_prompt_id,
                        "model_id": model.id,
                    },
                )

            assert response.status_code == 200, response.get_data(as_text=True)
            payload = response.json["data"]
            assert payload["version_count"] == 2
            assert payload["succeeded"] == 2
            assert payload["failed"] == 0
            assert len(payload["tasks"]) == 2
            assert call_counts["版本一产品详情图"] == 1
            assert call_counts["版本二产品详情图"] == 1
            actual_pairs = sorted(
                (call["options"]["aspect_ratio"], call["options"]["resolution"])
                for call in calls
            )
            assert actual_pairs == [
                ("16:9", "1k"),
                ("1:1", "4k"),
            ], actual_pairs
            assert all(
                call["acting_user"].username == "admin"
                for call in calls
            )
            assert all(
                call["options"]["prepared_prompt"] == call["prompt"]
                for call in calls
            )
            assert all(
                "skill_id" not in call["options"]
                and "skill_name" not in call["options"]
                and "skill_prompt" not in call["options"]
                for call in calls
            )

            accepted_failure_calls = []

            def fake_accepted_failure(**kwargs):
                accepted_failure_calls.append(kwargs)
                error = StorageError("模拟 GoFastDFS 保存失败")
                error._upstream_accepted = True
                error._generation_task_id = 9999
                raise error

            with patch.object(
                studio_routes,
                "_batch_prompt_content",
                return_value=(document, ""),
            ), patch.object(
                studio_routes,
                "create_generation",
                side_effect=fake_accepted_failure,
            ):
                retry_response = client.post(
                    "/studio/api/image/batch-process",
                    json={
                        "batch_prompt_id": batch_prompt_id,
                        "model_id": model.id,
                    },
                )

            assert retry_response.status_code == 200
            retry_payload = retry_response.json["data"]
            assert retry_payload["version_count"] == 2
            assert retry_payload["succeeded"] == 0
            assert retry_payload["failed"] == 2
            assert len(accepted_failure_calls) == 2
        finally:
            db.session.rollback()
            row = StudioBatchPrompt.query.get(batch_prompt_id)
            if row:
                db.session.delete(row)
            provider = StudioProvider.query.get(provider.id)
            if provider:
                provider.api_key = original_key
            db.session.commit()

    print("studio image batch process smoke test passed")


if __name__ == "__main__":
    main()
