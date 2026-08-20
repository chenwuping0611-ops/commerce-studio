import json


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


def _role_index(role):
    try:
        return PRODUCT_ASSET_ROLE_ORDER.index(str(role or "").lower())
    except ValueError:
        return len(PRODUCT_ASSET_ROLE_ORDER)


def product_reference_descriptors(product, extra_urls=None, media_type="IMAGE"):
    """Return stable, labeled references for prompt and provider request bodies.

    Product references always come first. Fixed product views are ordered as
    front, back, left, right, top, bottom, then cover/detail/scene assets.
    One-off uploads are appended afterwards in the order supplied by the
    creation form.
    """

    descriptors = []
    seen = set()

    def add(url, role, source, name="", index=None):
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
            }
        )

    if product:
        assets = [
            asset
            for asset in (product.assets or [])
            if getattr(asset, "enabled", True)
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
            if media_type == "VIDEO" and asset_type not in ("IMAGE", "VIDEO", "BOTH"):
                continue
            add(
                getattr(asset, "url", ""),
                getattr(asset, "role", "reference"),
                "product",
                getattr(asset, "name", ""),
            )

        for index, url in enumerate(split_urls(getattr(product, "asset_urls", "")), 1):
            add(url, "reference", "product", f"产品外部素材 {index}")

    for index, url in enumerate(split_urls(extra_urls), 1):
        add(
            url,
            "reference",
            "request",
            f"本次上传的其他细节图 {index}",
            index=index,
        )

    return descriptors


def product_reference_urls(product, extra_urls=None, media_type="IMAGE"):
    """Collect enabled product assets plus one-off references for a task."""

    return [
        descriptor["url"]
        for descriptor in product_reference_descriptors(product, extra_urls, media_type)
    ]


def reference_instructions(descriptors):
    """Describe ordered image roles so a planner can preserve product identity."""

    lines = []
    for index, descriptor in enumerate(descriptors or [], 1):
        label = descriptor.get("label") or "参考图"
        source = "产品中心" if descriptor.get("source") == "product" else "本次上传"
        name = descriptor.get("name")
        suffix = f"（{name}）" if name else ""
        lines.append(f"第 {index} 张参考图：{label}{suffix}，来源：{source}。")
    return "\n".join(lines)


def compose_prompt(product, user_prompt, descriptors=None, skill_prompt=None):
    """Put the current creative request first, then append fixed product context."""

    parts = []
    if user_prompt:
        parts.append(f"本次创意要求：{str(user_prompt).strip()}")
    if skill_prompt:
        parts.append(f"创作 Skill 指令：{str(skill_prompt).strip()}")
    if product:
        if product.name:
            parts.append(f"产品名称：{product.name}")
        if product.brand:
            parts.append(f"品牌信息：{product.brand}")
        if product.description:
            parts.append(f"产品资料：{product.description}")
        if product.product_profile:
            parts.append(f"Product Profile：{product.product_profile}")
        if product.product_memory:
            parts.append(f"产品记忆：{product.product_memory}")
        if product.generation_rules:
            parts.append(f"生成规则：{product.generation_rules}")
        if product.forbidden_rules:
            parts.append(f"禁止修改规则：{product.forbidden_rules}")
    instructions = reference_instructions(descriptors)
    if instructions:
        parts.append(
            "参考图必须按以下顺序理解，第一张、第二张及后续图片的角色不能混淆：\n"
            + instructions
        )
    return "\n".join(parts).strip()
