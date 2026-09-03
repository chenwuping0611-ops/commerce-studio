from flask import Blueprint, abort, render_template, request, jsonify
from flask_login import current_user

from sqlalchemy import and_, or_

from applications.common import curd
from applications.common.scope import (
    department_in_scope,
    effective_permission_codes,
    is_department_admin_user,
    is_super_admin_user,
    managed_department_ids,
    user_department_id,
)
from applications.common.utils.http import success_api, fail_api
from applications.common.utils.rights import authorize
from applications.common.utils.validate import xss_escape
from applications.extensions import db
from applications.models import Power
from applications.schemas import PowerOutSchema2

admin_power = Blueprint('adminPower', __name__, url_prefix='/admin/power')


def _power_query():
    if is_super_admin_user():
        return Power.query
    if not is_department_admin_user():
        return Power.query.filter(False)
    visible = managed_department_ids() or [-1]
    return Power.query.filter(
        or_(
            Power.dept_id.in_(visible),
            and_(
                Power.dept_id.is_(None),
                Power.code.isnot(None),
            ),
        )
    )


def _can_manage_power(power):
    return bool(
        power
        and (
            is_super_admin_user()
            or (
                power.dept_id is not None
                and department_in_scope(power.dept_id, include_descendants=False)
            )
        )
    )


def _can_manage_powers():
    return is_super_admin_user() or is_department_admin_user()


@admin_power.get('/')
@authorize("admin:power:main", log=True)
def index():
    if not _can_manage_powers():
        abort(403)
    return render_template('admin/power/main.html')


@admin_power.post('/data')
@authorize("admin:power:main", log=True)
def data():
    if not _can_manage_powers():
        return jsonify(success=False, msg="权限不足"), 403
    power = _power_query().all()
    res = {
        "data": curd.model_to_dicts(schema=PowerOutSchema2, data=power)
    }
    return jsonify(res)


@admin_power.get('/add')
@authorize("admin:power:add", log=True)
def add():
    if not _can_manage_powers():
        abort(403)
    return render_template('admin/power/add.html')


@admin_power.get('/selectParent')
@authorize("admin:power:main", log=True)
def select_parent():
    if not _can_manage_powers():
        return jsonify(success=False, msg="权限不足"), 403
    power = _power_query().all()
    res = curd.model_to_dicts(schema=PowerOutSchema2, data=power)
    res.append({"powerId": 0, "powerName": "顶级权限", "parentId": -1})
    res = {
        "status": {"code": 200, "message": "默认"},
        "data": res

    }
    return jsonify(res)


# 增加
@admin_power.post('/save')
@authorize("admin:power:add", log=True)
def save():
    if not _can_manage_powers():
        return fail_api(msg="只有超级管理员或部门管理员可以管理权限")
    req = request.json
    icon = xss_escape(req.get("icon"))
    openType = xss_escape(req.get("openType"))
    parentId = xss_escape(req.get("parentId"))
    powerCode = xss_escape(req.get("powerCode"))
    powerName = xss_escape(req.get("powerName"))
    powerType = xss_escape(req.get("powerType"))
    powerUrl = xss_escape(req.get("powerUrl"))
    sort = xss_escape(req.get("sort"))
    if not powerCode or not powerName:
        return fail_api(msg="权限标识和名称不能为空")
    if (
        not is_super_admin_user()
        and powerCode not in effective_permission_codes(current_user)
    ):
        return fail_api(msg="部门管理员不能创建超出自身授权范围的权限")
    if not is_super_admin_user():
        parent = _power_query().filter_by(id=parentId).first()
        if parent is None and str(parentId) not in ("0", "-1"):
            return fail_api(msg="上级权限不存在或无权访问")
    if not is_super_admin_user() and user_department_id() is None:
        return fail_api(msg="请先为当前管理员指定管理部门")
    power = Power(
        icon=icon,
        open_type=openType,
        parent_id=parentId,
        code=powerCode,
        name=powerName,
        type=powerType,
        url=powerUrl,
        sort=sort,
        enable=1,
        dept_id=None if is_super_admin_user() else user_department_id(),
        created_by=None if is_super_admin_user() else current_user.id,
    )
    r = db.session.add(power)
    db.session.commit()
    return success_api(msg="成功")


# 权限编辑
@admin_power.get('/edit/<int:_id>')
@authorize("admin:power:edit", log=True)
def edit(_id):
    if not _can_manage_powers():
        abort(403)
    power = _power_query().filter_by(id=_id).first()
    if not _can_manage_power(power):
        return fail_api(msg="权限不存在或无权访问")
    icon = str(power.icon).split()
    if len(icon) == 2:
        icon = icon[1]
    else:
        icon = None
    return render_template('admin/power/edit.html', power=power, icon=icon)


# 权限更新
@admin_power.put('/update')
@authorize("admin:power:edit", log=True)
def update():
    if not _can_manage_powers():
        return fail_api(msg="只有超级管理员或部门管理员可以管理权限")
    req_json = request.json
    id = request.json.get("powerId")
    data = {
        "icon": xss_escape(req_json.get("icon")),
        "open_type": xss_escape(req_json.get("openType")),
        "parent_id": xss_escape(req_json.get("parentId")),
        "code": xss_escape(req_json.get("powerCode")),
        "name": xss_escape(req_json.get("powerName")),
        "type": xss_escape(req_json.get("powerType")),
        "url": xss_escape(req_json.get("powerUrl")),
        "sort": xss_escape(req_json.get("sort"))
    }
    power = _power_query().filter_by(id=id).first()
    if not _can_manage_power(power):
        return fail_api(msg="权限不存在或无权访问")
    if (
        not is_super_admin_user()
        and data["code"] != str(power.code or "")
    ):
        return fail_api(msg="部门管理员不能修改权限标识")
    if (
        not is_super_admin_user()
        and data["code"] not in effective_permission_codes(current_user)
    ):
        return fail_api(msg="部门管理员不能修改为未授权的权限标识")
    res = Power.query.filter_by(id=id).update(data)
    db.session.commit()
    if not res:
        return fail_api(msg="更新权限失败")
    return success_api(msg="更新权限成功")


# 启用权限
@admin_power.put('/enable')
@authorize("admin:power:edit", log=True)
def enable():
    if not _can_manage_powers():
        return fail_api(msg="只有超级管理员或部门管理员可以管理权限")
    _id = request.json.get('powerId')
    if _id:
        if not _can_manage_power(_power_query().filter_by(id=_id).first()):
            return fail_api(msg="权限不存在或无权访问")
        res = curd.enable_status(Power, _id)
        if not res:
            return fail_api(msg="出错啦")
        return success_api(msg="启用成功")
    return fail_api(msg="数据错误")


# 禁用权限
@admin_power.put('/disable')
@authorize("admin:power:edit", log=True)
def dis_enable():
    if not _can_manage_powers():
        return fail_api(msg="只有超级管理员或部门管理员可以管理权限")
    _id = request.json.get('powerId')
    if _id:
        if not _can_manage_power(_power_query().filter_by(id=_id).first()):
            return fail_api(msg="权限不存在或无权访问")
        res = curd.disable_status(Power, _id)
        if not res:
            return fail_api(msg="出错啦")
        return success_api(msg="禁用成功")
    return fail_api(msg="数据错误")


# 权限删除
@admin_power.delete('/remove/<int:id>')
@authorize("admin:power:remove", log=True)
def remove(id):
    if not _can_manage_powers():
        return fail_api(msg="只有超级管理员或部门管理员可以删除权限")
    power = _power_query().filter_by(id=id).first()
    if not _can_manage_power(power):
        return fail_api(msg="权限不存在或无权访问")
    if power.dept_id is None and not is_super_admin_user():
        return fail_api(msg="系统内置权限不可由部门管理员删除")
    power.role = []

    r = Power.query.filter_by(id=id).delete()
    db.session.commit()
    if r:
        return success_api(msg="删除成功")
    else:
        return fail_api(msg="删除失败")


# 批量删除
@admin_power.delete('/batchRemove')
@authorize("admin:power:remove", log=True)
def batch_remove():
    if not _can_manage_powers():
        return fail_api(msg="只有超级管理员或部门管理员可以删除权限")
    ids = request.form.getlist('ids[]')
    for id in ids:
        power = _power_query().filter_by(id=id).first()
        if not _can_manage_power(power):
            continue
        if power.dept_id is None and not is_super_admin_user():
            continue
        power.role = []

        r = Power.query.filter_by(id=id).delete()
        db.session.commit()
    return success_api(msg="批量删除成功")
