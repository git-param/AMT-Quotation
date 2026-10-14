"""Permission-controlled email and WhatsApp source management."""

import re
import sqlite3
import uuid

from flask import Blueprint, jsonify, request, send_file

from backend.common.auth import permission_required
from backend.config import FRONTEND_DIR
from backend.database import get_db

bp = Blueprint('enquiry_sources', __name__)


def _validated_source():
    """Validate full edits and normalize contacts for duplicate detection."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('Provide a JSON object.')
    name = data.get('name')
    value = data.get('contact_value')
    kind = data.get('source_type')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError('Enter a source name (up to 100 characters).')
    if not isinstance(value, str):
        raise ValueError('Enter a contact address or number.')
    value = value.strip()
    if kind == 'email':
        if len(value) > 254 or not re.fullmatch(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
                r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+",
                value):
            raise ValueError('Enter a valid email address.')
        value = value.lower()
    elif kind == 'whatsapp':
        value = re.sub(r'[ ()-]', '', value)
        if not re.fullmatch(r'\+[1-9][0-9]{6,14}', value):
            raise ValueError(
                'Use an international number, e.g. +919876543210.'
            )
    else:
        raise ValueError('Choose Email or WhatsApp.')
    return name.strip(), kind, value


@bp.route('/sources')
@permission_required('sources.manage')
def source_page():
    """Serve the source management screen."""
    return send_file(str(FRONTEND_DIR / 'enquiry_sources' / 'sources.html'))


@bp.route('/api/sources')
@permission_required('sources.manage')
def list_sources():
    """List active, inactive, and unclassified legacy sources."""
    connection = get_db()
    try:
        rows = connection.execute(
            'SELECT * FROM enquiry_sources '
            'ORDER BY is_active DESC, name COLLATE NOCASE, id'
        ).fetchall()
        return jsonify(sources=[dict(row) for row in rows])
    finally:
        connection.close()


@bp.route('/api/sources', methods=['POST'])
@bp.route('/api/sources/<int:source_id>', methods=['PUT'])
@permission_required('sources.manage')
def save_source(source_id=None):
    """Create or edit a source while retaining its ID, code, and status."""
    try:
        name, kind, value = _validated_source()
    except ValueError as error:
        return jsonify(error=str(error)), 400
    connection = get_db()
    try:
        with connection:
            if source_id is None:
                cursor = connection.execute(
                    'INSERT INTO enquiry_sources '
                    '(code, name, source_type, contact_value, updated_at) '
                    "VALUES (?, ?, ?, ?, "
                    "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                    (uuid.uuid4().hex, name, kind, value),
                )
                source_id = cursor.lastrowid
                status = 201
            else:
                cursor = connection.execute(
                    'UPDATE enquiry_sources SET name = ?, source_type = ?, '
                    'contact_value = ?, updated_at = '
                    "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                    (name, kind, value, source_id),
                )
                if not cursor.rowcount:
                    return jsonify(error='Source not found.'), 404
                status = 200
        return jsonify(ok=True, id=source_id), status
    except sqlite3.IntegrityError:
        return jsonify(
            error='That contact already exists (active or inactive).'
        ), 409
    finally:
        connection.close()


@bp.route('/api/sources/<int:source_id>/deactivate', methods=['POST'])
@bp.route('/api/sources/<int:source_id>/activate', methods=['POST'])
@permission_required('sources.manage')
def set_source_status(source_id):
    """Change availability without deleting historical source identities."""
    active = int(request.path.endswith('/activate'))
    connection = get_db()
    try:
        with connection:
            cursor = connection.execute(
                'UPDATE enquiry_sources SET is_active = ?, updated_at = '
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (active, source_id),
            )
            if not cursor.rowcount:
                return jsonify(error='Source not found.'), 404
        return jsonify(ok=True)
    finally:
        connection.close()
