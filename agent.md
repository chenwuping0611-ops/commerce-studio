# AI 电商产品图片 / 视频生成工作台长期开发规范

文档状态：长期有效的工程约束  
适用范围：本项目全部源码、接口、数据库、部署文件、测试和运维文档  
目标部署：2C2G 单节点服务器、单节点 MySQL、Nginx 统一入口、外部图片/视频模型 API  
架构类型：模块化单体（Modular Monolith），保留后续拆分为 Worker、Model Gateway 和独立服务的边界  
当前原则：先保证稳定、可定位、可恢复和易维护，再追求并发和复杂抽象

---

## 1. 总体目标

本项目是面向电商运营人员的 AI 产品图片 / 视频生成工作台，不是本地模型运行平台，也不是 ComfyUI 类型的专业参数调试工具。

核心业务链路：

```text
产品资料
  -> 产品事实
  -> 产品记忆
  -> Prompt Engine
  -> 模型网关
  -> 图片/视频生成任务
  -> 结果接收
  -> 历史记录、成本和评分
```

核心使用体验：

```text
选择产品
  -> 输入创意
  -> 自动合并产品记忆
  -> 生成完整 Prompt
  -> 选择图片或视频模型
  -> 提交任务
  -> 查看进度和结果
```

产品必须长期支持：

- 产品中心
- 产品档案
- SKU 和颜色变体
- 多角度产品素材
- 产品记忆
- 品牌视觉记忆
- 生成边界和禁止规则
- Prompt 版本
- AI 图片生成
- AI 视频生成
- 任务中心
- 生成历史
- 成本记录
- RBAC 和数据范围
- Canvas 工作流
- 官方模型 API
- OpenAI 兼容的中转 API
- 审计日志

---

## 2. 不可违反的工程原则

### 2.1 资源约束

2C2G 是当前最低运行目标，所有新增依赖必须说明：

- 常驻内存占用
- 启动内存占用
- 是否需要额外服务
- 是否需要 GPU
- 是否会增加网络长连接
- 是否会增加磁盘写入
- 2C2G 下的降级方式

默认禁止在第一阶段加入：

- Kubernetes
- Kafka
- Dify 常驻服务
- Flowise 常驻服务
- ComfyUI 常驻服务
- 本地模型推理服务
- 多数据库集群
- 不必要的微服务

### 2.2 模块化单体优先

第一阶段使用一个代码仓库和一个主要应用，不拆成多个业务微服务。

允许独立运行的进程只有：

1. Nginx
2. NestJS API/AdminJS 应用
3. 可选的任务 Worker
4. MySQL

2C2G 部署默认将任务执行器合并在 NestJS 应用内；升级到 4C8G 后，再拆成独立 Worker。

所有模块必须通过明确的接口访问，不能因为当前是单体就直接互相读取数据库表。

### 2.3 业务规则不能放在控制器和页面

以下位置不得直接编写业务规则：

- Controller
- AdminJS 页面组件
- React Flow 节点组件
- Nginx 配置
- 数据库触发器

业务规则必须位于 Application Service、Domain Service 或 Policy 中。

### 2.4 所有外部调用都必须可追踪

每次请求、任务、模型调用、文件下载和权限检查都必须带有：

- `requestId`
- `traceId`
- `userId`
- `taskId`（如果属于异步任务）
- `providerId` 和 `modelId`（如果属于模型调用）

日志中禁止记录：

- API Key
- Cookie
- 密码
- 完整用户隐私信息
- 未脱敏的授权请求头

### 2.5 所有写入都必须考虑幂等性

以下动作必须支持幂等或重复提交保护：

- 创建产品
- 保存产品记忆
- 创建生成任务
- 提交模型请求
- 接收模型回调
- 下载生成结果
- 扣减额度或记录成本
- 取消任务

写入接口优先使用 `Idempotency-Key`。

---

## 3. 技术基线

### 3.1 操作系统

首选：

- AlmaLinux 9
- Rocky Linux 9

如果服务器必须使用 CentOS，应明确使用 CentOS Stream 9，并在项目文档中记录迁移计划。

禁止依赖发行版中的过旧 Node、MySQL、Nginx 版本。运行时版本必须显式锁定。

### 3.2 应用运行时

- Node.js：LTS 版本
- TypeScript：严格模式
- NestJS：使用 Express 适配器
- AdminJS：用于后台壳、权限入口、系统 CRUD 和自定义页面
- React：用于 AdminJS 自定义页面和 Canvas 页面
- React Flow：用于 Canvas 节点、连线、视口和交互
- ORM：Prisma
- 数据库：MySQL 8.4 LTS
- 反向代理：Nginx
- 任务队列：2C2G 先使用 MySQL 持久化任务表；扩容后使用 BullMQ + Redis

AdminJS 只作为后台承载层，不作为全部业务逻辑层。

### 3.3 依赖版本规则

所有生产依赖必须：

- 固定主版本和次版本范围
- 提交锁文件
- 记录安装时间和升级原因
- 升级前通过兼容性测试
- 升级后执行完整冒烟测试

禁止：

- 生产环境直接安装 `latest`
- 未审查的自动升级
- 运行时从 CDN 加载核心依赖
- 在业务代码中依赖未锁定的隐式传递依赖

AdminJS、NestJS、Prisma 和 React Flow 的组合必须在项目早期做一次版本兼容性验证，尤其不能默认认为 AdminJS 的 Prisma 适配器永远与最新 Prisma 兼容。

---

## 4. 总体部署架构

### 4.1 2C2G 基线架构

```text
Internet
   |
   v
Nginx
   |
   +-- /admin/*  -> NestJS + AdminJS
   +-- /api/*    -> NestJS API
   +-- /events/* -> SSE 事件接口
   +-- /media/*  -> 授权后的媒体文件
   |
   v
NestJS 模块化单体
   |
   +-- Auth / RBAC
   +-- Product Center
   +-- Product Memory
   +-- Prompt Engine
   +-- Model Gateway
   +-- Generation Task
   +-- Canvas
   +-- History / Cost
   +-- Audit
   |
   +-- MySQL
   +-- 本地媒体目录
   +-- 外部图片/视频 API
```

### 4.2 2C2G 运行模式

默认运行一个 Node.js 进程，内部包含：

- HTTP API
- AdminJS
- SSE 事件通道
- 任务轮询器
- 单任务执行器

约束：

- 同时只执行一个生成任务
- 外部 API 调用必须异步化
- 生成任务不能占用 HTTP 请求生命周期
- 任务状态必须先落 MySQL，再执行外部调用
- 进程重启后可以从 MySQL 恢复未完成任务

### 4.3 未来扩容模式

当升级到 4C8G 或更高配置后，允许拆分：

```text
Nginx
  +-- API/AdminJS
  +-- Worker
  +-- MySQL
  +-- Redis/BullMQ
```

拆分时不得修改业务接口，只替换 `TaskQueue` 实现。

---

## 5. 推荐目录结构

目录结构以业务边界为中心，不以数据库表数量为中心。

```text
/
├─ agent.md
├─ package.json
├─ package-lock.json
├─ tsconfig.json
├─ nest-cli.json
├─ prisma/
│  ├─ schema.prisma
│  ├─ migrations/
│  └─ seed/
├─ src/
│  ├─ main.ts
│  ├─ app.module.ts
│  ├─ common/
│  │  ├─ config/
│  │  ├─ errors/
│  │  ├─ logger/
│  │  ├─ http/
│  │  ├─ database/
│  │  ├─ storage/
│  │  ├─ security/
│  │  └─ types/
│  ├─ modules/
│  │  ├─ auth/
│  │  ├─ users/
│  │  ├─ rbac/
│  │  ├─ teams/
│  │  ├─ products/
│  │  ├─ product-memory/
│  │  ├─ prompts/
│  │  ├─ canvas/
│  │  ├─ model-gateway/
│  │  ├─ generation/
│  │  ├─ assets/
│  │  ├─ history/
│  │  ├─ billing/
│  │  ├─ audit/
│  │  └─ system/
│  ├─ admin/
│  │  ├─ admin.config.ts
│  │  ├─ auth/
│  │  ├─ resources/
│  │  ├─ pages/
│  │  └─ components/
│  ├─ workers/
│  │  ├─ generation.worker.ts
│  │  ├─ task.recovery.ts
│  │  └─ task.scheduler.ts
│  └─ integrations/
│     ├─ providers/
│     ├─ webhooks/
│     └─ downloaders/
├─ contracts/
│  ├─ dto/
│  ├─ events/
│  └─ proto/
├─ test/
│  ├─ unit/
│  ├─ integration/
│  ├─ contract/
│  └─ e2e/
├─ docs/
│  ├─ architecture/
│  ├─ api/
│  ├─ runbooks/
│  └─ decisions/
└─ ops/
   ├─ nginx/
   ├─ systemd/
   ├─ backup/
   └─ scripts/
```

每个业务模块至少包含：

```text
module.ts
controller.ts
application/
domain/
infrastructure/
dto/
types.ts
errors.ts
policy.ts
*.spec.ts
```

---

## 6. 函数和功能边界规范

### 6.1 Controller

Controller 只负责：

- 接收 HTTP 参数
- 校验 DTO
- 注入当前用户
- 调用 Application Service
- 转换响应

Controller 禁止：

- 直接访问 Prisma
- 直接调用模型供应商
- 拼接 Prompt
- 写权限判断
- 修改多个业务表
- 编写重试逻辑

### 6.2 Application Service

Application Service 表示一个完整用例，例如：

- `createProduct`
- `updateProductProfile`
- `saveProductMemory`
- `generatePrompt`
- `createGenerationTask`
- `cancelGenerationTask`
- `retryGenerationTask`
- `receiveProviderCallback`
- `recordGenerationCost`

一个用例函数必须：

- 只处理一个业务动作
- 明确输入和输出
- 明确事务边界
- 明确权限要求
- 明确是否幂等
- 明确是否会调用外部服务
- 明确失败后是否可重试

### 6.3 Domain Service

Domain Service 只放与业务规则相关的逻辑，例如：

- 合并产品事实和产品记忆
- 判断禁止规则是否冲突
- 计算有效 Prompt
- 校验 SKU 视觉素材完整度
- 判断生成结果是否属于当前产品
- 计算任务状态是否允许转换

Domain Service 不得访问 HTTP、Nginx、Prisma Client 或外部 API。

### 6.4 Repository

Repository 只负责数据库读写：

- `findProductById`
- `listProductVariants`
- `saveProductMemoryVersion`
- `createGenerationTask`
- `claimNextGenerationTask`
- `markTaskSucceeded`
- `markTaskFailed`

Repository 不得：

- 调用模型 API
- 发送通知
- 判断当前用户是否有权限
- 拼接业务 Prompt

### 6.5 Adapter

所有外部系统必须通过 Adapter 接入：

- `ImageProviderAdapter`
- `VideoProviderAdapter`
- `OpenAICompatibleAdapter`
- `FileStorageAdapter`
- `NotificationAdapter`
- `TaskQueueAdapter`

业务模块只能依赖 Adapter 接口，不能依赖具体供应商 SDK。

### 6.6 函数注释模板

所有公共函数、外部调用函数、任务函数和复杂领域函数必须使用类似以下注释：

```ts
/**
 * 目的：创建一个带产品记忆快照的图片生成任务。
 * 输入：用户、产品、创意描述、模型配置、幂等键。
 * 输出：持久化后的 GenerationTask。
 * 业务错误：产品不存在、无权限、模型不支持图片生成。
 * 外部副作用：无；本函数只创建任务，不直接调用模型。
 * 幂等性：相同用户和 Idempotency-Key 只返回同一个任务。
 * 事务：产品校验、Prompt 快照和任务创建必须在同一事务中完成。
 * 重试：数据库死锁可重试；业务校验错误不可重试。
 */
```

注释重点描述决策、边界和副作用，不写无意义的逐行翻译。

---

## 7. API 设计规范

### 7.1 入口

统一使用：

```text
/api/v1/*
/admin/*
/events/*
/media/*
/health/*
```

禁止业务接口直接暴露在根路径。

### 7.2 API 类型

查询接口：

- `GET /api/v1/products`
- `GET /api/v1/products/:id`
- `GET /api/v1/generation-tasks/:id`

命令接口：

- `POST /api/v1/products`
- `POST /api/v1/products/:id/memory`
- `POST /api/v1/generation-tasks`
- `POST /api/v1/generation-tasks/:id/cancel`
- `POST /api/v1/generation-tasks/:id/retry`

命令接口必须经过：

```text
认证
  -> RBAC
  -> 数据范围
  -> DTO 校验
  -> 幂等检查
  -> 业务事务
  -> 任务或事件创建
```

### 7.3 响应格式

成功响应：

```text
{
  "data": {},
  "meta": {
    "requestId": "...",
    "nextCursor": null
  }
}
```

错误响应：

```text
{
  "error": {
    "code": "GENERATION_TASK_NOT_FOUND",
    "message": "任务不存在",
    "details": {}
  },
  "requestId": "..."
}
```

错误码必须稳定，前端不得根据中文错误消息判断业务。

### 7.4 接口文档

所有 JSON/HTTP 接口必须维护 OpenAPI 文档，至少包含：

- 请求方法和路径
- 认证方式
- 请求参数和字段约束
- 成功响应示例
- 错误码和错误响应
- 是否幂等
- 是否触发异步任务
- 是否需要数据范围
- 兼容性说明

Protobuf 接口必须同时维护：

- `.proto` schema
- 字段说明
- 版本兼容说明
- 生成客户端版本
- 二进制请求和响应示例

### 7.5 分页、排序和过滤

- 默认使用游标分页。
- 列表接口必须限制最大返回条数。
- 不允许无条件查询全表。
- 所有高频筛选字段必须建立索引。
- 排序字段必须使用白名单。
- 查询条件必须经过 DTO 校验。

### 7.6 时间和 ID

- 所有服务端时间使用 UTC 保存。
- API 返回 ISO 8601 时间。
- 不在数据库中保存本地化时间字符串。
- ID 统一由服务端生成。
- 日志、任务、文件和审计记录必须能通过 ID 互相定位。

---

## 8. Protobuf、JSON 和压缩策略

### 8.1 总体原则

协议选择必须以接口为单位，不允许全项目强制一种协议。

优先级：

1. 稳定、可调试、可兼容
2. 正确的压缩和缓存
3. 减少传输体积
4. 再考虑极限序列化性能

### 8.2 Protobuf 使用条件

满足以下条件时才使用 Protobuf：

- 数据结构稳定
- 字段数量较多
- 接口调用频繁
- 能维护 `.proto` 文件
- 能为浏览器生成并锁定客户端类型
- 已有兼容性测试
- 错误处理和调试链路已经确定

适合 Protobuf 的场景：

- 后续独立 Worker 与 API 的内部通信
- 大批量结构化任务事件
- 稳定的模型网关内部协议
- 高调用频率的结构化接口

### 8.3 JSON 使用条件

以下场景默认使用 JSON：

- AdminJS CRUD
- 产品中心
- 产品记忆
- Prompt 编辑
- React Flow Canvas 数据
- 系统设置
- RBAC 管理
- SSE 事件
- 调试接口
- 结构经常变化的接口

原因：

- 浏览器兼容性更好
- AdminJS 和 React 生态默认支持
- 便于排查问题
- 动态字段和版本兼容成本更低
- SSE 使用文本事件更简单

JSON 接口必须支持：

- HTTPS
- Nginx gzip
- 可选 Brotli
- ETag 或 Last-Modified
- 游标分页
- 字段裁剪
- 缩略图和懒加载

图片和视频本体禁止转换为 JSON 或 Base64 传输，必须使用文件流或对象存储地址。

浏览器端不直接使用裸 gRPC。需要浏览器访问 Protobuf 时，使用普通 HTTPS 二进制请求，并明确：

```text
Content-Type: application/protobuf
Accept: application/protobuf
Content-Encoding: gzip（如果启用压缩）
```

如果浏览器客户端生成、错误调试、Nginx 代理或 AdminJS 集成出现兼容问题，立即回退为 JSON + gzip，不为了协议形式增加额外网关。

单体应用内部直接调用函数，不为了 Protobuf 引入内部 RPC。

### 8.4 协议版本

Protobuf：

- `.proto` 文件必须进入版本控制。
- 新字段必须向后兼容。
- 不得重用已删除字段编号。
- 不得随意修改字段类型。
- 需要保留旧版本读取能力。

JSON：

- 新增字段默认向后兼容。
- 删除字段前至少经过一个兼容周期。
- 修改字段含义必须升级 API 版本或增加新字段。

---

## 9. Nginx 统一入口规范

所有外部访问必须经过 Nginx，Node、MySQL 和 Redis 不得直接暴露公网。

### 9.1 路由规划

```text
/admin/       AdminJS 页面
/api/         REST API
/events/      SSE 事件
/media/       授权媒体访问
/health/live  进程存活检查
/health/ready 依赖就绪检查
```

### 9.2 Nginx 职责

- TLS 终止
- HTTP/2 或 HTTP/1.1 管理
- 静态文件缓存
- gzip JSON 压缩
- 上传大小限制
- 连接超时
- 登录和生成接口限流
- 请求 ID 转发
- SSE 长连接转发
- WebSocket 备用转发
- 访问日志和错误日志

### 9.3 长连接规则

生成任务不允许使用一个持续几十分钟的 HTTP 请求等待模型完成。

推荐：

```text
提交任务 -> 返回 taskId
浏览器 -> SSE 或短轮询
Worker -> 调用供应商
Worker -> 更新 MySQL
SSE -> 推送任务状态
```

SSE 规则：

- 事件接口单独使用 `/events/` 路径。
- 禁止代理缓存事件。
- Nginx 必须关闭该路径的代理缓冲和缓存。
- Nginx 必须返回 `X-Accel-Buffering: no` 或等效配置。
- `proxy_read_timeout` 必须大于心跳间隔和允许的空闲时间。
- 发送心跳，防止中间设备断开。
- 支持浏览器自动重连。
- 支持 `Last-Event-ID`。
- SSE 只发送任务状态和结果元数据，不发送大文件。
- 连接断开后以 MySQL 中的任务状态为准。

WebSocket 只在需要双向实时协作时使用，例如多人同时编辑 Canvas。当前单用户 Canvas 默认不使用 WebSocket。

如果以后启用 WebSocket：

- 只开放 `/ws/` 路径。
- Nginx 必须正确转发 `Upgrade` 和 `Connection` 头。
- 必须有连接数上限。
- 必须有心跳和空闲断开。
- 必须在握手阶段完成认证和权限检查。
- WebSocket 断开后，客户端仍以 MySQL 持久化状态为准。

外部模型连接规则：

- 提交请求使用连接池和 HTTP Keep-Alive。
- 连接超时、响应头超时、下载超时分别设置。
- 默认连接超时 5 秒。
- 普通提交请求超时 30 秒。
- 大文件下载使用流式处理。
- 429、网络错误和 5xx 才允许重试。
- 4xx 业务错误默认不重试。
- 非幂等请求重试前必须确认供应商支持幂等键。
- 优先使用供应商 Webhook；没有 Webhook 时使用定时轮询。
- 轮询必须有最大次数和最大持续时间。

---

## 10. 认证、RBAC 和数据权限

### 10.1 角色

初始角色：

- `super_admin`
- `team_lead`
- `employee`
- `visitor`

### 10.2 权限模型

权限至少包含：

```text
resource
action
scope
```

例如：

```text
product:read:team
product:update:own
generation:create:team
model_config:update:system
cost:read:team
user:manage:system
```

### 10.3 强制要求

- 页面隐藏不是权限控制。
- Controller 和 Application Service 必须再次校验权限。
- 数据库查询必须带数据范围条件。
- 产品、SKU、素材、任务、Canvas 和历史记录都必须验证归属。
- 系统管理员操作必须写审计日志。
- API Key 只能由授权管理员查看脱敏信息。
- API Key 绝不能发送到浏览器。
- Cookie 使用 HttpOnly、Secure 和合理的 SameSite。
- 使用 Cookie 认证时，写操作必须有 CSRF 防护。

---

## 11. 产品中心和 Product Memory

### 11.1 产品数据边界

建议核心实体：

- `User`
- `Role`
- `Permission`
- `Team`
- `Product`
- `ProductVariant`
- `ProductAsset`
- `ProductFact`
- `BrandMemory`
- `GenerationRule`
- `ForbiddenRule`
- `PromptVersion`
- `CanvasDocument`
- `GenerationTask`
- `GenerationAttempt`
- `GenerationAsset`
- `ModelProvider`
- `ModelProfile`
- `CostLedger`
- `AuditLog`

### 11.2 Product Memory 分层

产品记忆必须拆分保存：

1. 产品事实
2. 品牌和视觉记忆
3. 生成边界
4. 禁止修改规则
5. 历史 Prompt
6. 成功案例
7. 失败案例
8. 最近生成结果

每次生成必须保存不可变的 Product Memory 快照，不能只保存一个当时会继续变化的产品 ID。

### 11.3 SKU 防跑偏

每个 SKU 或颜色变体可以关联：

- 主图
- 前视图
- 后视图
- 左视图
- 右视图
- 上视图
- 下视图
- 细节图
- 场景图
- 360 度视频

Prompt Engine 只能引用已授权的素材。

产品规则优先级：

```text
禁止规则
  > 产品事实
  > 品牌记忆
  > 用户创意
  > 模型默认建议
```

冲突时必须保留冲突原因，并返回可读的错误码。

---

## 12. Model Gateway 规范

业务页面不允许直接调用任何官方模型或中转站 API。

统一经过：

```text
ModelGateway
  -> ProviderAdapter
      -> NativeProviderAdapter
      -> OpenAICompatibleAdapter
      -> ImageProviderAdapter
      -> VideoProviderAdapter
```

### 12.1 必备函数边界

```text
registerProvider()
validateProviderConfig()
listAvailableModels()
resolveModelProfile()
buildPromptSnapshot()
createImageGenerationTask()
createVideoGenerationTask()
submitProviderTask()
pollProviderTask()
receiveProviderWebhook()
cancelProviderTask()
downloadProviderAsset()
recordProviderUsage()
calculateGenerationCost()
```

每个供应商必须有独立 Adapter，不允许在业务服务中出现供应商名称判断。

### 12.2 统一任务状态

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

状态转换必须通过一个状态机函数完成：

```text
canTransitionTaskState()
transitionTaskState()
```

禁止在多个文件中直接修改任务状态字符串。

### 12.3 API Key

- 数据库只保存加密后的密钥。
- 页面只显示脱敏后的密钥。
- 日志必须自动脱敏。
- 供应商请求只在服务端发起。
- 更换密钥要写审计日志。
- 删除供应商前必须检查是否存在未完成任务。

---

## 13. 2C2G 任务系统

2C2G 默认不部署 Redis，先使用 MySQL 持久化任务表。

### 13.1 任务表必须保存

- 任务 ID
- 用户 ID
- 产品 ID
- Prompt 快照
- Product Memory 快照
- 模型供应商
- 模型名称
- 输入参数
- 输出结果
- 当前状态
- 重试次数
- 最大重试次数
- 租约时间
- 心跳时间
- 下次执行时间
- 错误码
- 错误摘要
- 创建时间
- 完成时间

### 13.2 Worker 规则

- 单 Worker。
- 单任务并发。
- 任务先落库，再调用外部 API。
- Worker 启动时恢复过期租约。
- 外部请求必须有超时。
- 任务失败必须保存原因。
- 任务完成必须保存供应商原始任务 ID。
- 回调和轮询必须幂等。
- 进程重启不能丢任务。

### 13.3 后续升级

当需要并发任务时，新增 `TaskQueueAdapter` 的 BullMQ 实现：

```text
DatabaseTaskQueue
BullMqTaskQueue
```

业务模块只依赖：

```text
enqueue()
claim()
acknowledge()
retry()
cancel()
recoverExpired()
```

---

## 14. Canvas 规范

Canvas 使用 React Flow，但 Canvas 不直接执行模型请求。

### 14.1 节点类型

第一阶段允许：

- `Product`
- `Memory`
- `Prompt`
- `Structure`
- `Model`
- `Image`
- `FirstFrame`
- `Duration`
- `Video`
- `Stitch`
- `Result`
- `BatchTask`
- `Watermark`

### 14.2 节点职责

每个节点必须包含：

- 节点类型
- 节点版本
- 输入端口
- 输出端口
- 配置数据
- 校验状态
- 权限要求
- 可执行状态

节点组件只负责：

- 展示
- 输入编辑
- 连接端口
- 展示校验状态

Canvas 执行必须经过：

```text
validateCanvas()
compileCanvas()
createExecutionSnapshot()
submitCanvasTask()
```

### 14.3 保存和版本

- Canvas 草稿自动保存必须防抖。
- 每次正式执行保存不可变快照。
- 节点和边保存为 JSON。
- 不把图片和视频二进制保存到 Canvas JSON。
- Canvas 执行结果必须关联产品、Prompt 和任务 ID。
- 节点版本升级时必须提供兼容读取策略。

---

## 15. 数据库规范

- 字符集统一使用 `utf8mb4`。
- 时间统一使用 UTC。
- 业务表必须有创建时间和更新时间。
- 重要表必须有软删除或归档策略。
- 生成历史和审计日志原则上不可物理删除。
- 大文件不存 MySQL BLOB。
- JSON 字段只保存不适合拆列的配置，不得把整张业务表塞进 JSON。
- 所有外键和高频查询字段建立索引。
- 迁移文件必须进入版本控制。
- 生产环境只执行正式 migration。
- 禁止生产环境使用自动同步表结构。
- 任何破坏性迁移必须先做兼容迁移，再清理旧字段。

### 15.1 事务边界

一个事务只处理一个明确业务用例：

```text
校验产品
  -> 创建 Prompt 快照
  -> 创建生成任务
  -> 写入审计记录
```

外部模型 API 调用不得放在数据库事务中。

### 15.2 连接管理

- 使用单一 Prisma Client。
- 使用连接池。
- 启动时检查数据库连接。
- 关闭时优雅释放连接。
- API 请求不得自行创建和销毁数据库连接。
- 数据库异常必须转换为稳定错误码。

---

## 16. 文件和媒体规范

媒体存储分为：

```text
数据库：元数据、权限、哈希、尺寸、MIME、来源、任务 ID
文件系统/对象存储：图片、视频、缩略图、原始下载文件
```

必须保存：

- 文件 ID
- 文件哈希
- MIME 类型
- 文件大小
- 存储地址
- 所属产品
- 所属任务
- 创建用户
- 可见范围

禁止：

- 使用 Base64 长期保存图片和视频。
- 通过数据库传输大文件。
- 直接暴露真实文件系统路径。
- 允许用户提交任意路径。
- 没有 MIME 和大小校验就保存上传文件。

下载流程：

```text
认证
  -> 数据权限
  -> 文件权限
  -> 生成授权地址或内部转发
  -> 流式下载
```

---

## 17. 日志、错误和可观测性

### 17.1 日志级别

- `debug`：开发环境使用
- `info`：正常业务事件
- `warn`：可恢复异常
- `error`：请求或任务失败
- `fatal`：进程无法继续运行

生产环境默认使用 `info`，禁止长期打开完整 `debug`。

### 17.2 结构化日志字段

至少包含：

```text
timestamp
level
service
requestId
traceId
userId
module
action
taskId
providerId
modelId
durationMs
status
errorCode
```

### 17.3 错误分类

```text
AUTH_*
RBAC_*
PRODUCT_*
MEMORY_*
PROMPT_*
CANVAS_*
MODEL_*
GENERATION_*
STORAGE_*
DATABASE_*
SYSTEM_*
```

错误必须区分：

- 用户输入错误
- 权限错误
- 数据不存在
- 外部供应商错误
- 网络超时
- 数据库错误
- 系统内部错误

外部供应商原始错误只进入内部日志，返回给用户的内容必须脱敏和稳定。

### 17.4 健康检查

```text
/health/live
/health/ready
```

`live` 只检查进程是否存活。  
`ready` 检查 MySQL、必要配置和任务执行能力。

---

## 18. 性能规范

### 18.1 2C2G 内存预算

目标预算：

```text
系统和 Nginx       400-600MB
NestJS/AdminJS     400-600MB
任务执行器         250-400MB
MySQL              300-500MB
预留空间           300-500MB
```

禁止内存无界增长：

- 列表接口禁止一次返回全部记录。
- 任务日志必须分页。
- Prompt 和 Canvas 需要限制大小。
- 文件下载使用流式传输。
- 图片预览使用缩略图。
- 不把视频完整读入内存。
- 不在内存中长期缓存所有产品和历史记录。

### 18.2 数据库性能

- 所有分页有上限。
- 所有列表查询必须检查执行计划。
- 产品、任务、用户、时间和状态字段建立合适索引。
- 慢查询必须记录。
- 不在请求循环中执行 N+1 查询。
- 复杂统计可以异步生成。

### 18.3 网络性能

- API 使用 HTTP Keep-Alive。
- 外部供应商连接使用连接池。
- JSON 使用 gzip。
- 图片和视频不使用 gzip。
- 文件传输使用流。
- 大响应必须分页或异步导出。
- 前端只请求当前页面所需字段。

---

## 19. AdminJS 和业务页面规范

AdminJS 页面分为：

1. 系统管理页面
2. 业务工作台页面
3. 只读监控页面

业务页面必须使用 Application API，不得绕过领域服务直接操作数据库。

AdminJS 自定义页面中：

- 页面组件只负责展示和交互。
- 表单提交调用 API。
- 权限由后端返回并再次校验。
- 页面必须处理加载、空数据、错误、无权限和过期状态。
- 长任务必须显示 taskId 和当前状态。
- 不能仅依赖浏览器按钮禁用防止重复提交。

React Flow 页面必须处理：

- 节点加载失败
- 节点配置不完整
- 产品已删除
- 模型不可用
- 权限变化
- Canvas 版本冲突
- 保存失败
- 任务提交失败
- 浏览器断线重连

---

## 20. 测试规范

每个新功能至少包含：

### 20.1 单元测试

测试：

- Domain Service
- 状态机
- Prompt 合并规则
- 权限策略
- Provider Adapter 参数转换
- 重试判断
- 成本计算

### 20.2 集成测试

测试：

- MySQL 读写
- 事务
- 任务租约
- 任务恢复
- 文件存储
- Webhook 幂等
- RBAC 数据范围

### 20.3 契约测试

每个模型供应商必须测试：

- 正常响应
- 429
- 4xx
- 5xx
- 超时
- 空结果
- 重复回调
- 结果下载失败

### 20.4 端到端测试

至少覆盖：

```text
登录
  -> 创建产品
  -> 上传素材
  -> 保存产品记忆
  -> 自动生成 Prompt
  -> 创建图片任务
  -> 接收结果
  -> 查看历史
```

### 20.5 发布前测试

- 数据库迁移测试
- Nginx 代理测试
- SSE 断线重连测试
- 文件上传大小测试
- gzip 响应测试
- 权限越权测试
- 任务进程重启恢复测试
- 备份恢复测试

---

## 21. 安全规范

- MySQL 只监听内网或本机。
- Redis（启用后）只监听本机或内网。
- Nginx 是唯一公网入口。
- 所有管理页面使用 HTTPS。
- 密码使用强哈希算法保存。
- API Key 使用应用级加密密钥加密。
- 加密密钥不进入数据库和 Git。
- 上传文件检查扩展名、MIME、大小和实际文件类型。
- 防止 SSRF：模型回调地址和下载地址必须通过白名单。
- 防止 Prompt 中注入系统密钥或内部配置。
- 所有管理员操作写审计日志。
- 登录、生成、上传、回调接口必须限流。
- 错误响应不得泄露 SQL、文件路径和供应商密钥。

---

## 22. 部署规范

### 22.1 进程

2C2G 初始部署：

```text
nginx.service
ai-workbench.service
mysql.service
```

扩容后：

```text
nginx.service
ai-workbench-api.service
ai-workbench-worker.service
mysql.service
redis.service
```

应用必须支持：

- 优雅启动
- 优雅关闭
- 收到停止信号后停止接收新任务
- 等待当前外部请求到达超时或安全终止
- 释放数据库连接
- 输出启动版本和配置摘要

### 22.2 配置

配置分为：

- `development`
- `test`
- `staging`
- `production`

生产配置必须通过环境变量或服务器密钥文件注入。

启动时必须校验：

- 数据库地址
- 数据库密码
- Session/JWT 密钥
- 加密密钥
- 媒体目录
- Nginx 外部地址
- 供应商配置

缺少关键配置时禁止启动。

### 22.3 发布流程

```text
创建分支
  -> 本地测试
  -> CI 检查
  -> 构建产物
  -> 测试环境
  -> 备份生产数据
  -> 执行兼容迁移
  -> 发布应用
  -> 重启服务
  -> 冒烟测试
  -> 观察日志和任务
```

禁止：

- 直接在生产目录修改源码。
- 直接修改生产表结构。
- 未备份就执行破坏性迁移。
- 未测试就升级核心框架。
- 通过人工 SQL 修复而不记录变更。

---

## 23. 备份和恢复

至少备份：

- MySQL 数据库
- 生成任务记录
- 产品记忆
- Canvas 文档
- Prompt 版本
- 审计日志
- 图片和视频文件
- 生产配置模板（不包含明文密钥）

策略：

- 每日数据库备份。
- 每日媒体增量备份。
- 保留最近 7 天快速恢复副本。
- 保留最近 4 周归档副本。
- 每月执行一次完整恢复演练。
- 备份失败必须报警。
- 备份文件不能只保存在同一块硬盘。

---

## 24. 版本控制和代码审查

分支：

```text
main
feature/*
fix/*
hotfix/*
```

要求：

- `main` 只能通过合并进入。
- 一个提交只解决一个明确问题。
- 业务变更必须同步更新测试。
- 数据结构变更必须同步迁移文件。
- API 变更必须同步接口文档。
- 新增外部供应商必须同步契约测试。
- 删除字段、权限或状态前必须写迁移说明。

### 24.1 GitHub 仓库

本项目的唯一主远程仓库：

```text
origin = https://github.com/chenwuping0611-ops/commerce-studio.git
```

仓库规则：

- 默认分支为 `main`。
- `main` 是稳定分支，不直接提交业务代码。
- 所有功能从 `feature/*` 创建分支。
- 修复问题使用 `fix/*`。
- 紧急生产修复使用 `hotfix/*`。
- 每个功能完成后先测试，再提交，再推送。
- 推送前必须确认工作区没有密钥、临时文件和媒体文件。
- 禁止对 `main` 使用强制推送。
- 禁止提交 `.env`、`.env.*`、API Key、密码、证书、备份、日志、`node_modules` 和构建缓存。
- 生产配置只能提交脱敏模板，例如 `.env.example`。
- 第三方代码、模型 SDK 和字体必须保留许可证记录。

首次初始化或绑定远程仓库时使用：

```text
git init
git add .
git commit -m "chore: initialize commerce studio"
git branch -M main
git remote add origin https://github.com/chenwuping0611-ops/commerce-studio.git
git push -u origin main
```

如果 `origin` 已存在，先检查远程地址，不重复添加：

```text
git remote -v
git branch -M main
git push -u origin main
```

当前只有规范文件、没有业务代码时，不自动推送空项目。正式开始开发时，首次提交必须包含：

- `agent.md`
- `README.md`
- `.gitignore`
- 项目许可证或许可证决策记录
- 当前阶段的架构说明

### 24.2 提交前检查

每次提交前必须执行：

```text
git status
git diff
依赖安装检查
类型检查
单元测试
构建检查
敏感信息扫描
```

提交信息必须说明：

- 做了什么
- 影响哪些模块
- 是否有数据库迁移
- 是否有 API 兼容性变化
- 是否需要部署配置变化

### 24.3 里程碑推送

以下节点必须单独提交并推送：

1. 工程骨架完成
2. 认证和 RBAC 完成
3. 产品中心完成
4. Product Memory 完成
5. Model Gateway 完成
6. 图片任务完成
7. 视频任务完成
8. Canvas 完成
9. 测试和部署流程完成

里程碑提交必须可以独立构建、启动或明确说明尚未完成的依赖，不允许把无法启动的半成品标记为稳定版本。

提交信息建议：

```text
feat: add product memory versioning
fix: recover expired generation tasks
refactor: isolate provider adapter
test: add webhook idempotency tests
docs: update deployment runbook
```

---

## 25. 维护周期

### 每日

- 检查服务存活。
- 检查失败任务。
- 检查磁盘和媒体目录。
- 检查数据库备份。
- 检查模型供应商错误率。

### 每周

- 查看慢查询。
- 查看任务平均耗时。
- 查看 429 和 5xx。
- 检查 API 成本异常。
- 清理过期临时文件。
- 检查审计日志。

### 每月

- 应用依赖补丁升级。
- 操作系统安全更新。
- 备份恢复演练。
- 权限和管理员账号审计。
- 供应商密钥轮换检查。
- 检查 Nginx 和 TLS 配置。

### 每季度

- 评估是否需要拆分 Worker。
- 评估是否需要 Redis/BullMQ。
- 评估是否需要对象存储。
- 评估 MySQL 索引和数据增长。
- 做一次故障恢复演练。
- 审查第三方许可证和依赖风险。

---

## 26. 扩容触发条件

满足任一条件时，从 2C2G 轻量版升级：

- 任务同时执行数量超过 1。
- 任务队列经常积压超过 10 分钟。
- API 进程内存持续超过 1GB。
- MySQL 内存持续超过 700MB。
- 磁盘使用率超过 70%。
- 活跃用户超过 5～10 人。
- 需要第二个 Worker。
- 需要多实例 API。
- 需要 Redis、缓存或实时协作。

扩容顺序：

```text
2C2G SQLite/单 Worker
  -> 2C4G 单节点 MySQL
  -> 4C8G MySQL + Redis/BullMQ
  -> 独立媒体存储
  -> API 与 Worker 分离
  -> 独立数据库
```

---

## 27. 功能完成标准

一个功能只有同时满足以下条件才算完成：

- 有明确模块归属。
- 有明确的 Controller、Application Service、Repository 或 Adapter 边界。
- 公共函数有职责和副作用说明。
- 有稳定错误码。
- 有权限和数据范围检查。
- 有幂等策略。
- 有日志和 requestId。
- 有单元测试。
- 有集成测试或契约测试。
- 有数据库迁移。
- 有回滚或恢复方案。
- 有接口文档。
- 在 2C2G 环境下完成基本验证。

---

## 28. 当前最终技术路线

```text
模块化 NestJS 单体
  +
AdminJS 后台壳和系统管理
  +
React Flow 自定义 Canvas 页面
  +
Prisma + 单节点 MySQL
  +
MySQL 持久化任务队列
  +
单 Worker / 单任务并发
  +
自建 Model Gateway
  +
官方 API 和 OpenAI 兼容中转 API
  +
Nginx HTTPS 统一入口
```

Dify、Flowise 和 infinite-canvas 继续作为设计参考，不作为 2C2G 生产运行时依赖。

当用户规模、任务并发或数据量增长后，只替换任务队列、存储和进程部署方式，不重写产品中心、Product Memory、Prompt Engine、Canvas 和 Model Gateway。
