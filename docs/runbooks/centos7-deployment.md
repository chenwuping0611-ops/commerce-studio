# CentOS 7.9 部署手册

## 目标拓扑

```text
浏览器
  -> Nginx:80/443
      -> 127.0.0.1:3000
          -> Commerce Studio Docker container
              -> 外部 MySQL:3306
              -> commerce-studio-media volume
```

本方案不要求在宿主机安装 Node.js、Prisma 或本地 MySQL。应用运行在
Node 24 Debian Bookworm 容器中，CentOS 7.9 只负责 Docker、Nginx 和 systemd。

CentOS 7.9 属于旧版运行环境。可以继续作为过渡宿主机，但新服务器优先使用
Rocky Linux 9、AlmaLinux 9 或其他当前维护中的发行版。

## 1. 服务器目录

```text
/opt/commerce-studio/
/etc/commerce-studio/
/var/backups/commerce-studio/
```

把仓库部署到 `/opt/commerce-studio`，并创建仅 root 可读的生产配置：

```bash
install -d -m 0750 /etc/commerce-studio
cp .env.production.example /opt/commerce-studio/.env.production
chmod 0600 /opt/commerce-studio/.env.production
vi /opt/commerce-studio/.env.production
```

必须替换：

- `DATABASE_URL`
- `JWT_SECRET`
- `APP_ENCRYPTION_KEY`
- `ADMIN_COOKIE_PASSWORD`
- `ADMIN_PASSWORD`
- `PUBLIC_BASE_URL`
- `FRONTEND_ORIGINS`

不要把 `.env.production` 提交到 Git。

## 2. 数据库准备

在 MySQL 上创建独立数据库和应用账号。不要让应用长期使用 root：

```sql
CREATE DATABASE commerce_studio
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'commerce_app'@'应用服务器IP'
  IDENTIFIED BY '替换为强密码';

GRANT ALL PRIVILEGES ON commerce_studio.* TO 'commerce_app'@'应用服务器IP';
FLUSH PRIVILEGES;
```

如果数据库已经由管理员准备好，只需要把连接地址写入
`.env.production`。应用容器启动时会自动执行已提交的 Prisma migrations。

## 3. 启动应用

先确认 Docker Compose 命令路径。下方 systemd 模板默认使用
`/usr/local/bin/docker-compose`：

```bash
command -v docker
command -v docker-compose
cd /opt/commerce-studio
docker-compose --env-file .env.production config
docker-compose --env-file .env.production up -d --build
docker-compose ps
docker-compose logs --tail=100 commerce-studio
```

如果服务器使用 Docker Compose v2 插件，把
`deploy/systemd/commerce-studio-docker.service` 中的
`/usr/local/bin/docker-compose` 替换为 `/usr/bin/docker compose` 对应的
可执行形式，或建立兼容软链接。

检查：

```bash
curl -fsS http://127.0.0.1:3000/health/live
curl -fsS http://127.0.0.1:3000/health/ready
```

首次 seed 使用一次性命令执行，不要把默认密码留在生产环境：

```bash
docker-compose --env-file .env.production exec commerce-studio \
  npm run db:seed
```

## 4. Nginx

```bash
cp deploy/nginx/commerce-studio.conf /etc/nginx/conf.d/commerce-studio.conf
vi /etc/nginx/conf.d/commerce-studio.conf
nginx -t
systemctl enable --now nginx
systemctl reload nginx
```

把 `server_name` 和 TLS 配置替换为真实域名。必须保留：

- `/api/` 的常规 API 转发
- `/events/` 的 `proxy_buffering off`
- `/events/` 的长 `proxy_read_timeout`
- `client_max_body_size 50m`
- `X-Forwarded-Proto` 和 `X-Forwarded-For`

业务访问地址：

- `https://域名/workbench/`
- `https://域名/admin/`
- `https://域名/api/docs`

## 5. systemd 托管

```bash
cp deploy/systemd/commerce-studio-docker.service \
  /etc/systemd/system/commerce-studio-docker.service
systemctl daemon-reload
systemctl enable --now commerce-studio-docker
systemctl status commerce-studio-docker
```

更新发布：

```bash
cd /opt/commerce-studio
git fetch origin
git checkout main
git pull --ff-only origin main
docker-compose --env-file .env.production up -d --build --remove-orphans
docker-compose ps
```

不要在生产目录直接编辑源码，不要使用 `git reset --hard` 覆盖未确认的
配置或媒体卷。

## 6. 备份

创建 root-only 备份环境文件：

```bash
install -d -m 0750 /etc/commerce-studio
vi /etc/commerce-studio/backup.env
chmod 0600 /etc/commerce-studio/backup.env
```

内容示例：

```bash
MYSQL_HOST=replace-with-mysql-host
MYSQL_PORT=3306
MYSQL_DATABASE=commerce_studio
MYSQL_USER=commerce_app
MYSQL_PASSWORD=replace-with-password
BACKUP_ROOT=/var/backups/commerce-studio
MEDIA_SOURCE=/var/lib/docker/volumes/commerce-studio-media/_data
BACKUP_RETENTION_DAYS=14
```

安装备份任务：

```bash
chmod +x deploy/scripts/backup.sh
cp deploy/systemd/commerce-studio-backup.service /etc/systemd/system/
cp deploy/systemd/commerce-studio-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now commerce-studio-backup.timer
systemctl list-timers commerce-studio-backup.timer
```

至少定期把 `/var/backups/commerce-studio` 复制到另一台机器或对象存储。
备份完成不等于恢复验证完成，发布前应在临时数据库演练导入。

## 7. 2C2G 运行约束

- 应用只运行一个容器和一个内置 Worker。
- 任务并发保持 1，图片/视频通过异步任务，不占用请求连接。
- MySQL 不放在本 Compose 中，不与应用争抢 2G 内存。
- 媒体文件只放 Docker named volume，不写入 MySQL BLOB。
- 开启至少 1G Swap，并设置 Docker 日志大小上限。
- 定期检查 `docker stats`、磁盘空间、失败任务和 MySQL 连接。
- 不要在第一阶段加入 Redis、Kafka、Dify、Flowise 或本地模型服务。

## 8. 故障定位

```bash
docker-compose ps
docker-compose logs --tail=200 commerce-studio
curl -i http://127.0.0.1:3000/health/live
curl -i http://127.0.0.1:3000/health/ready
nginx -t
tail -n 100 /var/log/nginx/error.log
df -h
free -m
```

常见问题：

- `ready` 为 degraded：检查 `DATABASE_URL`、MySQL 白名单、防火墙和账号权限。
- `/workbench/` 空白：检查容器是否完成 `npm run build:web`，并查看容器日志。
- SSE 不更新：检查 Nginx `/events/` 是否关闭缓冲并提高读取超时。
- 素材上传失败：检查 Nginx body size、容器媒体卷和 `MAX_UPLOAD_BYTES`。
- AdminJS 无法登录：确认 seed 用户、`ADMIN_COOKIE_PASSWORD` 和反向代理 HTTPS 设置。
