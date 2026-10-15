"""Client enquiry lifecycle, parent permissions and regression tests."""

from pathlib import Path
import sqlite3
import unittest

import test_leads
from backend import database
from backend.client_access.routes import bp as access_bp
from backend.enquiries.routes import bp
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database


class EnquiryTests(unittest.TestCase):
    """Use private clients, distinct teams, and explicit client shares."""

    as_user = test_leads.LeadTests.as_user
    create = test_leads.LeadTests.create
    assign = test_leads.LeadTests.assign

    def setUp(self):
        test_leads.LeadTests.setUp(self)
        self.client.application.register_blueprint(access_bp)
        self.client.application.register_blueprint(bp)

    def enquiry(self, client_id, reference='ENQ-001'):
        return self.client.post('/api/enquiries', json={
            'client_id': client_id, 'reference': reference,
            'enquiry_date': '2026-10-14', 'subject': 'Marine parts request',
            'description': 'Please provide availability.',
            'deal_currency': 'USD',
            'lines': [{'sku': 'INITIAL', 'description': 'Initial enquiry item',
                       'quantity': '1', 'unit_price': '0', 'currency': 'USD'}],
        })

    def test_multiple_enquiries_detail_edit_and_immutable_relationships(self):
        client_id = self.create('exec1')
        first = self.enquiry(client_id)
        self.assertEqual(first.status_code, 201)
        original = first.json['enquiry']
        self.assertEqual(self.enquiry(client_id, 'ENQ-002').status_code, 201)
        uid = original['id']
        response = self.client.put(f'/api/enquiries/{uid}', json={
            'subject': 'Updated request', 'status': 'in_progress',
        })
        self.assertEqual(response.status_code, 200)
        result = response.json['enquiry']
        for field in ('created_by', 'created_at', 'client_id', 'reference'):
            self.assertEqual(result[field], original[field])
        self.assertEqual(result['updated_by'], self.ids['exec1'])
        self.assertEqual(result['subject'], 'Updated request')
        self.assertEqual(self.client.get(
            '/api/enquiries', query_string={'client_id': client_id}
        ).json['total'], 2)
        self.assertEqual(self.client.delete(
            f'/api/enquiries/{uid}'
        ).status_code, 403)
        for field in ('created_by', 'created_at', 'client_id', 'updated_by'):
            self.assertEqual(self.client.put(
                f'/api/enquiries/{uid}', json={field: self.ids['exec2']}
            ).status_code, 400)

    def test_tl_admin_legacy_permissions_and_cross_tl_isolation(self):
        client_id = self.create('exec1')
        uid = self.enquiry(client_id).json['enquiry']['id']
        self.assign('exec1', 'tl1')
        self.as_user('tl2')
        self.assertEqual(self.client.get('/api/enquiries').json['total'], 0)
        self.assertEqual(self.client.get(
            f'/api/enquiries/{uid}'
        ).status_code, 404)
        self.assertEqual(self.enquiry(client_id, 'FORBIDDEN').status_code, 404)
        for name in ('tl1', 'admin', 'manager'):
            self.as_user(name)
            self.assertEqual(self.enquiry(
                client_id, 'ENQ-' + name
            ).status_code, 201)
            self.assertEqual(self.client.put(
                f'/api/enquiries/{uid}', json={'description': name}
            ).status_code, 200)
        self.as_user('exec2')
        self.assertEqual(self.client.get(
            '/api/enquiries', query_string={'client_id': client_id}
        ).json['total'], 0)

    def test_view_edit_share_and_revocation_apply_to_enquiries(self):
        client_id = self.create('exec1')
        uid = self.enquiry(client_id).json['enquiry']['id']
        self.as_user('admin')
        self.client.post(f'/api/client-access/{client_id}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'VIEW',
        })
        self.as_user('exec2')
        self.assertEqual(self.client.get('/api/enquiries').json['total'], 1)
        self.assertEqual(self.enquiry(client_id, 'READONLY').status_code, 403)
        self.assertEqual(self.client.put(
            f'/api/enquiries/{uid}', json={'subject': 'Denied'}
        ).status_code, 403)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{client_id}/level', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        })
        self.as_user('exec2')
        shared_id = self.enquiry(
            client_id, 'SHARED-CREATE'
        ).json['enquiry']['id']
        self.assertEqual(self.client.put(
            f'/api/enquiries/{uid}', json={'description': 'Shared edit'}
        ).status_code, 200)
        self.assertEqual(self.client.post(
            f'/api/client-access/{client_id}/grant',
            json={'user_id': self.ids['legacy']},
        ).status_code, 403)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{client_id}/revoke', json={
            'user_id': self.ids['exec2'],
        })
        self.as_user('exec2')
        self.assertEqual(self.client.get('/api/enquiries').json['total'], 0)
        self.assertEqual(self.client.get(
            f'/api/enquiries/{shared_id}'
        ).status_code, 404)
        self.assertEqual(self.client.put(
            f'/api/enquiries/{shared_id}', json={'description': 'Denied'}
        ).status_code, 404)

    def test_validation_duplicate_references_and_update_conflicts(self):
        client_id = self.create('exec1')
        uid = self.enquiry(client_id).json['enquiry']['id']
        self.assertEqual(self.enquiry(client_id, 'enq-001').status_code, 409)
        second = self.enquiry(client_id, 'OTHER').json['enquiry']['id']
        self.assertEqual(self.client.put(
            f'/api/enquiries/{second}', json={'reference': 'ENQ-001'}
        ).status_code, 409)
        for data in ({}, {'client_id': True}, {'client_id': -1},
                     {'client_id': client_id, 'reference': ''},
                     {'client_id': client_id, 'reference': 'X', 'subject': 'Y',
                      'enquiry_date': '2026-02-30'},
                     {'client_id': client_id, 'reference': 'X', 'subject': 'Y',
                      'enquiry_date': '2026-10-14', 'status': 'deleted'}):
            self.assertEqual(self.client.post(
                '/api/enquiries', json=data
            ).status_code, 400)
        self.assertEqual(self.client.get(
            f'/api/enquiries/{uid}'
        ).json['enquiry']['reference'], 'ENQ-001')

    def test_client_counts_and_view_all_are_limited_to_selected_client(self):
        first = self.create('exec1')
        second = self.client.post('/api/leads', json={
            'name': 'Second client',
        }).json['lead']['id']
        first_ids = {
            self.enquiry(first, reference).json['enquiry']['id']
            for reference in ('FIRST-1', 'FIRST-2')
        }
        self.enquiry(second, 'SECOND-1')
        clients = self.client.get('/api/leads').json['leads']
        counts = {client['id']: client['enquiry_count'] for client in clients}
        self.assertEqual(counts, {first: 2, second: 1})
        selected = self.client.get('/api/enquiries', query_string={
            'client_id': first, 'page_size': 1,
        }).json
        self.assertEqual(selected['total'], 2)
        self.assertEqual(selected['enquiries'][0]['client_id'], first)
        self.assertIn(selected['enquiries'][0]['id'], first_ids)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{first}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'VIEW',
        })
        self.as_user('exec2')
        visible = self.client.get('/api/leads').json['leads']
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]['enquiry_count'], 2)
        hidden = self.client.get('/api/enquiries', query_string={
            'client_id': second,
        }).json
        self.assertEqual(hidden['total'], 0)

    def test_scoped_search_filters_pagination_and_inactive_history(self):
        client_id = self.create('exec1')
        for number in range(3):
            self.enquiry(client_id, f'PART-{number}')
        self.client.post(f'/api/leads/{client_id}/deactivate')
        self.assertEqual(self.enquiry(client_id, 'INACTIVE').status_code, 400)
        response = self.client.get('/api/enquiries', query_string={
            'q': 'part', 'page_size': 2,
            'sort': 'reference', 'direction': 'asc',
        })
        self.assertEqual(response.json['total'], 3)
        self.assertEqual(response.json['pages'], 2)
        self.assertEqual(len(response.json['enquiries']), 2)
        self.assertEqual(self.client.get('/api/enquiries', query_string={
            'q': 'part', 'page_size': 2, 'page': 2,
        }).json['total'], 3)
        self.as_user('exec2')
        self.assertEqual(self.client.get('/api/enquiries', query_string={
            'q': 'part', 'client_id': client_id, 'creator': self.ids['exec1'],
        }).json['total'], 0)
        for filters in ({'page_size': 101}, {'status': 'bad'},
                        {'sort': 'id;DROP TABLE users'}, {'client_id': -1}):
            self.assertEqual(self.client.get(
                '/api/enquiries', query_string=filters
            ).status_code, 400)

    def test_anonymous_access_and_restrictive_history_relationships(self):
        client_id = self.create('exec1')
        uid = self.enquiry(client_id).json['enquiry']['id']
        self.as_user(None)
        self.assertEqual(self.client.get('/api/enquiries').status_code, 401)
        self.assertEqual(self.client.get(
            f'/api/enquiries/{uid}'
        ).status_code, 401)
        self.assertEqual(self.enquiry(client_id).status_code, 401)
        connection = database.get_db()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('DELETE FROM client_leads WHERE id = ?',
                                   (client_id,))
        finally:
            connection.close()

    def test_version_nine_upgrade_keeps_client_and_address_records(self):
        path = Path(database.DB_PATH).parent / 'legacy_enquiries.db'
        migrate_database(path, MIGRATIONS[:9])
        connection = sqlite3.connect(path)
        try:
            before = connection.execute(
                'SELECT COUNT(*) FROM client_leads'
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), list(range(10, len(MIGRATIONS) + 1)))
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM client_leads'
            ).fetchone()[0], before)
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM client_enquiries'
            ).fetchone()[0], 0)
            self.assertEqual(
                connection.execute('PRAGMA foreign_key_check').fetchall(), []
            )
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
