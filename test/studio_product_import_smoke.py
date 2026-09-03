"""Smoke test Listing history import without calling a real model provider."""

import json
from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.amazon_ai.service import read_task_result_text
from applications.extensions import db
from applications.models import (
    AmazonAiTask,
    StudioModel,
    StudioProduct,
    StudioProvider,
    StudioSetting,
    User,
)
from applications.view.studio import routes as studio_routes


GLOBAL_CHAT_MODEL_SETTING_KEY = "global_chat_model_id"
LISTING_TASK_ID = 12


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
    temporary_product_id = None
    provider_id = None
    original_provider_key = None

    with app.app_context():
        task = AmazonAiTask.query.get(LISTING_TASK_ID)
        assert task is not None
        assert task.task_type == "LISTING_GENERATE"
        assert task.status == "SUCCEEDED"
        assert task.output_asset_id
        listing_department_id = task.dept_id
        before_task = {
            "status": task.status,
            "output_asset_id": task.output_asset_id,
            "output_filename": task.output_filename,
            "response_digest": task.response_digest,
            "result_refs_json": task.result_refs_json,
        }
        listing_text = read_task_result_text(task, maximum_size=280000)
        assert listing_text.strip()

        setting = StudioSetting.query.filter_by(
            setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
            dept_id=task.dept_id,
        ).first()
        assert setting is not None and str(setting.setting_value or "").isdigit()
        chat_model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.id == int(setting.setting_value),
                StudioModel.media_type == "CHAT",
                StudioModel.enabled == 1,
                StudioProvider.dept_id == listing_department_id,
                StudioProvider.enabled == 1,
            )
            .first()
        )
        assert chat_model is not None and chat_model.provider is not None
        provider_id = chat_model.provider.id
        original_provider_key = chat_model.provider.api_key
        if not str(original_provider_key or "").strip():
            chat_model.provider.api_key = "local-product-import-smoke-key"
            db.session.commit()

    _login_as(client, "admin")

    try:
        response = client.get("/studio/api/products/listing-histories")
        assert response.status_code == 200, response.json
        assert any(
            int(item["id"]) == LISTING_TASK_ID
            for item in response.json["data"]
        )

        product_code = "LOCAL-EXTRACTED-" + uuid4().hex[:12].upper()
        fake_model_response = {
            "product_name": "Listing 提取测试产品",
            "product_code": product_code,
            "brand": "Listing Test Brand",
            "description": "来自 Product Description 的产品描述。",
            "core_selling_points": "来自 Item Highlights 的核心卖点。",
            "product_profile": "Listing 明确出现的外形和结构信息。",
            "product_memory": "Listing 明确出现的适用场景。",
            "generation_rules": None,
            "forbidden_rules": None,
        }
        captured = {}

        def fake_complete_chat(model, body, department_id=None, user=None):
            del model, department_id, user
            captured["body"] = body
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                fake_model_response,
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        with patch.object(
            studio_routes,
            "complete_chat",
            side_effect=fake_complete_chat,
        ):
            response = client.post(
                "/studio/api/products/from-listing",
                json={"listing_task_id": LISTING_TASK_ID},
            )
        assert response.status_code == 200, response.json
        imported = response.json["data"]["product"]
        temporary_product_id = int(imported["id"])
        assert imported["dept_id"]
        assert imported["code"] == product_code
        assert imported["name"] == fake_model_response["product_name"]
        assert imported["description"] == fake_model_response["description"]
        assert (
            imported["core_selling_points"]
            == fake_model_response["core_selling_points"]
        )
        assert imported["generation_rules"] == ""
        assert imported["forbidden_rules"] == ""

        model_request_text = json.dumps(
            captured.get("body") or {},
            ensure_ascii=False,
        )
        assert "Product Description" in listing_text
        assert "Product Description" in model_request_text
        assert len(listing_text.encode("utf-8")) > 0

        with app.app_context():
            product = StudioProduct.query.get(temporary_product_id)
            assert product is not None
            assert product.dept_id == listing_department_id
            assert product.created_by == User.query.filter_by(
                username="admin"
            ).first().id

            db.session.delete(product)
            db.session.commit()
            temporary_product_id = None

            task_after = AmazonAiTask.query.get(LISTING_TASK_ID)
            assert task_after is not None
            assert {
                "status": task_after.status,
                "output_asset_id": task_after.output_asset_id,
                "output_filename": task_after.output_filename,
                "response_digest": task_after.response_digest,
                "result_refs_json": task_after.result_refs_json,
            } == before_task
    finally:
        with app.app_context():
            db.session.rollback()
            if temporary_product_id:
                product = StudioProduct.query.get(temporary_product_id)
                if product:
                    db.session.delete(product)
            if provider_id:
                provider = StudioProvider.query.get(provider_id)
                if provider:
                    provider.api_key = original_provider_key
            db.session.commit()

    print("studio product import smoke test passed")


if __name__ == "__main__":
    main()
