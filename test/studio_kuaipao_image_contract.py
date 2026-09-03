"""Unit checks for the Kuaipao GPT Image 2 multipart contract."""

from types import SimpleNamespace

from applications.studio.provider_client import KuaipaoClient
from applications.studio.request_builder import build_request_body


def main():
    provider = SimpleNamespace(
        name="快跑AI",
        base_url="https://image.kuaipao.pro",
        api_key="test-kuaipao-key",
        generation_path="/v1/images/edits",
        result_path="",
        balance_path="",
        token_balance_path="",
        auth_header="Authorization",
        auth_prefix="Bearer",
        timeout=120,
    )
    model = SimpleNamespace(
        model_code="gpt-image2",
        media_type="IMAGE",
        generation_path="/v1/images/edits",
        provider=provider,
    )
    body = build_request_body(
        model,
        {
            "prompt": "保持产品颜色、结构和两个钥匙扣一致",
            "aspect_ratio": "16:9",
            "resolution": "2k",
            "reference_images": [
                "https://files.example/front.png",
                "https://files.example/back.png",
            ],
        },
    )
    assert body["model"] == "gpt-image-2-2k"
    assert body["size"] == "3840x2160"
    assert "resolution" not in body
    assert body["reference_images"] == [
        "https://files.example/front.png",
        "https://files.example/back.png",
    ]

    client = KuaipaoClient(provider)
    downloaded = {
        "https://files.example/front.png": (
            b"front",
            "front.png",
            "image/png",
        ),
        "https://files.example/back.png": (
            b"back",
            "back.png",
            "image/png",
        ),
    }
    captured = {}
    client._download_reference_image = (
        lambda url, index: downloaded[url]
    )

    def fake_multipart(method, path, data=None, files=None):
        captured["method"] = method
        captured["path"] = path
        captured["data"] = data
        captured["files"] = files
        return {"data": [{"b64_json": "ZmFrZQ=="}]}

    client._multipart_request = fake_multipart
    result = client.submit_generation(model, body)
    assert result["data"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/images/edits"
    assert captured["data"]["model"] == "gpt-image-2-2k"
    assert captured["data"]["size"] == "3840x2160"
    assert captured["data"]["prompt"] == body["prompt"]
    assert len(captured["files"]) == 2
    assert [item[0] for item in captured["files"]] == ["image", "image"]
    assert [item[1][0] for item in captured["files"]] == [
        "front.png",
        "back.png",
    ]


if __name__ == "__main__":
    main()
