#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only production diagnostic. It never changes the database or storage.
APP_DIR="${APP_DIR:-/opt/pear-ai}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "请使用 root 执行此脚本。" >&2
    exit 1
fi

if [[ ! -f "${APP_DIR}/.flaskenv" ]]; then
    echo "未找到线上配置：${APP_DIR}/.flaskenv" >&2
    exit 1
fi

if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    echo "未找到线上 Python：${APP_DIR}/.venv/bin/python" >&2
    exit 1
fi

cd "${APP_DIR}"
export FLASK_APP=app.py
export FLASK_CONFIG=production

echo "== Alembic 当前版本 =="
"${APP_DIR}/.venv/bin/python" -m flask db current
echo
echo "== Alembic 目标版本 =="
"${APP_DIR}/.venv/bin/python" -m flask db heads
echo
echo "== Amazon AI 表与历史数据（只读） =="

"${APP_DIR}/.venv/bin/python" - <<'PY'
import sys

from applications import create_app
from applications.extensions import db
from sqlalchemy import inspect, text


app = create_app("production")

with app.app_context():
    inspector = inspect(db.engine)
    table = "amazon_ai_workspace_task"
    if not inspector.has_table(table):
        print(f"缺少数据表：{table}", file=sys.stderr)
        raise SystemExit(2)

    columns = {item["name"] for item in inspector.get_columns(table)}
    required_columns = {
        "id",
        "task_code",
        "task_type",
        "status",
        "created_at",
        "custom_name",
    }
    missing = sorted(required_columns - columns)
    print(f"表：{table}")
    print(f"字段数量：{len(columns)}")
    print("关键字段：", ", ".join(sorted(required_columns & columns)))
    if missing:
        print("缺少字段：" + ", ".join(missing), file=sys.stderr)
        raise SystemExit(3)

    row = db.session.execute(
        text(
            "SELECT COUNT(*) AS total, "
            "MIN(created_at) AS oldest, "
            "MAX(created_at) AS newest "
            "FROM amazon_ai_workspace_task"
        )
    ).mappings().one()
    print("任务总数：", row["total"])
    print("最早创建时间：", row["oldest"] or "")
    print("最新创建时间：", row["newest"] or "")

    counts = db.session.execute(
        text(
            "SELECT task_type, status, COUNT(*) AS total "
            "FROM amazon_ai_workspace_task "
            "GROUP BY task_type, status "
            "ORDER BY task_type, status"
        )
    ).mappings()
    print("按类型/状态统计：")
    for item in counts:
        print(
            f"  {item['task_type']} / {item['status']}: "
            f"{item['total']}"
        )
PY

echo
echo "诊断完成：数据库结构和任务记录未被修改。"
