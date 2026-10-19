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
            'INSERT INTO security_events(user_id,username,event_type,severity,'
            'ip_address,user_agent,details) VALUES(?,?,?,?,?,?,?)',
            (user_id, (username or '')[:100], event_type[:100], severity,
             client_ip(), user_agent(), json.dumps(details or {})),
        )
        if own:
            db.commit()
    finally:
        if own:
            db.close()


def detect_login_anomaly(connection, username):
    """Record explainable credential-stuffing signals for review and alerting."""
    since = "julianday(created_at)>=julianday('now','-15 minutes')"
    account = connection.execute(
        'SELECT COUNT(*),COUNT(DISTINCT ip_address) FROM security_events '
        "WHERE event_type='login_failed' AND username=? AND " + since,
        (username,),
    ).fetchone()
    ip = client_ip()
    source = connection.execute(
        'SELECT COUNT(*),COUNT(DISTINCT username) FROM security_events '
        "WHERE event_type='login_failed' AND ip_address=? AND " + since,
        (ip,),
    ).fetchone()
    if account[0] == 5 or (account[0] > 5 and account[0] % 10 == 0):
        record('account_login_anomaly', 'critical', username=username,
               details={'failed_attempts_15m': account[0],
                        'source_ips_15m': account[1]}, connection=connection)
    if source[1] >= 5 and (source[0] == 5 or source[0] % 10 == 0):
        record('source_login_anomaly', 'critical', username=username,
               details={'failed_attempts_15m': source[0],
                        'accounts_targeted_15m': source[1]}, connection=connection)
