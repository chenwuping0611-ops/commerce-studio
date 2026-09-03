from flask import session
from flask_login import current_user

from applications.common.scope import is_super_admin_user


AMAZON_AI_PERMISSION_CODES = frozenset(
    {
        "amazon_ai:root",
        "amazon_ai:dashboard",
        "amazon_ai:history",
        "amazon_ai:competitor",
        "amazon_ai:differentiation",
        "amazon_ai:basic_info",
        "amazon_ai:listing_create",
    }
)

AMAZON_AI_LEGACY_PERMISSION_CODES = frozenset(
    {
        "amazon_ai:keyword",
        "amazon_ai:review",
    }
)

AMAZON_AI_SESSION_PERMISSION_CODES = (
    AMAZON_AI_PERMISSION_CODES | AMAZON_AI_LEGACY_PERMISSION_CODES
)


def sync_amazon_permissions():
    """Refresh only Amazon permissions in the current session.

    The existing authorize() decorator remains the final gate. This scoped
    refresh fixes sessions created before Amazon permissions were initialized
    without changing the application's system-management permission flow.
    """

    if not current_user.is_authenticated:
        return

    assigned = set()
    for role in current_user.role:
        if not role or role.enable == 0:
            continue
        if not is_super_admin_user() and getattr(role, "code", "") == "admin":
            continue
        for power in role.power:
            if (
                power
                and power.enable != 0
                and power.code in AMAZON_AI_PERMISSION_CODES
            ):
                assigned.add(power.code)

    existing = [
        code
        for code in session.get("permissions", [])
        if code not in AMAZON_AI_SESSION_PERMISSION_CODES
    ]
    session["permissions"] = list(dict.fromkeys(existing + sorted(assigned)))
    session.modified = True
