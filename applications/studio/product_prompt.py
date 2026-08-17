import json


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


def product_reference_urls(product, extra_urls=None, media_type="IMAGE"):
    """Collect enabled product assets plus one-off references for a task."""

    urls = split_urls(product.asset_urls if product else "")
    if product:
        for asset in product.assets:
            if not asset.enabled:
                continue
            asset_type = str(asset.asset_type or "IMAGE").upper()
            if media_type == "IMAGE" and asset_type not in ("IMAGE", "BOTH"):
                continue
            if media_type == "VIDEO" and asset_type not in ("IMAGE", "VIDEO", "BOTH"):
                continue
            urls.append(asset.url)
    urls.extend(split_urls(extra_urls))
    return list(dict.fromkeys(urls))


def compose_prompt(product, user_prompt):
    """Combine durable product memory with the current creative request."""

    parts = []
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
    if user_prompt:
        parts.append(f"本次创意要求：{str(user_prompt).strip()}")
    return "\n".join(parts).strip()
