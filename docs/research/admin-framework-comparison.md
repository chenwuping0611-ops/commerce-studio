# 后台框架对比与选择

分析日期：2026-08-12
目标：为 AI 电商产品图片 / 视频生成工作台选择主后台承载方式。

候选：

1. AdminJS
2. React Admin
3. Filament

---

## 1. 结论

本项目选择：

```text
NestJS + Express
+
AdminJS
+
自定义 React 页面
+
React Flow Canvas
```

AdminJS 只负责：

- 系统管理入口
- 用户、角色、团队和配置 CRUD
- 模型供应商配置
- 任务和审计日志查询
- 后台导航和基础 Dashboard

以下页面必须使用自定义 React 页面：

- 产品中心
- 产品档案
- SKU 变体
- Product Memory
- Prompt Engine
- 图片生成
- 视频生成
- Canvas
- 生成历史

原因是这些页面不是普通 CRUD，而是工作台、编辑器和异步任务界面。

---

## 2. AdminJS

### 2.1 优点

- Node.js 体系，与 NestJS、TypeScript 和 MySQL 统一。
- 可自动生成资源管理页面。
- 支持自定义组件和自定义页面。
- 适合快速承载系统配置和后台 CRUD。
- 不需要引入 PHP、Laravel 或额外后端语言。

### 2.2 风险

- AdminJS 7 使用 ESM，Nest 集成存在动态导入和模块配置要求。
- 官方 Nest 插件当前只支持 Express，不支持 Fastify。
- `@adminjs/prisma` 当前 peer 依赖覆盖 Prisma 5/6，不覆盖 Prisma 7。
- AdminJS 本身不提供本项目需要的完整业务 RBAC，权限仍需由 Nest API 和 Casbin/Policy 层实现。
- AdminJS 自定义页面需要处理 React、React Flow 和 AdminJS 的打包边界。

### 2.3 使用限制

AdminJS 不得直接成为业务领域层。页面不得绕过 Nest Application Service 直接写表。

首个兼容性验证必须覆盖：

```text
AdminJS 7
  -> @adminjs/nestjs 7
  -> NestJS 11 Express
  -> Prisma 6
  -> MySQL 8.4
```

如果兼容性验证失败，保留 NestJS、Prisma 和 React Flow，后台页面切换到 React Admin，不重写业务服务。

---

## 3. React Admin

### 3.1 优点

- 纯 React 前端框架。
- 自定义路由和自定义页面自然。
- React Flow 嵌入最直接。
- `dataProvider` 可以连接任意 REST、GraphQL 或自定义 API。
- `authProvider` 和 `canAccess` 可以承载前端权限显示。
- 不增加 Node 服务端 AdminJS ESM 适配问题。

### 3.2 缺点

- 它主要是前端管理框架，不是 NestJS 服务端管理后台。
- 所有资源 API、CRUD、表单和系统管理页都需要自己提供。
- 后端 RBAC、审计、数据范围和校验仍然必须自建。
- 需要投入更多前端 CRUD 开发工作。

### 3.3 备用条件

如果 AdminJS 兼容性验证无法在目标版本组合中稳定通过，React Admin 是第一备用方案：

```text
React Admin + 自定义 React 工作台 + React Flow
  -> NestJS REST API
      -> Prisma + MySQL
```

React Admin 不是第二套后端，不能与 AdminJS 同时长期部署。

---

## 4. Filament

### 4.1 优点

- Laravel 生态成熟。
- CRUD、Resource、Policy 和权限能力完整。
- 管理后台开发效率高。
- 适合传统业务管理系统。

### 4.2 缺点

- 后端需要切换到 PHP/Laravel。
- Model Gateway、任务、Canvas API 和 TypeScript 前端之间形成跨语言边界。
- React Flow 需要通过独立 React 页面或混合前端接入。
- 与当前 NestJS、TypeScript 和 Node 规划不一致。
- 2C2G 下同时维护 PHP 运行时和 Node 前端会增加维护面。

### 4.3 结论

不作为本项目主路线。

---

## 5. 对比表

| 维度 | AdminJS | React Admin | Filament |
| --- | --- | --- | --- |
| 后端语言 | Node/TypeScript | 无后端 | PHP/Laravel |
| NestJS 集成 | 有，但需兼容验证 | API 连接 | 跨语言 |
| React Flow 嵌入 | 可行，需自定义页面 | 最自然 | 需要混合集成 |
| 自动 CRUD | 强 | 需要 Data Provider/API | 强 |
| 自定义工作台 | 可行 | 很强 | 需要额外前端 |
| RBAC | 需后端自建 | 需后端自建，前端可接入 | Laravel 侧较完整 |
| 2C2G 体量 | 合适 | 前端静态 + Nest，合适 | 运行时较多 |
| 当前技术栈一致性 | 最高 | 高 | 低 |
| 主要风险 | ESM、Prisma 适配 | CRUD 工作量 | 跨语言维护 |
| 最终角色 | 主方案 | 备用方案 | 排除 |

---

## 6. 许可证

- AdminJS：MIT
- React Admin：MIT
- React Flow：MIT
- NestJS：MIT

每次升级依赖仍需重新检查许可证和传递依赖，不因为主项目使用 MIT 就忽略第三方包的其他许可证。
