from collections import OrderedDict
from functools import wraps

from flask import abort, current_app, jsonify, request, session
from flask_login import current_user

from applications.common.admin_log import admin_log
from applications.common.scope import (
    effective_permission_codes,
    has_effective_permission,
    is_super_admin_user,
)
from applications.schemas import PowerOutSchema


def is_super_admin():
    """Return whether the current account owns the built-in super role."""

    return is_super_admin_user()


def authorize(power, log=False):
    def decorator(func):
        from flask_login import login_required

        @login_required
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not has_effective_permission(power):
                if log:
                    admin_log(request=request, is_access=False)
                if request.method == "GET":
                    abort(403)
                return jsonify(success=False, msg="权限不足")
            if log:
                admin_log(request=request, is_access=True)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def add_auth_session():
    session["permissions"] = sorted(effective_permission_codes())


def make_menu_tree():
    allowed_codes = effective_permission_codes()
    powers = []
    for role in current_user.role:
        if role.enable == 0:
            continue
        for power in role.power:
            if (
                (
                    is_super_admin_user()
                    or getattr(role, "code", "") != "admin"
                )
                and
                power.enable != 0
                and int(power.type) in (0, 1)
                and power.code in allowed_codes
            ):
                powers.append(power)

    # ``admin`` is a reserved account, not a role assignment.  Include all
    # enabled menu powers even if an old database row lost its role relation.
    if is_super_admin_user():
        from applications.models import Power

        powers = [
            power
            for power in Power.query.filter_by(enable=1).all()
            if int(power.type) in (0, 1)
        ]

    power_dict = PowerOutSchema(many=True).dump(powers)
    unique_powers = OrderedDict()
    for item in power_dict:
        unique_powers.setdefault(item["id"], item)

    children_by_parent = {}
    for item in unique_powers.values():
        children_by_parent.setdefault(item["parent_id"], []).append(item)

    def build_children(parent_id):
        children = sorted(
            children_by_parent.get(parent_id, []),
            key=lambda item: (item.get("sort") or 0, item.get("id") or 0),
        )
        for item in children:
            nested = build_children(item["id"])
            if nested:
                item["children"] = nested
            else:
                item.pop("children", None)
        return children

    return build_children(0)


def get_render_config():
    return dict(
        logo={
            "title": current_app.config.get("SYSTEM_NAME"),
            "image": "/static/admin/admin/images/logo.png",
        },
        menu={
            "data": "/rights/menu",
            "collaspe": False,
            "accordion": True,
            "method": "GET",
            "control": False,
            "controlWidth": 500,
            "select": "0",
            "async": True,
        },
        tab={
            "enable": True,
            "keepState": True,
            "session": True,
            "max": 30,
            "index": {"id": "studio-dashboard", "href": "/studio/", "title": "工作台"},
        },
        theme={
            "defaultColor": "3",
            "defaultMenu": "dark-theme",
            "allowCustom": True,
        },
        colors=[
            {"id": "1", "color": "#1677ff"},
            {"id": "2", "color": "#2f54eb"},
            {"id": "3", "color": "#1677ff"},
            {"id": "4", "color": "#13c2c2"},
            {"id": "5", "color": "#5b8ff9"},
        ],
        links=current_app.config.get("SYSTEM_PANEL_LINKS"),
        other={"keepLoad": 600, "autoHead": False},
        header=False,
    )
