# 本地开发运行手册

本项目本地开发不安装 MySQL 和 Nginx：

```text
浏览器 -> NestJS:3000
NestJS -> 远程 MySQL
NestJS -> 外部图片/视频 API
```

## 首次准备

1. 使用 Node.js 24 LTS。
2. 复制 `.env.example` 为 `.env`。
3. 设置远程 MySQL 的 `DATABASE_URL`。
4. 设置本地开发用的 `JWT_SECRET`、`APP_ENCRYPTION_KEY` 和 `ADMIN_COOKIE_PASSWORD`。
5. 安装依赖：

```powershell
npm.cmd install
```

## 数据库

已有项目数据库时：

```powershell
npm.cmd run prisma:generate
npm.cmd run prisma:migrate:deploy
npm.cmd run db:seed
```

首次创建数据库需要由具备建库权限的 MySQL 管理员执行：

```sql
CREATE DATABASE commerce_studio
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

## 启动

前端生产资源和后端构建：

```powershell
npm.cmd run build:web
npm.cmd run build
```

启动服务：

```powershell
npm.cmd run start:dev
```

访问：

- `http://127.0.0.1:3000/workbench`
- `http://127.0.0.1:3000/admin`
- `http://127.0.0.1:3000/api/docs`
- `http://127.0.0.1:3000/health/live`
- `http://127.0.0.1:3000/health/ready`

如果需要局域网其他设备访问，将 `.env` 中 `HOST` 改为 `0.0.0.0`，并确保操作系统防火墙只开放开发所需端口。

## 验证

```powershell
npm.cmd run typecheck:all
npm.cmd test
npm.cmd run build:all
```

生成任务没有配置模型供应商时，只验证任务建模和 API；不要提交真实生成任务。
