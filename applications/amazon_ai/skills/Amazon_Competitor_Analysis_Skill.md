---
name: amazon-competitor-analysis-skill
description: Create structured Chinese Amazon competitor research reports and a final evidence-based summary of recommended selling points, functions, scenarios, specifications, and target audiences without inventing missing data.
metadata:
  short-description: Amazon 竞品分析 Skill
---

# Amazon 竞品分析 Skill

Use this skill when the user provides one or more Amazon product pages and wants a structured Chinese competitor research report in the format defined below.

For multiple links, write one complete report per product, in the same order as the links. Use headings `竞品 A`, `竞品 B`, and so on. Do not merge data between ASINs. After all product reports, add one consolidated recommendation summary. Do not create Excel unless the user explicitly asks.

## Evidence Rules

Use only content actually visible on the supplied Amazon product page and its accessible sections:

- Product title and product details
- Bullet points
- Main image, secondary images, and images in A+ content
- A+ content, package information, and visible after-sales claims
- Overall rating, visible reviews, and visible Q&A

Do not use external keyword tools, review aggregators, brand sites, search results, market data, or unsupported assumptions.

If a page, image, A+, review, or Q&A section is unavailable, state `信息缺失` for that exact section. Do not replace a missing section with guesses. Start each report with a short note stating which page materials were available and which were missing.

Keep these evidence types distinct in reasoning:

- `页面事实`：directly shown on the product page.
- `用户反馈`：stated in a visible review.
- `QA信息`：stated in a visible question or answer.
- `推导`：a restrained conclusion from page facts, reviews, or Q&A; cite the basis and do not present it as fact.

## Analysis Rules

### Title Core Keywords

Extract meaningful title phrases in their actual left-to-right order. Explain each phrase's role, such as core product noun, quantity, product form, compatible device, specification, or category.

Do not claim real Amazon search weight, search volume, ranking, or traffic from title order alone. Describe the sequence as `标题文案重心从前到后`.

### Five Bullet Points

For each visible bullet, extract only its core selling point, function, scenario, and factual parameters. Keep the table concise. Do not rewrite bullets into new listing copy.

### A+ And Visuals

Analyze A+ structure only when A+ modules are visible. Describe the page sequence and logic only from shown modules, for example `问题 -> 功能 -> 参数 -> 场景 -> 信任`, and label the logic as `推导`.

Analyze the main image and secondary images only when visible. Cover main-image message, image order, and whether real use scenarios are shown. If images are unavailable, state that the whole visual section is missing.

### Reviews And Q&A

Record the overall displayed star rating and review count exactly as shown. Make the rating and count bold.

Calculate a recent-30-day rating only from visible reviews with readable dates and star ratings. State the number of included visible reviews. If the page does not expose sufficient dated reviews, state `信息缺失`.

For low-rated reviews, return up to five repeated issues from visible 1-2 star reviews. For positive reviews, return up to three repeated benefits from visible 3-5 star reviews. Include only visible-sample counts; do not claim they represent all reviews.

For Q&A, list up to five repeated buyer concerns from accessible Q&A. Treat an answer as official only if the brand, seller, or Amazon official identity is visible. Otherwise state `未见官方回复`.

### Pain Points And Opportunity Points

Pain points must come from visible low-star reviews, repeated Q&A concerns, or a clearly stated product limitation.

Opportunity points must be marked as `【推导】` and grounded in a cited pain point, limitation, or listing information gap. Phrase them as possible improvement directions. Do not state unverified product defects, market gaps, market demand, or competitor advantages as facts.

### Final Competitor Summary And Recommendation

When two or more competitor pages are analyzed, add one final section after all individual reports: `## 六、竞品汇总：产品基本信息`.

This section converts the preceding competitor evidence into practical directions for the user's product. It is not a new competitor report and must not repeat every product's details.

Use these rules:

- A `竞品共性` may be stated only when at least two analyzed competitor pages explicitly show the same function, scenario, parameter pattern, target audience, or selling-point theme.
- Every recommended product direction must start with `【推导】` and cite its competitor basis by competitor label, ASIN, or a short source reference such as `竞品A五点1、竞品C产品信息`.
- Do not describe a recommendation as a confirmed market need, guaranteed conversion driver, exclusive advantage, or final product specification.
- If the user provides their own product facts, prioritize recommendations compatible with those facts. If the user does not provide their product details, write `适合切入的候选方向` rather than assuming the user's final product configuration.
- Do not invent a recommended material, size, count, function, certification, or target audience without a basis in the preceding reports. When recommending a combination of existing competitor features, make clear it is a combination inference.

The final summary must contain only these six fields:

1. **品牌名称**：Use the user's brand when supplied; otherwise write `待定`.
2. **适用场景**：Recommended scenarios based on the preceding competitors.
3. **核心功能**：Recommended functions based on the preceding competitors.
4. **核心参数**：Recommended page-supported specifications or package combination.
5. **目标人群**：Recommended audiences based on the preceding competitors.
6. **主要差异化卖点**：Recommended differentiated product propositions based on recurring competitor limitations, unclear information, or a valid combination of existing competitor strengths.

For fields 2-6, every recommendation must start with `【推导】` and include a compact evidence basis in parentheses.

## Required Output Format

Use this exact report structure. Keep it concise but complete. Do not add a separate methodology section beyond the initial note.

```markdown
# 亚马逊竞品调研报告

> 注：本报告所有数据均来源于提供的产品页面内容；未在页面中呈现的主图/A+视觉内容、QA、分星级评价、近30天评分、售后政策等维度，均标注“信息缺失”，未编造数据。

## 一、文案转化分析

### 1. 标题核心关键词排序

标题文案重心从前到后，核心关键词依次为：

1. [页面关键词/短语]（中文说明，词组角色）
2. [页面关键词/短语]（中文说明，词组角色）

### 2. 五点描述核心信息拆解

| 卖点序号 | 核心卖点 | 对应功能 | 适用场景 | 核心参数 |
|---|---|---|---|---|
| 1 |  |  |  |  |

### 3. A+页面逻辑结构

[基于可见A+模块的简短逻辑分析；若缺失，明确说明信息缺失。]

### 4. 售后承诺

[仅记录页面明确写出的质保、退换、客服、补发或满意保证；若缺失，明确说明信息缺失。]

## 二、视觉体系分析

[主图卖点、辅图顺序、场景化展示情况；若图片不可见，明确说明该板块整体信息缺失。]

## 三、用户真实反馈

1. **整体星级**：**[页面显示星级]**，累计**[页面显示评价数]**
2. 近30天评分：[可见带日期评论样本计算结果；否则“信息缺失”]
3. 1-2星差评Top5高频问题：[可见样本的高频问题；否则“信息缺失”]
4. 3-5星好评Top3核心卖点：[可见样本的高频卖点；否则“信息缺失”]

## 四、QA高频问题

[买家最关心的最多5个问题及官方回复口径；若QA不可见，明确说明信息缺失。]

## 五、重点调研：五点描述深度拆解

### 1. 主打卖点

- [页面支持的主打卖点]

### 2. 核心功能

- [页面支持的核心功能]

### 3. 适用场景

- [页面支持的适用场景]

### 4. 核心参数

- [页面支持的参数]

### 5. 目标人群

- [页面明确的人群；图片推断需标注]

---

## 产品痛点与市场机会点

### 产品痛点

- [页面事实或用户反馈支持的痛点]

### 市场机会点

- 【推导】[基于已列出证据的可能改进方向]

---

## 产品基本信息

- **品牌名称**：[品牌]
- **适用场景**：[场景]
- **核心功能**：[功能]
- **核心参数**：
  - [参数]
- **目标人群**：[人群]
- **主要差异化卖点**：[页面支持的主打卖点；不要把未验证的市场比较写成事实]
```

After all competitors have been reported, append this exact structure when two or more competitors are available:

```markdown
---

## 六、竞品汇总：产品基本信息

> 注：以下内容基于前述竞品页面信息进行归纳；除品牌名称外，均为【推导】，需结合你的产品能力、成本与合规要求进一步验证。

- **品牌名称**：[用户提供的品牌；未提供则写“待定”]
- **适用场景**：【推导】[建议优先的场景]（依据：[对应竞品证据]）
- **核心功能**：【推导】[建议优先的功能]（依据：[对应竞品证据]）
- **核心参数**：【推导】[建议考虑的参数、数量、材质或组件组合]（依据：[对应竞品证据]）
- **目标人群**：【推导】[建议优先的人群]（依据：[对应竞品证据]）
- **主要差异化卖点**：【推导】[基于竞品限制、信息缺口或可组合优势的主张]（依据：[对应竞品证据]）
```

## Writing Requirements

- Use Chinese as the primary language. Preserve original English terms, models, units, dimensions, and claimed numbers when useful for accuracy.
- Use bold only for key displayed data such as star rating, review count, major quantities, ranges, dimensions, or material claims.
- In the five-bullet table, use `信息缺失` for missing values instead of filling empty cells.
- Keep each analysis item attributable to visible page content. Do not paste full page text unless the user explicitly asks.
- When a limitation is an inference, make its condition clear. Example: `未标注耐高温性能，高功率场景适用性需进一步验证`.
- The final competitor summary must be concise and actionable. It should synthesize the preceding reports rather than re-listing them.

## Boundaries

Do not generate a new Amazon title, Bullet Points, product description, A+ copy, advertising plan, keyword strategy, sales estimate, or unsupported market report.
