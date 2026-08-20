from applications import create_app
from applications.common.storage import FileService, StoredFile
from applications.extensions import db
from applications.models import (
    StudioAsset,
    StudioGenerationTask,
    StudioProduct,
    StudioProvider,
)
from applications.studio import generation_service
from applications.studio.generation_service import create_generation, poll_task
from applications.studio.request_builder import build_request_body
from unittest.mock import patch


class FakeProviderClient:
    def __init__(self, provider):
        self.provider = provider

    def submit_generation(self, model, body):
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


def main():
    app = create_app()
    with app.app_context():
        provider = StudioProvider.query.filter_by(name="ToAPIs").first()
        image_model = next(model for model in provider.models if model.media_type == "IMAGE")
        video_model = next(model for model in provider.models if model.media_type == "VIDEO")
        provider_id = provider.id
        image_model_id = image_model.id
        video_model_id = video_model.id
        original_api_key = provider.api_key
        provider.api_key = "smoke-key"
        task_ids = []
        created_product = False

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
        assert image_body["image_urls"] == ["https://cdn.example/product.png"]
        assert image_body["quality"] == "high"

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

        product = StudioProduct.query.filter_by(code="SMOKE-001").first()
        if not product:
            product = StudioProduct(
                code="SMOKE-001",
                name="Smoke Product",
                product_profile="Stable product profile",
                product_memory="Stable product memory",
                asset_urls='["https://cdn.example/product.png"]',
                enabled=1,
            )
            db.session.add(product)
            db.session.commit()
            created_product = True
        product_id = product.id

        original_client = generation_service.ProviderClient
        generation_service.ProviderClient = FakeProviderClient
        try:
            with patch.object(
                FileService,
                "upload_from_url",
                classmethod(fake_upload_from_url),
            ):
                image_task = create_generation(
                    user_id=1,
                    media_type="IMAGE",
                    model_id=image_model_id,
                    product_id=product_id,
                    prompt="生成一张广告图",
                    options={"count": 1, "aspect_ratio": "1:1", "resolution": "1k"},
                )
                task_ids.append(image_task.id)
                assert len(image_task.task_code) == 7
                assert image_task.status == "SUBMITTED"
                poll_task(image_task)
                assert image_task.status == "SUCCEEDED"
                assert image_task.output_url.endswith(".png")

                video_task = create_generation(
                    user_id=1,
                    media_type="VIDEO",
                    model_id=video_model_id,
                    product_id=product_id,
                    prompt="生成一个产品视频",
                    options={"duration": 5, "aspect_ratio": "16:9", "resolution": "720p"},
                )
                task_ids.append(video_task.id)
                assert len(video_task.task_code) == 7
                poll_task(video_task)
                assert video_task.status == "SUCCEEDED"
                assert video_task.output_url.endswith(".mp4")
        finally:
            generation_service.ProviderClient = original_client
            # Keep the development database free of generated smoke-test data.
            if task_ids:
                StudioAsset.query.filter(
                    StudioAsset.generation_task_id.in_(task_ids)
                ).delete(synchronize_session=False)
                StudioGenerationTask.query.filter(
                    StudioGenerationTask.id.in_(task_ids)
                ).delete(synchronize_session=False)
            if created_product:
                product = StudioProduct.query.filter_by(code="SMOKE-001").first()
                if product:
                    db.session.delete(product)
            provider = StudioProvider.query.get(provider_id)
            if provider:
                # Do not persist the test token into the developer's configured
                # provider. create_generation() commits task state internally.
                provider.api_key = original_api_key
            db.session.commit()

    print("studio domain smoke test passed")


if __name__ == "__main__":
    main()
