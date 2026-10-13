from flask import Blueprint, request, jsonify, send_file, session, redirect, make_response
from werkzeug.security import check_password_hash, generate_password_hash
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.common.auth import login_required, get_current_user

bp = Blueprint('login', __name__)

@bp.route('/login', methods=['GET','POST'])
def login():
    if session.get('user_id'):
        return redirect('/')
    error = ''
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        con = get_db()
        u = con.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        con.close()
        if u and check_password_hash(u['password_hash'], password):
            session.clear()
            session['user_id']   = u['id']
            session['username']  = u['username']
            session['role']      = u['role']
            session.permanent    = True
            return redirect('/')
        error = 'Invalid username or password'
    if error:
        return jsonify(error=error), 401
    return send_file(str(FRONTEND_DIR / 'login' / 'login.html'))


@bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@bp.route('/api/me')
@login_required
def api_me():
    u = get_current_user()
    return jsonify({'username': u['username'], 'role': u['role']})


@bp.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    data         = request.json or {}
    current      = data.get('current', '')
    new_password = (data.get('new_password') or '').strip()
    if not new_password or len(new_password) < 4:
        return jsonify({'error': 'New password must be at least 4 characters'}), 400
    con = get_db()
    u = con.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if not u or not check_password_hash(u['password_hash'], current):
        con.close()
        return jsonify({'error': 'Current password incorrect'}), 400
    con.execute('UPDATE users SET password_hash=? WHERE id=?',
                (generate_password_hash(new_password), session['user_id']))
    con.commit()
    con.close()
    return jsonify({'ok': True})


