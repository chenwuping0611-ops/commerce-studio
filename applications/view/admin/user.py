from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import desc

from applications.common import curd
from applications.common.curd import model_to_dicts, enable_status, disable_status
from applications.common.helper import ModelFilter
from applications.common.utils.http import table_api, fail_api, success_api
from applications.common.utils.rights import authorize
from applications.common.utils.validate import xss_escape
from applications.extensions import db
from applications.models import Role
from applications.models import User, AdminLog
from applications.schemas import UserOutSchema
from applications.studio.bootstrap import DEFAULT_STUDIO_ROLE_CODE

admin_user = Blueprint('adminUser', __name__, url_prefix='/admin/user')


def _parse_role_ids(raw_role_ids):
    """Normalize the comma-separated role ids submitted by the Pear forms."""

    if not raw_role_ids:
        return []
    values = raw_role_ids if isinstance(raw_role_ids, list) else str(raw_role_ids).split(',')
    role_ids = []
    for value in values:
        value = str(value).strip()
        if value.isdigit() and int(value) > 0:
            role_ids.append(int(value))
    return list(dict.fromkeys(role_ids))


def _get_enabled_roles(role_ids=None):
    query = Role.query.filter_by(enable=1)
    if role_ids is not None:
        if not role_ids:
            return []
        query = query.filter(Role.id.in_(role_ids))
    return query.order_by(Role.sort.asc(), Role.id.asc()).all()


# 用户管理
@admin_user.get('/')
@authorize("admin:user:main", log=True)
def main():
    return render_template('admin/user/main.html')


#   用户分页查询
@admin_user.get('/data')
@authorize("admin:user:main", log=True)
def data():
    # 获取请求参数
    real_name = xss_escape(request.args.get('realName', type=str))
    username = xss_escape(request.args.get('username', type=str))
    dept_id = request.args.get('deptId', type=int)
    # 查询参数构造
    mf = ModelFilter()
    if real_name:
        mf.contains(field_name="realname", value=real_name)
    if username:
        mf.contains(field_name="username", value=username)
    if dept_id:
        mf.exact(field_name="dept_id", value=dept_id)
    # orm查询
    # 使用分页获取data需要.items
    user = User.query.filter(mf.get_filter(model=User)).layui_paginate()
    count = user.total
    # 返回api
    return table_api(data=model_to_dicts(schema=UserOutSchema, data=user.items), count=count)


# 用户增加
@admin_user.get('/add')
@authorize("admin:user:add", log=True)
def add():
    roles = _get_enabled_roles()
    return render_template('admin/user/add.html', roles=roles)


@admin_user.post('/save')
@authorize("admin:user:add", log=True)
def save():
    req_json = request.json or {}
    a = req_json.get("roleIds") or ""
    username = xss_escape(req_json.get('username'))
    real_name = xss_escape(req_json.get('realName'))
    password = xss_escape(req_json.get('password'))
    role_ids = _parse_role_ids(a)

    if not username or not real_name or not password:
        return fail_api(msg="账号姓名密码不得为空")
    if len(password) < 6:
        return fail_api(msg="密码长度不能少于6位")

    if bool(User.query.filter_by(username=username).count()):
        return fail_api(msg="用户已经存在")
    roles = _get_enabled_roles(role_ids)
    if role_ids and len(roles) != len(role_ids):
        return fail_api(msg="只能分配已启用的角色")
    if not roles:
        default_role = Role.query.filter_by(
            code=DEFAULT_STUDIO_ROLE_CODE,
            enable=1,
        ).first()
        if default_role:
            roles = [default_role]
    if not roles:
        return fail_api(msg="请先配置可用角色")

    user = User(username=username, realname=real_name, enable=1)
    user.set_password(password)
    user.role = roles
    db.session.add(user)
    db.session.commit()
    return success_api(msg="增加成功")


# 删除用户
@admin_user.delete('/remove/<int:id>')
@authorize("admin:user:remove", log=True)
def delete(id):
    user = User.query.filter_by(id=id).first()
    user.role = []
    
    res = User.query.filter_by(id=id).delete()
    db.session.commit()
    if not res:
        return fail_api(msg="删除失败")
    return success_api(msg="删除成功")


#  编辑用户
@admin_user.get('/edit/<int:id>')
@authorize("admin:user:edit", log=True)
def edit(id):
    user = curd.get_one_by_id(User,id)
    roles = _get_enabled_roles()
    checked_roles = []
    for r in user.role:
        if r.enable == 1:
            checked_roles.append(r.id)
    return render_template('admin/user/edit.html', user=user, roles=roles, checked_roles=checked_roles)


#  编辑用户
@admin_user.put('/update')
@authorize("admin:user:edit", log=True)
def update():
    req_json = request.json or {}
    a = req_json.get("roleIds")
    id = xss_escape(req_json.get("userId"))
    username = xss_escape(req_json.get('username'))
    real_name = xss_escape(req_json.get('realName'))
    dept_id = xss_escape(req_json.get('deptId'))
    role_ids = _parse_role_ids(a)
    u = User.query.filter_by(id=id).first()
    if not u:
        return fail_api(msg="用户不存在")

    roles = _get_enabled_roles(role_ids)
    if role_ids and len(roles) != len(role_ids):
        return fail_api(msg="只能分配已启用的角色")

    u.username = username
    u.realname = real_name
    u.dept_id = dept_id
    u.role = roles

    db.session.commit()
    return success_api(msg="更新成功")


# 个人中心
@admin_user.get('/center')
@login_required
def center():
    user_info = current_user
    user_logs = AdminLog.query.filter_by(url='/passport/login').filter_by(uid=current_user.id).order_by(
        desc(AdminLog.create_time)).limit(10)
    return render_template('admin/user/center.html', user_info=user_info, user_logs=user_logs)


# 修改头像
@admin_user.get('/profile')
@login_required
def profile():
    return render_template('admin/user/profile.html')


# 修改头像
@admin_user.put('/updateAvatar')
@login_required
def update_avatar():
    url = request.json.get("avatar").get("src")
    r = User.query.filter_by(id=current_user.id).update({"avatar": url})
    db.session.commit()
    if not r:
        return fail_api(msg="出错啦")
    return success_api(msg="修改成功")


# 修改当前用户信息
@admin_user.put('/updateInfo')
@login_required
def update_info():
    req_json = request.json
    r = User.query.filter_by(id=current_user.id).update(
        {"realname": req_json.get("realName"), "remark": req_json.get("details")})
    db.session.commit()
    if not r:
        return fail_api(msg="出错啦")
    return success_api(msg="更新成功")


# 修改当前用户密码
@admin_user.get('/editPassword')
@login_required
def edit_password():
    return render_template('admin/user/edit_password.html')


# 修改当前用户密码
@admin_user.put('/editPassword')
@login_required
def edit_password_put():
    res_json = request.json or {}
    old_password = res_json.get("oldPassword") or ""
    new_password = res_json.get("newPassword") or ""
    confirm_password = res_json.get("confirmPassword") or ""
    if not new_password:
        return fail_api("新密码不得为空")
    if len(new_password) < 6:
        return fail_api("新密码长度不能少于6位")
    if new_password != confirm_password:
        return fail_api("俩次密码不一样")
    user = current_user
    is_right = user.validate_password(old_password)
    if not is_right:
        return fail_api("旧密码错误")
    user.set_password(res_json.get("newPassword"))
    db.session.add(user)
    db.session.commit()
    return success_api("更改成功")


# 启用用户
@admin_user.put('/enable')
@authorize("admin:user:edit", log=True)
def enable():
    _id = request.json.get('userId')
    if _id:
        res = enable_status(model=User, id=_id)
        if not res:
            return fail_api(msg="出错啦")
        return success_api(msg="启动成功")
    return fail_api(msg="数据错误")


# 禁用用户
@admin_user.put('/disable')
@authorize("admin:user:edit", log=True)
def dis_enable():
    _id = request.json.get('userId')
    if _id:
        res = disable_status(model=User,id=_id)
        if not res:
            return fail_api(msg="出错啦")
        return success_api(msg="禁用成功")
    return fail_api(msg="数据错误")


# 批量删除
@admin_user.delete('/batchRemove')
@authorize("admin:user:remove", log=True)
def batch_remove():
    ids = request.form.getlist('ids[]')
    for id in ids:
        user = User.query.filter_by(id=id).first()
        user.role = []
        
        res = User.query.filter_by(id=id).delete()
        db.session.commit()
    return success_api(msg="批量删除成功")
