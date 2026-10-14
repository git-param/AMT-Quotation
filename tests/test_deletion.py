"""Management-only deletion, retained relationships and descendant access."""

import sqlite3
import unittest

import test_enquiries
from backend import database
from backend.enquiries.lines import bp as lines_bp
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database


class DeletionTests(unittest.TestCase):
    """Exercise all deletion APIs with real ownership and sharing rules."""

    as_user = test_enquiries.EnquiryTests.as_user
    create = test_enquiries.EnquiryTests.create
    assign = test_enquiries.EnquiryTests.assign
    enquiry = test_enquiries.EnquiryTests.enquiry

    def setUp(self):
        test_enquiries.EnquiryTests.setUp(self)
        self.client.application.register_blueprint(lines_bp)
        self.parent = self.create('exec1')
        self.enquiry_id = self.enquiry(self.parent).json['enquiry']['id']
        self.enquiry_path = f'/api/enquiries/{self.enquiry_id}'
        self.lines_path = self.enquiry_path + '/lines'
        self.line_id = self.client.get(self.lines_path).json['lines'][0]['id']
        self.line_path = self.lines_path + f'/{self.line_id}'
        self.lead_path = f'/api/leads/{self.parent}'

    def test_executives_and_anonymous_users_cannot_delete_any_record(self):
        for path in (self.lead_path, self.enquiry_path, self.line_path):
            self.as_user('exec1')
            self.assertEqual(self.client.delete(path).status_code, 403)
            self.as_user(None)
            self.assertEqual(self.client.delete(path).status_code, 401)
        self.as_user('exec1')
        self.assertFalse(
            self.client.get(self.lead_path).json['lead']['can_delete']
        )
        self.assertFalse(self.client.get(
            self.enquiry_path
        ).json['enquiry']['can_delete'])
        self.assertEqual(
            self.client.get(self.lines_path).json['lines'][0]['id'],
            self.line_id,
        )

    def test_edit_share_does_not_grant_deletion(self):
        self.as_user('admin')
        self.assertEqual(self.client.post(
            f'/api/client-access/{self.parent}/grant', json={
                'user_id': self.ids['exec2'], 'access_level': 'EDIT',
            },
        ).status_code, 200)
        self.as_user('exec2')
        for path in (self.lead_path, self.enquiry_path, self.line_path):
            self.assertEqual(self.client.delete(path).status_code, 403)
        self.assertEqual(self.client.put(self.line_path, json={
            'quantity': '2',
        }).status_code, 200)

    def test_tl_team_deletion_and_cross_team_isolation(self):
        self.assign('exec1', 'tl1')
        self.as_user('tl2')
        for path in (self.lead_path, self.enquiry_path, self.line_path):
            self.assertEqual(self.client.delete(path).status_code, 404)
        self.as_user('tl1')
        self.assertTrue(
            self.client.get(self.lead_path).json['lead']['can_delete']
        )
        self.assertEqual(self.client.delete(self.line_path).status_code, 200)
        history = self.client.get(self.line_path).json['revisions']
        self.assertEqual(history[-1]['actor_user_id'], self.ids['tl1'])
        self.assertEqual(history[-1]['action'], 'remove')
        self.assertEqual(
            self.client.delete(self.enquiry_path).status_code, 200
        )
        self.assertEqual(
            self.client.get(self.lead_path).json['lead']['enquiry_count'], 0
        )
        self.assertEqual(self.client.delete(self.lead_path).status_code, 200)

    def test_tl_can_delete_own_records_and_loses_team_access_immediately(self):
        self.assign('exec1', 'tl1')
        self.assign('exec1', None)
        self.as_user('tl1')
        self.assertEqual(
            self.client.delete(self.enquiry_path).status_code, 404
        )
        own = self.create('tl1')
        enquiry = self.enquiry(own, 'TL-OWN').json['enquiry']['id']
        self.assertEqual(self.client.delete(
            f'/api/enquiries/{enquiry}'
        ).status_code, 200)
        self.assertEqual(
            self.client.delete(f'/api/leads/{own}').status_code, 200
        )

    def test_other_tl_and_inactive_executive_are_outside_delete_scope(self):
        other = self.create('tl2')
        self.as_user('tl1')
        self.assertEqual(self.client.delete(f'/api/leads/{other}').status_code,
                         404)
        self.assign('exec1', 'tl1')
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'UPDATE users SET is_active = 0 WHERE id = ?',
                    (self.ids['exec1'],),
                )
        finally:
            connection.close()
        self.as_user('tl1')
        self.assertEqual(self.client.delete(self.lead_path).status_code, 404)

    def test_enquiry_delete_hides_children_and_preserves_metadata(self):
        self.as_user('manager')
        original = self.client.get(self.enquiry_path).json['enquiry']
        self.assertEqual(
            self.client.delete(self.enquiry_path).status_code, 200
        )
        self.assertEqual(self.client.get('/api/enquiries').json['total'], 0)
        for path in (self.enquiry_path, self.lines_path, self.line_path):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.put(self.line_path, json={
            'quantity': '2',
        }).status_code, 404)
        self.assertEqual(self.client.post(self.enquiry_path + '/sku-lookup',
                                         json={'sku': 'INITIAL'}).status_code,
                         404)
        self.as_user('exec1')
        self.assertEqual(self.enquiry(self.parent).status_code, 409)
        connection = database.get_db()
        try:
            row = connection.execute(
                'SELECT * FROM client_enquiries WHERE id = ?',
                (self.enquiry_id,),
            ).fetchone()
            for field in ('client_id', 'created_by', 'created_at',
                          'reference'):
                self.assertEqual(row[field], original[field])
            self.assertEqual(row['deleted_by'], self.ids['manager'])
            self.assertIsNotNone(row['deleted_at'])
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM enquiry_sku_lines WHERE enquiry_id = ?',
                (self.enquiry_id,),
            ).fetchone()[0], 1)
        finally:
            connection.close()

    def test_client_delete_hides_tree_and_preserves_relationships(self):
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        })
        original = self.client.get(self.lead_path).json['lead']
        self.assertEqual(self.client.delete(self.lead_path).status_code, 200)
        for name in ('admin', 'exec1', 'exec2', 'tl1', 'manager'):
            self.as_user(name)
            self.assertEqual(self.client.get('/api/leads').json['total'], 0)
            self.assertEqual(
                self.client.get('/api/enquiries').json['total'], 0
            )
            for path in (self.lead_path, self.enquiry_path, self.lines_path):
                self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.put(self.line_path, json={
                'quantity': '2',
            }).status_code, 404)
            self.assertEqual(self.client.put(self.lead_path, json={
                'notes': 'Cannot restore through editing',
            }).status_code, 404)
        self.as_user('admin')
        self.assertEqual(
            self.client.post(self.lead_path + '/activate').status_code, 404
        )
        self.assertEqual(
            self.client.get('/api/client-access').json['leads'], []
        )
        self.assertEqual(self.client.get(
            f'/api/client-access/{self.parent}'
        ).status_code, 404)
        self.assertEqual(self.client.post('/api/enquiries/sku-lookup', json={
            'client_id': self.parent, 'skus': ['INITIAL'], 'currency': 'USD',
        }).status_code, 404)
        connection = database.get_db()
        try:
            client = connection.execute(
                'SELECT * FROM client_leads WHERE id = ?', (self.parent,),
            ).fetchone()
            for field in ('created_by', 'created_at'):
                self.assertEqual(client[field], original[field])
            self.assertEqual(client['deleted_by'], self.ids['admin'])
            self.assertIsNotNone(client['deleted_at'])
            for table in ('client_enquiries', 'enquiry_sku_lines',
                          'client_lead_shares', 'client_share_events',
                          'client_address_history'):
                self.assertGreater(connection.execute(
                    'SELECT COUNT(*) FROM ' + table
                ).fetchone()[0], 0)
            self.assertEqual(
                connection.execute('PRAGMA foreign_key_check').fetchall(), []
            )
        finally:
            connection.close()

    def test_migration_thirteen_preserves_version_twelve_records(self):
        path = database.DB_PATH + '.upgrade.db'
        migrate_database(path, MIGRATIONS[:12])
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute(
                    'INSERT INTO users(username,password_hash) '
                    "VALUES('u','test')"
                )
                connection.execute(
                    "INSERT INTO client_leads(name,created_by) VALUES('c',1)"
                )
                connection.execute(
                    'INSERT INTO client_enquiries(client_id,reference,'
                    'enquiry_date,subject,created_by,updated_by) '
                    "VALUES(1,'HISTORY','2026-10-14','Saved',1,1)"
                )
            before = connection.execute(
                'SELECT * FROM client_enquiries'
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), [13, 14])
        self.assertEqual(migrate_database(path), [])
        connection = sqlite3.connect(path)
        try:
            after = connection.execute(
                'SELECT * FROM client_enquiries'
            ).fetchall()
            self.assertEqual([row[:-2] for row in after], before)
            self.assertEqual(after[0][-2:], (None, None))
        finally:
            connection.close()
