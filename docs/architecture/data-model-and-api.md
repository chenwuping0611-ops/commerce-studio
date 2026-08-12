# 数据模型与 API 规划

目标：为 Product Memory、图片/视频任务、Canvas 和 RBAC 建立稳定边界。

---

## 1. 数据域

```text
Identity
  User
  Team
  Role
  Permission
  UserRole
  TeamMember

Product
  Product
  ProductVariant
  ProductAsset
  ProductPlatformLink

Memory
  ProductFact
  BrandMemory
  GenerationRule
  ForbiddenRule
  ProductMemoryVersion
  MemoryExample

Prompt
  PromptTemplate
  PromptVersion
  PromptExecution

Canvas
  CanvasDocument
  CanvasRevision
  CanvasExecution

Generation
  ModelProvider
  ModelProfile
  GenerationTask
  GenerationAttempt
  GenerationAsset
  CostLedger

Governance
  AuditLog
  ApiRequestLog
  SystemSetting
```

---

## 2. 产品中心

### Product

保存：

- 产品名称
- 产品编码
- 品牌
- 类目
- 描述
- 负责人
- 所属团队
- 状态

### ProductVariant

保存：

- 颜色
- SKU
- 尺寸
- 材质
- 变体状态

### ProductAsset

保存：

- 素材 ID
- 产品或变体 ID
- 素材类型
- 视角
- MIME
- 文件大小
- 哈希
- 存储地址
- 审核状态

素材类型：

```text
main
front
back
left
right
top
bottom
detail
scene
turntable
reference
generated
```

大文件只保存元数据和地址，不保存 MySQL BLOB。

---

## 3. Product Memory

Product Memory 必须支持版本化。

一份有效记忆由以下分区组成：

```text
facts
brand_visual
generation_rules
forbidden_rules
prompt_history
success_examples
failure_examples
recent_results
```

提交生成任务时创建不可变快照：

```text
GenerationTask.memoryVersionId
GenerationTask.memorySnapshot
GenerationTask.promptSnapshot
```

这样即使产品记忆后续被修改，也能还原当时使用的规则。

规则优先级：

```text
禁止规则
  > 产品事实
  > 品牌视觉
  > 用户创意
  > 模型默认建议
```

---

## 4. RBAC 与数据范围

权限格式：

```text
resource:action:scope
```

示例：

```text
product:read:own
product:read:team
product:update:own
memory:update:team
generation:create:team
generation:cancel:own
model_config:read:system
model_config:update:system
cost:read:team
audit:read:system
user:manage:system
```

每个业务查询都必须能生成数据范围条件：

```text
own  -> createdBy = currentUser.id
team -> teamId in currentUser.teamIds
system -> administrator policy
```

前端隐藏菜单不能替代后端权限检查。

---

## 5. Canvas 数据

CanvasDocument 保存：

- 文档 ID
- 所属用户或团队
- 产品 ID
- 标题
- 当前版本
- JSON 节点
- JSON 边
- 视口
- 背景设置

CanvasRevision 保存：

- 文档 ID
- 版本号
- 节点和边快照
- 创建人
- 创建时间
- 变更摘要

节点必须使用版本化的业务数据：

```text
node.type
node.version
node.position
node.data
node.data.productId
node.data.memoryVersionId
node.data.promptVersionId
node.data.modelProfileId
```

节点不得保存：

- API Key
- 完整媒体二进制
- 未授权的外部 URL

---

## 6. GenerationTask

任务状态：

```text
created
queued
running
provider_submitted
provider_processing
succeeded
failed
retry_waiting
cancel_requested
cancelled
expired
```

任务必须保存：

- 产品和变体
- Product Memory 快照
- Prompt 快照
- 模型供应商和模型
- 输入素材引用
- 供应商任务 ID
- 当前状态
- 重试次数
- 租约时间
- 下次轮询时间
- 错误码
- 错误摘要
- 完成时间

外部调用不放在数据库事务内。

---

## 7. API 路由

### Identity

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
GET  /api/v1/auth/permissions
```

### Product

```text
GET    /api/v1/products
POST   /api/v1/products
GET    /api/v1/products/:id
PATCH  /api/v1/products/:id
GET    /api/v1/products/:id/variants
POST   /api/v1/products/:id/variants
POST   /api/v1/products/:id/assets
```

### Memory and Prompt

```text
GET  /api/v1/products/:id/memory
PUT  /api/v1/products/:id/memory
GET  /api/v1/products/:id/memory/versions
POST /api/v1/prompt/preview
POST /api/v1/prompt/compile
```

### Generation

```text
POST /api/v1/generation-tasks
GET  /api/v1/generation-tasks
GET  /api/v1/generation-tasks/:id
POST /api/v1/generation-tasks/:id/cancel
POST /api/v1/generation-tasks/:id/retry
```

### Canvas

```text
GET   /api/v1/canvas
POST  /api/v1/canvas
GET   /api/v1/canvas/:id
PATCH /api/v1/canvas/:id
POST  /api/v1/canvas/:id/revisions
POST  /api/v1/canvas/:id/execute
```

### Long connection and media

```text
GET /events/generation/:taskId
GET /media/:assetId
POST /api/v1/providers/:id/webhook
```

---

## 8. 事件

事件统一使用：

```text
eventId
eventType
requestId
taskId
version
occurredAt
data
```

任务事件：

```text
generation.created
generation.queued
generation.started
generation.provider_submitted
generation.progress
generation.succeeded
generation.failed
generation.cancelled
```

SSE 只发送状态和元数据，客户端断线后必须重新从 API 查询任务状态。
