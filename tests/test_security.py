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

        @self.app.post('/api/security-write')
        @authenticated_required
        def protected_write():
            return jsonify(ok=True)

        init_security(self.app)

    def login(self, client):
        response = client.post('/login', data={
            'username': 'security-user', 'password': 'fixture-password'})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        return client.get_cookie('amt_csrf_v2').value

    def test_new_login_invalidates_previous_session(self):
        first, second = self.app.test_client(), self.app.test_client()
        self.login(first)
        self.assertEqual(first.get('/api/me').status_code, 200)
        self.login(second)
        self.assertEqual(second.get('/api/me').status_code, 200)
        self.assertEqual(first.get('/api/me').status_code, 401)

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
        connection = database.get_db()
        try:
            events = {row[0] for row in connection.execute(
                'SELECT event_type FROM security_events')}
            self.assertIn('login_failed', events)
            self.assertIn('login_succeeded', events)
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
