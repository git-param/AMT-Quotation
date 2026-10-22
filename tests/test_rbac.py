"""Test permissions, legacy sessions, and account lifecycle behavior."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from backend import database
from backend.common.auth import ROLE_LABELS
from backend.migrations import migrate_database


class RBACTests(unittest.TestCase):
    """Use an isolated database and Flask app without live API calls."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.db'
        migrate_database(self.path)
        db_patch = patch.object(database, 'DB_PATH', str(self.path))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        # Import route definitions with fake provider configuration only.
        with patch.dict(os.environ, {
                'SHOPIFY_SHOP': 'example.invalid',
                'SHOPIFY_CLIENT_ID': 'test-placeholder',
                'SHOPIFY_CLIENT_SECRET': 'test-placeholder',
        }):
            from backend.login.routes import bp as login_bp
            from backend.manager_dashboard.routes import bp as manager_bp
            from backend.quotation_tool.routes import bp as quotation_bp
            from backend.quotation_tool.search_routes import bp as search_bp
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True, SECRET_KEY='test-only-signing-key'
        )
        from backend.enquiry_sources.routes import bp as sources_bp
        from backend.client_leads.routes import bp as leads_bp
        from backend.client_access.routes import bp as access_bp
        from backend.enquiries.routes import bp as enquiries_bp
        from backend.enquiries.lines import bp as lines_bp
        for blueprint in (
                login_bp, manager_bp, quotation_bp, search_bp, sources_bp,
                leads_bp, access_bp, enquiries_bp, lines_bp):
            self.app.register_blueprint(blueprint)
        self.client = self.app.test_client()
        self.ids = {}
        connection = database.get_db()
        try:
            with connection:
                connection.executemany('INSERT INTO departments(name) VALUES (?)',
                                       [('Sales',), ('Sales & Support',), ('Management',)])
                for role in ROLE_LABELS:
                    cursor = connection.execute(
                        'INSERT INTO users (username, password_hash, role) '
                        'VALUES (?, ?, ?)',
                        (role, generate_password_hash('fixture-pass'), role),
                    )
                    self.ids[role] = cursor.lastrowid
        finally:
            connection.close()

    def session_as(self, role):
        """Use the old session format, including an untrusted cached role."""
        with self.client.session_transaction() as session:
            session.clear()
            session['user_id'] = self.ids[role]
            session['username'] = role
            session['role'] = 'manager'

    def test_anonymous_api_denied_for_every_protected_route(self):
        for rule in self.app.url_map.iter_rules():
            if not rule.rule.startswith('/api/'):
                continue
            path = rule.rule.replace('<int:uid>', str(self.ids['user']))
            path = path.replace('<int:kid>', '1')
            path = path.replace('<item_id>', 'test-item')
            path = path.replace('<int:source_id>', '1')
            path = path.replace('<int:lead_id>', '1')
            path = path.replace('<int:enquiry_id>', '1')
            path = path.replace('<int:line_id>', '1')
            method = ('POST' if 'POST' in rule.methods else
                      'PUT' if 'PUT' in rule.methods else 'GET')
            with self.subTest(endpoint=rule.rule):
                response = self.client.open(path, method=method, json={})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json['error'], 'Not logged in')

    def test_quotation_api_key_identity_lookup_and_access_boundary(self):
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'INSERT INTO api_keys(key, label) VALUES (?, ?)',
                    ('amtq-test-key', 'Inbox'),
                )
        finally:
            connection.close()
        headers = {'X-API-Key': 'amtq-test-key'}
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.client.get('/api/me', headers={'X-API-Key': 'wrong'}).status_code, 401)
        response = self.client.get('/api/me', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {
            'auth': 'api_key', 'role': 'api', 'username': 'api-key',
        })
        with patch('backend.quotation_tool.routes.fetch_sku',
                   return_value={'found': True, 'price': 25}) as lookup, \
                patch('backend.quotation_tool.routes.threading.Thread') as thread:
            response = self.client.post('/api/lookup', headers=headers,
                                        json={'skus': ['SKU-1']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['found'], 1)
            lookup.assert_called_once_with('SKU-1')
            self.assertEqual(thread.call_args.kwargs['args'][0], 'API: Inbox')
        self.assertEqual(self.client.get('/api/manager/users', headers=headers).status_code, 401)
        self.assertEqual(self.client.post('/api/change-password', headers=headers,
                                          json={}).status_code, 401)
        connection = database.get_db()
        try:
            self.assertIsNotNone(connection.execute(
                'SELECT last_used FROM api_keys WHERE key = ?', ('amtq-test-key',)
            ).fetchone()['last_used'])
        finally:
            connection.close()

    def test_api_key_does_not_change_session_profile(self):
        self.session_as('admin')
        response = self.client.get('/api/me')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['username'], 'admin')
        self.assertIn('account.self', response.json['permissions'])

    def test_admin_can_issue_and_revoke_quotation_api_key(self):
        self.session_as('admin')
        created = self.client.post('/api/manager/api-keys/create',
                                   json={'label': 'Inbox'})
        self.assertEqual(created.status_code, 200)
        key = created.json['key']
        self.assertTrue(key.startswith('amtq-'))
        listed = self.client.get('/api/manager/api-keys').json['api_keys']
        self.assertEqual(listed[0]['label'], 'Inbox')
        self.assertNotIn('key', listed[0])
        separate_client = self.app.test_client()
        self.assertEqual(separate_client.get('/api/me',
                         headers={'X-API-Key': key}).status_code, 200)
        self.assertEqual(self.client.post(
            f"/api/manager/api-keys/{created.json['id']}/revoke"
        ).status_code, 200)
        self.assertEqual(separate_client.get('/api/me',
                         headers={'X-API-Key': key}).status_code, 401)

    def test_role_permission_matrix_and_legacy_session(self):
        for role in ROLE_LABELS:
            self.session_as(role)
            profile = self.client.get('/api/me')
            self.assertEqual(profile.status_code, 200)
            self.assertEqual(profile.json['role'], role)
            self.assertIn('quotation.use', profile.json['permissions'])
            with self.client.get('/') as response:
                self.assertEqual(response.status_code, 200)
            management = role in ('manager', 'admin', 'sales_tl')
            administration = role in ('manager', 'admin')
            self.assertEqual(
                self.client.get('/api/manager/stats').status_code,
                200 if management else 403,
            )
            self.assertEqual(
                self.client.get('/api/manager/users').status_code,
                200 if administration else 403,
            )

    def test_non_admin_cannot_mutate_users(self):
        for role in ('user', 'sales_executive', 'sales_tl'):
            self.session_as(role)
            target = self.ids['admin']
            for suffix in ('role', 'activate', 'deactivate', 'delete',
                           'reset-password'):
                response = self.client.post(
                    f'/api/manager/users/{target}/{suffix}',
                    json={'role': 'admin', 'password': 'fixture-pass'},
                )
                self.assertEqual(response.status_code, 403)
            self.assertEqual(self.client.post(
                '/api/manager/users/add', json={}
            ).status_code, 403)

    def test_login_password_change_logout_and_inactive_login(self):
        self.assertEqual(self.client.post('/login', data={
            'username': 'user', 'password': 'incorrect',
        }).status_code, 401)
        self.assertEqual(self.client.post('/login', data={
            'username': 'user', 'password': 'fixture-pass',
        }).status_code, 302)
        self.assertEqual(self.client.post('/api/change-password', json={
            'current': 'fixture-pass', 'new_password': 'updated-pass',
        }).status_code, 200)
        self.assertEqual(self.client.get('/logout').status_code, 302)
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.client.post('/login', data={
            'username': 'user', 'password': 'updated-pass',
        }).status_code, 302)
        self.session_as('admin')
        self.client.post(
            f"/api/manager/users/{self.ids['user']}/deactivate"
        )
        self.client.get('/logout')
        self.assertEqual(self.client.post('/login', data={
            'username': 'user', 'password': 'updated-pass',
        }).status_code, 401)

    def test_user_creation_requires_valid_department(self):
        self.session_as('admin')
        base = {'username': 'department-test', 'password': 'fixture-pass',
                'role': 'sales_executive'}
        for extra in ({}, {'department': None}, {'department': ''},
                      {'department': '   '}, {'department': 123},
                      {'department': []}, {'department': 'x' * 101}):
            with self.subTest(extra=extra):
                response = self.client.post('/api/manager/users/add',
                                            json={**base, **extra})
                self.assertEqual(response.status_code, 400)
                self.assertIn('Department', response.json['error'])
        self.assertEqual(self.client.post('/api/manager/users/add', json={
            **base, 'department': '  Sales & Support  ',
        }).status_code, 200)
        users = self.client.get('/api/manager/users').json['users']
        created = next(user for user in users if user['username'] == base['username'])
        self.assertEqual(created['department'], 'Sales & Support')
        self.assertNotIn('password_hash', created)
        existing = next(user for user in users if user['username'] == 'admin')
        self.assertEqual(existing['department'], '')

    def test_edit_user_saves_profile_and_settings_atomically(self):
        self.session_as('admin')
        uid = self.ids['sales_executive']
        body = {'username': 'Renamed', 'department': '  Sales  ',
                'role': 'sales_executive', 'is_active': 1,
                'supervisor_user_id': self.ids['sales_tl']}
        connection = database.get_db()
        try:
            original_hash = connection.execute(
                'SELECT password_hash FROM users WHERE id = ?', (uid,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit',
                                         json=body).status_code, 200)
        users = self.client.get('/api/manager/users').json['users']
        target = next(u for u in users if u['id'] == uid)
        self.assertEqual(target['username'], 'Renamed')
        self.assertEqual(target['department'], 'Sales')
        self.assertEqual(target['supervisor_user_id'], self.ids['sales_tl'])
        for changes in (
                {'username': 'admin'}, {'department': ' '},
                {'department': 'x' * 101}, {'department': 'Unconfigured'}, {'username': 'x' * 41},
                {'role': 'unknown'}, {'is_active': True},
                {'supervisor_user_id': uid},
                {'supervisor_user_id': self.ids['admin']},
                {'supervisor_user_id': 2**100},
                {'role': 'sales_tl'}, {'is_active': 0}):
            with self.subTest(changes=changes):
                response = self.client.post(f'/api/manager/users/{uid}/edit',
                                            json={**body, **changes})
                self.assertIn(response.status_code, (400, 409))
                current = next(u for u in self.client.get('/api/manager/users').json['users']
                               if u['id'] == uid)
                self.assertEqual(current, target)
        self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit', json={
            **body, 'role': 'sales_tl', 'supervisor_user_id': None,
        }).status_code, 200)
        connection = database.get_db()
        try:
            self.assertEqual(connection.execute(
                'SELECT password_hash FROM users WHERE id = ?', (uid,)
            ).fetchone()[0], original_hash)
        finally:
            connection.close()

    def test_edit_user_permissions_self_protection_and_missing_user(self):
        body = {'username': 'Updated admin', 'department': 'Management',
                'role': 'admin', 'is_active': 1, 'supervisor_user_id': None}
        uid = self.ids['admin']
        self.session_as('sales_executive')
        self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit',
                                         json=body).status_code, 403)
        self.session_as('admin')
        self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit',
                                         json=body).status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session['username'], 'Updated admin')
        for changes in ({'role': 'sales_executive'}, {'is_active': 0}):
            self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit',
                json={**body, **changes}).status_code, 400)
        self.assertEqual(self.client.post('/api/manager/users/99999/edit',
                                         json=body).status_code, 404)

    def test_admin_can_add_edit_and_clear_international_phone(self):
        self.session_as('admin')
        base = {'username': 'phone-user', 'password': 'fixture-pass', 'role': 'sales_executive',
                'department': 'Sales', 'is_active': 1, 'supervisor_user_id': None}
        phone = {'phone_country_code': '91', 'phone_number': '(98765) 43210'}
        self.assertEqual(self.client.post('/api/manager/users/add', json={**base, **phone}).status_code, 200)
        def current():
            return next(u for u in self.client.get('/api/manager/users').json['users'] if u['username'] == 'phone-user')
        user = current()
        uid = user['id']
        self.assertEqual((user['phone_country_code'], user['phone_number']), ('+91', '9876543210'))
        # Existing clients that omit phone fields must retain the saved phone.
        self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit', json=base).status_code, 200)
        self.assertEqual(current()['phone_number'], '9876543210')
        invalid = [('', '1234567890'), ('+91', ''), ('+9999', '1234567890'), ('+0', '1234567890'),
                   ('+91', 'call-me'), ('+91', '123'), ('+91', '1' * 14), (91, '1234567890'),
                   ('+91', None)]
        for code, number in invalid:
            with self.subTest(code=code, number=number):
                data = {**base, 'phone_country_code': code, 'phone_number': number}
                self.assertEqual(self.client.post('/api/manager/users/add', json={**data, 'username': 'invalid-phone'}).status_code, 400)
                self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit', json=data).status_code, 400)
                self.assertEqual(current()['phone_number'], '9876543210')
        self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit', json={
            **base, 'phone_country_code': '+1', 'phone_number': '202-555-0123',
        }).status_code, 200)
        self.assertEqual((current()['phone_country_code'], current()['phone_number']), ('+1', '2025550123'))
        self.assertEqual(self.client.post(f'/api/manager/users/{uid}/edit', json={
            **base, 'phone_country_code': '', 'phone_number': '',
        }).status_code, 200)
        self.assertEqual((current()['phone_country_code'], current()['phone_number']), ('', ''))

    def test_admin_create_assign_deactivate_preserves_account(self):
        self.session_as('admin')
        self.assertEqual(self.client.post('/api/manager/users/add', json={
            'username': 'new-sales', 'password': 'fixture-pass',
            'role': 'sales_executive', 'department': 'Sales',
        }).status_code, 200)
        self.assertEqual(self.client.post('/api/manager/users/add', json={
            'username': 'invalid', 'password': 'fixture-pass', 'role': 'root',
        }).status_code, 400)
        target = self.ids['sales_executive']
        connection = database.get_db()
        try:
            original = connection.execute(
                'SELECT password_hash FROM users WHERE id = ?', (target,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(self.client.post(
            f'/api/manager/users/{target}/role', json={'role': 'sales_tl'}
        ).status_code, 200)
        self.session_as('sales_executive')
        self.assertEqual(
            self.client.get('/api/manager/stats').status_code, 200
        )
        self.session_as('admin')
        self.assertEqual(self.client.post(
            f'/api/manager/users/{target}/delete'
        ).status_code, 200)
        self.session_as('sales_executive')
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        connection = database.get_db()
        try:
            row = connection.execute(
                'SELECT password_hash, is_active FROM users WHERE id = ?',
                (target,),
            ).fetchone()
            self.assertTrue(row['password_hash'] == original)
            self.assertEqual(row['is_active'], 0)
        finally:
            connection.close()

    def test_unknown_role_fails_closed_and_html_denial(self):
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    "UPDATE users SET role = 'unknown' WHERE id = ?",
                    (self.ids['user'],),
                )
        finally:
            connection.close()
        self.session_as('user')
        self.assertEqual(self.client.get('/api/me').status_code, 403)
        response = self.client.get('/manager')
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Access denied', response.data)

    def test_self_lockout_blocked_and_missing_user_returns_404(self):
        self.session_as('admin')
        self.assertEqual(self.client.post(
            f"/api/manager/users/{self.ids['admin']}/deactivate"
        ).status_code, 400)
        self.assertEqual(self.client.post(
            '/api/manager/users/9999/role', json={'role': 'sales_tl'}
        ).status_code, 404)

    def test_role_demotion_and_permission_revocation_affect_open_session(self):
        self.session_as('sales_tl')
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    "UPDATE users SET role = 'sales_executive' WHERE id = ?",
                    (self.ids['sales_tl'],),
                )
            self.assertEqual(
                self.client.get('/api/manager/stats').status_code, 403
            )
            with connection:
                connection.execute(
                    "DELETE FROM role_permissions WHERE "
                    "role_code = 'sales_executive' "
                    "AND permission_code = 'quotation.use'"
                )
            self.assertEqual(self.client.get('/api/rate').status_code, 403)
        finally:
            connection.close()

    def test_deleted_account_session_is_rejected(self):
        self.session_as('user')
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'DELETE FROM users WHERE id = ?', (self.ids['user'],)
                )
        finally:
            connection.close()
        self.assertEqual(self.client.get('/api/rate').status_code, 401)

    def test_account_reactivation_restores_login(self):
        self.session_as('admin')
        uid = self.ids['user']
        self.assertEqual(self.client.post(
            f'/api/manager/users/{uid}/deactivate'
        ).status_code, 200)
        self.assertEqual(self.client.post(
            f'/api/manager/users/{uid}/activate'
        ).status_code, 200)
        self.client.get('/logout')
        self.assertEqual(self.client.post('/login', data={
            'username': 'user', 'password': 'fixture-pass',
        }).status_code, 302)

    def test_quotation_lookup_and_rate_keep_existing_response_format(self):
        self.session_as('sales_executive')
        product = {'found': True, 'sku': '001', 'price': 25.0, 'qty': 3}
        with patch('backend.quotation_tool.routes.fetch_sku',
                   return_value=product) as lookup, \
                patch('backend.quotation_tool.routes.threading.Thread'):
            response = self.client.post('/api/lookup', json={'skus': ['001']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['found'], 1)
            self.assertEqual(response.json['results'][0]['price'], 25.0)
            lookup.assert_called_once_with('001')
        with patch('backend.quotation_tool.routes.get_inr_rate',
                   return_value=83.5):
            self.assertEqual(self.client.get('/api/rate').json, {'rate': 83.5})

    def test_quotation_lookup_rejects_duplicate_skus(self):
        self.session_as('sales_executive')
        with patch('backend.quotation_tool.routes.fetch_sku') as lookup:
            response=self.client.post('/api/lookup',json={'skus':[' PART-A ','part-a']})
            self.assertEqual(response.status_code,400,response.json)
            self.assertIn('Duplicate SKUs: part-a',response.json['error'])
            lookup.assert_not_called()

    def test_quotation_lookup_rejects_excess_without_truncation(self):
        self.session_as('sales_executive')
        connection = database.get_db()
        with connection:
            connection.execute("UPDATE app_settings SET value='2' WHERE key='sku_lookup_limit'")
        connection.close()
        with patch('backend.quotation_tool.routes.fetch_sku') as lookup:
            response = self.client.post('/api/lookup', json={'skus': ['A', 'B', 'C']})
            self.assertEqual(response.status_code, 400)
            self.assertIn('at most 2 SKUs', response.json['error'])
            lookup.assert_not_called()
        with patch('backend.quotation_tool.routes.fetch_sku',
                   return_value={'found': True}) as lookup, \
                patch('backend.quotation_tool.routes.threading.Thread'):
            response = self.client.post('/api/lookup', json={'skus': ['A', 'B']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(lookup.call_count, 2)

    def test_api_key_lookup_obeys_admin_limit(self):
        connection = database.get_db()
        with connection:
            connection.execute("UPDATE app_settings SET value='1' WHERE key='sku_lookup_limit'")
            connection.execute(
                "INSERT INTO api_keys(key,label) VALUES('amtq-limited','Inbox')"
            )
        connection.close()
        with patch('backend.quotation_tool.routes.fetch_sku') as lookup:
            response = self.client.post('/api/lookup',
                headers={'X-API-Key': 'amtq-limited'}, json={'skus': ['A', 'B']})
            self.assertEqual(response.status_code, 400)
            self.assertIn('at most 1 SKU', response.json['error'])
            lookup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
