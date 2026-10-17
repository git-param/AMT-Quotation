"""Shared application configuration managed by team leads and administrators."""
import json
import re
import sqlite3
from decimal import Decimal
from backend.common.currencies import configured_rates

from flask import Blueprint, jsonify, request, send_file

from backend.common.auth import authenticated_required, get_current_user, permission_required
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('settings', __name__)


@bp.route('/api/currency-rates', methods=['GET'])
@permission_required('settings.manage')
def read_currency_rates():
    connection = get_db()
    try:
        return jsonify(rates=configured_rates(connection))
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
            connection.execute("INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) VALUES(?,?,'currency_rates_update','app_settings','currency_rates',?)",
                (user['id'],user['username'],json.dumps({'before':before,'after':rates})))
        return jsonify(rates=rates)
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
            connection.execute(
                'INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) '
                "VALUES(?,?,'department_create','departments',?,?)",
                (user['id'], user['username'], str(cursor.lastrowid), json.dumps({'name': name, 'pi_prefix': prefix})),
            )
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
            connection.execute(
                'INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) '
                "VALUES(?,?,'department_prefix_update','departments',?,?)",
                (user['id'], user['username'], str(department_id), json.dumps({'before': previous['pi_prefix'], 'after': prefix})),
            )
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
                connection.execute(
                    'INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) '
                    "VALUES(?,?,'settings_update','app_settings','hsn_code',?)",
                    (user['id'], user['username'], json.dumps({'before': previous, 'after': value.strip()})))
        return jsonify(hsn_code=shared_hsn(connection))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    finally:
        connection.close()
