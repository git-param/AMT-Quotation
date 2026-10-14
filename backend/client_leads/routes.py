"""Private client lead creation and database-scoped read access."""

from flask import Blueprint, jsonify, request, send_file

from backend.common.auth import (
    authenticated_required, get_current_user, get_permissions,
)
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('client_leads', __name__)


def visibility(user):
    """Return parameterized access predicates shared by list and detail."""
    permissions = get_permissions(user)
    if 'leads.view_all' in permissions:
        return '1 = 1', []
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
    return predicate, parameters


def edit_scope(user):
    """Shares grant read access only; ownership and supervision grant edits."""
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


def read_leads(user, lead_id=None):
    """Apply authorization inside SQL before any records are returned."""
    predicate, parameters = visibility(user)
    editable, edit_parameters = edit_scope(user)
    sql = (
        'SELECT l.*, u.username AS creator_name, (' + editable +
        ') AS can_edit, EXISTS (SELECT 1 FROM client_lead_shares s '
        'WHERE s.lead_id = l.id AND s.user_id = ? AND s.is_active = 1) '
        'AS is_shared FROM client_leads l '
        'JOIN users u ON u.id = l.created_by WHERE (' + predicate + ')'
    )
    if lead_id is not None:
        sql += ' AND l.id = ?'
        parameters.append(lead_id)
    parameters = edit_parameters + [user['id']] + parameters
    sql += ' ORDER BY l.id DESC'
    connection = get_db()
    try:
        return [dict(row) for row in connection.execute(sql, parameters)]
    finally:
        connection.close()


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
    return jsonify(
        leads=read_leads(user), username=user['username'],
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
    return jsonify(lead=leads[0])


@bp.route('/api/leads', methods=['POST'])
@authenticated_required
def create_lead():
    """Assign ownership and timestamp on the server, never from input."""
    try:
        values = validated_details()
    except ValueError as error:
        return jsonify(error=str(error)), 400
    user = get_current_user()
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute(
                'INSERT INTO client_leads '
                '(name, company, email, phone, notes, created_by) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (*values.values(), user['id']),
            )
        return jsonify(lead=read_leads(user, cursor.lastrowid)[0]), 201
    finally:
        connection.close()


def validated_details():
    """Allow only client details; reject ownership and creation metadata."""
    data = request.get_json(silent=True)
    limits = {'name': 150, 'company': 150, 'email': 254,
              'phone': 40, 'notes': 2000}
    if not isinstance(data, dict) or set(data) - set(limits):
        raise ValueError(
            'Invalid fields; ownership is server assigned.'
        )
    values = {}
    for field, limit in limits.items():
        value = data.get(field, '')
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError('Invalid value for ' + field)
        values[field] = value.strip()
    if not values['name']:
        raise ValueError('A client name is required.')
    return values


@bp.route('/api/leads/<int:lead_id>', methods=['PUT'])
@authenticated_required
def update_lead(lead_id):
    """Scope updates to editable leads while preserving ownership."""
    user = get_current_user()
    visible = read_leads(user, lead_id)
    if not visible:
        return jsonify(error='Lead not found.'), 404
    if not visible[0]['can_edit']:
        return jsonify(error='This lead is read-only.'), 403
    try:
        values = validated_details()
    except ValueError as error:
        return jsonify(error=str(error)), 400
    predicate, parameters = edit_scope(user)
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute(
                'UPDATE client_leads AS l SET name = ?, company = ?, '
                'email = ?, phone = ?, notes = ? WHERE l.id = ? '
                'AND EXISTS (SELECT 1 FROM users u WHERE u.id = l.created_by '
                'AND (' + predicate + '))',
                (*values.values(), lead_id, *parameters),
            )
            if not cursor.rowcount:
                return jsonify(
                    error='Edit access is no longer available.'
                ), 403
        return jsonify(lead=read_leads(user, lead_id)[0])
    finally:
        connection.close()
