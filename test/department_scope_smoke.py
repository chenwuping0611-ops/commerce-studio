from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.amazon_ai.service import global_chat_model_state
from applications.common.scope import effective_permission_codes
from applications.extensions import db
from applications.models import (
    AmazonAiTask,
    Dept,
    Power,
    Role,
    StudioGenerationTask,
    StudioModel,
    StudioProvider,
    StudioSetting,
    User,
)
from applications.studio import generation_service
from applications.amazon_ai.skill_catalog import BATCH_DETAIL_IMAGE_SKILL_CODE


def _set_session(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = sorted(effective_permission_codes(user))


def main():
    app = create_app()
    with app.app_context():
        token = uuid4().hex[:6]
        ids = {
            "departments": [],
            "users": [],
            "roles": [],
            "providers": [],
            "amazon_tasks": [],
            "tasks": [],
        }
        original_studio_powers = None
        try:
            root = Dept.query.filter(
                (Dept.parent_id == 0) | (Dept.parent_id.is_(None))
            ).order_by(Dept.id.asc()).first()
            assert root is not None

            department_a = Dept(
                parent_id=root.id,
                dept_name="scope-a-" + token,
                sort=90,
                status=1,
            )
            department_b = Dept(
                parent_id=root.id,
                dept_name="scope-b-" + token,
                sort=91,
                status=1,
            )
            db.session.add_all([department_a, department_b])
            db.session.flush()
            ids["departments"] = [department_a.id, department_b.id]

            department_role = Role.query.filter_by(code="dept_admin").first()
            studio_role = Role.query.filter_by(code="studio_user").first()
            super_admin = User.query.filter_by(username="admin").first()
            assert department_role is not None
            assert studio_role is not None
            assert super_admin is not None

            amazon_power_codes = {
                "amazon_ai:root",
                "amazon_ai:dashboard",
                "amazon_ai:history",
                "amazon_ai:competitor",
                "amazon_ai:differentiation",
                "amazon_ai:basic_info",
                "amazon_ai:listing_create",
            }
            amazon_powers = Power.query.filter(
                Power.code.in_(amazon_power_codes),
                Power.enable == 1,
            ).all()
            assert {
                power.code for power in amazon_powers
            } == amazon_power_codes
            original_studio_powers = list(studio_role.power)
            studio_role.power = list(
                {
                    power.id: power
                    for power in original_studio_powers + amazon_powers
                }.values()
            )

            admin_a = User(
                username="sc-a-" + token,
                realname="Scope A",
                enable=1,
                dept_id=department_a.id,
            )
            admin_b = User(
                username="sc-b-" + token,
                realname="Scope B",
                enable=1,
                dept_id=department_b.id,
            )
            admin_a.set_password("123456")
            admin_b.set_password("123456")
            admin_a.role = [department_role]
            admin_b.role = [department_role]
            operator_a = User(
                username="scope-op-a-" + token,
                realname="Operator A",
                enable=1,
                dept_id=department_a.id,
            )
            operator_a_peer = User(
                username="scope-peer-" + token,
                realname="Operator A Peer",
                enable=1,
                dept_id=department_a.id,
            )
            operator_b = User(
                username="scope-op-b-" + token,
                realname="Operator B",
                enable=1,
                dept_id=department_b.id,
            )
            for operator in (operator_a, operator_a_peer, operator_b):
                operator.set_password("123456")
                operator.role = [studio_role]
            db.session.add_all(
                [
                    admin_a,
                    admin_b,
                    operator_a,
                    operator_a_peer,
                    operator_b,
                ]
            )
            db.session.flush()
            ids["users"] = [
                admin_a.id,
                admin_b.id,
                operator_a.id,
                operator_a_peer.id,
                operator_b.id,
            ]

            custom_role = Role(
                name="Scope Role",
                code="scope-role-" + token,
                enable=1,
                dept_id=department_a.id,
                created_by=admin_a.id,
            )
            db.session.add(custom_role)
            db.session.flush()
            ids["roles"] = [custom_role.id]

            provider_a = StudioProvider(
                name="scope-provider-a-" + token,
                dept_id=department_a.id,
                base_url="https://a.example",
                api_key="key-a",
                enabled=1,
            )
            provider_b = StudioProvider(
                name="scope-provider-b-" + token,
                dept_id=department_b.id,
                base_url="https://b.example",
                api_key="key-b",
                enabled=1,
            )
            db.session.add_all([provider_a, provider_b])
            db.session.flush()
            ids["providers"] = [provider_a.id, provider_b.id]

            image_a = StudioModel(
                provider_id=provider_a.id,
                name="Scope Image A",
                model_code="scope-image-a-" + token,
                media_type="IMAGE",
                enabled=1,
                parameter_schema="[]",
                capabilities="{}",
            )
            image_b = StudioModel(
                provider_id=provider_b.id,
                name="Scope Image B",
                model_code="scope-image-b-" + token,
                media_type="IMAGE",
                enabled=1,
                parameter_schema="[]",
                capabilities="{}",
            )
            chat_a = StudioModel(
                provider_id=provider_a.id,
                name="Scope Chat A",
                model_code="gpt-5.4",
                media_type="CHAT",
                enabled=1,
                parameter_schema="[]",
                capabilities="{}",
            )
            chat_b = StudioModel(
                provider_id=provider_b.id,
                name="Scope Chat B",
                model_code="gpt-5.4",
                media_type="CHAT",
                enabled=1,
                parameter_schema="[]",
                capabilities="{}",
            )
            db.session.add_all([image_a, image_b, chat_a, chat_b])
            db.session.flush()

            db.session.add_all(
                [
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
            )

            studio_task_a = StudioGenerationTask(
                dept_id=department_a.id,
                task_code="I" + token,
                user_id=operator_a.id,
                media_type="IMAGE",
                model_id=image_a.id,
                prompt="operator A image",
                status="SUCCEEDED",
                progress=100,
            )
            studio_task_a_peer = StudioGenerationTask(
                dept_id=department_a.id,
                task_code="V" + token,
                user_id=operator_a_peer.id,
                media_type="VIDEO",
                model_id=image_a.id,
                prompt="operator A peer video",
                status="SUCCEEDED",
                progress=100,
            )
            studio_task_b = StudioGenerationTask(
                dept_id=department_b.id,
                task_code="B" + token,
                user_id=operator_b.id,
                media_type="IMAGE",
                model_id=image_b.id,
                prompt="operator B image",
                status="SUCCEEDED",
                progress=100,
            )
            db.session.add_all(
                [studio_task_a, studio_task_a_peer, studio_task_b]
            )
            db.session.flush()
            ids["tasks"] = [
                studio_task_a.id,
                studio_task_a_peer.id,
                studio_task_b.id,
            ]

            amazon_task_a = AmazonAiTask(
                dept_id=department_a.id,
                task_code="SCOPE-A-" + token,
                task_type="COMPETITOR_ANALYZE",
                title="Scope Competitor A",
                status="SUCCEEDED",
                progress=100,
                user_id=admin_a.id,
            )
            amazon_task_b = AmazonAiTask(
                dept_id=department_b.id,
                task_code="SCOPE-B-" + token,
                task_type="COMPETITOR_ANALYZE",
                title="Scope Competitor B",
                status="SUCCEEDED",
                progress=100,
                user_id=admin_b.id,
            )
            amazon_task_operator_a = AmazonAiTask(
                dept_id=department_a.id,
                task_code="SCOPE-OA-" + token,
                task_type="COMPETITOR_ANALYZE",
                title="Scope Operator A",
                status="SUCCEEDED",
                progress=100,
                user_id=operator_a.id,
            )
            amazon_task_operator_a_peer = AmazonAiTask(
                dept_id=department_a.id,
                task_code="SCOPE-OP-" + token,
                task_type="COMPETITOR_ANALYZE",
                title="Scope Operator A Peer",
                status="SUCCEEDED",
                progress=100,
                user_id=operator_a_peer.id,
            )
            amazon_task_operator_b = AmazonAiTask(
                dept_id=department_b.id,
                task_code="SCOPE-OB-" + token,
                task_type="COMPETITOR_ANALYZE",
                title="Scope Operator B",
                status="SUCCEEDED",
                progress=100,
                user_id=operator_b.id,
            )
            db.session.add_all(
                [
                    amazon_task_a,
                    amazon_task_b,
                    amazon_task_operator_a,
                    amazon_task_operator_a_peer,
                    amazon_task_operator_b,
                ]
            )
            db.session.commit()
            ids["amazon_tasks"] = [
                amazon_task_a.id,
                amazon_task_b.id,
                amazon_task_operator_a.id,
                amazon_task_operator_a_peer.id,
                amazon_task_operator_b.id,
            ]

            client_a = app.test_client()
            super_client = app.test_client()
            operator_a_client = app.test_client()
            operator_a_peer_client = app.test_client()
            operator_b_client = app.test_client()
            _set_session(client_a, admin_a)
            _set_session(super_client, super_admin)
            _set_session(operator_a_client, operator_a)
            _set_session(operator_a_peer_client, operator_a_peer)
            _set_session(operator_b_client, operator_b)

            response = client_a.get("/studio/forms/skill")
            assert response.status_code == 200

            response = super_client.post("/dept/data")
            assert response.status_code == 200
            assert all(
                not {"phone", "email", "address"} & set(item)
                for item in response.json["data"]
            )
            response = super_client.post("/dept/data?include_users=1")
            assert response.status_code == 200
            department_rows = response.json["data"]
            root_row = next(
                item for item in department_rows
                if item["deptId"] == root.id
            )
            assert root_row["parentId"] == 0
            operator_a_row = next(
                item for item in department_rows
                if item.get("userId") == operator_a.id
            )
            operator_a_peer_row = next(
                item for item in department_rows
                if item.get("userId") == operator_a_peer.id
            )
            assert operator_a_row["nodeType"] == "USER"
            assert operator_a_row["parentId"] == department_a.id
            assert operator_a_row["leader"] == studio_role.name
            assert operator_a_peer_row["parentId"] == department_a.id
            assert not any(
                item.get("nodeType") == "USER"
                for item in super_client.get("/dept/tree").json["data"]
            )

            response = client_a.get("/studio/api/providers")
            assert response.status_code == 200
            department_provider_rows = response.json["data"]
            assert provider_a.id in {
                item["id"] for item in department_provider_rows
            }
            assert all(
                item["dept_id"] == department_a.id
                and item["owner_type"] == "DEPARTMENT"
                for item in department_provider_rows
            )
            assert {"ToAPIs", "快跑AI", "接口AI"} <= {
                item["name"] for item in department_provider_rows
            }

            response = client_a.get(
                f"/studio/api/providers?dept_id={department_b.id}"
            )
            assert response.status_code == 200
            assert response.json["data"] == []

            response = client_a.get("/studio/api/options?media_type=IMAGE")
            assert response.status_code == 200
            option_models = response.json["data"]["models"]
            assert image_a.id in {item["id"] for item in option_models}
            assert image_b.id not in {item["id"] for item in option_models}
            assert all(
                item["dept_id"] == department_a.id
                for item in option_models
            )
            assert all(
                "dept_id" in item for item in response.json["data"]["skills"]
            )
            batch_skill_a = next(
                item
                for item in response.json["data"]["skills"]
                if item["name"] == "Amazon 电商批量详情图提示词 Skill"
            )
            assert batch_skill_a["is_builtin"] is True
            assert batch_skill_a["dept_name"]

            response = operator_b_client.get(
                "/studio/api/options?media_type=IMAGE"
            )
            assert response.status_code == 200
            batch_skill_b = next(
                item
                for item in response.json["data"]["skills"]
                if item["name"] == "Amazon 电商批量详情图提示词 Skill"
            )
            assert batch_skill_b["is_builtin"] is True
            assert batch_skill_b["dept_name"] == batch_skill_a["dept_name"]

            response = operator_b_client.get("/studio/api/skills")
            assert response.status_code == 200
            visible_batch_skill = next(
                item
                for item in response.json["data"]
                if item["code"] == BATCH_DETAIL_IMAGE_SKILL_CODE
            )
            assert visible_batch_skill["is_builtin"] is True
            assert visible_batch_skill["dept_name"] == batch_skill_a["dept_name"]
            assert visible_batch_skill["file_available"] is True
            response = operator_b_client.get(
                "/studio/api/skills?include_content=1&id="
                + str(visible_batch_skill["id"])
            )
            assert response.status_code == 200
            readable_batch_skill = response.json["data"][0]
            assert "逐画面执行协议" in readable_batch_skill["content"]
            assert readable_batch_skill["dept_name"] == batch_skill_a["dept_name"]

            response = super_client.get("/studio/api/providers")
            assert response.status_code == 200
            assert {provider_a.id, provider_b.id} <= {
                item["id"] for item in response.json["data"]
            }

            response = client_a.post(
                "/studio/api/providers",
                json={
                    "name": "scope-spoof-" + token,
                    "base_url": "https://spoof.example",
                    "api_key": "spoof-key",
                    "dept_id": department_b.id,
                },
            )
            assert response.status_code == 200
            spoof_provider = StudioProvider.query.filter_by(
                name="scope-spoof-" + token
            ).first()
            assert spoof_provider is not None
            assert spoof_provider.dept_id == department_a.id
            ids["providers"].append(spoof_provider.id)

            response = client_a.post(
                "/admin/user/save",
                json={
                    "username": "sc-u-" + token,
                    "realName": "Scoped User",
                    "password": "123456",
                    "deptId": department_b.id,
                    "roleIds": str(studio_role.id),
                },
            )
            assert response.status_code == 200
            assert response.json["success"] is True
            created_user = User.query.filter_by(
                username="sc-u-" + token
            ).first()
            assert created_user is not None
            assert created_user.dept_id == department_a.id
            ids["users"].append(created_user.id)

            response = client_a.put(
                "/admin/role/update",
                json={
                    "roleId": custom_role.id,
                    "roleCode": "admin",
                    "roleName": "Escalated",
                    "sort": 10,
                    "enable": 1,
                    "details": "",
                },
            )
            assert response.status_code == 200
            assert response.json["success"] is False
            assert Role.query.get(custom_role.id).code == "scope-role-" + token

            response = client_a.get("/amazon-ai/api/listing-projects")
            assert response.status_code == 200
            assert response.json["data"] == []

            response = client_a.get("/amazon-ai/api/competitors")
            assert response.status_code == 200
            assert {
                amazon_task_a.id,
                amazon_task_operator_a.id,
                amazon_task_operator_a_peer.id,
            } <= {item["id"] for item in response.json["data"]}
            assert amazon_task_b.id not in {
                item["id"] for item in response.json["data"]
            }

            response = super_client.get("/amazon-ai/api/competitors")
            assert response.status_code == 200
            assert {
                amazon_task_a.id,
                amazon_task_b.id,
                amazon_task_operator_a.id,
                amazon_task_operator_a_peer.id,
                amazon_task_operator_b.id,
            } <= {
                item["id"] for item in response.json["data"]
            }

            response = operator_a_client.get(
                "/amazon-ai/api/competitors/history"
            )
            assert response.status_code == 200
            assert {item["id"] for item in response.json["data"]} == {
                amazon_task_operator_a.id
            }
            response = operator_a_client.get(
                f"/amazon-ai/api/tasks/{amazon_task_operator_a.id}/result"
            )
            assert response.status_code == 200
            assert operator_a_client.get(
                "/amazon-ai/api/competitors/history/"
                f"{amazon_task_operator_a_peer.task_code}/result"
            ).status_code == 404
            assert operator_a_client.get(
                f"/amazon-ai/api/tasks/{amazon_task_operator_a_peer.id}/result"
            ).status_code == 404

            response = operator_a_peer_client.get(
                "/amazon-ai/api/competitors/history"
            )
            assert response.status_code == 200
            assert {item["id"] for item in response.json["data"]} == {
                amazon_task_operator_a_peer.id
            }
            response = client_a.get("/amazon-ai/api/competitors/history")
            assert response.status_code == 200
            assert {
                amazon_task_a.id,
                amazon_task_operator_a.id,
                amazon_task_operator_a_peer.id,
            } <= {item["id"] for item in response.json["data"]}
            assert amazon_task_b.id not in {
                item["id"] for item in response.json["data"]
            }
            response = operator_b_client.get(
                "/amazon-ai/api/competitors/history"
            )
            assert response.status_code == 200
            assert {item["id"] for item in response.json["data"]} == {
                amazon_task_operator_b.id
            }

            response = operator_a_client.get("/studio/api/history")
            assert response.status_code == 200
            assert {item["id"] for item in response.json["data"]} == {
                studio_task_a.id
            }
            assert operator_a_client.get(
                f"/studio/api/tasks/{studio_task_a_peer.task_code}"
            ).status_code == 404
            response = operator_a_peer_client.get(
                "/studio/api/history?media_type=VIDEO"
            )
            assert response.status_code == 200
            assert {item["id"] for item in response.json["data"]} == {
                studio_task_a_peer.id
            }
            response = client_a.get("/studio/api/history")
            assert response.status_code == 200
            assert {
                studio_task_a.id,
                studio_task_a_peer.id,
            } <= {item["id"] for item in response.json["data"]}
            assert studio_task_b.id not in {
                item["id"] for item in response.json["data"]
            }
            response = super_client.get("/studio/api/history")
            assert response.status_code == 200
            assert {
                studio_task_a.id,
                studio_task_a_peer.id,
                studio_task_b.id,
            } <= {item["id"] for item in response.json["data"]}

            state_a = global_chat_model_state(department_a.id)
            state_b = global_chat_model_state(department_b.id)
            assert state_a["allowed"]
            assert state_a["model"]["id"] == chat_a.id
            assert state_a["model"]["provider_id"] == provider_a.id
            assert state_b["allowed"]
            assert state_b["model"]["id"] == chat_b.id
            assert state_b["model"]["provider_id"] == provider_b.id

            captured_keys = []

            class FakeProviderClient:
                def __init__(self, provider):
                    captured_keys.append(provider.api_key)

                def submit_generation(self, model, body):
                    return {"id": "scope-provider-task"}

            with patch.object(
                generation_service,
                "ProviderClient",
                FakeProviderClient,
            ):
                task_a = generation_service.create_generation(
                    user_id=admin_a.id,
                    media_type="IMAGE",
                    model_id=image_a.id,
                    product_id=None,
                    prompt="department A image",
                    options={},
                )
                task_b = generation_service.create_generation(
                    user_id=super_admin.id,
                    media_type="IMAGE",
                    model_id=image_b.id,
                    product_id=None,
                    prompt="super admin department B image",
                    options={"department_id": department_b.id},
                )
                assert task_a.dept_id == department_a.id
                assert task_b.dept_id == department_b.id
                assert captured_keys == ["key-a", "key-b"]
                ids["tasks"].extend([task_a.id, task_b.id])

                try:
                    generation_service.create_generation(
                        user_id=admin_a.id,
                        media_type="IMAGE",
                        model_id=image_b.id,
                        product_id=None,
                        prompt="cross department image",
                        options={},
                    )
                except ValueError as exc:
                    assert "模型不存在" in str(exc) or "无权" in str(exc)
                else:
                    raise AssertionError(
                        "cross-department model was accepted"
                    )

            print("department isolation and routing smoke test passed")
        finally:
            db.session.rollback()
            if original_studio_powers is not None:
                studio_role.power = original_studio_powers
            if ids["tasks"]:
                StudioGenerationTask.query.filter(
                    StudioGenerationTask.id.in_(ids["tasks"])
                ).delete(synchronize_session=False)
            if ids["amazon_tasks"]:
                AmazonAiTask.query.filter(
                    AmazonAiTask.id.in_(ids["amazon_tasks"])
                ).delete(synchronize_session=False)
            if ids["departments"]:
                StudioSetting.query.filter(
                    StudioSetting.dept_id.in_(ids["departments"])
                ).delete(synchronize_session=False)
            for user_id in ids["users"]:
                user = User.query.get(user_id)
                if user:
                    user.role = []
                    db.session.delete(user)
            provider_rows = StudioProvider.query.filter(
                StudioProvider.dept_id.in_(ids["departments"])
            ).all()
            provider_rows.extend(
                StudioProvider.query.filter(
                    StudioProvider.id.in_(ids["providers"])
                ).all()
            )
            seen_provider_ids = set()
            for provider in provider_rows:
                if provider.id in seen_provider_ids:
                    continue
                seen_provider_ids.add(provider.id)
                if provider:
                    db.session.delete(provider)
            for role_id in ids["roles"]:
                role = Role.query.get(role_id)
                if role:
                    role.power = []
                    db.session.delete(role)
            if ids["departments"]:
                Dept.query.filter(
                    Dept.id.in_(ids["departments"])
                ).delete(synchronize_session=False)
            db.session.commit()


if __name__ == "__main__":
    main()
