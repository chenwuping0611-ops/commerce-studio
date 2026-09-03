---
name: amazon-listing-product-extraction
description: >
  从已经完成的 Amazon Listing 创作历史中提取有证据支持的长期产品资料，
  供产品中心创建和后续图片、视频、Amazon AI 任务引用。
metadata:
  short-description: Amazon Listing 产品资料提取 Skill
---

# Amazon Listing Product Extraction Skill

你负责把一份已经完成的 Listing 创作历史整理成产品中心可以长期维护的结构化资料。

## 输入边界

输入是系统读取到的 Listing 创作历史 TXT 或 Markdown 全文。只使用输入中明确出现、并且确实描述目标产品的内容。不要访问外部网页，不要调用其他模型，不要把这次任务的内部信息当成产品资料。

## 字段规则

- `product_name`：只有 Listing 的 Item Name 或明确产品名称能确认时才填写。
- `product_code`：只填写正文中明确标注为 SKU、Model、MPN、Product Code 或同义产品编码的值。绝对不能使用 ASIN、Amazon 链接、任务 ID、任务编号、文件名或日期时间代替产品编码。
- `brand`：只有明确写出的品牌才填写。
- `description`：优先整理 Product Description 中明确描述产品本身的内容，可以保留重要参数、用途、适用场景和限制。
- `core_selling_points`：从 Item Highlights、明确的产品卖点和产品功能中提炼长期可复用的卖点，只保留有输入证据的内容。
- `product_profile`：只记录稳定的产品身份信息，例如外形、结构、材质、颜色、品牌标识、接口、按钮、附件和明确规格。
- `product_memory`：只记录适合后续创作长期携带的明确事实、目标人群、使用场景或产品偏好；一次性的广告修辞不要写入。
- `generation_rules`：只有输入明确给出长期生成要求时才填写，不要为了完整而自行生成。
- `forbidden_rules`：只有输入明确给出禁止修改或不可改变的内容时才填写，不要凭空补充。

不能从输入确认的字段必须返回 `null`。不能用“未知”“信息缺失”“暂无”等文字代替空值。数组字段请合并成一个易读的字符串，每条内容单独一行。

## 输出格式

只返回一个 JSON 对象，不要 Markdown 代码块、解释文字或额外字段：

{
  "product_name": null,
  "product_code": null,
  "brand": null,
  "description": null,
  "core_selling_points": null,
  "product_profile": null,
  "product_memory": null,
  "generation_rules": null,
  "forbidden_rules": null
}

所有非空字段必须是字符串。不要输出 ASIN、任务编号、来源文件名或来源 URL 作为产品编码。
