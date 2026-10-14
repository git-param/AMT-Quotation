"""Private lead ownership, sharing, and supervisor authorization tests."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from backend import database
from backend.client_leads.routes import bp as leads_bp
from backend.manager_dashboard.routes import bp as manager_bp
from backend.migrations import migrate_database


class LeadTests(unittest.TestCase):
    """Use isolated users with two separate supervisor groups."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'leads.db'
        migrate_database(path)
        db_patch = patch.object(database, 'DB_PATH', str(path))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-only-key')
        app.register_blueprint(leads_bp)
        app.register_blueprint(manager_bp)
        self.client = app.test_client()
        self.ids = {}
        connection = database.get_db()
        try:
            with connection:
                for name, role in (
                        ('admin', 'admin'), ('tl1', 'sales_tl'),
                        ('tl2', 'sales_tl'), ('exec1', 'sales_executive'),
                        ('exec2', 'sales_executive'), ('legacy', 'user'),
                        ('manager', 'manager'), ('unknown', 'unknown')):
                    cursor = connection.execute(
                        'INSERT INTO users (username, role, password_hash) '
                        'VALUES (?, ?, ?)', (name, role, 'test-placeholder'),
                    )
                    self.ids[name] = cursor.lastrowid
        finally:
            connection.close()

    def as_user(self, name):
        with self.client.session_transaction() as session:
            session.clear()
            if name:
                session['user_id'] = self.ids[name]
                session['role'] = 'admin'  # Never trust cached session roles.

    def create(self, name):
        self.as_user(name)
        response = self.client.post('/api/leads', json={'name': name})
        self.assertEqual(response.status_code, 201)
        lead = response.json['lead']
        self.assertEqual(lead['created_by'], self.ids[name])
        self.assertTrue(lead['created_at'].endswith('Z'))
        return lead['id']

    def visible(self, name):
        self.as_user(name)
        return {lead['id'] for lead in self.client.get(
            '/api/leads'
        ).json['leads']}

    def assign(self, executive, tl):
        self.as_user('admin')
        return self.client.post(
            f'/api/manager/users/{self.ids[executive]}/supervisor',
            json={'supervisor_user_id': self.ids[tl] if tl else None},
        )

    def test_each_role_can_create_and_creator_is_identifiable(self):
        for name in self.ids:
            lead_id = self.create(name)
            self.as_user('admin')
            lead = self.client.get(f'/api/leads/{lead_id}').json['lead']
            self.assertEqual(lead['creator_name'], name)

    def test_default_privacy_and_cross_tl_isolation(self):
        leads = {name: self.create(name) for name in self.ids}
        self.assertEqual(self.visible('tl1'), {leads['tl1']})
        self.assertEqual(self.visible('exec1'), {leads['exec1']})
        self.assertEqual(self.assign('exec1', 'tl1').status_code, 200)
        self.assertEqual(self.assign('exec2', 'tl2').status_code, 200)
        self.assertEqual(self.visible('tl1'), {leads['tl1'], leads['exec1']})
        self.assertEqual(self.visible('tl2'), {leads['tl2'], leads['exec2']})
        self.assertEqual(self.visible('admin'), set(leads.values()))
        self.assertEqual(self.visible('manager'), set(leads.values()))

    def test_explicit_shares_and_detail_queries(self):
        lead_id = self.create('tl2')
        self.as_user('exec1')
        self.assertEqual(self.client.get(
            f'/api/leads/{lead_id}'
        ).status_code, 404)
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'INSERT INTO client_lead_shares (lead_id, user_id) '
                    'VALUES (?, ?)',
                    (lead_id, self.ids['exec1']),
                )
        finally:
            connection.close()
        self.assertEqual(self.visible('exec1'), {lead_id})
        self.assertEqual(self.visible('tl1'), set())
        self.as_user('exec1')
        self.assertEqual(self.client.get(
            f'/api/leads/{lead_id}'
        ).status_code, 200)

    def test_manipulated_ownership_and_filters_cannot_expand_access(self):
        hidden = self.create('tl2')
        own = self.create('exec1')
        for field in ('created_by', 'created_at', 'supervisor_user_id'):
            self.assertEqual(self.client.post('/api/leads', json={
                'name': 'Spoofed', field: self.ids['admin'],
            }).status_code, 400)
        response = self.client.get('/api/leads?created_by=1&all=true')
        self.assertEqual({row['id'] for row in response.json['leads']}, {own})
        self.assertEqual(self.client.get(
            f'/api/leads/{hidden}'
        ).status_code, 404)
        self.assertEqual(self.client.put(
            f'/api/leads/{own}', json={'created_by': self.ids['admin']}
        ).status_code, 400)

    def test_supervisor_configuration_is_admin_only_and_validated(self):
        for name in ('exec1', 'tl1'):
            self.as_user(name)
            self.assertEqual(self.client.post(
                f"/api/manager/users/{self.ids['exec1']}/supervisor",
                json={'supervisor_user_id': self.ids['tl1']},
            ).status_code, 403)
        for executive, supervisor in (
                ('exec1', 'exec1'), ('exec1', 'admin'), ('tl1', 'tl2')):
            self.assertEqual(self.assign(
                executive, supervisor
            ).status_code, 400)
        self.assertEqual(self.assign('exec1', 'tl1').status_code, 200)
        self.assertEqual(self.assign('exec1', None).status_code, 200)

    def test_inactive_and_deleted_supervisors_do_not_grant_team_access(self):
        lead_id = self.create('exec1')
        self.assign('exec1', 'tl1')
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'UPDATE users SET is_active = 0 WHERE id = ?',
                    (self.ids['tl1'],),
                )
            self.as_user('tl1')
            self.assertEqual(self.client.get('/api/leads').status_code, 401)
            self.assertEqual(self.assign('exec2', 'tl1').status_code, 400)
            with connection:
                connection.execute('DELETE FROM users WHERE id = ?',
                                   (self.ids['tl1'],))
            self.assertIsNone(connection.execute(
                'SELECT supervisor_user_id FROM users WHERE id = ?',
                (self.ids['exec1'],),
            ).fetchone()[0])
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('DELETE FROM users WHERE id = ?',
                                   (self.ids['exec1'],))
        finally:
            connection.close()
        self.assertEqual(self.visible('exec1'), {lead_id})

    def test_authentication_validation_and_database_self_supervision(self):
        self.as_user(None)
        self.assertEqual(self.client.get('/api/leads').status_code, 401)
        self.assertEqual(
            self.client.post('/api/leads', json={}).status_code, 401
        )
        self.as_user('exec1')
        for data in ({}, {'name': ''}, {'name': 'a' * 151}, ['invalid']):
            self.assertEqual(self.client.post(
                '/api/leads', json=data
            ).status_code, 400)
        connection = database.get_db()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    'UPDATE users SET supervisor_user_id = id WHERE id = ?',
                    (self.ids['exec1'],),
                )
        finally:
            connection.close()

    def test_reassignment_and_inactive_executive_remove_team_visibility(self):
        lead_id = self.create('exec1')
        self.assign('exec1', 'tl1')
        self.assertIn(lead_id, self.visible('tl1'))
        self.assign('exec1', 'tl2')
        self.assertNotIn(lead_id, self.visible('tl1'))
        self.assertIn(lead_id, self.visible('tl2'))
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'UPDATE users SET is_active = 0 WHERE id = ?',
                    (self.ids['exec1'],),
                )
        finally:
            connection.close()
        self.assertNotIn(lead_id, self.visible('tl2'))
        self.assertIn(lead_id, self.visible('admin'))

    def test_existing_permission_grants_can_authorize_additional_access(self):
        lead_id = self.create('tl2')
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'INSERT INTO role_permissions VALUES (?, ?)',
                    ('sales_executive', 'leads.view_all'),
                )
        finally:
            connection.close()
        self.assertIn(lead_id, self.visible('exec1'))

    def test_allowed_edits_preserve_ownership_and_creation(self):
        uid = self.create('exec1')
        original = self.client.get(f'/api/leads/{uid}').json['lead']
        self.assign('exec1', 'tl1')
        for name in ('exec1', 'tl1', 'admin', 'manager'):
            self.as_user(name)
            response = self.client.put(f'/api/leads/{uid}', json={
                'name': 'Updated client', 'company': name,
                'email': 'client@example.com', 'phone': '+12345678901',
                'notes': 'Updated notes',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['lead']['created_by'],
                             original['created_by'])
            self.assertEqual(response.json['lead']['created_at'],
                             original['created_at'])
            self.assertEqual(response.json['lead']['company'], name)

    def test_unauthorized_and_shared_edits_are_denied(self):
        uid = self.create('exec1')
        self.assign('exec1', 'tl1')
        for name in ('exec2', 'tl2'):
            self.as_user(name)
            self.assertEqual(self.client.put(
                f'/api/leads/{uid}', json={'name': 'Forbidden'}
            ).status_code, 404)
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'INSERT INTO client_lead_shares (lead_id, user_id) '
                    'VALUES (?, ?)',
                    (uid, self.ids['exec2']),
                )
        finally:
            connection.close()
        self.as_user('exec2')
        self.assertFalse(self.client.get(
            f'/api/leads/{uid}'
        ).json['lead']['can_edit'])
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Forbidden'}
        ).status_code, 403)
        self.as_user('admin')
        self.assertEqual(self.client.get(
            f'/api/leads/{uid}'
        ).json['lead']['name'], 'exec1')

    def test_edit_reassignment_metadata_and_no_delete(self):
        uid = self.create('exec1')
        self.assign('exec1', 'tl1')
        self.assign('exec1', 'tl2')
        self.as_user('tl1')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Forbidden'}
        ).status_code, 404)
        self.as_user('exec1')
        for field in ('created_by', 'created_at', 'id'):
            self.assertEqual(self.client.put(f'/api/leads/{uid}', json={
                'name': 'Spoofed', field: self.ids['admin'],
            }).status_code, 400)
        self.assertEqual(self.client.delete(
            f'/api/leads/{uid}'
        ).status_code, 405)
        self.as_user(None)
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Forbidden'}
        ).status_code, 401)


if __name__ == '__main__':
    unittest.main()
