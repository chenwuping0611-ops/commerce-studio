import io
import json
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.amazon_ai.service import AmazonAiService, _persist_text_result
from applications.common.scope import effective_permission_codes
from applications.common.storage.gofastdfs_client import StoredFile
from applications.extensions import db
from applications.models import (
    AmazonAiTask,
    StudioAsset,
    StudioModel,
    StudioProduct,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)


def _set_session(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = sorted(effective_permission_codes(user))


def _listing_markdown():
    qa = "\n\n".join(
        f"### Q{index}. Confirmed customer question {index}\n"
        f"**A:** Use the product according to the confirmed product facts "
        f"for question {index}."
        for index in range(1, 21)
    )
    return (
        "# Amazon Listing Copy\n\n"
        "## Item Name\n\n"
        "Brand Portable Organizer\n\n"
        "## Item Highlights\n\n"
        "Compact storage solution for everyday home and travel use\n\n"
        "## Product Description\n\n"
        "A practical organizer built for confirmed everyday storage scenarios.\n\n"
        "## Customer FAQ / QA\n\n"
        + qa
    )


def _fake_execute(self, task_id, context="", input_asset_ids=None, web_search=None):
    task = AmazonAiTask.query.get(task_id)
    if task.task_type == "LISTING_GENERATE":
        content = _listing_markdown()
    elif task.task_type == "DIFFERENTIATION_GENERATE":
        content = (
            "# 高转化轻差异化方案\n\n"
            "## 现货微改\n\n"
            "1. 调整包装并确认成本。\n\n"
            "## 配件搭配\n\n"
            "1. 增加现货配件并核价。\n\n"
            "## 低成本升级方案\n\n"
            "1. 组合基础升级款并确认供应链。"
        )
    elif task.task_type == "COMPETITOR_ANALYZE":
        content = (
            "# 竞品 A\n\n"
            "页面事实：便携收纳结构和可见使用场景。\n\n"
            "## 竞品汇总\n\n"
            "只保留页面确认的竞品事实。"
        )
    else:
        content = f"{task.task_type} result"

    task.status = "SUCCEEDED"
    task.progress = 100
    task.started_at = task.started_at or datetime.now()
    task.finished_at = datetime.now()
    task.response_digest = "smoke-response-digest"
    task.result_refs_json = json.dumps(
        {"response_digest": task.response_digest},
        ensure_ascii=False,
    )
    _persist_text_result(task, content)
    db.session.commit()
    return {"task": task, "content": content, "response": {}, "model": None}


def _fake_upload_bytes(data, filename, **kwargs):
    token = uuid4().hex
    return StoredFile(
        storage_path=f"/smoke/results/{token}/{filename}",
        public_url=f"https://files.example/{token}/{filename}",
        original_filename=filename,
        content_type=kwargs.get("content_type") or "text/plain",
        file_size=len(data or b""),
        checksum="smoke-checksum-" + token,
    )


def _fake_input_upload(file_storage, **kwargs):
    filename = str(file_storage.filename or "upload.bin")
    token = uuid4().hex
    return StudioAsset(
        dept_id=kwargs.get("dept_id"),
        asset_type=kwargs.get("asset_type") or "FILE",
        purpose=kwargs.get("purpose") or "AMAZON_INPUT",
        retention_policy=kwargs.get("retention_policy") or "TTL_7D",
        storage_path=f"/smoke/input/{token}/{filename}",
        public_url=f"https://files.example/input/{token}/{filename}",
        original_filename=filename,
        content_type=file_storage.mimetype or "application/octet-stream",
        file_size=None,
        status="ACTIVE",
        created_by=kwargs.get("created_by"),
    )


def main():
    app = create_app()
    token = uuid4().hex[:10]
    task_ids = []
    input_asset_ids = []
    temporary_asset_ids = []
    product_ids = []
    skill_ids = []
    original_provider_keys = {}
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        assert admin is not None
        root_provider = (
            StudioProvider.query.filter_by(
                name="ToAPIs",
                dept_id=admin.dept_id,
            )
            .order_by(StudioProvider.id.asc())
            .first()
        )
        assert root_provider is not None
        root_provider_id = root_provider.id
        original_provider_keys[root_provider.id] = root_provider.api_key
        root_provider.api_key = "amazon-flow-smoke-key"
        chat_setting = StudioSetting.query.filter_by(
            setting_key="global_chat_model_id",
            dept_id=admin.dept_id,
        ).first()
        assert chat_setting is not None
        chat_model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.id == int(chat_setting.setting_value),
                StudioModel.media_type == "CHAT",
                StudioModel.enabled == 1,
                StudioProvider.dept_id == admin.dept_id,
                StudioProvider.enabled == 1,
            )
            .first()
        )
        assert chat_model is not None and chat_model.provider is not None
        chat_provider_id = chat_model.provider.id
        original_provider_keys.setdefault(
            chat_provider_id,
            chat_model.provider.api_key,
        )
        chat_model.provider.api_key = "amazon-flow-smoke-chat-key"
        db.session.commit()
        client = app.test_client()
        _set_session(client, admin)

        try:
            input_asset = StudioAsset(
                dept_id=admin.dept_id,
                asset_type="FILE",
                purpose="AMAZON_INPUT",
                retention_policy="TTL_7D",
                storage_path=f"/smoke/{token}-keywords.csv",
                public_url=f"https://files.example/{token}-keywords.csv",
                original_filename=f"{token}-keywords.csv",
                content_type="text/csv",
                status="ACTIVE",
                created_by=admin.id,
            )
            db.session.add(input_asset)
            db.session.flush()
            input_asset_ids.append(input_asset.id)
            second_input_asset = StudioAsset(
                dept_id=admin.dept_id,
                asset_type="FILE",
                purpose="AMAZON_INPUT",
                retention_policy="TTL_7D",
                storage_path=f"/smoke/{token}-reviews.csv",
                public_url=f"https://files.example/{token}-reviews.csv",
                original_filename=f"{token}-reviews.csv",
                content_type="text/csv",
                status="ACTIVE",
                created_by=admin.id,
            )
            db.session.add(second_input_asset)
            db.session.flush()
            input_asset_ids.append(second_input_asset.id)
            deletable_input_asset = StudioAsset(
                dept_id=admin.dept_id,
                asset_type="FILE",
                purpose="AMAZON_INPUT",
                retention_policy="TTL_7D",
                storage_path=f"/smoke/{token}-unused.csv",
                public_url=f"https://files.example/{token}-unused.csv",
                original_filename=f"{token}-unused.csv",
                content_type="text/csv",
                status="ACTIVE",
                created_by=admin.id,
            )
            db.session.add(deletable_input_asset)
            db.session.flush()
            temporary_asset_ids.append(deletable_input_asset.id)
            batch_cleanup_asset = StudioAsset(
                dept_id=admin.dept_id,
                asset_type="FILE",
                purpose="AMAZON_INPUT",
                retention_policy="TTL_7D",
                storage_path=f"/smoke/{token}-unused-batch.csv",
                public_url=f"https://files.example/{token}-unused-batch.csv",
                original_filename=f"{token}-unused-batch.csv",
                content_type="text/csv",
                status="ACTIVE",
                created_by=admin.id,
            )
            db.session.add(batch_cleanup_asset)
            db.session.flush()
            temporary_asset_ids.append(batch_cleanup_asset.id)
            db.session.commit()

            product = StudioProduct(
                dept_id=admin.dept_id,
                code=f"SMOKE-{token}-PRODUCT",
                name="Smoke Amazon Product",
                core_selling_points="旧核心卖点",
                enabled=1,
                created_by=admin.id,
            )
            db.session.add(product)
            db.session.commit()
            product_ids.append(product.id)

            custom_skill = StudioSkill(
                dept_id=admin.dept_id,
                name=f"Smoke Custom Skill {token}",
                code=f"SMOKE-{token}-SKILL",
                media_type="BOTH",
                content="使用操作者选择的自定义 Skill 规则。",
                prompt_template="使用操作者选择的自定义 Skill 规则。",
                file_name=f"SMOKE-{token}-SKILL.md",
                file_type="md",
                enabled=1,
                created_by=admin.id,
            )
            db.session.add(custom_skill)
            db.session.commit()
            skill_ids.append(custom_skill.id)

            options_response = client.get("/amazon-ai/api/options")
            assert options_response.status_code == 200, options_response.json
            assert any(
                item["id"] == custom_skill.id
                for item in options_response.json["data"]["skills"]
            )

            with patch.object(
                AmazonAiService,
                "execute_task",
                _fake_execute,
            ), patch(
                "applications.amazon_ai.service.FileService.upload_bytes",
                side_effect=_fake_upload_bytes,
            ), patch(
                "applications.amazon_ai.service.FileService.read_text",
                return_value="stored result text",
            ), patch(
                "applications.view.amazon_ai.routes.FileService.upload_file",
                side_effect=_fake_input_upload,
            ):
                for page in (
                    "/amazon-ai/competitor",
                    "/amazon-ai/differentiation",
                    "/amazon-ai/listing/create",
                ):
                    page_response = client.get(page)
                    assert page_response.status_code == 200
                    assert 'data-max-file-bytes="536870912"' in (
                        page_response.get_data(as_text=True)
                    )
                    assert 'type="file"' in page_response.get_data(
                        as_text=True
                    )
                    assert "multiple" in page_response.get_data(
                        as_text=True
                    )
                    if page == "/amazon-ai/listing/create":
                        listing_html = page_response.get_data(as_text=True)
                        assert (
                            'name="skill_id" class="amazon-select '
                            'amazon-option-skill" required'
                            not in listing_html
                        )
                        assert (
                            'id="listingCompetitorTaskCode" class="amazon-select" '
                            'required'
                            not in listing_html
                        )
                        assert (
                            'id="listingDifferentiationTaskCode" class="amazon-select" '
                            'required'
                            not in listing_html
                        )
                        assert (
                            'id="listingBasicInfoTaskCode" class="amazon-select" '
                            'required'
                            not in listing_html
                        )

                with patch(
                    "applications.view.amazon_ai.routes.FileService.upload_file"
                ) as upload_file, patch(
                    "applications.view.amazon_ai.routes._file_storage_size",
                    return_value=(
                        app.config["AMAZON_AI_MAX_UPLOAD_FILE_BYTES"] + 1
                    ),
                ):
                    response = client.post(
                        "/amazon-ai/api/competitors/input-files",
                        data={
                            "file": (
                                io.BytesIO(b"this file is intentionally small"),
                                f"{token}-too-large.md",
                            )
                        },
                        content_type="multipart/form-data",
                    )
                assert response.status_code == 413, response.json
                assert response.json["code"] == (
                    "AMAZON_INPUT_FILE_TOO_LARGE"
                )
                assert "文件未上传" in response.json["msg"]
                upload_file.assert_not_called()

                response = client.post(
                    "/amazon-ai/api/competitors/input-files",
                    data={
                        "file": (
                            io.BytesIO(b"# uploaded input\n"),
                            f"{token}-uploaded.md",
                        )
                    },
                    content_type="multipart/form-data",
                )
                assert response.status_code == 200, response.json
                uploaded_asset = response.json["data"]
                assert uploaded_asset["id"]
                assert uploaded_asset["filename"] == f"{token}-uploaded.md"
                assert StudioAsset.query.get(uploaded_asset["id"]) is not None
                temporary_asset_ids.append(uploaded_asset["id"])

                response = client.post(
                    "/amazon-ai/api/competitors/analyze",
                    json={
                        "product_urls": "https://www.amazon.com/dp/B000000001",
                        "input_asset_ids": input_asset_ids,
                    },
                )
                assert response.status_code == 400, response.json
                assert "Skill" in response.json["msg"]

                response = client.post(
                    "/amazon-ai/api/competitors/analyze",
                    json={
                        "product_urls": (
                            "https://www.amazon.com/dp/B000000001\n"
                            "https://www.amazon.com/dp/B000000002"
                        ),
                        "input_asset_ids": input_asset_ids,
                        "skill_id": custom_skill.id,
                    },
                )
                assert response.status_code == 200, response.json
                competitor_task = response.json["data"]["task"]
                task_ids.append(competitor_task["id"])
                assert competitor_task["task_type"] == "COMPETITOR_ANALYZE"
                assert competitor_task["source_key"] == "B000000001"
                assert competitor_task["skill_id"] == custom_skill.id
                assert competitor_task["input_asset_ids"] == input_asset_ids
                assert competitor_task["output_asset_id"]
                assert competitor_task["response_filename"].startswith(
                    "B000000001-竞品分析-R"
                )

                response = client.post(
                    "/amazon-ai/api/differentiation/analyze",
                    json={
                        "input_asset_ids": input_asset_ids,
                        "studio_product_id": product.id,
                        "skill_id": custom_skill.id,
                    },
                )
                assert response.status_code == 200, response.json
                differentiation_task = response.json["data"]["task"]
                task_ids.append(differentiation_task["id"])
                assert differentiation_task["task_type"] == (
                    "DIFFERENTIATION_GENERATE"
                )
                assert differentiation_task["input_asset_ids"] == input_asset_ids
                assert differentiation_task["output_asset_id"]

                response = client.get("/amazon-ai/api/result-tasks")
                assert response.status_code == 200, response.json
                result_task_ids = {item["id"] for item in response.json["data"]}
                assert set(task_ids) <= result_task_ids

                response = client.post(
                    "/amazon-ai/api/basic-info/save",
                    json={
                        "competitor_task_code": competitor_task["task_code"],
                        "content": "人工确认后的基础信息。",
                    },
                )
                assert response.status_code == 400
                assert "文件未命名" in response.json["msg"]

                response = client.post(
                    "/amazon-ai/api/basic-info/save",
                    json={
                        "competitor_task_code": competitor_task["task_code"],
                        "content": "人工确认后的基础信息。",
                        "result_filename": "暴风机",
                        "studio_product_id": product.id,
                    },
                )
                assert response.status_code == 200, response.json
                basic_task = response.json["data"]["task"]
                task_ids.append(basic_task["id"])
                assert basic_task["task_type"] == "BASIC_INFO_CORRECT"
                assert basic_task["response_filename"] == "暴风机.txt"
                assert basic_task["display_id"] == "暴风机.txt"
                refreshed_product = StudioProduct.query.get(product.id)
                assert refreshed_product.core_selling_points == (
                    "人工确认后的基础信息。"
                )

                response = client.get("/amazon-ai/api/basic-info/history")
                assert response.status_code == 200, response.json
                assert any(
                    item["response_filename"] == "暴风机.txt"
                    for item in response.json["data"]
                )

                response = client.post(
                    "/amazon-ai/api/listing/generate",
                    json={
                        "competitor_task_code": competitor_task["task_code"],
                        "differentiation_task_code": (
                            differentiation_task["task_code"]
                        ),
                        "basic_info_task_code": basic_task["task_code"],
                        "input_asset_ids": input_asset_ids,
                        "skill_id": custom_skill.id,
                        "context": (
                            "Product: portable organizer. "
                            "Use only confirmed product facts."
                        ),
                        "studio_product_id": product.id,
                    },
                )
                assert response.status_code == 200, response.json
                listing_task = response.json["data"]["task"]
                task_ids.append(listing_task["id"])
                assert listing_task["task_type"] == "LISTING_GENERATE"
                assert listing_task["skill_id"] == custom_skill.id
                assert listing_task["input_asset_ids"] == input_asset_ids
                assert listing_task["output_asset_id"]
                assert response.json["data"]["version_summary"] == {
                    "item_name": "Brand Portable Organizer",
                    "qa_count": 20,
                }

                response = client.get("/amazon-ai/api/listing/history")
                assert response.status_code == 200, response.json
                assert any(
                    item["task_code"] == listing_task["task_code"]
                    for item in response.json["data"]
                )

                response = client.get(
                    "/amazon-ai/api/listing/history/"
                    f"{listing_task['task_code']}/result"
                )
                assert response.status_code == 200, response.json
                assert response.json["data"]["task_type"] == "LISTING_GENERATE"
                assert response.json["data"]["response_text"]

                response = client.post(
                    "/amazon-ai/api/listing/generate",
                    json={
                        "context": (
                            "Write a concise Amazon listing for a portable "
                            "organizer using only this confirmed requirement."
                        )
                    },
                )
                assert response.status_code == 200, response.json
                standalone_listing_task = response.json["data"]["task"]
                task_ids.append(standalone_listing_task["id"])
                assert standalone_listing_task["task_type"] == (
                    "LISTING_GENERATE"
                )
                assert standalone_listing_task["skill_id"] is None
                assert standalone_listing_task["source_task_codes"] == []
                assert standalone_listing_task["input_asset_ids"] == []
                assert response.json["data"]["version_summary"]["qa_count"] == 20

                response = client.post(
                    "/amazon-ai/api/listing/generate",
                    json={},
                )
                assert response.status_code == 400, response.json
                assert "至少提供一项 Listing 输入" in response.json["msg"]

                with patch(
                    "applications.view.amazon_ai.routes.FileService.delete_storage",
                    return_value=True,
                ) as delete_storage:
                    response = client.delete(
                        "/amazon-ai/api/competitors/input-files/"
                        f"{temporary_asset_ids[0]}"
                    )
                assert response.status_code == 200, response.json
                assert delete_storage.call_count == 1
                deleted_input_asset = StudioAsset.query.get(
                    temporary_asset_ids[0]
                )
                assert deleted_input_asset.status == "DELETED"

                with patch(
                    "applications.view.amazon_ai.routes.FileService.delete_storage",
                    return_value=True,
                ) as delete_storage:
                    response = client.post(
                        "/amazon-ai/api/competitors/input-files/cleanup",
                        json={"asset_ids": [temporary_asset_ids[1]]},
                    )
                assert response.status_code == 200, response.json
                assert response.json["success"] is True
                assert delete_storage.call_count == 1
                batch_deleted_asset = StudioAsset.query.get(
                    temporary_asset_ids[1]
                )
                assert batch_deleted_asset.status == "DELETED"

                with patch(
                    "applications.view.amazon_ai.routes.FileService.delete_storage",
                    return_value=True,
                ) as delete_storage:
                    response = client.post(
                        "/amazon-ai/api/competitors/input-files/cleanup",
                        json={"asset_ids": [input_asset_ids[0]]},
                    )
                assert response.status_code == 200, response.json
                assert response.json["success"] is True
                assert response.json["data"]["results"][0]["success"] is False
                assert delete_storage.call_count == 0

                with patch(
                    "applications.view.amazon_ai.routes.FileService.delete_storage",
                    return_value=True,
                ) as delete_storage:
                    response = client.delete(
                        "/amazon-ai/api/competitors/input-files/"
                        f"{input_asset_ids[0]}"
                    )
                assert response.status_code == 409, response.json
                assert delete_storage.call_count == 0

                delete_target = AmazonAiTask.query.get(
                    differentiation_task["id"]
                )
                output_asset_id = delete_target.output_asset_id
                with patch(
                    "applications.view.amazon_ai.routes.FileService.delete_asset",
                    return_value=True,
                ) as delete_asset:
                    response = client.delete(
                        f"/amazon-ai/api/tasks/{delete_target.task_code}"
                    )
                assert response.status_code == 200, response.json
                assert delete_asset.call_count == 1
                assert AmazonAiTask.query.get(delete_target.id) is None
                assert StudioAsset.query.get(output_asset_id) is None

            print("amazon ai unified workspace smoke test passed")
        finally:
            db.session.rollback()
            root_provider = StudioProvider.query.get(root_provider_id)
            if root_provider is not None:
                root_provider.api_key = original_provider_keys.get(
                    root_provider.id
                )
            chat_provider = StudioProvider.query.get(chat_provider_id)
            if chat_provider is not None:
                chat_provider.api_key = original_provider_keys.get(
                    chat_provider.id
                )
            remaining_tasks = AmazonAiTask.query.filter(
                AmazonAiTask.id.in_(task_ids)
            ).all()
            remaining_task_ids = [task.id for task in remaining_tasks]
            remaining_asset_ids = []
            for task in remaining_tasks:
                if task.output_asset_id:
                    remaining_asset_ids.append(task.output_asset_id)
                remaining_asset_ids.extend(
                    int(value)
                    for value in json.loads(task.input_asset_ids_json or "[]")
                    if str(value).isdigit()
                )
            if remaining_task_ids:
                AmazonAiTask.query.filter(
                    AmazonAiTask.id.in_(remaining_task_ids)
                ).delete(synchronize_session=False)
            cleanup_asset_ids = list(
                dict.fromkeys(
                    input_asset_ids
                    + temporary_asset_ids
                    + remaining_asset_ids
                )
            )
            if cleanup_asset_ids:
                StudioAsset.query.filter(
                    StudioAsset.id.in_(cleanup_asset_ids)
                ).delete(synchronize_session=False)
            if product_ids:
                StudioProduct.query.filter(
                    StudioProduct.id.in_(product_ids)
                ).delete(synchronize_session=False)
            if skill_ids:
                StudioSkill.query.filter(
                    StudioSkill.id.in_(skill_ids)
                ).delete(synchronize_session=False)
            db.session.commit()


if __name__ == "__main__":
    main()
