"""Order validation, client-scoped queries and immutable delivery snapshots."""

from datetime import date
from decimal import Decimal
import json
import re

from backend.client_leads.details import address, email, phone, text
from backend.client_leads.routes import delete_scope, edit_scope, visibility
from backend.enquiries.lines import number, serialize, validated as validate_line
from backend.enquiries.routes import read_enquiry
from backend.orders.parties import TEXT_FIELDS, text_delivery

STATUSES = ('draft', 'confirmed', 'processing', 'dispatched', 'completed',
            'cancelled')
FIELDS = {'order_date': 10, 'pi_date': 10, 'po_reference': 100,
          'pi_reference': 100, 'payment_terms': 2000, 'delivery_terms': 500,
          'delivery_time': 200, 'dispatch_method': 200, 'notes': 5000,
          'status': 20, 'currency': 3, 'destination': 200,
          'shipping_charges': 30}


def pi_line_requirements(lines):
    """Expose missing commercial fields before the user attempts PI issuance."""
    return [{'id': line['id'], 'sku': line['sku'],
             'fields': [key for key in ('hsn_code', 'item_condition') if not line.get(key)]}
            for line in lines if not line.get('hsn_code') or not line.get('item_condition')]


def order_line(data, existing=None):
    """Extend established decimal line validation with commercial fields."""
    extra = {'hsn_code': 20, 'item_condition': 100, 'uom': 30}
    if not isinstance(data, dict):
        raise ValueError('Provide a SKU line object.')
    values = validate_line({k: v for k, v in data.items() if k not in extra}, existing)
    old = dict(existing) if existing else {}
    for key, limit in extra.items():
        values[key] = text(data.get(key, old.get(key, 'PCs' if key == 'uom' else '')),
                           limit, key)
    if not values['uom']:
        raise ValueError('Unit of measure is required.')
    return values


def order_query(user):
    """Use original client ownership and current grants for every order."""
    scope, parameters = visibility(user)
    edit, edit_parameters = edit_scope(user)
    deletion, delete_parameters = delete_scope(user)
    query = (
        'SELECT o.*, l.name AS client_name, l.company AS client_company, '
        'e.reference AS enquiry_reference, '
        'e.deleted_at AS enquiry_deleted_at, '
        'u.username AS owner_name, oc.username AS creator_name, '
        '(' + edit + ') AS can_edit, (' + deletion + ') AS can_delete '
        'FROM client_orders o JOIN client_leads l ON l.id = o.client_id '
        'JOIN users u ON u.id = l.created_by '
        'JOIN users oc ON oc.id = o.created_by '
        'LEFT JOIN client_enquiries e ON e.id = o.enquiry_id WHERE (' + scope + ')'
    )
    return query, edit_parameters + delete_parameters + parameters


def read_order(connection, user, order_id):
    """Unknown and inaccessible orders share the same missing result."""
    query, parameters = order_query(user)
    return connection.execute(query + ' AND o.id = ?',
                              [*parameters, order_id]).fetchone()


def header(data, existing=None):
    """Validate editable fields; parent links and reference are fixed."""
    if not isinstance(data, dict) or set(data) - set(FIELDS):
        raise ValueError('Invalid fields; ownership and links are immutable.')
    old = dict(existing) if existing else {}
    values = {key: text(data.get(key, old.get(key, '')), limit, key)
              for key, limit in FIELDS.items() if key != 'shipping_charges'}
    values['shipping_minor'] = number(data.get('shipping_charges', format(
        Decimal(old.get('shipping_minor', 0)) / 100, '.2f')), 2,
        Decimal('999999999.99'))
    values['status'] = values['status'] or 'draft'
    if values['status'] not in STATUSES:
        raise ValueError('Choose a valid order status.')
    if values['currency'] not in ('USD', 'INR'):
        raise ValueError('Choose USD or INR currency.')
    for key in ('order_date', 'pi_date'):
        if not values[key] and key == 'pi_date':
            continue
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', values[key]):
            raise ValueError(key + ' must use YYYY-MM-DD.')
        try:
            date.fromisoformat(values[key])
        except ValueError as error:
            raise ValueError('Enter a valid ' + key) from error
    return values


def party(value, required=False):
    """Reuse CRM contact validators for separate order-only parties."""
    fields = {'name', 'email', 'phone', 'pic', 'gst_number', 'address'}
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError('Invalid party details.')
    result = {key: text(value.get(key, ''), 200, key) for key in fields - {'address'}}
    if 'address' in value:
        result['address'] = address(value['address'])
    result['email'] = email(value.get('email', ''))
    result['phone'] = phone(value.get('phone', ''))
    if (required or any(result.values())) and not result['name']:
        raise ValueError('A legal party name is required.')
    return result


def delivery(connection, client, data, old=None, draft=False, destination=''):
    """Copy a selected saved address or accept a private order address."""
    fields = {'billing_address', 'shipping_address', 'consignee', 'buyer',
              'notify_party', 'instructions', 'saved_address_id',
              'saved_address_kind', *TEXT_FIELDS}
    if not isinstance(data, dict) or set(data) - fields:
        raise ValueError('Invalid delivery fields.')
    old = old or {}
    if any(key in data for key in TEXT_FIELDS) or (
            any(key in old for key in TEXT_FIELDS)
            and not set(data) - {'instructions'}):
        if set(data) - {*TEXT_FIELDS, 'instructions'}:
            raise ValueError('Use party text blocks or structured delivery fields, not both.')
        return text_delivery(data, old, destination, draft)
    saved_id = data.get('saved_address_id', old.get('saved_address_id'))
    kind = data.get('saved_address_kind', old.get('saved_address_kind'))
    if 'shipping_address' in data:
        if data.get('saved_address_id') is not None:
            raise ValueError('Choose a saved address or a custom address.')
        saved_id, kind = None, None
    if saved_id is not None:
        if (type(saved_id) is not int
                or not 1 <= saved_id <= 9223372036854775807
                or kind not in ('billing', 'shipping')):
            raise ValueError('Choose a valid saved address version.')
        saved = connection.execute(
            'SELECT * FROM client_address_history WHERE id = ? '
            'AND client_id = ?', (saved_id, client['id']),
        ).fetchone()
        if not saved:
            raise ValueError('Saved address does not belong to this client.')
        shipping = json.loads(saved[kind + '_address_json'])
    else:
        if kind is not None:
            raise ValueError('Address kind requires a saved address version.')
        shipping = data.get('shipping_address',
                            old.get('shipping_address', {}))
    result = {
        'shipping_address': address(shipping),
        'billing_address': address(data.get('billing_address', old.get(
            'billing_address', json.loads(client['billing_address_json'])))),
        'instructions': text(data.get('instructions', old.get(
            'instructions', '')), 2000, 'delivery instructions'),
    }
    if not result['shipping_address'] and not draft:
        raise ValueError('Shipping address requires street and country.')
    for key in ('consignee', 'buyer', 'notify_party'):
        result[key] = party(data.get(key, old.get(key, {})),
                            key == 'consignee' and not draft)
    return result, saved_id, kind


def save_delivery(connection, order_id, values, actor):
    """Append a delivery version; never update client defaults/history."""
    snapshot, saved_id, kind = values
    connection.execute(
        'INSERT INTO order_delivery_versions '
        '(order_id, snapshot_json, saved_address_id, saved_address_kind, '
        'recorded_by) VALUES (?, ?, ?, ?, ?)',
        (order_id, json.dumps(snapshot), saved_id, kind, actor),
    )


def delivery_version(row):
    """Decode provenance together with the immutable address snapshot."""
    result = dict(row)
    result.update(json.loads(result.pop('snapshot_json')))
    return result


def details(connection, order):
    """Calculate totals and return independent line and delivery versions."""
    lines = []
    totals = {}
    for row in connection.execute(
            'SELECT * FROM order_sku_lines WHERE order_id = ? '
            'AND is_active = 1 ORDER BY id', (order['id'],)):
        line = serialize(row)
        source = line.pop('source_snapshot_json')
        line['source_snapshot'] = json.loads(source) if source else None
        lines.append(line)
        code = line['currency']
        totals[code] = (totals.get(code, Decimal(0))
                        + Decimal(line['line_total']))
    versions = [delivery_version(row) for row in connection.execute(
        'SELECT * FROM order_delivery_versions WHERE order_id = ? '
        'ORDER BY id DESC', (order['id'],),
    )]
    result = dict(order)
    result['shipping_charges'] = format(Decimal(result['shipping_minor']) / 100, '.2f')
    invoices = [dict(row) for row in connection.execute(
        'SELECT id, reference, currency, created_at, workbook_format, '
        '(pdf IS NOT NULL) AS has_pdf FROM order_invoices '
        'WHERE order_id = ? ORDER BY id DESC', (order['id'],))]
    legacy_review = []
    if order['reference'] == 'LEGACY-ENQ-' + str(order['enquiry_id']):
        legacy_review = [serialize(row) for row in connection.execute(
            'SELECT s.* FROM enquiry_sku_lines s WHERE s.enquiry_id = ? '
            'AND s.is_active = 1 AND s.quantity_milli % 1000 != 0 '
            'AND NOT EXISTS (SELECT 1 FROM order_legacy_line_reviews r '
            'JOIN order_sku_lines replacement ON replacement.id = r.replacement_line_id '
            'WHERE r.order_id = ? AND r.source_line_id = s.id '
            'AND replacement.order_id = ? AND replacement.is_active = 1)',
            (order['enquiry_id'], order['id'], order['id']))]
    return {'order': result, 'lines': lines, 'invoices': invoices,
            'pi_line_requirements': pi_line_requirements(lines),
            'legacy_lines_requiring_review': legacy_review,
            'subtotals': {key: format(value, '.2f')
                          for key, value in totals.items()},
            'delivery': versions[0] if versions else None,
            'delivery_history': versions}


def record_revision(connection, order_id, user, action):
    """Record complete order state in the same transaction as each write."""
    state = details(connection, read_order(connection, user, order_id))
    # Delivery history has its own immutable table; copy the current version.
    state.pop('delivery_history')
    connection.execute(
        'INSERT INTO order_revisions '
        '(order_id, action, snapshot_json, actor_user_id) VALUES (?, ?, ?, ?)',
        (order_id, action, json.dumps(state), user['id']),
    )


def copied_line(connection, user, enquiry_id, line_id):
    """Copy only an active line from this order's authorized enquiry."""
    if (type(line_id) is not int or not 1 <= line_id <= 9223372036854775807
            or not read_enquiry(connection, user, enquiry_id)):
        raise ValueError('Invalid source enquiry line.')
    source = connection.execute(
        'SELECT * FROM enquiry_sku_lines WHERE id = ? AND enquiry_id = ? '
        'AND is_active = 1', (line_id, enquiry_id),
    ).fetchone()
    if not source:
        raise ValueError('Choose an active line belonging to this enquiry.')
    snapshot = serialize(source)
    values = validate_line({key: snapshot[key] for key in (
        'sku', 'description', 'quantity', 'unit_price', 'currency')})
    values.update(source_enquiry_line_id=line_id,
                  source_snapshot_json=json.dumps(snapshot))
    return values


def insert_lines(connection, order_id, lines, actor):
    """Persist new stable IDs with optional source traceability."""
    count = connection.execute(
        'SELECT COUNT(*) FROM order_sku_lines WHERE order_id = ? '
        'AND is_active = 1', (order_id,),
    ).fetchone()[0]
    if not lines or count + len(lines) > 50:
        raise ValueError('An order supports 1 to 50 active SKU lines.')
    for line in lines:
        columns = ', '.join(line)
        marks = ', '.join('?' for _ in line)
        connection.execute(
            'INSERT INTO order_sku_lines (' + columns
            + ', order_id, created_by, updated_by) VALUES (' + marks
            + ', ?, ?, ?)', [*line.values(), order_id, actor, actor],
        )
