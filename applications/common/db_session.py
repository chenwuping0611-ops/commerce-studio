"""Small SQLAlchemy session helpers shared by long-running service paths."""

from applications.extensions import db


def release_db_connection():
    """Return an idle connection without detaching the request's ORM objects.

    ``scoped_session.remove()`` also expunges every object in the current
    request. That is too aggressive for service functions called by a route or
    another service that still needs those objects after a remote API call.
    The preparation paths commit or have no pending changes before calling
    this helper, so rollback ends the idle transaction and returns the
    connection while keeping the Session usable.
    """

    try:
        db.session.rollback()
    except Exception:
        # A broken transaction/session must not keep a bad connection checked
        # out. This fallback is intentionally rare and may detach objects.
        db.session.remove()
