import json
import os

from sqlalchemy import or_

from applications.common.scope import (
    DEPARTMENT_ADMIN_ROLE_CODE,
    PROVIDER_OWNER_DEPARTMENT,
    SUPER_ADMIN_ROLE_CODE,
)
from applications.common.skill_storage import force_replace_skill_storage
from applications.common.storage import FileService
from applications.extensions import db
from applications.models import (
    Dept,
    Power,
    Role,
    StudioAsset,
    StudioModel,
    StudioProvider,
    StudioSetting,
    StudioSkill,
    User,
)

from .request_builder import (
    is_seedance_model,
    seedance_capabilities,
    seedance_parameters,
)
from .provider_catalog import (
    KUAIPAO_LEGACY_IMAGE_MODEL_CODES,
    catalog_for_provider,
)
from .feedback_skill import (
    FEEDBACK_SKILL_CODE,
    FEEDBACK_SKILL_FILE_NAME,
    FEEDBACK_SKILL_NAME,
    load_feedback_skill_content,
)


STUDIO_MENUS = [
    ("视频与图片创作", "studio:root", "/studio/", "layui-icon layui-icon-console", 1, "0"),
    ("工作台首页", "studio:dashboard", "/studio/", "layui-icon layui-icon-home", 1, "1"),
    ("图片创作", "studio:image", "/studio/image", "layui-icon layui-icon-picture", 2, "1"),
    ("白底图生成", "studio:white_background", "/studio/white-background", "layui-icon layui-icon-picture-fine", 3, "1"),
    ("视频创作", "studio:video", "/studio/video", "layui-icon layui-icon-video", 4, "1"),
    ("批量创作提示词", "studio:batch_prompts", "/studio/batch-prompts", "layui-icon layui-icon-edit", 5, "1"),
    ("产品中心", "studio:products", "/studio/products", "layui-icon layui-icon-app", 6, "1"),
    ("Skill 配置", "studio:skills", "/studio/skills", "layui-icon layui-icon-component", 7, "1"),
    ("生成历史", "studio:history", "/studio/history", "layui-icon layui-icon-log", 8, "1"),
]

GLOBAL_CHAT_MODEL_SETTING_KEY = "global_chat_model_id"
DEFAULT_STUDIO_ROLE_CODE = "studio_user"
DEFAULT_STUDIO_ROLE_NAME = "五组操作员"
_DEFAULT_PROVIDER_DEPARTMENT = object()


CORE_MENUS = [
    ("系统管理", "admin:system:root", "", "layui-icon layui-icon-set-fill", 3, "0"),
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


DEPARTMENT_ADMIN_POWER_CODES = {
    "admin:system:root",
    "admin:user:main",
    "admin:user:add",
    "admin:user:edit",
    "admin:user:remove",
    "admin:role:main",
    "admin:role:add",
    "admin:role:edit",
    "admin:role:remove",
    "admin:role:power",
    "admin:power:main",
    "admin:power:add",
    "admin:power:edit",
    "admin:power:remove",
    "admin:dept:main",
    "admin:dept:add",
    "admin:dept:edit",
    "admin:dept:remove",
    "admin:log:main",
    "studio:dashboard",
    "studio:root",
    "studio:image",
    "studio:white_background",
    "studio:video",
    "studio:batch_prompts",
    "studio:products",
    "studio:skills",
    "studio:history",
    "studio:providers",
    "amazon_ai:root",
    "amazon_ai:dashboard",
    "amazon_ai:history",
    "amazon_ai:competitor",
    "amazon_ai:keyword",
    "amazon_ai:review",
    "amazon_ai:differentiation",
    "amazon_ai:basic_info",
    "amazon_ai:listing_create",
}


def _root_department():
    root = (
        Dept.query.filter(
            Dept.dept_name == "总项目",
            (Dept.parent_id == 0) | (Dept.parent_id.is_(None)),
        )
        .order_by(Dept.id.asc())
        .first()
    )
    if root:
        return root
    return (
        Dept.query.filter(
            (Dept.parent_id == 0) | (Dept.parent_id.is_(None))
        )
        .order_by(Dept.sort.asc(), Dept.id.asc())
        .first()
    )


def ensure_default_departments():
    """Create the initial organization boundary without creating users.

    The first deployment has one real top-level department for ``admin``.
    The two child departments are only structural defaults; users are still
    created explicitly from the user-management page.
    """

    root = (
        Dept.query.filter(
            Dept.dept_name == "总项目",
            (Dept.parent_id == 0) | (Dept.parent_id.is_(None)),
        )
        .order_by(Dept.id.asc())
        .first()
    )
    if not root:
        # Older deployments sometimes used the first business department as
        # the root. Rename only the known legacy default so existing ownership
        # references remain valid.
        root = (
            Dept.query.filter(
                Dept.dept_name == "三部五组",
                (Dept.parent_id == 0) | (Dept.parent_id.is_(None)),
            )
            .order_by(Dept.id.asc())
            .first()
        )
        if root:
            root.dept_name = "总项目"
        else:
            root = Dept(
                parent_id=0,
                dept_name="总项目",
                sort=0,
                leader="",
                status=1,
            )
            db.session.add(root)
            db.session.flush()

    root.parent_id = 0
    root.sort = 0
    root.status = 1 if root.status is None else root.status

    children = {}
    for name, sort in (("三部五组", 10), ("三部二组", 20)):
        department = (
            Dept.query.filter_by(dept_name=name)
            .order_by(Dept.id.asc())
            .first()
        )
        if not department or department.id == root.id:
            department = Dept(
                parent_id=root.id,
                dept_name=name,
                sort=sort,
                leader="",
                status=1,
            )
            db.session.add(department)
        else:
            department.parent_id = root.id
            if department.sort is None:
                department.sort = sort
            if department.status is None:
                department.status = 1
        children[name] = department

    db.session.flush()
    return root, children


def _studio_default_department():
    preferred_name = os.getenv("STUDIO_DEFAULT_DEPT_NAME", "总项目")
    return (
        Dept.query.filter_by(dept_name=preferred_name)
        .order_by(Dept.id.asc())
        .first()
        or _root_department()
    )


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
            name="超级管理员",
            code="admin",
            remark="Commerce Studio 超级管理员",
            details="拥有全部部门、用户、权限、供应商和模型数据权限",
            sort=1,
            enable=1,
        )
        db.session.add(role)
        db.session.flush()
    else:
        role.name = "超级管理员"
        role.remark = "Commerce Studio 超级管理员"
        role.details = "拥有全部部门、用户、权限、供应商和模型数据权限"
        role.enable = 1

    user = User.query.filter_by(username="admin").first()
    root = _root_department()
    if not user:
        user = User(
            username="admin",
            realname="超级管理员",
            remark="Commerce Studio 默认管理员",
            enable=1,
            dept_id=root.id if root else None,
        )
        user.set_password(os.getenv("ADMIN_PASSWORD", "123456"))
        user.role.append(role)
        db.session.add(user)
    elif role not in user.role:
        user.role.append(role)
    # ``admin`` is always represented by the real ``总项目`` department.
    # Keeping this assignment idempotent also repairs older deployments where
    # the reserved account was left under a business department.
    if root:
        user.dept_id = root.id
    return role


def _ensure_studio_user_role():
    """Create the safe default role for newly created workspace users."""

    role = Role.query.filter_by(code=DEFAULT_STUDIO_ROLE_CODE).first()
    if not role:
        role = Role(
            name=DEFAULT_STUDIO_ROLE_NAME,
            code=DEFAULT_STUDIO_ROLE_CODE,
            remark="默认创作工作台角色",
            details="五组普通操作员，拥有 AI 创作工作台全部功能，不包含系统管理权限",
            sort=10,
            enable=1,
        )
        db.session.add(role)
        db.session.flush()
    else:
        role.name = DEFAULT_STUDIO_ROLE_NAME
        role.remark = "默认创作工作台角色"
        role.details = "五组普通操作员，拥有 AI 创作工作台全部功能，不包含系统管理权限"
        role.enable = 1
    return role


def _ensure_department_admin_role():
    """Create the scoped administrator role used by branch administrators."""

    role = Role.query.filter_by(code=DEPARTMENT_ADMIN_ROLE_CODE).first()
    if not role:
        role = Role(
            name="部门管理员",
            code=DEPARTMENT_ADMIN_ROLE_CODE,
            remark="部门范围管理员",
            details="只能管理自己部门及下属部门的数据，不能访问其他部门的 Key",
            sort=5,
            enable=1,
        )
        db.session.add(role)
        db.session.flush()
    else:
        role.name = "部门管理员"
        role.remark = "部门范围管理员"
        role.details = "只能管理自己部门的数据，不能访问其他部门的 Key"
        role.enable = 1

    role.power = Power.query.filter(
        Power.code.in_(DEPARTMENT_ADMIN_POWER_CODES),
        Power.enable == 1,
    ).all()
    return role


def _find_seed_provider(name, owner_type, department_id):
    """Find one built-in provider inside one real department."""

    del owner_type
    query = StudioProvider.query.filter(
        StudioProvider.name == name,
        StudioProvider.dept_id == department_id,
    )
    provider = query.order_by(StudioProvider.id.asc()).first()
    if provider:
        return provider
    # A legacy deployment may still have one unscoped built-in row. Adopt it
    # only while materializing the default ``总项目`` scope. A newly created
    # department must never steal the administrator's legacy configuration;
    # migrations handle the complete cleanup for existing installations.
    root = _root_department()
    if not root or department_id != root.id:
        return None
    return (
        StudioProvider.query.filter(
            StudioProvider.name == name,
            StudioProvider.dept_id.is_(None),
            or_(
                StudioProvider.owner_type == "SUPER_ADMIN",
                StudioProvider.owner_type == PROVIDER_OWNER_DEPARTMENT,
                StudioProvider.owner_type.is_(None),
            ),
        )
        .order_by(StudioProvider.id.asc())
        .first()
    )


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
    ensure_default_departments()
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
    studio_codes = {
        menu[1] for menu in STUDIO_MENUS
    } | {
        "admin:system:root",
        "admin:user:main",
        "admin:log:main",
    }
    studio_powers = Power.query.filter(
        Power.code.in_(studio_codes),
        Power.enable == 1,
    ).all()
    studio_role.power = studio_powers
    _ensure_department_admin_role()

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
        roles = list(user.role)
        if user.username != "admin":
            # ``admin`` is an account-reserved identity.  Remove an old
            # accidental assignment instead of allowing it to survive a
            # restart and grant a normal account broad functional access.
            roles = [
                item
                for item in roles
                if getattr(item, "code", "") != SUPER_ADMIN_ROLE_CODE
            ]
        if user.username != "admin" and not roles:
            roles.append(studio_role)
        user.role = roles
    db.session.commit()


def _sync_catalog_models(provider):
    """Materialize one provider's code-owned model catalog idempotently."""

    catalog_specs = catalog_for_provider(provider).models()
    catalog_codes = {spec.code for spec in catalog_specs}
    for spec in catalog_specs:
        model = StudioModel.query.filter_by(
            provider_id=provider.id,
            model_code=spec.code,
        ).first()
        if not model:
            model = StudioModel(
                provider_id=provider.id,
                name=spec.name,
                model_code=spec.code,
                media_type=spec.media_type,
                generation_path=spec.generation_path,
                result_path=spec.result_path,
                parameter_schema=json.dumps(
                    spec.parameter_schema(),
                    ensure_ascii=False,
                ),
                capabilities=json.dumps(
                    spec.capability_data(),
                    ensure_ascii=False,
                ),
                enabled=1,
                description=spec.description,
            )
            db.session.add(model)
            continue

        # The catalog is the protocol source of truth. Keep only the
        # operator-controlled enabled flag in the database.
        model.name = spec.name
        model.model_code = spec.code
        model.media_type = spec.media_type
        model.generation_path = spec.generation_path
        model.result_path = spec.result_path
        model.parameter_schema = json.dumps(
            spec.parameter_schema(),
            ensure_ascii=False,
        )
        model.capabilities = json.dumps(
            spec.capability_data(),
            ensure_ascii=False,
        )
        model.description = spec.description

    db.session.flush()
    for model in StudioModel.query.filter_by(provider_id=provider.id).all():
        if model.model_code not in catalog_codes:
            # Keep legacy rows for historical references, but stop exposing
            # them as active choices after a catalog revision.
            model.enabled = 0
    return catalog_specs


def seed_provider(
    *,
    seed_credentials=True,
    clear_credentials=False,
    provider_owner_type=None,
    provider_department_id=_DEFAULT_PROVIDER_DEPARTMENT,
):
    default_department = _studio_default_department()
    owner_type = PROVIDER_OWNER_DEPARTMENT
    if (
        provider_department_id is _DEFAULT_PROVIDER_DEPARTMENT
        or provider_department_id in (None, "")
    ):
        provider_department_id = (
            default_department.id if default_department else None
        )
    if provider_department_id is None:
        return None
    try:
        provider_department_id = int(provider_department_id)
    except (TypeError, ValueError):
        return None

    default_base_url = (
        str(os.getenv("STUDIO_DEFAULT_PROVIDER_URL") or "https://toapis.com")
        .strip()
        .rstrip("/")
        or "https://toapis.com"
    )
    provider = _find_seed_provider(
        "ToAPIs",
        owner_type,
        provider_department_id,
    )
    if not provider:
        provider = StudioProvider(
            name="ToAPIs",
            dept_id=provider_department_id,
            owner_type=owner_type,
            kind="relay",
            base_url=default_base_url,
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
        provider.owner_type = owner_type
        provider.dept_id = provider_department_id
        provider.kind = provider.kind or "relay"
        provider.base_url = (
            str(provider.base_url or "").strip().rstrip("/")
            or default_base_url
        )
        provider.generation_path = (
            provider.generation_path or "/v1/images/generations"
        )
        provider.result_path = (
            provider.result_path or "/v1/images/generations/{task_id}"
        )
        provider.balance_path = provider.balance_path or "/v1/user/balance"
        provider.token_balance_path = provider.token_balance_path or "/v1/balance"
        provider.auth_header = provider.auth_header or "Authorization"
        provider.auth_prefix = provider.auth_prefix or "Bearer"
        provider.timeout = max(30, int(provider.timeout or 120))
        provider.enabled = 1 if provider.enabled is None else provider.enabled
        provider.description = (
            provider.description or "ToAPIs 图片与视频异步生成接口"
        )

    _sync_catalog_models(provider)
    chat_model_filters = [
        StudioModel.media_type == "CHAT",
        StudioModel.enabled == 1,
        StudioProvider.enabled == 1,
    ]
    chat_model_filters.append(StudioProvider.dept_id == provider.dept_id)
    setting_department_id = provider.dept_id
    chat_models = (
        StudioModel.query.join(StudioProvider)
        .filter(*chat_model_filters)
        .order_by(StudioModel.id.asc())
        .all()
    )
    setting = StudioSetting.query.filter_by(
        setting_key=GLOBAL_CHAT_MODEL_SETTING_KEY,
        dept_id=setting_department_id,
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
                dept_id=setting_department_id,
                description="图片与视频创作在关联产品或 Skill 时使用的全局语言模型",
            )
            db.session.add(setting)
        setting.setting_value = str(selected_model.id)
    if clear_credentials:
        provider.api_key = None
    db.session.commit()
    return provider


def seed_kuaipao_provider(
    *,
    seed_credentials=True,
    clear_credentials=False,
    provider_owner_type=None,
    provider_department_id=_DEFAULT_PROVIDER_DEPARTMENT,
):
    """Seed the optional Kuaipao Responses provider without storing secrets in code."""

    default_department = _studio_default_department()
    owner_type = PROVIDER_OWNER_DEPARTMENT
    if (
        provider_department_id is _DEFAULT_PROVIDER_DEPARTMENT
        or provider_department_id in (None, "")
    ):
        provider_department_id = (
            default_department.id if default_department else None
        )
    if provider_department_id is None:
        return None, None
    try:
        provider_department_id = int(provider_department_id)
    except (TypeError, ValueError):
        return None, None

    default_base_url = (
        str(os.getenv("KUAIPAO_BASE_URL") or "https://kuaipao.pro/v1")
        .strip()
        .rstrip("/")
        or "https://kuaipao.pro/v1"
    )
    provider = _find_seed_provider(
        "快跑AI",
        owner_type,
        provider_department_id,
    )
    if not provider:
        provider = StudioProvider(
            name="快跑AI",
            dept_id=provider_department_id,
            owner_type=owner_type,
            kind="relay",
            base_url=default_base_url,
            generation_path="/responses",
            result_path=None,
            balance_path="/v1/user/balance",
            token_balance_path="/v1/balance",
            auth_header="Authorization",
            auth_prefix="Bearer",
            timeout=max(30, int(os.getenv("KUAIPAO_TIMEOUT") or 180)),
            enabled=1,
            description="快跑AI OpenAI 兼容 Responses API，支持 input_file 与 web_search",
        )
        db.session.add(provider)
        db.session.flush()
    else:
        provider.owner_type = owner_type
        provider.dept_id = provider_department_id
        provider.kind = provider.kind or "relay"
        provider.base_url = (
            str(provider.base_url or "").strip().rstrip("/")
            or default_base_url
        )
        provider.generation_path = "/responses"
        provider.result_path = None
        provider.balance_path = provider.balance_path or "/v1/user/balance"
        provider.token_balance_path = provider.token_balance_path or "/v1/balance"
        provider.auth_header = provider.auth_header or "Authorization"
        provider.auth_prefix = provider.auth_prefix or "Bearer"
        provider.timeout = max(
            30,
            int(os.getenv("KUAIPAO_TIMEOUT") or provider.timeout or 180),
        )
        provider.description = (
            provider.description
            or "快跑AI OpenAI 兼容 Responses API，支持 input_file 与 web_search"
        )

    configured_key = str(os.getenv("KUAIPAO_API_KEY") or "").strip()
    if seed_credentials and configured_key:
        provider.api_key = configured_key
    elif clear_credentials:
        provider.api_key = None

    catalog_specs = _sync_catalog_models(provider)
    catalog_codes = {spec.code for spec in catalog_specs}
    last_model = None
    for model in StudioModel.query.filter_by(
        provider_id=provider.id,
    ).order_by(StudioModel.id.asc()).all():
        if model.model_code in catalog_codes:
            last_model = model
    db.session.commit()
    return provider, last_model


def seed_jiekou_provider(
    *,
    seed_credentials=True,
    clear_credentials=False,
    provider_owner_type=None,
    provider_department_id=_DEFAULT_PROVIDER_DEPARTMENT,
):
    """Seed the Interface AI Responses provider without storing secrets in code."""

    default_department = _studio_default_department()
    owner_type = PROVIDER_OWNER_DEPARTMENT
    if (
        provider_department_id is _DEFAULT_PROVIDER_DEPARTMENT
        or provider_department_id in (None, "")
    ):
        provider_department_id = (
            default_department.id if default_department else None
        )
    if provider_department_id is None:
        return None
    try:
        provider_department_id = int(provider_department_id)
    except (TypeError, ValueError):
        return None

    default_base_url = (
        str(
            os.getenv("JIEKOU_BASE_URL")
            or "https://api.jiekou.ai/openai/v1"
        )
        .strip()
        .rstrip("/")
        or "https://api.jiekou.ai/openai/v1"
    )
    provider = _find_seed_provider(
        "接口AI",
        owner_type,
        provider_department_id,
    )
    if not provider:
        provider = StudioProvider(
            name="接口AI",
            dept_id=provider_department_id,
            owner_type=owner_type,
            kind="relay",
            base_url=default_base_url,
            generation_path="/responses",
            result_path=None,
            balance_path="/v1/user/balance",
            token_balance_path="/v1/balance",
            auth_header="Authorization",
            auth_prefix="Bearer",
            timeout=max(30, int(os.getenv("JIEKOU_TIMEOUT") or 600)),
            enabled=1,
            description=(
                "接口AI OpenAI 兼容 Responses API，支持 input_file、"
                "input_image 与 web_search"
            ),
        )
        db.session.add(provider)
        db.session.flush()
    else:
        provider.owner_type = owner_type
        provider.dept_id = provider_department_id
        provider.kind = provider.kind or "relay"
        provider.base_url = (
            str(provider.base_url or "").strip().rstrip("/")
            or default_base_url
        )
        provider.generation_path = "/responses"
        provider.result_path = None
        provider.balance_path = provider.balance_path or "/v1/user/balance"
        provider.token_balance_path = provider.token_balance_path or "/v1/balance"
        provider.auth_header = provider.auth_header or "Authorization"
        provider.auth_prefix = provider.auth_prefix or "Bearer"
        provider.timeout = max(
            30,
            int(os.getenv("JIEKOU_TIMEOUT") or provider.timeout or 600),
        )
        provider.enabled = 1 if provider.enabled is None else provider.enabled
        provider.description = (
            provider.description
            or "接口AI OpenAI 兼容 Responses API，支持 input_file、"
            "input_image 与 web_search"
        )

    configured_key = str(os.getenv("JIEKOU_API_KEY") or "").strip()
    if seed_credentials and configured_key:
        provider.api_key = configured_key
    elif clear_credentials:
        provider.api_key = None

    _sync_catalog_models(provider)
    db.session.commit()
    return provider


def disable_legacy_kuaipao_image_models():
    """Hide old quality-specific rows across every existing Kuaipao provider."""

    legacy_codes = set(KUAIPAO_LEGACY_IMAGE_MODEL_CODES)
    for provider in StudioProvider.query.all():
        if catalog_for_provider(provider).key != "kuaipao":
            continue
        for model in provider.models:
            if (
                model.media_type == "IMAGE"
                and str(model.model_code or "").strip().lower()
                in legacy_codes
            ):
                model.enabled = 0
    db.session.flush()


def ensure_default_provider_configs(department_id=None):
    """Ensure all built-in providers exist for one ownership scope.

    ``None`` denotes the real ``总项目`` department. A positive department id
    denotes an independent department scope. The operation is idempotent,
    fills missing protocol defaults, adds missing catalog models, and never
    writes an API key.
    """

    if department_id in (None, ""):
        root = _root_department()
        scoped_department_id = root.id if root else None
    else:
        try:
            scoped_department_id = int(department_id)
        except (TypeError, ValueError):
            raise ValueError("部门 ID 无效")
        if scoped_department_id <= 0:
            raise ValueError("部门 ID 无效")
        if not Dept.query.filter_by(id=scoped_department_id).first():
            raise ValueError("部门不存在")
    if scoped_department_id is None:
        raise ValueError("总项目部门不存在")

    toapis = seed_provider(
        seed_credentials=False,
        clear_credentials=False,
        provider_owner_type=PROVIDER_OWNER_DEPARTMENT,
        provider_department_id=scoped_department_id,
    )
    kuaipao, _ = seed_kuaipao_provider(
        seed_credentials=False,
        clear_credentials=False,
        provider_owner_type=PROVIDER_OWNER_DEPARTMENT,
        provider_department_id=scoped_department_id,
    )
    jiekou = seed_jiekou_provider(
        seed_credentials=False,
        clear_credentials=False,
        provider_owner_type=PROVIDER_OWNER_DEPARTMENT,
        provider_department_id=scoped_department_id,
    )
    return {
        "toapis": toapis,
        "kuaipao": kuaipao,
        "jiekou": jiekou,
    }


def seed_feedback_skill(seed_storage=True, force_storage_sync=False):
    """Create the built-in feedback Skill and persist its Markdown in storage."""

    content = load_feedback_skill_content()
    default_department = _studio_default_department()
    skill = StudioSkill.query.filter_by(code=FEEDBACK_SKILL_CODE).first()
    if skill and skill.storage_asset_id:
        storage_asset = StudioAsset.query.filter_by(
            id=skill.storage_asset_id,
            status="ACTIVE",
            purpose="SKILL",
        ).first()
        if storage_asset:
            if skill.dept_id is None and default_department:
                skill.dept_id = default_department.id
            if storage_asset.dept_id is None:
                storage_asset.dept_id = skill.dept_id
            try:
                stored_content = str(
                    FileService.read_text(
                        storage_asset,
                        filename=storage_asset.original_filename,
                        maximum_size=512000,
                    )
                    or ""
                ).strip()
            except Exception:
                stored_content = ""
            if stored_content and not force_storage_sync:
                # The GoFastDFS document is canonical. Do not let the
                # duplicated legacy columns make the Skill appear to have
                # local content or trigger another upload.
                skill.prompt_template = None
                skill.content = None
                skill.enabled = 1
                db.session.commit()
                return skill

    if not skill:
        skill = StudioSkill(
            dept_id=default_department.id if default_department else None,
            name=FEEDBACK_SKILL_NAME,
            code=FEEDBACK_SKILL_CODE,
            media_type="BOTH",
            version="1.0.0",
            tags="意见反馈,产品约束,图片,视频,电商",
            file_name=FEEDBACK_SKILL_FILE_NAME,
            file_type="md",
            content=content if not seed_storage else None,
            prompt_template=content if not seed_storage else None,
            negative_prompt="",
            enabled=1,
        )
        db.session.add(skill)
    else:
        # A manually edited built-in Skill keeps its content; only repair a
        # missing storage record so the Skill page can always download it.
        if not force_storage_sync:
            content = skill.content or content
        skill.name = skill.name or FEEDBACK_SKILL_NAME
        if skill.dept_id is None and default_department:
            skill.dept_id = default_department.id
        skill.media_type = "BOTH"
        skill.file_name = skill.file_name or FEEDBACK_SKILL_FILE_NAME
        skill.file_type = skill.file_type or "md"
        if not force_storage_sync:
            content = (
                str(skill.content or skill.prompt_template or "").strip()
                or content
            )
        if not seed_storage:
            skill.prompt_template = content
            skill.content = content
        skill.enabled = 1

    if not seed_storage:
        db.session.commit()
        return skill

    if force_storage_sync:
        force_replace_skill_storage(
            skill,
            content,
            skill.file_name or FEEDBACK_SKILL_FILE_NAME,
            created_by=skill.created_by,
            dept_id=skill.dept_id,
        )
        return skill

    stored = None
    try:
        stored = FileService.upload_bytes(
            content.encode("utf-8"),
            skill.file_name or FEEDBACK_SKILL_FILE_NAME,
            content_type="text/markdown",
            asset_type="FILE",
            purpose="SKILL",
            retention_policy=FileService.PERMANENT,
            created_by=skill.created_by,
            dept_id=skill.dept_id,
            record=False,
        )
        storage_asset = FileService.create_asset_record(
            stored,
            asset_type="FILE",
            purpose="SKILL",
            retention_policy=FileService.PERMANENT,
            created_by=skill.created_by,
            dept_id=skill.dept_id,
        )
        db.session.add(storage_asset)
        db.session.flush()
        skill.storage_asset_id = storage_asset.id
        # Store the editable body only in GoFastDFS after a successful
        # upload. MySQL keeps Skill metadata and the asset foreign key.
        skill.prompt_template = None
        skill.content = None
        db.session.commit()
    except Exception:
        db.session.rollback()
        if stored:
            try:
                FileService.delete_storage(
                    stored.storage_path,
                    checksum=stored.checksum,
                )
            except Exception:
                pass
        raise
    return skill


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
        elif is_seedance_model(model.model_code) and field == "generate_audio":
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


def initialize_studio(
    *,
    seed_credentials=True,
    clear_credentials=False,
    seed_storage=True,
    force_storage_sync=False,
    provider_owner_type=None,
    provider_department_id=_DEFAULT_PROVIDER_DEPARTMENT,
):
    """Create all tables and seed a usable administrator and starter configuration."""

    import applications.models  # noqa: F401

    db.create_all()
    seed_menu()
    # Materialize the same provider catalogs independently for every real
    # department. ``总项目`` is the admin's department, not a virtual owner
    # scope, so it receives the same built-in provider rows as every other
    # department.
    scopes = []
    departments = Dept.query.order_by(Dept.sort.asc(), Dept.id.asc()).all()
    scopes.extend(
        (PROVIDER_OWNER_DEPARTMENT, department.id)
        for department in departments
    )
    # Preserve compatibility with callers that explicitly target a department
    # not yet returned by the query (for example, during a department save).
    if (
        provider_department_id not in (_DEFAULT_PROVIDER_DEPARTMENT, None)
    ):
        try:
            explicit_scope = int(provider_department_id)
        except (TypeError, ValueError):
            explicit_scope = None
        if explicit_scope and (
            PROVIDER_OWNER_DEPARTMENT,
            explicit_scope,
        ) not in scopes:
            scopes.append((PROVIDER_OWNER_DEPARTMENT, explicit_scope))

    for owner_type, department_id in scopes:
        seed_provider(
            seed_credentials=seed_credentials,
            clear_credentials=clear_credentials,
            provider_owner_type=owner_type,
            provider_department_id=department_id,
        )
        seed_kuaipao_provider(
            seed_credentials=seed_credentials,
            clear_credentials=clear_credentials,
            provider_owner_type=owner_type,
            provider_department_id=department_id,
        )
        seed_jiekou_provider(
            seed_credentials=seed_credentials,
            clear_credentials=clear_credentials,
            provider_owner_type=owner_type,
            provider_department_id=department_id,
        )
    disable_legacy_kuaipao_image_models()
    seed_feedback_skill(
        seed_storage=seed_storage,
        force_storage_sync=force_storage_sync,
    )
