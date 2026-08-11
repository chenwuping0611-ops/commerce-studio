# commerce-studio

AI 电商产品图片 / 视频生成工作台。

## 当前阶段

当前仓库先建立长期开发基线和架构规范，不在初始化阶段安装依赖或运行本地模型。

长期开发规范见：

- [agent.md](./agent.md)

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
