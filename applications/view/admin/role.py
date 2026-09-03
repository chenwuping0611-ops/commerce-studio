from flask import Blueprint, abort, render_template, request, jsonify
from flask_login import current_user, login_required
from sqlalchemy import and_, or_
from applications.common.curd import model_to_dicts, enable_status, disable_status, get_one_by_id
from applications.common.helper import ModelFilter
from applications.common.utils.http import table_api, success_api, fail_api
from applications.common.utils.rights import authorize
from applications.common.utils.validate import xss_escape
from applications.common.scope import (
    department_in_scope,
    effective_permission_codes,
    is_super_admin_user,
    is_department_admin_user,
    managed_department_ids,
    RESERVED_ROLE_CODES,
    scope_query,
    user_department_id,
)
from applications.extensions import db
from applications.models import Role, Power, User
from applications.schemas import RoleOutSchema, PowerOutSchema2

admin_role = Blueprint('adminRole', __name__, url_prefix='/admin/role')


def _role_query():
    if is_super_admin_user():
        return Role.query
    if not is_department_admin_user():
        return Role.query.filter(False)
    visible = managed_department_ids() or [-1]
    return Role.query.filter(
        or_(
            Role.dept_id.in_(visible),
            and_(
                Role.dept_id.is_(None),
                Role.code == "studio_user",
            ),
        )
    )


def _can_manage_role(role):
    if not role:
        return False
    if is_super_admin_user():
        return True
    return (
        role.dept_id is not None
        and department_in_scope(role.dept_id, include_descendants=False)
        and role.code not in ("admin", "dept_admin")
    )


def _can_manage_roles():
    return is_super_admin_user() or is_department_admin_user()


def _allowed_power_ids():
    assigned_codes = effective_permission_codes(current_user)
    return {
        power.id
        for power in Power.query.filter_by(enable=1).all()
        if power and power.code and power.code in assigned_codes
    }


# 用户管理
@admin_role.get('/')
@authorize("admin:role:main", log=True)
def main():
    if not _can_manage_roles():
        abort(403)
    return render_template('admin/role/main.html')


# 表格数据
@admin_role.get('/data')
@authorize("admin:role:main", log=True)
def table():
    if not _can_manage_roles():
        abort(403)
    # 获取请求参数
    role_name = xss_escape(request.args.get('roleName', type=str))
    role_code = xss_escape(request.args.get('roleCode', type=str))
    # 查询参数构造
    mf = ModelFilter()
    if role_name:
        mf.vague(field_name="name", value=role_name)
    if role_code:
        mf.vague(field_name="code", value=role_code)
    # orm查询
    # 使用分页获取data需要.items
    role = _role_query().filter(mf.get_filter(Role)).layui_paginate()
    count = role.total
    # 返回api
    return table_api(data=model_to_dicts(schema=RoleOutSchema, data=role.items), count=count)


# 角色增加
@admin_role.get('/add')
@authorize("admin:role:add", log=True)
def add():
    if not _can_manage_roles():
        abort(403)
    return render_template('admin/role/add.html')


# 角色增加
@admin_role.post('/save')
@authorize("admin:role:add", log=True)
def save():
    if not _can_manage_roles():
        return fail_api(msg="只有超级管理员或部门管理员可以管理角色")
    req = request.json
    details = xss_escape(req.get("details"))
    enable = xss_escape(req.get("enable"))
    roleCode = xss_escape(req.get("roleCode"))
    roleName = xss_escape(req.get("roleName"))
    sort = xss_escape(req.get("sort"))
    if not roleCode or not roleName:
        return fail_api(msg="角色标识和角色名称不能为空")
    if roleCode in RESERVED_ROLE_CODES:
        return fail_api(msg="系统保留角色只能由系统初始化")
    if Role.query.filter_by(code=roleCode).first():
        return fail_api(msg="角色标识已经存在")
    if not is_super_admin_user() and user_department_id() is None:
        return fail_api(msg="请先为当前管理员指定管理部门")
    role = Role(
        details=details,
        enable=enable,
        code=roleCode,
        name=roleName,
        sort=sort,
        dept_id=None if is_super_admin_user() else user_department_id(),
        created_by=None if is_super_admin_user() else current_user.id,
    )
    db.session.add(role)
    db.session.commit()
    return success_api(msg="成功")


# 角色授权
@admin_role.get('/power/<int:_id>')
@authorize("admin:role:power", log=True)
def power(_id):
    if not _can_manage_roles():
        abort(403)
    return render_template('admin/role/power.html', id=_id)


# 获取角色权限
@admin_role.get('/getRolePower/<int:id>')
@authorize("admin:role:main", log=True)
def get_role_power(id):
    if not _can_manage_roles():
        return jsonify(success=False, msg="权限不足"), 403
    role = _role_query().filter_by(id=id).first()
    if not role:
        return jsonify(success=False, msg="角色不存在或无权访问"), 404
    check_powers = role.power
    check_powers_list = []
    for cp in check_powers:
        check_powers_list.append(cp.id)
    powers = [
        power for power in Power.query.all()
        if power.id in _allowed_power_ids()
    ]
    power_schema = PowerOutSchema2(many=True)  # 用已继承ma.ModelSchema类的自定制类生成序列化类
    output = power_schema.dump(powers)  # 生成可序列化对象
    for i in output:
        if int(i.get("powerId")) in check_powers_list:
            i["checkArr"] = "1"
        else:
            i["checkArr"] = "0"
    res = {
        "data": output,
        "status": {"code": 200, "message": "默认"}
    }
    return jsonify(res)


# 保存角色权限
@admin_role.put('/saveRolePower')
@authorize("admin:role:edit", log=True)
def save_role_power():
    if not _can_manage_roles():
        return fail_api(msg="只有超级管理员或部门管理员可以授权")
    req_form = request.form
    power_ids = req_form.get("powerIds")
    power_list = (power_ids or "").split(',')
    role_id = req_form.get("roleId")
    role = _role_query().filter_by(id=role_id).first()
    if not _can_manage_role(role):
        return fail_api(msg="角色不存在或无权访问")

    requested_ids = [item for item in power_list if str(item).isdigit()]
    powers = Power.query.filter(
        Power.id.in_(requested_ids),
        Power.enable == 1,
    ).all()
    if len(powers) != len(set(requested_ids)):
        return fail_api(msg="只能授权已启用的权限")
    if any(power.id not in _allowed_power_ids() for power in powers):
        return fail_api(msg="不能授予超出自身范围的权限")
    role.power = powers
    
    db.session.commit()
    return success_api(msg="授权成功")


# 角色编辑
@admin_role.get('/edit/<int:id>')
@authorize("admin:role:edit", log=True)
def edit(id):
    if not _can_manage_roles():
        abort(403)
    r = _role_query().filter_by(id=id).first()
    if not _can_manage_role(r):
        return fail_api(msg="角色不存在或无权访问")
    return render_template('admin/role/edit.html', role=r)


# 更新角色
@admin_role.put('/update')
@authorize("admin:role:edit", log=True)
def update():
    if not _can_manage_roles():
        return fail_api(msg="只有超级管理员或部门管理员可以管理角色")
    req_json = request.json
    id = req_json.get("roleId")
    data = {
        "code": xss_escape(req_json.get("roleCode")),
        "name": xss_escape(req_json.get("roleName")),
        "sort": xss_escape(req_json.get("sort")),
        "enable": xss_escape(req_json.get("enable")),
        "details": xss_escape(req_json.get("details"))
    }
    role_obj = _role_query().filter_by(id=id).first()
    if not _can_manage_role(role_obj):
        return fail_api(msg="角色不存在或无权访问")
    if role_obj.code in RESERVED_ROLE_CODES:
        if data["code"] != role_obj.code:
            return fail_api(msg="系统保留角色标识不可修改")
    elif data["code"] in RESERVED_ROLE_CODES:
        return fail_api(msg="内置管理员角色标识不可分配给自定义角色")
    duplicate = Role.query.filter(
        Role.code == data["code"],
        Role.id != role_obj.id,
    ).first()
    if duplicate:
        return fail_api(msg="角色标识已经存在")
    role = Role.query.filter_by(id=id).update(data)
    db.session.commit()
    if not role:
        return fail_api(msg="更新角色失败")
    return success_api(msg="更新角色成功")


# 启用用户
@admin_role.put('/enable')
@authorize("admin:role:edit", log=True)
def enable():
    if not _can_manage_roles():
        return fail_api(msg="只有超级管理员或部门管理员可以管理角色")
    id = request.json.get('roleId')
    if id:
        if not _can_manage_role(_role_query().filter_by(id=id).first()):
            return fail_api(msg="角色不存在或无权访问")
        res = enable_status(Role, id)
        if not res:
            return fail_api(msg="出错啦")
        return success_api(msg="启动成功")
    return fail_api(msg="数据错误")


# 禁用用户
@admin_role.put('/disable')
@authorize("admin:role:edit", log=True)
def dis_enable():
    if not _can_manage_roles():
        return fail_api(msg="只有超级管理员或部门管理员可以管理角色")
    _id = request.json.get('roleId')
    if _id:
        if not _can_manage_role(_role_query().filter_by(id=_id).first()):
            return fail_api(msg="角色不存在或无权访问")
        res = disable_status(Role, _id)
        if not res:
            return fail_api(msg="出错啦")
        return success_api(msg="禁用成功")
    return fail_api(msg="数据错误")


# 角色删除
@admin_role.delete('/remove/<int:id>')
@authorize("admin:role:remove", log=True)
def remove(id):
    if not _can_manage_roles():
        return fail_api(msg="只有超级管理员或部门管理员可以删除角色")
    role = _role_query().filter_by(id=id).first()
    if not _can_manage_role(role) or role.code in ("admin", "dept_admin", "studio_user"):
        return fail_api(msg="角色不存在、无权访问或不可删除")
    # 删除该角色的权限和用户
    role.power = []
    role.user = []
    
    r = Role.query.filter_by(id=id).delete()
    db.session.commit()
    if not r:
        return fail_api(msg="角色删除失败")
    return success_api(msg="角色删除成功")


# 批量删除
@admin_role.delete('/batchRemove')
@authorize("admin:role:remove", log=True)
@login_required
def batch_remove():
    if not _can_manage_roles():
        return fail_api(msg="只有超级管理员或部门管理员可以删除角色")
    ids = request.form.getlist('ids[]')
    for id in ids:
        role = _role_query().filter_by(id=id).first()
        if not _can_manage_role(role) or role.code in ("admin", "dept_admin", "studio_user"):
            continue
        # 删除该角色的权限和用户
        role.power = []
        role.user = []
        
        r = Role.query.filter_by(id=id).delete()
        db.session.commit()
    return success_api(msg="批量删除成功")
