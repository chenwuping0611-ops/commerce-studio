"""Code-owned model catalogs for each API provider.

The database keeps model identity, department scope, and enabled state. The
request contract itself lives here so an administrator cannot accidentally
change a provider's protocol fields from the web UI.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Tuple


KUAIPAO_IMAGE_EDIT_URL = "https://image.kuaipao.pro/v1/images/edits"
KUAIPAO_IMAGE_GENERATION_URL = (
    "https://image.kuaipao.pro/v1/images/generations"
)
KUAIPAO_IMAGE_MODEL_CODE = "gpt-image2"
KUAIPAO_IMAGE_MODEL_CODES = (KUAIPAO_IMAGE_MODEL_CODE,)
KUAIPAO_LEGACY_IMAGE_MODEL_CODES = (
    "gpt-image-2-1k",
    "gpt-image-2-2k",
    "gpt-image-2-4k",
)
KUAIPAO_IMAGE_API_MODEL_CODES = {
    "1k": "gpt-image-2-1k",
    "2k": "gpt-image-2-2k",
    "4k": "gpt-image-2-4k",
}
KUAIPAO_IMAGE_ASPECT_RATIOS = (
    "1:1",
    "2.44:1",
    "3:2",
    "2:3",
    "4:3",
    "3:4",
    "5:4",
    "4:5",
    "16:9",
    "9:16",
    "2:1",
    "1:2",
    "21:9",
    "9:21",
)


def kuaipao_image_api_model_code(resolution):
    """Map the UI quality choice to the real Kuaipao image model code."""

    value = str(resolution or "1k").strip().lower()
    try:
        return KUAIPAO_IMAGE_API_MODEL_CODES[value]
    except KeyError as exc:
        raise ValueError("图片分辨率只能选择 1K、2K 或 4K") from exc


def _parameter(
    field_name,
    label,
    *,
    runtime_key="",
    value="",
    value_type="string",
    options=None,
    minimum=None,
    maximum=None,
    step=None,
    hint="",
):
    item = {
        "field": field_name,
        "label": label,
        "runtime_key": runtime_key,
        "value": value,
        "value_type": value_type,
        "enabled": True,
        "hint": hint,
    }
    if options is not None:
        item["options"] = list(options)
    if minimum is not None:
        item["min"] = minimum
    if maximum is not None:
        item["max"] = maximum
    if step is not None:
        item["step"] = step
    return item


def _image_parameters(
    model_code,
    *,
    size_options,
    resolution_options,
    resolution_value,
    reference_field="reference_images",
    reference_label="参考图片",
    reference_hint="URL 数组；没有参考图时不发送",
):
    return [
        _parameter(
            "model",
            "模型标识",
            value=model_code,
            hint="由供应商模型目录固定",
        ),
        _parameter(
            "prompt",
            "提示词",
            runtime_key="prompt",
            hint="由创作页固定参数和产品信息整理后生成",
        ),
        _parameter(
            "n",
            "生成数量",
            runtime_key="count",
            value="1",
            value_type="number",
            minimum=1,
            maximum=8,
            step=1,
            hint="沿用图片创作页的生成数量",
        ),
        _parameter(
            "size",
            "画面比例",
            runtime_key="aspect_ratio",
            value=size_options[0],
            options=size_options,
            hint="由图片创作页的画面比例选择",
        ),
        _parameter(
            "resolution",
            "分辨率",
            runtime_key="resolution",
            value=resolution_value,
            options=resolution_options,
            hint="由图片创作页的分辨率选择",
        ),
        _parameter(
            reference_field,
            reference_label,
            runtime_key="reference_images",
            value=[],
            value_type="json",
            hint=reference_hint,
        ),
    ]


def _toapis_gpt_image_parameters():
    parameters = _image_parameters(
        "gpt-image-2",
        size_options=(
            "1:1",
            "3:2",
            "2:3",
            "4:3",
            "3:4",
            "5:4",
            "4:5",
            "16:9",
            "9:16",
            "2:1",
            "1:2",
            "21:9",
            "9:21",
        ),
        resolution_options=("1k", "2k", "4k"),
        resolution_value="1k",
        reference_field="reference_images",
        reference_hint=(
            "URL 数组；ToAPIs GPT Image 2 的正式字段。"
            "兼容旧字段 image_urls，但本目录统一使用 reference_images"
        ),
    )
    parameters.insert(
        6,
        _parameter(
            "response_format",
            "返回格式",
            value="url",
            options=("url",),
            hint="ToAPIs 推荐返回公网 URL",
        ),
    )
    return parameters


def _toapis_nano_banana_parameters():
    parameters = _image_parameters(
        "gemini-3.1-flash-image-preview",
        size_options=(
            "1:1",
            "3:2",
            "2:3",
            "4:3",
            "3:4",
            "16:9",
            "9:16",
            "5:4",
            "4:5",
            "21:9",
            "1:4",
            "4:1",
            "1:8",
            "8:1",
        ),
        resolution_options=("0.5K", "1K", "2K", "4K"),
        resolution_value="2K",
        reference_field="image_urls",
        reference_hint=(
            "公开图片 URL 数组；单张最大 10MB，最多 14 张，"
            "支持 jpg/jpeg/png/webp"
        ),
    )
    parameters[4]["field"] = "metadata.resolution"
    parameters[4]["hint"] = "Nano Banana 2 的分辨率位于 metadata.resolution"
    parameters.extend(
        [
            _parameter(
                "metadata.google_search",
                "联网搜索",
                value=False,
                value_type="boolean",
                hint="高级协议参数；当前创作页不单独暴露",
            ),
            _parameter(
                "metadata.google_image_search",
                "图片搜索",
                value=False,
                value_type="boolean",
                hint="必须配合 metadata.google_search=true",
            ),
        ]
    )
    return parameters


def _kuaipao_gpt_image_parameters(model_code):
    parameters = _image_parameters(
        model_code,
        size_options=tuple(KUAIPAO_IMAGE_ASPECT_RATIOS),
        resolution_options=(
            {"value": "1k", "label": "1K"},
            {"value": "2k", "label": "2K"},
            {"value": "4k", "label": "4K"},
        ),
        resolution_value="1k",
        reference_field="reference_images",
        reference_hint=(
            "图片 URL 数组；有参考图时由服务端下载后以多个 image "
            "multipart 字段发送到快跑 AI 图片编辑接口，最多 14 张"
        ),
    )
    parameters[3]["hint"] = (
        "只支持预设画面比例；服务端按 4K 画布转换为宽x高"
    )
    parameters[4]["hint"] = (
        "1K、2K、4K 只决定实际调用的图片模型质量，画布始终按 4K 比例计算"
    )
    return parameters


def _seedance_parameters(model_code, resolution_options):
    return [
        _parameter(
            "model",
            "模型标识",
            value=model_code,
            hint="由供应商模型目录固定",
        ),
        _parameter(
            "prompt",
            "提示词",
            runtime_key="prompt",
            hint="由视频创作页固定参数和产品信息整理后生成",
        ),
        _parameter(
            "client_business_id",
            "业务请求标识",
            hint="可选协议字段；不填写时不发送",
        ),
        _parameter(
            "duration",
            "视频时长",
            runtime_key="duration",
            value="5",
            value_type="number",
            minimum=4,
            maximum=15,
            step=1,
            hint="4-15 秒；标准版和 Fast 版支持自动时长 0/-1",
        ),
        _parameter(
            "aspect_ratio",
            "画面比例",
            runtime_key="aspect_ratio",
            value="16:9",
            options=("21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"),
            hint="由视频创作页的画面比例选择",
        ),
        _parameter(
            "image_with_roles",
            "带角色参考图",
            runtime_key="reference_images_with_roles",
            value=[],
            value_type="json",
            hint="首帧、尾帧和参考图模式互斥；当前创作页使用 reference_image",
        ),
        _parameter(
            "video_with_roles",
            "带角色参考视频",
            runtime_key="reference_videos_with_roles",
            value=[],
            value_type="json",
            hint="Seedance Mini 最多 3 条参考视频",
        ),
        _parameter(
            "audio_with_roles",
            "带角色参考音频",
            value=[],
            value_type="json",
            hint="必须和图片或视频参考一起使用",
        ),
        _parameter(
            "image_urls",
            "兼容参考图片",
            value=[],
            value_type="json",
            hint="旧兼容字段；当前统一使用 image_with_roles",
        ),
        _parameter(
            "resolution",
            "分辨率",
            runtime_key="resolution",
            value="720p",
            options=resolution_options,
            hint="当前版本支持：" + "、".join(resolution_options),
        ),
        _parameter(
            "generate_audio",
            "生成音频",
            runtime_key="generate_audio",
            value=False,
            value_type="boolean",
            hint="由视频创作页的固定开关选择",
        ),
        _parameter(
            "return_last_frame",
            "返回尾帧",
            value=False,
            value_type="boolean",
            hint="可选协议字段；当前创作页默认关闭",
        ),
        _parameter(
            "tools",
            "工具",
            value=[],
            value_type="json",
            hint="仅纯文生视频支持 web_search",
        ),
        _parameter(
            "seed",
            "随机种子",
            value="",
            value_type="number",
            hint="可选协议字段",
        ),
        _parameter(
            "callback_url",
            "回调地址",
            hint="可选协议字段",
        ),
        _parameter(
            "trace_id",
            "链路标识",
            hint="可选协议字段",
        ),
    ]


def _chat_parameters(model_code, *, responses=False):
    if responses:
        return [
            _parameter(
                "model",
                "模型标识",
                value=model_code,
                hint="由供应商模型目录固定",
            ),
            _parameter(
                "input",
                "输入内容",
                runtime_key="input",
                value=[],
                value_type="json",
                hint="Responses API input 内容数组",
            ),
            _parameter(
                "tools",
                "工具",
                runtime_key="tools",
                value=[],
                value_type="json",
                hint="可选工具，例如 web_search",
            ),
            _parameter(
                "max_output_tokens",
                "最大输出 Token",
                runtime_key="max_output_tokens",
                value="128000",
                value_type="number",
                minimum=1,
                maximum=128000,
                step=1,
                hint="Responses API 输出上限",
            ),
        ]
    code = str(model_code or "").strip().lower()
    if code in {
        "gpt-5.4",
        "gpt-5.5",
    }:
        token_parameter = _parameter(
            "max_completion_tokens",
            "最大完成 Token",
            runtime_key="max_completion_tokens",
            value="128000",
            value_type="number",
            minimum=1,
            maximum=128000,
            step=1,
            hint="GPT-5 推理模型使用 max_completion_tokens",
        )
    else:
        token_parameter = _parameter(
            "max_tokens",
            "最大输出 Token",
            runtime_key="max_tokens",
            value="12000",
            value_type="number",
            minimum=1,
            maximum=128000,
            step=1,
            hint="分析结果的最大输出长度",
        )
    return [
        _parameter(
            "model",
            "模型标识",
            value=model_code,
            hint="由供应商模型目录固定",
        ),
        _parameter(
            "messages",
            "消息内容",
            runtime_key="messages",
            value=[],
            value_type="json",
            hint="OpenAI Chat Completions 消息数组",
        ),
        token_parameter,
        _parameter(
            "temperature",
            "温度",
            runtime_key="temperature",
            value="0.2",
            value_type="number",
            minimum=0,
            maximum=2,
            step=0.1,
            hint="分析任务建议使用较低温度",
        ),
        _parameter(
            "top_p",
            "Top P",
            runtime_key="top_p",
            value="1",
            value_type="number",
            minimum=0,
            maximum=1,
            step=0.01,
            hint="可选采样参数；与 temperature 二选一时优先保持默认值",
        ),
        _parameter(
            "stop",
            "停止序列",
            runtime_key="stop",
            value=[],
            value_type="json",
            hint="可选字符串或字符串数组",
        ),
        _parameter(
            "stream",
            "流式输出",
            runtime_key="stream",
            value=False,
            value_type="boolean",
            hint="当前服务端按完整 JSON 响应处理，默认关闭",
        ),
    ]


def _gpt56_chat_parameters(model_code):
    return [
        _parameter(
            "model",
            "模型标识",
            value=model_code,
            hint="由供应商模型目录固定",
        ),
        _parameter(
            "messages",
            "消息内容",
            runtime_key="messages",
            value=[],
            value_type="json",
            hint="OpenAI Chat Completions 消息数组",
        ),
        _parameter(
            "max_completion_tokens",
            "最大完成 Token",
            runtime_key="max_completion_tokens",
            value="128000",
            value_type="number",
            minimum=1,
            maximum=128000,
            step=1,
            hint="GPT-5.6 系列使用 max_completion_tokens",
        ),
        _parameter(
            "reasoning_effort",
            "推理强度",
            runtime_key="reasoning_effort",
            value="medium",
            hint="GPT-5.6 系列的推理强度",
        ),
        _parameter(
            "stream",
            "流式输出",
            runtime_key="stream",
            value=False,
            value_type="boolean",
            hint="当前服务端按完整 JSON 响应处理，默认关闭",
        ),
    ]


@dataclass(frozen=True)
class ModelSpec:
    """One immutable provider model definition."""

    code: str
    name: str
    media_type: str
    generation_path: str
    result_path: Optional[str]
    parameters: Tuple[Mapping, ...]
    capabilities: Mapping = field(default_factory=dict)
    description: str = ""

    def parameter_schema(self):
        return deepcopy(list(self.parameters))

    def capability_data(self):
        return deepcopy(dict(self.capabilities))


class ProviderCatalog:
    key = "custom"
    display_name = "自定义供应商"

    def models(self) -> Tuple[ModelSpec, ...]:
        return ()

    def get(self, model_code) -> Optional[ModelSpec]:
        code = str(model_code or "").strip()
        return next((item for item in self.models() if item.code == code), None)


class ToApisCatalog(ProviderCatalog):
    key = "toapis"
    display_name = "ToAPIs"
    # Keep the catalog aligned with the original project defaults. The
    # provider remains extensible in code, but experimental model variants
    # must not be auto-created for every department or shown as enabled
    # models in the management page.
    DEFAULT_MODEL_CODES = frozenset(
        {
            "gpt-image-2",
            "gemini-3.1-flash-image-preview",
            "seedance-2",
            "gpt-5.5",
        }
    )

    def models(self):
        specs = [
            ModelSpec(
                code="gpt-image-2",
                name="GPT Image 2",
                media_type="IMAGE",
                generation_path="/v1/images/generations",
                result_path="/v1/images/generations/{task_id}",
                parameters=tuple(_toapis_gpt_image_parameters()),
                capabilities={
                    "supports_reference_images": True,
                    "max_reference_images": 14,
                    "response_format": ["url"],
                },
                description="ToAPIs GPT Image 2 图片生成接口",
            ),
            ModelSpec(
                code="gemini-3.1-flash-image-preview",
                name="Nano Banana 2",
                media_type="IMAGE",
                generation_path="/v1/images/generations",
                result_path="/v1/images/generations/{task_id}",
                parameters=tuple(_toapis_nano_banana_parameters()),
                capabilities={
                    "supports_reference_images": True,
                    "max_reference_images": 14,
                    "max_reference_image_size_mb": 10,
                    "image_formats": ["jpg", "jpeg", "png", "webp"],
                    "resolution_options": ["0.5K", "1K", "2K", "4K"],
                    "supports_google_search": True,
                    "supports_google_image_search": True,
                },
                description="ToAPIs Nano Banana 2 图片生成接口",
            ),
            ModelSpec(
                code="seedance-2",
                name="Seedance 2",
                media_type="VIDEO",
                generation_path="/v1/videos/generations",
                result_path="/v1/videos/generations/{task_id}",
                parameters=tuple(
                    _seedance_parameters(
                        "seedance-2",
                        ("480p", "720p", "1080p", "4k"),
                    )
                ),
                capabilities={
                    "supports_multimodal_reference": True,
                    "max_reference_images": 9,
                    "resolution_options": ["480p", "720p", "1080p", "4k"],
                    "supports_audio_reference": True,
                    "supports_web_search": True,
                },
                description="ToAPIs Seedance 2 多模态视频生成接口",
            ),
            ModelSpec(
                code="seedance-2-fast",
                name="Seedance 2 Fast",
                media_type="VIDEO",
                generation_path="/v1/videos/generations",
                result_path="/v1/videos/generations/{task_id}",
                parameters=tuple(
                    _seedance_parameters(
                        "seedance-2-fast",
                        ("480p", "720p"),
                    )
                ),
                capabilities={
                    "supports_multimodal_reference": True,
                    "max_reference_images": 9,
                    "resolution_options": ["480p", "720p"],
                    "supports_audio_reference": True,
                    "supports_web_search": True,
                },
                description="ToAPIs Seedance 2 Fast 多模态视频生成接口",
            ),
            ModelSpec(
                code="seedance-2-mini",
                name="Seedance 2 Mini",
                media_type="VIDEO",
                generation_path="/v1/videos/generations",
                result_path="/v1/videos/generations/{task_id}",
                parameters=tuple(
                    _seedance_parameters(
                        "seedance-2-mini",
                        ("480p", "720p"),
                    )
                ),
                capabilities={
                    "supports_multimodal_reference": True,
                    "max_reference_images": 9,
                    "max_reference_videos": 3,
                    "max_reference_audio": 3,
                    "resolution_options": ["480p", "720p"],
                    "supports_audio_reference": True,
                    "supports_web_search": True,
                },
                description="ToAPIs Seedance 2 Mini 多模态视频生成接口",
            ),
            ModelSpec(
                code="gpt-5.4-mini",
                name="GPT-5.4-mini 视觉分析",
                media_type="CHAT",
                generation_path="/v1/chat/completions",
                result_path=None,
                parameters=tuple(_chat_parameters("gpt-5.4-mini")),
                capabilities={
                    "supports_vision": True,
                    "supports_file_input": True,
                },
                description="ToAPIs GPT-5.4-mini Chat Completions 接口",
            ),
            ModelSpec(
                code="gpt-5.4",
                name="GPT-5.4 视觉分析",
                media_type="CHAT",
                generation_path="/v1/chat/completions",
                result_path=None,
                parameters=tuple(_chat_parameters("gpt-5.4")),
                capabilities={
                    "supports_vision": True,
                    "supports_file_input": True,
                },
                description="ToAPIs GPT-5.4 Chat Completions 接口",
            ),
            ModelSpec(
                code="gpt-5.5",
                name="GPT-5.5 视觉分析",
                media_type="CHAT",
                generation_path="/v1/chat/completions",
                result_path=None,
                parameters=tuple(_chat_parameters("gpt-5.5")),
                capabilities={
                    "supports_vision": True,
                    "supports_file_input": True,
                },
                description="ToAPIs GPT-5.5 Chat Completions 接口",
            ),
            ModelSpec(
                code="gpt-5.6-sol",
                name="GPT-5.6 Sol 视觉分析",
                media_type="CHAT",
                generation_path="/v1/chat/completions",
                result_path=None,
                parameters=tuple(_gpt56_chat_parameters("gpt-5.6-sol")),
                capabilities={
                    "supports_vision": True,
                    "supports_file_input": True,
                    "supports_reasoning_effort": True,
                },
                description="ToAPIs GPT-5.6 Sol Chat Completions 接口",
            ),
            ModelSpec(
                code="gpt-5.6-terra",
                name="GPT-5.6 Terra 视觉分析",
                media_type="CHAT",
                generation_path="/v1/chat/completions",
                result_path=None,
                parameters=tuple(_gpt56_chat_parameters("gpt-5.6-terra")),
                capabilities={
                    "supports_vision": True,
                    "supports_file_input": True,
                    "supports_reasoning_effort": True,
                },
                description="ToAPIs GPT-5.6 Terra Chat Completions 接口",
            ),
            ModelSpec(
                code="gpt-5.6-luna",
                name="GPT-5.6 Luna 视觉分析",
                media_type="CHAT",
                generation_path="/v1/chat/completions",
                result_path=None,
                parameters=tuple(_gpt56_chat_parameters("gpt-5.6-luna")),
                capabilities={
                    "supports_vision": True,
                    "supports_file_input": True,
                    "supports_reasoning_effort": True,
                },
                description="ToAPIs GPT-5.6 Luna Chat Completions 接口",
            ),
        ]
        return tuple(
            spec
            for spec in specs
            if spec.code in self.DEFAULT_MODEL_CODES
        )


class KuaipaoCatalog(ProviderCatalog):
    key = "kuaipao"
    display_name = "快跑AI"

    CHAT_MODEL_CODES = (
        "gpt-5.4",
        "gpt-5.5",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    )
    IMAGE_MODEL_CODES = KUAIPAO_IMAGE_MODEL_CODES
    MODEL_CODES = CHAT_MODEL_CODES + IMAGE_MODEL_CODES
    MODEL_NAMES = {
        "gpt-5.4": "GPT-5.4",
        "gpt-5.5": "GPT-5.5",
        "gpt-5.6-sol": "GPT-5.6 Sol",
        "gpt-5.6-terra": "GPT-5.6 Terra",
        KUAIPAO_IMAGE_MODEL_CODE: "gpt-image2",
    }

    def models(self):
        # Keep this catalog code-owned so environment values cannot expose
        # ToAPIs models or unverified Kuaipao model codes in the UI.
        chat_specs = tuple(
            ModelSpec(
                code=code,
                name=self.MODEL_NAMES[code],
                media_type="CHAT",
                generation_path="/responses",
                result_path=None,
                parameters=tuple(
                    _chat_parameters(code, responses=True)
                ),
                capabilities={
                    "supports_responses": True,
                    "supports_input_file": True,
                    "supports_web_search": True,
                },
                description=(
                    f"快跑AI {self.MODEL_NAMES[code]} Responses API"
                ),
            )
            for code in self.CHAT_MODEL_CODES
        )
        image_specs = tuple(
            ModelSpec(
                code=code,
                name=self.MODEL_NAMES[code],
                media_type="IMAGE",
                generation_path=KUAIPAO_IMAGE_EDIT_URL,
                result_path=None,
                parameters=tuple(_kuaipao_gpt_image_parameters(code)),
                capabilities={
                    "supports_reference_images": True,
                    "supports_image_edits": True,
                    "supports_sync_result": True,
                    "max_reference_images": 14,
                    "max_reference_image_size_mb": 10,
                    "image_formats": ["jpg", "jpeg", "png", "webp"],
                    "input_transport": "multipart",
                    "input_field": "image",
                    "returns_base64": True,
                    "force_4k_size": True,
                    "resolution_options": ["1K", "2K", "4K"],
                    "api_model_mapping": dict(KUAIPAO_IMAGE_API_MODEL_CODES),
                },
                description=(
                    f"快跑AI {self.MODEL_NAMES[code]} 图片生成/编辑接口"
                ),
            )
            for code in self.IMAGE_MODEL_CODES
        )
        return chat_specs + image_specs

    def get(self, model_code):
        return super().get(model_code)


CATALOGS = {
    ToApisCatalog.key: ToApisCatalog(),
    KuaipaoCatalog.key: KuaipaoCatalog(),
    ProviderCatalog.key: ProviderCatalog(),
}


def provider_catalog_key(provider) -> str:
    """Infer the built-in catalog from a provider's stable connection URL."""

    name = str(getattr(provider, "name", "") or "").strip().lower()
    base_url = str(getattr(provider, "base_url", "") or "").strip().lower()
    value = f"{name} {base_url}"
    if "toapis" in value:
        return ToApisCatalog.key
    if "kuaipao" in value or "快跑" in value:
        return KuaipaoCatalog.key
    return ProviderCatalog.key


def catalog_for_provider(provider) -> ProviderCatalog:
    return CATALOGS.get(provider_catalog_key(provider), CATALOGS["custom"])


def model_spec_for(provider, model_code) -> Optional[ModelSpec]:
    return catalog_for_provider(provider).get(model_code)


def catalog_payload(provider, existing_models: Iterable = ()) -> Dict:
    """Return read-only catalog entries plus current database enable state."""

    existing_by_code = {
        str(getattr(model, "model_code", "") or "").strip(): model
        for model in (existing_models or ())
        if str(getattr(model, "model_code", "") or "").strip()
    }
    catalog = catalog_for_provider(provider)
    items = []
    for spec in catalog.models():
        existing = existing_by_code.get(spec.code)
        items.append(
            {
                "code": spec.code,
                "name": spec.name,
                "media_type": spec.media_type,
                "generation_path": spec.generation_path,
                "result_path": spec.result_path or "",
                "parameter_schema": spec.parameter_schema(),
                "capabilities": spec.capability_data(),
                "description": spec.description,
                "model_id": getattr(existing, "id", None),
                "enabled": bool(getattr(existing, "enabled", 0)),
            }
        )
    return {
        "key": catalog.key,
        "name": catalog.display_name,
        "models": items,
    }


def spec_payload(spec: Optional[ModelSpec]) -> Dict:
    if not spec:
        return {}
    return {
        "code": spec.code,
        "name": spec.name,
        "media_type": spec.media_type,
        "generation_path": spec.generation_path,
        "result_path": spec.result_path or "",
        "parameter_schema": spec.parameter_schema(),
        "capabilities": spec.capability_data(),
        "description": spec.description,
    }
