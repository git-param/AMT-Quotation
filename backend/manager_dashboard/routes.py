"""Permission-controlled activity statistics and account administration."""

import sqlite3

from flask import Blueprint, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.common.auth import (
    ROLE_LABELS, manager_required, permission_required,
)

bp = Blueprint('manager_dashboard', __name__)

@bp.route('/manager')
@manager_required
def manager():
    """Serve the management dashboard for authorized roles."""
    return send_file(
        str(FRONTEND_DIR / 'manager_dashboard' / 'manager.html')
    )


@bp.route('/api/manager/stats')
@manager_required
def api_manager_stats():
    """Return existing application-wide quotation activity statistics."""
    con = get_db()

    today_row = con.execute('''
        SELECT COUNT(*) searches,
               COALESCE(SUM(found_count + not_found), 0) skus_searched,
               COALESCE(SUM(found_count), 0) found
        FROM search_logs WHERE date(ts) = date('now','localtime')
    ''').fetchone()

    copies_today = con.execute(
        "SELECT COUNT(*) cnt FROM copy_logs "
        "WHERE date(ts)=date('now','localtime')"
    ).fetchone()

    by_day = con.execute('''
        SELECT date(ts) day, COUNT(*) searches,
               COALESCE(SUM(found_count + not_found), 0) skus
        FROM search_logs
        WHERE ts >= datetime('now', '-13 days', 'localtime')
        GROUP BY day ORDER BY day
    ''').fetchall()

    by_user = con.execute('''
        SELECT user_name,
               COUNT(*) searches,
               COALESCE(SUM(found_count + not_found), 0) skus,
               COALESCE(SUM(found_count), 0) found,
               MAX(ts) last_seen
        FROM search_logs
        GROUP BY user_name ORDER BY skus DESC LIMIT 20
    ''').fetchall()

    copy_types = con.execute('''
        SELECT copy_type, COUNT(*) cnt
        FROM copy_logs GROUP BY copy_type ORDER BY cnt DESC
    ''').fetchall()

    recent = con.execute('''
        SELECT user_name, skus, found_count, not_found, ts
        FROM search_logs ORDER BY id DESC LIMIT 60
    ''').fetchall()

    all_skus_rows = con.execute(
        'SELECT skus FROM search_logs WHERE skus != ""'
    ).fetchall()
    sku_freq = {}
    for row in all_skus_rows:
        for s in (row['skus'] or '').split(','):
            s = s.strip()
            if s:
                sku_freq[s] = sku_freq.get(s, 0) + 1
    top_skus = sorted(sku_freq.items(), key=lambda x: -x[1])[:15]

    con.close()
    return jsonify({
        'today': {
            'searches':      today_row['searches'],
            'skus_searched': today_row['skus_searched'],
            'found':         today_row['found'],
            'copies':        copies_today['cnt'],
        },
        'by_day':     [dict(r) for r in by_day],
        'by_user':    [dict(r) for r in by_user],
        'copy_types': [dict(r) for r in copy_types],
        'recent':     [dict(r) for r in recent],
        'top_skus':   [{'sku': k, 'count': v} for k, v in top_skus],
    })


def _request_data():
    """Treat malformed non-object JSON as an empty request."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.route('/api/manager/users')
@permission_required('users.manage')
def api_manager_users():
    """Return account metadata and assignable roles, never password hashes."""
    connection = get_db()
    try:
        rows = connection.execute(
            'SELECT id, username, role, is_active, created_at '
            'FROM users ORDER BY id'
        ).fetchall()
        return jsonify(users=[dict(row) for row in rows], roles=ROLE_LABELS)
    finally:
        connection.close()


@bp.route('/api/manager/users/add', methods=['POST'])
@permission_required('users.manage')
def api_manager_add_user():
    """Create an account using a current or legacy role."""
    data = _request_data()
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    role = data.get('role', 'sales_executive')
    if not username or len(password) < 4:
        return jsonify(error='Username and password (4+ chars) required'), 400
    if not isinstance(role, str) or role not in ROLE_LABELS:
        return jsonify(error='Invalid role'), 400
    connection = get_db()
    try:
        with connection:
            connection.execute(
                'INSERT INTO users (username, password_hash, role) '
                'VALUES (?, ?, ?)',
                (username, generate_password_hash(password), role),
            )
        return jsonify(ok=True)
    except sqlite3.IntegrityError:
        return jsonify(error='Username already exists'), 409
    finally:
        connection.close()


def _update_account(uid, role=None, active=None):
    """Serialize updates and prevent accidental administrator lockout."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        target = connection.execute(
            'SELECT role, is_active FROM users WHERE id = ?', (uid,)
        ).fetchone()
        if not target:
            return jsonify(error='User not found'), 404
        if uid == session['user_id']:
            return jsonify(error='Cannot change your own role or status'), 400
        loses_admin = (
            target['is_active'] and target['role'] in ('manager', 'admin')
            and (active == 0 or role not in (None, 'manager', 'admin'))
        )
        if loses_admin:
            count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1 "
                "AND role IN ('manager', 'admin')"
            ).fetchone()[0]
            if count <= 1:
                return jsonify(
                    error='Cannot remove the last active admin'
                ), 409
        if role is not None:
            connection.execute('UPDATE users SET role = ? WHERE id = ?',
                               (role, uid))
        if active is not None:
            connection.execute('UPDATE users SET is_active = ? WHERE id = ?',
                               (active, uid))
        connection.commit()
        return jsonify(ok=True)
    finally:
        connection.rollback()
        connection.close()


@bp.route('/api/manager/users/<int:uid>/role', methods=['POST'])
@permission_required('users.manage')
def api_manager_assign_role(uid):
    """Assign a role; existing sessions observe the change immediately."""
    role = (_request_data()).get('role')
    if not isinstance(role, str) or role not in ROLE_LABELS:
        return jsonify(error='Invalid role'), 400
    return _update_account(uid, role=role)


@bp.route('/api/manager/users/<int:uid>/deactivate', methods=['POST'])
@bp.route('/api/manager/users/<int:uid>/delete', methods=['POST'])
@permission_required('users.manage')
def api_manager_delete_user(uid):
    """Retain the legacy delete URL as a non-destructive deactivation alias."""
    return _update_account(uid, active=0)


@bp.route('/api/manager/users/<int:uid>/activate', methods=['POST'])
@permission_required('users.manage')
def api_manager_activate_user(uid):
    """Restore access without changing the existing password hash."""
    return _update_account(uid, active=1)


@bp.route('/api/manager/users/<int:uid>/reset-password', methods=['POST'])
@permission_required('users.manage')
def api_manager_reset_password(uid):
    """Reset another account's password without replacing session signing."""
    password = str((_request_data()).get('password') or '')
    if len(password) < 4:
        return jsonify(error='Password must be at least 4 characters'), 400
    connection = get_db()
    try:
        with connection:
            result = connection.execute(
                'UPDATE users SET password_hash = ? WHERE id = ?',
                (generate_password_hash(password), uid),
            )
        if not result.rowcount:
            return jsonify(error='User not found'), 404
        return jsonify(ok=True)
    finally:
        connection.close()
