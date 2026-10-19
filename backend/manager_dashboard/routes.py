"""Permission-controlled activity statistics and account administration."""

import sqlite3
import re

from flask import Blueprint, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.settings import department_names
from backend.security.passwords import error as password_error
from backend.security.sessions import revoke as revoke_sessions
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


def _user_phone(data):
    """Accept optional paired phone fields; omitted fields preserve an edit."""
    if not {'phone_country_code', 'phone_number'} & data.keys():
        return None, None
    code = data.get('phone_country_code', '')
    number = data.get('phone_number', '')
    if not isinstance(code, str) or not isinstance(number, str):
        raise ValueError('Enter a valid country code and phone number')
    code, number = code.strip(), number.strip()
    if not code and not number:
        return '', ''
    if not re.fullmatch(r'\+?[1-9][0-9]{0,2}', code):
        raise ValueError('Enter a country code such as +91 or +1')
    if len(number) > 40 or not re.fullmatch(r'[0-9 ()-]+', number):
        raise ValueError('Enter a phone number using digits, spaces, parentheses or hyphens')
    code = '+' + code.lstrip('+')
    number = re.sub(r'[^0-9]', '', number)
    if len(number) < 4 or not 7 <= len(code[1:] + number) <= 15:
        raise ValueError('Enter a phone number with 7 to 15 digits including the country code')
    return code, number


@bp.route('/api/manager/users')
@permission_required('users.manage')
def api_manager_users():
    """Return account metadata and assignable roles, never password hashes."""
    connection = get_db()
    try:
        rows = connection.execute(
            'SELECT id, username, department, phone_country_code, phone_number, role, is_active, created_at, '
            'supervisor_user_id '
            'FROM users ORDER BY id'
        ).fetchall()
        return jsonify(users=[dict(row) for row in rows], roles=ROLE_LABELS,
                       departments=department_names(connection))
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
    department = data.get('department')
    if not username:
        return jsonify(error='Username is required'), 400
    problem = password_error(password)
    if problem:
        return jsonify(error=problem), 400
    if not isinstance(role, str) or role not in ROLE_LABELS:
        return jsonify(error='Invalid role'), 400
    if not isinstance(department, str) or not department.strip():
        return jsonify(error='Department is required'), 400
    department = department.strip()
    if len(department) > 100:
        return jsonify(error='Department must be 100 characters or fewer'), 400
    try:
        phone_code, phone_number = _user_phone(data)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    connection = get_db()
    try:
        with connection:
            configured = connection.execute(
                'SELECT name FROM departments WHERE name = ?', (department,)
            ).fetchone()
            if not configured:
                return jsonify(error='Choose a department from Configuration'), 400
            department = configured['name']
            connection.execute(
                'INSERT INTO users (username, password_hash, role, department, '
                'phone_country_code, phone_number) VALUES (?, ?, ?, ?, ?, ?)',
                (username, generate_password_hash(password), role, department,
                 phone_code or '', phone_number or ''),
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
            if active == 0:
                revoke_sessions(connection, uid, 'account_deactivated')
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
    problem = password_error(password)
    if problem:
        return jsonify(error=problem), 400
    connection = get_db()
    try:
        with connection:
            result = connection.execute(
                'UPDATE users SET password_hash = ? WHERE id = ?',
                (generate_password_hash(password), uid),
            )
            revoke_sessions(connection, uid, 'admin_password_reset')
        if not result.rowcount:
            return jsonify(error='User not found'), 404
        return jsonify(ok=True)
    finally:
        connection.close()


@bp.route('/api/manager/users/<int:uid>/supervisor', methods=['POST'])
@permission_required('users.manage')
def assign_supervisor(uid):
    """Configure the sole supervisor relationship for an active executive."""
    data = _request_data()
    if 'supervisor_user_id' not in data:
        return jsonify(error='Supervisor field is required.'), 400
    supervisor = data['supervisor_user_id']
    if supervisor is not None and type(supervisor) is not int:
        return jsonify(error='Invalid supervisor ID.'), 400
    if supervisor == uid:
        return jsonify(error='Self-supervision is not allowed.'), 400
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        target = connection.execute(
            'SELECT role, is_active FROM users WHERE id = ?', (uid,)
        ).fetchone()
        if not target:
            return jsonify(error='User not found.'), 404
        if supervisor is not None:
            if not target['is_active'] or target['role'] not in (
                    'user', 'sales_executive'):
                return jsonify(error='Select an active executive.'), 400
            leader = connection.execute(
                'SELECT role, is_active FROM users WHERE id = ?',
                (supervisor,),
            ).fetchone()
            if not leader or not leader['is_active'] or leader['role'] != (
                    'sales_tl'):
                return jsonify(error='Select an active Sales TL.'), 400
        connection.execute(
            'UPDATE users SET supervisor_user_id = ? WHERE id = ?',
            (supervisor, uid),
        )
        connection.commit()
        return jsonify(ok=True)
    finally:
        connection.rollback()
        connection.close()

@bp.route('/api/manager/users/<int:uid>/edit', methods=['POST'])
@permission_required('users.manage')
def edit_user(uid):
    """Save profile and account settings together without partial changes."""
    data = _request_data()
    username = data.get('username')
    department = data.get('department')
    role = data.get('role')
    active = data.get('is_active')
    supervisor = data.get('supervisor_user_id')
    if not isinstance(username, str) or not 1 <= len(username.strip()) <= 40:
        return jsonify(error='Username must be 1 to 40 characters'), 400
    if not isinstance(department, str) or not 1 <= len(department.strip()) <= 100:
        return jsonify(error='Department is required (100 characters or fewer)'), 400
    if not isinstance(role, str) or role not in ROLE_LABELS:
        return jsonify(error='Invalid role'), 400
    if type(active) is not int or active not in (0, 1):
        return jsonify(error='Invalid account status'), 400
    if ('supervisor_user_id' not in data or
            (supervisor is not None and
             (type(supervisor) is not int or not 1 <= supervisor <= 9223372036854775807))):
        return jsonify(error='Invalid supervisor ID'), 400
    try:
        phone_code, phone_number = _user_phone(data)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        target = connection.execute(
            'SELECT role, is_active FROM users WHERE id = ?', (uid,)
        ).fetchone()
        if not target:
            return jsonify(error='User not found'), 404
        configured = connection.execute(
            'SELECT name FROM departments WHERE name = ?', (department.strip(),)
        ).fetchone()
        if not configured:
            return jsonify(error='Choose a department from Configuration'), 400
        department = configured['name']
        if uid == session['user_id'] and (
                role != target['role'] or active != target['is_active']):
            return jsonify(error='Cannot change your own role or status'), 400
        if (target['is_active'] and target['role'] in ('admin', 'manager')
                and (not active or role not in ('admin', 'manager'))):
            count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1 "
                "AND role IN ('admin', 'manager')"
            ).fetchone()[0]
            if count <= 1:
                return jsonify(error='Cannot remove the last active admin'), 409
        if supervisor is not None:
            if supervisor == uid:
                return jsonify(error='Self-supervision is not allowed'), 400
            if not active or role not in ('user', 'sales_executive'):
                return jsonify(error='Only active executives can have a supervisor'), 400
            leader = connection.execute(
                'SELECT role, is_active FROM users WHERE id = ?', (supervisor,)
            ).fetchone()
            if not leader or not leader['is_active'] or leader['role'] != 'sales_tl':
                return jsonify(error='Select an active Sales TL'), 400
        connection.execute(
            'UPDATE users SET username = ?, department = ?, role = ?, '
            'is_active = ?, supervisor_user_id = ?, '
            'phone_country_code = COALESCE(?, phone_country_code), '
            'phone_number = COALESCE(?, phone_number) WHERE id = ?',
            (username.strip(), department.strip(), role, active, supervisor,
             phone_code, phone_number, uid),
        )
        if not active:
            revoke_sessions(connection, uid, 'account_deactivated')
        connection.commit()
        if uid == session['user_id']:
            session['username'] = username.strip()
        return jsonify(ok=True)
    except sqlite3.IntegrityError:
        return jsonify(error='Username already exists'), 409
    finally:
        connection.rollback()
        connection.close()


# Register the separate TL workspace after this blueprint is defined.
from backend.manager_dashboard import team  # noqa: E402,F401
