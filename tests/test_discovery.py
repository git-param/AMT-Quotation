"""Client discovery, source integration, address history and scope tests."""

from pathlib import Path
import sqlite3
import unittest

import test_leads
from backend import database
from backend.client_access.routes import bp
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database


class DiscoveryTests(unittest.TestCase):
    """Exercise list/count/detail with isolated private and shared clients."""

    as_user = test_leads.LeadTests.as_user
    create = test_leads.LeadTests.create
    assign = test_leads.LeadTests.assign

    def setUp(self):
        test_leads.LeadTests.setUp(self)
        self.client.application.register_blueprint(bp)

    def listing(self, **filters):
        response = self.client.get('/api/leads', query_string=filters)
        self.assertEqual(response.status_code, 200)
        return response.json

    def test_search_contacts_company_email_phone_and_literal_wildcards(self):
        self.as_user('exec1')
        uid = self.client.post('/api/leads', json={
            'name': 'Client', 'company': '100% Marine',
            'emails': ['accounts@example.com'], 'phones': ['+12345678901'],
            'contact_persons': [{'name': 'Alice', 'email': 'alice@example.com',
                                 'phone': '+919876543210'}],
        }).json['lead']['id']
        for query in ('marine', 'Alice', 'accounts@example.com',
                      'alice@example.com', '+1 (234) 567-8901', '100%',
                      '+91 98765 43210'):
            self.assertEqual(self.listing(q=query)['total'], 1)
        self.assertEqual(self.listing(q='_')['total'], 0)
        self.as_user('exec2')
        for query in ('marine', 'alice@example.com'):
            self.assertEqual(self.listing(q=query)['total'], 0)
        self.assertEqual(self.client.get(f'/api/leads/{uid}').status_code, 404)

    def test_pagination_sort_counts_and_creator_filters_are_scoped(self):
        self.as_user('exec1')
        for name in ('Zulu', 'Bravo', 'Alpha'):
            self.client.post(
                '/api/leads', json={'name': name, 'company': name}
            )
        hidden = self.create('tl2')
        self.as_user('exec1')
        first = self.listing(
            page=1, page_size=2, sort='company', direction='asc'
        )
        second = self.listing(
            page=2, page_size=2, sort='company', direction='asc'
        )
        self.assertEqual(first['total'], 3)
        self.assertEqual(first['pages'], 2)
        self.assertEqual(
            [c['name'] for c in first['leads']], ['Alpha', 'Bravo']
        )
        self.assertEqual([c['name'] for c in second['leads']], ['Zulu'])
        self.assertNotIn(hidden, {c['id'] for c in first['leads']})
        self.assertEqual(self.listing(creator=self.ids['tl2'])['total'], 0)
        self.assertEqual(self.listing(ownership='others')['total'], 0)
        options = self.client.get('/api/leads/options').json
        self.assertEqual({u['id'] for u in options['creators']},
                         {self.ids['exec1']})
        self.assign('exec1', 'tl1')
        self.as_user('tl1')
        self.assertEqual(self.listing()['total'], 3)
        self.assertEqual(self.listing(creator=self.ids['tl2'])['total'], 0)
        for role in ('admin', 'manager'):
            self.as_user(role)
            self.assertEqual(self.listing()['total'], 4)

    def test_filters_shares_revocation_and_inactive_clients(self):
        own = self.create('exec2')
        uid = self.create('exec1')
        self.as_user('admin')
        self.client.post(f'/api/client-access/{uid}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'VIEW',
        })
        self.as_user('exec1')
        self.client.put(f'/api/leads/{uid}', json={'status': 'customer'})
        self.client.post(f'/api/leads/{uid}/deactivate')
        self.as_user('exec2')
        result = self.listing(access='VIEW', active='inactive',
                              status='customer', ownership='others')
        self.assertEqual(result['total'], 1)
        self.assertFalse(result['leads'][0]['can_edit'])
        self.assertEqual(self.listing(ownership='own')['leads'][0]['id'], own)
        self.assertEqual(self.listing(access='EDIT')['total'], 0)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{uid}/revoke', json={
            'user_id': self.ids['exec2'],
        })
        self.as_user('exec2')
        self.assertEqual(self.listing(access='shared')['total'], 0)

    def test_source_link_validation_deactivation_and_filter(self):
        connection = database.get_db()
        try:
            with connection:
                cursor = connection.execute(
                    'INSERT INTO enquiry_sources '
                    '(code,name,source_type,contact_value) '
                    "VALUES ('inbox','Sales inbox','email',"
                    "'sales@example.com')"
                )
                source = cursor.lastrowid
        finally:
            connection.close()
        self.as_user('exec1')
        self.assertEqual(self.client.get(
            '/api/leads/options'
        ).json['sources'][0]['id'], source)
        uid = self.client.post('/api/leads', json={
            'name': 'Source client', 'enquiry_source_id': source,
        }).json['lead']['id']
        self.assertEqual(self.listing(source=source)['total'], 1)
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'UPDATE enquiry_sources SET is_active = 0 WHERE id = ?',
                    (source,),
                )
        finally:
            connection.close()
        self.assertEqual(
            self.client.get('/api/leads/options').json['sources'], []
        )
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'notes': 'Retain historical source'}
        ).status_code, 200)
        self.assertEqual(self.client.post('/api/leads', json={
            'name': 'Other source client', 'enquiry_source_id': source,
        }).status_code, 400)
        self.assertEqual(self.client.post('/api/leads', json={
            'name': 'Missing source', 'enquiry_source_id': 99999,
        }).status_code, 400)
        self.as_user('exec2')
        self.assertEqual(self.listing(source=source)['total'], 0)

    def test_addresses_history_and_order_address_separation(self):
        self.as_user('exec1')
        old = {'line1': 'Original default', 'country': 'India'}
        uid = self.client.post('/api/leads', json={
            'name': 'Address client', 'billing_address': old,
            'shipping_address': old,
        }).json['lead']['id']
        original = self.client.get(f'/api/leads/{uid}').json
        new = {'line1': 'New default', 'country': 'India'}
        self.assertEqual(self.client.put(f'/api/leads/{uid}', json={
            'shipping_address': new,
        }).status_code, 200)
        detail = self.client.get(f'/api/leads/{uid}').json
        self.assertEqual(detail['lead']['billing_address'], old)
        self.assertEqual(detail['lead']['shipping_address'], new)
        self.assertEqual(len(detail['address_history']), 2)
        self.assertEqual(
            detail['address_history'][-1]['default_shipping_address'], old
        )
        self.assertEqual(original['lead']['created_at'],
                         detail['lead']['created_at'])
        self.assertEqual(self.client.put(f'/api/leads/{uid}', json={
            'order_shipping_address': {
                'line1': 'Order only', 'country': 'USA'
            },
        }).status_code, 400)
        self.client.put(
            f'/api/leads/{uid}', json={'notes': 'No address change'}
        )
        self.assertEqual(len(self.client.get(
            f'/api/leads/{uid}'
        ).json['address_history']), 2)
        self.as_user('exec2')
        self.assertEqual(self.client.get(f'/api/leads/{uid}').status_code, 404)

    def test_invalid_discovery_inputs_and_anonymous_options(self):
        self.as_user('exec1')
        for filters in ({'page': 0}, {'page_size': 101}, {'page': 'bad'},
                        {'sort': 'name;DROP TABLE users'},
                        {'direction': 'bad'},
                        {'status': 'bad'}, {'ownership': 'all; OR 1=1'},
                        {'access': 'admin'}, {'creator': -1},
                        {'source': 'bad'}):
            self.assertEqual(self.client.get(
                '/api/leads', query_string=filters
            ).status_code, 400)
        self.as_user(None)
        self.assertEqual(
            self.client.get('/api/leads/options').status_code, 401
        )

    def test_version_eight_upgrade_preserves_address_baseline(self):
        path = Path(database.DB_PATH).parent / 'legacy_discovery.db'
        migrate_database(path, MIGRATIONS[:8])
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute(
                    "INSERT INTO users (username,password_hash) "
                    "VALUES ('owner','test-placeholder')"
                )
                connection.execute(
                    'INSERT INTO client_leads (name,created_by) '
                    "VALUES ('Existing',1)"
                )
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), [9, 10])
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute(
                'SELECT client_id, recorded_by FROM client_address_history'
            ).fetchone(), (1, None))
            self.assertIsNone(connection.execute(
                'SELECT enquiry_source_id FROM client_leads'
            ).fetchone()[0])
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
