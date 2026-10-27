"""Filterable, permission-controlled view over durable audit and activity logs."""
from datetime import date

from flask import Blueprint, jsonify, request, send_file

from backend.common.auth import get_current_user, permission_required
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.security.audit import record_action

bp = Blueprint('audit', __name__)

EVENTS = '''
    SELECT CAST(id AS TEXT) AS event_key, action, actor_name AS username,
           actor_role AS role, created_at, ip_address, entity_type,
           COALESCE(entity_id,'') AS entity_id, details
      FROM audit_logs
'''


@bp.route('/audit-logs')
@permission_required('audit.view')
def audit_page():
    return send_file(FRONTEND_DIR / 'audit' / 'audit.html')


@bp.route('/api/audit-logs')
@permission_required('audit.view')
def audit_rows():
    try:
        page = int(request.args.get('page', '1'))
        size = int(request.args.get('page_size', '50'))
        if not 1 <= page <= 1_000_000 or not 1 <= size <= 100:
            raise ValueError
    except ValueError:
        return jsonify(error='Invalid page or page size.'), 400
    clauses, values = [], []
    filters = (
        ('action', 'action'), ('user', 'username'), ('role', 'role'),
    )
    for parameter, column in filters:
        value = (request.args.get(parameter) or '').strip()
        if value:
            clauses.append(column + ' = ?')
            values.append(value)
    for parameter, operator in (('from', '>='), ('to', '<=')):
        value = (request.args.get(parameter) or '').strip()
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                return jsonify(error='Use YYYY-MM-DD for date filters.'), 400
            clauses.append('date(created_at) ' + operator + ' date(?)')
            values.append(value)
    ip = (request.args.get('ip') or '').strip()
    if ip:
        clauses.append('ip_address LIKE ? ESCAPE \'!\'')
        values.append('%' + ip.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%')
    query = (request.args.get('q') or '').strip()
    if query:
        clauses.append("(action LIKE ? OR username LIKE ? OR entity_type LIKE ? "
                       "OR entity_id LIKE ? OR details LIKE ?)")
        pattern = '%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        values.extend([pattern] * 5)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    connection = get_db()
    try:
        total = connection.execute(
            'WITH events AS (' + EVENTS + ') SELECT COUNT(*) FROM events' + where,
            values).fetchone()[0]
        rows = connection.execute(
            'WITH events AS (' + EVENTS + ') SELECT * FROM events' + where +
            ' ORDER BY julianday(created_at) DESC,event_key DESC LIMIT ? OFFSET ?',
            [*values, size, (page - 1) * size]).fetchall()
        options = connection.execute(
            'WITH events AS (' + EVENTS + ') SELECT DISTINCT action,username,role '
            'FROM events ORDER BY action,username,role').fetchall()
    finally:
        connection.close()
    return jsonify(
        events=[dict(row) for row in rows], total=total, page=page,
        page_size=size, pages=max(1, (total + size - 1) // size),
        actions=sorted({row['action'] for row in options}),
        users=sorted({row['username'] for row in options if row['username']}),
        roles=sorted({row['role'] for row in options if row['role']}),
    )


def _cleanup_date():
    value = (request.args.get('before') or '').strip()
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


@bp.route('/api/audit-logs/cleanup', methods=['GET', 'DELETE'])
@permission_required('audit.delete')
def cleanup_audit_logs():
    cutoff = _cleanup_date()
    if cutoff is None:
        return jsonify(error='Select a valid date in YYYY-MM-DD format.'), 400

    connection = get_db()
    try:
        count = connection.execute(
            'SELECT COUNT(*) FROM audit_logs WHERE date(created_at) < date(?)',
            (cutoff,)).fetchone()[0]
        if request.method == 'GET':
            return jsonify(before=cutoff, matching=count)

        body = request.get_json(silent=True) or {}
        expected = body.get('expected_count')
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            return jsonify(error='Refresh the preview before deleting logs.'), 400
        connection.execute('BEGIN IMMEDIATE')
        count = connection.execute(
            'SELECT COUNT(*) FROM audit_logs WHERE date(created_at) < date(?)',
            (cutoff,)).fetchone()[0]
        if count != expected:
            connection.rollback()
            return jsonify(error='The matching log count changed. Review the preview again.',
                           matching=count), 409
        connection.execute(
            'DELETE FROM audit_logs WHERE date(created_at) < date(?)', (cutoff,))
        record_action(
            'audit_logs_cleanup', 'audit_logs', 'older_than:' + cutoff,
            {'deleted_count': count, 'before': cutoff},
            actor=get_current_user(), connection=connection)
        connection.commit()
        return jsonify(before=cutoff, deleted=count)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
