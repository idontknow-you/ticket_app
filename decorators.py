from functools import wraps
from flask import abort
from flask_login import current_user
from models.permission import UserPermission


def require_permission(module, permission='can_view'):
    """
    Usage:
        @require_permission('Tickets', 'can_edit')
        def my_route(): ...

    Superadmin always passes. Regular users need a matching UserPermission row.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.is_superadmin:
                return f(*args, **kwargs)
            perm = UserPermission.query.filter_by(
                user_id=current_user.id,
                module=module
            ).first()
            if not perm or not getattr(perm, permission, False):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
