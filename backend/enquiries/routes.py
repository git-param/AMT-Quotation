"""Client-scoped enquiries; all access derives from existing client grants."""

from datetime import date
import re
import sqlite3

from flask import Blueprint, jsonify, request, send_file

from backend.client_leads.discovery import integer
from backend.client_leads.routes import edit_scope, visibility
from backend.common.auth import authenticated_required, get_current_user
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('enquiries', __name__)
STATUSES = ('open', 'in_progress', 'closed', 'cancelled')


def enquiry_query(user):
    """Use the same client visibility for detail, list and counts."""
    scope, parameters = visibility(user)
    edit, edit_parameters = edit_scope(user)
    sql = (
        'SELECT e.*, l.name AS client_name, l.company AS client_company, '
        'l.is_active AS client_active, ec.username AS creator_name, '
        'eu.username AS updated_by_name, (' + edit + ') AS can_edit '
        'FROM client_enquiries e JOIN client_leads l ON l.id = e.client_id '
        'JOIN users u ON u.id = l.created_by '
        'JOIN users ec ON ec.id = e.created_by '
        'JOIN users eu ON eu.id = e.updated_by WHERE (' + scope + ')'
    )
    return sql, edit_parameters + parameters


def read_enquiry(connection, user, enquiry_id):
    """Never return an enquiry belonging to an inaccessible client."""
    sql, parameters = enquiry_query(user)
    return connection.execute(sql + ' AND e.id = ?',
                              [*parameters, enquiry_id]).fetchone()


def editable_client(connection, user, client_id):
    """Check the original client scope inside the write transaction."""
    scope, parameters = visibility(user)
    edit, edit_parameters = edit_scope(user)
    row = connection.execute(
        'SELECT l.id, l.is_active, (' + edit + ') AS can_edit '
        'FROM client_leads l JOIN users u ON u.id = l.created_by '
        'WHERE (' + scope + ') AND l.id = ?',
        [*edit_parameters, *parameters, client_id],
    ).fetchone()
    return row


def validated(data, existing=None):
    """Validate details and reject client reassignment or metadata input."""
    fields = {'reference', 'enquiry_date', 'subject', 'description',
              'status', 'deal_currency'}
    allowed = fields if existing else fields | {'client_id'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError(
            'Invalid fields; client and creator cannot be changed.'
        )
    result = {}
    existing = dict(existing) if existing else {}
    for key, limit in (('reference', 80), ('subject', 200),
                       ('description', 5000), ('enquiry_date', 10),
                       ('status', 20)):
        default = 'open' if key == 'status' else ''
        value = data.get(key, existing.get(key, default))
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError('Invalid ' + key)
        result[key] = value.strip()
    if not result['reference'] or not result['subject']:
        raise ValueError('Reference and subject are required.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 /_.-]{0,79}',
                        result['reference']):
        raise ValueError('Use letters, numbers, spaces or /_.- in references.')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', result['enquiry_date']):
        raise ValueError('Enquiry date must use YYYY-MM-DD.')
    try:
        date.fromisoformat(result['enquiry_date'])
    except ValueError as error:
        raise ValueError('Enter a valid enquiry date.') from error
    if result['status'] not in STATUSES:
        raise ValueError('Choose a valid enquiry status.')
    currency = data.get('deal_currency', existing.get('deal_currency'))
    if (currency not in ('USD', 'INR')
            and (not existing or currency is not None)):
        raise ValueError('Choose USD or INR deal currency.')
    result['deal_currency'] = currency
    return result


@bp.route('/enquiries')
@authenticated_required
def enquiry_page():
    """Serve searchable enquiries and create/edit/detail views."""
    return send_file(str(FRONTEND_DIR / 'enquiries' / 'enquiries.html'))


@bp.route('/api/enquiries')
@authenticated_required
def list_enquiries():
    """Scope search, filters, pagination and counts to client visibility."""
    user = get_current_user()
    try:
        page = integer(request.args.get('page', '1'), 'page', 1000000)
        size = integer(request.args.get('page_size', '25'), 'page size', 100)
        sql, parameters = enquiry_query(user)
        if request.args.get('client_id'):
            sql += ' AND e.client_id = ?'
            parameters.append(integer(request.args['client_id'], 'client ID'))
        if request.args.get('creator'):
            sql += ' AND e.created_by = ?'
            parameters.append(integer(request.args['creator'], 'creator'))
        status = request.args.get('status', 'all')
        if status not in ('all', *STATUSES):
            raise ValueError('Invalid status filter.')
        if status != 'all':
            sql += ' AND e.status = ?'
            parameters.append(status)
        search = request.args.get('q', '').strip()
        if len(search) > 200:
            raise ValueError('Search is limited to 200 characters.')
        if search:
            escaped = search.replace('!', '!!').replace('%', '!%')
            pattern = '%' + escaped.replace('_', '!_') + '%'
            columns = ('e.reference', 'e.subject', 'e.description',
                       'l.name', 'l.company')
            sql += ' AND (' + ' OR '.join(
                column + " LIKE ? ESCAPE '!'" for column in columns) + ')'
            parameters.extend([pattern] * len(columns))
        sorts = {'date': 'e.enquiry_date', 'created': 'e.created_at',
                 'reference': 'e.reference', 'status': 'e.status'}
        sort = request.args.get('sort', 'date')
        direction = request.args.get('direction', 'desc')
        if sort not in sorts or direction not in ('asc', 'desc'):
            raise ValueError('Invalid sorting option.')
    except ValueError as error:
        return jsonify(error=str(error)), 400
    connection = get_db()
    try:
        connection.execute('BEGIN')
        total = connection.execute(
            'SELECT COUNT(*) FROM (' + sql + ')', parameters
        ).fetchone()[0]
        rows = connection.execute(
            sql + ' ORDER BY ' + sorts[sort] + ' ' + direction
            + ', e.id ' + direction + ' LIMIT ? OFFSET ?',
            [*parameters, size, (page - 1) * size],
        ).fetchall()
        return jsonify(enquiries=[dict(row) for row in rows], total=total,
                       page=page, pages=(total + size - 1) // size)
    finally:
        connection.close()


@bp.route('/api/enquiries/<int:enquiry_id>')
@authenticated_required
def enquiry_detail(enquiry_id):
    """Use the same missing response for unknown and unauthorized records."""
    connection = get_db()
    try:
        enquiry = read_enquiry(connection, get_current_user(), enquiry_id)
        if not enquiry:
            return jsonify(error='Enquiry not found.'), 404
        return jsonify(enquiry=dict(enquiry))
    finally:
        connection.close()


@bp.route('/api/enquiries', methods=['POST'])
@bp.route('/api/enquiries/<int:enquiry_id>', methods=['PUT'])
@authenticated_required
def save_enquiry(enquiry_id=None):
    """Write atomically while retaining the creator and client link."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user = get_current_user()
        if not user:
            return jsonify(error='Not logged in'), 401
        data = request.get_json(silent=True)
        existing = None
        if enquiry_id is not None:
            existing = read_enquiry(connection, user, enquiry_id)
            if not existing:
                return jsonify(error='Enquiry not found.'), 404
            if not existing['can_edit']:
                return jsonify(error='Client access is read-only.'), 403
            client_id = existing['client_id']
        else:
            if (not isinstance(data, dict)
                    or type(data.get('client_id')) is not int):
                return jsonify(error='A valid client_id is required.'), 400
            client_id = integer(data['client_id'], 'client ID')
        client = editable_client(connection, user, client_id)
        if not client:
            return jsonify(error='Client not found.'), 404
        if not client['can_edit']:
            return jsonify(error='Client access is read-only.'), 403
        if existing is None and not client['is_active']:
            return jsonify(
                error='Reactivate the client to create enquiries.'
            ), 400
        from backend.enquiries.lines import create_lines
        from backend.enquiries.lines import validated as line_data

        if not isinstance(data, dict):
            raise ValueError('Provide a JSON object.')
        header = {key: value for key, value in data.items() if key != 'lines'}
        values = validated(header, existing)
        lines = data.get('lines')
        if existing is None:
            if not isinstance(lines, list) or not 1 <= len(lines) <= 50:
                raise ValueError('At least one complete SKU line is required.')
            lines = [line_data(item) for item in lines]
            if any(item['currency'] != values['deal_currency']
                   for item in lines):
                raise ValueError(
                    'Initial lines must use the chosen deal currency.'
                )
        elif lines is not None:
            raise ValueError('Edit saved lines in the enquiry SKU section.')
        if existing is None:
            columns = ', '.join(values)
            marks = ', '.join('?' for _ in values)
            cursor = connection.execute(
                'INSERT INTO client_enquiries (' + columns
                + ', client_id, created_by, updated_by) VALUES (' + marks
                + ', ?, ?, ?)',
                [*values.values(), client_id, user['id'], user['id']],
            )
            enquiry_id = cursor.lastrowid
            create_lines(connection, enquiry_id, lines, user['id'])
            status = 201
        else:
            assignments = ', '.join(key + ' = ?' for key in values)
            connection.execute(
                'UPDATE client_enquiries SET ' + assignments
                + ', updated_by = ?, '
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                'WHERE id = ?',
                [*values.values(), user['id'], enquiry_id],
            )
            status = 200
        result = dict(read_enquiry(connection, user, enquiry_id))
        connection.commit()
        return jsonify(enquiry=result), status
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error='Enquiry reference already exists.'), 409
    finally:
        connection.rollback()
        connection.close()
