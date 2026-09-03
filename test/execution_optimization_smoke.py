"""Focused checks for execution races, storage rollback, and keyset history."""

import json
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.common.scope import effective_permission_codes
from applications.common.storage import FileService, StoredFile
from applications.extensions import db
from applications.amazon_ai.service import AmazonAiService
from applications.studio import generation_service
from applications.studio.generation_service import create_generation
from applications.models import (
    AmazonAiTask,
    Dept,
    StudioAsset,
    StudioGenerationTask,
    StudioModel,
    StudioProvider,
    User,
)


def _set_session(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = sorted(effective_permission_codes(user))


def _fake_result_file(data, filename, **kwargs):
    token = uuid4().hex
    return StoredFile(
        storage_path=f"/smoke/optimization/{token}/{filename}",
        public_url=f"https://files.example/optimization/{token}/{filename}",
        original_filename=filename,
        content_type=kwargs.get("content_type") or "text/plain",
        file_size=len(data or b""),
        checksum=f"optimization-{token}",
    )


def main():
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        assert admin is not None
        client = app.test_client()
        _set_session(client, admin)

        token = uuid4().hex[:10]
        created_amazon_ids = []
        created_studio_ids = []
        created_poll_ids = []
        created_model_ids = []
        created_provider_ids = []
        generation_prompt = f"studio-cancel-{token}"
        try:
            department_id = admin.dept_id
            if not department_id:
                department = Dept.query.order_by(Dept.id.asc()).first()
                assert department is not None
                department_id = department.id

            provider = StudioProvider(
                name=f"optimization-provider-{token}",
                dept_id=department_id,
                owner_type="DEPARTMENT",
                base_url="https://optimization.example/v1",
                api_key="test-key",
                generation_path="/responses",
                result_path="/responses/{task_id}",
                enabled=1,
            )
            db.session.add(provider)
            db.session.flush()
            created_provider_ids.append(provider.id)

            chat_model = StudioModel(
                provider_id=provider.id,
                name=f"Optimization Chat {token}",
                model_code=f"optimization-chat-{token}",
                media_type="CHAT",
                generation_path="/responses",
                parameter_schema="[]",
                capabilities="{}",
                enabled=1,
            )
            image_model = StudioModel(
                provider_id=provider.id,
                name=f"Optimization Image {token}",
                model_code=f"optimization-image-{token}",
                media_type="IMAGE",
                generation_path="/images/generations",
                parameter_schema="[]",
                capabilities="{}",
                enabled=1,
            )
            db.session.add_all([chat_model, image_model])
            db.session.commit()
            created_model_ids.extend([chat_model.id, image_model.id])

            cursor_tasks = []
            base_time = datetime.now() - timedelta(minutes=3)
            for index in range(3):
                task = AmazonAiTask(
                    task_code=f"AMZ-OPT-{token}-{index}",
                    task_type="LISTING_AUDIT",
                    title="优化游标测试",
                    status="FAILED",
                    user_id=admin.id,
                    dept_id=admin.dept_id,
                    created_at=base_time + timedelta(seconds=index),
                    updated_at=base_time + timedelta(seconds=index),
                    input_refs_json=json.dumps({"asset_ids": []}),
                )
                db.session.add(task)
                cursor_tasks.append(task)
            claim_task = AmazonAiTask(
                task_code=f"AMZ-OPT-CLAIM-{token}",
                task_type="COMPETITOR_ANALYZE",
                title="优化抢占测试",
                status="PENDING",
                user_id=admin.id,
                dept_id=admin.dept_id,
                output_filename=f"cancel-{token}.txt",
                input_refs_json=json.dumps({"asset_ids": []}),
            )
            db.session.add(claim_task)
            db.session.flush()
            created_amazon_ids.extend(
                task.id for task in cursor_tasks
            )
            created_amazon_ids.append(claim_task.id)
            db.session.commit()

            service = AmazonAiService()
            claimed = service._claim_execution_task(claim_task.id)
            assert claimed.status == "RUNNING"
            try:
                service._claim_execution_task(claim_task.id)
            except ValueError as exc:
                assert "正在执行" in str(exc)
            else:
                raise AssertionError("a running task was claimed twice")

            first_page = client.get(
                "/amazon-ai/api/tasks",
                query_string={
                    "task_type": "LISTING_AUDIT",
                    "page": 1,
                    "page_size": 2,
                },
            )
            assert first_page.status_code == 200, first_page.json
            first_ids = [item["id"] for item in first_page.json["data"]]
            first_meta = first_page.json["meta"]
            assert len(first_ids) == 2
            assert first_meta["next_cursor"]

            next_cursor = first_meta["next_cursor"]
            second_page = client.get(
                "/amazon-ai/api/tasks",
                query_string={
                    "task_type": "LISTING_AUDIT",
                    "page_size": 2,
                    "cursor_created_at": next_cursor["cursor_created_at"],
                    "cursor_id": next_cursor["cursor_id"],
                },
            )
            assert second_page.status_code == 200, second_page.json
            second_ids = [item["id"] for item in second_page.json["data"]]
            assert not set(first_ids) & set(second_ids)
            assert second_page.json["meta"]["total"] is None

            cancel_task = AmazonAiTask(
                task_code=f"AMZ-OPT-CANCEL-{token}",
                task_type="COMPETITOR_ANALYZE",
                title="优化取消回收测试",
                status="PENDING",
                user_id=admin.id,
                dept_id=admin.dept_id,
                input_refs_json=json.dumps({"asset_ids": []}),
            )
            db.session.add(cancel_task)
            db.session.commit()
            created_amazon_ids.append(cancel_task.id)

            def fake_complete(_self, _model, _body):
                current = AmazonAiTask.query.get(cancel_task.id)
                current.status = "CANCELLED"
                current.finished_at = datetime.now()
                db.session.commit()
                return {"output_text": "this result must be discarded"}

            with patch.object(
                AmazonAiService,
                "require_global_model",
                return_value=chat_model,
            ), patch(
                "applications.amazon_ai.service.ProviderClient.complete",
                autospec=True,
                side_effect=fake_complete,
            ), patch(
                "applications.amazon_ai.service.FileService.upload_bytes",
                side_effect=_fake_result_file,
            ), patch(
                "applications.amazon_ai.service.FileService.download_url",
                return_value="https://files.example/download/result.txt",
            ), patch(
                "applications.amazon_ai.service.FileService.delete_storage",
                return_value=True,
            ) as delete_storage:
                response = client.post(
                    f"/amazon-ai/api/tasks/{cancel_task.task_code}/run",
                    json={},
                )
            assert response.status_code == 400, response.json
            assert "取消" in response.json["msg"]
            assert delete_storage.call_count == 1
            refreshed_cancel = AmazonAiTask.query.get(cancel_task.id)
            assert refreshed_cancel.status == "CANCELLED"
            assert not StudioAsset.query.filter_by(
                purpose="AMAZON_RESULT",
                original_filename=f"cancel-{token}.txt",
            ).first()

            def cancel_generation_before_return(_self, _model, _body):
                current = StudioGenerationTask.query.filter_by(
                    prompt=generation_prompt,
                ).first()
                assert current is not None
                current.status = "CANCELLED"
                current.completed_at = datetime.now()
                db.session.commit()
                return {
                    "status": "completed",
                    "output_url": (
                        "https://upstream.example/"
                        f"{token}/result.png"
                    ),
                }

            def fake_upload_from_url(_url, filename=None, **_kwargs):
                return _fake_result_file(
                    b"cancelled generation output",
                    filename or f"cancel-{token}.png",
                    content_type="image/png",
                )

            with patch(
                "applications.studio.generation_service.ProviderClient.submit_generation",
                autospec=True,
                side_effect=cancel_generation_before_return,
            ), patch.object(
                FileService,
                "upload_from_url",
                side_effect=fake_upload_from_url,
            ), patch.object(
                FileService,
                "delete_storage",
                return_value=True,
            ) as studio_delete_storage:
                generation_task = create_generation(
                    user_id=admin.id,
                    media_type="IMAGE",
                    model_id=image_model.id,
                    product_id=None,
                    prompt=generation_prompt,
                    options={},
                )

            created_studio_ids.append(generation_task.id)
            assert generation_task.status == "CANCELLED"
            assert studio_delete_storage.call_count == 1
            assert not StudioAsset.query.filter(
                StudioAsset.storage_path.like(f"/smoke/optimization/%"),
                StudioAsset.original_filename.like(f"%{token}%"),
            ).first()

            poll_tasks = []
            poll_started = []
            poll_threads = []
            poll_lock = threading.Lock()
            poll_ready = threading.Event()
            poll_base_time = datetime.now() - timedelta(minutes=1)
            for index in range(3):
                poll_task_row = StudioGenerationTask(
                    task_code=f"P{token[:5]}{index}",
                    dept_id=department_id,
                    user_id=admin.id,
                    media_type="IMAGE",
                    provider_task_id=f"poll-{token}-{index}",
                    prompt=f"poll-concurrency-{token}-{index}",
                    status="PROCESSING",
                    created_at=poll_base_time + timedelta(seconds=index),
                )
                db.session.add(poll_task_row)
                poll_tasks.append(poll_task_row)
            db.session.commit()
            created_poll_ids.extend(task.id for task in poll_tasks)

            def fake_poll(task):
                with poll_lock:
                    poll_started.append(time.perf_counter())
                    poll_threads.append(threading.get_ident())
                    if len(poll_started) == 3:
                        poll_ready.set()
                if not poll_ready.wait(timeout=1):
                    raise AssertionError(
                        "poll workers did not reach the concurrency barrier"
                    )
                time.sleep(0.1)
                return task

            previous_batch_size = app.config.get("STUDIO_POLL_BATCH_SIZE")
            previous_max_workers = app.config.get("STUDIO_POLL_MAX_WORKERS")
            app.config["STUDIO_POLL_BATCH_SIZE"] = 3
            app.config["STUDIO_POLL_MAX_WORKERS"] = 3
            started_at = time.perf_counter()
            with patch.object(
                generation_service,
                "poll_task",
                side_effect=fake_poll,
            ):
                assert generation_service.poll_processing_tasks() == 3
            elapsed = time.perf_counter() - started_at
            if previous_batch_size is None:
                app.config.pop("STUDIO_POLL_BATCH_SIZE", None)
            else:
                app.config["STUDIO_POLL_BATCH_SIZE"] = previous_batch_size
            if previous_max_workers is None:
                app.config.pop("STUDIO_POLL_MAX_WORKERS", None)
            else:
                app.config["STUDIO_POLL_MAX_WORKERS"] = previous_max_workers
            assert len(poll_started) == 3
            assert len(set(poll_threads)) >= 2
            # The barrier above proves the independent workers overlap. Keep
            # the timing as diagnostic data without making the test depend on
            # database connection warm-up speed.
            assert elapsed < 2

            print("execution optimization smoke test passed")
        finally:
            db.session.rollback()
            for task_id in created_poll_ids:
                task = StudioGenerationTask.query.get(task_id)
                if task:
                    db.session.delete(task)
            for task_id in created_amazon_ids:
                task = AmazonAiTask.query.get(task_id)
                if task:
                    db.session.delete(task)
            for task_id in created_studio_ids:
                task = StudioGenerationTask.query.get(task_id)
                if task:
                    db.session.delete(task)
            for task in StudioGenerationTask.query.filter_by(
                prompt=generation_prompt,
            ).all():
                if task.id not in created_studio_ids:
                    db.session.delete(task)
            for asset in StudioAsset.query.filter(
                StudioAsset.storage_path.like("/smoke/optimization/%"),
            ).all():
                db.session.delete(asset)
            db.session.commit()
            for model_id in created_model_ids:
                model = StudioModel.query.get(model_id)
                if model:
                    db.session.delete(model)
            db.session.commit()
            for provider_id in created_provider_ids:
                provider = StudioProvider.query.get(provider_id)
                if provider:
                    db.session.delete(provider)
            db.session.commit()


if __name__ == "__main__":
    main()
