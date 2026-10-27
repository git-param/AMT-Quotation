"""Decimal SKU lines with scoped access and retained revisions."""
from backend.common.currencies import CURRENCIES

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

from flask import Blueprint, jsonify, request

from backend.common.auth import authenticated_required, get_current_user
from backend.database import get_db, log_search
from backend.common.request import _get_ip
from backend.enquiries.routes import read_enquiry

bp = Blueprint('enquiry_lines', __name__)


def number(value, places, maximum, positive=False):
    """Reject invalid numbers, precision and out-of-range values."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('Provide a decimal number.')
    raw = str(value).strip()
    if len(raw) > 30 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', raw):
        raise ValueError('Use a plain nonnegative decimal number.')
    if '.' in raw and len(raw.split('.')[1]) > places:
        raise ValueError(f'Maximum precision is {places} decimal places.')
    decimal = Decimal(raw)
    if decimal > maximum or (decimal <= 0 if positive else decimal < 0):
        raise ValueError('Number is outside the supported range.')
    return int(decimal * (10 ** places))


def validated(data, existing=None):
    """Allow line details; the server assigns relationships and totals."""
    fields = {'sku', 'description', 'quantity', 'unit_price', 'currency'}
    if not isinstance(data, dict) or set(data) - fields:
        raise ValueError(
            'Invalid fields; totals and relationships are immutable.'
        )
    old = serialize(existing) if existing else {}
    values = {}
    for field, maximum in (('sku', 100), ('description', 2000)):
        value = data.get(field, old.get(field))
        if (not isinstance(value, str)
                or not 1 <= len(value.strip()) <= maximum):
            raise ValueError('A valid ' + field + ' is required.')
        values[field] = value.strip()
    values['quantity_milli'] = number(
        data.get('quantity', old.get('quantity')),
        3, Decimal('999999.999'), True
    )
    if values['quantity_milli'] % 1000 and (
            existing is None or 'quantity' in data):
        raise ValueError('Quantity must be a positive whole number.')
    values['unit_price_minor'] = number(
        data.get('unit_price', old.get('unit_price')),
        2, Decimal('999999999.99')
    )
    currency = data.get('currency', old.get('currency'))
    if currency not in CURRENCIES:
        raise ValueError('Choose USD, INR, AED, GBP or EUR currency.')
    values['currency'] = currency
    return values


def serialize(row):
    """Calculate rounded totals from scaled integers, never binary floats."""
    result = dict(row)
    quantity = Decimal(result.pop('quantity_milli')) / 1000
    price = Decimal(result.pop('unit_price_minor')) / 100
    result['quantity'] = format(
        quantity, '.0f' if quantity == quantity.to_integral_value() else '.3f'
    )
    result['unit_price'] = format(price, '.2f')
    for field in ('catalog_original_price', 'catalog_sale_price'):
        minor_key = field + '_minor'
        if minor_key in result:
            minor = result.pop(minor_key)
            result[field] = (format(Decimal(minor) / 100, '.2f')
                             if minor is not None else None)
    result['line_total'] = format((quantity * price).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')
    return result


def revision(connection, line_id, user_id, action):
    """Store a full snapshot for future orders to copy rather than mutate."""
    row = connection.execute('SELECT * FROM enquiry_sku_lines WHERE id = ?',
                             (line_id,)).fetchone()
    connection.execute(
        'INSERT INTO enquiry_line_revisions '
        '(line_id, snapshot_json, action, actor_user_id) VALUES (?, ?, ?, ?)',
        (line_id, json.dumps(serialize(row)), action, user_id),
    )


def authorize(connection, enquiry_id, write=False):
    """Recheck client grants for every enquiry-line endpoint."""
    user = get_current_user()
    if not user:
        return None, (jsonify(error='Not logged in'), 401)
    enquiry = read_enquiry(connection, user, enquiry_id)
    if not enquiry:
        return None, (jsonify(error='Enquiry not found.'), 404)
    if write and not enquiry['can_edit']:
        return None, (jsonify(error='Client access is read-only.'), 403)
    return user, None


@bp.route('/api/enquiries/<int:enquiry_id>/lines')
@authenticated_required
def list_lines(enquiry_id):
    """Return current lines and currency totals for authorized enquiries."""
    connection = get_db()
    try:
        connection.execute('BEGIN')
        _, error = authorize(connection, enquiry_id)
        if error:
            return error
        rows = connection.execute(
            'SELECT * FROM enquiry_sku_lines WHERE enquiry_id = ? '
            'AND is_active = 1 ORDER BY id', (enquiry_id,),
        ).fetchall()
        lines = [serialize(row) for row in rows]
        totals = {}
        for line in lines:
            currency = line['currency']
            totals[currency] = totals.get(currency, Decimal(0)) + Decimal(
                line['line_total'])
        return jsonify(lines=lines, subtotals={
            currency: format(total, '.2f')
            for currency, total in totals.items()
        })
    finally:
        connection.close()


@bp.route('/api/enquiries/<int:enquiry_id>/lines/<int:line_id>')
@authenticated_required
def line_detail(enquiry_id, line_id):
    """Retain accessible removed-line records and their complete revisions."""
    connection = get_db()
    try:
        connection.execute('BEGIN')
        _, error = authorize(connection, enquiry_id)
        if error:
            return error
        row = connection.execute(
            'SELECT * FROM enquiry_sku_lines WHERE id = ? AND enquiry_id = ?',
            (line_id, enquiry_id),
        ).fetchone()
        if not row:
            return jsonify(error='Line not found.'), 404
        history = connection.execute(
            'SELECT * FROM enquiry_line_revisions '
            'WHERE line_id = ? ORDER BY id',
            (line_id,),
        ).fetchall()
        versions = []
        for record in history:
            value = dict(record)
            value['snapshot'] = json.loads(value.pop('snapshot_json'))
            versions.append(value)
        return jsonify(line=serialize(row), revisions=versions)
    finally:
        connection.close()


@bp.route('/api/enquiries/<int:enquiry_id>/lines', methods=['POST'])
@bp.route('/api/enquiries/<int:enquiry_id>/lines/<int:line_id>',
          methods=['PUT'])
@bp.route('/api/enquiries/<int:enquiry_id>/lines/<int:line_id>',
          methods=['DELETE'])
@authenticated_required
def save_line(enquiry_id, line_id=None):
    """Create, edit or soft-remove while retaining stable IDs and history."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user, error = authorize(connection, enquiry_id, write=True)
        if error:
            return error
        existing = None
        if line_id is not None:
            existing = connection.execute(
                'SELECT * FROM enquiry_sku_lines WHERE id = ? '
                'AND enquiry_id = ? AND is_active = 1',
                (line_id, enquiry_id),
            ).fetchone()
            if not existing:
                return jsonify(error='Active line not found.'), 404
        if request.method == 'DELETE':
            enquiry = read_enquiry(connection, user, enquiry_id)
            if not enquiry['can_delete']:
                return jsonify(error='SKU deletion is not permitted.'), 403
            connection.execute(
                'UPDATE enquiry_sku_lines SET is_active = 0, updated_by = ?, '
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                'WHERE id = ?',
                (user['id'], line_id),
            )
            action = 'remove'
        else:
            values = validated(request.get_json(silent=True), existing)
            validate_enquiry_stock(connection, enquiry_id, [values], line_id)
            if existing is None:
                columns = ', '.join(values)
                placeholders = ', '.join('?' for _ in values)
                cursor = connection.execute(
                    'INSERT INTO enquiry_sku_lines (' + columns
                    + ', enquiry_id, created_by, updated_by) VALUES ('
                    + placeholders + ', ?, ?, ?)',
                    [*values.values(), enquiry_id, user['id'], user['id']],
                )
                line_id = cursor.lastrowid
                action = 'create'
            else:
                assignments = ', '.join(key + ' = ?' for key in values)
                connection.execute(
                    'UPDATE enquiry_sku_lines SET ' + assignments
                    + ', updated_by = ?, '
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    'WHERE id = ?', [*values.values(), user['id'], line_id],
                )
                action = 'edit'
        revision(connection, line_id, user['id'], action)
        row = connection.execute(
            'SELECT * FROM enquiry_sku_lines WHERE id = ?', (line_id,)
        ).fetchone()
        connection.commit()
        return jsonify(line=serialize(row)), 201 if action == 'create' else 200
    except ValueError as error:
        return jsonify(error=str(error)), 400
    finally:
        connection.rollback()
        connection.close()


def lookup_product(sku):
    """Reuse the quotation Shopify lookup and its existing 15-minute cache."""
    from backend.quotation_tool.shopify import fetch_sku

    return fetch_sku(sku)


@bp.route('/api/enquiries/<int:enquiry_id>/sku-lookup', methods=['POST'])
@authenticated_required
def sku_lookup(enquiry_id):
    """Fetch a draft for review; never overwrite existing enquiry lines."""
    connection = get_db()
    try:
        _, error = authorize(connection, enquiry_id, write=True)
        if error:
            return error
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'sku'}
                or not isinstance(data['sku'], str)
                or not 1 <= len(data['sku'].strip()) <= 100):
            return jsonify(error='Provide a SKU (up to 100 characters).'), 400
        try:
            product = lookup_product(data['sku'].strip())
        except Exception:
            log_search(get_current_user()['username'], _get_ip(), [data['sku'].strip()], 0, 1)
            return jsonify(
                error='SKU provider is unavailable. Try again.'
            ), 502
        # A network call must not preserve rights that were revoked meanwhile.
        _, error = authorize(connection, enquiry_id, write=True)
        if error:
            return error
        found = int(bool(product.get('found')))
        log_search(get_current_user()['username'], _get_ip(), [data['sku'].strip()], found, 1-found)
        if not product.get('found'):
            return jsonify(error='SKU not found.'), 404
        price = product.get('sale_price')
        if price is None:
            price = product.get('price')
        if price is None:
            return jsonify(error='SKU has no available price.'), 422
        try:
            decimal_price = Decimal(str(price))
            if (not decimal_price.is_finite() or decimal_price < 0
                    or decimal_price > Decimal('999999999.99')):
                raise InvalidOperation
        except InvalidOperation:
            return jsonify(error='SKU price is not supported.'), 422
        draft = {
            'sku': product.get('sku', data['sku'].strip()),
            'description': product.get('title', ''), 'quantity': '1',
            'unit_price': format(decimal_price.quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f'),
            'currency': 'USD',
        }
        return jsonify(draft=draft, stock=product.get('qty'),
                       condition=product.get('condition'),
                       url=product.get('url'))
    finally:
        connection.close()


def validate_enquiry_stock(connection, enquiry_id, values, exclude_id=None):
    from backend.orders.catalog import validate_stock_batch
    keys = {item['sku'].strip().casefold() for item in values}
    items = [(item['sku'], Decimal(item['quantity_milli'])/1000) for item in values]
    for row in connection.execute('SELECT id,sku,quantity_milli FROM enquiry_sku_lines '
                                  'WHERE enquiry_id=? AND is_active=1', (enquiry_id,)):
        if row['id'] != exclude_id and row['sku'].strip().casefold() in keys:
            items.append((row['sku'], Decimal(row['quantity_milli'])/1000))
    validate_stock_batch(items, connection)


def create_lines(connection, enquiry_id, values, actor):
    """Insert reviewed drafts under the caller's enquiry transaction."""
    validate_enquiry_stock(connection, enquiry_id, values)
    for item in values:
        columns = ', '.join(item)
        marks = ', '.join('?' for _ in item)
        cursor = connection.execute(
            'INSERT INTO enquiry_sku_lines (' + columns
            + ', enquiry_id, created_by, updated_by) VALUES (' + marks
            + ', ?, ?, ?)', [*item.values(), enquiry_id, actor, actor],
        )
        revision(connection, cursor.lastrowid, actor, 'create')


@bp.route('/api/enquiries/<int:enquiry_id>/lines/bulk', methods=['POST'])
@authenticated_required
def bulk_add(enquiry_id):
    """Atomically add multiple reviewed lines to one authorized enquiry."""
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user, error = authorize(connection, enquiry_id, write=True)
        if error:
            return error
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {'lines'}
                or not isinstance(data['lines'], list)
                or not 1 <= len(data['lines']) <= 50):
            raise ValueError('Provide 1 to 50 complete SKU lines.')
        values = [validated(item) for item in data['lines']]
        create_lines(connection, enquiry_id, values, user['id'])
        connection.commit()
        return jsonify(ok=True, added=len(values)), 201
    except ValueError as error:
        return jsonify(error=str(error)), 400
    finally:
        connection.rollback()
        connection.close()


def lookup_rate():
    """Reuse the existing cached USD/INR rate service."""
    from backend.quotation_tool.shopify import get_inr_rate

    return get_inr_rate()


@bp.route('/api/enquiries/sku-lookup', methods=['POST'])
@authenticated_required
def bulk_lookup():
    """Fetch drafts for a new or existing enquiry without saving anything."""
    from backend.enquiries.routes import editable_client

    data = request.get_json(silent=True)
    if (not isinstance(data, dict)
            or set(data) - {'client_id', 'enquiry_id', 'skus', 'currency'}
            or ('client_id' in data) == ('enquiry_id' in data)):
        return jsonify(
            error='Provide exactly one client or enquiry scope.'
        ), 400
    key = 'enquiry_id' if 'enquiry_id' in data else 'client_id'
    if type(data[key]) is not int or not 1 <= data[key] <= 9223372036854775807:
        return jsonify(error='Invalid scope ID.'), 400
    skus = data.get('skus')
    currency = data.get('currency')
    from backend.common.skus import sku_lookup_limit
    max_lookup = sku_lookup_limit()
    if (not isinstance(skus, list) or not 1 <= len(skus) <= max_lookup
            or any(not isinstance(sku, str) or not 1 <= len(sku.strip()) <= 100
                   for sku in skus) or currency not in CURRENCIES):
        count_hint = 'one SKU' if max_lookup == 1 else f'1 to {max_lookup} SKUs'
        return jsonify(error=f'Provide {count_hint} and a supported currency.'), 400
    connection = get_db()

    def permitted():
        user = get_current_user()
        if not user:
            return jsonify(error='Not logged in'), 401
        if key == 'enquiry_id':
            return authorize(connection, data[key], write=True)[1]
        client = editable_client(connection, user, data[key])
        if not client:
            return jsonify(error='Client not found.'), 404
        if not client['can_edit']:
            return jsonify(error='Client access is read-only.'), 403
        if not client['is_active']:
            return jsonify(error='Reactivate the client first.'), 400
        return None

    try:
        error = permitted()
        if error:
            return error
        from backend.common.skus import duplicate_skus
        duplicates = duplicate_skus(skus)
        if duplicates:
            return jsonify(error='Duplicate SKUs: '+', '.join(duplicates)+
                           '. Enter each SKU only once.'), 400
        rate = None
        try:
            rate = Decimal(str(lookup_rate()))
            if not rate.is_finite() or rate <= 0:
                rate = None
        except Exception:
            # A display conversion must not prevent USD lookup or manual entry.
            rate = None
        results = []
        from backend.settings import shared_hsn
        from backend.common.currencies import configured_rates
        hsn=shared_hsn(connection)
        saved_rates = configured_rates(connection)
        factors = {'USD': Decimal('1'), 'INR': Decimal(saved_rates['INR']) if saved_rates.get('INR') else rate,
                   **{code:Decimal(saved_rates[code]) if saved_rates.get(code) else None for code in ('AED','GBP','EUR')}}
        for raw in skus:
            sku = raw.strip()
            row = {'sku': sku, 'description': '', 'quantity': '1', 'hsn_code':hsn,
                   'unit_price': '', 'currency': currency, 'found': False,
                   'lookup_status': 'unavailable'}
            try:
                product = lookup_product(sku)
                if not product.get('found'):
                    row['lookup_status'] = 'not_found'
                    row['error'] = 'SKU not found in the catalog. Add this SKU manually.'
                else:
                    from backend.orders.catalog import remember_stock
                    remember_stock(sku,product.get('qty'))
                    row.update(description=product.get('title', ''),
                               found=True, lookup_status='found',
                               stock=product.get('qty'),
                               condition=product.get('condition', ''),
                               url=product.get('url', ''))
                    row['catalog_prices'] = {}
                    for code, factor in factors.items():
                        amounts = {}
                        for name in ('price', 'sale_price'):
                            try:
                                amount = Decimal(str(product.get(name)))
                                if (factor is None or not amount.is_finite()
                                        or amount < 0):
                                    continue
                                amounts[name] = format(
                                    (amount * factor).quantize(
                                        Decimal('0.01'), rounding=ROUND_HALF_UP
                                    ), '.2f'
                                )
                            except (InvalidOperation, TypeError):
                                continue
                        if amounts or code in ('USD','INR'):
                            row['catalog_prices'][code] = amounts
                    price = product.get('sale_price')
                    if price is None:
                        price = product.get('price')
                    price = Decimal(str(price))
                    if not price.is_finite() or price < 0:
                        raise InvalidOperation
                    if currency != 'USD':
                        if factors[currency] is None:
                            row['error'] = 'Rate unavailable; configure the '+currency+' rate or enter the price manually.'
                            results.append(row)
                            continue
                        price *= factors[currency]
                    price = price.quantize(
                        Decimal('0.01'), rounding=ROUND_HALF_UP
                    )
                    if price > Decimal('999999999.99'):
                        raise InvalidOperation
                    row['unit_price'] = format(price, '.2f')
            except Exception:
                row['error'] = 'Lookup unavailable; enter details manually.'
            results.append(row)
        error = permitted()
        if error:
            return error
        found = sum(bool(row['found']) for row in results)
        log_search(get_current_user()['username'], _get_ip(), [sku.strip() for sku in skus], found, len(results)-found)
        return jsonify(drafts=results, currency=currency,
                       usd_inr_rate=str(factors['INR']) if factors['INR'] else None,shared_hsn_code=hsn)
    finally:
        connection.close()
