"""Orders APIs using current client permissions and transactional writes."""

import json
import sqlite3
from uuid import uuid4

from flask import Blueprint, jsonify, request, send_file

from backend.client_leads.discovery import integer
from backend.common.auth import authenticated_required, get_current_user
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.enquiries.lines import serialize, validated as validate_line
from backend.enquiries.routes import editable_client, read_enquiry
from backend.orders.service import (
    STATUSES, copied_line, delivery, details, header, insert_lines,
    order_query, read_order, record_revision, save_delivery, order_line,
)

bp = Blueprint('orders', __name__)


@bp.route('/orders')
@authenticated_required
def order_page():
    """Serve searchable orders and separate create/edit/detail panels."""
    return send_file(str(FRONTEND_DIR / 'orders' / 'orders.html'))


@bp.route('/api/orders')
@authenticated_required
def list_orders():
    """Scope search, filters, sorting, counts and pagination identically."""
    try:
        page = integer(request.args.get('page', '1'), 'page', 1000000)
        size = integer(request.args.get('page_size', '25'), 'page size', 100)
        query, parameters = order_query(get_current_user())
        for key in ('client_id', 'enquiry_id'):
            if request.args.get(key):
                query += ' AND o.' + key + ' = ?'
                parameters.append(integer(request.args[key], key))
        status = request.args.get('status', 'all')
        if status not in ('all', *STATUSES):
            raise ValueError('Invalid order status.')
        if status != 'all':
            query += ' AND o.status = ?'
            parameters.append(status)
        exclude = request.args.get('exclude_drafts', '0')
        if exclude not in ('0', '1'):
            raise ValueError('Invalid draft filter.')
        if exclude == '1':
            query += " AND o.status != 'draft'"
        search = request.args.get('q', '').strip()
        if len(search) > 200:
            raise ValueError('Search is limited to 200 characters.')
        if search:
            pattern = '%' + search.replace('!', '!!').replace(
                '%', '!%').replace('_', '!_') + '%'
            columns = ('o.reference', 'o.po_reference', 'o.pi_reference',
                       'l.name', 'l.company', 'e.reference')
            query += ' AND (' + ' OR '.join(
                column + " LIKE ? ESCAPE '!'" for column in columns) + ')'
            parameters.extend([pattern] * len(columns))
        sorts = {'date': 'o.order_date', 'reference': 'o.reference',
                 'created': 'o.created_at', 'status': 'o.status'}
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
            'SELECT COUNT(*) FROM (' + query + ')', parameters,
        ).fetchone()[0]
        rows = connection.execute(
            query + ' ORDER BY ' + sorts[sort] + ' ' + direction
            + ', o.id ' + direction + ' LIMIT ? OFFSET ?',
            [*parameters, size, (page - 1) * size],
        ).fetchall()
        return jsonify(orders=[dict(row) for row in rows], total=total,
                       page=page, pages=(total + size - 1) // size)
    finally:
        connection.close()


@bp.route('/api/orders/<int:order_id>')
@authenticated_required
def order_detail(order_id):
    """Read current snapshots and retained history only within client scope."""
    connection = get_db()
    try:
        connection.execute('BEGIN')
        order = read_order(connection, get_current_user(), order_id)
        if not order:
            return jsonify(error='Order not found.'), 404
        result = details(connection, order)
        result['revisions'] = [dict(row, snapshot=json.loads(
            row['snapshot_json'])) for row in connection.execute(
                'SELECT id, action, actor_user_id, created_at, snapshot_json '
                'FROM order_revisions WHERE order_id = ? ORDER BY id DESC',
                (order_id,),
            )]
        for revision in result['revisions']:
            revision.pop('snapshot_json')
        return jsonify(result)
    finally:
        connection.close()


@bp.route('/api/orders', methods=['POST'])
@bp.route('/api/orders/<int:order_id>', methods=['PUT'])
@authenticated_required
def save_order(order_id=None):
    """Create copies atomically or edit details without reparenting."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user = get_current_user()
        if not user:
            return jsonify(error='Not logged in'), 401
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Provide a JSON object.')
        old = read_order(connection, user, order_id) if order_id else None
        if order_id and not old:
            return jsonify(error='Order not found.'), 404
        if old and not old['can_edit']:
            return jsonify(error='Client access is read-only.'), 403
        if old:
            values = header({key: value for key, value in data.items()
                             if key != 'delivery'}, old)
            client_id = old['client_id']
        else:
            enquiry_id = data.get('enquiry_id')
            if enquiry_id is not None:
                if type(enquiry_id) is not int:
                    raise ValueError('A valid enquiry_id is required.')
                integer(enquiry_id, 'enquiry ID')
                enquiry = read_enquiry(connection, user, enquiry_id)
                if not enquiry:
                    return jsonify(error='Enquiry not found.'), 404
                if not enquiry['can_edit']:
                    return jsonify(error='Client access is read-only.'), 403
                client_id = enquiry['client_id']
                if 'client_id' in data and data['client_id'] != client_id:
                    raise ValueError('Enquiry does not belong to this client.')
            else:
                client_id = data.get('client_id')
                if type(client_id) is not int:
                    raise ValueError('A valid client_id is required.')
                integer(client_id, 'client ID')
            client = editable_client(connection, user, client_id)
            if not client:
                return jsonify(error='Client not found.'), 404
            if not client['can_edit']:
                return jsonify(error='Client access is read-only.'), 403
            if not client['is_active']:
                raise ValueError('Reactivate the client to create orders.')
            values = header({key: value for key, value in data.items()
                             if key not in ('client_id', 'enquiry_id', 'delivery', 'lines',
                                            'source_line_ids')})
        client = connection.execute(
            'SELECT * FROM client_leads WHERE id = ?', (client_id,),
        ).fetchone()
        previous = details(connection, old)['delivery'] if old else None
        destination = None
        if not old or 'delivery' in data:
            destination = delivery(connection, client, data.get('delivery', {}),
                                   previous, values['status'] == 'draft' and
                                   (enquiry_id is None if not old else old['enquiry_id'] is None))
        if old:
            assignments = ', '.join(key + ' = ?' for key in values)
            connection.execute(
                'UPDATE client_orders SET ' + assignments
                + ', updated_by = ?, '
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                'WHERE id = ?',
                [*values.values(), user['id'], order_id],
            )
        else:
            ids = data.get('source_line_ids', [])
            items = data.get('lines', [])
            if (not isinstance(ids, list) or not isinstance(items, list)
                    or len(ids) + len(items) > 50
                    or any(type(item) is not int for item in ids)
                    or len(ids) != len(set(ids))):
                raise ValueError('Choose up to 50 unique source lines/items.')
            lines = [copied_line(connection, user, enquiry_id, item)
                     for item in ids] + [order_line(item) for item in items]
            columns = ', '.join(values)
            marks = ', '.join('?' for _ in values)
            cursor = connection.execute(
                'INSERT INTO client_orders (' + columns
                + ', reference, client_id, enquiry_id, created_by, '
                'updated_by) '
                'VALUES (' + marks + ', ?, ?, ?, ?, ?)',
                [*values.values(), 'NEW-' + uuid4().hex, client_id, enquiry_id,
                 user['id'], user['id']],
            )
            order_id = cursor.lastrowid
            connection.execute(
                'UPDATE client_orders SET reference = ? WHERE id = ?',
                (f'ORD-{order_id:06d}', order_id),
            )
            if lines or enquiry_id is not None or values['status'] != 'draft':
                insert_lines(connection, order_id, lines, user['id'])
        if destination:
            save_delivery(connection, order_id, destination, user['id'])
        record_revision(connection, order_id, user,
                        'edit' if old else 'create')
        result = details(connection, read_order(connection, user, order_id))
        connection.commit()
        return jsonify(result), 200 if old else 201
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error='Conflicting order or source line.'), 409
    finally:
        connection.rollback()
        connection.close()


@bp.route('/api/orders/<int:order_id>/lines')
@bp.route('/api/orders/<int:order_id>/lines/<int:line_id>')
@bp.route('/api/orders/<int:order_id>/lines', methods=['POST'])
@bp.route('/api/orders/<int:order_id>/lines/bulk', methods=['POST'])
@bp.route('/api/orders/<int:order_id>/lines/<int:line_id>',
          methods=['PUT', 'DELETE'])
@authenticated_required
def order_lines(order_id, line_id=None):
    """Manage independent SKU lines; removal retains state and revisions."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE' if request.method != 'GET'
                           else 'BEGIN')
        user = get_current_user()
        if not user:
            return jsonify(error='Not logged in'), 401
        order = read_order(connection, user, order_id)
        if not order:
            return jsonify(error='Order not found.'), 404
        row = None
        if line_id is not None:
            row = connection.execute(
                'SELECT * FROM order_sku_lines WHERE id = ? AND order_id = ?',
                (line_id, order_id),
            ).fetchone()
            if not row:
                return jsonify(error='Order line not found.'), 404
        if request.method == 'GET':
            return jsonify(line=serialize(row)) if row else jsonify(
                details(connection, order))
        if not order['can_edit']:
            return jsonify(error='Client access is read-only.'), 403
        if row and not row['is_active']:
            return jsonify(error='Active order line not found.'), 404
        data = request.get_json(silent=True)
        if request.method == 'DELETE':
            if not order['can_delete']:
                return jsonify(error='SKU deletion is not permitted.'), 403
            connection.execute(
                'UPDATE order_sku_lines SET is_active = 0, updated_by = ?, '
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                'WHERE id = ?',
                (user['id'], line_id),
            )
            action = 'line_remove'
        elif request.method == 'PUT':
            values = order_line(data, row)
            connection.execute(
                'UPDATE order_sku_lines SET '
                + ', '.join(key + ' = ?' for key in values)
                + ', updated_by = ?, '
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                'WHERE id = ?',
                [*values.values(), user['id'], line_id],
            )
            action = 'line_edit'
        else:
            if request.path.endswith('/bulk'):
                if (not isinstance(data, dict) or set(data) != {'lines'}
                        or not isinstance(data['lines'], list)
                        or not 1 <= len(data['lines']) <= 50):
                    raise ValueError('Provide 1 to 50 complete SKU lines.')
                values = [order_line(item) for item in data['lines']]
            elif isinstance(data, dict) and set(data) == {'source_line_id'}:
                values = [copied_line(connection, user, order['enquiry_id'],
                                      data['source_line_id'])]
            else:
                values = [order_line(data)]
            insert_lines(connection, order_id, values, user['id'])
            action = 'line_create'
        connection.execute(
            'UPDATE client_orders SET updated_by = ?, '
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (user['id'], order_id),
        )
        record_revision(connection, order_id, user, action)
        result = details(connection, read_order(connection, user, order_id))
        connection.commit()
        return jsonify(result), 201 if action == 'line_create' else 200
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error='This source line is already on the order.'), 409
    finally:
        connection.rollback()
        connection.close()


# Imported after blueprint and routes are defined to avoid a circular dependency.
from backend.orders import invoices  # noqa: E402,F401
