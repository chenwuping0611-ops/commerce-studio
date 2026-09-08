#!/usr/bin/env bash
set -Eeuo pipefail

# Update an existing production checkout without replacing its environment,
# database credentials, provider keys, or persistent business data.

APP_DIR="${APP_DIR:-/opt/pear-ai}"
SERVICE_NAME="${SERVICE_NAME:-pear-ai}"
BACKUP_ROOT="${BACKUP_ROOT:-/opt/pear-ai-backups}"
ARCHIVE="${1:-}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "请使用 root 执行此脚本。" >&2
    exit 1
fi

if [[ -z "${ARCHIVE}" || ! -f "${ARCHIVE}" ]]; then
    echo "用法：$0 /root/pear-ai-release-YYYYMMDD_HHMMSS.tar.gz" >&2
    exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
    echo "线上项目目录不存在：${APP_DIR}" >&2
    exit 1
fi

if [[ ! -f "${APP_DIR}/.flaskenv" ]]; then
    echo "未找到线上 ${APP_DIR}/.flaskenv，已停止以避免误用本地配置。" >&2
    exit 1
fi

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    echo "未找到线上虚拟环境：${APP_DIR}/.venv/bin/python" >&2
    exit 1
fi

mkdir -p "${BACKUP_ROOT}"
chmod 700 "${BACKUP_ROOT}"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/pear-ai-${STAMP}"
TEMP_DIR="$(mktemp -d "/tmp/pear-ai-release.XXXXXX")"
OLD_DIR="${BACKUP_DIR}/previous-app"
mkdir -p "${BACKUP_DIR}"

cleanup() {
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

tar -xzf "${ARCHIVE}" -C "${TEMP_DIR}"

mapfile -t TOP_LEVEL_DIRS < <(
    find "${TEMP_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n'
)
if [[ "${#TOP_LEVEL_DIRS[@]}" -ne 1 ]]; then
    echo "上线包目录结构无效：必须只有一个顶层目录。" >&2
    exit 1
fi

RELEASE_DIR="${TEMP_DIR}/${TOP_LEVEL_DIRS[0]}"
for required_path in app.py applications migrations templates static requirement; do
    if [[ ! -e "${RELEASE_DIR}/${required_path}" ]]; then
        echo "上线包缺少必要路径：${required_path}" >&2
        exit 1
    fi
done

echo "即将停止 ${SERVICE_NAME}，并备份当前代码到：${BACKUP_DIR}"
systemctl stop "${SERVICE_NAME}"

# Move the old checkout as one unit so removed source files cannot remain in
# the new release. Runtime configuration and the existing virtualenv are
# restored into the new checkout below.
mv "${APP_DIR}" "${OLD_DIR}"
mkdir -p "${APP_DIR}"
cp -a "${RELEASE_DIR}/." "${APP_DIR}/"

mv "${OLD_DIR}/.flaskenv" "${APP_DIR}/.flaskenv"
mv "${OLD_DIR}/.venv" "${APP_DIR}/.venv"

# Keep any deployment-local runtime directories that are not part of the
# release archive. The database remains external and is never copied.
for runtime_path in instance logs tmp; do
    if [[ -e "${OLD_DIR}/${runtime_path}" ]]; then
        mv "${OLD_DIR}/${runtime_path}" "${APP_DIR}/${runtime_path}"
    fi
done

# Legacy Pear uploads may still live in the checkout. Merge them into the
# release so an update does not hide deployment-local photo assets.
if [[ -d "${OLD_DIR}/static/upload" ]]; then
    mkdir -p "${APP_DIR}/static/upload"
    cp -a "${OLD_DIR}/static/upload/." "${APP_DIR}/static/upload/"
fi

chown -R root:root "${APP_DIR}"
chmod 750 "${APP_DIR}"

install -o root -g root -m 0644 \
    "${APP_DIR}/deploy/pear-ai.service" \
    "/etc/systemd/system/pear-ai.service"
install -o root -g root -m 0644 \
    "${APP_DIR}/deploy/pear-ai-tmpfiles.conf" \
    "/etc/tmpfiles.d/pear-ai.conf"
install -o root -g root -m 0644 \
    "${APP_DIR}/deploy/pear-ai-logrotate" \
    "/etc/logrotate.d/pear-ai"
systemd-tmpfiles --create
systemctl daemon-reload

export FLASK_APP=app.py
export FLASK_CONFIG=production
export PYTHONUNBUFFERED=1

echo "应用数据库迁移，不执行 init --fresh，不清理线上历史。"
"${APP_DIR}/.venv/bin/python" -m flask db upgrade

echo "同步代码内置 Skill 到线上 GoFastDFS，保留线上 API Key。"
"${APP_DIR}/.venv/bin/python" -m flask sync-skills

systemctl enable "${SERVICE_NAME}"
systemctl start "${SERVICE_NAME}"

if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "服务启动失败。当前版本备份在：${BACKUP_DIR}" >&2
    systemctl status "${SERVICE_NAME}" --no-pager >&2 || true
    exit 1
fi

echo
echo "线上更新完成。"
echo "当前代码：${APP_DIR}"
echo "旧版本备份：${BACKUP_DIR}"
echo "查看状态：systemctl status ${SERVICE_NAME} --no-pager"
echo "查看日志：tail -f /var/log/pear-ai/pear-ai.log"
