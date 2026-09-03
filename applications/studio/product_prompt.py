import datetime
import json
import re


PRODUCT_ASSET_ROLE_ORDER = (
    "front",
    "back",
    "left",
    "right",
    "top",
    "bottom",
    "cover",
    "detail",
    "scene",
    "reference",
    "360",
)

PRODUCT_ASSET_ROLE_LABELS = {
    "front": "产品正面图",
    "back": "产品背面图",
    "left": "产品左侧图",
    "right": "产品右侧图",
    "top": "产品顶部图",
    "bottom": "产品底部图",
    "cover": "产品主图",
    "detail": "产品细节图",
    "scene": "产品场景图",
    "reference": "产品其他参考图",
    "360": "产品 360 视频参考",
}

VIDEO_URL_PATTERN = re.compile(
    r"\.(?:mp4|mov|webm|m4v|avi|mkv|mpeg|mpg)(?:$|[?#])",
    re.IGNORECASE,
)

DETAIL_IMAGE_OUTPUT_CONTRACT = """
【图片创作硬性输出契约：不可降级】
1. 最终只生成一张完整的 Amazon 电商详情信息图；同一画布必须同时有完整主视觉、真实卖点、产品细节和使用场景或参数模块。不得只输出白底单品抠图、证件照、普通白底展示图或没有详情模块的单张产品照，也不得输出彼此无关的多张图片拼贴。
2. 产品中心提供的全部图片是唯一产品身份依据。正面、背面、左侧、右侧及其他角度都属于同一个产品；如果本次只有左侧图和右侧图，必须把它们合并理解为同一个产品的两个视角，不能生成两个产品或把一张图当成另一种型号。
3. 生成前必须从产品中心图片逐项清点主体和所有可见配件，记录颜色、色块边界、轮廓、比例、材质、纹理、缝线、Logo、连接位置、配件种类和准确数量。主体与每一个钥匙扣、钥匙圈、金属环、龙虾扣、连接片、挂扣及其他五金属于不可拆分的同一产品身份，不能模糊概括为“配件齐全”。
4. 产品中心图片中可见的每一个配件都必须保留、逐个对应、数量一致、形状一致、颜色一致、连接关系一致。主视觉、场景示意、详情小格、局部特写和放大模块都只能复用同一个真实产品；不得遗漏、增加、复制、合并、替换、隐藏、重新设计或改变配件。任何小图都不能出现“主图有、细节图少一个”的情况。
5. 画面至少包含一个完整产品主视觉和三个有明确层级的详情模块；每个详情模块都必须能看出仍是同一个产品，至少保留完整产品定位图或清晰连接关系。没有资料支持的卖点、参数和功能必须省略，不能用猜测填充；浅色背景和留白不能取代详情模块。
6. 用户创意可以改变场景、构图、镜头、光线和风格，但不能改变产品固定身份。不得因挂在包、裤腰带或其他场景中而遮挡或丢失任一配件，不得通过裁切、虚化、反光、阴影或透视掩盖缺件；产品不得拉伸、融化、变形、换色或换型号。
7. 最终生成前必须逐项复核：产品颜色、结构、比例、材质、主体数量、每一种配件及数量、每个配件的连接关系、每个详情模块的产品一致性和所有文字参数均正确；不得虚构文字、规格、认证或功能。
8. 参考图中任何可见的品牌名、型号、按钮标签、电池标签、警示字样、图标、丝印、刺绣和包装文字都是产品外观的一部分。必须保持原文、语言、大小写、方向、位置、颜色、字形可辨识程度和相对大小；不得把产品中心的产品名称覆盖、替换或改写到产品本体上。无法辨认的文字必须保持无法辨认或省略，不能凭空补写、翻译、换品牌或生成新型号。
9. 如果产品包含长筒、喷筒、管体、杆体、轴体、线缆或其他细长结构，必须按参考图保持真实长度、直径、粗细变化、弯曲程度、端部形状、连接件和与主体的比例；不得拉长、缩短、变粗、变细、拉直、折叠、熔化、穿模或用透视/裁切隐藏。视角可以变化，但物理几何比例不能变化。
10. 如果产品有握把、手柄、扳机或电池仓，使用场景必须让人物手握真实握把/手柄，手指和扳机位置符合人体工学，产品正反面和电池位置仍与参考图一致；不得手拿喷筒、长管、出风口或不适合握持的部位，不得增加第二个握把、改变握把方向或把工具画成另一种结构。若参考图没有明确握把，不能凭空添加握把或指定错误姿势。
11. 详情图中的产品文字、标签和标注必须服务于已确认事实，不能为了“更像电商图”重绘、擦除或替换产品本体上的原始文字；外部排版标题与产品本体丝印必须严格区分，外部标题不能遮挡、覆盖或冒充原始标签。
""".strip()

PRODUCT_IDENTITY_PLANNER_CONTRACT = """
【产品身份与使用方式规划硬约束】
1. 产品中心图片中的产品本体、可见文字和所有配件是最终视觉身份依据。产品名称字段只用于识别产品或安排外部标题，绝不能覆盖或改写机身、面板、电机、按钮、电池标签、包装上的原始品牌、型号、标签、丝印、图标和警示文字。
2. 规划时必须逐张核对产品图片中的原始文字：保持原文、大小写、数字、符号、语言、方向、位置、颜色和相对大小；无法辨认的文字保持不可辨认，不得自行补写、翻译、替换成产品名称或生成新型号。
3. 对黑色长筒、喷筒、管体、杆体、轴体和其他细长结构，必须根据参考图保持长度、直径、粗细变化、端部形状、连接位置和与主体的比例；不得为了构图拉伸、缩短、变粗、变细或用透视、裁切、遮挡隐藏。
4. 如果图片显示握把、手柄、扳机或电池仓，使用场景必须让人物握住真实握把/手柄，手指和扳机位置符合产品结构；禁止手拿喷筒、长管、出风口或其他不适合握持的部位，禁止新增握把或改变产品结构。
5. 外部详情图标题、参数文字和产品本体原始文字必须严格区分；外部标题不得贴到产品本体标签位置，也不得把一个模块中识别出的产品名称当作产品图片上的文字。
""".strip()


def _looks_like_video_url(url):
    """Avoid treating legacy URL-only video entries as image references."""

    value = str(url or "").strip()
    return bool(
        VIDEO_URL_PATTERN.search(value)
        or re.search(r"/(?:video|videos|media/video)(?:/|$)", value, re.I)
    )


def split_urls(raw):
    """Normalize a textarea, JSON array, or Python list into unique URL values."""

    if not raw:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        try:
            parsed = json.loads(raw)
            values = parsed if isinstance(parsed, list) else [raw]
        except (TypeError, ValueError):
            values = str(raw).replace(",", "\n").splitlines()
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def detail_image_output_contract():
    """Return the compact hard contract shared by planner and image calls."""

    return DETAIL_IMAGE_OUTPUT_CONTRACT


def product_identity_planner_contract():
    """Return the shared identity rules for multimodal prompt planning."""

    return PRODUCT_IDENTITY_PLANNER_CONTRACT


def append_detail_image_output_contract(prompt, max_bytes=5000):
    """Keep the detail-image contract in the final provider prompt.

    Planner output is user-facing and the provider prompt has a hard byte
    limit. Truncate the lower-priority planner text first so the contract
    itself cannot disappear from the request.
    """

    try:
        max_bytes = int(max_bytes)
    except (TypeError, ValueError):
        max_bytes = 5000
    text = str(prompt or "").strip()
    contract = DETAIL_IMAGE_OUTPUT_CONTRACT
    if contract in text:
        if len(text.encode("utf-8")) <= max_bytes:
            return text
        text = text.split(contract, 1)[0].rstrip()
    suffix = "\n\n" + contract
    suffix_bytes = suffix.encode("utf-8")
    if max_bytes <= len(suffix_bytes):
        return suffix_bytes[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    prefix_budget = max_bytes - len(suffix_bytes)
    prefix = text.encode("utf-8")[:prefix_budget].decode(
        "utf-8",
        errors="ignore",
    ).rstrip()
    return (prefix + suffix).strip()


def _role_index(role):
    try:
        return PRODUCT_ASSET_ROLE_ORDER.index(str(role or "").lower())
    except ValueError:
        return len(PRODUCT_ASSET_ROLE_ORDER)


def product_reference_descriptors(
    product,
    extra_urls=None,
    media_type="IMAGE",
    asset_filter=None,
):
    """Return stable, labeled references for prompt and provider request bodies.

    Product references always come first. Fixed product views are ordered as
    front, back, left, right, top, bottom, then cover/detail/scene assets for
    image creation. Video creation deliberately uses only the four standard
    product views (front, back, left, right); empty product slots are omitted.
    One-off uploads are appended afterwards in the order supplied by the
    creation form.
    """

    descriptors = []
    seen = set()
    video_reference_roles = {"front", "back", "left", "right"}

    def add(url, role, source, name="", index=None, asset_type="IMAGE"):
        url = str(url or "").strip()
        if not url or url in seen:
            return
        seen.add(url)
        role = str(role or "reference").lower()
        label = PRODUCT_ASSET_ROLE_LABELS.get(role, "参考素材")
        if source == "request":
            label = f"本次上传的其他细节图 {index or 1}"
        descriptors.append(
            {
                "url": url,
                "role": role,
                "label": label,
                "source": source,
                "name": str(name or "").strip(),
                "asset_type": str(asset_type or "IMAGE").upper(),
            }
        )

    if product:
        assets = [
            asset
            for asset in (product.assets or [])
            if getattr(asset, "enabled", True)
            and (
                asset_filter is None
                or asset_filter(asset)
            )
        ]
        assets.sort(
            key=lambda asset: (
                _role_index(getattr(asset, "role", "")),
                int(getattr(asset, "sort", 0) or 0),
                int(getattr(asset, "id", 0) or 0),
            )
        )
        for asset in assets:
            asset_type = str(getattr(asset, "asset_type", "IMAGE") or "IMAGE").upper()
            if media_type == "IMAGE" and asset_type not in ("IMAGE", "BOTH"):
                continue
            if (
                media_type == "IMAGE"
                and str(getattr(asset, "role", "") or "").lower() == "360"
                and asset_type != "IMAGE"
            ):
                continue
            if media_type == "VIDEO" and (
                asset_type not in ("IMAGE", "BOTH")
                or str(getattr(asset, "role", "") or "").lower()
                not in video_reference_roles
            ):
                continue
            storage_asset = getattr(asset, "storage_asset", None)
            storage_url = str(
                getattr(storage_asset, "public_url", "") or ""
            ).strip()
            storage_is_active = bool(
                storage_asset
                and str(getattr(storage_asset, "status", "") or "").upper()
                == "ACTIVE"
                and not (
                    getattr(storage_asset, "expires_at", None)
                    and storage_asset.expires_at <= datetime.datetime.now()
                )
            )
            # A storage-backed product asset is canonical. Do not let an old
            # URL-only value silently replace the current GoFastDFS file.
            if storage_url and storage_is_active:
                asset_url = storage_url
            elif getattr(asset, "storage_asset_id", None):
                asset_url = ""
            else:
                asset_url = getattr(asset, "url", "")
            asset_name = (
                getattr(asset, "name", "")
                or getattr(storage_asset, "original_filename", "")
            )
            add(
                asset_url,
                getattr(asset, "role", "reference"),
                "product",
                asset_name,
                asset_type=asset_type,
            )

        if media_type != "VIDEO":
            for index, url in enumerate(split_urls(getattr(product, "asset_urls", "")), 1):
                if _looks_like_video_url(url):
                    continue
                add(
                    url,
                    "reference",
                    "product",
                    f"产品外部素材 {index}",
                    asset_type="IMAGE",
                )

    for index, url in enumerate(split_urls(extra_urls), 1):
        add(
            url,
            "reference",
            "request",
            f"本次上传的其他细节图 {index}",
            index=index,
            asset_type="IMAGE",
        )

    return descriptors


def product_reference_urls(
    product,
    extra_urls=None,
    media_type="IMAGE",
    asset_filter=None,
):
    """Collect enabled product assets plus one-off references for a task."""

    return [
        descriptor["url"]
        for descriptor in product_reference_descriptors(
            product,
            extra_urls,
            media_type,
            asset_filter=asset_filter,
        )
    ]


def reference_instructions(descriptors, include_urls=True):
    """Describe ordered image roles without repeating the full prompt context."""

    lines = []
    for index, descriptor in enumerate(descriptors or [], 1):
        label = descriptor.get("label") or "参考图"
        source = "产品中心" if descriptor.get("source") == "product" else "本次上传"
        name = descriptor.get("name")
        suffix = f"（{name}）" if name else ""
        url = str(descriptor.get("url") or "").strip()
        url_part = f"；URL：{url}" if include_urls and url else ""
        lines.append(f"第 {index} 张参考图：{label}{suffix}；来源：{source}{url_part}。")
    return "\n".join(lines)


def video_reference_instructions(urls, include_urls=True):
    """Describe ordered video references supplied for the current task."""

    lines = []
    for index, url in enumerate(split_urls(urls), 1):
        url_part = f"；URL：{url}" if include_urls else ""
        lines.append(f"第 {index} 个参考视频：本次上传的视频 {index}{url_part}。")
    return "\n".join(lines)


def compose_prompt(
    product,
    user_prompt,
    descriptors=None,
    skill_prompt=None,
    media_type="IMAGE",
    video_urls=None,
):
    """Compose a prompt using creative, product, then Skill priority.

    Product information is shared by image and video creation. The user
    creative request leads the scene and style, product fields protect the
    product identity, and Skill instructions only fill details left undefined.
    """

    parts = []
    media_type = str(media_type or "IMAGE").upper()
    if user_prompt:
        parts.append(f"本次创意要求：{str(user_prompt).strip()}")
    if product:
        if product.name:
            parts.append(f"产品名称：{product.name}")
        if product.brand:
            parts.append(f"品牌信息：{product.brand}")
        if product.description:
            parts.append(f"产品资料：{product.description}")
        if product.product_profile:
            parts.append(f"Product Profile：{product.product_profile}")
        if product.core_selling_points:
            parts.append(f"核心卖点：{product.core_selling_points}")
        if product.product_memory:
            parts.append(f"产品记忆：{product.product_memory}")
        if product.generation_rules:
            parts.append(f"生成规则：{product.generation_rules}")
        if product.forbidden_rules:
            parts.append(f"禁止修改规则：{product.forbidden_rules}")
    if skill_prompt:
        parts.append(
            "创作 Skill 指令（仅作为未定义内容的兜底，不得覆盖用户创意或产品约束）："
            + str(skill_prompt).strip()
        )
    instructions = reference_instructions(descriptors, include_urls=False)
    if instructions:
        parts.append(
            "参考图必须按以下顺序理解，第一张、第二张及后续图片的角色不能混淆：\n"
            + instructions
        )
    video_instructions = video_reference_instructions(video_urls, include_urls=False)
    if video_instructions:
        parts.append(
            "参考视频必须按以下顺序理解；视频只作为动作、镜头和运动参考，"
            "不能改变产品固定结构：\n"
            + video_instructions
        )
    return "\n".join(parts).strip()
