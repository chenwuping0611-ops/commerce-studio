# commerce-studio

AI 电商产品图片 / 视频生成工作台。

## 当前阶段

当前仓库先建立长期开发基线和架构规范，不在初始化阶段安装依赖或运行本地模型。

长期开发规范见：

- [agent.md](./agent.md)
- [最终技术选型](./docs/architecture/stack-decision.md)
- [后台框架对比](./docs/research/admin-framework-comparison.md)
- [数据模型与 API 规划](./docs/architecture/data-model-and-api.md)
- [实施路线](./docs/architecture/implementation-roadmap.md)
- [infinite-canvas 源码分析](./docs/research/infinite-canvas-v0.15.1-analysis.md)

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
