import json
from datetime import datetime, timedelta

from flask import current_app, has_app_context
from flask_login import current_user
from sqlalchemy import and_, or_

from applications.common.scope import user_department_id
from applications.common.utils.validate import xss_escape
from applications.extensions import db
from applications.models import AdminLog


_SENSITIVE_KEYS = {
    "password",
    "oldpassword",
    "newpassword",
    "confirmpassword",
    "apikey",
    "authkey",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "privatekey",
    "token",
    "secret",
    "authorization",
    "captcha",
}


def _log_retention_days():
    try:
        return max(
            1,
            int(current_app.config.get("ADMIN_LOG_RETENTION_DAYS") or 90),
        )
    except (TypeError, ValueError, RuntimeError):
        return 90


def _log_expiry(now=None):
    now = now or datetime.now()
    return now + timedelta(days=_log_retention_days())


def _redact_mapping(value):
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        normalized_key = (
            str(key).replace("-", "").replace("_", "").lower()
        )
        result[key] = (
            "[REDACTED]"
            if normalized_key in _SENSITIVE_KEYS
            else _redact_mapping(item)
        )
    return result


def _request_description(request):
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        value = _redact_mapping(payload)
    else:
        value = _redact_mapping(request.values.to_dict(flat=True))
    return json.dumps(value, ensure_ascii=False, default=str)[:4000]


def login_log(request, uid, is_access, department_id=None):
    info = {
        "method": request.method,
        "url": request.path,
        "ip": request.remote_addr,
        "user_agent": xss_escape(request.headers.get("User-Agent")),
        "desc": xss_escape(request.form.get("username")),
        "uid": uid,
        "dept_id": department_id,
        "success": int(is_access),
    }
    log = AdminLog(
        url=info["url"],
        ip=info["ip"],
        user_agent=info["user_agent"],
        desc=info["desc"],
        uid=info["uid"],
        dept_id=info["dept_id"],
        method=info["method"],
        success=info["success"],
        expires_at=_log_expiry(),
    )
    db.session.add(log)
    db.session.flush()
    db.session.commit()
    return log.id


def admin_log(request, is_access, desc=None, target_uid=None):
    description = (
        xss_escape(desc)
        if desc is not None
        else _request_description(request)
    )
    if target_uid is not None and desc is None:
        description = f"target_user_id={int(target_uid)}"

    log = AdminLog(
        url=request.path,
        ip=request.remote_addr,
        user_agent=xss_escape(request.headers.get("User-Agent")),
        desc=description,
        uid=current_user.id,
        dept_id=user_department_id(),
        method=request.method,
        success=int(is_access),
        expires_at=_log_expiry(),
    )
    db.session.add(log)
    db.session.commit()
    return log.id


def cleanup_expired_admin_logs(limit=100, now=None):
    """Delete a bounded batch of expired logs.

    ``expires_at`` is authoritative for new rows. The create-time fallback
    keeps old rows, created before the retention column existed, compatible.
    """

    now = now or datetime.now()
    fallback = now - timedelta(days=_log_retention_days())
    rows = (
        AdminLog.query.filter(
            or_(
                AdminLog.expires_at.isnot(None)
                & (AdminLog.expires_at <= now),
                and_(
                    AdminLog.expires_at.is_(None),
                    AdminLog.create_time.isnot(None),
                    AdminLog.create_time <= fallback,
                ),
            )
        )
        .order_by(AdminLog.id.asc())
        .limit(max(1, int(limit or 100)))
        .all()
    )
    ids = [row.id for row in rows if row.id]
    if ids:
        AdminLog.query.filter(AdminLog.id.in_(ids)).delete(
            synchronize_session=False,
        )
        db.session.commit()
    return {
        "scanned": len(rows),
        "deleted": len(ids),
    }
