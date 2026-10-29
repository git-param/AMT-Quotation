"""Revocable server-side sessions for account logins."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets

from flask import session

from backend.security.request import client_ip, user_agent


IDLE_MINUTES = int(os.getenv('AMT_SESSION_IDLE_MINUTES', '30'))
ABSOLUTE_HOURS = int(os.getenv('AMT_SESSION_ABSOLUTE_HOURS', '12'))


def _now():
    return datetime.now(timezone.utc)


def _stamp(value):
    return value.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _parse(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def token_hash(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def create(connection, user):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = _now()
    connection.execute(
        'INSERT INTO app_sessions(id_hash,user_id,created_at,last_seen_at,expires_at,'
        'ip_address,user_agent) VALUES(?,?,?,?,?,?,?)',
        (token_hash(token), user['id'], _stamp(now), _stamp(now),
         _stamp(now + timedelta(hours=ABSOLUTE_HOURS)), client_ip(), user_agent()),
    )
    session.clear()
    session.update(user_id=user['id'], username=user['username'], sid=token,
                   csrf_token=csrf)
    session.permanent = True
    return token


def validate(connection, user_id):
    token = session.get('sid')
    if not isinstance(token, str):
        return False
    row = connection.execute(
        'SELECT * FROM app_sessions WHERE id_hash=? AND user_id=?',
        (token_hash(token), user_id)
    ).fetchone()
    if not row or not hmac.compare_digest(row['id_hash'], token_hash(token)):
        return False
    now = _now()
    if row['revoked_at'] or now >= _parse(row['expires_at']):
        return False
    last = _parse(row['last_seen_at'])
    if now - last > timedelta(minutes=IDLE_MINUTES):
        connection.execute(
            "UPDATE app_sessions SET revoked_at=?,revoke_reason='idle_timeout' "
            'WHERE id_hash=?', (_stamp(now), row['id_hash']))
        connection.commit()
        return False
    if now - last > timedelta(minutes=5):
        connection.execute('UPDATE app_sessions SET last_seen_at=? WHERE id_hash=?',
                           (_stamp(now), row['id_hash']))
        connection.commit()
    return True


def revoke(connection, user_id, reason):
    connection.execute(
        'UPDATE app_sessions SET revoked_at=?,revoke_reason=? '
        'WHERE user_id=? AND revoked_at IS NULL',
        (_stamp(_now()), reason[:100], user_id),
    )


def revoke_current(connection, reason='logout'):
    token = session.get('sid')
    if isinstance(token, str):
        connection.execute(
            'UPDATE app_sessions SET revoked_at=?,revoke_reason=? '
            'WHERE id_hash=? AND revoked_at IS NULL',
            (_stamp(_now()), reason[:100], token_hash(token)),
        )
