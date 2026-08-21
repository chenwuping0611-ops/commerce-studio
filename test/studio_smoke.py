from applications import create_app
from applications.extensions import db
import json
import secrets

from applications.models import (
    Power,
    Role,
    StudioGenerationTask,
    StudioModel,
    StudioProvider,
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
        task_code = str(secrets.randbelow(9_000_000) + 1_000_000)
        if task_code not in existing:
            return task_code


def main():
    app = create_app()
    client = app.test_client()

    assert client.get("/passport/login").status_code == 200
    captcha_response = client.get("/passport/getCaptcha")
    assert captcha_response.status_code == 200
    assert captcha_response.content_type == "image/png"
    assert captcha_response.data.startswith(b"\x89PNG")

    with client.session_transaction() as session:
        session["code"] = "test"

    response = client.post(
        "/passport/login",
        data={"username": "admin", "password": "123456", "captcha": "test"},
    )
    assert response.status_code == 200, response.data
    assert response.json["success"] is True, response.json

    assert client.get("/admin/").status_code == 200
    menu_response = client.get("/rights/menu")
    assert menu_response.status_code == 200
    menu_roots = menu_response.json
    assert [item["code"] for item in menu_roots] == [
        "studio:root",
        "admin:system:root",
    ]
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

    with app.app_context():
        assert User.query.filter_by(username="admin").count() == 1
        assert Power.query.filter(Power.code.like("studio:%")).count() >= 7
        studio_role = Role.query.filter_by(code="studio_user").first()
        assert studio_role is not None
        assert all(
            power.code.startswith("studio:")
            and power.code != "studio:providers"
            for power in studio_role.power
        )
        assert any(power.code == "studio:image" for power in studio_role.power)
        assert not any(
            power.code.startswith("admin:") for power in studio_role.power
        )
        assert not any(
            power.code == "studio:providers" for power in studio_role.power
        )
        assert StudioProvider.query.filter_by(name="ToAPIs").count() == 1
        assert StudioModel.query.filter_by(model_code="gpt-image-2").count() == 1
        seedance = StudioModel.query.filter_by(model_code="seedance-2").first()
        assert seedance is not None
        seedance_parameters = json.loads(seedance.parameter_schema or "[]")
        audio_parameter = next(
            item for item in seedance_parameters
            if item.get("field") == "generate_audio"
        )
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
