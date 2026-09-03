"""Centralized identity, functional permission, and data-scope helpers.

The application has one built-in super administrator account and two normal
business identities:

* ``admin`` account: ``ALL``
* ``dept_admin`` role: ``DEPARTMENT``
* every other enabled account: ``SELF``

These helpers are shared by views and domain services.  A department or user
id supplied by a browser is never trusted for authorization.
"""

from flask_login import current_user

from applications.common.utils.validate import xss_escape


SUPER_ADMIN_ROLE_CODE = "admin"
DEPARTMENT_ADMIN_ROLE_CODE = "dept_admin"
STUDIO_USER_ROLE_CODE = "studio_user"
RESERVED_ROLE_CODES = frozenset(
    {
        SUPER_ADMIN_ROLE_CODE,
        DEPARTMENT_ADMIN_ROLE_CODE,
        STUDIO_USER_ROLE_CODE,
    }
)

PROVIDER_OWNER_DEPARTMENT = "DEPARTMENT"
# Kept as a compatibility constant for old callers and migrations. Provider
# records are now always owned by a real department, including ``总项目``.
PROVIDER_OWNER_SUPER_ADMIN = "SUPER_ADMIN"
# Kept for old database migrations. New settings are keyed by a real
# department id and never use this sentinel.
SUPER_ADMIN_SETTING_DEPT_ID = 0

DATA_SCOPE_ALL = "ALL"
DATA_SCOPE_DEPARTMENT = "DEPARTMENT"
DATA_SCOPE_SELF = "SELF"


def _user_or_current(user=None):
    if user is not None:
        return user
    return (
        current_user
        if getattr(current_user, "is_authenticated", False)
        else None
    )


def _roles(user):
    if not user:
        return []
    relation = getattr(user, "role", [])
    try:
        return relation.all() if hasattr(relation, "all") else list(relation)
    except TypeError:
        return []


def role_codes(user=None):
    """Return enabled role identifiers for a user."""

    return {
        str(role.code).strip()
        for role in _roles(_user_or_current(user))
        if role and getattr(role, "enable", 1) != 0 and role.code
    }


def is_reserved_role_code(code):
    return str(code or "").strip() in RESERVED_ROLE_CODES


def provider_owner_type(provider):
    """Return the only supported provider ownership type.

    ``SUPER_ADMIN`` was used by an earlier version to represent a virtual
    provider scope with a NULL department. The workspace now treats ``总项目``
    as the administrator's real department, so all provider rows are exposed
    as department-owned after migration.
    """

    return PROVIDER_OWNER_DEPARTMENT


def is_super_admin_user(user=None):
    """Only the reserved ``admin`` account receives ``ALL`` data access."""

    user = _user_or_current(user)
    return bool(user and str(getattr(user, "username", "")) == "admin")


def is_department_admin_user(user=None):
    user = _user_or_current(user)
    return bool(
        user
        and not is_super_admin_user(user)
        and DEPARTMENT_ADMIN_ROLE_CODE in role_codes(user)
    )


def is_studio_user(user=None):
    user = _user_or_current(user)
    return bool(
        user
        and not is_super_admin_user(user)
        and not is_department_admin_user(user)
    )


def data_scope_for_user(user=None):
    user = _user_or_current(user)
    if not user:
        return DATA_SCOPE_SELF
    if is_super_admin_user(user):
        return DATA_SCOPE_ALL
    if is_department_admin_user(user):
        return DATA_SCOPE_DEPARTMENT
    return DATA_SCOPE_SELF


def get_data_scope(user=None):
    """Readable alias for callers that describe policy as an operation."""

    return data_scope_for_user(user)


def user_department_id(user=None):
    user = _user_or_current(user)
    try:
        return int(user.dept_id) if user and user.dept_id else None
    except (TypeError, ValueError):
        return None


def managed_department_ids(user=None, include_descendants=False):
    """Return departments visible to an identity.

    ``include_descendants`` is retained for compatibility with old callers,
    but the current policy is deliberately flat: a department administrator
    never implicitly receives child-department data.
    """

    del include_descendants
    user = _user_or_current(user)
    if is_super_admin_user(user):
        return None
    department_id = user_department_id(user)
    return [department_id] if department_id is not None else []


def department_in_scope(
    department_id,
    user=None,
    include_descendants=False,
):
    del include_descendants
    if department_id is None:
        return False
    if is_super_admin_user(user):
        return True
    own_department_id = user_department_id(user)
    try:
        return own_department_id is not None and int(department_id) == own_department_id
    except (TypeError, ValueError):
        return False


def _has_column(model, name):
    table = getattr(model, "__table__", None)
    columns = getattr(table, "columns", None)
    return bool(columns is not None and name in columns)


def _column(model, name):
    return getattr(model, name, None) if _has_column(model, name) else None


def scope_query(
    query,
    model,
    user=None,
    include_descendants=False,
    include_global=False,
):
    """Apply the identity's data scope to a SQLAlchemy query."""

    del include_descendants
    user = _user_or_current(user)
    scope = data_scope_for_user(user)
    if scope == DATA_SCOPE_ALL:
        return query

    if scope == DATA_SCOPE_DEPARTMENT:
        department_column = _column(model, "dept_id")
        department_id = user_department_id(user)
        if department_column is None or department_id is None:
            return query.filter(False)
        if include_global:
            return query.filter(
                (department_column == department_id)
                | department_column.is_(None)
            )
        return query.filter(department_column == department_id)

    owner_column = next(
        (
            _column(model, name)
            for name in ("user_id", "created_by", "uid")
            if _column(model, name) is not None
        ),
        None,
    )
    if owner_column is not None and getattr(user, "id", None) is not None:
        return query.filter(owner_column == user.id)

    table_name = getattr(getattr(model, "__table__", None), "name", "")
    if table_name == "admin_user" and _column(model, "id") is not None:
        return query.filter(model.id == user.id)

    # A resource without an immutable owner must never become visible to a
    # SELF-scoped account by accident.
    return query.filter(False)


def can_access_department(user, department_id):
    return department_in_scope(department_id, user=user)


def _resource_owner_id(resource):
    for field in ("user_id", "created_by", "uid"):
        value = getattr(resource, field, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    if getattr(getattr(resource, "__table__", None), "name", "") == "admin_user":
        try:
            return int(resource.id)
        except (TypeError, ValueError):
            return None
    return None


def can_access_resource(user, resource):
    """Check a concrete row against ALL/DEPARTMENT/SELF."""

    user = _user_or_current(user)
    if not user or not resource:
        return False
    scope = data_scope_for_user(user)
    if scope == DATA_SCOPE_ALL:
        return True
    if scope == DATA_SCOPE_DEPARTMENT:
        return department_in_scope(getattr(resource, "dept_id", None), user=user)
    return _resource_owner_id(resource) == getattr(user, "id", None)


def can_access_user(current, target):
    return can_access_resource(current, target)


def can_manage_user(current, target):
    """Check administrative profile operations, excluding passwords."""

    current = _user_or_current(current)
    if not current or not target:
        return False
    if is_super_admin_user(current):
        return True
    target_username = str(getattr(target, "username", "") or "")
    if target_username == "admin":
        return False
    if getattr(target, "id", None) == getattr(current, "id", None):
        return False
    return bool(
        is_department_admin_user(current)
        and getattr(target, "dept_id", None) == user_department_id(current)
        and DEPARTMENT_ADMIN_ROLE_CODE not in role_codes(target)
    )


def can_change_password(current, target):
    """Apply the explicit password-change permission matrix."""

    current = _user_or_current(current)
    if not current or not target:
        return False
    if is_super_admin_user(current):
        return True
    if getattr(target, "id", None) == getattr(current, "id", None):
        return True
    return bool(
        is_department_admin_user(current)
        and getattr(target, "dept_id", None) == user_department_id(current)
        and DEPARTMENT_ADMIN_ROLE_CODE not in role_codes(target)
        and str(getattr(target, "username", "")) != "admin"
    )


def can_manage_provider(user=None):
    user = _user_or_current(user)
    return is_super_admin_user(user) or is_department_admin_user(user)


def provider_scope_matches(provider, department_id=None, owner_type=None):
    """Check a provider against an already-resolved ownership scope."""

    if not provider:
        return False
    actual_owner_type = provider_owner_type(provider)
    requested_owner_type = (
        str(owner_type or "").strip().upper()
        if owner_type not in (None, "")
        else None
    )
    if requested_owner_type and requested_owner_type != actual_owner_type:
        return False
    if department_id in (None, ""):
        return getattr(provider, "dept_id", None) is not None
    try:
        return int(getattr(provider, "dept_id", None)) == int(department_id)
    except (TypeError, ValueError):
        return False


def can_access_provider(user, provider, department_id=None, owner_type=None):
    if not can_manage_provider(user):
        return False
    if getattr(provider, "dept_id", None) is None:
        return False
    if is_super_admin_user(user):
        if department_id in (None, "") and owner_type in (None, ""):
            return True
        return provider_scope_matches(
            provider,
            department_id=department_id,
            owner_type=owner_type,
        )
    own_department_id = user_department_id(user)
    if department_id not in (None, ""):
        try:
            if int(department_id) != own_department_id:
                return False
        except (TypeError, ValueError):
            return False
    return (
        own_department_id is not None
        and getattr(provider, "dept_id", None) == own_department_id
    )


def can_access_model(user, model, department_id=None, owner_type=None):
    """Check a model and its provider without trusting a requested department."""

    user = _user_or_current(user)
    provider = getattr(model, "provider", None) if model else None
    if not user or not model or not provider:
        return False
    if is_super_admin_user(user):
        if department_id in (None, "") and owner_type in (None, ""):
            return True
        return provider_scope_matches(
            provider,
            department_id=department_id,
            owner_type=owner_type,
        )
    return can_access_provider(
        user,
        provider,
        department_id=department_id,
        owner_type=owner_type,
    )


def can_manage_model(user, model, department_id=None, owner_type=None):
    """Require provider-management access in addition to model visibility."""

    return bool(
        can_manage_provider(user)
        and can_access_model(
            user,
            model,
            department_id=department_id,
            owner_type=owner_type,
        )
    )


def can_access_skill(user, skill, builtin_codes=None):
    """Allow system Skills globally while scoping custom Skills by ownership."""

    user = _user_or_current(user)
    if not user or not skill:
        return False
    if builtin_codes and getattr(skill, "code", None) in set(builtin_codes):
        return True
    return can_access_resource(user, skill)


def can_access_asset(user, asset, allow_system=False):
    """Apply the data scope to a stored file row."""

    user = _user_or_current(user)
    if not user or not asset:
        return False
    if is_super_admin_user(user):
        return True
    if is_department_admin_user(user):
        return department_in_scope(getattr(asset, "dept_id", None), user=user)
    if _resource_owner_id(asset) == getattr(user, "id", None):
        return True
    return bool(
        allow_system
        and _resource_owner_id(asset) is None
        and str(getattr(asset, "purpose", "") or "").upper() == "SKILL"
    )


def can_assign_role(current, role, target=None):
    """Prevent reserved roles from being created or assigned by normal users."""

    current = _user_or_current(current)
    if not current or not role:
        return False
    code = str(getattr(role, "code", "") or "").strip()
    if code == SUPER_ADMIN_ROLE_CODE:
        return bool(
            is_super_admin_user(current)
            and target is not None
            and str(getattr(target, "username", "")) == "admin"
        )
    if is_super_admin_user(current):
        return True
    if not is_department_admin_user(current):
        return False
    if code == DEPARTMENT_ADMIN_ROLE_CODE:
        return False
    if target is not None:
        if getattr(target, "username", "") == "admin":
            return False
        if getattr(target, "dept_id", None) != user_department_id(current):
            return False
    role_department_id = getattr(role, "dept_id", None)
    if code == STUDIO_USER_ROLE_CODE and role_department_id is None:
        return True
    return department_in_scope(role_department_id, user=current)


def effective_permission_codes(user=None):
    """Resolve functional permissions from the current database state."""

    user = _user_or_current(user)
    if not user:
        return set()
    if is_super_admin_user(user):
        try:
            from applications.models import Power

            return {
                power.code
                for power in Power.query.filter_by(enable=1).all()
                if power and power.code
            }
        except Exception:
            # Bootstrap may call this helper before the permissions table is
            # available.  has_effective_permission still special-cases admin.
            return set()

    codes = set()
    for role in _roles(user):
        if not role or getattr(role, "enable", 1) == 0:
            continue
        # The admin role is reserved for the username ``admin``.  Legacy
        # rows must not turn a normal account into a functional superuser.
        if (
            str(getattr(role, "code", "") or "").strip()
            == SUPER_ADMIN_ROLE_CODE
        ):
            continue
        for power in getattr(role, "power", []) or []:
            if power and getattr(power, "enable", 1) != 0 and power.code:
                codes.add(power.code)
    return codes


def has_effective_permission(code, user=None):
    user = _user_or_current(user)
    if is_super_admin_user(user):
        return True
    return str(code or "") in effective_permission_codes(user)


def department_scope_id(requested=None, user=None):
    """Resolve a department selector without trusting normal-user input."""

    user = _user_or_current(user)
    own_department_id = user_department_id(user)
    if not is_super_admin_user(user):
        return own_department_id
    if requested in (None, ""):
        return own_department_id
    try:
        return int(requested)
    except (TypeError, ValueError):
        return own_department_id


def safe_log_value(value):
    """Keep request logging from exposing credentials or tokens."""

    text = str(value or "")
    lowered = text.lower()
    sensitive_markers = (
        "password",
        "passwd",
        "api_key",
        "apikey",
        "token",
        "secret",
        "authorization",
        "captcha",
    )
    if any(marker in lowered for marker in sensitive_markers):
        return "[REDACTED]"
    return xss_escape(text)[:4000]
