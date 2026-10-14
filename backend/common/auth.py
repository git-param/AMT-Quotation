"""Database-backed role permissions with legacy session compatibility."""

from functools import wraps

from flask import jsonify, redirect, request, session

from backend.database import get_db

ROLE_LABELS = {
    'user': 'Sales Executive (legacy)',
    'manager': 'Admin (legacy)',
    'sales_executive': 'Sales Executive',
    'sales_tl': 'Sales TL',
    'admin': 'Admin',
}


def get_current_user():
    """Revalidate accounts while preserving the existing session format."""
    uid = session.get('user_id')
    if not uid:
        return None
    connection = get_db()
    try:
        user = connection.execute(
            'SELECT id, username, role, is_active FROM users WHERE id = ?',
            (uid,),
        ).fetchone()
        return dict(user) if user and user['is_active'] else None
    finally:
        connection.close()


def get_permissions(user):
    """Read current grants; session role values are never trusted."""
    connection = get_db()
    try:
        return [row[0] for row in connection.execute(
            'SELECT permission_code FROM role_permissions '
            'WHERE role_code = ? ORDER BY permission_code', (user['role'],)
        )]
    finally:
        connection.close()


def permission_required(permission):
    """Reject anonymous APIs with 401 and authenticated denials with 403."""
    def decorate(function):
        @wraps(function)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                session.clear()
                if request.path.startswith('/api/'):
                    return jsonify(error='Not logged in'), 401
                return redirect('/login')
            if permission not in get_permissions(user):
                if request.path.startswith('/api/'):
                    return jsonify(error='Access denied'), 403
                return (
                    '<!doctype html><title>Access denied</title>'
                    '<h1>Access denied</h1>'
                    '<p>Your role does not allow access to this page.</p>'
                    '<a href="/">Quotation Tool</a> | '
                    '<a href="/logout">Sign out</a>', 403
                )
            return function(*args, **kwargs)
        return decorated
    return decorate


# Compatibility names retained for existing imports and quotation endpoints.
login_required = permission_required('quotation.use')
manager_required = permission_required('management.view')
