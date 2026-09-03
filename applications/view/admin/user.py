from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import and_, desc, or_

from applications.common import curd
from applications.common.curd import (
    disable_status,
    enable_status,
    model_to_dicts,
)
from applications.common.helper import ModelFilter
from applications.common.scope import (
    can_assign_role,
    can_change_password,
    can_manage_user,
    department_in_scope,
    has_effective_permission,
    is_department_admin_user,
    is_super_admin_user,
    is_reserved_role_code,
    managed_department_ids,
    scope_query,
    user_department_id,
)
from applications.common.utils.http import fail_api, success_api, table_api
from applications.common.utils.rights import authorize
from applications.common.utils.validate import xss_escape
from applications.extensions import db
from applications.models import AdminLog, Dept, Role, User
from applications.schemas import UserOutSchema
from applications.studio.bootstrap import DEFAULT_STUDIO_ROLE_CODE


admin_user = Blueprint("adminUser", __name__, url_prefix="/admin/user")


def _parse_role_ids(raw_role_ids):
    """Normalize comma-separated role ids submitted by Pear forms."""

    if not raw_role_ids:
        return []
    values = (
        raw_role_ids
        if isinstance(raw_role_ids, list)
        else str(raw_role_ids).split(",")
    )
    role_ids = []
    for value in values:
        value = str(value).strip()
        if value.isdigit() and int(value) > 0:
            role_ids.append(int(value))
    return list(dict.fromkeys(role_ids))


def _get_enabled_roles(role_ids=None):
    query = Role.query.filter_by(enable=1)
    if is_super_admin_user():
        # ``admin`` is an account-reserved identity and can never be selected
        # for a second account.
        query = query.filter(Role.code != "admin")
    elif is_department_admin_user():
        visible = managed_department_ids() or [-1]
        query = query.filter(
            or_(
                Role.dept_id.in_(visible),
                and_(
                    Role.dept_id.is_(None),
                    Role.code == DEFAULT_STUDIO_ROLE_CODE,
                ),
            )
        )
    else:
        return []

    if role_ids is not None:
        if not role_ids:
            return []
        query = query.filter(Role.id.in_(role_ids))
    return query.order_by(Role.sort.asc(), Role.id.asc()).all()


def _visible_departments():
    if is_super_admin_user():
        return Dept.query.order_by(Dept.sort.asc(), Dept.id.asc()).all()
    return (
        Dept.query.filter(Dept.id.in_(managed_department_ids() or [-1]))
        .order_by(Dept.sort.asc(), Dept.id.asc())
        .all()
    )


def _can_manage_user(user):
    return can_manage_user(current_user, user)


def _can_manage_user_accounts():
    return is_super_admin_user() or is_department_admin_user()


def _can_change_password_for_request(target):
    """Allow self-service, but protect delegated password changes by permission."""

    if not target or not can_change_password(current_user, target):
        return False
    if getattr(target, "id", None) == getattr(current_user, "id", None):
        return True
    return has_effective_permission("admin:user:edit")


def _validate_roles(roles, target=None):
    if any(
        not can_assign_role(current_user, role, target=target)
        for role in roles
    ):
        return False
    return True


def _department_exists(department_id):
    return bool(
        department_id is not None
        and Dept.query.filter_by(id=department_id).first()
    )


def _root_department_id():
    root = (
        Dept.query.filter(
            Dept.dept_name == "总项目",
            (Dept.parent_id == 0) | (Dept.parent_id.is_(None)),
        )
        .order_by(Dept.id.asc())
        .first()
    )
    return root.id if root else None


@admin_user.get("/")
@authorize("admin:user:main", log=True)
def main():
    return render_template(
        "admin/user/main.html",
        is_super_admin=is_super_admin_user(),
        is_department_admin=is_department_admin_user(),
        can_manage_accounts=_can_manage_user_accounts(),
    )


@admin_user.get("/data")
@authorize("admin:user:main", log=True)
def data():
    real_name = xss_escape(request.args.get("realName", type=str))
    username = xss_escape(request.args.get("username", type=str))
    dept_id = request.args.get("deptId", type=int)

    mf = ModelFilter()
    if real_name:
        mf.contains(field_name="realname", value=real_name)
    if username:
        mf.contains(field_name="username", value=username)
    if dept_id:
        mf.exact(field_name="dept_id", value=dept_id)

    user_query = scope_query(User.query, User)
    if not is_super_admin_user():
        # ``admin`` is a reserved system identity. It must stay invisible to
        # department-scoped and self-scoped user listings even if legacy data
        # put it in the same department.
        user_query = user_query.filter(User.username != "admin")
    users = user_query.filter(mf.get_filter(model=User)).layui_paginate()
    return table_api(
        data=model_to_dicts(schema=UserOutSchema, data=users.items),
        count=users.total,
    )


@admin_user.get("/add")
@authorize("admin:user:add", log=True)
def add():
    if not _can_manage_user_accounts():
        abort(403)
    return render_template(
        "admin/user/add.html",
        roles=_get_enabled_roles(),
        departments=_visible_departments(),
        current_dept_id=user_department_id(),
        is_super_admin=is_super_admin_user(),
    )


@admin_user.post("/save")
@authorize("admin:user:add", log=True)
def save():
    if not _can_manage_user_accounts():
        return fail_api(msg="只有管理员可以新增用户")

    req_json = request.json or {}
    username = xss_escape(req_json.get("username"))
    real_name = xss_escape(req_json.get("realName"))
    password = xss_escape(req_json.get("password"))
    role_ids = _parse_role_ids(req_json.get("roleIds") or "")
    requested_dept_id = req_json.get("deptId")

    if not username or username == "admin" or not real_name or not password:
        return fail_api(msg="账号姓名密码不得为空，且不能使用系统保留账号")
    if len(password) < 6:
        return fail_api(msg="密码长度不能少于6位")
    if User.query.filter_by(username=username).count():
        return fail_api(msg="用户已经存在")

    roles = _get_enabled_roles(role_ids)
    if role_ids and len(roles) != len(role_ids):
        return fail_api(msg="只能分配已启用且在管理范围内的角色")
    if roles and not _validate_roles(roles):
        return fail_api(msg="不能分配系统保留角色或其他部门角色")
    if not roles:
        default_role = Role.query.filter_by(
            code=DEFAULT_STUDIO_ROLE_CODE,
            enable=1,
        ).first()
        if default_role:
            roles = [default_role]
    if not roles:
        return fail_api(msg="请先配置可用角色")

    if is_super_admin_user():
        try:
            dept_id = int(requested_dept_id) if requested_dept_id else None
        except (TypeError, ValueError):
            return fail_api(msg="部门选择无效")
        if dept_id is None:
            return fail_api(msg="普通用户必须指定所属部门")
        if not _department_exists(dept_id):
            return fail_api(msg="部门不存在")
        if not department_in_scope(dept_id):
            return fail_api(msg="无权分配该部门")
        if dept_id == _root_department_id():
            return fail_api(msg="总项目仅供超级管理员使用")
    else:
        dept_id = user_department_id()
        if dept_id is None:
            return fail_api(msg="请先为当前管理员指定管理部门")

    user = User(
        username=username,
        realname=real_name,
        enable=1,
        dept_id=dept_id,
    )
    user.set_password(password)
    user.role = roles
    db.session.add(user)
    db.session.commit()
    return success_api(msg="增加成功")


@admin_user.delete("/remove/<int:id>")
@authorize("admin:user:remove", log=True)
def delete(id):
    if not _can_manage_user_accounts():
        return fail_api(msg="只有管理员可以删除用户")
    user = User.query.filter_by(id=id).first()
    if not user or user.username == "admin" or not _can_manage_user(user):
        return fail_api(msg="无权操作该用户")
    user.role = []
    db.session.delete(user)
    db.session.commit()
    return success_api(msg="删除成功")


@admin_user.get("/edit/<int:id>")
@authorize("admin:user:edit", log=True)
def edit(id):
    user = curd.get_one_by_id(User, id)
    if not user or not _can_manage_user(user):
        return fail_api(msg="无权操作该用户")
    return render_template(
        "admin/user/edit.html",
        user=user,
        roles=_get_enabled_roles(),
        checked_roles=[
            role.id for role in user.role if role.enable == 1
        ],
        departments=_visible_departments(),
        current_dept_id=user_department_id(),
        is_super_admin=is_super_admin_user(),
    )


@admin_user.put("/update")
@authorize("admin:user:edit", log=True)
def update():
    if not _can_manage_user_accounts():
        return fail_api(msg="只有管理员可以编辑用户")

    req_json = request.json or {}
    user_id = req_json.get("userId")
    user = User.query.filter_by(id=user_id).first()
    if not user:
        return fail_api(msg="用户不存在")
    if not _can_manage_user(user):
        return fail_api(msg="无权操作该用户")

    real_name = xss_escape(req_json.get("realName"))
    if not real_name:
        return fail_api(msg="姓名不得为空")

    if user.username == "admin":
        # ``admin`` is a reserved identity. It may update its display name,
        # but no request can rename, demote, or move it out of the root scope.
        if not is_super_admin_user():
            return fail_api(msg="无权操作该用户")
        admin_role = Role.query.filter_by(code="admin", enable=1).first()
        if not admin_role:
            return fail_api(msg="超级管理员角色未初始化")
        root = (
            Dept.query.filter(
                Dept.dept_name == "总项目",
                (Dept.parent_id == 0) | (Dept.parent_id.is_(None)),
            )
            .order_by(Dept.id.asc())
            .first()
        )
        user.username = "admin"
        user.realname = real_name
        if root:
            user.dept_id = root.id
        user.role = [admin_role]
        db.session.commit()
        return success_api(msg="更新成功")

    username = xss_escape(req_json.get("username"))
    if not username or username == "admin":
        return fail_api(msg="账号不得为空，且不能使用系统保留账号")
    duplicate = User.query.filter(
        User.username == username,
        User.id != user.id,
    ).first()
    if duplicate:
        return fail_api(msg="用户已经存在")

    roles = _get_enabled_roles(_parse_role_ids(req_json.get("roleIds")))
    if req_json.get("roleIds") and len(roles) != len(
        _parse_role_ids(req_json.get("roleIds"))
    ):
        return fail_api(msg="只能分配已启用且在管理范围内的角色")
    if roles and not _validate_roles(roles, target=user):
        return fail_api(msg="不能分配系统保留角色或其他部门角色")
    if not roles:
        default_role = Role.query.filter_by(
            code=DEFAULT_STUDIO_ROLE_CODE,
            enable=1,
        ).first()
        if default_role:
            roles = [default_role]

    if is_super_admin_user():
        try:
            target_dept_id = int(req_json.get("deptId"))
        except (TypeError, ValueError):
            return fail_api(msg="部门选择无效")
        if not _department_exists(target_dept_id):
            return fail_api(msg="部门不存在")
        if not department_in_scope(target_dept_id):
            return fail_api(msg="无权分配该部门")
        if target_dept_id == _root_department_id():
            return fail_api(msg="总项目仅供超级管理员使用")
        user.dept_id = target_dept_id
    else:
        user.dept_id = user_department_id()
        if user.dept_id is None:
            return fail_api(msg="请先为当前管理员指定管理部门")

    user.username = username
    user.realname = real_name
    user.role = roles
    db.session.commit()
    return success_api(msg="更新成功")


@admin_user.get("/center")
@login_required
def center():
    user_logs = (
        AdminLog.query.filter_by(
            url="/passport/login",
            uid=current_user.id,
        )
        .order_by(desc(AdminLog.create_time))
        .limit(10)
    )
    return render_template(
        "admin/user/center.html",
        user_info=current_user,
        user_logs=user_logs,
    )


@admin_user.get("/profile")
@login_required
def profile():
    return render_template("admin/user/profile.html")


@admin_user.put("/updateAvatar")
@login_required
def update_avatar():
    payload = request.json or {}
    avatar = payload.get("avatar") or {}
    url = avatar.get("src") if isinstance(avatar, dict) else None
    result = User.query.filter_by(id=current_user.id).update({"avatar": url})
    db.session.commit()
    return success_api(msg="修改成功") if result else fail_api(msg="出错啦")


@admin_user.put("/updateInfo")
@login_required
def update_info():
    req_json = request.json or {}
    result = User.query.filter_by(id=current_user.id).update(
        {
            "realname": req_json.get("realName"),
            "remark": req_json.get("details"),
        }
    )
    db.session.commit()
    return success_api(msg="更新成功") if result else fail_api(msg="出错啦")


@admin_user.get("/editPassword")
@login_required
def edit_password():
    requested_id = request.args.get("userId", type=int)
    target = (
        User.query.filter_by(id=requested_id).first()
        if requested_id
        else current_user
    )
    if not _can_change_password_for_request(target):
        abort(403)
    return render_template(
        "admin/user/edit_password.html",
        target_user=target,
    )


@admin_user.put("/editPassword")
@login_required
def edit_password_put():
    payload = request.json or {}
    target_id = payload.get("userId")
    target = (
        User.query.filter_by(id=target_id).first()
        if target_id not in (None, "")
        else current_user
    )
    if not _can_change_password_for_request(target):
        return fail_api("无权修改该用户密码")

    new_password = str(payload.get("newPassword") or "")
    confirm_password = str(payload.get("confirmPassword") or "")
    if not new_password:
        return fail_api("新密码不得为空")
    if len(new_password) < 6:
        return fail_api("新密码长度不能少于6位")
    if new_password != confirm_password:
        return fail_api("两次密码不一致")

    target.set_password(new_password)
    db.session.add(target)
    db.session.commit()

    from applications.common.admin_log import admin_log

    admin_log(
        request,
        is_access=True,
        desc=(
            f"修改用户密码 target_user_id={target.id} "
            f"target_username={target.username}"
        ),
    )
    return success_api("密码修改成功")


@admin_user.put("/enable")
@authorize("admin:user:edit", log=True)
def enable():
    if not _can_manage_user_accounts():
        return fail_api(msg="只有管理员可以修改用户状态")
    user_id = (request.json or {}).get("userId")
    user = User.query.filter_by(id=user_id).first()
    if not user or user.username == "admin" or not _can_manage_user(user):
        return fail_api(msg="无权操作该用户")
    result = enable_status(model=User, id=user_id)
    return success_api(msg="启动成功") if result else fail_api(msg="出错啦")


@admin_user.put("/disable")
@authorize("admin:user:edit", log=True)
def dis_enable():
    if not _can_manage_user_accounts():
        return fail_api(msg="只有管理员可以修改用户状态")
    user_id = (request.json or {}).get("userId")
    user = User.query.filter_by(id=user_id).first()
    if not user or user.username == "admin" or not _can_manage_user(user):
        return fail_api(msg="无权操作该用户")
    result = disable_status(model=User, id=user_id)
    return success_api(msg="禁用成功") if result else fail_api(msg="出错啦")


@admin_user.delete("/batchRemove")
@authorize("admin:user:remove", log=True)
def batch_remove():
    if not _can_manage_user_accounts():
        return fail_api(msg="只有管理员可以删除用户")
    ids = request.form.getlist("ids[]")
    for user_id in ids:
        user = User.query.filter_by(id=user_id).first()
        if user and user.username != "admin" and _can_manage_user(user):
            user.role = []
            db.session.delete(user)
    db.session.commit()
    return success_api(msg="批量删除成功")
