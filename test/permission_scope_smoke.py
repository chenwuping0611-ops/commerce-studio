from uuid import uuid4

from applications import create_app
from applications.amazon_ai.service import (
    global_chat_model_state,
)
from applications.common.scope import (
    PROVIDER_OWNER_DEPARTMENT,
    effective_permission_codes,
)
from applications.extensions import db
from applications.models import (
    Dept,
    Role,
    StudioModel,
    StudioProvider,
    StudioSetting,
    User,
)


def set_user_session(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = sorted(effective_permission_codes(user))


def change_password(client, user_id, password):
    return client.put(
        "/admin/user/editPassword",
        json={
            "userId": user_id,
            "newPassword": password,
            "confirmPassword": password,
        },
    )


def main():
    app = create_app()
    with app.app_context():
        token = uuid4().hex[:8]
        created_departments = []
        created_users = []
        created_providers = []
        created_settings = []
        original_admin_hash = None
        original_admin_dept = None
        original_root_setting_value = None
        original_root_setting_description = None
        created_root_setting = False

        root = Dept.query.filter(
            (Dept.parent_id == 0) | (Dept.parent_id.is_(None))
        ).order_by(Dept.id.asc()).first()
        admin = User.query.filter_by(username="admin").first()
        dept_admin_role = Role.query.filter_by(code="dept_admin").first()
        studio_role = Role.query.filter_by(code="studio_user").first()
        assert root and admin and dept_admin_role and studio_role

        department_a = Dept(
            parent_id=root.id,
            dept_name="permission-a-" + token,
            sort=910,
            status=1,
        )
        department_b = Dept(
            parent_id=root.id,
            dept_name="permission-b-" + token,
            sort=911,
            status=1,
        )
        db.session.add_all([department_a, department_b])
        db.session.flush()
        created_departments = [department_a, department_b]

        admin_a = User(
            username="pma-" + token,
            realname="Admin A",
            enable=1,
            dept_id=department_a.id,
        )
        admin_b = User(
            username="pmb-" + token,
            realname="Admin B",
            enable=1,
            dept_id=department_b.id,
        )
        admin_a_peer = User(
            username="pma-peer-" + token,
            realname="Admin A Peer",
            enable=1,
            dept_id=department_a.id,
        )
        operator_a = User(
            username="pua-" + token,
            realname="User A",
            enable=1,
            dept_id=department_a.id,
        )
        operator_b = User(
            username="pub-" + token,
            realname="User B",
            enable=1,
            dept_id=department_b.id,
        )
        for user in (admin_a, admin_b, admin_a_peer):
            user.set_password("123456")
            user.role = [dept_admin_role]
        for user in (operator_a, operator_b):
            user.set_password("123456")
            user.role = [studio_role]
        db.session.add_all([admin_a, admin_b, operator_a, operator_b])
        db.session.flush()
        created_users = [
            admin_a,
            admin_b,
            admin_a_peer,
            operator_a,
            operator_b,
        ]

        provider_a = StudioProvider(
            name="permission-provider-a-" + token,
            owner_type="DEPARTMENT",
            dept_id=department_a.id,
            base_url="https://permission-a.example",
            api_key="permission-key-a-" + token,
            enabled=1,
        )
        provider_b = StudioProvider(
            name="permission-provider-b-" + token,
            owner_type="DEPARTMENT",
            dept_id=department_b.id,
            base_url="https://permission-b.example",
            api_key="permission-key-b-" + token,
            enabled=1,
        )
        admin_provider = StudioProvider(
            name="permission-provider-root-" + token,
            owner_type=PROVIDER_OWNER_DEPARTMENT,
            dept_id=root.id,
            base_url="https://permission-root.example",
            api_key="permission-key-root-" + token,
            enabled=1,
        )
        db.session.add_all([provider_a, provider_b, admin_provider])
        db.session.flush()
        created_providers = [provider_a, provider_b, admin_provider]

        chat_a = StudioModel(
            provider_id=provider_a.id,
            name="Permission Chat A",
            model_code="permission-chat-a-" + token,
            media_type="CHAT",
            enabled=1,
            parameter_schema="[]",
            capabilities="{}",
        )
        chat_b = StudioModel(
            provider_id=provider_b.id,
            name="Permission Chat B",
            model_code="permission-chat-b-" + token,
            media_type="CHAT",
            enabled=1,
            parameter_schema="[]",
            capabilities="{}",
        )
        super_chat = StudioModel(
            provider_id=admin_provider.id,
            name="Permission Chat Super",
            model_code="permission-chat-super-" + token,
            media_type="CHAT",
            enabled=1,
            parameter_schema="[]",
            capabilities="{}",
        )
        db.session.add_all([chat_a, chat_b, super_chat])
        db.session.flush()
        department_settings = [
            StudioSetting(
                setting_key="global_chat_model_id",
                dept_id=department_a.id,
                setting_value=str(chat_a.id),
            ),
            StudioSetting(
                setting_key="global_chat_model_id",
                dept_id=department_b.id,
                setting_value=str(chat_b.id),
            ),
        ]
        super_setting = StudioSetting.query.filter_by(
            setting_key="global_chat_model_id",
            dept_id=root.id,
        ).first()
        if super_setting:
            original_root_setting_value = super_setting.setting_value
            original_root_setting_description = super_setting.description
            super_setting.setting_value = str(super_chat.id)
        else:
            super_setting = StudioSetting(
                setting_key="global_chat_model_id",
                dept_id=root.id,
                setting_value=str(super_chat.id),
            )
            created_root_setting = True
            db.session.add(super_setting)
        created_settings = department_settings
        db.session.add_all(department_settings)
        original_admin_hash = admin.password_hash
        original_admin_dept = admin.dept_id
        db.session.commit()

        try:
            admin.dept_id = department_a.id
            db.session.commit()

            super_client = app.test_client()
            department_client = app.test_client()
            operator_client = app.test_client()
            login_client = app.test_client()
            set_user_session(super_client, admin)
            set_user_session(department_client, admin_a)
            set_user_session(operator_client, operator_a)

            assert login_client.get("/passport/getCaptcha").status_code == 404
            login_response = login_client.post(
                "/passport/login",
                data={"username": "admin", "password": "123456"},
            )
            assert login_response.status_code == 200
            assert login_response.json["success"] is True

            users = super_client.get("/admin/user/data").json["data"]
            assert {item["username"] for item in users} >= {
                "admin",
                admin_a.username,
                admin_b.username,
                operator_a.username,
                operator_b.username,
            }
            department_users = department_client.get(
                "/admin/user/data"
            ).json["data"]
            assert {item["username"] for item in department_users} == {
                admin_a.username,
                admin_a_peer.username,
                operator_a.username,
            }
            assert "admin" not in {
                item["username"] for item in department_users
            }
            operator_users = operator_client.get("/admin/user/data").json["data"]
            assert [item["username"] for item in operator_users] == [
                operator_a.username
            ]

            assert department_client.get("/dept/add").status_code == 403
            assert department_client.get("/admin/task/").status_code == 403

            admin_password = "admin-password-" + token
            assert change_password(
                super_client,
                admin.id,
                admin_password,
            ).json["success"] is True
            assert admin.validate_password(admin_password)

            assert change_password(
                department_client,
                admin_a.id,
                "dept-self-" + token,
            ).json["success"] is True
            assert change_password(
                department_client,
                operator_a.id,
                "dept-user-" + token,
            ).json["success"] is True
            assert not change_password(
                department_client,
                admin_a_peer.id,
                "blocked-peer-admin-" + token,
            ).json["success"]
            assert not change_password(
                department_client,
                admin_b.id,
                "blocked-other-admin-" + token,
            ).json["success"]
            assert not change_password(
                department_client,
                admin.id,
                "blocked-super-" + token,
            ).json["success"]

            assert change_password(
                operator_client,
                operator_a.id,
                "operator-self-" + token,
            ).json["success"] is True
            assert not change_password(
                operator_client,
                operator_b.id,
                "blocked-other-user-" + token,
            ).json["success"]
            assert not change_password(
                operator_client,
                admin_a.id,
                "blocked-dept-admin-" + token,
            ).json["success"]

            department_providers = department_client.get(
                "/studio/api/providers"
            )
            assert department_providers.status_code == 200
            provider_payload = department_providers.get_data(as_text=True)
            assert provider_a.name in provider_payload
            assert provider_b.name not in provider_payload
            assert admin_provider.name not in provider_payload
            assert "permission-key-a-" + token not in provider_payload

            super_providers = super_client.get("/studio/api/providers")
            assert super_providers.status_code == 200
            super_payload = super_providers.get_data(as_text=True)
            assert provider_a.name in super_payload
            assert provider_b.name in super_payload
            assert admin_provider.name in super_payload
            assert "permission-key-a-" + token not in super_payload
            assert "permission-key-root-" + token not in super_payload

            assert operator_client.get("/studio/api/providers").status_code == 403

            scoped_state = global_chat_model_state(
                department_b.id,
                user=admin_a,
            )
            assert scoped_state["dept_id"] == department_a.id
            assert scoped_state["model"]["id"] == chat_a.id
            super_state = global_chat_model_state(
                root.id,
                owner_type="SUPER_ADMIN",
                user=admin,
            )
            assert super_state["owner_type"] == PROVIDER_OWNER_DEPARTMENT
            assert super_state["dept_id"] == root.id
            assert super_state["model"]["id"] == super_chat.id

            menu = department_client.get("/rights/menu")
            assert menu.status_code == 200
            root_codes = {item["code"] for item in menu.json}
            assert {"admin:system:root", "studio:root"} <= root_codes

            print("permission scope smoke test passed")
        finally:
            db.session.rollback()
            admin.password_hash = original_admin_hash
            admin.dept_id = original_admin_dept
            for setting in created_settings:
                db.session.delete(setting)
            if created_root_setting:
                db.session.delete(super_setting)
            else:
                super_setting.setting_value = original_root_setting_value
                super_setting.description = original_root_setting_description
            for user in created_users:
                user.role = []
                db.session.delete(user)
            for provider in created_providers:
                db.session.delete(provider)
            for department in created_departments:
                db.session.delete(department)
            db.session.commit()


if __name__ == "__main__":
    main()
