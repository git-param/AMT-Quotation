"""Scoped lead sharing with transactional grants and retained event history."""

from flask import Blueprint, jsonify, request, send_file

from backend.client_leads.routes import management_edit_scope
from backend.common.auth import (
    get_current_user, get_permissions, permission_required,
)
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('client_access', __name__)


def management_scope(user):
    """Shared VIEW/EDIT grants never provide sharing authority."""
    if (user['role'] not in ('admin', 'manager', 'sales_tl')
            or 'leads.share_manage' not in get_permissions(user)):
        return '0 = 1', []
    return management_edit_scope(user)


def managed_leads(connection, user, lead_id=None):
    """Apply ownership/supervision checks inside management queries."""
    predicate, parameters = management_scope(user)
    sql = (
        'SELECT l.*, u.username AS creator_name FROM client_leads l '
        'JOIN users u ON u.id = l.created_by WHERE (' + predicate + ')'
    )
    if lead_id is not None:
        sql += ' AND l.id = ?'
        parameters.append(lead_id)
    return [dict(row) for row in connection.execute(
        sql + ' ORDER BY l.id DESC', parameters
    )]


@bp.route('/client-access')
@permission_required('leads.share_manage')
def sharing_page():
    """Serve a separate access-management section."""
    if get_current_user()['role'] not in ('admin', 'manager', 'sales_tl'):
        return 'Access denied', 403
    return send_file(str(FRONTEND_DIR / 'client_access' / 'access.html'))


@bp.route('/api/client-access')
@permission_required('leads.share_manage')
def sharing_options():
    """Return only manageable leads and active executive recipient choices."""
    user = get_current_user()
    if user['role'] not in ('admin', 'manager', 'sales_tl'):
        return jsonify(error='Access denied'), 403
    connection = get_db()
    try:
        executives = connection.execute(
            "SELECT id, username FROM users WHERE is_active = 1 "
            "AND role IN ('user', 'sales_executive') ORDER BY username"
        ).fetchall()
        return jsonify(
            leads=managed_leads(connection, user), username=user['username'],
            executives=[dict(row) for row in executives],
        )
    finally:
        connection.close()


@bp.route('/api/client-access/<int:lead_id>')
@permission_required('leads.share_manage')
def sharing_details(lead_id):
    """Expose shares and history only for a lead the actor may manage."""
    connection = get_db()
    try:
        user = get_current_user()
        if not managed_leads(connection, user, lead_id):
            return jsonify(error='Client not found.'), 404
        shares = connection.execute(
            'SELECT s.*, u.username, u.is_active AS account_active '
            'FROM client_lead_shares s JOIN users u ON u.id = s.user_id '
            'WHERE s.lead_id = ? ORDER BY u.username', (lead_id,),
        ).fetchall()
        events = connection.execute(
            'SELECT e.*, u.username AS recipient_name '
            'FROM client_share_events e JOIN users u ON u.id = e.user_id '
            'WHERE e.lead_id = ? ORDER BY e.id DESC', (lead_id,),
        ).fetchall()
        return jsonify(shares=[dict(row) for row in shares],
                       events=[dict(row) for row in events])
    finally:
        connection.close()


@bp.route('/api/client-access/<int:lead_id>/level', methods=['POST'])
@bp.route('/api/client-access/<int:lead_id>/grant', methods=['POST'])
@bp.route('/api/client-access/<int:lead_id>/revoke', methods=['POST'])
@permission_required('leads.share_manage')
def change_share(lead_id):
    """Keep share changes and their recorded history atomic."""
    data = request.get_json(silent=True)
    grant = request.path.endswith('/grant')
    modify = request.path.endswith('/level')
    if (not isinstance(data, dict) or 'user_id' not in data
            or set(data) - {'user_id', 'access_level'}
            or type(data['user_id']) is not int
            or not 1 <= data['user_id'] <= 9223372036854775807):
        return jsonify(error='Provide a valid executive user_id.'), 400
    level = data.get('access_level', 'VIEW')
    if (not isinstance(level, str) or level not in ('VIEW', 'EDIT')
            or (modify and 'access_level' not in data)
            or (not grant and not modify and 'access_level' in data)):
        return jsonify(error='Choose VIEW or EDIT access.'), 400
    recipient = data['user_id']
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user = get_current_user()
        if not user:
            return jsonify(error='Not logged in'), 401
        leads = managed_leads(connection, user, lead_id)
        if not leads:
            return jsonify(error='Client not found.'), 404
        target = connection.execute(
            'SELECT role, is_active FROM users WHERE id = ?', (recipient,)
        ).fetchone()
        if not target:
            return jsonify(error='User not found.'), 404
        if (grant or modify) and (
                not target['is_active']
                or target['role'] not in ('user', 'sales_executive')):
            return jsonify(error='Choose an active Sales Executive.'), 400
        if (grant or modify) and recipient == leads[0]['created_by']:
            return jsonify(error='The creator already has access.'), 400
        share = connection.execute(
            'SELECT is_active, access_level FROM client_lead_shares '
            'WHERE lead_id = ? AND user_id = ?', (lead_id, recipient),
        ).fetchone()
        if grant and share and share['is_active']:
            return jsonify(error='Access is already granted.'), 409
        if not grant and (not share or not share['is_active']):
            return jsonify(error='No active share to change or revoke.'), 409
        if modify and share['access_level'] == level:
            return jsonify(error='This access level is already set.'), 409
        previous = (share['access_level']
                    if share and share['is_active'] else None)
        # One row per lead/recipient; event history preserves every cycle.
        if grant or modify:
            connection.execute(
                'INSERT INTO client_lead_shares '
                '(lead_id, user_id, is_active, granted_by, granted_at, '
                'access_level) '
                "VALUES (?, ?, 1, ?, "
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?) "
                'ON CONFLICT(lead_id, user_id) DO UPDATE SET '
                'is_active = 1, granted_by = excluded.granted_by, '
                'granted_at = excluded.granted_at, '
                'access_level = excluded.access_level, '
                'revoked_by = NULL, revoked_at = NULL',
                (lead_id, recipient, user['id'], level),
            )
        else:
            connection.execute(
                'UPDATE client_lead_shares SET is_active = 0, revoked_by = ?, '
                "revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                'WHERE lead_id = ? AND user_id = ?',
                (user['id'], lead_id, recipient),
            )
        connection.execute(
            'INSERT INTO client_share_events '
            '(lead_id, user_id, action, actor_user_id, actor_name, '
            'access_level, previous_access_level) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (lead_id, recipient, 'grant' if grant or modify else 'revoke',
             user['id'], user['username'],
             level if grant or modify else previous, previous),
        )
        connection.commit()
        return jsonify(ok=True)
    finally:
        connection.rollback()
        connection.close()
