# 部署文件

本目录对应单节点部署基线：

```text
Nginx
  -> 127.0.0.1:3000
      -> Commerce Studio Docker container
          -> external MySQL
          -> named media volume
```

文件说明：

- `nginx/commerce-studio.conf`: Nginx 入口、上传大小、SSE 长连接和反向代理超时。
- `docker/entrypoint.sh`: 启动前执行 `prisma migrate deploy`。
- `systemd/commerce-studio-docker.service`: 使用宿主机 systemd 管理 Docker Compose。
- `systemd/commerce-studio-backup.*`: 每日数据库和媒体备份定时任务。
- `scripts/backup.sh`: 不保存密码的备份脚本，凭 `/etc/commerce-studio/backup.env` 注入参数。

默认不在 Compose 中启动 MySQL。数据库由独立 MySQL 服务提供，应用容器只负责
NestJS、AdminJS、Workbench、SSE、单 Worker 和媒体卷。
