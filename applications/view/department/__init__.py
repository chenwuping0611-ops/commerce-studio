import re

from flask import Blueprint, abort, current_app, render_template, request, jsonify
from flask_login import current_user
from marshmallow import ValidationError

from applications.common import curd
from applications.common.utils.http import success_api, fail_api
from applications.common.utils.rights import authorize
from applications.common.utils import validate
from applications.common.scope import (
    department_in_scope,
    is_department_admin_user,
    is_super_admin_user,
    managed_department_ids,
    user_department_id,
)
from applications.extensions import db
from applications.models import Dept, User
from applications.schemas import DeptOutSchema
from applications.schemas.admin_dept import DeptInSchema

dept_bp = Blueprint('dept', __name__, url_prefix='/dept')


def register_dept_views(app):
    app.register_blueprint(dept_bp)


def _dept_query():
    if is_super_admin_user():
        return Dept.query
    if not is_department_admin_user():
        return Dept.query.filter(False)
    return Dept.query.filter(Dept.id.in_(managed_department_ids() or [-1]))


def _can_manage_dept(dept):
    return bool(
        dept
        and (
            is_super_admin_user()
            or department_in_scope(dept.id)
        )
    )


def _can_manage_departments():
    return is_super_admin_user() or is_department_admin_user()


def _user_role_label(user):
    """Return a compact role label for a read-only department-tree user row."""

    roles = user.role.all() if hasattr(user.role, "all") else list(user.role)
    labels = []
    for role in roles:
        code = str(getattr(role, "code", "") or "").strip()
        if code == "admin":
            label = "超级管理员"
        elif code == "dept_admin":
            label = "部门管理员"
        else:
            label = str(getattr(role, "name", "") or "").strip()
            if not label:
                label = "AI 创作用户"
        if label not in labels:
            labels.append(label)
    return "、".join(labels) or "AI 创作用户"


def _department_rows(departments, include_users=False):
    """Serialize visible departments and, optionally, their user children.

    The user rows are deliberately added only for the department-management
    table.  The pure department tree is also used by user forms and the
    "new department" parent selector, where user nodes must never be valid
    parents.
    """

    department_rows = curd.model_to_dicts(
        schema=DeptOutSchema,
        data=departments,
    )
    visible_ids = {
        int(item["deptId"])
        for item in department_rows
        if item.get("deptId") is not None
    }
    for item in department_rows:
        parent_id = item.get("parentId")
        item["parentId"] = parent_id if parent_id in visible_ids else 0
        item["nodeType"] = "DEPARTMENT"

    if not include_users or not visible_ids:
        return department_rows

    users = (
        User.query.filter(User.dept_id.in_(visible_ids))
        .order_by(User.dept_id.asc(), User.id.asc())
        .all()
    )
    users_by_department = {}
    for user in users:
        # ``admin`` is the reserved system identity. It is already represented
        # by the top-level ``总项目`` department and must not appear as a
        # second user leaf under that department.
        if str(user.username or "").strip().lower() == "admin":
            continue
        users_by_department.setdefault(int(user.dept_id), []).append(user)

    rows = []
    for department in department_rows:
        rows.append(department)
        for user in users_by_department.get(int(department["deptId"]), []):
            username = str(user.username or "").strip()
            realname = str(user.realname or "").strip() or username
            rows.append(
                {
                    "deptId": f"user-{user.id}",
                    "parentId": int(department["deptId"]),
                    "deptName": (
                        f"{realname}（{username}）"
                        if username and realname != username
                        else realname or username
                    ),
                    "leader": _user_role_label(user),
                    "status": "启用" if user.enable else "禁用",
                    "sort": "",
                    "nodeType": "USER",
                    "userId": user.id,
                    "username": username,
                }
            )
    return rows


_INVALID_INTEGER = object()


def _coerce_integer(value, default=None):
    """Convert form values to integers without accepting JS objects/booleans."""

    if value is None:
        return default
    if isinstance(value, bool):
        return _INVALID_INTEGER
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return default
    if not re.fullmatch(r"[+-]?\d+", text):
        return _INVALID_INTEGER
    try:
        return int(text)
    except (TypeError, ValueError):
        return _INVALID_INTEGER


def _load_department_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, "部门数据格式不正确"

    parent_id = _coerce_integer(payload.get("parentId"), default=0)
    if parent_id is _INVALID_INTEGER or parent_id < 0:
        return None, "parentId不是合法整数"

    sort = _coerce_integer(payload.get("sort"), default=0)
    if sort is _INVALID_INTEGER:
        return None, "sort不是合法整数"

    normalized = {
        "parentId": parent_id,
        "deptName": payload.get("deptName"),
        "leader": payload.get("leader") or "",
        "status": str(payload.get("status") or "1"),
        "sort": sort,
    }
    try:
        return DeptInSchema().load(normalized), None
    except ValidationError as exc:
        for field, messages in exc.messages.items():
            message = messages[0] if isinstance(messages, list) else messages
            return None, f"{field}{message}"
    return None, "部门数据校验失败"


@dept_bp.get('/')
@authorize("admin:dept:main", log=True)
def main():
    if not _can_manage_departments():
        abort(403)
    return render_template(
        'admin/dept/main.html',
        is_super_admin=is_super_admin_user(),
    )


@dept_bp.post('/data')
@authorize("admin:dept:main", log=True)
def data():
    if not _can_manage_departments():
        return jsonify(success=False, msg="权限不足"), 403
    dept = _dept_query().order_by(Dept.sort).all()
    include_users = str(request.args.get("include_users") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    power_data = _department_rows(dept, include_users=include_users)
    res = {
        "data": power_data
    }
    return jsonify(res)


@dept_bp.get('/add')
@authorize("admin:dept:add", log=True)
def add():
    if not _can_manage_departments():
        abort(403)
    if not is_super_admin_user():
        # Departments are a flat business boundary. A department admin
        # manages users and data inside the existing department, not the
        # department tree itself.
        abort(403)
    return render_template(
        'admin/dept/add.html',
        departments=_dept_query().order_by(Dept.sort).all(),
        current_dept_id=user_department_id(),
        is_super_admin=is_super_admin_user(),
    )


@dept_bp.get('/tree')
@authorize("admin:dept:main", log=True)
def tree():
    if not _can_manage_departments():
        return jsonify(success=False, msg="权限不足"), 403
    dept = _dept_query().order_by(Dept.sort).all()
    power_data = _department_rows(dept)
    res = {
        "status": {"code": 200, "message": "默认"},
        "data": power_data

    }
    return jsonify(res)


@dept_bp.post('/save')
@authorize("admin:dept:add", log=True)
def save():
    if not _can_manage_departments():
        return fail_api(msg="只有超级管理员或部门管理员可以管理部门")
    if not is_super_admin_user():
        return fail_api(msg="部门管理员不能新增下级部门")
    args, error = _load_department_payload()
    if error:
        return fail_api(msg=error)
    parent_id = args.get("parentId", 0)
    parent = (
        Dept.query.filter_by(id=parent_id).first()
        if parent_id
        else None
    )
    if parent_id and not parent:
        return fail_api(msg="上级部门不存在")
    dept_name = validate.xss_escape(args.get("deptName")).strip()
    leader = validate.xss_escape(args.get("leader") or "").strip()
    if not dept_name:
        return fail_api(msg="部门名称不能为空")
    dept = Dept(
        parent_id=parent_id,
        dept_name=dept_name,
        sort=args.get("sort") or 0,
        leader=leader,
        status=int(args.get("status") or "1"),
    )
    if not is_super_admin_user():
        # The model inherits scope through the parent; this is the only
        # assignment path available to a department administrator.
        dept.remark = f"created_by={current_user.id}"
    db.session.add(dept)
    db.session.commit()
    try:
        # Every real department owns independent built-in provider
        # configurations. The helper is idempotent and never writes a key.
        from applications.studio.bootstrap import ensure_default_provider_configs

        ensure_default_provider_configs(dept.id)
    except Exception:
        # Department creation has already committed. Keep the department
        # usable and leave a clear server-side trail for a later studio-init
        # repair instead of turning a successful department save into a 500.
        db.session.rollback()
        current_app.logger.exception(
            "department created but default provider initialization failed: dept_id=%s",
            dept.id,
        )
    return success_api(msg="成功")


@dept_bp.get('/edit')
@authorize("admin:dept:edit", log=True)
def edit():
    if not _can_manage_departments():
        abort(403)
    _id = request.args.get("deptId")
    dept = _dept_query().filter_by(id=_id).first()
    if not _can_manage_dept(dept):
        return fail_api(msg="部门不存在或无权访问")
    return render_template('admin/dept/edit.html', dept=dept)


# 启用
@dept_bp.put('/enable')
@authorize("admin:dept:edit", log=True)
def enable():
    if not _can_manage_departments():
        return fail_api(msg="只有超级管理员或部门管理员可以管理部门")
    id = request.json.get('deptId')
    if id:
        if not _can_manage_dept(_dept_query().filter_by(id=id).first()):
            return fail_api(msg="部门不存在或无权访问")
        enable = 1
        d = Dept.query.filter_by(id=id).update({"status": enable})
        if d:
            db.session.commit()
            return success_api(msg="启用成功")
        return fail_api(msg="出错啦")
    return fail_api(msg="数据错误")


# 禁用
@dept_bp.put('/disable')
@authorize("admin:dept:edit", log=True)
def dis_enable():
    if not _can_manage_departments():
        return fail_api(msg="只有超级管理员或部门管理员可以管理部门")
    id = request.json.get('deptId')
    if id:
        if not _can_manage_dept(_dept_query().filter_by(id=id).first()):
            return fail_api(msg="部门不存在或无权访问")
        enable = 0
        d = Dept.query.filter_by(id=id).update({"status": enable})
        if d:
            db.session.commit()
            return success_api(msg="禁用成功")
        return fail_api(msg="出错啦")
    return fail_api(msg="数据错误")


@dept_bp.put('/update')
@authorize("admin:dept:edit", log=True)
def update():
    if not _can_manage_departments():
        return fail_api(msg="只有超级管理员或部门管理员可以管理部门")
    payload = request.json or {}
    id = payload.get("deptId")
    dept = _dept_query().filter_by(id=id).first()
    if not _can_manage_dept(dept):
        return fail_api(msg="部门不存在或无权访问")
    data = {
        "dept_name": validate.xss_escape(payload.get("deptName")),
        "sort": validate.xss_escape(payload.get("sort")),
        "leader": validate.xss_escape(payload.get("leader") or ""),
        "status": validate.xss_escape(payload.get("status")),
    }
    d = Dept.query.filter_by(id=id).update(data)
    if not d:
        return fail_api(msg="更新失败")
    db.session.commit()
    return success_api(msg="更新成功")


@dept_bp.delete('/remove/<int:_id>')
@authorize("admin:dept:remove", log=True)
def remove(_id):
    if not _can_manage_departments():
        return fail_api(msg="只有超级管理员或部门管理员可以删除部门")
    dept = _dept_query().filter_by(id=_id).first()
    if not _can_manage_dept(dept):
        return fail_api(msg="部门不存在或无权访问")
    if not is_super_admin_user() and dept.id == user_department_id():
        return fail_api(msg="不能删除当前管理部门")
    if Dept.query.filter_by(parent_id=_id).count():
        return fail_api(msg="请先处理下级部门")
    if User.query.filter_by(dept_id=_id).count():
        return fail_api(msg="部门下仍有用户，不能物理删除，请先调整用户所属部门")
    d = Dept.query.filter_by(id=_id).delete()
    if not d:
        return fail_api(msg="删除失败")
    db.session.commit()
    return success_api(msg="删除成功")
