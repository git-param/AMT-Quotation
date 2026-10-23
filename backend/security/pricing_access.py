"""Quotation IP policy managed by the Pricing App's shared security tables."""
import ipaddress
import threading
import time

from backend.quotation_tool.pricing_db import connect

_lock = threading.Lock()
_cache = {'at': 0.0, 'policy': None}


def load_policy():
    """Use the last good policy if the shared database is temporarily unavailable."""
    now = time.monotonic()
    with _lock:
        if _cache['policy'] is not None and now - _cache['at'] < 30:
            return _cache['policy']
    try:
        connection = connect()
        try:
            cursor = connection.cursor()
            cursor.execute('SELECT key, value FROM public.sec_config')
            settings = {str(row['key']): str(row['value'] or '')
                        for row in cursor.fetchall()}
            cursor.execute('SELECT username, ips FROM public.sec_user_ips')
            users = {str(row['username'] or '').strip().lower(): str(row['ips'] or '')
                     for row in cursor.fetchall()}
            cursor.close()
        finally:
            connection.close()
    except Exception:
        with _lock:
            return _cache['policy'] or {'_users': {}}
    settings['_users'] = users
    with _lock:
        _cache.update(at=now, policy=settings)
    return settings


def _enabled(policy, key, default='0'):
    return str(policy.get(key, default) or default).strip().lower() in (
        '1', 'true', 'yes', 'on')


def _matches(ip, allowed):
    try:
        address = ipaddress.ip_address(str(ip or '').strip())
    except ValueError:
        return False
    for part in str(allowed or '').replace('\n', ',').replace(' ', ',').split(','):
        if not part.strip():
            continue
        try:
            if address in ipaddress.ip_network(part.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def access_decision(username, role, ip):
    """Return (allowed, reason) with production's admin and internal proxy rules."""
    policy = load_policy()
    if not _enabled(policy, 'ip_enforce'):
        return True, 'disabled'
    if role in ('admin', 'manager') and _enabled(policy, 'admin_anywhere', '1'):
        return True, 'admin_anywhere'
    try:
        address = ipaddress.ip_address(str(ip or '').strip())
        if address.is_private or address.is_loopback:
            # Match production's lockout protection when only an internal proxy
            # address is visible. Configure AMT_TRUSTED_PROXY_COUNT correctly.
            return True, 'internal_proxy'
    except ValueError:
        pass
    allowed = (policy.get('office_ips', '') + ',' +
               policy.get('_users', {}).get(str(username or '').strip().lower(), ''))
    matched = _matches(ip, allowed)
    return matched, 'allowed_ip' if matched else 'blocked_ip'
