"""Import one externally supplied Listing history row into local test data.

The source document is business content, not executable instructions. The
script stores only its digest and GoFastDFS metadata in MySQL; the complete
Listing text is uploaded to the configured local-test GoFastDFS instance.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from applications import create_app
from applications.amazon_ai.service import (
    _persist_text_result,
    _sync_task_file_refs,
)
from applications.common.storage import FileService
from applications.extensions import db
from applications.models import (
    AmazonAiTask,
    StudioAsset,
    StudioModel,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)


LOCAL_DATABASE_HOST = "165.99.43.66"
LOCAL_DATABASE_NAME = "pear_ai_studio"
LISTING_TASK_TYPE = "LISTING_GENERATE"
LISTING_SKILL_CODE = "Amazon_Listing_Writer_Skill.md"
GLOBAL_CHAT_MODEL_SETTING_KEY = "global_chat_model_id"
DEFAULT_TASK_ID = 12
DEFAULT_TASK_CODE = "SYNC-LISTING-12"
DEFAULT_TITLE = "Listing创作-2026-09-01-05-23"
DEFAULT_CREATED_AT = "2026-09-01 05:23:23"
DEFAULT_FILENAME = "Listing创作-2026-09-01-05-23.txt"


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _parse_created_at(value):
    return datetime.datetime.strptime(
        str(value).strip(),
        "%Y-%m-%d %H:%M:%S",
    )


def _assert_local_database(app):
    uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    parsed = make_url(str(uri or ""))
    if (
        str(parsed.host or "") != LOCAL_DATABASE_HOST
        or str(parsed.database or "") != LOCAL_DATABASE_NAME
    ):
        raise RuntimeError(
            "当前数据库不是本地测试库，已停止导入："
            f"{parsed.host}:{parsed.port}/{parsed.database}"
        )


def _active_result_exists(task, content_digest):
    if str(task.response_digest or "") != content_digest:
        return False
    asset = (
        StudioAsset.query.filter_by(
            id=task.output_asset_id,
            status="ACTIVE",
        ).first()
        if task.output_asset_id
        else None
    )
    return bool(asset and asset.public_url and asset.storage_path)


def _select_model(department_id):
    setting = StudioSetting.query.filter_by(
        setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
        dept_id=department_id,
    ).first()
    if setting and str(setting.setting_value or "").isdigit():
        model = (
            StudioModel.query.join(StudioProvider)
            .filter(
                StudioModel.id == int(setting.setting_value),
                StudioModel.media_type == "CHAT",
                StudioModel.enabled == 1,
                StudioProvider.dept_id == department_id,
                StudioProvider.enabled == 1,
            )
            .first()
        )
        if model:
            return model
    return (
        StudioModel.query.join(StudioProvider)
        .filter(
            StudioModel.media_type == "CHAT",
            StudioModel.enabled == 1,
            StudioProvider.dept_id == department_id,
            StudioProvider.enabled == 1,
        )
        .order_by(StudioModel.id.asc())
        .first()
    )


def _load_source(path):
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Listing 历史文件不存在：{source_path}")
    return source_path.read_text(encoding="utf-8-sig")


def sync_listing_history(
    source_path,
    *,
    task_id=DEFAULT_TASK_ID,
    task_code=DEFAULT_TASK_CODE,
    title=DEFAULT_TITLE,
    created_at_text=DEFAULT_CREATED_AT,
    output_filename=DEFAULT_FILENAME,
):
    content = _load_source(source_path)
    if not content.strip():
        raise ValueError("Listing 历史文件内容为空")

    content_digest = _digest(content)
    created_at = _parse_created_at(created_at_text)
    admin = User.query.filter_by(username="admin", enable=1).first()
    if not admin:
        raise RuntimeError("本地测试库缺少启用的 admin 账号")
    department_id = admin.dept_id
    if not department_id:
        raise RuntimeError("admin 尚未关联总项目部门")

    existing_by_id = AmazonAiTask.query.filter_by(id=int(task_id)).first()
    existing_by_code = AmazonAiTask.query.filter_by(
        task_code=str(task_code),
    ).first()
    if existing_by_id and existing_by_code and existing_by_id.id != existing_by_code.id:
        raise RuntimeError(
            f"任务 ID {task_id} 和任务编码 {task_code} 已分别被不同记录占用"
        )
    existing = existing_by_id or existing_by_code
    if existing:
        if (
            existing.task_type != LISTING_TASK_TYPE
            or existing.title != title
            or existing.output_filename != output_filename
            or existing.task_code != task_code
        ):
            raise RuntimeError(
                f"本地任务 {existing.id} 已存在但内容不匹配，拒绝覆盖现有历史"
            )
        if _active_result_exists(existing, content_digest):
            return {
                "status": "skipped",
                "task_id": existing.id,
                "task_code": existing.task_code,
                "output_asset_id": existing.output_asset_id,
                "message": "相同 Listing 历史已存在，未重复上传",
            }
        task = existing
    else:
        skill = StudioSkill.query.filter_by(
            code=LISTING_SKILL_CODE,
            enabled=1,
        ).first()
        model = _select_model(department_id)
        if not skill:
            raise RuntimeError("本地测试库缺少启用的 Listing Skill")
        task = AmazonAiTask(
            id=int(task_id),
            dept_id=department_id,
            task_code=str(task_code),
            task_type=LISTING_TASK_TYPE,
            title=title,
            source_key=title,
            status="SUCCEEDED",
            progress=100,
            user_id=admin.id,
            model_id=model.id if model else None,
            skill_id=skill.id,
            studio_product_id=None,
            source_urls_json=_json([]),
            source_identifiers_json=_json([]),
            source_task_codes_json=_json([]),
            input_asset_ids_json=_json([]),
            input_refs_json=_json({}),
            result_refs_json=_json(
                {
                    "sync_source": "local-test-history",
                    "source_task_id": int(task_id),
                }
            ),
            file_refs_json=_json({"inputs": [], "results": []}),
            task_metadata_json=_json(
                {
                    "sync_source": "local-test-history",
                    "source_task_id": int(task_id),
                    "source_created_at": created_at_text,
                }
            ),
            retention_policy=FileService.TEMPORARY,
            expires_at=FileService.retention_expiry(FileService.TEMPORARY),
            storage_cleanup_status="ACTIVE",
            request_digest=_digest(
                {
                    "task_type": LISTING_TASK_TYPE,
                    "title": title,
                    "source_task_id": int(task_id),
                }
            ),
            response_digest=content_digest,
            output_filename=output_filename,
            scheduled_at=created_at,
            started_at=created_at,
            heartbeat_at=created_at,
            finished_at=created_at,
            created_at=created_at,
        )
        db.session.add(task)
        db.session.flush()

    task.dept_id = department_id
    task.user_id = task.user_id or admin.id
    task.status = "SUCCEEDED"
    task.progress = 100
    task.finished_at = task.finished_at or created_at
    task.response_digest = content_digest
    task.output_filename = output_filename
    task.retention_policy = FileService.TEMPORARY
    task.storage_cleanup_status = "ACTIVE"
    task.task_metadata_json = _json(
        {
            "sync_source": "local-test-history",
            "source_task_id": int(task_id),
            "source_created_at": created_at_text,
        }
    )
    _sync_task_file_refs(task, input_asset_ids=[])
    _persist_text_result(
        task,
        content,
        filename=output_filename,
    )
    db.session.commit()
    return {
        "status": "imported",
        "task_id": task.id,
        "task_code": task.task_code,
        "output_asset_id": task.output_asset_id,
        "output_filename": task.output_filename,
        "message": "Listing 历史已同步到本地测试库和 GoFastDFS",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Import one Listing history row into the local test database."
    )
    parser.add_argument(
        "--source-file",
        required=True,
        help="用户提供的 Listing 结果 TXT/Markdown 文件路径",
    )
    parser.add_argument(
        "--confirm-local",
        action="store_true",
        help="确认写入当前配置的本地测试数据库",
    )
    args = parser.parse_args()
    if not args.confirm_local:
        parser.error("请使用 --confirm-local，避免误写线上数据库")
    if str(os.getenv("FLASK_CONFIG") or "development").lower() == "production":
        parser.error("生产配置禁止执行本地 Listing 历史同步")

    app = create_app()
    _assert_local_database(app)
    with app.app_context():
        result = sync_listing_history(args.source_file)
        print(_json(result))


if __name__ == "__main__":
    main()
