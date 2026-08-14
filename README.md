# commerce-studio

AI 电商产品图片 / 视频生成工作台。

## 当前阶段

当前仓库已完成可本地启动的 2C2G MVP 基线，不把它误认为已经覆盖所有供应商和所有 Canvas 编排能力。
当前实现已经包含登录、RBAC、产品中心、产品素材、Product Memory、Prompt 编译、模型供应商配置、
OpenAI 兼容模型调用、MySQL 异步任务、媒体持久化、SSE、AdminJS 只读后台、自定义系统管理页、
React Flow Canvas 保存和 Docker/Nginx/systemd 部署模板。

长期开发规范见：

- [agent.md](./agent.md)
- [最终技术选型](./docs/architecture/stack-decision.md)
- [后台框架对比](./docs/research/admin-framework-comparison.md)
- [数据模型与 API 规划](./docs/architecture/data-model-and-api.md)
- [实施路线](./docs/architecture/implementation-roadmap.md)
- [本地开发运行手册](./docs/runbooks/local-development.md)
- [infinite-canvas 源码分析](./docs/research/infinite-canvas-v0.15.1-analysis.md)
- [Skill 配置格式](./docs/architecture/skill-format.md)

当前已实现：

- NestJS、Prisma、MySQL、AdminJS、React 和 React Flow 的基础组合
- 登录、退出、当前用户、角色、权限、团队、数据范围和审计基础
- 产品、SKU、产品素材上传/读取/更新/删除、Product Memory 版本和 Prompt 编译
- 模型供应商和 Model Profile 管理、API Key 加密、OpenAI 兼容图片/视频任务适配
- MySQL 持久化任务、单 Worker、租约恢复、重试、结果下载、媒体去重和 SSE 状态推送
- React Flow Canvas 的全屏工作台、节点/连线、保存、版本快照、执行快照、撤销重做和敏感字段过滤
- 本地直连端口启动、AdminJS、Workbench、Swagger 和健康检查
- Docker、Compose、Nginx、systemd、MySQL/媒体备份脚本和 CentOS 7.9 部署手册

## 当前未完成

- 官方原生 Provider Adapter 仍需按具体供应商协议逐个实现；未配置的 `NATIVE` 供应商会明确报错。
- Webhook 回调、CostLedger 写入、成本统计、结果评分和供应商错误率看板尚未完成。
- Canvas 当前保存业务引用并创建执行快照；节点级业务编译为可执行生成任务仍在后续阶段，当前已支持节点操作、连线、保存和撤销重做。
- Nginx、Docker 和 CentOS 7.9 只完成配置模板和代码侧检查，最终服务器联调仍需在目标环境执行。
- 浏览器协议当前使用 JSON + gzip，未引入 Protobuf。

当前仓库已补充单节点容器化部署资产：

- `Dockerfile` 和 `docker-compose.yml`
- `.env.production.example`
- `deploy/nginx/commerce-studio.conf`
- `deploy/systemd/`
- `deploy/scripts/backup.sh`
- [CentOS 7.9 部署手册](./docs/runbooks/centos7-deployment.md)

CentOS 7.9 仅作为过渡宿主机，Node.js、Prisma 和应用进程运行在 Node 24
Debian Bookworm 容器中。Compose 默认不启动 MySQL，继续使用外部 MySQL。

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
