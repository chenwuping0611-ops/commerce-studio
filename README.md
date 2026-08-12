# commerce-studio

AI 电商产品图片 / 视频生成工作台。

## 当前阶段

当前仓库已建立长期开发基线，并完成阶段 0 的工程骨架和兼容性验证。当前仍不接入真实模型调用，不把阶段 0 骨架视为完整业务成品。

长期开发规范见：

- [agent.md](./agent.md)
- [最终技术选型](./docs/architecture/stack-decision.md)
- [后台框架对比](./docs/research/admin-framework-comparison.md)
- [数据模型与 API 规划](./docs/architecture/data-model-and-api.md)
- [实施路线](./docs/architecture/implementation-roadmap.md)
- [本地开发运行手册](./docs/runbooks/local-development.md)
- [infinite-canvas 源码分析](./docs/research/infinite-canvas-v0.15.1-analysis.md)

阶段 0 已覆盖：

- NestJS、Prisma、MySQL、AdminJS、React 和 React Flow 的基础组合
- 认证、基础 RBAC、产品、Product Memory、Prompt、Canvas 和生成任务的数据骨架
- 本地直连端口启动、AdminJS、Workbench、Swagger 和健康检查
- MySQL 任务持久化与单 Worker 的基础状态模型

后续阶段仍需实现产品素材完整管理、模型供应商适配、结果媒体持久化、成本记录、完整审计、Canvas 节点执行和生产 Nginx 配置。

## 目标架构

```text
Nginx
  -> NestJS + AdminJS
      -> React Flow Canvas
      -> Product Center
      -> Product Memory
      -> Prompt Engine
      -> Model Gateway
      -> Generation Task
      -> RBAC / Audit
          -> MySQL
          -> 外部图片/视频模型 API
```

目标部署基线：

- 2C2G 单节点服务器
- 单节点 MySQL
- Nginx 统一入口
- 外部图片和视频 API
- MySQL 持久化任务表
- 单 Worker / 单任务并发

扩容后再考虑 BullMQ、Redis、独立 Worker 和对象存储。

## 参考源码

当前指定下载的参考源码：

```text
项目：basketikun/infinite-canvas
版本：v0.15.1
放置目录：references/infinite-canvas-v0.15.1/
```

该源码只作为 Canvas、节点交互、创作流程和视觉工作台的参考。它不直接替代本项目的 NestJS、AdminJS、MySQL、RBAC 和 Model Gateway。

下载源码后，先不要修改、安装依赖或提交构建产物。下一步先进行：

1. 目录结构检查
2. 许可证和第三方依赖核对
3. Canvas 状态和数据结构分析
4. API 调用方式分析
5. 与本项目 MySQL、RBAC 和 Product Memory 的兼容性评估

## 开发约束

所有代码、接口、数据库、部署和维护操作必须遵守 `agent.md`。

## 本地启动

本地开发不安装 MySQL 或 Nginx。应用直接监听端口，数据库通过 `DATABASE_URL` 连接外部 MySQL：

```powershell
$env:DATABASE_URL="mysql://<user>:<password>@<host>:3306/commerce_studio"
$env:DATABASE_REQUIRED="true"
$env:JWT_SECRET="<random-secret>"
$env:APP_ENCRYPTION_KEY="<64-hex-character-key>"
$env:ADMIN_COOKIE_PASSWORD="<random-secret>"
npm.cmd run start:dev
```

访问地址：

- 工作台：`http://127.0.0.1:3000/workbench`
- AdminJS：`http://127.0.0.1:3000/admin`
- API 文档：`http://127.0.0.1:3000/api/docs`
- 存活检查：`http://127.0.0.1:3000/health/live`

首次连接新数据库时执行：

```powershell
npm.cmd run prisma:migrate:deploy
npm.cmd run db:seed
```

当前不提交：

- `.env` 和任何密钥
- 真实模型 API Key
- 生产数据库备份
- 图片、视频和临时媒体文件
- `node_modules`
- 构建缓存和本地日志

## 仓库

主远程仓库：

```text
https://github.com/chenwuping0611-ops/commerce-studio.git
```
