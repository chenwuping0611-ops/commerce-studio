from collections import OrderedDict
from functools import wraps
from io import BytesIO

from flask import abort, current_app, jsonify, make_response, request, session
from flask_login import current_user

from applications.common.admin_log import admin_log
from applications.common.utils.gen_captcha import gen_captcha
from applications.schemas import PowerOutSchema


def is_super_admin():
    """Return whether the current account owns the built-in admin role."""

    if not current_user.is_authenticated:
        return False
    return any(
        role
        and role.enable == 1
        and role.code == "admin"
        for role in current_user.role
    )


def authorize(power, log=False):
    def decorator(func):
        from flask_login import login_required

        @login_required
        @wraps(func)
        def wrapper(*args, **kwargs):
            if power not in session.get("permissions", []):
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
    permissions = []
    for role in current_user.role:
        if role.enable == 0:
            continue
        for power in role.power:
            if power.enable == 0:
                continue
            if power.code:
                permissions.append(power.code)
    session["permissions"] = list(dict.fromkeys(permissions))


def make_menu_tree():
    powers = []
    for role in current_user.role:
        if role.enable == 0:
            continue
        for power in role.power:
            if power.enable == 0:
                continue
            if int(power.type) in (0, 1):
                powers.append(power)

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


def get_captcha():
    code, image = gen_captcha()
    out = BytesIO()
    session["code"] = code
    image.save(out, "png")
    out.seek(0)
    response = make_response(out.read())
    response.content_type = "image/png"
    return response, code


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
