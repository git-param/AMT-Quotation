"""Enquiry source lifecycle and permission tests on an isolated SQLite file."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from backend import database
from backend.enquiry_sources.routes import bp
from backend.migrations import migrate_database
from backend.migration_definitions import MIGRATIONS


class SourceTests(unittest.TestCase):
    """Validate management APIs without provider credentials or requests."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sources.db'
        migrate_database(self.path)
        db_patch = patch.object(database, 'DB_PATH', str(self.path))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-only-key')
        app.register_blueprint(bp)
        self.client = app.test_client()
        self.ids = {}
        connection = database.get_db()
        try:
            with connection:
                for role in ('admin', 'sales_tl', 'sales_executive',
                             'manager', 'user'):
                    cursor = connection.execute(
                        'INSERT INTO users (username, password_hash, role) '
                        'VALUES (?, ?, ?)', (role, 'test-placeholder', role),
                    )
                    self.ids[role] = cursor.lastrowid
        finally:
            connection.close()
        self.as_role('admin')

    def as_role(self, role):
        with self.client.session_transaction() as session:
            session.clear()
            if role:
                session['user_id'] = self.ids[role]

    def create(self, **overrides):
        data = {'name': 'Sales inbox', 'source_type': 'email',
                'contact_value': 'sales@example.com'}
        data.update(overrides)
        return self.client.post('/api/sources', json=data)

    def test_create_edit_and_list_preserve_identity(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        uid = response.json['id']
        original = self.client.get('/api/sources').json['sources'][0]
        response = self.client.put(f'/api/sources/{uid}', json={
            'name': 'WhatsApp desk', 'source_type': 'whatsapp',
            'contact_value': '+91 98765 43210',
        })
        self.assertEqual(response.status_code, 200)
        edited = self.client.get('/api/sources').json['sources'][0]
        self.assertEqual(edited['contact_value'], '+919876543210')
        self.assertEqual(edited['code'], original['code'])
        self.assertEqual(edited['created_at'], original['created_at'])
        self.assertEqual(edited['id'], uid)
        self.assertIsNotNone(edited['updated_at'])

    def test_deactivate_edit_and_reactivate_without_deletion(self):
        uid = self.create().json['id']
        for _ in range(2):
            self.assertEqual(self.client.post(
                f'/api/sources/{uid}/deactivate'
            ).status_code, 200)
        self.assertEqual(self.client.put(f'/api/sources/{uid}', json={
            'name': 'Updated name', 'source_type': 'email',
            'contact_value': 'sales@example.com',
        }).status_code, 200)
        source = self.client.get('/api/sources').json['sources'][0]
        self.assertEqual(source['is_active'], 0)
        self.assertEqual(self.create().status_code, 409)
        self.assertEqual(self.client.delete(
            f'/api/sources/{uid}'
        ).status_code, 405)
        self.assertEqual(self.client.post(
            f'/api/sources/{uid}/activate'
        ).status_code, 200)
        self.assertEqual(self.client.get(
            '/api/sources'
        ).json['sources'][0]['is_active'], 1)

    def test_permissions_for_all_operations(self):
        uid = self.create().json['id']
        routes = [('GET', '/sources'), ('GET', '/api/sources'),
                  ('POST', '/api/sources'), ('PUT', f'/api/sources/{uid}'),
                  ('POST', f'/api/sources/{uid}/deactivate'),
                  ('POST', f'/api/sources/{uid}/activate')]
        for role in ('sales_executive', 'user', None):
            self.as_role(role)
            for method, url in routes:
                response = self.client.open(url, method=method, json={})
                expected = 403 if role else 302 if url == '/sources' else 401
                self.assertEqual(response.status_code, expected)
        for role in ('admin', 'sales_tl', 'manager'):
            self.as_role(role)
            self.assertEqual(self.client.get('/api/sources').status_code, 200)
            self.assertEqual(self.create(
                contact_value=f'{role}@example.com'
            ).status_code, 201)
            self.assertEqual(self.client.put(f'/api/sources/{uid}', json={
                'name': role, 'source_type': 'email',
                'contact_value': 'sales@example.com',
            }).status_code, 200)
            self.assertEqual(self.client.post(
                f'/api/sources/{uid}/deactivate'
            ).status_code, 200)
            self.assertEqual(self.client.post(
                f'/api/sources/{uid}/activate'
            ).status_code, 200)

    def test_validation_duplicates_and_missing_sources(self):
        for changes in ({'name': ''}, {'name': 'a' * 101},
                        {'source_type': 'fax'}, {'contact_value': 'invalid'},
                        {'contact_value': None},
                        {'source_type': 'whatsapp',
                         'contact_value': '9876543210'}):
            self.assertEqual(self.create(**changes).status_code, 400)
        self.assertEqual(self.client.post(
            '/api/sources', json=['invalid']
        ).status_code, 400)
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create(
            contact_value='SALES@EXAMPLE.COM'
        ).status_code, 409)
        self.assertEqual(self.create(
            source_type='whatsapp', contact_value='+1 (234) 567-8901'
        ).status_code, 201)
        self.assertEqual(self.create(
            source_type='whatsapp', contact_value='+12345678901'
        ).status_code, 409)
        self.assertEqual(self.client.put('/api/sources/9999', json={
            'name': 'Missing', 'source_type': 'email',
            'contact_value': 'missing@example.com',
        }).status_code, 404)
        self.assertEqual(self.client.post(
            '/api/sources/9999/deactivate'
        ).status_code, 404)

    def test_inactive_account_cannot_manage_sources(self):
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'UPDATE users SET is_active = 0 WHERE id = ?',
                    (self.ids['admin'],),
                )
        finally:
            connection.close()
        self.assertEqual(self.client.get('/api/sources').status_code, 401)

    def test_existing_source_rows_survive_version_four(self):
        path = Path(self.temp.name) / 'legacy.db'
        migrate_database(path, MIGRATIONS[:3])
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO enquiry_sources (code, name, is_active) "
                "VALUES ('legacy', 'Legacy channel', 0)"
            )
            connection.commit()
            original = connection.execute(
                'SELECT id, code, name, is_active, created_at '
                'FROM enquiry_sources'
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), [4, 5, 6, 7, 8, 9, 10])
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(original, connection.execute(
                'SELECT id, code, name, is_active, created_at '
                'FROM enquiry_sources'
            ).fetchall())
            self.assertEqual(connection.execute(
                'SELECT source_type, contact_value FROM enquiry_sources'
            ).fetchone(), (None, None))
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
