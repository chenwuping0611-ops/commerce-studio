"""Regression checks for asset retention and task cleanup invariants."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from applications import create_app
from applications.amazon_ai import retention as amazon_retention
from applications.common.scope import effective_permission_codes
from applications.common.storage import FileService
from applications.extensions import db
from applications.models import (
    AmazonAiTask,
    AmazonAiTaskAsset,
    AmazonAiTaskDependency,
    StudioAsset,
    StudioGenerationTask,
    StudioGenerationTaskAsset,
    StudioProduct,
    StudioProductAsset,
    StudioSkill,
    User,
)
from applications.studio import retention as studio_retention
from applications.view.amazon_ai import routes as amazon_routes


def _set_session(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["permissions"] = sorted(effective_permission_codes(user))


def _studio_task(user, code, now, department_id):
    return StudioGenerationTask(
        task_code=code,
        dept_id=department_id,
        user_id=user.id,
        media_type="IMAGE",
        prompt="retention lifecycle smoke task",
        status="SUCCEEDED",
        progress=100,
        retention_policy=FileService.TEMPORARY,
        expires_at=now + timedelta(days=30),
        storage_cleanup_status="ACTIVE",
        created_at=now,
        completed_at=now,
    )


def _amazon_task(user, code, now, department_id):
    return AmazonAiTask(
        task_code=code,
        dept_id=department_id,
        user_id=user.id,
        task_type="COMPETITOR_ANALYZE",
        title="retention lifecycle smoke",
        status="SUCCEEDED",
        progress=100,
        retention_policy=FileService.TEMPORARY,
        expires_at=now + timedelta(days=30),
        storage_cleanup_status="ACTIVE",
        created_at=now,
        finished_at=now,
        file_refs_json=json.dumps(
            {"inputs": [], "results": [], "legacy_urls": []},
            ensure_ascii=False,
        ),
    )


def _asset(user, filename, purpose, retention_policy, now):
    return StudioAsset(
        dept_id=user.dept_id,
        asset_type="FILE",
        purpose=purpose,
        retention_policy=retention_policy,
        storage_path=f"/smoke/retention/{uuid4().hex}/{filename}",
        public_url=f"https://files.example/retention/{filename}",
        original_filename=filename,
        content_type="text/plain",
        file_size=12,
        checksum=uuid4().hex,
        created_by=user.id,
        status="ACTIVE",
        created_at=now,
        expires_at=(
            None
            if retention_policy == FileService.PERMANENT
            else now + timedelta(days=30)
        ),
    )


def main():
    app = create_app()
    token = uuid4().hex[:8]
    studio_task_ids = []
    amazon_task_ids = []
    asset_ids = []
    product_ids = []
    skill_ids = []
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        assert admin is not None
        client = app.test_client()
        _set_session(client, admin)
        now = datetime.now()
        studio_code = lambda suffix: f"{token[:4]}{int(suffix):03d}"

        try:
            department_id = admin.dept_id

            # A permanent file must survive a direct task reference even if
            # Product/Skill backfill has not created a relation yet.
            direct_task = _studio_task(
                admin,
                studio_code(1),
                now,
                department_id,
            )
            direct_asset = _asset(
                admin,
                f"{token}-direct.txt",
                "GENERATION_OUTPUT",
                FileService.PERMANENT,
                now,
            )
            db.session.add_all([direct_task, direct_asset])
            db.session.flush()
            direct_asset.generation_task_id = direct_task.id
            db.session.add(
                StudioGenerationTaskAsset(
                    generation_task_id=direct_task.id,
                    asset_id=direct_asset.id,
                    role="OUTPUT",
                )
            )
            db.session.commit()
            studio_task_ids.append(direct_task.id)
            asset_ids.append(direct_asset.id)

            with patch.object(
                FileService,
                "delete_asset",
                return_value=True,
            ) as delete_asset:
                result = studio_retention.delete_generation_task(
                    direct_task,
                    assets=[direct_asset],
                )
            assert result["deleted"] is True
            assert result["protected_assets"] == 1
            assert delete_asset.call_count == 0
            assert StudioGenerationTask.query.get(direct_task.id) is None
            retained_direct = StudioAsset.query.get(direct_asset.id)
            assert retained_direct is not None
            assert retained_direct.status == "ACTIVE"
            assert retained_direct.generation_task_id is None
            studio_task_ids.remove(direct_task.id)

            # Formal Product and Skill assets are permanent and remain after
            # their generation task is removed.
            product = StudioProduct(
                dept_id=department_id,
                code=f"RET-{token}-PRODUCT",
                name="Retention Product",
                enabled=1,
                created_by=admin.id,
            )
            product_asset = _asset(
                admin,
                f"{token}-product.png",
                "PRODUCT_IMAGE",
                FileService.PERMANENT,
                now,
            )
            skill_asset = _asset(
                admin,
                f"{token}-skill.md",
                "SKILL",
                FileService.PERMANENT,
                now,
            )
            skill = StudioSkill(
                dept_id=department_id,
                name=f"Retention Skill {token}",
                code=f"retention-skill-{token}",
                media_type="BOTH",
                content="retention smoke",
                enabled=1,
                created_by=admin.id,
            )
            db.session.add_all(
                [product, product_asset, skill_asset, skill]
            )
            db.session.flush()
            db.session.add(
                StudioProductAsset(
                    product_id=product.id,
                    storage_asset_id=product_asset.id,
                    name=product_asset.original_filename,
                    asset_type="IMAGE",
                    enabled=1,
                )
            )
            skill.storage_asset_id = skill_asset.id
            product_task = _studio_task(
                admin,
                studio_code(2),
                now,
                department_id,
            )
            skill_task = _studio_task(
                admin,
                studio_code(3),
                now,
                department_id,
            )
            db.session.add_all([product_task, skill_task])
            db.session.flush()
            db.session.add_all(
                [
                    StudioGenerationTaskAsset(
                        generation_task_id=product_task.id,
                        asset_id=product_asset.id,
                        role="REFERENCE_IMAGE",
                    ),
                    StudioGenerationTaskAsset(
                        generation_task_id=skill_task.id,
                        asset_id=skill_asset.id,
                        role="REFERENCE_IMAGE",
                    ),
                ]
            )
            db.session.commit()
            studio_task_ids.extend([product_task.id, skill_task.id])
            asset_ids.extend([product_asset.id, skill_asset.id])
            product_ids.append(product.id)
            skill_ids.append(skill.id)

            with patch.object(
                FileService,
                "delete_asset",
                return_value=True,
            ) as delete_asset:
                product_result = studio_retention.delete_generation_task(
                    product_task,
                    assets=[product_asset],
                )
                skill_result = studio_retention.delete_generation_task(
                    skill_task,
                    assets=[skill_asset],
                )
            assert product_result["deleted"] is True
            assert skill_result["deleted"] is True
            assert delete_asset.call_count == 0
            assert StudioAsset.query.get(product_asset.id) is not None
            assert StudioAsset.query.get(skill_asset.id) is not None
            studio_task_ids.remove(product_task.id)
            studio_task_ids.remove(skill_task.id)

            # A temporary asset shared by two active task relations cannot be
            # deleted when only one task is removed.
            shared_asset = _asset(
                admin,
                f"{token}-shared.txt",
                "GENERATION_OUTPUT",
                FileService.TEMPORARY,
                now,
            )
            shared_a = _studio_task(
                admin,
                studio_code(4),
                now,
                department_id,
            )
            shared_b = _studio_task(
                admin,
                studio_code(5),
                now,
                department_id,
            )
            db.session.add_all([shared_asset, shared_a, shared_b])
            db.session.flush()
            db.session.add_all(
                [
                    StudioGenerationTaskAsset(
                        generation_task_id=shared_a.id,
                        asset_id=shared_asset.id,
                        role="OUTPUT",
                    ),
                    StudioGenerationTaskAsset(
                        generation_task_id=shared_b.id,
                        asset_id=shared_asset.id,
                        role="OUTPUT",
                    ),
                ]
            )
            db.session.commit()
            studio_task_ids.extend([shared_a.id, shared_b.id])
            asset_ids.append(shared_asset.id)
            with patch.object(
                FileService,
                "delete_asset",
                return_value=True,
            ) as delete_asset:
                first_result = studio_retention.delete_generation_task(
                    shared_a,
                    assets=[shared_asset],
                )
                assert first_result["shared_assets"] == 1
                assert delete_asset.call_count == 0
                assert StudioAsset.query.get(shared_asset.id) is not None
                second_result = studio_retention.delete_generation_task(
                    shared_b,
                    assets=[shared_asset],
                )
            assert second_result["deleted"] is True
            assert delete_asset.call_count == 1
            assert StudioAsset.query.get(shared_asset.id) is None
            studio_task_ids.remove(shared_a.id)
            studio_task_ids.remove(shared_b.id)

            # Amazon source-result assets stay alive while a downstream task
            # still references them through the normalized relation table.
            amazon_asset = _asset(
                admin,
                f"{token}-amazon.txt",
                "AMAZON_RESULT",
                FileService.TEMPORARY,
                now,
            )
            upstream = _amazon_task(
                admin,
                f"RET-AMZ-{token}-A",
                now,
                department_id,
            )
            downstream = _amazon_task(
                admin,
                f"RET-AMZ-{token}-B",
                now,
                department_id,
            )
            db.session.add_all([amazon_asset, upstream, downstream])
            db.session.flush()
            upstream.output_asset_id = amazon_asset.id
            upstream.output_url = amazon_asset.public_url
            upstream.output_filename = amazon_asset.original_filename
            upstream.result_refs_json = json.dumps(
                {"response_asset_id": amazon_asset.id},
                ensure_ascii=False,
            )
            db.session.add_all(
                [
                    AmazonAiTaskAsset(
                        task_id=upstream.id,
                        asset_id=amazon_asset.id,
                        role="RESULT",
                    ),
                    AmazonAiTaskAsset(
                        task_id=downstream.id,
                        asset_id=amazon_asset.id,
                        role="SOURCE_RESULT",
                    ),
                    AmazonAiTaskDependency(
                        task_id=downstream.id,
                        source_task_id=upstream.id,
                        relation_type="SOURCE_TASK",
                    ),
                ]
            )
            db.session.commit()
            amazon_task_ids.extend([upstream.id, downstream.id])
            asset_ids.append(amazon_asset.id)
            with patch.object(
                FileService,
                "delete_asset",
                return_value=True,
            ) as delete_asset:
                upstream_result = amazon_retention._cleanup_task(
                    upstream,
                    now,
                    assets=[amazon_asset],
                )
                db.session.commit()
                assert upstream_result["protected"] == 1
                assert delete_asset.call_count == 0
                assert StudioAsset.query.get(amazon_asset.id) is not None
                downstream_result = amazon_retention._cleanup_task(
                    downstream,
                    now,
                    assets=[amazon_asset],
                )
                db.session.commit()
            assert downstream_result["deleted"] is True
            assert delete_asset.call_count == 1
            assert StudioAsset.query.get(amazon_asset.id) is None
            amazon_task_ids.clear()

            # Promotion to permanent removes the asset from temporary
            # orphan cleanup, even when its old expiry date has passed.
            promoted = _asset(
                admin,
                f"{token}-promoted.txt",
                "GENERATION_OUTPUT",
                FileService.TEMPORARY,
                now - timedelta(days=31),
            )
            promoted.expires_at = None
            promoted.retention_policy = FileService.PERMANENT
            db.session.add(promoted)
            db.session.commit()
            asset_ids.append(promoted.id)
            with patch.object(
                FileService,
                "delete_asset",
                return_value=True,
            ) as delete_asset:
                cleanup_result = studio_retention._cleanup_orphan_assets(
                    100,
                    now,
                )
            assert cleanup_result["deleted"] == 0
            assert delete_asset.call_count == 0
            assert StudioAsset.query.get(promoted.id) is not None

            # An obsolete file from a permanent Product/Skill replacement is
            # a temporary cleanup record, so it remains retryable without
            # making the current permanent asset eligible for deletion.
            cleanup_source = _asset(
                admin,
                f"{token}-cleanup-source.txt",
                "PRODUCT",
                FileService.PERMANENT,
                now,
            )
            db.session.add(cleanup_source)
            db.session.commit()
            cleanup_path = f"/smoke/retention/{token}/obsolete.txt"
            with patch.object(
                FileService,
                "delete_storage",
                side_effect=RuntimeError("temporary fileserver failure"),
            ):
                assert FileService._record_failed_cleanup(
                    source_asset=cleanup_source,
                    storage_path=cleanup_path,
                    public_url=f"https://files.example{cleanup_path}",
                    original_filename="obsolete.txt",
                    content_type="text/plain",
                    checksum="obsolete-checksum",
                )
            cleanup_record = StudioAsset.query.filter_by(
                storage_path=cleanup_path,
                status="DELETE_FAILED",
            ).first()
            assert cleanup_record is not None
            assert cleanup_record.purpose == "CLEANUP_PENDING"
            assert cleanup_record.retention_policy == FileService.TEMPORARY
            asset_ids.extend([cleanup_source.id, cleanup_record.id])
            with patch.object(
                FileService,
                "delete_asset",
                return_value=True,
            ) as delete_asset:
                cleanup_result = studio_retention._cleanup_orphan_assets(
                    100,
                    now,
                )
            assert cleanup_result["deleted"] >= 1
            assert delete_asset.call_count >= 1
            assert StudioAsset.query.get(cleanup_record.id) is None

            # The manual Amazon delete endpoint path has the same protection
            # as scheduled cleanup.
            route_asset = _asset(
                admin,
                f"{token}-route.txt",
                "AMAZON_RESULT",
                FileService.PERMANENT,
                now,
            )
            route_task = _amazon_task(
                admin,
                f"RET-AMZ-{token}-C",
                now,
                department_id,
            )
            db.session.add_all([route_asset, route_task])
            db.session.flush()
            route_task.output_asset_id = route_asset.id
            db.session.add(
                AmazonAiTaskAsset(
                    task_id=route_task.id,
                    asset_id=route_asset.id,
                    role="RESULT",
                )
            )
            db.session.commit()
            amazon_task_ids.append(route_task.id)
            asset_ids.append(route_asset.id)
            with patch.object(
                amazon_routes.FileService,
                "delete_asset",
                return_value=True,
            ) as delete_asset:
                route_result = amazon_routes._delete_amazon_task(route_task)
            assert route_result["deleted"] is True
            assert delete_asset.call_count == 0
            assert StudioAsset.query.get(route_asset.id) is not None
            amazon_task_ids.remove(route_task.id)

            print("retention lifecycle smoke test passed")
        finally:
            db.session.rollback()
            if studio_task_ids:
                StudioGenerationTaskAsset.query.filter(
                    StudioGenerationTaskAsset.generation_task_id.in_(
                        studio_task_ids
                    )
                ).delete(synchronize_session=False)
            if amazon_task_ids:
                AmazonAiTaskAsset.query.filter(
                    AmazonAiTaskAsset.task_id.in_(amazon_task_ids)
                ).delete(synchronize_session=False)
                AmazonAiTaskDependency.query.filter(
                    (
                        AmazonAiTaskDependency.task_id.in_(amazon_task_ids)
                    )
                    | (
                        AmazonAiTaskDependency.source_task_id.in_(
                            amazon_task_ids
                        )
                    )
                ).delete(synchronize_session=False)
            if studio_task_ids:
                StudioGenerationTask.query.filter(
                    StudioGenerationTask.id.in_(studio_task_ids)
                ).delete(synchronize_session=False)
            if amazon_task_ids:
                AmazonAiTask.query.filter(
                    AmazonAiTask.id.in_(amazon_task_ids)
                ).delete(synchronize_session=False)
            if product_ids:
                StudioProductAsset.query.filter(
                    StudioProductAsset.product_id.in_(product_ids)
                ).delete(synchronize_session=False)
                StudioProduct.query.filter(
                    StudioProduct.id.in_(product_ids)
                ).delete(synchronize_session=False)
            if skill_ids:
                StudioSkill.query.filter(
                    StudioSkill.id.in_(skill_ids)
                ).delete(synchronize_session=False)
            if asset_ids:
                StudioAsset.query.filter(
                    StudioAsset.id.in_(list(dict.fromkeys(asset_ids)))
                ).delete(synchronize_session=False)
            db.session.commit()


if __name__ == "__main__":
    main()
