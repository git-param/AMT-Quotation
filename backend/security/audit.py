"""Write append-only, consistently attributed application audit events."""
import json

from flask import current_app, has_request_context, request, session

from backend.database import get_db
from backend.security.request import client_ip

EXPLICIT_AUDIT_ENDPOINTS = {
    'manager_dashboard.cleanup_lookups',
    'settings.save_sku_lookup_limit', 'settings.save_currency_rates',
    'settings.save_currency_rate_schedule', 'settings.pi_number_counter',
    'settings.add_department', 'settings.update_department_prefix',
    'settings.settings', 'orders.delete_order', 'orders.generate_invoice',
    'orders.remove_invoice', 'orders.issue_preview',
    'orders.review_legacy_line',
}


def record_action(action, entity_type, entity_id=None, details=None, *,
                  actor=None, connection=None):
    """Record an action with the actor role and request IP when available."""
    own = connection is None
    db = connection or get_db()
    try:
        in_request = has_request_context()
        user_id = actor.get('id') if actor else (session.get('user_id') if in_request else None)
        actor_name = (actor.get('username') if actor else
                      (session.get('username', '') if in_request else '')) or ''
        role = actor.get('role', '') if actor else ''
        if actor is None and in_request and not user_id:
            from backend.common.auth import get_api_key, request_actor_name
            key = get_api_key()
            if key:
                actor_name, role = request_actor_name(), 'api'
        if user_id and not role:
            row = db.execute('SELECT role FROM users WHERE id=?',
                             (user_id,)).fetchone()
            role = row['role'] if row else ''
        db.execute(
            'INSERT INTO audit_logs(actor_user_id,actor_name,actor_role,ip_address,'
            'action,entity_type,entity_id,details) VALUES(?,?,?,?,?,?,?,?)',
            (user_id, actor_name[:100], str(role or '')[:50],
             client_ip() if in_request else '',
             action[:100], entity_type[:50],
             None if entity_id is None else str(entity_id)[:100],
             json.dumps(details or {}, ensure_ascii=False)),
        )
        if own:
            db.commit()
    finally:
        if own:
            db.close()


def audit_request(response):
    """Capture successful mutations and PI searches without request bodies."""
    if response.status_code >= 400 or request.endpoint in (
            'login.login', 'login.logout'):
        return response
    endpoint = request.endpoint or ''
    path = request.path
    if endpoint in EXPLICIT_AUDIT_ENDPOINTS:
        return response
    is_pi_search = request.method == 'GET' and path == '/api/pi-search'
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'} and not is_pi_search:
        return response
    if path.startswith('/api/audit-logs'):
        return response
    if path == '/api/log-copy' or path == '/api/lookup' or path.endswith('/sku-lookup'):
        # These routes write their full lookup/copy records to the legacy
        # activity tables, which the audit screen includes directly.
        return response

    action, entity = _action_entity(endpoint, path, request.method)
    details = {'endpoint': endpoint, 'method': request.method,
               'status': response.status_code}
    if request.method in {'POST', 'PUT', 'PATCH'}:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            if isinstance(body.get('skus'), list):
                details['sku_count'] = len(body['skus'])
            elif isinstance(body.get('lines'), list):
                details['sku_count'] = len(body['lines'])
    entity_id = None
    view_args = request.view_args or {}
    for key in ('lead_id', 'order_id', 'invoice_id', 'uid', 'department_id'):
        if key in view_args:
            entity_id = view_args[key]
            break
    payload = response.get_json(silent=True) if response.is_json else None
    if entity_id is None and isinstance(payload, dict):
        for key in ('lead', 'order'):
            value = payload.get(key)
            if isinstance(value, dict) and value.get('id') is not None:
                entity_id = value['id']
                break
    if entity_id is None and action == 'user_create':
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            entity_id = body.get('username')
    try:
        record_action(action, entity, entity_id, details)
    except Exception:
        # Auditing must not turn a completed user action into a failed response.
        current_app.logger.exception('Audit record failed for %s', endpoint)
    return response


def _action_entity(endpoint, path, method):
    if path == '/api/pi-search':
        return 'pi_search', 'pi_search'
    if path == '/api/quotation/letter':
        return 'sku_lookup', 'sku_lookup'
    verb = {'POST': 'create', 'PUT': 'update', 'PATCH': 'update',
            'DELETE': 'delete'}.get(method, 'action')
    if endpoint.endswith('api_manager_add_user'):
        return 'user_create', 'user'
    if '.api_manager_' in endpoint and '/users/' in path:
        operation = path.rsplit('/', 1)[-1].replace('-', '_') or verb
        if operation == 'delete':
            operation = 'deactivate'
        return 'user_' + operation, 'user'
    if '/api/leads' in path:
        if path.endswith('/deactivate'):
            return 'client_deactivate', 'client'
        if path.endswith('/activate'):
            return 'client_activate', 'client'
        return 'client_' + verb, 'client'
    if '/api/orders/' in path and '/invoices/preview' in path:
        if path.endswith('/calculate'):
            return 'pi_preview_calculate', 'pi'
        return 'pi_preview_' + verb, 'pi'
    if '/api/orders/' in path and '/invoices' in path:
        return 'pi_' + ('delete' if method == 'DELETE' else verb), 'pi'
    if '/api/orders' in path:
        return 'order_' + verb, 'order'
    if '/enquiries' in path:
        return 'enquiry_' + verb, 'enquiry'
    if 'user' in endpoint:
        return 'user_' + verb, 'user'
    if 'department' in endpoint:
        return 'department_' + verb, 'department'
    return (endpoint.replace('.', '_') or 'application') + '_' + verb, 'application'
