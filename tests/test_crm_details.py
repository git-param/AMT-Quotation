"""Test CRM validation, duplicates, lifecycle, and sharing authorization."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import unittest

import test_leads
from backend import database
from backend.client_access.routes import bp
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database


class CRMTests(unittest.TestCase):
    """Reuse the isolated client/supervisor fixture and all existing routes."""

    as_user = test_leads.LeadTests.as_user
    create = test_leads.LeadTests.create
    assign = test_leads.LeadTests.assign

    def setUp(self):
        test_leads.LeadTests.setUp(self)
        self.client.application.register_blueprint(bp)

    def full_details(self):
        return {
            'name': 'Alice', 'company': 'Example Marine',
            'business_details': 'Ship repair', 'status': 'prospect',
            'email': 'SALES@EXAMPLE.COM', 'phone': '+91 (98765) 43210',
            'emails': ['accounts@example.com'], 'phones': ['+12345678901'],
            'contact_persons': [{'name': 'Bob', 'email': 'bob@example.com',
                                 'phone': '+19876543210'}],
            'billing_address': {'line1': 'Billing street', 'country': 'India'},
            'shipping_address': {'line1': 'Shipping street', 'country': 'USA'},
            'notes': 'Contact during office hours',
        }

    def test_full_fields_round_trip_and_partial_edit_preservation(self):
        self.as_user('exec1')
        response = self.client.post('/api/leads', json=self.full_details())
        self.assertEqual(response.status_code, 201)
        original = response.json['lead']
        self.assertEqual(original['email'], 'sales@example.com')
        self.assertEqual(original['phone'], '+919876543210')
        self.assertEqual(original['contact_persons'][0]['name'], 'Bob')
        uid = original['id']
        response = self.client.put(
            f'/api/leads/{uid}', json={'notes': 'Updated'}
        )
        self.assertEqual(response.status_code, 200)
        result = response.json['lead']
        for field in ('created_by', 'created_at', 'business_details',
                      'billing_address', 'shipping_address', 'contact_persons',
                      'emails', 'phones', 'status'):
            self.assertEqual(result[field], original[field])
        self.assertEqual(result['notes'], 'Updated')

    def test_validation_and_metadata_protection(self):
        self.as_user('exec1')
        changes = (
            {'email': 'invalid'}, {'phone': '+12'}, {'emails': ['invalid']},
            {'phones': ['abc1234567']}, {'status': 'deleted'},
            {'contact_persons': [{'name': ''}]},
            {'billing_address': {'country': 'India'}},
            {'shipping_address': {'line1': 'Road'}},
            {'billing_address': {'line1': 'Road', 'country': 'India',
                                 'created_by': 1}},
            {'business_details': 'x' * 2001}, {'emails': ['']},
            {'created_by': 1}, {'is_active': 0}, {'created_at': 'spoof'},
        )
        for change in changes:
            data = {'name': 'Client', **change}
            self.assertEqual(self.client.post(
                '/api/leads', json=data
            ).status_code, 400)

    def test_duplicates_use_original_owner_and_include_inactive_clients(self):
        self.as_user('exec1')
        uid = self.client.post('/api/leads', json=self.full_details()).json[
            'lead']['id']
        for data in (
                {'name': ' alice ', 'company': 'EXAMPLE MARINE'},
                {'name': 'Other', 'email': 'accounts@example.com'},
                {'name': 'Other', 'phone': '+1 (987) 654-3210'}):
            self.assertEqual(self.client.post(
                '/api/leads', json=data
            ).status_code, 409)
        self.client.post(f'/api/leads/{uid}/deactivate')
        self.assertEqual(self.client.post(
            '/api/leads', json=self.full_details()
        ).status_code, 409)
        self.as_user('exec2')
        self.assertEqual(self.client.post(
            '/api/leads', json=self.full_details()
        ).status_code, 201)

    def test_lifecycle_permissions_and_sharing_history_preservation(self):
        uid = self.create('exec1')
        self.assign('exec1', 'tl1')
        self.as_user('admin')
        self.client.post(f'/api/client-access/{uid}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        })
        before = self.client.get(f'/api/client-access/{uid}').json
        self.as_user('exec2')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'business_details': 'Updated'}
        ).status_code, 200)
        self.assertEqual(self.client.post(
            f'/api/leads/{uid}/deactivate'
        ).status_code, 403)
        self.as_user('tl2')
        self.assertEqual(self.client.post(
            f'/api/leads/{uid}/deactivate'
        ).status_code, 404)
        for actor in ('exec1', 'tl1', 'admin', 'manager'):
            self.as_user(actor)
            self.assertEqual(self.client.post(
                f'/api/leads/{uid}/deactivate'
            ).status_code, 200)
            self.assertFalse(self.client.get(
                f'/api/leads/{uid}'
            ).json['lead']['is_active'])
            self.assertEqual(self.client.post(
                f'/api/leads/{uid}/activate'
            ).status_code, 200)
        self.as_user('admin')
        self.assertEqual(before, self.client.get(
            f'/api/client-access/{uid}'
        ).json)
        self.client.post(f'/api/leads/{uid}/deactivate')
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/grant',
            json={'user_id': self.ids['legacy'], 'access_level': 'VIEW'},
        ).status_code, 400)
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/revoke',
            json={'user_id': self.ids['exec2']},
        ).status_code, 200)
        self.assertEqual(
            self.client.delete(f'/api/leads/{uid}').status_code, 200
        )

    def test_view_share_remains_read_only_for_crm_fields_and_lifecycle(self):
        uid = self.create('exec1')
        self.as_user('admin')
        self.client.post(f'/api/client-access/{uid}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'VIEW',
        })
        self.as_user('exec2')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json=self.full_details()
        ).status_code, 403)
        self.assertEqual(self.client.post(
            f'/api/leads/{uid}/activate'
        ).status_code, 403)

    def test_concurrent_duplicate_creation_is_serialized(self):
        app = self.client.application

        def create(_):
            client = app.test_client()
            with client.session_transaction() as session:
                session['user_id'] = self.ids['exec1']
            return client.post(
                '/api/leads', json={'name': 'Duplicate'}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(create, range(2)))
        self.assertEqual(sorted(statuses), [201, 409])

    def test_version_seven_upgrade_preserves_legacy_records(self):
        path = Path(database.DB_PATH).parent / 'legacy_crm.db'
        migrate_database(path, MIGRATIONS[:7])
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute(
                    "INSERT INTO users (username, password_hash) "
                    "VALUES ('owner', 'test-placeholder')"
                )
                connection.execute(
                    'INSERT INTO client_leads (name, email, created_by) '
                    "VALUES ('Legacy', 'historical-value', 1)"
                )
            original = connection.execute(
                'SELECT * FROM client_leads'
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), [8, 9, 10, 11, 12, 13, 14])
        connection = sqlite3.connect(path)
        try:
            row = connection.execute('SELECT * FROM client_leads').fetchone()
            self.assertEqual(row[:len(original[0])], original[0])
            self.assertEqual(connection.execute(
                'SELECT status, is_active FROM client_leads'
            ).fetchone(), ('lead', 1))
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
