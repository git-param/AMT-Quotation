"""Server-side session, CSRF and response-hardening coverage."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, jsonify
from werkzeug.security import generate_password_hash

from backend import database
from backend.common.auth import authenticated_required
from backend.login.routes import bp as login_bp
from backend.migrations import migrate_database
from backend.orders.routes import bp as orders_bp
from backend.security.middleware import init_security


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'security.db'
        migrate_database(path)
        patcher = patch.object(database, 'DB_PATH', str(path))
        patcher.start(); self.addCleanup(patcher.stop)
        connection = database.get_db()
        with connection:
            connection.execute(
                "INSERT INTO users(username,password_hash,role) VALUES(?,?, 'admin')",
                ('security-user', generate_password_hash('fixture-password')),
            )
        connection.close()
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='security-test-key', TESTING=False)
        self.app.register_blueprint(login_bp)
        self.app.register_blueprint(orders_bp)

        @self.app.post('/api/security-write')
        @authenticated_required
        def protected_write():
            return jsonify(ok=True)

        init_security(self.app)

    def login(self, client):
        with patch('backend.login.routes.hit', return_value=(True, 0, 'test')):
            response = client.post('/login', data={
                'username': 'security-user', 'password': 'fixture-password'})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return client.get_cookie('amt_csrf_v2').value

    def test_two_logins_create_independently_valid_sessions(self):
        first, second = self.app.test_client(), self.app.test_client()
        self.login(first)
        self.assertEqual(first.get('/api/me').status_code, 200)
        self.login(second)
        self.assertEqual(second.get('/api/me').status_code, 200)
        self.assertEqual(first.get('/api/me').status_code, 200)

    def test_logout_revokes_only_the_current_session(self):
        first, second = self.app.test_client(), self.app.test_client()
        first_csrf = self.login(first)
        second_csrf = self.login(second)
        self.assertEqual(first.post('/logout', headers={
            'X-CSRF-Token': first_csrf}).status_code, 302)
        self.assertEqual(first.get('/api/me').status_code, 401)
        self.assertEqual(second.get('/api/me').status_code, 200)
        self.assertTrue(second_csrf)

    def test_session_expiry_and_revocation_are_independent(self):
        first, second = self.app.test_client(), self.app.test_client()
        self.login(first)
        self.login(second)
        connection = database.get_db()
        try:
            rows = connection.execute(
                'SELECT id_hash FROM app_sessions ORDER BY created_at,id_hash'
            ).fetchall()
            self.assertEqual(len(rows), 2)
            connection.execute(
                "UPDATE app_sessions SET expires_at='2000-01-01T00:00:00Z' "
                'WHERE id_hash=?', (rows[0]['id_hash'],))
            connection.commit()
        finally:
            connection.close()
        # The expired browser cannot authenticate; the other remains valid.
        self.assertEqual(first.get('/api/me').status_code, 401)
        self.assertEqual(second.get('/api/me').status_code, 200)
        connection = database.get_db()
        try:
            connection.execute(
                "UPDATE app_sessions SET revoked_at='2026-01-01T00:00:00Z', "
                "revoke_reason='test' WHERE id_hash=(SELECT id_hash FROM app_sessions "
                'WHERE expires_at > ?) ', ('2000-01-01T00:00:00Z',))
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(second.get('/api/me').status_code, 401)

    def test_csrf_token_is_required_for_authenticated_writes(self):
        client = self.app.test_client()
        token = self.login(client)
        self.assertEqual(client.post('/api/security-write').status_code, 403)
        self.assertEqual(client.post('/api/security-write',
            headers={'X-CSRF-Token': token}).status_code, 200)

    def test_security_headers_and_session_events(self):
        client = self.app.test_client()
        self.assertEqual(client.post('/login', data={
            'username': 'security-user', 'password': 'wrong-password'}).status_code, 401)
        self.login(client)
        response = client.get('/api/me')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        order_page = client.get('/orders?embedded=1', buffered=True)
        self.assertEqual(order_page.status_code, 200)
        self.assertEqual(order_page.headers['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(order_page.headers['Content-Security-Policy'], "frame-ancestors 'self'")
        connection = database.get_db()
        try:
            events = {row[0] for row in connection.execute(
                'SELECT event_type FROM security_events')}
            self.assertNotIn('login_failed', events)
            self.assertIn('login_succeeded', events)
        finally:
            connection.close()

    def test_pricing_ip_rule_blocks_login_after_valid_password(self):
        client = self.app.test_client()
        with patch('backend.login.routes.hit', return_value=(True, 0, 'test')), \
                patch('backend.login.routes.access_decision', return_value=(False, 'blocked_ip')):
            response = client.post('/login', data={
                'username': 'security-user', 'password': 'fixture-password'})
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(client.get_cookie('amt_session_v2'))

    def test_pricing_ip_rule_revokes_existing_session(self):
        client = self.app.test_client()
        with patch('backend.login.routes.hit', return_value=(True, 0, 'test')):
            self.login(client)
        with patch('backend.security.middleware.access_decision',
                   return_value=(False, 'blocked_ip')):
            response = client.get('/api/me')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get('/api/me').status_code, 401)


if __name__ == '__main__':
    unittest.main()
