"""Integration smoke checks for batch prompt generation and editing."""

import json
import re
from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.common.scope import effective_permission_codes
from applications.common.storage import (
    FileService,
    StoredFile,
)
from applications.common.storage.file_service import PendingAssetUpdate
from applications.extensions import db
from applications.models import (
    StudioAsset,
    StudioBatchPrompt,
    StudioModel,
    StudioProduct,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)
from applications.amazon_ai.skill_catalog import (
    BATCH_DETAIL_IMAGE_SKILL_CODE,
    read_skill_content,
)
from applications.studio.batch_prompt import format_versions
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
        client = app.test_client()
        _set_session(client, admin)
        batch_page = client.get("/studio/batch-prompts")
        assert batch_page.status_code == 200
        batch_page_text = batch_page.get_data(as_text=True)
        assert "创作风格" in batch_page_text
        assert "画布比例" in batch_page_text
        assert "data-batch-prompt-image-aspect-ratio" in batch_page_text
        assert re.search(
            r'value="2\.44:1"\s+selected',
            batch_page_text,
        )
        for ratio in (
            "1:1",
            "2.44:1",
            "3:2",
            "2:3",
            "4:3",
            "3:4",
            "5:4",
            "4:5",
            "16:9",
            "9:16",
            "2:1",
            "1:2",
            "21:9",
            "9:21",
        ):
            assert ratio in batch_page_text
        assert "默认生成 10 个" in batch_page_text
        assert "自定义风格" in batch_page_text

        token = uuid4().hex
        stored_documents = {}
        created_batch_id = None
        created_asset_id = None
        created_product_id = None
        original_key = None
        setting = StudioSetting.query.filter_by(
            setting_key=studio_routes.GLOBAL_CHAT_MODEL_SETTING_KEY,
            dept_id=admin.dept_id,
        ).first()
        chat_model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.id == int(setting.setting_value),
                StudioModel.media_type == "CHAT",
                StudioModel.enabled == 1,
                StudioProvider.enabled == 1,
                StudioProvider.dept_id == admin.dept_id,
            )
            .first()
            if setting and str(setting.setting_value or "").isdigit()
            else None
        )
        assert chat_model is not None and chat_model.provider is not None
        original_key = chat_model.provider.api_key
        chat_model.provider.api_key = "batch-prompt-smoke-key"
        db.session.commit()

        batch_skill = StudioSkill.query.filter_by(
            code=BATCH_DETAIL_IMAGE_SKILL_CODE,
            enabled=1,
        ).first()
        assert batch_skill is not None
        batch_skill_content = read_skill_content(
            {
                "file_name": batch_skill.file_name
                or BATCH_DETAIL_IMAGE_SKILL_CODE,
            }
        )
        test_product = StudioProduct(
            dept_id=admin.dept_id,
            code="BATCH-PROMPT-" + token[:10].upper(),
            name="批量详情图测试产品",
            core_selling_points="真实核心卖点一\n真实核心卖点二",
            product_profile="真实产品档案",
            product_memory="真实产品记忆",
            asset_urls=json.dumps(
                ["https://files.example/product-front.png"],
                ensure_ascii=False,
            ),
            enabled=1,
            created_by=admin.id,
        )
        db.session.add(test_product)
        db.session.commit()
        created_product_id = test_product.id
        captured_bodies = []

        def fake_complete_chat(model, body, department_id=None, user=None):
            del model, department_id, user
            captured_bodies.append(body)
            request_text = json.dumps(body, ensure_ascii=False)
            match = re.search(r"生成\s+(\d+)\s*个", request_text)
            expected_count = int(match.group(1)) if match else 2
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "versions": [
                                        f"保持产品外观一致的批量详情图提示词版本 {index}"
                                        for index in range(1, expected_count + 1)
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        def fake_upload(content, filename, department_id, user_id):
            del user_id
            path = f"/smoke/batch/{token}/{filename}"
            stored = StoredFile(
                storage_path=path,
                public_url=f"https://files.example{path}",
                original_filename=filename,
                content_type="text/plain",
                file_size=len(content.encode("utf-8")),
                checksum=uuid4().hex,
            )
            stored_documents[path] = content
            return stored

        def fake_read_text(asset, **_kwargs):
            if asset.storage_path in stored_documents:
                return stored_documents[asset.storage_path]
            if asset.id == batch_skill.storage_asset_id:
                return batch_skill_content
            raise AssertionError(
                "unexpected GoFastDFS asset in batch prompt test: "
                + str(asset.storage_path)
            )

        def fake_stage_update(
            asset,
            content,
            filename=None,
            content_type=None,
            category=None,
        ):
            del content_type, category
            old_storage_path = asset.storage_path
            old_checksum = asset.checksum
            old_public_url = asset.public_url
            old_original_filename = asset.original_filename
            old_content_type = asset.content_type
            old_file_size = asset.file_size
            new_path = f"/smoke/batch/{token}/edited-{uuid4().hex}.txt"
            new_file = StoredFile(
                storage_path=new_path,
                public_url=f"https://files.example{new_path}",
                original_filename=filename or "edited.txt",
                content_type="text/plain",
                file_size=len(content),
                checksum=uuid4().hex,
            )
            stored_documents[new_path] = content.decode("utf-8")
            FileService._apply_stored_to_asset(asset, new_file)
            return PendingAssetUpdate(
                asset=asset,
                new_file=new_file,
                old_storage_path=old_storage_path,
                old_checksum=old_checksum,
                old_public_url=old_public_url,
                old_original_filename=old_original_filename,
                old_content_type=old_content_type,
                old_file_size=old_file_size,
            )

        try:
            with patch.object(
                studio_routes,
                "complete_chat",
                side_effect=fake_complete_chat,
            ), patch.object(
                studio_routes,
                "_upload_batch_prompt_text",
                side_effect=fake_upload,
            ), patch.object(
                studio_routes.FileService,
                "read_text",
                side_effect=fake_read_text,
            ):
                response = client.post(
                    "/studio/api/batch-prompts",
                    json={
                        "media_type": "IMAGE",
                        "count": 0,
                        "product_id": created_product_id,
                        "skill_id": batch_skill.id,
                        "creative_style": "高端商业摄影",
                        "creative_prompt": "默认数量生成多套电商详情图方案",
                        "image_aspect_ratio": "16:9",
                    },
                )
            assert response.status_code == 200, response.json
            payload = response.json["data"]
            created_batch_id = int(payload["id"])
            created_asset_id = int(payload["storage_asset_id"])
            assert payload["status"] == "SUCCEEDED"
            assert payload["version_count"] == 10
            assert payload["creative_style"] == "高端商业摄影"
            assert payload["image_aspect_ratio"] == "16:9"
            assert payload["file_name"] == "批量详情图测试产品·R01.txt"
            assert "第一版：" in payload["content"]
            assert "第十版：" in payload["content"]
            assert len(payload["version_settings"]) == 10
            assert payload["version_settings"][0]["aspect_ratio"] == "16:9"
            assert payload["version_settings"][0]["resolution"] == "2k"
            request_context = json.dumps(
                captured_bodies[-1],
                ensure_ascii=False,
            )
            assert "amazon-ecommerce-batch-detail-image-skill" in request_context
            assert "高端商业摄影" in request_context
            assert "真实核心卖点一" in request_context
            assert "真实产品档案" in request_context
            assert "真实产品记忆" in request_context
            assert "https://files.example/product-front.png" in request_context
            assert "16:9" in request_context
            assert "电池标签" in request_context
            assert "长筒" in request_context
            assert "真实握把" in request_context
            assert "弯曲程度" in request_context
            assert "手掌、手指、扳机" in request_context
            assert "外部详情图标题" in request_context
            assert "完整产品定位视图" in request_context
            assert "同一个不可拆分的产品身份" in request_context

            with patch.object(
                studio_routes.FileService,
                "read_text",
                side_effect=fake_read_text,
            ):
                listed = client.get(
                    "/studio/api/batch-prompts?media_type=IMAGE"
                )
            assert listed.status_code == 200, listed.json
            listed_item = next(
                item
                for item in listed.json["data"]
                if int(item["id"]) == created_batch_id
            )
            assert listed_item["content"] == payload["content"]

            edited_document = format_versions(
                [
                    f"编辑后的批量详情图提示词版本 {index}"
                    for index in range(1, 11)
                ]
            )
            with patch.object(
                studio_routes.FileService,
                "stage_asset_update",
                side_effect=fake_stage_update,
            ), patch.object(
                studio_routes.FileService,
                "finalize_asset_update",
                return_value=True,
            ), patch.object(
                studio_routes.FileService,
                "read_text",
                side_effect=fake_read_text,
            ):
                response = client.put(
                    f"/studio/api/batch-prompts/{created_batch_id}",
                    json={"content": edited_document},
                )
            assert response.status_code == 200, response.json
            assert response.json["data"]["content"] == edited_document
            assert response.json["data"]["storage_asset_id"] == created_asset_id

            with patch.object(
                studio_routes.FileService,
                "read_text",
                side_effect=fake_read_text,
            ):
                detail = client.get(
                    f"/studio/api/batch-prompts/{created_batch_id}"
                )
            assert detail.status_code == 200, detail.json
            assert detail.json["data"]["content"] == edited_document
        finally:
            db.session.rollback()
            batch_prompt = (
                StudioBatchPrompt.query.get(created_batch_id)
                if created_batch_id
                else None
            )
            asset = (
                StudioAsset.query.get(created_asset_id)
                if created_asset_id
                else None
            )
            if batch_prompt:
                db.session.delete(batch_prompt)
            if asset:
                db.session.delete(asset)
            if created_product_id:
                product = StudioProduct.query.get(created_product_id)
                if product:
                    db.session.delete(product)
            if chat_model.provider:
                chat_model.provider.api_key = original_key
            db.session.commit()


if __name__ == "__main__":
    main()
