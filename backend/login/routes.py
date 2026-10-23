"""Existing session login and self-service endpoints with RBAC checks."""

import hashlib

from flask import Blueprint, current_app, jsonify, redirect, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

from backend.common.auth import (
    ROLE_LABELS, get_current_user, get_permissions, permission_required,
)
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.security.events import detect_login_anomaly, record
from backend.security.limiter import hit
from backend.security.passwords import error as password_error
from backend.security.request import client_ip
from backend.security.sessions import create as create_session, revoke_current
from backend.security.devices import normalize_mac, request_registration, device_status

bp = Blueprint('login', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Accept legacy credentials while denying inactive accounts."""
    existing = get_current_user()
    if existing:
        return redirect('/' if device_status(existing['id']) == 'approved' else '/device/wait')
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        ip_key = hashlib.sha256(client_ip().encode()).hexdigest()[:32]
        account_key = hashlib.sha256(username.casefold().encode()).hexdigest()[:32]
        limits = () if current_app.testing else (
                ('login_ip', ip_key, 20), ('login_account', account_key, 5))
        for scope, identity, limit in limits:
            allowed, retry, backend = hit(scope, identity, limit, 15 * 60)
            if not allowed:
                try:
                    record('login_rate_limited', 'warning', username=username,
                           details={'scope': scope, 'backend': backend})
                except Exception:
                    pass
                response = jsonify(error='Too many login attempts. Try again later.')
                response.status_code = 429
                response.headers['Retry-After'] = str(retry)
                return response
        connection = get_db()
        try:
            user = connection.execute(
                'SELECT * FROM users WHERE username = ?', (username,)
            ).fetchone()
            if (user and user['is_active']
                    and check_password_hash(user['password_hash'], password)):
                mac = normalize_mac(request.form.get('mac_address'))
                name = request.form.get('device_name') or ''
                if not mac or not isinstance(name, str) or not name.strip():
                    return jsonify(error='Device identification is unavailable. Open AMT Quotation through the Windows desktop launcher.'), 400
                status = request_registration(user['id'], mac, name)
                if status == 'unavailable':
                    return jsonify(error='This MAC address is registered to another account.'), 409
                if status == 'invalid':
                    return jsonify(error='Device details from the Windows launcher are invalid. Reopen the application.'), 400
                create_session(connection, user)
                session['device_mac'] = mac
                record('login_succeeded', user_id=user['id'], username=user['username'],
                       details={'replaced_previous_session': True}, connection=connection)
                connection.commit()
                return redirect('/' if status == 'approved' else '/device/wait')
            record('login_failed', 'warning', user['id'] if user else None,
                   username, {'known_account': bool(user)}, connection=connection)
            detect_login_anomaly(connection, username)
            connection.commit()
        finally:
            connection.close()
        return jsonify(error='Invalid username or password'), 401
    return send_file(str(FRONTEND_DIR / 'login' / 'login.html'))


@bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """Clear the current session, including sessions for inactive accounts."""
    if request.method == 'GET' and not current_app.testing:
        return jsonify(error='Use POST to sign out.'), 405
    connection = get_db()
    try:
        with connection:
            revoke_current(connection)
            if session.get('user_id'):
                record('logout', user_id=session.get('user_id'),
                       username=session.get('username', ''), connection=connection)
    finally:
        connection.close()
    session.clear()
    return redirect('/login')


@bp.route('/api/me')
@permission_required('account.self', allow_api_key=True)
def api_me():
    """Expose current database grants for permission-aware navigation."""
    user = get_current_user()
    if not user:
        return jsonify(username='api-key', role='api', auth='api_key')
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
    problem = password_error(new_password)
    if problem:
        return jsonify(error=problem), 400
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
            create_session(connection, user)
            record('password_changed', user_id=user['id'], username=user['username'],
                   details={'all_other_sessions_revoked': True}, connection=connection)
        return jsonify(ok=True)
    finally:
        connection.close()
