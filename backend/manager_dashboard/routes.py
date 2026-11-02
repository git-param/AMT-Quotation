"""Permission-controlled activity statistics and account administration."""

import sqlite3
import re
import secrets

from flask import Blueprint, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.settings import department_names
from backend.security.passwords import error as password_error
from backend.security.sessions import revoke as revoke_sessions
from backend.common.auth import (
    ROLE_LABELS, admin_required, get_current_user, managed_user_ids, may_manage_user,
    manager_required, permission_required,
)

bp = Blueprint('manager_dashboard', __name__)


def _visible_usernames(connection, user):
    ids = managed_user_ids(connection, user)
    if ids is None:
        return None
    if not ids:
        return []
    return [row[0] for row in connection.execute(
        'SELECT username FROM users WHERE id IN (' + ','.join('?' for _ in ids) + ')',
        sorted(ids))]


@bp.route('/api/admin/roles')
@admin_required
def list_roles():
    con = get_db()
    try:
        roles = [dict(row) for row in con.execute(
            'SELECT code,description FROM roles ORDER BY code')]
        permissions = [dict(row) for row in con.execute(
            'SELECT code,description FROM permissions ORDER BY code')]
        grants = {row['code']: [] for row in roles}
        for row in con.execute('SELECT role_code,permission_code FROM role_permissions'):
            grants.setdefault(row['role_code'], []).append(row['permission_code'])
        counts = {row['role']: row['members'] for row in con.execute(
            'SELECT role,COUNT(*) members FROM users GROUP BY role')}
        return jsonify(roles=[dict(role, permissions=grants.get(role['code'], []),
                                   user_count=counts.get(role['code'], 0)) for role in roles],
                       permissions=permissions)
    finally:
        con.close()


@bp.route('/api/admin/roles', methods=['POST'])
@admin_required
def create_role():
    data = _request_data()
    code, description = data.get('code'), data.get('description')
    if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,39}', code):
        return jsonify(error='Use a role code with lowercase letters, numbers, and underscores.'), 400
    if not isinstance(description, str) or not description.strip() or len(description.strip()) > 80:
        return jsonify(error='Enter a role name up to 80 characters.'), 400
    permissions = data.get('permissions', [])
    if not isinstance(permissions, list) or any(not isinstance(p, str) for p in permissions):
        return jsonify(error='Invalid permissions.'), 400
    con = get_db()
    try:
        with con:
            known = {row[0] for row in con.execute('SELECT code FROM permissions')}
            if not set(permissions) <= known:
                return jsonify(error='Select valid module permissions.'), 400
            con.execute('INSERT INTO roles(code,description) VALUES(?,?)', (code, description.strip()))
            con.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES(?,?)',
                            [(code, permission) for permission in set(permissions)])
        return jsonify(ok=True), 201
    except sqlite3.IntegrityError:
        return jsonify(error='That role code already exists.'), 409
    finally:
        con.close()


@bp.route('/api/admin/roles/<code>', methods=['PUT', 'DELETE'])
@admin_required
def update_role(code):
    con = get_db()
    try:
        role = con.execute('SELECT code FROM roles WHERE code=?', (code,)).fetchone()
        if not role:
            return jsonify(error='Role not found.'), 404
        if request.method == 'DELETE':
            if code == 'admin':
                return jsonify(error='The Admin role cannot be deleted.'), 400
            if con.execute('SELECT 1 FROM users WHERE role=? LIMIT 1', (code,)).fetchone():
                return jsonify(error='Reassign users before deleting this role.'), 409
            with con:
                con.execute('DELETE FROM role_permissions WHERE role_code=?', (code,))
                con.execute('DELETE FROM roles WHERE code=?', (code,))
            return jsonify(ok=True)
        data = _request_data()
        description, permissions = data.get('description'), data.get('permissions')
        if not isinstance(description, str) or not description.strip() or len(description.strip()) > 80:
            return jsonify(error='Enter a role name up to 80 characters.'), 400
        if not isinstance(permissions, list) or any(not isinstance(p, str) for p in permissions):
            return jsonify(error='Invalid permissions.'), 400
        known = {row[0] for row in con.execute('SELECT code FROM permissions')}
        if not set(permissions) <= known:
            return jsonify(error='Select valid module permissions.'), 400
        with con:
            con.execute('UPDATE roles SET description=? WHERE code=?', (description.strip(), code))
            con.execute('DELETE FROM role_permissions WHERE role_code=?', (code,))
            con.executemany('INSERT INTO role_permissions(role_code,permission_code) VALUES(?,?)',
                            [(code, permission) for permission in set(permissions)])
        return jsonify(ok=True)
    finally:
        con.close()


@bp.route('/api/manager/logs')
@manager_required
def api_manager_logs():
    """Page through search and copy activity with server-side filters."""
    kind = (request.args.get('kind') or 'search').strip().lower()
    kind = 'copy' if kind == 'copy' else 'search'
    table = 'copy_logs' if kind == 'copy' else 'search_logs'
    columns = ('id, user_name, user_ip, copy_type, sku_count, ts' if kind == 'copy'
               else 'id, user_name, user_ip, skus, found_count, not_found, ts')
    searchable = ('user_name', 'copy_type') if kind == 'copy' else ('user_name', 'skus')
    try:
        page = max(1, int(request.args.get('page') or 1))
    except ValueError:
        page = 1
    clauses, params = [], []
    scope_connection = get_db()
    names = _visible_usernames(scope_connection, get_current_user())
    scope_connection.close()
    if names is not None:
        if not names:
            return jsonify(kind=kind, page=1, per_page=100, total=0, pages=0, rows=[], users=[])
        clauses.append('user_name IN (' + ','.join('?' for _ in names) + ')')
        params.extend(names)
    user = (request.args.get('user') or '').strip()
    if user:
        clauses.append('user_name = ?')
        params.append(user)
    for param, operator in (('from', '>='), ('to', '<=')):
        value = (request.args.get(param) or '').strip()
        if value:
            clauses.append(f'date(ts) {operator} date(?)')
            params.append(value)
    query = (request.args.get('q') or '').strip()
    if query:
        clauses.append('(' + ' OR '.join(f'{column} LIKE ?' for column in searchable) + ')')
        params.extend([f'%{query}%'] * len(searchable))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    connection = get_db()
    try:
        total = connection.execute(f'SELECT COUNT(*) FROM {table}{where}', params).fetchone()[0]
        rows = connection.execute(
            f'SELECT {columns} FROM {table}{where} ORDER BY id DESC LIMIT ? OFFSET ?',
            params + [100, (page - 1) * 100]).fetchall()
        users_query = f'SELECT DISTINCT user_name FROM {table}'
        user_params = []
        if names is not None:
            users_query += ' WHERE user_name IN (' + ','.join('?' for _ in names) + ')'
            user_params = names
        users = [row['user_name'] for row in connection.execute(
            users_query + ' ORDER BY user_name', user_params)]
    finally:
        connection.close()
    return jsonify(kind=kind, page=page, per_page=100, total=total,
                   pages=max(1, (total + 99) // 100), rows=[dict(row) for row in rows],
                   users=users)


@bp.route('/api/manager/reports')
@manager_required
def api_manager_reports():
    """Summarize quotation demand and copy activity."""
    connection = get_db()
    names = _visible_usernames(connection, get_current_user())
    scope_sql = '' if names is None else (' AND user_name IN (' + ','.join('?' for _ in names) + ')')
    scope_values = [] if names is None else names
    try:
        missing = connection.execute('''
            SELECT TRIM(skus) sku, COUNT(*) times, MAX(ts) last_asked
            FROM search_logs WHERE not_found > 0 AND found_count = 0
              AND skus NOT LIKE '%,%' AND TRIM(skus) <> '' '''+scope_sql+'''
            GROUP BY TRIM(skus) ORDER BY times DESC, last_asked DESC LIMIT 200
        ''', scope_values).fetchall()
        weekly = connection.execute('''
            SELECT strftime('%Y-%W', ts) week, MIN(date(ts)) week_start,
                   COALESCE(SUM(found_count), 0) found,
                   COALESCE(SUM(not_found), 0) missed
            FROM search_logs WHERE ts >= datetime('now', '-84 days', 'localtime')'''+scope_sql+'''
            GROUP BY week ORDER BY week
        ''', scope_values).fetchall()
        hours = connection.execute('''
            SELECT CAST(strftime('%H', ts) AS INTEGER) hour, COUNT(*) searches
            FROM search_logs WHERE 1=1'''+scope_sql+''' GROUP BY hour ORDER BY hour
        ''', scope_values).fetchall()
        copies = connection.execute('''
            SELECT copy_type, COUNT(*) copies, COALESCE(SUM(sku_count), 0) skus
            FROM copy_logs WHERE 1=1'''+scope_sql+''' GROUP BY copy_type ORDER BY copies DESC
        ''', scope_values).fetchall()
        totals = connection.execute('''
            SELECT COALESCE(SUM(found_count), 0) found,
                   COALESCE(SUM(not_found), 0) missed, COUNT(*) searches
            FROM search_logs WHERE 1=1'''+scope_sql,
            scope_values).fetchone()
        frequency = {}
        for row in connection.execute("SELECT skus FROM search_logs WHERE TRIM(COALESCE(skus,'')) <> ''"+scope_sql, scope_values):
            for sku in str(row['skus'] or '').split(','):
                sku = sku.strip()
                if sku:
                    frequency[sku] = frequency.get(sku, 0) + 1
    finally:
        connection.close()
    found, missed = int(totals['found']), int(totals['missed'])
    return jsonify(
        totals={'searches': int(totals['searches']), 'skus_found': found,
                'skus_missed': missed,
                'hit_rate': round(found * 100 / (found + missed), 1)
                            if found + missed else None,
                'distinct_missing': len(missing)},
        missing=[dict(row) for row in missing], hit_by_week=[dict(row) for row in weekly],
        by_hour=[dict(row) for row in hours], copy_types=[dict(row) for row in copies],
        top_skus=[{'sku': sku, 'count': count} for sku, count in
                  sorted(frequency.items(), key=lambda item: -item[1])[:50]],
        note='The could not quote list includes only single-SKU searches.'
    )


@bp.route('/api/manager/api-keys')
@admin_required
def api_manager_list_keys():
    """List key metadata without returning reusable credentials."""
    connection = get_db()
    try:
        rows = connection.execute(
            'SELECT id, label, created_at, last_used FROM api_keys ORDER BY id'
        ).fetchall()
        return jsonify(api_keys=[dict(row) for row in rows])
    finally:
        connection.close()


@bp.route('/api/manager/api-keys/create', methods=['POST'])
@admin_required
def api_manager_create_key():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('label', ''), str):
        return jsonify(error='Invalid label'), 400
    label = data.get('label', '').strip()[:80]
    key = 'amtq-' + secrets.token_urlsafe(32)
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute(
                'INSERT INTO api_keys (key, label) VALUES (?, ?)', (key, label)
            )
        return jsonify(id=cursor.lastrowid, key=key, label=label)
    finally:
        connection.close()


@bp.route('/api/manager/api-keys/<int:kid>/revoke', methods=['POST'])
@admin_required
def api_manager_revoke_key(kid):
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute('DELETE FROM api_keys WHERE id = ?', (kid,))
        if not cursor.rowcount:
            return jsonify(error='API key not found'), 404
        return jsonify(ok=True)
    finally:
        connection.close()


@bp.route('/manager')
@manager_required
def manager():
    """Serve the management dashboard for authorized roles."""
    return send_file(
        str(FRONTEND_DIR / 'manager_dashboard' / 'manager.html')
    )


@bp.route('/admin/roles')
@admin_required
def roles_page():
    return send_file(str(FRONTEND_DIR / 'manager_dashboard' / 'roles.html'))


@bp.route('/api/manager/stats')
@manager_required
def api_manager_stats():
    """Return activity statistics for the actor's authorized team."""
    con = get_db()
    names = _visible_usernames(con, get_current_user())
    scope_sql = '' if names is None else (' AND user_name IN (' + ','.join('?' for _ in names) + ')')
    scope_values = [] if names is None else names

    today_row = con.execute('''
        SELECT COUNT(*) searches,
               COALESCE(SUM(found_count + not_found), 0) skus_searched,
               COALESCE(SUM(found_count), 0) found
        FROM search_logs WHERE date(ts) = date('now','localtime')''' + scope_sql,
        scope_values).fetchone()

    copies_today = con.execute(
        "SELECT COUNT(*) cnt FROM copy_logs "
        "WHERE date(ts)=date('now','localtime')" + scope_sql,
        scope_values).fetchone()

    by_day = con.execute('''
        SELECT date(ts) day, COUNT(*) searches,
               COALESCE(SUM(found_count + not_found), 0) skus
        FROM search_logs
        WHERE ts >= datetime('now', '-13 days', 'localtime')'''+scope_sql+'''
        GROUP BY day ORDER BY day
    ''', scope_values).fetchall()

    by_user = con.execute('''
        SELECT user_name,
               COUNT(*) searches,
               COALESCE(SUM(found_count + not_found), 0) skus,
               COALESCE(SUM(found_count), 0) found,
               MAX(ts) last_seen
        FROM search_logs WHERE 1=1'''+scope_sql+'''
        GROUP BY user_name ORDER BY skus DESC LIMIT 20
    ''', scope_values).fetchall()

    copy_types = con.execute('''
        SELECT copy_type, COUNT(*) cnt
        FROM copy_logs WHERE 1=1'''+scope_sql+''' GROUP BY copy_type ORDER BY cnt DESC
    ''', scope_values).fetchall()

    recent = con.execute('''
        SELECT user_name, skus, found_count, not_found, ts
        FROM search_logs WHERE 1=1'''+scope_sql+''' ORDER BY id DESC LIMIT 60
    ''', scope_values).fetchall()

    all_skus_rows = con.execute(
        'SELECT skus FROM search_logs WHERE skus != ""'+scope_sql, scope_values
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
        actor = get_current_user()
        scope = managed_user_ids(connection, actor)
        rows = connection.execute(
            'SELECT id, username, department, phone_country_code, phone_number, role, is_active, created_at, '
            'supervisor_user_id '
            'FROM users ORDER BY id'
        ).fetchall()
        if scope is not None:
            rows = [row for row in rows if row['id'] in scope]
        role_rows = connection.execute('SELECT code,description FROM roles ORDER BY code').fetchall()
        roles = {row['code']: row['description'] for row in role_rows}
        return jsonify(users=[dict(row) for row in rows], roles=roles,
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
    actor = get_current_user()
    if not isinstance(role, str):
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
            valid = connection.execute('SELECT 1 FROM roles WHERE code=?', (role,)).fetchone()
            if not valid:
                return jsonify(error='Invalid role'), 400
            if actor['role'] == 'manager' and role in ('admin', 'manager'):
                return jsonify(error='Managers can assign only roles within their team.'), 403
            configured = connection.execute(
                'SELECT name FROM departments WHERE name = ?', (department,)
            ).fetchone()
            if not configured:
                return jsonify(error='Choose a department from Configuration'), 400
            department = configured['name']
            supervisor = actor['id'] if actor['role'] == 'manager' else None
            connection.execute(
                'INSERT INTO users (username, password_hash, role, department, '
                'phone_country_code, phone_number, supervisor_user_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (username, generate_password_hash(password), role, department,
                 phone_code or '', phone_number or '', supervisor),
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
        actor = get_current_user()
        if not may_manage_user(connection, actor, uid):
            return jsonify(error='That user is outside your team.'), 403
        if actor['role'] == 'manager' and uid != actor['id'] and role in ('admin', 'manager'):
            return jsonify(error='Managers cannot assign administrative roles.'), 403
        if uid == session['user_id']:
            return jsonify(error='Cannot change your own role or status'), 400
        loses_admin = (
            target['is_active'] and target['role'] == 'admin'
            and (active == 0 or role != 'admin')
        )
        if loses_admin:
            count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1 "
                "AND role = 'admin'"
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
    if not isinstance(role, str):
        return jsonify(error='Invalid role'), 400
    con = get_db()
    try:
        if not con.execute('SELECT 1 FROM roles WHERE code=?', (role,)).fetchone():
            return jsonify(error='Invalid role'), 400
    finally:
        con.close()
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
        actor = get_current_user()
        if not may_manage_user(connection, actor, uid):
            return jsonify(error='That user is outside your team.'), 403
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
        actor = get_current_user()
        if not may_manage_user(connection, actor, uid):
            return jsonify(error='That user is outside your team.'), 403
        if supervisor is not None:
            if not target['is_active'] or target['role'] not in (
                    'user', 'sales_executive', 'sales_tl'):
                return jsonify(error='Select an active team member.'), 400
            leader = connection.execute(
                'SELECT role, is_active FROM users WHERE id = ?',
                (supervisor,),
            ).fetchone()
            allowed = ('manager',) if target['role'] == 'sales_tl' else ('sales_tl', 'manager')
            if not leader or not leader['is_active'] or leader['role'] not in allowed:
                return jsonify(error='Choose an active manager or Sales TL as appropriate.'), 400
            if actor['role'] == 'manager' and not may_manage_user(connection, actor, supervisor):
                return jsonify(error='Supervisor must belong to your team.'), 403
            subtree = connection.execute('''WITH RECURSIVE team(id) AS (
                SELECT id FROM users WHERE id=? UNION
                SELECT u.id FROM users u JOIN team t ON u.supervisor_user_id=t.id
            ) SELECT 1 FROM team WHERE id=? LIMIT 1''', (uid, supervisor)).fetchone()
            if subtree:
                return jsonify(error='A user cannot report to someone in their own team branch.'), 400
        elif actor['role'] == 'manager' and uid != actor['id']:
            return jsonify(error='Team members must remain assigned within your team.'), 403
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
    if not isinstance(role, str):
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
        actor = get_current_user()
        if not may_manage_user(connection, actor, uid):
            return jsonify(error='That user is outside your team.'), 403
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
        if not connection.execute('SELECT 1 FROM roles WHERE code=?', (role,)).fetchone():
            return jsonify(error='Invalid role'), 400
        if actor['role'] == 'manager' and role in ('admin', 'manager') and uid != actor['id']:
            return jsonify(error='Managers cannot assign administrative roles.'), 403
        department = configured['name']
        if uid == session['user_id'] and (
                role != target['role'] or active != target['is_active']):
            return jsonify(error='Cannot change your own role or status'), 400
        if (target['is_active'] and target['role'] == 'admin'
                and (not active or role != 'admin')):
            count = connection.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1 "
                "AND role = 'admin'"
            ).fetchone()[0]
            if count <= 1:
                return jsonify(error='Cannot remove the last active admin'), 409
        if supervisor is not None:
            if supervisor == uid:
                return jsonify(error='Self-supervision is not allowed'), 400
            if not active or role not in ('user', 'sales_executive', 'sales_tl'):
                return jsonify(error='Only active team members can have a supervisor'), 400
            leader = connection.execute(
                'SELECT role, is_active FROM users WHERE id = ?', (supervisor,)
            ).fetchone()
            permitted_leaders = ('sales_tl', 'manager') if role in ('user','sales_executive') else ('manager',)
            if not leader or not leader['is_active'] or leader['role'] not in permitted_leaders:
                return jsonify(error='Choose an active manager or Sales TL as appropriate.'), 400
            if actor['role'] == 'manager' and not may_manage_user(connection, actor, supervisor):
                return jsonify(error='Supervisor must belong to your team.'), 403
            subtree = connection.execute('''WITH RECURSIVE team(id) AS (
                SELECT id FROM users WHERE id=? UNION
                SELECT u.id FROM users u JOIN team t ON u.supervisor_user_id=t.id
            ) SELECT 1 FROM team WHERE id=? LIMIT 1''', (uid, supervisor)).fetchone()
            if subtree:
                return jsonify(error='A user cannot report to someone in their own team branch.'), 400
        elif actor['role'] == 'manager' and uid != actor['id']:
            return jsonify(error='Team members must remain assigned within your team.'), 403
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
