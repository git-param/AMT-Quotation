"""MAC-based enrollment. MACs are client-reported identifiers, not proof of hardware."""
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request, send_file, session

from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.common.auth import get_current_user, get_permissions
from backend.security.mac import normalize_mac

bp = Blueprint('devices', __name__)


def registration(user_id, mac):
    connection = get_db()
    try:
        row = connection.execute(
            'SELECT id,user_id,status,last_seen_at FROM device_registrations WHERE mac_address=?',
            (mac,)).fetchone()
        if row and row['user_id'] == user_id and row['status'] == 'approved':
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%fZ')
            if not row['last_seen_at'] or row['last_seen_at'] < cutoff:
                connection.execute(
                    "UPDATE device_registrations SET last_seen_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (row['id'],))
                connection.commit()
        return dict(row) if row else None
    finally:
        connection.close()


def device_status(user_id):
    cached = getattr(g, 'device_status_result', None)
    if cached and cached[0] == user_id:
        return cached[1]
    mac = normalize_mac(session.get('device_mac'))
    if not mac:
        status = 'missing'
    else:
        row = registration(user_id, mac)
        status = 'missing' if not row else row['status'] if row['user_id'] == user_id else 'unavailable'
    g.device_status_result = (user_id, status)
    return status


def request_registration(user_id, mac, name):
    name = name.strip() if isinstance(name, str) else ''
    if (not mac or not name or len(name) > 120
            or any(ord(character) < 32 or ord(character) == 127 for character in name)):
        return 'invalid'
    connection = get_db()
    try:
        with connection:
            row = connection.execute(
                'SELECT user_id,status FROM device_registrations WHERE mac_address=?',
                (mac,)).fetchone()
            if row:
                return row['status'] if row['user_id'] == user_id else 'unavailable'
            connection.execute(
                'INSERT INTO device_registrations(user_id,mac_address,device_name,status) '
                "VALUES(?,?,?,'pending')", (user_id, mac, name))
            return 'pending'
    except sqlite3.IntegrityError:
        # Another login can win the unique-MAC insert race.
        row = connection.execute(
            'SELECT user_id,status FROM device_registrations WHERE mac_address=?',
            (mac,)).fetchone()
        return row['status'] if row and row['user_id'] == user_id else 'unavailable'
    finally:
        connection.close()


@bp.get('/device/wait')
def waiting_page():
    if not get_current_user():
        return jsonify(error='Not logged in'), 401
    return send_file(str(FRONTEND_DIR / 'login' / 'device-wait.html'))


@bp.get('/api/device/status')
def status():
    user = get_current_user()
    if not user:
        return jsonify(error='Not logged in'), 401
    return jsonify(status=device_status(user['id']))


@bp.get('/api/admin/devices')
def list_devices():
    user = get_current_user()
    if not user:
        return jsonify(error='Not logged in'), 401
    if 'devices.manage' not in get_permissions(user):
        return jsonify(error='Access denied'), 403
    connection = get_db()
    try:
        rows = connection.execute(
            'SELECT d.id,d.user_id,u.username,d.mac_address,d.device_name,d.status,'
            'd.requested_at,d.decided_at,d.last_seen_at,a.username AS decided_by '
            'FROM device_registrations d JOIN users u ON u.id=d.user_id '
            'LEFT JOIN users a ON a.id=d.decided_by '
            'ORDER BY d.requested_at DESC,d.id DESC').fetchall()
        return jsonify(devices=[dict(row) for row in rows])
    finally:
        connection.close()


@bp.post('/api/admin/devices/<int:device_id>/<action>')
def decide_device(device_id, action):
    user = get_current_user()
    if not user:
        return jsonify(error='Not logged in'), 401
    if 'devices.manage' not in get_permissions(user):
        return jsonify(error='Access denied'), 403
    if action not in ('approve', 'reject', 'revoke'):
        return jsonify(error='Invalid action'), 400
    connection = get_db()
    try:
        with connection:
            row = connection.execute(
                'SELECT user_id,status FROM device_registrations WHERE id=?',
                (device_id,)).fetchone()
            if not row:
                return jsonify(error='Device not found'), 404
            if row['user_id'] == user['id']:
                return jsonify(error='You cannot approve or change your own device'), 403
            target = {'approve': 'approved', 'reject': 'rejected', 'revoke': 'revoked'}[action]
            allowed = (row['status'] == 'pending' and action in ('approve', 'reject')) or (
                row['status'] == 'approved' and action == 'revoke')
            if row['status'] == target:
                return jsonify(status=target)
            if not allowed:
                return jsonify(error='Invalid status transition'), 409
            connection.execute(
                "UPDATE device_registrations SET status=?,decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
                'decided_by=? WHERE id=?', (target, user['id'], device_id))
            connection.execute(
                "INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) "
                "VALUES(?,?,?,?,?,'{}')",
                (user['id'], user['username'], 'device.' + action, 'device_registration', str(device_id)))
        return jsonify(status=target)
    finally:
        connection.close()
