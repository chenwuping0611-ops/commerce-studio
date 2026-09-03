from applications.common.storage import FileService
from applications.extensions import db
from applications.common.scope import DEPARTMENT_ADMIN_ROLE_CODE
from applications.models import Dept, Power, Role, StudioAsset, StudioSkill

from .permissions import AMAZON_AI_PERMISSION_CODES
from .skill_catalog import AMAZON_SKILL_DEFINITIONS, read_skill_content


AMAZON_AI_MENUS = [
    (
        "Amazon AI 工作台",
        "amazon_ai:root",
        "/amazon-ai/",
        "layui-icon layui-icon-console",
        2,
        "0",
    ),
    (
        "工作台首页",
        "amazon_ai:dashboard",
        "/amazon-ai/dashboard",
        "layui-icon layui-icon-home",
        1,
        "1",
    ),
    (
        "任务历史",
        "amazon_ai:history",
        "/amazon-ai/history",
        "layui-icon layui-icon-log",
        2,
        "1",
    ),
    (
        "竞品分析",
        "amazon_ai:competitor",
        "/amazon-ai/competitor",
        "layui-icon layui-icon-search",
        3,
        "1",
    ),
    (
        "差异化分析",
        "amazon_ai:differentiation",
        "/amazon-ai/differentiation",
        "layui-icon layui-icon-chart",
        4,
        "1",
    ),
    (
        "基础信息修正",
        "amazon_ai:basic_info",
        "/amazon-ai/basic-info",
        "layui-icon layui-icon-edit",
        5,
        "1",
    ),
    (
        "Listing创作",
        "amazon_ai:listing_create",
        "/amazon-ai/listing/create",
        "layui-icon layui-icon-edit",
        6,
        "1",
    ),
]


def _find_power(code):
    return Power.query.filter_by(code=code).first()


def _ensure_power(name, code, url, icon, sort, power_type, parent_id):
    power = _find_power(code)
    if not power:
        power = Power(
            name=name,
            type=power_type,
            code=code,
            url=url,
            open_type="_iframe" if power_type == "1" else "",
            parent_id=parent_id,
            icon=icon,
            sort=sort,
            enable=1,
        )
        db.session.add(power)
        db.session.flush()
    else:
        power.name = name
        power.url = url
        power.icon = icon
        power.sort = sort
        power.parent_id = parent_id
        power.enable = 1
        if power_type == "1":
            power.open_type = "_iframe"
    return power


def _skill_storage_asset(skill):
    if not skill or not skill.storage_asset_id:
        return None
    return StudioAsset.query.filter_by(
        id=skill.storage_asset_id,
        purpose="SKILL",
    ).first()


def _read_skill_storage_asset(asset):
    """Read one active Skill file without falling back to MySQL text."""

    if not asset or str(asset.status or "").upper() != "ACTIVE":
        return "", False
    try:
        return (
            str(
                FileService.read_text(
                    asset,
                    filename=asset.original_filename,
                    maximum_size=512000,
                )
                or ""
            ).strip(),
            True,
        )
    except Exception:
        return "", False


def seed_amazon_skills(seed_storage=True):
    """Import the bundled Amazon Markdown Skills into the existing Skill system."""

    default_department = (
        Dept.query.filter_by(
            dept_name="三部五组",
        ).order_by(Dept.id.asc()).first()
        or Dept.query.filter(
            (Dept.parent_id == 0) | (Dept.parent_id.is_(None))
        ).order_by(Dept.sort.asc(), Dept.id.asc()).first()
    )
    retired_codes = {
        "Amazon_Listing_Strategy_Integration.md",
        "Amazon_Keyword_Analysis_Skill.md",
        "Amazon_Review_Analysis_Skill.md",
        "Amazon_Listing_Audit_Skill.md",
    }
    for retired_code in retired_codes:
        retired = StudioSkill.query.filter_by(code=retired_code).first()
        if retired:
            retired_asset = (
                StudioAsset.query.filter_by(id=retired.storage_asset_id).first()
                if retired.storage_asset_id
                else None
            )
            if retired_asset:
                if FileService.delete_asset(retired_asset):
                    db.session.delete(retired_asset)
            db.session.delete(retired)
    db.session.flush()
    seeded = []
    for definition in AMAZON_SKILL_DEFINITIONS:
        content = read_skill_content(definition)
        skill = StudioSkill.query.filter_by(code=definition["code"]).first()
        previous_asset = _skill_storage_asset(skill)
        stored_content, storage_readable = _read_skill_storage_asset(
            previous_asset
        )

        if not skill:
            skill = StudioSkill(
                dept_id=default_department.id if default_department else None,
                name=definition["name"],
                code=definition["code"],
                media_type=definition.get("media_type") or "BOTH",
                version="1.0.0",
                tags=definition["tags"],
                prompt_template=content if not seed_storage else None,
                content=content if not seed_storage else None,
                negative_prompt="",
                file_name=definition["file_name"],
                file_type="md",
                enabled=1,
            )
            db.session.add(skill)
            db.session.flush()
        else:
            if skill.dept_id is None and default_department:
                skill.dept_id = default_department.id
            skill.name = definition["name"]
            skill.media_type = definition.get("media_type") or "BOTH"
            skill.version = "1.0.0"
            skill.tags = definition["tags"]
            skill.negative_prompt = ""
            skill.file_name = definition["file_name"]
            skill.file_type = "md"
            skill.enabled = 1

        if not seed_storage:
            # A valid stored file is canonical even when this command is run
            # with --skip-storage. Keep the legacy columns empty in that
            # case; rows without a file remain usable through the fallback.
            if previous_asset and storage_readable:
                skill.prompt_template = None
                skill.content = None
                if skill.dept_id is None and default_department:
                    skill.dept_id = default_department.id
                if previous_asset.dept_id is None:
                    previous_asset.dept_id = skill.dept_id
            else:
                skill.prompt_template = content
                skill.content = content
            db.session.commit()
            seeded.append(skill)
            continue

        if (
            previous_asset
            and storage_readable
            and stored_content == content.strip()
        ):
            # Compare against the canonical GoFastDFS document. The old
            # MySQL body is only a legacy duplicate and must not trigger a
            # fresh upload on every initialization.
            skill.prompt_template = None
            skill.content = None
            if skill.dept_id is None and default_department:
                skill.dept_id = default_department.id
            if previous_asset.dept_id is None:
                previous_asset.dept_id = skill.dept_id
            db.session.commit()
            seeded.append(skill)
            continue

        pending_update = None
        stored = None
        try:
            if (
                previous_asset
                and previous_asset.status in (
                "ACTIVE",
                "DELETE_FAILED",
                )
                and storage_readable
            ):
                # Keep the existing StudioAsset as the stable business
                # identity and replace only its GoFastDFS version.
                pending_update = FileService.stage_asset_update(
                    previous_asset,
                    content=content.encode("utf-8"),
                    filename=definition["file_name"],
                    content_type="text/markdown",
                    category=FileService.default_category("FILE", "SKILL"),
                )
            else:
                stored = FileService.upload_bytes(
                    content.encode("utf-8"),
                    definition["file_name"],
                    content_type="text/markdown",
                    asset_type="FILE",
                    purpose="SKILL",
                    retention_policy=FileService.PERMANENT,
                    created_by=skill.created_by,
                    dept_id=skill.dept_id,
                    record=False,
                )
                asset = FileService.create_asset_record(
                    stored,
                    asset_type="FILE",
                    purpose="SKILL",
                    retention_policy=FileService.PERMANENT,
                    created_by=skill.created_by,
                    dept_id=skill.dept_id,
                )
                db.session.add(asset)
                db.session.flush()
                skill.storage_asset_id = asset.id
            # Only clear the duplicate after the new canonical file has been
            # uploaded or the existing file has been verified/replaced.
            skill.prompt_template = None
            skill.content = None
            db.session.commit()
        except Exception:
            db.session.rollback()
            if pending_update:
                FileService.rollback_asset_update(pending_update)
            elif stored:
                try:
                    FileService.delete_storage(
                        stored.storage_path,
                        checksum=stored.checksum,
                    )
                except Exception:
                    pass
            raise

        if pending_update:
            FileService.finalize_asset_update(pending_update)
        seeded.append(skill)
    return seeded


def initialize_amazon_ai(seed_storage=True):
    """Seed the independent Amazon menu, permissions, and bundled Skills."""

    from applications.studio.bootstrap import (
        ensure_default_departments,
        seed_feedback_skill,
    )

    ensure_default_departments()
    root = _ensure_power(*AMAZON_AI_MENUS[0], parent_id=0)
    pages = [
        _ensure_power(*item, parent_id=root.id)
        for item in AMAZON_AI_MENUS[1:]
    ]
    retired_page_powers = [
        _find_power("amazon_ai:keyword"),
        _find_power("amazon_ai:review"),
    ]
    for retired_power in retired_page_powers:
        if retired_power:
            retired_power.enable = 0
    retired_review_power = _find_power("amazon_ai:listing_review")
    if retired_review_power:
        retired_review_power.enable = 0
    admin_role = Role.query.filter_by(code="admin").first()
    if admin_role:
        admin_role.enable = 1
        for retired_power in retired_page_powers:
            if retired_power and retired_power in admin_role.power:
                admin_role.power.remove(retired_power)
        if retired_review_power in admin_role.power:
            admin_role.power.remove(retired_review_power)
        for power in [root] + pages:
            if power.code in AMAZON_AI_PERMISSION_CODES and power not in admin_role.power:
                admin_role.power.append(power)
    department_admin_role = Role.query.filter_by(
        code=DEPARTMENT_ADMIN_ROLE_CODE
    ).first()
    if department_admin_role:
        department_admin_role.enable = 1
        for retired_power in retired_page_powers:
            if retired_power and retired_power in department_admin_role.power:
                department_admin_role.power.remove(retired_power)
        if retired_review_power in department_admin_role.power:
            department_admin_role.power.remove(retired_review_power)
        for power in [root] + pages:
            if (
                power.code in AMAZON_AI_PERMISSION_CODES
                and power not in department_admin_role.power
            ):
                department_admin_role.power.append(power)
    db.session.commit()
    skills = seed_amazon_skills(seed_storage=seed_storage)
    # Feedback is used from the shared Studio image/video history. Keep the
    # Amazon-only bootstrap command sufficient to repair that built-in Skill.
    seed_feedback_skill(seed_storage=seed_storage)
    return root, pages, skills
