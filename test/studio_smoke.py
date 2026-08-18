from applications import create_app
from applications.models import Power, StudioModel, StudioProvider, User


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
    assert any(
        item["code"] == "studio:providers"
        for item in system_root.get("children", [])
    )

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
        assert StudioProvider.query.filter_by(name="ToAPIs").count() == 1
        assert StudioModel.query.filter_by(model_code="gpt-image-2").count() == 1
        assert StudioModel.query.filter_by(model_code="seedance-2").count() == 1

    print("studio smoke test passed")


if __name__ == "__main__":
    main()
