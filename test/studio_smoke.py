from applications import create_app
from io import BytesIO
import json
import secrets
import string

from applications.common.scope import effective_permission_codes
from applications.extensions import db
from applications.models import (
    Dept,
    Power,
    Role,
    StudioAsset,
    StudioGenerationTask,
    StudioModel,
    StudioProvider,
    StudioSkill,
    User,
)


def set_user_session(client, user, permissions):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = permissions


def unique_task_code():
    existing = {
        task_code
        for (task_code,) in StudioGenerationTask.query.with_entities(
            StudioGenerationTask.task_code
        ).all()
    }
    while True:
        task_code = "".join(
            secrets.choice(string.ascii_letters + string.digits)
            for _ in range(7)
        )
        if task_code not in existing:
            return task_code


def main():
    app = create_app()
    client = app.test_client()

    assert client.get("/passport/login").status_code == 200
    captcha_response = client.get("/passport/getCaptcha")
    assert captcha_response.status_code == 404

    response = client.post(
        "/passport/login",
        data={"username": "admin", "password": "123456"},
    )
    assert response.status_code == 200, response.data
    assert response.json["success"] is True, response.json

    assert client.get("/admin/").status_code == 200
    menu_response = client.get("/rights/menu")
    assert menu_response.status_code == 200
    menu_roots = menu_response.json
    root_codes = {item["code"] for item in menu_roots}
    assert {"studio:root", "admin:system:root"} <= root_codes
    system_root = next(item for item in menu_roots if item["code"] == "admin:system:root")
    system_codes = {
        item["code"] for item in system_root.get("children", [])
    }
    assert {
        "admin:user:main",
        "admin:role:main",
        "admin:power:main",
        "admin:dept:main",
        "admin:log:main",
        "studio:providers",
    }.issubset(system_codes)

    for path in (
        "/studio/",
        "/studio/image",
        "/studio/video",
        "/studio/batch-prompts",
        "/studio/products",
        "/studio/forms/product",
        "/studio/forms/asset?product_id=1",
        "/studio/skills",
        "/studio/forms/skill",
        "/studio/history",
        "/studio/providers",
        "/studio/forms/provider",
        "/studio/forms/model",
    ):
        assert client.get(path).status_code == 200, path

    assert client.get("/studio/api/dashboard").status_code == 200
    assert client.get("/studio/api/options?media_type=IMAGE").status_code == 200
    assert client.get("/studio/api/options?media_type=VIDEO").status_code == 200
    history_response = client.get("/studio/api/history?page=1&page_size=1")
    assert history_response.status_code == 200
    assert history_response.json["success"] is True
    assert history_response.json["meta"]["page"] == 1
    assert history_response.json["meta"]["page_size"] == 1
    assert isinstance(history_response.json["meta"]["has_more"], bool)

    with app.app_context():
        assert User.query.filter_by(username="admin").count() == 1
        assert Power.query.filter(Power.code.like("studio:%")).count() >= 7
        assert Power.query.filter_by(code="studio:batch_prompts").count() == 1
        studio_role = Role.query.filter_by(code="studio_user").first()
        assert studio_role is not None
        studio_role_codes = {power.code for power in studio_role.power}
        assert {
            "studio:root",
            "admin:system:root",
            "admin:user:main",
            "admin:log:main",
        } <= studio_role_codes
        assert any(power.code == "studio:image" for power in studio_role.power)
        assert any(
            power.code == "studio:batch_prompts"
            for power in studio_role.power
        )
        assert not any(
            power.code.startswith("admin:")
            for power in studio_role.power
            if power.code
            not in {
                "admin:system:root",
                "admin:user:main",
                "admin:log:main",
            }
        )
        assert not any(
            power.code == "studio:providers" for power in studio_role.power
        )
        admin_user = User.query.filter_by(username="admin").first()
        assert admin_user is not None
        root_department = Dept.query.filter_by(id=admin_user.dept_id).first()
        assert root_department is not None
        toapis = StudioProvider.query.filter_by(
            name="ToAPIs",
            dept_id=root_department.id,
        ).order_by(StudioProvider.id.asc()).first()
        assert toapis is not None
        assert toapis.owner_type == "DEPARTMENT"
        assert StudioModel.query.filter_by(
            provider_id=toapis.id,
            model_code="gpt-image-2",
        ).count() == 1
        catalog_response = client.get(
            f"/studio/api/provider-catalog?provider_id={toapis.id}"
        )
        assert catalog_response.status_code == 200
        catalog_payload = catalog_response.json["data"]
        assert catalog_payload["key"] == "toapis"
        catalog_codes = {item["code"] for item in catalog_payload["models"]}
        assert catalog_codes == {
            "gpt-image-2",
            "gemini-3.1-flash-image-preview",
            "seedance-2",
            "gpt-5.5",
        }
        assert all(
            item["parameter_schema"] and item["generation_path"]
            for item in catalog_payload["models"]
        )
        chat_parameters = {
            item["code"]: {field["field"] for field in item["parameter_schema"]}
            for item in catalog_payload["models"]
            if item["media_type"] == "CHAT"
        }
        assert {"max_completion_tokens", "temperature", "top_p", "stop", "stream"} <= (
            chat_parameters["gpt-5.5"]
        )
        kuaipao = StudioProvider.query.filter_by(
            name="快跑AI",
            dept_id=root_department.id,
        ).order_by(StudioProvider.id.asc()).first()
        assert kuaipao is not None
        kuaipao_catalog_response = client.get(
            f"/studio/api/provider-catalog?provider_id={kuaipao.id}"
        )
        assert kuaipao_catalog_response.status_code == 200
        kuaipao_catalog = kuaipao_catalog_response.json["data"]
        assert kuaipao_catalog["key"] == "kuaipao"
        kuaipao_chat_codes = {
            "gpt-5.4",
            "gpt-5.5",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
        }
        kuaipao_image_codes = {
            "gpt-image2",
        }
        kuaipao_codes = kuaipao_chat_codes | kuaipao_image_codes
        assert {
            item["code"] for item in kuaipao_catalog["models"]
        } == kuaipao_codes
        assert all(
            item["media_type"] == "CHAT"
            and item["generation_path"] == "/responses"
            and {
                "model",
                "input",
                "tools",
                "max_output_tokens",
            } <= {
                field["field"]
                for field in item["parameter_schema"]
            }
            for item in kuaipao_catalog["models"]
            if item["code"] in kuaipao_chat_codes
        )
        kuaipao_image_models = [
            item
            for item in kuaipao_catalog["models"]
            if item["code"] in kuaipao_image_codes
        ]
        assert all(
            item["media_type"] == "IMAGE"
            and item["generation_path"]
            == "https://image.kuaipao.pro/v1/images/edits"
            and {
                "model",
                "prompt",
                "n",
                "size",
                "resolution",
                "reference_images",
            } <= {
                field["field"]
                for field in item["parameter_schema"]
            }
            and item["capabilities"]["supports_image_edits"] is True
            and "supports_custom_aspect_ratio"
            not in item["capabilities"]
            and item["capabilities"]["resolution_options"]
            == ["1K", "2K", "4K"]
            for item in kuaipao_image_models
        )
        assert len(kuaipao_image_models) == 1
        assert kuaipao_image_models[0]["name"] == "gpt-image2"
        image_ratio_parameter = next(
            field
            for field in kuaipao_image_models[0]["parameter_schema"]
            if field["field"] == "size"
        )
        assert {
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
        } <= {
            option["value"] if isinstance(option, dict) else option
            for option in image_ratio_parameter["options"]
        }
        assert "__custom__" not in {
            option["value"] if isinstance(option, dict) else option
            for option in image_ratio_parameter["options"]
        }
        resolution_parameter = next(
            field
            for field in kuaipao_image_models[0]["parameter_schema"]
            if field["field"] == "resolution"
        )
        assert resolution_parameter["options"] == [
            {"value": "1k", "label": "1K"},
            {"value": "2k", "label": "2K"},
            {"value": "4k", "label": "4K"},
        ]
        assert kuaipao_image_models[0]["capabilities"]["api_model_mapping"] == {
            "1k": "gpt-image-2-1k",
            "2k": "gpt-image-2-2k",
            "4k": "gpt-image-2-4k",
        }
        kuaipao_enabled_models = [
            model for model in kuaipao.models if model.enabled
        ]
        assert {
            model.model_code for model in kuaipao_enabled_models
        } == kuaipao_codes
        assert not {
            "gpt-image-2-1k",
            "gpt-image-2-2k",
            "gpt-image-2-4k",
        } & {
            model.model_code for model in kuaipao_enabled_models
        }
        assert not any(
            model.media_type == "IMAGE"
            and model.model_code in {
                "gpt-image-2-1k",
                "gpt-image-2-2k",
                "gpt-image-2-4k",
            }
            and model.enabled
            for provider in StudioProvider.query.filter_by(
                name="快跑AI"
            ).all()
            for model in provider.models
        )
        assert all(
            model.media_type == "CHAT"
            and model.generation_path == "/responses"
            for model in kuaipao_enabled_models
            if model.model_code in kuaipao_chat_codes
        )
        assert all(
            model.media_type == "IMAGE"
            and model.generation_path
            == "https://image.kuaipao.pro/v1/images/edits"
            for model in kuaipao_enabled_models
            if model.model_code in kuaipao_image_codes
        )
        provider_page = client.get("/studio/providers").get_data(
            as_text=True
        )
        assert "字段数" not in provider_page
        assert "添加字段" not in client.get(
            "/studio/forms/model"
        ).get_data(as_text=True)
        feedback_skill = StudioSkill.query.filter_by(
            code="studio-feedback-quality",
        ).first()
        assert feedback_skill is not None
        assert feedback_skill.file_name == "studio-feedback-quality.md"
        assert feedback_skill.file_type == "md"
        assert feedback_skill.media_type == "BOTH"
        assert feedback_skill.enabled == 1
        feedback_asset = StudioAsset.query.get(feedback_skill.storage_asset_id)
        assert feedback_asset is not None
        assert feedback_asset.purpose == "SKILL"
        assert feedback_asset.retention_policy == "PERMANENT"
        assert feedback_asset.status == "ACTIVE"
        assert feedback_asset.public_url.startswith("http")
        seedance_models = {
            model.model_code: model
            for model in StudioModel.query.filter_by(media_type="VIDEO").all()
            if model.enabled
        }
        assert "seedance-2" in seedance_models

        seedance = seedance_models["seedance-2"]
        seedance_parameters = json.loads(seedance.parameter_schema or "[]")
        audio_parameter = next(
            item for item in seedance_parameters
            if item.get("field") == "generate_audio"
        )
        resolution_parameter = next(
            item for item in seedance_parameters
            if item.get("field") == "resolution"
        )
        assert resolution_parameter.get("options") == [
            "480p",
            "720p",
            "1080p",
            "4k",
        ]
        assert str(audio_parameter.get("value")).lower() == "false"
        admin_user = User.query.filter_by(username="admin").first()
        ordinary_user = next(
            (
                user
                for user in User.query.all()
                if user.username != "admin"
                and any(
                    role.code == "studio_user" and role.enable == 1
                    for role in user.role
                )
            ),
            None,
        )
        assert admin_user is not None
        assert ordinary_user is not None

        for path in ("/studio/image", "/studio/video", "/studio/history"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert b"var canDeleteHistory = true" in response.data

        image_page = client.get("/studio/image").get_data(as_text=True)
        assert "imageCustomAspect" not in image_page
        assert "其他比例" not in image_page
        assert "gpt-image2" in image_page

        skills_page = client.get("/studio/skills")
        assert skills_page.status_code == 200
        assert ">删除</button>".encode("utf-8") in skills_page.data

        set_user_session(
            client,
            ordinary_user,
            sorted(effective_permission_codes(ordinary_user)),
        )
        read_only_skills_page = client.get("/studio/skills")
        assert read_only_skills_page.status_code == 200
        assert b'id="newSkill"' not in read_only_skills_page.data
        assert ">编辑</button>".encode("utf-8") not in read_only_skills_page.data
        assert ">删除</button>".encode("utf-8") not in read_only_skills_page.data
        assert client.get("/studio/forms/skill").status_code == 403
        assert client.post(
            "/studio/api/skills",
            json={"name": "普通用户不应创建 Skill"},
        ).status_code == 403
        assert client.post(
            "/studio/api/skills/upload",
            data={"file": (BytesIO(b"blocked"), "blocked.md")},
            content_type="multipart/form-data",
        ).status_code == 403
        assert client.delete(
            f"/studio/api/skills/{feedback_skill.id}"
        ).status_code == 403

        set_user_session(
            client,
            ordinary_user,
            ["studio:image", "studio:video", "studio:history"],
        )
        for path in ("/studio/image", "/studio/video", "/studio/history"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert b"var canDeleteHistory = false" in response.data

        task = StudioGenerationTask(
            task_code=unique_task_code(),
            user_id=ordinary_user.id,
            media_type="IMAGE",
            prompt="删除权限烟测任务",
            status="FAILED",
            error_message="test",
        )
        db.session.add(task)
        db.session.commit()
        task_id = task.id

        try:
            forbidden = client.delete(f"/studio/api/history/{task_id}")
            assert forbidden.status_code == 403

            set_user_session(
                client,
                admin_user,
                ["studio:image", "studio:video", "studio:history"],
            )
            deleted = client.delete(f"/studio/api/history/{task_id}")
            assert deleted.status_code == 200, deleted.data
            assert deleted.json["success"] is True
            assert StudioGenerationTask.query.get(task_id) is None
        finally:
            leftover = StudioGenerationTask.query.get(task_id)
            if leftover is not None:
                db.session.delete(leftover)
                db.session.commit()

    print("studio smoke test passed")


if __name__ == "__main__":
    main()
