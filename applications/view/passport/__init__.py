from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from applications.common import admin as index_curd
from applications.common.admin_log import login_log
from applications.common.utils.http import fail_api, success_api
from applications.models import User


passport_bp = Blueprint("passport", __name__, url_prefix="/passport")


def register_passport_views(app):
    app.register_blueprint(passport_bp)


@passport_bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.index"))
    return render_template("admin/login.html")


@passport_bp.post("/login")
def login_post():
    req = request.form
    username = req.get("username")
    password = req.get("password")
    if not username or not password:
        return fail_api(msg="用户名和密码不能为空")

    user = User.query.filter_by(username=username).first()
    if user is None:
        return fail_api(msg="用户不存在")
    if user.enable == 0:
        return fail_api(msg="用户已停用")

    if user.validate_password(password):
        login_user(user)
        login_log(
            request,
            uid=user.id,
            is_access=True,
            department_id=user.dept_id,
        )
        index_curd.add_auth_session()
        return success_api(msg="登录成功")

    login_log(
        request,
        uid=user.id,
        is_access=False,
        department_id=user.dept_id,
    )
    return fail_api(msg="用户名或密码错误")


@passport_bp.post("/logout")
@login_required
def logout():
    logout_user()
    session.pop("permissions", None)
    return success_api(msg="已退出登录")
