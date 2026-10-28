"""Shared application configuration managed by team leads and administrators."""
import json
import re
import sqlite3
from decimal import Decimal
from backend.common.currencies import configured_rates, rate_is_stale
from backend.common.live_rates import status as rate_status, refresh_if_due, wake_scheduler

from flask import Blueprint, jsonify, request, send_file

from backend.common.auth import authenticated_required, get_current_user, login_required, permission_required
from backend.common.skus import MAX_SKU_LOOKUP_LIMIT, sku_lookup_limit
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.security.audit import record_action

bp = Blueprint('settings', __name__)


@bp.route('/api/sku-lookup-limit', methods=['GET'])
@login_required
def read_sku_lookup_limit():
    return jsonify(max_sku_lookup=sku_lookup_limit())


@bp.route('/api/sku-lookup-limit', methods=['PUT'])
@permission_required('users.manage')
def save_sku_lookup_limit():
    data = request.get_json(silent=True)
    value = data.get('max_sku_lookup') if isinstance(data, dict) and set(data) == {'max_sku_lookup'} else None
    if type(value) is not int or not 1 <= value <= MAX_SKU_LOOKUP_LIMIT:
        return jsonify(error=f'Choose a SKU lookup limit from 1 to {MAX_SKU_LOOKUP_LIMIT}.'), 400
    user = get_current_user()
    connection = get_db()
    try:
        before = sku_lookup_limit(connection)
        with connection:
            connection.execute(
                "INSERT INTO app_settings(key,value) VALUES('sku_lookup_limit',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(value),)
            )
            record_action('sku_lookup_limit_update', 'app_settings', 'sku_lookup_limit',
                          {'before': before, 'after': value}, actor=user,
                          connection=connection)
        return jsonify(max_sku_lookup=value)
    finally:
        connection.close()


def currency_rate_payload(connection):
    return {'rates': configured_rates(connection, allow_stale=True),
            'stale': rate_is_stale(connection), **rate_status(connection)}


@bp.route('/api/currency-rates', methods=['GET'])
@permission_required('settings.manage')
def read_currency_rates():
    connection = get_db()
    try:
        return jsonify(currency_rate_payload(connection))
    finally:
        connection.close()


@bp.route('/api/currency-rates', methods=['PUT'])
@permission_required('users.manage')
def save_currency_rates():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'rates'} or not isinstance(data['rates'], dict) or set(data['rates']) - {'INR','AED','GBP','EUR'}:
        return jsonify(error='Provide INR, AED, GBP and EUR rates per 1 USD.'), 400
    rates = {}
    for code, value in data['rates'].items():
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,6})?', value) or not 0 < Decimal(value) <= 1000000:
            return jsonify(error='Enter a positive '+code+' rate with up to 6 decimal places.'), 400
        rates[code] = value
    user = get_current_user()
    connection = get_db()
    try:
        with connection:
            before = configured_rates(connection)
            connection.execute("INSERT INTO app_settings(key,value) VALUES('currency_rates',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(rates),))
            record_action('currency_rates_update', 'app_settings', 'currency_rates',
                          {'before': before, 'after': rates}, actor=user,
                          connection=connection)
        return jsonify(currency_rate_payload(connection))
    finally:
        connection.close()


@bp.route('/api/currency-rates/schedule', methods=['PUT'])
@permission_required('users.manage')
def save_currency_rate_schedule():
    data = request.get_json(silent=True)
    hours = data.get('refresh_hours') if isinstance(data, dict) and set(data) == {'refresh_hours'} else None
    if type(hours) is not int or not 1 <= hours <= 168:
        return jsonify(error='Choose a refresh interval from 1 to 168 hours.'), 400
    user = get_current_user()
    connection = get_db()
    try:
        before = rate_status(connection)['refresh_hours']
        with connection:
            connection.execute("INSERT INTO app_settings(key,value) VALUES('currency_rate_refresh_hours',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(hours),))
            record_action('currency_rate_schedule_update', 'app_settings',
                          'currency_rate_refresh_hours', {'before': before, 'after': hours},
                          actor=user, connection=connection)
        wake_scheduler()
        return jsonify(currency_rate_payload(connection))
    finally:
        connection.close()


@bp.route('/api/currency-rates/refresh', methods=['POST'])
@permission_required('users.manage')
def refresh_currency_rates():
    try:
        refreshed = refresh_if_due(force=True)
    except ValueError as error:
        return jsonify(error=str(error)), 502
    if not refreshed:
        return jsonify(error='A currency rate refresh is already in progress.'), 409
    connection = get_db()
    try:
        return jsonify(currency_rate_payload(connection))
    finally:
        connection.close()


def shared_hsn(connection):
    row = connection.execute("SELECT value FROM app_settings WHERE key='hsn_code'").fetchone()
    return row[0] if row else ''


def department_names(connection):
    return [row[0] for row in connection.execute(
        'SELECT name FROM departments ORDER BY name COLLATE NOCASE'
    )]


def department_configuration(connection):
    return {'departments': department_names(connection), 'department_settings': [dict(row) for row in connection.execute(
        'SELECT id, name, pi_prefix FROM departments ORDER BY name COLLATE NOCASE'
    )]}


def validated_pi_prefix(value):
    if not isinstance(value, str):
        raise ValueError('Enter a PI prefix such as AMT or PUC.')
    value = value.strip().rstrip('/')
    if value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,19}', value):
        raise ValueError('Use up to 20 letters, digits, hyphens or underscores for the PI prefix.')
    return value


def user_pi_defaults(connection, user_id):
    row = connection.execute(
        'SELECT u.department, COALESCE(d.pi_prefix, \'\') AS pi_prefix '
        'FROM users u LEFT JOIN departments d ON d.name = trim(u.department) COLLATE NOCASE '
        'WHERE u.id = ?', (user_id,),
    ).fetchone()
    return dict(row) if row else {'department': '', 'pi_prefix': ''}


PI_NUMBER_SETTING = 'pi_number_last_used'


def pi_number_last_used(connection):
    row = connection.execute('SELECT value FROM app_settings WHERE key=?', (PI_NUMBER_SETTING,)).fetchone()
    return int(row[0]) if row and str(row[0]).isdigit() else 0


def allocate_pi_reference(connection, user_id):
    """Reserve the next global PI number; caller must hold a write transaction."""
    number = pi_number_last_used(connection) + 1
    if number > 2_000_000_000:
        raise ValueError('The PI number sequence has reached its maximum value.')
    connection.execute(
        'INSERT INTO app_settings(key,value) VALUES(?,?) '
        'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (PI_NUMBER_SETTING, str(number)),
    )
    prefix = user_pi_defaults(connection, user_id)['pi_prefix']
    return f'{prefix}/{number}' if prefix else str(number)


@bp.route('/api/pi-number-counter', methods=['GET', 'PUT'])
@permission_required('users.manage')
def pi_number_counter():
    user = get_current_user()
    connection = get_db()
    try:
        if request.method == 'PUT':
            data = request.get_json(silent=True)
            value = data.get('last_used') if isinstance(data, dict) and set(data) == {'last_used'} else None
            if type(value) is not int or not 0 <= value <= 2_000_000_000:
                return jsonify(error='Enter a whole PI number from 0 to 2,000,000,000.'), 400
            with connection:
                before = pi_number_last_used(connection)
                connection.execute(
                    'INSERT INTO app_settings(key,value) VALUES(?,?) '
                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (PI_NUMBER_SETTING, str(value)),
                )
                record_action('pi_number_counter_update', 'app_settings', PI_NUMBER_SETTING,
                              {'before': before, 'after': value}, actor=user,
                              connection=connection)
        return jsonify(last_used=pi_number_last_used(connection))
    finally:
        connection.close()


@bp.route('/api/departments', methods=['GET'])
@permission_required('settings.manage')
def list_departments():
    connection = get_db()
    try:
        return jsonify(department_configuration(connection))
    finally:
        connection.close()


@bp.route('/api/departments', methods=['POST'])
@permission_required('users.manage')
def add_department():
    """Administrators manage the choices shared by user creation and editing."""
    data = request.get_json(silent=True)
    name = data.get('name') if isinstance(data, dict) else None
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        return jsonify(error='Enter a department name (100 characters or fewer).'), 400
    name = name.strip()
    try:
        prefix = validated_pi_prefix(data.get('pi_prefix', ''))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    user = get_current_user()
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute('INSERT INTO departments(name, pi_prefix) VALUES (?, ?)', (name, prefix))
            record_action('department_create', 'departments', cursor.lastrowid,
                          {'name': name, 'pi_prefix': prefix}, actor=user,
                          connection=connection)
        return jsonify(department_configuration(connection)), 201
    except sqlite3.IntegrityError:
        return jsonify(error='This department already exists.'), 409
    finally:
        connection.close()


@bp.route('/api/departments/<int:department_id>/pi-prefix', methods=['PUT'])
@permission_required('users.manage')
def update_department_prefix(department_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'pi_prefix'}:
        return jsonify(error='Provide the PI prefix.'), 400
    try:
        prefix = validated_pi_prefix(data['pi_prefix'])
    except ValueError as error:
        return jsonify(error=str(error)), 400
    user = get_current_user()
    connection = get_db()
    try:
        with connection:
            previous = connection.execute('SELECT name, pi_prefix FROM departments WHERE id = ?', (department_id,)).fetchone()
            if not previous:
                return jsonify(error='Department not found.'), 404
            connection.execute('UPDATE departments SET pi_prefix = ? WHERE id = ?', (prefix, department_id))
            record_action('department_prefix_update', 'departments', department_id,
                          {'before': previous['pi_prefix'], 'after': prefix},
                          actor=user, connection=connection)
        return jsonify(department_configuration(connection))
    finally:
        connection.close()


@bp.route('/api/sku-defaults', methods=['GET'])
@authenticated_required
def sku_defaults():
    """Expose the shared item default without granting configuration access."""
    connection = get_db()
    try:
        return jsonify(shared_hsn_code=shared_hsn(connection))
    finally:
        connection.close()


@bp.route('/configuration')
@permission_required('settings.manage')
def page():
    return send_file(FRONTEND_DIR / 'configuration' / 'configuration.html')


@bp.route('/api/settings', methods=['GET', 'PUT'])
@permission_required('settings.manage')
def settings():
    user = get_current_user()
    connection = get_db()
    try:
        if request.method == 'PUT':
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or set(data) != {'hsn_code'}:
                raise ValueError('Provide the shared HSN code.')
            value = data['hsn_code']
            if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}|[0-9]{6}|[0-9]{8}', value.strip()):
                raise ValueError('Enter a 4, 6 or 8 digit HSN code.')
            with connection:
                previous = shared_hsn(connection)
                connection.execute("UPDATE app_settings SET value=? WHERE key='hsn_code'", (value.strip(),))
                record_action('settings_update', 'app_settings', 'hsn_code',
                              {'before': previous, 'after': value.strip()},
                              actor=user, connection=connection)
        return jsonify(hsn_code=shared_hsn(connection))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    finally:
        connection.close()


@bp.route('/api/pi-discount-limit', methods=['GET','PUT'])
@authenticated_required
def pi_discount_limit():
    from backend.orders.policy import maximum_discount
    from backend.enquiries.lines import number
    user=get_current_user()
    if not user:return jsonify(error='Not logged in'),401
    connection=get_db()
    try:
        if request.method=='PUT':
            if user['role'] not in ('admin','manager'):
                return jsonify(error='Only admins can configure the maximum discount.'),403
            data=request.get_json(silent=True)
            if not isinstance(data,dict) or set(data)!={'maximum_percent'}:
                return jsonify(error='Provide the maximum discount percentage.'),400
            try:value=Decimal(number(data['maximum_percent'],2,Decimal('100')))/100
            except ValueError as error:return jsonify(error=str(error)),400
            with connection:
                before=maximum_discount(connection)
                connection.execute("INSERT INTO app_settings(key,value) VALUES('max_pi_discount_percent',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(value),))
                record_action('discount_limit_update','app_settings','max_pi_discount_percent',
                              {'before':str(before),'after':str(value)},actor=user,connection=connection)
        return jsonify(maximum_percent=str(maximum_discount(connection)))
    finally:connection.close()
