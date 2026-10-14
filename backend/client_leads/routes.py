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
        'WHERE s.lead_id = l.id AND s.user_id = ?)'
    )
    parameters = [user['id'], user['id']]
    if 'leads.view_team' in permissions:
        predicate += (
            " OR (u.supervisor_user_id = ? AND u.is_active = 1 "
            "AND u.role IN ('user', 'sales_executive'))"
        )
        parameters.append(user['id'])
    return predicate, parameters


def read_leads(user, lead_id=None):
    """Apply authorization inside SQL before any records are returned."""
    predicate, parameters = visibility(user)
    sql = (
        'SELECT l.*, u.username AS creator_name FROM client_leads l '
        'JOIN users u ON u.id = l.created_by WHERE (' + predicate + ')'
    )
    if lead_id is not None:
        sql += ' AND l.id = ?'
        parameters.append(lead_id)
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
    return jsonify(leads=read_leads(user), username=user['username'])


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
    data = request.get_json(silent=True)
    limits = {'name': 150, 'company': 150, 'email': 254,
              'phone': 40, 'notes': 2000}
    if not isinstance(data, dict) or set(data) - set(limits):
        return jsonify(
            error='Invalid fields; ownership is server assigned.'
        ), 400
    values = {}
    for field, limit in limits.items():
        value = data.get(field, '')
        if not isinstance(value, str) or len(value.strip()) > limit:
            return jsonify(error='Invalid value for ' + field), 400
        values[field] = value.strip()
    if not values['name']:
        return jsonify(error='A client name is required.'), 400
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
