import base64

from applications import create_app
from applications.common.storage import FileService, StoredFile
from applications.extensions import db
from applications.models import (
    StudioAsset,
    StudioGenerationTask,
    StudioGenerationTaskAsset,
    StudioProduct,
    StudioProvider,
    StudioSkill,
    User,
)
from applications.studio import generation_service
from applications.studio.generation_service import create_generation, poll_task
from applications.studio.product_prompt import (
    DETAIL_IMAGE_OUTPUT_CONTRACT,
    compose_prompt,
    product_identity_planner_contract,
)
from applications.studio.request_builder import (
    build_request_body,
    image_size_for_aspect_ratio,
)
from applications.amazon_ai.skill_catalog import DETAIL_IMAGE_SKILL_CODE
from unittest.mock import patch
import string
import secrets


class FakeProviderClient:
    submitted_bodies = []

    def __init__(self, provider):
        self.provider = provider

    def submit_generation(self, model, body):
        self.submitted_bodies.append((model.model_code, dict(body)))
        if model.model_code == "gpt-image2":
            return {
                "id": "mock-image-sync",
                "status": "completed",
                "data": [
                    {
                        "b64_json": base64.b64encode(
                            b"fake generated image"
                        ).decode("ascii"),
                        "mime_type": "image/png",
                    }
                ],
            }
        return {"id": f"mock-{model.media_type.lower()}-task", "status": "queued"}

    def fetch_generation_result(self, model, task_id, media_type):
        extension = "mp4" if media_type == "VIDEO" else "png"
        return {
            "status": "completed",
            "result": {"data": [{"url": f"https://cdn.example/{task_id}.{extension}"}]},
        }


def fake_upload_from_url(
    cls,
    url,
    filename=None,
    asset_type=None,
    purpose="GENERATION_OUTPUT",
    retention_policy=FileService.TTL_7D,
    created_by=None,
    dept_id=None,
    record=True,
):
    return StoredFile(
        storage_path="/group1/images/generated/" + (filename or "output.bin"),
        public_url=(
            "https://mock.gofastdfs.local/gofastdfs/group1/images/generated/"
            + (filename or "output.bin")
        ),
        original_filename=filename or "output.bin",
        content_type="video/mp4" if asset_type == "VIDEO" else "image/png",
        file_size=3,
    )


def fake_upload_local_file(
    cls,
    path,
    filename=None,
    content_type=None,
    asset_type=None,
    purpose="FILE",
    retention_policy=FileService.PERMANENT,
    created_by=None,
    category=None,
    dept_id=None,
    record=True,
):
    with open(path, "rb") as local_file:
        data = local_file.read()
    return StoredFile(
        storage_path="/group1/images/generated/" + (filename or "output.bin"),
        public_url=(
            "https://mock.gofastdfs.local/gofastdfs/group1/images/generated/"
            + (filename or "output.bin")
        ),
        original_filename=filename or "output.bin",
        content_type=content_type or "image/png",
        file_size=len(data or b""),
    )


def main():
    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        assert admin is not None and admin.dept_id is not None
        provider = (
            StudioProvider.query.filter_by(
                name="ToAPIs",
                dept_id=admin.dept_id,
            )
            .order_by(StudioProvider.id.asc())
            .first()
        )
        assert provider is not None
        image_model = next(
            model
            for model in provider.models
            if model.media_type == "IMAGE"
            and model.model_code == "gpt-image-2"
        )
        video_model = next(
            model
            for model in provider.models
            if model.media_type == "VIDEO" and model.enabled
        )
        provider_id = provider.id
        image_model_id = image_model.id
        video_model_id = video_model.id
        original_api_key = provider.api_key
        provider.api_key = "smoke-key"
        kuaipao_provider = (
            StudioProvider.query.filter_by(
                name="快跑AI",
                dept_id=admin.dept_id,
            )
            .order_by(StudioProvider.id.asc())
            .first()
        )
        assert kuaipao_provider is not None
        kuaipao_image_model = next(
            model
            for model in kuaipao_provider.models
            if model.media_type == "IMAGE"
            and model.model_code == "gpt-image2"
            and model.enabled
        )
        original_kuaipao_api_key = kuaipao_provider.api_key
        kuaipao_provider.api_key = "smoke-kuaipao-key"
        task_ids = []
        created_product = False
        created_skill = False

        video_models = {
            model.model_code: model
            for model in provider.models
            if model.media_type == "VIDEO"
            and model.enabled
        }
        assert "seedance-2" in video_models

        normal_high_resolution = build_request_body(
            video_models["seedance-2"],
            {
                "prompt": "标准版高分辨率视频",
                "duration": "15",
                "aspect_ratio": "16:9",
                "resolution": "4k",
                "reference_images_with_roles": [
                    {
                        "url": "https://cdn.example/product.png",
                        "role": "first_frame",
                    }
                ],
            },
            {
                "first_frame": "https://cdn.example/should-be-removed.png",
                "image_urls": ["https://cdn.example/should-also-be-removed.png"],
            },
        )
        assert normal_high_resolution["model"] == "seedance-2"
        assert normal_high_resolution["resolution"] == "4k"
        assert normal_high_resolution["image_with_roles"] == [
            {
                "url": "https://cdn.example/product.png",
                "role": "reference_image",
            }
        ]
        assert "first_frame" not in normal_high_resolution
        assert "image_urls" not in normal_high_resolution

        image_body = build_request_body(
            image_model,
            {
                "prompt": "产品广告",
                "count": "1",
                "aspect_ratio": "1:1",
                "resolution": "1k",
                "reference_images": ["https://cdn.example/product.png"],
            },
            {"quality": "high"},
        )
        assert image_body["model"] == "gpt-image-2"
        assert image_body["prompt"] == "产品广告"
        assert image_body["n"] == 1
        assert image_body["reference_images"] == [
            "https://cdn.example/product.png"
        ]
        assert image_body["quality"] == "high"

        kuaipao_provider = (
            StudioProvider.query.filter_by(
                name="快跑AI",
                dept_id=admin.dept_id,
            )
            .order_by(StudioProvider.id.asc())
            .first()
        )
        assert kuaipao_provider is not None
        kuaipao_image_model = next(
            model
            for model in kuaipao_provider.models
            if model.model_code == "gpt-image2"
            and model.media_type == "IMAGE"
            and model.enabled
        )
        assert image_size_for_aspect_ratio("1:1") == "4096x4096"
        assert image_size_for_aspect_ratio("2.44:1") == "4096x1680"
        assert image_size_for_aspect_ratio("16:9") == "3840x2160"
        assert image_size_for_aspect_ratio("9:16") == "2160x3840"
        try:
            image_size_for_aspect_ratio("7:5")
        except ValueError as exc:
            assert "预设比例" in str(exc)
        else:
            raise AssertionError("未登记的图片比例不应被接受")
        kuaipao_image_body = build_request_body(
            kuaipao_image_model,
            {
                "prompt": "快跑多图编辑",
                "count": "2",
                "aspect_ratio": "2.44:1",
                "resolution": "4k",
                "reference_images": [
                    "https://cdn.example/one.png",
                    "https://cdn.example/two.png",
                ],
            },
        )
        assert kuaipao_image_body["model"] == "gpt-image-2-4k"
        assert kuaipao_image_body["n"] == 2
        assert kuaipao_image_body["size"] == "4096x1680"
        assert "resolution" not in kuaipao_image_body
        assert kuaipao_image_body["reference_images"] == [
            "https://cdn.example/one.png",
            "https://cdn.example/two.png",
        ]

        video_body = build_request_body(
            video_model,
            {
                "prompt": "产品视频",
                "duration": "5",
                "aspect_ratio": "16:9",
                "resolution": "720p",
                "reference_images_with_roles": [
                    {"url": "https://cdn.example/product.png", "role": "reference_image"}
                ],
                "generate_audio": True,
            },
        )
        assert video_body["model"] == "seedance-2"
        assert video_body["duration"] == 5
        assert video_body["image_with_roles"][0]["role"] == "reference_image"
        assert video_body["generate_audio"] is True

        default_video_body = build_request_body(
            video_model,
            {
                "prompt": "默认关闭音频的视频",
                "duration": "5",
                "aspect_ratio": "16:9",
                "resolution": "720p",
            },
        )
        assert default_video_body["generate_audio"] is False

        test_product_code = "SMOKE-" + secrets.token_hex(4).upper()
        product = StudioProduct(
            dept_id=admin.dept_id,
            code=test_product_code,
            name="Smoke Product",
            description="固定产品描述",
            product_profile="Stable product profile",
            product_memory="Stable product memory",
            asset_urls='["https://cdn.example/product.png"]',
            enabled=1,
        )
        db.session.add(product)
        db.session.commit()
        created_product = True
        product_id = product.id

        skill_code = "smoke-skill-" + secrets.token_hex(4)
        skill = StudioSkill(
            dept_id=admin.dept_id,
            name="Smoke Skill",
            code=skill_code,
            media_type="BOTH",
            prompt_template="保持商业摄影质感",
            content="保持商业摄影质感",
            enabled=1,
        )
        db.session.add(skill)
        db.session.commit()
        created_skill = True
        skill_id = skill.id

        image_prompt = compose_prompt(
            product,
            "下雨天拍摄产品广告",
            skill_prompt="晴天棚拍风格",
            media_type="IMAGE",
        )
        video_prompt = compose_prompt(
            product,
            "下雨天拍摄产品视频",
            skill_prompt="晴天棚拍风格",
            media_type="VIDEO",
        )
        for planned_prompt, creative in (
            (image_prompt, "下雨天拍摄产品广告"),
            (video_prompt, "下雨天拍摄产品视频"),
        ):
            assert planned_prompt.index("本次创意要求") < planned_prompt.index("产品资料")
            assert planned_prompt.index("产品资料") < planned_prompt.index("创作 Skill 指令")
            assert "Product Profile" in planned_prompt
            assert "产品记忆" in planned_prompt

        original_client = generation_service.ProviderClient
        generation_service.ProviderClient = FakeProviderClient
        FakeProviderClient.submitted_bodies = []
        try:
            with patch.object(
                FileService,
                "upload_from_url",
                classmethod(fake_upload_from_url),
            ), patch.object(
                FileService,
                "upload_local_file",
                classmethod(fake_upload_local_file),
            ):
                image_task = create_generation(
                    user_id=admin.id,
                    media_type="IMAGE",
                    model_id=image_model_id,
                    product_id=product_id,
                    prompt="生成一张广告图",
                    options={
                        "count": 1,
                        "aspect_ratio": "1:1",
                        "resolution": "1k",
                        "skill_id": skill_id,
                    },
                )
                task_ids.append(image_task.id)
                assert len(image_task.task_code) == 7
                assert all(
                    char in string.ascii_letters + string.digits
                    for char in image_task.task_code
                )
                assert any(char.isupper() for char in image_task.task_code)
                assert any(char.islower() for char in image_task.task_code)
                assert any(char.isdigit() for char in image_task.task_code)
                assert image_task.skill_id == skill_id
                assert image_task.skill_name == "Smoke Skill"
                assert image_task.skill_prompt == "保持商业摄影质感"
                assert image_task.status == "SUBMITTED"
                poll_task(image_task)
                assert image_task.status == "SUCCEEDED"
                assert image_task.output_url.endswith(".png")

                kuaipao_image_task = create_generation(
                    user_id=admin.id,
                    media_type="IMAGE",
                    model_id=kuaipao_image_model.id,
                    product_id=product_id,
                    prompt="快跑 Base64 同步图片",
                    options={
                        "count": 1,
                        "aspect_ratio": "1:1",
                        "resolution": "4k",
                        "skill_id": skill_id,
                    },
                )
                task_ids.append(kuaipao_image_task.id)
                assert kuaipao_image_task.status == "SUCCEEDED"
                assert kuaipao_image_task.provider_task_id is None
                assert kuaipao_image_task.output_url.endswith(".png")
                assert len(kuaipao_image_task.asset_links) == 1
                assert kuaipao_image_task.asset_links[0].role == "OUTPUT"
                assert "fake generated image" not in (
                    kuaipao_image_task.result_payload or ""
                )
                assert "BINARY_PAYLOAD_OMITTED" in (
                    kuaipao_image_task.result_payload or ""
                )

                detail_image_skill = StudioSkill.query.filter_by(
                    code=DETAIL_IMAGE_SKILL_CODE,
                    enabled=1,
                ).first()
                if detail_image_skill:
                    detail_image_task = create_generation(
                        user_id=admin.id,
                        media_type="IMAGE",
                        model_id=kuaipao_image_model.id,
                        product_id=product_id,
                        prompt="请生成一张完整电商详情图",
                        options={
                            "count": 1,
                            "aspect_ratio": "2.44:1",
                            "resolution": "2k",
                            "prepared_prompt": "模型规划后的图片创作提示词",
                            "skill_id": detail_image_skill.id,
                        },
                    )
                    task_ids.append(detail_image_task.id)
                    detail_prompt = FakeProviderClient.submitted_bodies[-1][1][
                        "prompt"
                    ]
                    assert DETAIL_IMAGE_OUTPUT_CONTRACT in detail_prompt
                    assert "左侧图和右侧图" in detail_prompt
                    assert "白底单品抠图" in detail_prompt
                    assert "电池标签" in detail_prompt
                    assert "长筒" in detail_prompt
                    assert "真实握把" in detail_prompt
                    assert "产品名称覆盖" in detail_prompt
                    assert len(detail_prompt.encode("utf-8")) <= 5000

                assert "电池标签" in product_identity_planner_contract()
                assert "真实握把" in product_identity_planner_contract()
                assert "长筒" in product_identity_planner_contract()

                snapshot_skill_task = create_generation(
                    user_id=admin.id,
                    media_type="IMAGE",
                    model_id=kuaipao_image_model.id,
                    product_id=product_id,
                    prompt="批量详情图版本正文",
                    options={
                        "count": 1,
                        "aspect_ratio": "2.44:1",
                        "resolution": "2k",
                        "skill_name": "批量详情图 Skill",
                        "skill_prompt": (
                            "必须保持产品真实颜色、结构和两个钥匙扣，"
                            "不得遗漏、变形或增加配件。"
                        ),
                    },
                )
                task_ids.append(snapshot_skill_task.id)
                submitted_prompt = FakeProviderClient.submitted_bodies[-1][1][
                    "prompt"
                ]
                assert "批量详情图版本正文" in submitted_prompt
                assert "两个钥匙扣" in submitted_prompt
                submitted_body = FakeProviderClient.submitted_bodies[-1][1]
                assert submitted_body["model"] == "gpt-image-2-2k"
                assert submitted_body["size"] == "4096x1680"
                assert submitted_body["reference_images"] == [
                    "https://cdn.example/product.png"
                ]

                video_task = create_generation(
                    user_id=admin.id,
                    media_type="VIDEO",
                    model_id=video_model_id,
                    product_id=product_id,
                    prompt="生成一个产品视频",
                    options={"duration": 5, "aspect_ratio": "16:9", "resolution": "720p"},
                )
                task_ids.append(video_task.id)
                assert len(video_task.task_code) == 7
                assert all(
                    char in string.ascii_letters + string.digits
                    for char in video_task.task_code
                )
                poll_task(video_task)
                assert video_task.status == "SUCCEEDED"
                assert video_task.output_url.endswith(".mp4")
        finally:
            generation_service.ProviderClient = original_client
            # Keep the development database free of generated smoke-test data.
            if task_ids:
                StudioGenerationTaskAsset.query.filter(
                    StudioGenerationTaskAsset.generation_task_id.in_(task_ids)
                ).delete(synchronize_session=False)
                StudioAsset.query.filter(
                    StudioAsset.generation_task_id.in_(task_ids)
                ).delete(synchronize_session=False)
                StudioGenerationTask.query.filter(
                    StudioGenerationTask.id.in_(task_ids)
                ).delete(synchronize_session=False)
            if created_product:
                product = StudioProduct.query.filter_by(code=test_product_code).first()
                if product:
                    db.session.delete(product)
            if created_skill:
                skill = StudioSkill.query.filter_by(code=skill_code).first()
                if skill:
                    db.session.delete(skill)
            provider = StudioProvider.query.get(provider_id)
            if provider:
                # Do not persist the test token into the developer's configured
                # provider. create_generation() commits task state internally.
                provider.api_key = original_api_key
            kuaipao_provider = StudioProvider.query.get(kuaipao_provider.id)
            if kuaipao_provider:
                kuaipao_provider.api_key = original_kuaipao_api_key
            db.session.commit()

    print("studio domain smoke test passed")


if __name__ == "__main__":
    main()
