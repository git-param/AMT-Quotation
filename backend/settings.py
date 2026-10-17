"""Shared application configuration managed by team leads and administrators."""
import json
import re
import sqlite3

from flask import Blueprint, jsonify, request, send_file

from backend.common.auth import authenticated_required, get_current_user, permission_required
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('settings', __name__)


def shared_hsn(connection):
    row = connection.execute("SELECT value FROM app_settings WHERE key='hsn_code'").fetchone()
    return row[0] if row else ''


def department_names(connection):
    return [row[0] for row in connection.execute(
        'SELECT name FROM departments ORDER BY name COLLATE NOCASE'
    )]


@bp.route('/api/departments', methods=['GET'])
@permission_required('settings.manage')
def list_departments():
    connection = get_db()
    try:
        return jsonify(departments=department_names(connection))
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
    user = get_current_user()
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute('INSERT INTO departments(name) VALUES (?)', (name,))
            connection.execute(
                'INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) '
                "VALUES(?,?,'department_create','departments',?,?)",
                (user['id'], user['username'], str(cursor.lastrowid), json.dumps({'name': name})),
            )
        return jsonify(departments=department_names(connection)), 201
    except sqlite3.IntegrityError:
        return jsonify(error='This department already exists.'), 409
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
