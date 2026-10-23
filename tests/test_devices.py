"""Enrollment, authorization, and administrator decisions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, jsonify
from werkzeug.security import generate_password_hash

from backend import database
from backend.common.auth import authenticated_required
from backend.login.routes import bp as login_bp
from backend.security.devices import bp as device_bp, normalize_mac
from backend.migrations import migrate_database
from backend.security.middleware import init_security


class DeviceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'devices.db'
        migrate_database(path)
        db_patch = patch.object(database, 'DB_PATH', str(path))
        db_patch.start(); self.addCleanup(db_patch.stop)
        connection = database.get_db()
        with connection:
            for name, role in [('admin1', 'admin'), ('admin2', 'admin'), ('worker', 'sales_executive')]:
                connection.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',
                                   (name, generate_password_hash('fixture-password'), role))
            admin = connection.execute("SELECT id FROM users WHERE username='admin1'").fetchone()[0]
            connection.execute(
                "INSERT INTO device_registrations(user_id,mac_address,device_name,status,decided_at,decided_by) "
                "VALUES(?,'02:aa:bb:cc:dd:01','Admin PC','approved',strftime('%Y-%m-%dT%H:%M:%fZ','now'),?)",
                (admin, admin))
        connection.close()
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='device-test-key', TESTING=False)
        self.app.register_blueprint(login_bp)
        self.app.register_blueprint(device_bp)

        @self.app.get('/api/protected')
        @authenticated_required
        def protected():
            return jsonify(ok=True)

        @self.app.get('/api/unguarded')
        def unguarded():
            return jsonify(secret=True)

        init_security(self.app)

    def login(self, client, name, mac):
        with patch('backend.login.routes.hit', return_value=(True, 0, 'fixture')):
            return client.post('/login', data={'username': name, 'password': 'fixture-password',
                                               'mac_address': mac, 'device_name': 'Test PC'})

    def csrf(self, client):
        return {'X-CSRF-Token': client.get_cookie('amt_csrf_v2').value}

    def test_first_request_pending_repeated_request_and_approval(self):
        worker = self.app.test_client()
        self.assertEqual(self.login(worker, 'worker', '02:aa:bb:cc:dd:02').location, '/device/wait')
        self.assertEqual(worker.get('/api/device/status').json['status'], 'pending')
        self.assertEqual(worker.get('/api/protected').status_code, 403)
        self.assertEqual(worker.get('/api/unguarded').status_code, 403)
        waiting = worker.get('/device/wait')
        self.assertEqual(waiting.status_code, 200)
        waiting.close()
        worker.post('/logout', headers=self.csrf(worker))
        self.assertEqual(self.login(worker, 'worker', '02-AA-BB-CC-DD-02').location, '/device/wait')
        admin = self.app.test_client()
        self.login(admin, 'admin1', '02:aa:bb:cc:dd:01')
        rows = admin.get('/api/admin/devices').json['devices']
        self.assertEqual(len(rows), 2)
        pending = next(row for row in rows if row['status'] == 'pending')
        self.assertEqual(admin.post(f"/api/admin/devices/{pending['id']}/approve", headers=self.csrf(admin)).json['status'], 'approved')
        self.assertEqual(worker.get('/api/device/status').json['status'], 'approved')
        self.assertEqual(worker.get('/api/protected').status_code, 200)
        self.assertEqual(worker.get('/api/admin/devices').status_code, 403)
        self.assertEqual(worker.post(f"/api/admin/devices/{pending['id']}/revoke",
                                     headers=self.csrf(worker)).status_code, 403)
        self.assertEqual(admin.post(f"/api/admin/devices/{pending['id']}/revoke", headers=self.csrf(admin)).json['status'], 'revoked')
        self.assertEqual(worker.get('/api/protected').status_code, 403)
        self.assertEqual(worker.get('/api/device/status').json['status'], 'revoked')

    def test_rejection_invalid_mac_duplicate_and_unauthorized_decisions(self):
        worker = self.app.test_client()
        self.assertEqual(self.login(worker, 'worker', 'invalid').status_code, 400)
        self.assertEqual(self.login(worker, 'worker', '01:aa:bb:cc:dd:02').status_code, 400)
        with patch('backend.login.routes.hit', return_value=(True, 0, 'fixture')):
            self.assertEqual(worker.post('/login', data={
                'username': 'worker', 'password': 'fixture-password',
                'mac_address': '02:aa:bb:cc:dd:04', 'device_name': 'bad\nname',
            }).status_code, 400)
        self.login(worker, 'worker', '02:aa:bb:cc:dd:03')
        admin = self.app.test_client()
        self.login(admin, 'admin1', '02:aa:bb:cc:dd:01')
        pending = next(row for row in admin.get('/api/admin/devices').json['devices'] if row['status'] == 'pending')
        self.assertEqual(worker.post(f"/api/admin/devices/{pending['id']}/approve", headers=self.csrf(worker)).status_code, 403)
        self.assertEqual(admin.post(f"/api/admin/devices/{pending['id']}/reject", headers=self.csrf(admin)).json['status'], 'rejected')
        self.assertEqual(worker.get('/api/device/status').json['status'], 'rejected')
        self.assertEqual(worker.get('/api/protected').status_code, 403)
        other = self.app.test_client()
        self.assertEqual(self.login(other, 'admin2', '02:aa:bb:cc:dd:03').status_code, 409)
        self.assertEqual(admin.post('/api/admin/devices/1/revoke', headers=self.csrf(admin)).status_code, 403)

    def test_normalization(self):
        self.assertEqual(normalize_mac('02-AA-BB-CC-DD-EE'), '02:aa:bb:cc:dd:ee')
        for value in ('', None, '00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff', '01:00:00:00:00:00'):
            self.assertIsNone(normalize_mac(value))


if __name__ == '__main__':
    unittest.main()
