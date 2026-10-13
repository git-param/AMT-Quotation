from functools import wraps
from flask import request, jsonify, session, redirect, make_response
from backend.database import get_db

def get_current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    con = get_db()
    u = con.execute('SELECT id,username,role FROM users WHERE id=?', (uid,)).fetchone()
    con.close()
    return dict(u) if u else None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Not logged in'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        u = get_current_user()
        if not u:
            return redirect('/login')
        if u['role'] != 'manager':
            return make_response('Access denied', 403)
        return f(*args, **kwargs)
    return decorated


