# CentOS 9 部署与日志

部署模板默认使用：

```text
项目目录：/opt/pear-ai
运行用户：pear
日志目录：/var/log/pear-ai
```

如果代码当前位于 `/root/pear-ai`，建议先复制或移动到 `/opt/pear-ai`，
再把目录交给 `pear` 用户。仅修改 systemd 的项目路径而不调整 `/root`
父目录权限，会导致服务无法启动。

## 安装服务

```bash
sudo useradd --system --home-dir /opt/pear-ai --shell /sbin/nologin pear
sudo install -d -o pear -g pear -m 0750 /var/log/pear-ai
sudo chown -R pear:pear /opt/pear-ai
sudo cp /opt/pear-ai/deploy/pear-ai.service /etc/systemd/system/pear-ai.service
sudo cp /opt/pear-ai/deploy/pear-ai-tmpfiles.conf /etc/tmpfiles.d/pear-ai.conf
sudo cp /opt/pear-ai/deploy/pear-ai-logrotate /etc/logrotate.d/pear-ai
sudo systemd-tmpfiles --create
sudo systemctl daemon-reload
sudo systemctl enable --now pear-ai
```

`pear-ai.service` 已经显式设置：

```text
FLASK_CONFIG=production
PEAR_AI_LOG_DIR=/var/log/pear-ai
PEAR_AI_APP_LOG_FILE=/var/log/pear-ai/pear-ai.log
PEAR_AI_LOG_LEVEL=INFO
PEAR_AI_LOG_STRICT=true
PEAR_AI_LOG_TO_CONSOLE=false
```

因此 `.flaskenv` 中遗留的开发配置 `LOG_DIR=logs` 不会覆盖生产日志
目录。应用无法创建 `/var/log/pear-ai` 时会直接启动失败，不会静默退回
项目目录。

直接执行项目根目录的 `start.sh` 也会自动导出生产日志变量；如果不使用
systemd，可以在确认目录权限后执行：

```bash
./start.sh
```

## 日志文件

```text
/var/log/pear-ai/pear-ai.log
/var/log/pear-ai/gunicorn-access.log
/var/log/pear-ai/gunicorn-error.log
/var/log/pear-ai/systemd.log
/var/log/pear-ai/systemd-error.log
```

查看服务状态和日志：

```bash
sudo systemctl status pear-ai --no-pager
sudo tail -f /var/log/pear-ai/pear-ai.log
sudo tail -f /var/log/pear-ai/gunicorn-error.log
sudo tail -f /var/log/pear-ai/gunicorn-access.log
```

`journalctl -u pear-ai` 仍可查看 systemd 的服务状态事件，但应用运行日志
的主文件是 `/var/log/pear-ai/pear-ai.log`。
