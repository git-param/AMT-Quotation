"""Existing session login and self-service endpoints with RBAC checks."""

from flask import Blueprint, jsonify, redirect, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

from backend.common.auth import (
    ROLE_LABELS, get_current_user, get_permissions, permission_required,
)
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('login', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Accept legacy credentials while denying inactive accounts."""
    if get_current_user():
        return redirect('/')
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        connection = get_db()
        try:
            user = connection.execute(
                'SELECT * FROM users WHERE username = ?', (username,)
            ).fetchone()
        finally:
            connection.close()
        if (user and user['is_active']
                and check_password_hash(user['password_hash'], password)):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session.permanent = True
            return redirect('/')
        return jsonify(error='Invalid username or password'), 401
    return send_file(str(FRONTEND_DIR / 'login' / 'login.html'))


@bp.route('/logout')
def logout():
    """Clear the current session, including sessions for inactive accounts."""
    session.clear()
    return redirect('/login')


@bp.route('/api/me')
@permission_required('account.self')
def api_me():
    """Expose current database grants for permission-aware navigation."""
    user = get_current_user()
    return jsonify({
        'id': user['id'], 'username': user['username'], 'role': user['role'],
        'role_label': ROLE_LABELS.get(user['role'], user['role']),
        'permissions': get_permissions(user),
    })


@bp.route('/api/change-password', methods=['POST'])
@permission_required('account.self')
def api_change_password():
    """Preserve the existing password change and session behavior."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error='Invalid request'), 400
    current = data.get('current', '')
    new_password = (data.get('new_password') or '').strip()
    if not new_password or len(new_password) < 4:
        return jsonify(error='New password must be at least 4 characters'), 400
    connection = get_db()
    try:
        user = connection.execute(
            'SELECT * FROM users WHERE id = ?', (session['user_id'],)
        ).fetchone()
        if not user or not check_password_hash(user['password_hash'], current):
            return jsonify(error='Current password incorrect'), 400
        with connection:
            connection.execute(
                'UPDATE users SET password_hash = ? WHERE id = ?',
                (generate_password_hash(new_password), session['user_id']),
            )
        return jsonify(ok=True)
    finally:
        connection.close()
