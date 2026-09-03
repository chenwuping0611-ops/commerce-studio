"""Smoke check for department-scoped users reading the global feedback Skill."""

import json
from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.common.scope import effective_permission_codes
from applications.extensions import db
from applications.models import (
    Role,
    StudioGenerationComment,
    StudioGenerationTask,
    StudioModel,
    StudioProduct,
    StudioProvider,
    User,
)
from applications.view.studio import routes as studio_routes


class FakeFeedbackClient:
    def __init__(self, provider):
        self.provider = provider

    def complete(self, model, body):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "analysis": "部门管理员反馈读取成功",
                                "product_updates": {},
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
        token = uuid4().hex[:8]
        product = (
            StudioProduct.query.filter(
                StudioProduct.enabled == 1,
                StudioProduct.dept_id.isnot(None),
            )
            .order_by(StudioProduct.id.asc())
            .first()
        )
        dept_admin_role = Role.query.filter_by(code="dept_admin").first()
        assert product is not None and dept_admin_role is not None

        chat_model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.media_type == "CHAT",
                StudioModel.enabled == 1,
                StudioProvider.enabled == 1,
                StudioProvider.dept_id == product.dept_id,
            )
            .order_by(StudioModel.id.asc())
            .first()
        )
        assert chat_model is not None and chat_model.provider is not None

        department_user = User(
            username="fbscope-" + token,
            realname="Feedback Scope Admin",
            enable=1,
            dept_id=product.dept_id,
        )
        department_user.set_password("123456")
        department_user.role = [dept_admin_role]

        task = StudioGenerationTask(
            dept_id=product.dept_id,
            task_code=("F" + token)[:7],
            user_id=department_user.id,
            media_type="IMAGE",
            product_id=product.id,
            model_id=None,
            prompt="部门反馈权限烟测",
            final_prompt="部门反馈权限烟测",
            output_url="https://cdn.example/feedback-scope.png",
            status="SUCCEEDED",
            progress=100,
        )
        db.session.add(department_user)
        db.session.flush()
        task.user_id = department_user.id
        db.session.add(task)
        db.session.flush()
        original_api_key = chat_model.provider.api_key
        chat_model.provider.api_key = "feedback-scope-smoke-key"
        db.session.commit()

        client = app.test_client()
        _set_session(client, department_user)
        try:
            with patch.object(
                studio_routes,
                "_global_chat_model",
                return_value=chat_model,
            ), patch.object(
                studio_routes,
                "ProviderClient",
                FakeFeedbackClient,
            ):
                response = client.post(
                    f"/studio/api/tasks/{task.task_code}/comments/analyze",
                    json={"feedback": "请确认部门管理员可以提交意见反馈"},
                )

            assert response.status_code == 200, response.get_data(as_text=True)
            assert response.json["success"] is True, response.json
            assert "部门反馈权限烟测" not in (
                response.json.get("msg") or ""
            )
            comment = StudioGenerationComment.query.filter_by(
                generation_task_id=task.id,
                user_id=department_user.id,
            ).first()
            assert comment is not None
            assert comment.status == "SUCCEEDED"
        finally:
            StudioGenerationComment.query.filter_by(
                generation_task_id=task.id,
            ).delete(synchronize_session=False)
            db.session.delete(task)
            department_user.role = []
            db.session.delete(department_user)
            chat_model.provider.api_key = original_api_key
            db.session.commit()

    print("studio feedback scope smoke test passed")


if __name__ == "__main__":
    main()
