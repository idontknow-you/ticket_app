from functools import wraps
from flask import abort, redirect, url_for
from flask_login import current_user


def superadmin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.is_superadmin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def permission_required(module, action="can_view"):
    """Usage: @permission_required('wiki', 'can_edit')"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.has_permission(module, action):
                return redirect(url_for("auth.no_access"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator