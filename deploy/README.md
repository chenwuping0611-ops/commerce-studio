# CentOS 9 部署与日志

部署模板默认使用：

```text
项目目录：/opt/pear-ai
运行用户：root
日志目录：/var/log/pear-ai
```

如果代码当前位于 `/root/pear-ai`，建议先复制或移动到 `/opt/pear-ai`，
当前服务直接由 `root` 运行，不需要创建 `pear` 用户。项目仍建议放在
`/opt/pear-ai`，避免把生产服务路径依赖在 `/root` 下。

## 安装服务

```bash
sudo install -d -o root -g root -m 0750 /var/log/pear-ai
sudo chown -R root:root /opt/pear-ai
sudo cp /opt/pear-ai/deploy/pear-ai.service /etc/systemd/system/pear-ai.service
sudo cp /opt/pear-ai/deploy/pear-ai-tmpfiles.conf /etc/tmpfiles.d/pear-ai.conf
sudo cp /opt/pear-ai/deploy/pear-ai-logrotate /etc/logrotate.d/pear-ai
sudo systemd-tmpfiles --create
sudo systemctl daemon-reload
sudo systemctl enable --now pear-ai
```

## 更新已有线上实例

更新时不要复制本地 `.flaskenv`、`.venv`、数据库、`test/` 或本地演示图片目录。
线上
`.flaskenv` 中的数据库、GoFastDFS 地址和线上供应商 API Key 必须继续使用。
不要执行 `flask init --fresh`，否则会删除线上业务数据和执行历史。

建议先在服务器执行数据库备份，`<MYSQL_...>` 替换为线上 `.flaskenv` 中的值：

```bash
mkdir -p /root/pear-ai-backups/mysql
mysqldump --single-transaction --routines --triggers \
  -h <MYSQL_HOST> -P <MYSQL_PORT> \
  -u <MYSQL_USERNAME> -p <MYSQL_DATABASE> \
  | gzip > /root/pear-ai-backups/mysql/pear-ai-$(date +%Y%m%d_%H%M%S).sql.gz
```

把上线包上传到服务器后，先解压到临时目录，再使用包内脚本更新。这样线上
旧版本即使还没有这个脚本也可以首次使用。脚本会备份旧代码、保留线上
`.flaskenv` 和 `.venv`、执行 `flask db upgrade`、执行 `flask sync-skills`
重新上传代码内置 Skill 并更新数据库地址，最后重载并重启服务：

```bash
PACKAGE=/root/pear-ai-release-20260905_XXXXXX.tar.gz
PACKAGE_TMP="$(mktemp -d /tmp/pear-ai-package.XXXXXX)"
tar -xzf "${PACKAGE}" -C "${PACKAGE_TMP}"
chmod +x "${PACKAGE_TMP}/pear-admin-flask-master/deploy/update_online.sh"
APP_DIR=/opt/pear-ai \
  "${PACKAGE_TMP}/pear-admin-flask-master/deploy/update_online.sh" \
  "${PACKAGE}"
```

如果项目当前不在 `/opt/pear-ai`，可以显式指定目录：

```bash
APP_DIR=/实际项目目录 \
  "${PACKAGE_TMP}/pear-admin-flask-master/deploy/update_online.sh" \
  /root/pear-ai-release-20260905_XXXXXX.tar.gz
```

脚本不会导入本地数据库、产品、图片、执行历史或供应商 API Key。旧代码备份
默认保存在 `/opt/pear-ai-backups/pear-ai-时间戳/previous-app`，确认新版本
稳定后再按保留策略清理备份。

如果旧部署仍有 `static/upload/` 中的传统本地图片，更新脚本会把它们合并到
新版本；产品素材、Skill、生成结果和执行历史仍以线上数据库及 GoFastDFS
为准，不会从本地包导入。

`pear-ai.service` 已经显式设置：

```text
FLASK_CONFIG=production
PEAR_AI_LOG_DIR=/var/log/pear-ai
PEAR_AI_APP_LOG_FILE=/var/log/pear-ai/pear-ai.log
PEAR_AI_LOG_LEVEL=INFO
PEAR_AI_LOG_STRICT=true
PEAR_AI_LOG_TO_CONSOLE=false
GUNICORN_TIMEOUT=900
GUNICORN_WORKER_CLASS=gthread
```

因此 `.flaskenv` 中遗留的开发配置 `LOG_DIR=logs` 不会覆盖生产日志
目录。应用无法创建 `/var/log/pear-ai` 时会直接启动失败，不会静默退回
项目目录。

服务模板固定使用 `GUNICORN_TIMEOUT=900` 和 `GUNICORN_WORKER_CLASS=gthread`。
接口 AI 文本请求的供应商超时为 600 秒，Gunicorn 必须比它更长；线程工作模式
允许历史、配置等短请求在模型长请求等待期间继续返回。若线上曾手动改过
`/etc/systemd/system/pear-ai.service`，更新代码后需要重新安装包内服务文件并
执行 `systemctl daemon-reload`，否则旧的 180 秒超时仍会生效。

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

## 更新后检查 Amazon AI 数据

如果竞品分析、差异化分析、Listing 创作或对应历史页面显示“服务器返回了
无效响应”，先在生产目录执行只读检查：

```bash
cd /opt/pear-ai
chmod +x deploy/verify_online.sh
APP_DIR=/opt/pear-ai deploy/verify_online.sh
```

该检查会输出 Alembic 当前版本、目标版本、`amazon_ai_workspace_task`
的 `custom_name` 字段是否存在，以及任务总数和最早/最新时间。它不会写入
数据库，不会删除历史记录或 GoFastDFS 文件。

如果检查提示缺少字段或当前版本不是最新版本，先备份线上数据库，再执行：

```bash
cd /opt/pear-ai
source .venv/bin/activate
export FLASK_APP=app.py
export FLASK_CONFIG=production
flask db upgrade
deactivate
systemctl restart pear-ai
systemctl status pear-ai --no-pager
```

本次新增迁移只增加名称和工作流元数据字段，不会清理
`amazon_ai_workspace_task` 中的历史数据。若迁移完成后仍有接口异常，查看：

```bash
tail -n 200 /var/log/pear-ai/pear-ai.log
tail -n 200 /var/log/pear-ai/gunicorn-error.log
```
