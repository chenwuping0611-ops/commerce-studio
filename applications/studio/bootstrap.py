import json
import os

from applications.extensions import db
from applications.models import (
    Power,
    Role,
    StudioModel,
    StudioProvider,
    StudioSetting,
    User,
)

from .request_builder import default_parameters_for_model


STUDIO_MENUS = [
    ("AI 创作工作台", "studio:root", "/studio/", "layui-icon layui-icon-console", 1, "0"),
    ("工作台首页", "studio:dashboard", "/studio/", "layui-icon layui-icon-home", 1, "1"),
    ("图片创作", "studio:image", "/studio/image", "layui-icon layui-icon-picture", 2, "1"),
    ("视频创作", "studio:video", "/studio/video", "layui-icon layui-icon-video", 3, "1"),
    ("产品中心", "studio:products", "/studio/products", "layui-icon layui-icon-app", 4, "1"),
    ("Skill 配置", "studio:skills", "/studio/skills", "layui-icon layui-icon-component", 5, "1"),
    ("生成历史", "studio:history", "/studio/history", "layui-icon layui-icon-log", 6, "1"),
]

GLOBAL_CHAT_MODEL_SETTING_KEY = "global_chat_model_id"
DEFAULT_STUDIO_ROLE_CODE = "studio_user"


CORE_MENUS = [
    ("系统管理", "admin:system:root", "", "layui-icon layui-icon-set-fill", 2, "0"),
    ("用户管理", "admin:user:main", "/admin/user/", "layui-icon layui-icon-username", 1, "1"),
    ("角色管理", "admin:role:main", "/admin/role", "layui-icon layui-icon-group", 2, "1"),
    ("权限管理", "admin:power:main", "/admin/power/", "layui-icon layui-icon-auz", 3, "1"),
    ("部门管理", "admin:dept:main", "/dept", "layui-icon layui-icon-tree", 4, "1"),
    ("操作日志", "admin:log:main", "/admin/log", "layui-icon layui-icon-read", 5, "1"),
    ("模型供应商", "studio:providers", "/studio/providers", "layui-icon layui-icon-set", 6, "1"),
]


CORE_ACTIONS = [
    ("新增用户", "admin:user:add", "admin:user:main"),
    ("编辑用户", "admin:user:edit", "admin:user:main"),
    ("删除用户", "admin:user:remove", "admin:user:main"),
    ("新增角色", "admin:role:add", "admin:role:main"),
    ("编辑角色", "admin:role:edit", "admin:role:main"),
    ("删除角色", "admin:role:remove", "admin:role:main"),
    ("角色授权", "admin:role:power", "admin:role:main"),
    ("新增权限", "admin:power:add", "admin:power:main"),
    ("编辑权限", "admin:power:edit", "admin:power:main"),
    ("删除权限", "admin:power:remove", "admin:power:main"),
    ("新增部门", "admin:dept:add", "admin:dept:main"),
    ("编辑部门", "admin:dept:edit", "admin:dept:main"),
    ("删除部门", "admin:dept:remove", "admin:dept:main"),
]


def _find_power(code):
    return Power.query.filter_by(code=code).first() if code else None


def _ensure_power(name, code, url, icon, sort, power_type, parent_id=0):
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
        power.enable = 1
        power.parent_id = parent_id
        if power_type == "1":
            power.open_type = "_iframe"
    return power


def _ensure_admin():
    role = Role.query.filter_by(code="admin").first()
    if not role:
        role = Role(
            name="管理员",
            code="admin",
            remark="Commerce Studio 管理员",
            details="拥有后台全部权限",
            sort=1,
            enable=1,
        )
        db.session.add(role)
        db.session.flush()

    user = User.query.filter_by(username="admin").first()
    if not user:
        user = User(
            username="admin",
            realname="管理员",
            remark="Commerce Studio 默认管理员",
            enable=1,
        )
        user.set_password(os.getenv("ADMIN_PASSWORD", "123456"))
        user.role.append(role)
        db.session.add(user)
    elif role not in user.role:
        user.role.append(role)
    return role


def _ensure_studio_user_role():
    """Create the safe default role for newly created workspace users."""

    role = Role.query.filter_by(code=DEFAULT_STUDIO_ROLE_CODE).first()
    if not role:
        role = Role(
            name="AI 创作用户",
            code=DEFAULT_STUDIO_ROLE_CODE,
            remark="默认创作工作台角色",
            details="拥有 AI 创作工作台全部功能，不包含系统管理权限",
            sort=10,
            enable=1,
        )
        db.session.add(role)
        db.session.flush()
    else:
        role.name = "AI 创作用户"
        role.remark = "默认创作工作台角色"
        role.details = "拥有 AI 创作工作台全部功能，不包含系统管理权限"
        role.enable = 1
    return role


def _disable_power_tree(power):
    """Hide a legacy menu and all of its descendants without deleting data."""

    power.enable = 0
    for child in Power.query.filter_by(parent_id=power.id).all():
        _disable_power_tree(child)


def disable_legacy_menus():
    """Remove unused Pear starter roots from the visible menu tree."""

    legacy_names = {"系统管理", "文件管理", "定时任务"}
    roots = Power.query.filter(Power.parent_id == 0, Power.enable == 1).all()
    for root in roots:
        if not root.code and root.name in legacy_names:
            _disable_power_tree(root)


def seed_menu():
    role = _ensure_admin()
    system_root = _ensure_power(*CORE_MENUS[0], parent_id=0)

    core_pages = {}
    for menu in CORE_MENUS[1:]:
        core_pages[menu[1]] = _ensure_power(*menu, parent_id=system_root.id)
    for name, code, parent_code in CORE_ACTIONS:
        parent = core_pages[parent_code]
        _ensure_power(
            name,
            code,
            "",
            "layui-icon layui-icon-more",
            20,
            "2",
            parent_id=parent.id,
        )

    studio_root = _ensure_power(*STUDIO_MENUS[0], parent_id=0)
    for menu in STUDIO_MENUS[1:]:
        _ensure_power(*menu, parent_id=studio_root.id)

    disable_legacy_menus()
    db.session.flush()
    for power in Power.query.filter(Power.enable == 1).all():
        if power not in role.power:
            role.power.append(power)

    studio_role = _ensure_studio_user_role()
    studio_codes = {menu[1] for menu in STUDIO_MENUS}
    studio_powers = Power.query.filter(
        Power.code.in_(studio_codes),
        Power.enable == 1,
    ).all()
    studio_role.power = studio_powers

    # Migrate the starter Pear "common" role away from system permissions.
    # Existing users keep access to the workspace, while explicit custom
    # roles remain untouched.
    legacy_role = Role.query.filter_by(code="common").first()
    if legacy_role and legacy_role.id != studio_role.id:
        for user in User.query.all():
            roles = list(user.role)
            if legacy_role not in roles:
                continue
            remaining_roles = [item for item in roles if item.id != legacy_role.id]
            if user.username != "admin" and not remaining_roles:
                remaining_roles = [studio_role]
            user.role = remaining_roles
        legacy_role.power = []
        legacy_role.enable = 0
        legacy_role.remark = "旧版 Pear 默认角色，已停用"
        legacy_role.details = "请使用 AI 创作用户或自定义角色"

    # Existing users without an explicit authorization get the same safe
    # workspace-only role as newly created users. Explicit assignments remain
    # untouched so administrators can build custom RBAC roles.
    for user in User.query.all():
        if user.username != "admin" and not list(user.role):
            user.role.append(studio_role)
    db.session.commit()


def seed_provider():
    provider = StudioProvider.query.filter_by(name="ToAPIs").first()
    if not provider:
        provider = StudioProvider(
            name="ToAPIs",
            kind="relay",
            base_url=os.getenv("STUDIO_DEFAULT_PROVIDER_URL", "https://toapis.com"),
            generation_path="/v1/images/generations",
            result_path="/v1/images/generations/{task_id}",
            balance_path="/v1/user/balance",
            token_balance_path="/v1/balance",
            auth_header="Authorization",
            auth_prefix="Bearer",
            timeout=120,
            enabled=1,
            description="ToAPIs 图片与视频异步生成接口",
        )
        db.session.add(provider)
        db.session.flush()
    else:
        provider.token_balance_path = provider.token_balance_path or "/v1/balance"
        provider.auth_header = provider.auth_header or "Authorization"
        provider.auth_prefix = provider.auth_prefix or "Bearer"

    defaults = [
        {
            "name": "GPT Image 2",
            "model_code": "gpt-image-2",
            "media_type": "IMAGE",
            "generation_path": "/v1/images/generations",
            "result_path": "/v1/images/generations/{task_id}",
        },
        {
            "name": "Seedance 2",
            "model_code": "seedance-2",
            "media_type": "VIDEO",
            "generation_path": "/v1/videos/generations",
            "result_path": "/v1/videos/generations/{task_id}",
        },
        {
            "name": "Nano Banana 2",
            "model_code": "gemini-3.1-flash-image-preview",
            "media_type": "IMAGE",
            "generation_path": "/v1/images/generations",
            "result_path": "/v1/images/generations/{task_id}",
        },
        {
            "name": "GPT-5.5 视觉分析",
            "model_code": "gpt-5.5",
            "media_type": "CHAT",
            "generation_path": "/v1/chat/completions",
            "result_path": None,
        },
    ]
    for item in defaults:
        model = StudioModel.query.filter_by(
            provider_id=provider.id,
            model_code=item["model_code"],
        ).first()
        if not model:
            model = StudioModel(
                provider_id=provider.id,
                name=item["name"],
                model_code=item["model_code"],
                media_type=item["media_type"],
                generation_path=item["generation_path"],
                result_path=item["result_path"],
                parameter_schema=json.dumps(
                    default_parameters_for_model(
                        item["model_code"],
                        item["media_type"],
                    ),
                    ensure_ascii=False,
                ),
                enabled=1,
                description="ToAPIs 默认参数模板，可在模型编辑中调整",
            )
            db.session.add(model)
        else:
            _backfill_model_constraints(model)
    db.session.flush()
    chat_models = (
        StudioModel.query.join(StudioProvider)
        .filter(
            StudioModel.media_type == "CHAT",
            StudioModel.enabled == 1,
            StudioProvider.enabled == 1,
        )
        .order_by(StudioModel.id.asc())
        .all()
    )
    setting = StudioSetting.query.filter_by(
        setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY
    ).first()
    selected_model = None
    if setting and setting.setting_value:
        try:
            selected_id = int(setting.setting_value)
        except (TypeError, ValueError):
            selected_id = None
        selected_model = next(
            (model for model in chat_models if model.id == selected_id),
            None,
        )
    if not selected_model and chat_models:
        selected_model = chat_models[0]
    if selected_model:
        if not setting:
            setting = StudioSetting(
                setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
                description="图片与视频创作在关联产品或 Skill 时使用的全局语言模型",
            )
            db.session.add(setting)
        setting.setting_value = str(selected_model.id)
    db.session.commit()


def _backfill_model_constraints(model):
    """Add safe UI constraints without overwriting custom model settings."""

    try:
        parameters = json.loads(model.parameter_schema or "[]")
    except (TypeError, ValueError):
        return
    if not isinstance(parameters, list):
        return

    changed = False
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        field = parameter.get("field")
        if field in ("size", "aspect_ratio") and not parameter.get("options"):
            parameter["options"] = (
                ["1:1", "4:3", "16:9", "9:16"]
                if model.media_type == "VIDEO"
                else ["1:1", "4:3", "16:9", "9:16"]
            )
            changed = True
        elif field == "resolution" and not parameter.get("options"):
            parameter["options"] = (
                ["480p", "720p", "1080p"]
                if model.media_type == "VIDEO"
                else ["1k", "2k", "4k"]
            )
            changed = True
        elif field in ("n", "count") and not any(
            parameter.get(key) is not None for key in ("min", "max", "step")
        ):
            parameter["min"] = 1
            parameter["max"] = 8
            parameter["step"] = 1
            changed = True
        elif (
            model.model_code == "seedance-2"
            and field == "generate_audio"
        ):
            # The starter Seedance configuration historically enabled audio
            # and only allowed the true value. Keep the field configurable,
            # but make the safe default explicit and accept both states.
            if str(parameter.get("value", "")).strip().lower() in (
                "true",
                "1",
                "yes",
                "on",
            ):
                parameter["value"] = "false"
                changed = True
            options = parameter.get("options") or []
            if isinstance(options, list):
                option_values = []
                for option in options:
                    if isinstance(option, dict):
                        option_values.append(
                            str(
                                option.get(
                                    "value",
                                    option.get("key", option.get("id", "")),
                                )
                            ).lower()
                        )
                    else:
                        option_values.append(str(option).lower())
                if "false" not in option_values:
                    if any(isinstance(option, dict) for option in options):
                        options.append({"value": "false", "label": "false"})
                    else:
                        options.append("false")
                    parameter["options"] = options
                    changed = True

    if changed:
        model.parameter_schema = json.dumps(parameters, ensure_ascii=False)


def initialize_studio():
    """Create all tables and seed a usable administrator and starter configuration."""

    import applications.models  # noqa: F401

    db.create_all()
    seed_menu()
    seed_provider()
