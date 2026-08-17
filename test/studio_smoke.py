from applications import create_app
from applications.models import Power, StudioModel, StudioProvider, User


def main():
    app = create_app()
    client = app.test_client()

    assert client.get("/passport/login").status_code == 200
    with client.session_transaction() as session:
        session["code"] = "test"

    response = client.post(
        "/passport/login",
        data={"username": "admin", "password": "123456", "captcha": "test"},
    )
    assert response.status_code == 200, response.data
    assert response.json["success"] is True, response.json

    assert client.get("/admin/").status_code == 200
    for path in (
        "/studio/",
        "/studio/image",
        "/studio/video",
        "/studio/products",
        "/studio/skills",
        "/studio/history",
        "/studio/providers",
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
