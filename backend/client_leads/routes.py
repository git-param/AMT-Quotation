"""Private client lead creation and database-scoped read access."""

import json

from flask import Blueprint, jsonify, request, send_file

from backend.common.auth import (
    authenticated_required, get_current_user, get_permissions,
)
from backend.client_leads.details import (
    decode, duplicate_exists, record_addresses, validate_source,
    validated_details,
)
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('client_leads', __name__)


def visibility(user):
    """Return parameterized access predicates shared by list and detail."""
    permissions = get_permissions(user)
    if 'leads.view_all' in permissions:
        return 'l.deleted_at IS NULL', []
    predicate = (
        'l.created_by = ? OR EXISTS (SELECT 1 FROM client_lead_shares s '
        'WHERE s.lead_id = l.id AND s.user_id = ? AND s.is_active = 1)'
    )
    parameters = [user['id'], user['id']]
    if 'leads.view_team' in permissions:
        predicate += (
            " OR (u.supervisor_user_id = ? AND u.is_active = 1 "
            "AND u.role IN ('user', 'sales_executive'))"
        )
        parameters.append(user['id'])
    return '(' + predicate + ') AND l.deleted_at IS NULL', parameters


def delete_scope(user):
    """Restrict deletion to management roles and independent client scope."""
    if user['role'] not in ('admin', 'manager', 'sales_tl'):
        return '0 = 1', []
    return management_edit_scope(user)


def management_edit_scope(user):
    """Authorize management by ownership and supervision, not shared access."""
    if user['role'] in ('admin', 'manager'):
        return '1 = 1', []
    predicate = 'l.created_by = ?'
    parameters = [user['id']]
    if (user['role'] == 'sales_tl'
            and 'leads.view_team' in get_permissions(user)):
        predicate += (
            " OR (u.supervisor_user_id = ? AND u.is_active = 1 "
            "AND u.role IN ('user', 'sales_executive'))"
        )
        parameters.append(user['id'])
    return predicate, parameters


def edit_scope(user):
    """Allow independent editing or an active EDIT share, never resharing."""
    predicate, parameters = management_edit_scope(user)
    predicate += (
        ' OR EXISTS (SELECT 1 FROM client_lead_shares s '
        'WHERE s.lead_id = l.id AND s.user_id = ? AND s.is_active = 1 '
        "AND s.access_level = 'EDIT')"
    )
    return predicate, parameters + [user['id']]


def lead_query(user):
    """Build the common scoped projection for detail, discovery and counts."""
    predicate, parameters = visibility(user)
    editable, edit_parameters = edit_scope(user)
    sql = (
        'SELECT l.*, u.username AS creator_name, (' + editable +
        ') AS can_edit, (' + management_edit_scope(user)[0] +
        ') AS can_manage_client, (' + delete_scope(user)[0] +
        ') AS can_delete, EXISTS (SELECT 1 FROM client_lead_shares s '
        'WHERE s.lead_id = l.id AND s.user_id = ? AND s.is_active = 1) '
        'AS is_shared, (SELECT s.access_level FROM client_lead_shares s '
        'WHERE s.lead_id = l.id AND s.user_id = ? AND s.is_active = 1) '
        'AS shared_access_level, src.name AS enquiry_source_name, '
        'src.is_active AS enquiry_source_active, '
        '(SELECT COUNT(*) FROM client_enquiries e WHERE e.client_id = l.id '
        'AND e.deleted_at IS NULL) '
        'AS enquiry_count, (SELECT COUNT(*) FROM client_orders o WHERE o.client_id = l.id AND o.deleted_at IS NULL) '
        'AS order_count, (SELECT COUNT(*) FROM client_orders o WHERE o.client_id = l.id '
        "AND o.status = 'draft' AND o.deleted_at IS NULL) AS pending_order_count FROM client_leads l "
        'JOIN users u ON u.id = l.created_by '
        'LEFT JOIN enquiry_sources src ON src.id = l.enquiry_source_id '
        'WHERE (' + predicate + ')'
    )
    parameters = (edit_parameters + management_edit_scope(user)[1]
                  + delete_scope(user)[1]
                  + [user['id'], user['id']] + parameters)
    return sql, parameters


def read_leads(user, lead_id=None):
    """Apply authorization inside SQL before any records are returned."""
    sql, parameters = lead_query(user)
    if lead_id is not None:
        sql += ' AND l.id = ?'
        parameters.append(lead_id)
    sql += ' ORDER BY l.id DESC'
    connection = get_db()
    try:
        return [decode(row) for row in connection.execute(sql, parameters)]
    finally:
        connection.close()


@bp.route('/clients-orders')
@bp.route('/leads')
@authenticated_required
def lead_page():
    """Serve the list/create screen for active authenticated users."""
    return send_file(str(FRONTEND_DIR / 'client_leads' / 'leads.html'))


@bp.route('/api/leads')
@authenticated_required
def list_leads():
    """Return authorized leads without accepting ownership query overrides."""
    user = get_current_user()
    from backend.client_leads.discovery import discover

    try:
        results = discover(user, request.args)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(
        **results, username=user['username'],
        can_manage_sharing=(user['role'] in ('admin', 'manager', 'sales_tl')
                            and 'leads.share_manage' in get_permissions(user)),
    )


@bp.route('/api/leads/<int:lead_id>')
@authenticated_required
def lead_detail(lead_id):
    """Do not disclose whether an inaccessible lead exists."""
    leads = read_leads(get_current_user(), lead_id)
    if not leads:
        return jsonify(error='Lead not found.'), 404
    connection = get_db()
    try:
        history = connection.execute(
            'SELECT h.*, u.username AS actor_name '
            'FROM client_address_history h '
            'LEFT JOIN users u ON u.id = h.recorded_by '
            'WHERE client_id = ? ORDER BY h.id DESC', (lead_id,),
        ).fetchall()
        snapshots = []
        for row in history:
            item = dict(row)
            item['billing_address'] = json.loads(
                item.pop('billing_address_json'))
            item['default_shipping_address'] = json.loads(
                item.pop('shipping_address_json'))
            snapshots.append(item)
        return jsonify(lead=leads[0], address_history=snapshots)
    finally:
        connection.close()


@bp.route('/api/leads', methods=['POST'])
@authenticated_required
def create_lead():
    """Assign ownership and timestamp on the server, never from input."""
    try:
        values = validated_details(request.get_json(silent=True))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    user = get_current_user()
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        try:
            validate_source(connection, values['enquiry_source_id'])
        except ValueError as error:
            return jsonify(error=str(error)), 400
        if duplicate_exists(connection, values, user['id']):
            return jsonify(
                error='A matching client exists in this ownership.'
            ), 409
        columns = ', '.join(values)
        placeholders = ', '.join('?' for _ in values)
        cursor = connection.execute(
            'INSERT INTO client_leads (' + columns + ', created_by) '
            'VALUES (' + placeholders + ', ?)',
            (*values.values(), user['id']),
        )
        record_addresses(connection, cursor.lastrowid, values, user['id'])
        connection.commit()
        return jsonify(lead=read_leads(user, cursor.lastrowid)[0]), 201
    finally:
        connection.rollback()
        connection.close()


@bp.route('/api/leads/<int:lead_id>', methods=['PUT'])
@authenticated_required
def update_lead(lead_id):
    """Scope updates to editable leads while preserving ownership."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user = get_current_user()
        if not user:
            return jsonify(error='Not logged in'), 401
        visible = read_leads(user, lead_id)
        if not visible:
            return jsonify(error='Lead not found.'), 404
        if not visible[0]['can_edit']:
            return jsonify(error='This lead is read-only.'), 403
        try:
            values = validated_details(
                request.get_json(silent=True), visible[0]
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400
        try:
            validate_source(connection, values['enquiry_source_id'],
                            visible[0]['enquiry_source_id'])
        except ValueError as error:
            return jsonify(error=str(error)), 400
        if duplicate_exists(
                connection, values, visible[0]['created_by'], lead_id):
            return jsonify(
                error='A matching client exists in this ownership.'
            ), 409
        predicate, parameters = edit_scope(user)
        assignments = ', '.join(field + ' = ?' for field in values)
        cursor = connection.execute(
            'UPDATE client_leads AS l SET ' + assignments + ' WHERE l.id = ? '
            'AND EXISTS (SELECT 1 FROM users u WHERE u.id = l.created_by '
            'AND (' + predicate + '))',
            (*values.values(), lead_id, *parameters),
        )
        if not cursor.rowcount:
            return jsonify(error='Edit access is no longer available.'), 403
        if any(json.loads(values[field + '_json']) != visible[0][field]
               for field in ('billing_address', 'shipping_address')):
            record_addresses(connection, lead_id, values, user['id'])
        connection.commit()
        return jsonify(lead=read_leads(user, lead_id)[0])
    finally:
        connection.rollback()
        connection.close()


@bp.route('/api/leads/<int:lead_id>/deactivate', methods=['POST'])
@bp.route('/api/leads/<int:lead_id>/activate', methods=['POST'])
@authenticated_required
def set_client_active(lead_id):
    """Keep related records; lifecycle changes require management rights."""
    user = get_current_user()
    leads = read_leads(user, lead_id)
    if not leads:
        return jsonify(error='Lead not found.'), 404
    if not leads[0]['can_manage_client']:
        return jsonify(
            error='Client lifecycle management is not permitted.'
        ), 403
    predicate, parameters = management_edit_scope(user)
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute(
                'UPDATE client_leads AS l SET is_active = ? WHERE l.id = ? '
                'AND l.deleted_at IS NULL '
                'AND EXISTS (SELECT 1 FROM users u WHERE u.id = l.created_by '
                'AND (' + predicate + '))',
                (int(request.path.endswith('/activate')),
                 lead_id, *parameters),
            )
            if not cursor.rowcount:
                return jsonify(
                    error='Management access is no longer valid.'
                ), 403
        return jsonify(lead=read_leads(user, lead_id)[0])
    finally:
        connection.close()


@bp.route('/api/leads/<int:lead_id>', methods=['DELETE'])
@authenticated_required
def delete_lead(lead_id):
    """Hide a client and its descendants, retaining every historical row."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user = get_current_user()
        if not user:
            return jsonify(error='Not logged in'), 401
        scope, parameters = visibility(user)
        permitted, delete_parameters = delete_scope(user)
        lead = connection.execute(
            'SELECT l.id, (' + permitted + ') AS can_delete '
            'FROM client_leads l JOIN users u ON u.id = l.created_by '
            'WHERE (' + scope + ') AND l.id = ?',
            [*delete_parameters, *parameters, lead_id],
        ).fetchone()
        if not lead:
            return jsonify(error='Lead not found.'), 404
        if not lead['can_delete']:
            return jsonify(error='Client deletion is not permitted.'), 403
        connection.execute(
            'UPDATE client_leads SET is_active = 0, deleted_by = ?, '
            "deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            'WHERE id = ?', (user['id'], lead_id),
        )
        connection.commit()
        return jsonify(message='Client deleted; history retained.')
    finally:
        connection.rollback()
        connection.close()


@bp.route('/api/leads/options')
@authenticated_required
def client_options():
    """Expose source choices without providing source management authority."""
    from backend.client_leads.discovery import options

    return jsonify(**options(get_current_user()))
