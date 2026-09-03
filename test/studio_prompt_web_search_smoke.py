import json
import secrets
from unittest.mock import patch

from applications import create_app
from applications.common.scope import effective_permission_codes
from applications.extensions import db
from applications.models import (
    StudioModel,
    StudioProduct,
    StudioProvider,
    StudioSetting,
    User,
)
from applications.view.studio import routes as studio_routes


class FakePlannerClient:
    last_body = None

    def __init__(self, provider):
        self.provider = provider

    def complete(self, model, body):
        del model
        type(self).last_body = body
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "final_prompt": (
                                    "使用联网核验到的正确握持方式，"
                                    "保持产品外观与原始标签一致。"
                                ),
                                "product_name": "联网核验测试产品",
                                "reference_instruction": "",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def _set_session(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = sorted(effective_permission_codes(user))


def main():
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        assert admin is not None and admin.dept_id is not None
        kuaipao_model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.media_type == "CHAT",
                StudioModel.model_code == "gpt-5.4",
                StudioModel.enabled == 1,
                StudioProvider.name == "快跑AI",
                StudioProvider.dept_id == admin.dept_id,
                StudioProvider.enabled == 1,
            )
            .order_by(StudioModel.id.asc())
            .first()
        )
        toapis_model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.media_type == "CHAT",
                StudioModel.model_code == "gpt-5.5",
                StudioModel.enabled == 1,
                StudioProvider.name == "ToAPIs",
                StudioProvider.dept_id == admin.dept_id,
                StudioProvider.enabled == 1,
            )
            .order_by(StudioModel.id.asc())
            .first()
        )
        assert kuaipao_model is not None
        assert toapis_model is not None

        product = StudioProduct(
            dept_id=admin.dept_id,
            code="USAGE-SEARCH-" + secrets.token_hex(4).upper(),
            name="联网核验测试产品",
            description="带真实握把的测试工具",
            enabled=1,
            created_by=admin.id,
        )
        db.session.add(product)
        db.session.flush()

        setting = StudioSetting.query.filter_by(
            setting_key=studio_routes.GLOBAL_CHAT_MODEL_SETTING_KEY,
            dept_id=admin.dept_id,
        ).first()
        created_setting = setting is None
        original_setting_value = setting.setting_value if setting else None
        original_kuaipao_key = kuaipao_model.provider.api_key
        original_toapis_key = toapis_model.provider.api_key
        if setting is None:
            setting = StudioSetting(
                setting_key=studio_routes.GLOBAL_CHAT_MODEL_SETTING_KEY,
                dept_id=admin.dept_id,
                description="usage search smoke",
            )
            db.session.add(setting)

        client = app.test_client()
        _set_session(client, admin)
        try:
            kuaipao_model.provider.api_key = "usage-search-kuaipao-key"
            setting.setting_value = str(kuaipao_model.id)
            db.session.commit()
            with patch.object(studio_routes, "ProviderClient", FakePlannerClient):
                response = client.post(
                    "/studio/api/prompt/prepare",
                    json={
                        "media_type": "IMAGE",
                        "department_id": admin.dept_id,
                        "product_id": product.id,
                        "prompt": "生成正确的产品使用场景",
                    },
                )
            assert response.status_code == 200, response.get_data(as_text=True)
            assert FakePlannerClient.last_body["tools"] == [
                {"type": "web_search"}
            ]
            assert response.json["data"]["usage_web_search_enabled"] is True
            planner_text = json.dumps(
                FakePlannerClient.last_body,
                ensure_ascii=False,
            )
            assert "官方说明" in planner_text
            assert "真实握把" in planner_text

            toapis_model.provider.api_key = "usage-search-toapis-key"
            setting.setting_value = str(toapis_model.id)
            db.session.commit()
            with patch.object(studio_routes, "ProviderClient", FakePlannerClient):
                response = client.post(
                    "/studio/api/prompt/prepare",
                    json={
                        "media_type": "IMAGE",
                        "department_id": admin.dept_id,
                        "product_id": product.id,
                        "prompt": "生成产品使用场景",
                    },
                )
            assert response.status_code == 200, response.get_data(as_text=True)
            assert "tools" not in FakePlannerClient.last_body
            assert response.json["data"]["usage_web_search_enabled"] is False
            planner_text = json.dumps(
                FakePlannerClient.last_body,
                ensure_ascii=False,
            )
            assert "没有声明 web_search 能力" in planner_text
        finally:
            db.session.rollback()
            refreshed_setting = StudioSetting.query.filter_by(
                setting_key=studio_routes.GLOBAL_CHAT_MODEL_SETTING_KEY,
                dept_id=admin.dept_id,
            ).first()
            if refreshed_setting:
                if created_setting:
                    db.session.delete(refreshed_setting)
                else:
                    refreshed_setting.setting_value = original_setting_value
            refreshed_kuaipao = StudioProvider.query.get(
                kuaipao_model.provider_id
            )
            if refreshed_kuaipao:
                refreshed_kuaipao.api_key = original_kuaipao_key
            refreshed_toapis = StudioProvider.query.get(
                toapis_model.provider_id
            )
            if refreshed_toapis:
                refreshed_toapis.api_key = original_toapis_key
            refreshed_product = StudioProduct.query.filter_by(
                code=product.code
            ).first()
            if refreshed_product:
                db.session.delete(refreshed_product)
            db.session.commit()

    print("studio prompt web search smoke passed")


if __name__ == "__main__":
    main()
