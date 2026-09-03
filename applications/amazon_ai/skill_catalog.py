from pathlib import Path


SKILL_DIRECTORY = Path(__file__).resolve().parent / "skills"
PRODUCT_EXTRACTION_SKILL_CODE = "Amazon_Product_Extraction_Skill.md"
DETAIL_IMAGE_SKILL_CODE = "Amazon_Ecommerce_Detail_Image_Skill.md"
BATCH_DETAIL_IMAGE_SKILL_CODE = "Amazon_Ecommerce_Batch_Detail_Image_Skill.md"

AMAZON_SKILL_DEFINITIONS = (
    {
        "name": "Amazon 竞品分析 Skill",
        "code": "Amazon_Competitor_Analysis_Skill.md",
        "file_name": "Amazon_Competitor_Analysis_Skill.md",
        "tags": "Amazon,竞品分析,市场定位,Listing",
        "task_type": "COMPETITOR_ANALYZE",
    },
    {
        "name": "Amazon Listing 两段式创作 Skill",
        "code": "Amazon_Listing_Writer_Skill.md",
        "file_name": "Amazon_Listing_Writer_Skill.md",
        "tags": "Amazon,Listing,Item Name,Item Highlights,QA",
        "task_type": "LISTING_GENERATE",
    },
    {
        "name": "Amazon 轻差异化策略 Skill",
        "code": "Amazon_Light_Differentiation_Skill.md",
        "file_name": "Amazon_Light_Differentiation_Skill.md",
        "tags": "Amazon,差异化分析,现货微改,配件,成本",
        "task_type": "DIFFERENTIATION_GENERATE",
    },
    {
        "name": "Amazon Listing 产品资料提取 Skill",
        "code": PRODUCT_EXTRACTION_SKILL_CODE,
        "file_name": PRODUCT_EXTRACTION_SKILL_CODE,
        "tags": "Amazon,Listing,产品中心,产品档案,结构化提取",
        "task_type": "PRODUCT_EXTRACT",
        "media_type": "TEXT",
        "hidden_from_task_options": True,
    },
    {
        "name": "Amazon 电商详情图创作 Skill",
        "code": DETAIL_IMAGE_SKILL_CODE,
        "file_name": DETAIL_IMAGE_SKILL_CODE,
        "tags": "Amazon,图片创作,电商详情图,产品中心,核心卖点,产品素材",
        "media_type": "IMAGE",
    },
    {
        "name": "Amazon 电商批量详情图提示词 Skill",
        "code": BATCH_DETAIL_IMAGE_SKILL_CODE,
        "file_name": BATCH_DETAIL_IMAGE_SKILL_CODE,
        "tags": "Amazon,批量创作,图片,电商详情图,产品中心,产品约束",
        "media_type": "IMAGE",
    },
    {
        "name": "Amazon 电商批量创作提示词 Skill",
        "code": "Amazon_Ecommerce_Batch_Prompt_Skill.md",
        "file_name": "Amazon_Ecommerce_Batch_Prompt_Skill.md",
        "tags": "Amazon,批量创作,提示词,图片创作,视频创作,产品中心",
        "media_type": "BOTH",
    },
)

TASK_SKILL_CODES = {
    task_type: item["code"]
    for item in AMAZON_SKILL_DEFINITIONS
    for task_type in (
        item.get("task_types")
        or (item.get("task_type"),)
    )
    if task_type
}

AMAZON_BUILTIN_SKILL_CODES = frozenset(
    item["code"] for item in AMAZON_SKILL_DEFINITIONS
)


def read_skill_content(definition):
    path = SKILL_DIRECTORY / definition["file_name"]
    return path.read_text(encoding="utf-8")


def skill_definition_for_task(task_type):
    code = TASK_SKILL_CODES.get(str(task_type or "").strip().upper())
    return next(
        (item for item in AMAZON_SKILL_DEFINITIONS if item["code"] == code),
        None,
    )
