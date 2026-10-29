"""Database-backed role permissions with legacy session compatibility."""

from functools import wraps

from flask import current_app, g, jsonify, redirect, request, session

from backend.database import get_db

ROLE_LABELS = {
    'user': 'Quotation User',
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
        if not user or not user['is_active']:
            return None
        # Hand-built legacy sessions remain available only to isolated tests.
        if not current_app.testing:
            from backend.security.sessions import validate
            if not validate(connection, uid):
                return None
        return dict(user)
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


def get_api_key():
    """Validate a legacy quotation API key once per request."""
    if hasattr(g, 'quotation_api_key'):
        return g.quotation_api_key
    key = request.headers.get('X-API-Key') or request.args.get('api_key')
    g.quotation_api_key = None
    if not key:
        return None
    connection = get_db()
    try:
        row = connection.execute(
            'SELECT id, label FROM api_keys WHERE key = ?', (key,)
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE api_keys SET last_used = datetime('now','localtime') WHERE id = ?",
                (row['id'],),
            )
            connection.commit()
            g.quotation_api_key = dict(row)
        return g.quotation_api_key
    finally:
        connection.close()


def request_actor_name():
    """Name the session user or quotation key for activity logs."""
    user = get_current_user()
    if user:
        return user['username']
    key = getattr(g, 'quotation_api_key', None)
    if key:
        return 'API: ' + key['label'] if key['label'] else 'API'
    return 'Unknown'


def permission_required(permission, *, allow_api_key=False):
    """Reject anonymous APIs with 401 and authenticated denials with 403."""
    def decorate(function):
        @wraps(function)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                if (allow_api_key and request.path.startswith('/api/')
                        and get_api_key()):
                    return function(*args, **kwargs)
                session.clear()
                if request.path.startswith('/api/'):
                    return jsonify(error='Not logged in'), 401
                return redirect('/login')
            if (user['role'] == 'user'
                    and permission != 'quotation.use'
                    and request.path not in ('/api/me', '/api/change-password')):
                if request.path.startswith('/api/'):
                    return jsonify(error='This account can access only the Quotation Tool.'), 403
                return (
                    '<!doctype html><title>Access denied</title>'
                    '<h1>Access denied</h1>'
                    '<p>This account can access only the Quotation Tool.</p>'
                    '<a href="/">Open Quotation Tool</a> | '
                    '<a href="/logout">Sign out</a>', 403
                )
            if (permission is not None
                    and permission not in get_permissions(user)):
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
login_required = permission_required('quotation.use', allow_api_key=True)
manager_required = permission_required('management.view')

# Account validation without a role restriction for lead creation.
authenticated_required = permission_required(None)
