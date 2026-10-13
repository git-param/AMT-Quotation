from flask import Blueprint, request, jsonify, send_file, session, redirect, make_response
import sqlite3
from werkzeug.security import generate_password_hash
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.common.auth import manager_required

bp = Blueprint('manager_dashboard', __name__)

@bp.route('/manager')
@manager_required
def manager():
    return send_file(str(FRONTEND_DIR / 'manager_dashboard' / 'manager.html'))


@bp.route('/api/manager/stats')
@manager_required
def api_manager_stats():
    con = get_db()

    today_row = con.execute('''
        SELECT COUNT(*) searches,
               COALESCE(SUM(found_count + not_found), 0) skus_searched,
               COALESCE(SUM(found_count), 0) found
        FROM search_logs WHERE date(ts) = date('now','localtime')
    ''').fetchone()

    copies_today = con.execute(
        "SELECT COUNT(*) cnt FROM copy_logs WHERE date(ts)=date('now','localtime')"
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

    all_skus_rows = con.execute('SELECT skus FROM search_logs WHERE skus != ""').fetchall()
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


@bp.route('/api/manager/users')
@manager_required
def api_manager_users():
    con = get_db()
    rows = con.execute('SELECT id, username, role, created_at FROM users ORDER BY id').fetchall()
    con.close()
    return jsonify({'users': [dict(r) for r in rows]})


@bp.route('/api/manager/users/add', methods=['POST'])
@manager_required
def api_manager_add_user():
    data     = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    role     = data.get('role', 'user')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if role not in ('user', 'manager'):
        return jsonify({'error': 'Invalid role'}), 400
    try:
        con = get_db()
        con.execute('INSERT INTO users (username, password_hash, role) VALUES (?,?,?)',
                    (username, generate_password_hash(password), role))
        con.commit()
        con.close()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 409


@bp.route('/api/manager/users/<int:uid>/delete', methods=['POST'])
@manager_required
def api_manager_delete_user(uid):
    if uid == session.get('user_id'):
        return jsonify({'error': 'Cannot delete yourself'}), 400
    con = get_db()
    target = con.execute('SELECT username, role FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        con.close()
        return jsonify({'error': 'User not found'}), 404
    if target['username'] == 'manager':
        con.close()
        return jsonify({'error': 'The main manager account cannot be deleted'}), 403
    con.execute('DELETE FROM users WHERE id=?', (uid,))
    con.commit()
    con.close()
    return jsonify({'ok': True})


@bp.route('/api/manager/users/<int:uid>/reset-password', methods=['POST'])
@manager_required
def api_manager_reset_password(uid):
    data     = request.json or {}
    password = (data.get('password') or '').strip()
    if not password or len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400
    con = get_db()
    con.execute('UPDATE users SET password_hash=? WHERE id=?', (generate_password_hash(password), uid))
    con.commit()
    con.close()
    return jsonify({'ok': True})


