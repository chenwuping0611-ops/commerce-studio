"""Contract checks for the batch detail-image prompt Skill."""

from pathlib import Path


SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "applications"
    / "amazon_ai"
    / "skills"
    / "Amazon_Ecommerce_Batch_Detail_Image_Skill.md"
)


def main():
    content = SKILL_PATH.read_text(encoding="utf-8")

    # The batch protocol is intentionally stable: visual constraints may grow,
    # but version parsing and the downstream JSON contract must remain intact.
    fixed_output_markers = (
        "## 批量输出要求",
        "当页面数量为 `0` 时，系统已经归一化为 `N=10`，必须输出 10 个版本",
        "当页面数量为 `1-50` 时，必须严格输出对应数量",
        "一次模型调用中生成全部 `N` 个版本",
        "每个版本必须是非空字符串，且字符数不能超过 32000",
        "每个图片版本正文必须明确写出一行 `画布比例：<系统预设比例>` 和一行 `图片质量：<1K/2K/4K>`",
        "不要在字符串中写“第一版”“第二版”等编号",
        "严格只返回合法 JSON",
        '{"versions":["第一个完整图片详情图提示词","第二个完整图片详情图提示词"]}',
    )
    for marker in fixed_output_markers:
        assert marker in content, marker

    strengthened_constraints = (
        "电池仓、握把、扳机",
        "主图、场景图、详情小格和局部特写都必须复用这份清单",
        "产品名称只能作为外部标题或识别信息",
        "粗细变化、弯曲程度、端部形状",
        "手掌、手指、扳机、电池仓和产品受力方向",
        "外部详情图标题、卖点标签、参数文字与产品本体原始文字",
        "每个版本的强制画面契约",
        "完整产品定位视图或清晰连接关系",
    )
    for marker in strengthened_constraints:
        assert marker in content, marker

    # The additions must stay in the constraint section and must not replace
    # the fixed output rules that the parser and image batch processor use.
    assert content.index("### 每个版本的强制画面契约") < content.index(
        "## 批量输出要求"
    )


if __name__ == "__main__":
    main()
