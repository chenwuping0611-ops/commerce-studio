# commerce-studio 最终技术选型

状态：已接受
决策日期：2026-08-12
适用范围：第一阶段到 2C2G 内部生产版本

---

## 1. 最终架构

```text
浏览器
  |
  v
Nginx
  |
  +-- /admin/*   -> AdminJS
  +-- /api/v1/*  -> NestJS REST API
  +-- /events/*  -> NestJS SSE
  +-- /media/*   -> 授权媒体流
  +-- /health/*  -> 健康检查
  |
  v
NestJS 模块化单体（Express）
  |
  +-- Auth / RBAC / Teams
  +-- Product Center
  +-- Product Memory
  +-- Prompt Engine
  +-- Model Gateway
  +-- Generation Task
  +-- Canvas API
  +-- Assets / History / Cost / Audit
  |
  +-- Prisma 6
  +-- MySQL 8.4 LTS
  +-- 单 Worker / MySQL 任务表
  +-- 外部图片/视频模型 API
```

浏览器端：

```text
React 18.3.x
  +-- AdminJS 自定义页面
  +-- React Flow @xyflow/react 12.11.x
  +-- Zustand（仅 UI 和交互状态）
```

---

## 2. 版本基线

| 组件 | 基线 |
| --- | --- |
| OS | AlmaLinux 9 或 Rocky Linux 9 |
| Node.js | 24 LTS |
| NestJS | 11.1.x |
| Express Adapter | `@nestjs/platform-express` 11.1.x |
| AdminJS | 7.8.17 |
| AdminJS Nest | 7.0.0 |
| AdminJS Express | 6.1.x |
| AdminJS Prisma | 5.0.4 |
| Prisma | 6.19.2 |
| React | 18.3.1 |
| React DOM | 18.3.1 |
| React Flow | `@xyflow/react` 12.11.x |
| Database | MySQL 8.4 LTS |
| Proxy | Nginx |

版本策略：

- 开发时锁定精确版本和 lockfile。
- 不使用 `latest`。
- Node 26 进入 LTS 前不作为生产基线。
- Prisma 暂不升级到 7，除非 `@adminjs/prisma` 已正式支持 Prisma 7，或 AdminJS 适配层被移除。
- `@xyflow/react` 使用新包名，不使用旧 `reactflow`。

---

## 3. 为什么不直接 Fork infinite-canvas

`infinite-canvas` 的高价值是前端创作体验，不是服务端业务架构。

保留设计思想：

- 无限画布和视口变换
- 媒体节点和 Prompt 节点
- 节点工具栏
- 上下游资源引用
- Canvas Ops
- 插件 Host API 的边界思想

不直接迁移：

- 浏览器 API Key
- 浏览器直连模型
- IndexedDB 作为业务主存储
- 浏览器视频轮询
- 远程任意 JavaScript 插件
- 本地 Codex/MCP Agent 服务

主项目 Canvas 使用 React Flow，重写为 Product、Memory、Prompt、Model、Image、Video 和 Result 业务节点。

---

## 4. 为什么不部署 Dify/Flowise

Dify 和 Flowise继续作为：

- Prompt/RAG/Workflow 设计参考
- Agent/Memory 设计参考
- 后续复杂编排的比较对象

第一阶段不作为常驻生产服务，因为本项目只需要：

```text
产品
  -> 产品记忆
  -> Prompt Engine
  -> 模型网关
  -> 图片/视频任务
```

引入完整 AI 编排平台会增加运行时、升级和故障面。

---

## 5. 模型网关决策

第一阶段不嵌入 One API 或 New API 作为业务后台。

直接在 NestJS 内实现：

```text
ModelGateway
  +-- NativeProviderAdapter
  +-- OpenAICompatibleAdapter
  +-- ImageProviderAdapter
  +-- VideoProviderAdapter
```

网关统一负责：

- API Key 加密
- Base URL
- 模型能力
- 模型路由
- 超时和重试
- 供应商任务 ID
- Webhook/轮询
- 结果下载
- 供应商用量
- 成本记录

未来如果渠道数量和并发明显增长，可以单独部署 One API 作为外部渠道层，但业务系统仍保留自己的模型能力、成本和权限模型。

---

## 6. 后台页面分工

### AdminJS 自动资源

- 用户
- 角色
- 小组
- 权限
- 模型供应商
- 模型配置
- 系统参数
- 任务记录
- 审计日志

### 自定义 React 页面

- 产品中心
- 产品档案
- SKU 变体
- 产品素材
- Product Memory
- Prompt 生成和预览
- 图片生成
- 视频生成
- Canvas
- 生成历史
- 成本统计

所有自定义页面都调用 Nest API，不直接调用 Prisma。

---

## 7. 兼容性闸门

进入业务开发前必须通过：

1. AdminJS 在 NestJS Express 下可启动。
2. AdminJS 登录和会话正常。
3. AdminJS Prisma 资源可读取和写入 MySQL。
4. 自定义 React 页面可以加载 React Flow。
5. React Flow 自定义节点、边和视口可保存。
6. `npm run build` 和生产模式启动成功。
7. Nginx 可以转发 `/admin`、`/api`、`/events` 和 `/media`。
8. 2C2G 下启动后内存有可用余量。

任何一项失败，先修复兼容层，不进入业务功能堆叠。
