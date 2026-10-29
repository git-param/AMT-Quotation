"""Append-only security event recording without credentials or request bodies."""
import json

from backend.database import get_db
from backend.security.request import client_ip, user_agent


def record(event_type, severity='info', user_id=None, username='', details=None,
           connection=None):
    own = connection is None
    db = connection or get_db()
    try:
        db.execute(
            'INSERT INTO security_events(user_id,username,role,event_type,severity,'
            'ip_address,user_agent,details) VALUES(?,?,?,?,?,?,?,?)',
            (user_id, (username or '')[:100], _role(db, user_id),
             event_type[:100], severity, client_ip(), user_agent(),
             json.dumps(details or {})),
        )
        from backend.security.audit import record_action
        record_action(event_type, 'security', user_id,
                      {'severity': severity, **(details or {})},
                      actor={'id': user_id, 'username': username or '',
                             'role': _role(db, user_id)}, connection=db)
        if own:
            db.commit()
    finally:
        if own:
            db.close()


def _role(connection, user_id):
    if not user_id:
        return ''
    row = connection.execute('SELECT role FROM users WHERE id=?',
                             (user_id,)).fetchone()
    return row['role'] if row else ''
