# Skill 配置格式

Skill 是可复用的图片或视频创作方法。它不保存 API Key，也不替代产品记忆；生成时会在服务端把 Skill Prompt 与产品资料、产品记忆和用户创意合并。

## JSON 示例

```json
{
  "name": "高级电商主图",
  "code": "commerce-product-hero",
  "mediaType": "IMAGE",
  "version": "1.0.0",
  "description": "适用于产品主图、白底图和棚拍视觉",
  "tags": ["电商主图", "棚拍", "高级感"],
  "promptTemplate": "商业棚拍，主体居中，柔和侧光，保留真实材质，画面干净，适合商品详情页首屏",
  "negativePrompt": "禁止出现其他品牌 Logo，禁止改变产品结构，禁止添加未授权配件",
  "settings": {
    "recommendedAspectRatios": ["1:1", "4:5"],
    "suggestedCount": 1
  }
}
```

## 字段约束

- `mediaType`：`IMAGE`、`VIDEO` 或 `BOTH`
- `promptTemplate`：会追加到生成 Prompt
- `negativePrompt`：会与产品记忆的禁止规则合并
- `settings`：给前端和后续模型适配器使用的非敏感参数
- `tags`：用于团队识别和后续筛选

导入支持单个 JSON 对象，也支持 JSON 对象数组。导入后可以在系统配置的 Skill 配置中心停用或重新启用，并在图片创作、视频创作页面选择。
