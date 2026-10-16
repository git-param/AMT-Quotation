"""Test decimal lines, history, lookup, and enquiry permissions."""

from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_enquiries
from backend import database
from backend.enquiries.lines import bp
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database


class LineTests(unittest.TestCase):
    """Exercise enquiry lines through their parent client permissions."""

    as_user = test_enquiries.EnquiryTests.as_user
    create = test_enquiries.EnquiryTests.create
    assign = test_enquiries.EnquiryTests.assign
    enquiry = test_enquiries.EnquiryTests.enquiry

    def setUp(self):
        test_enquiries.EnquiryTests.setUp(self)
        self.client.application.register_blueprint(bp)
        self.parent = self.create('exec1')
        self.enquiry_id = self.enquiry(self.parent).json['enquiry']['id']
        self.path = f'/api/enquiries/{self.enquiry_id}/lines'
        # Creation now requires an initial line; isolate individual-line tests.
        initial = self.client.get(self.path).json['lines']
        self.as_user('admin')
        for line in initial:
            self.client.delete(self.path + f"/{line['id']}")
        self.as_user('exec1')

    def add(self, **overrides):
        data = {'sku': 'SKU-001', 'description': 'Marine spare',
                'quantity': '1', 'unit_price': '1.00', 'currency': 'USD'}
        data.update(overrides)
        return self.client.post(self.path, json=data)

    def test_decimal_totals_mixed_currencies_and_edit_identity(self):
        line = self.add().json['line']
        self.assertEqual(line['line_total'], '1.00')
        self.add(quantity='1', unit_price='0.20')
        self.add(quantity='2', unit_price='5', currency='INR')
        self.assertEqual(self.client.get(self.path).json['subtotals'],
                         {'USD': '1.20', 'INR': '10.00'})
        response = self.client.put(self.path + f"/{line['id']}", json={
            'description': 'Updated description', 'unit_price': '2.00',
        })
        self.assertEqual(response.status_code, 200)
        updated = response.json['line']
        for field in ('id', 'enquiry_id', 'created_by', 'created_at'):
            self.assertEqual(updated[field], line[field])
        history = self.client.get(
            self.path + f"/{line['id']}"
        ).json['revisions']
        self.assertEqual([r['action'] for r in history], ['create', 'edit'])
        self.assertEqual(history[0]['snapshot']['unit_price'], '1.00')
        self.assertEqual(updated['line_total'], '2.00')

    def test_removal_retains_history_parent_and_original_records(self):
        line_id = self.add().json['line']['id']
        self.as_user('admin')
        self.assertEqual(self.client.delete(
            self.path + f'/{line_id}'
        ).status_code, 200)
        self.assertEqual(self.client.get(self.path).json['lines'], [])
        self.assertEqual(self.client.get(self.path).json['subtotals'], {})
        removed = self.client.get(self.path + f'/{line_id}').json
        self.assertFalse(removed['line']['is_active'])
        self.assertEqual(removed['revisions'][-1]['action'], 'remove')
        self.assertEqual(self.client.put(
            self.path + f'/{line_id}', json={'quantity': '2'}
        ).status_code, 404)
        self.assertEqual(self.client.get(
            f'/api/enquiries/{self.enquiry_id}'
        ).status_code, 200)
        self.assertEqual(
            self.client.get(f'/api/leads/{self.parent}').status_code, 200
        )

    def test_whole_quantities_and_legacy_fraction_preservation(self):
        for quantity in ('1.5', '0.5', '1.001'):
            self.assertEqual(self.add(quantity=quantity).status_code, 400)
        line = self.add(quantity='2.000').json['line']
        self.assertEqual(line['quantity'], '2')
        endpoint = self.path + f"/{line['id']}"
        self.assertEqual(self.client.put(endpoint, json={
            'quantity': '2.5',
        }).status_code, 400)
        self.assertEqual(
            self.client.get(endpoint).json['line']['quantity'], '2'
        )
        # Simulate a record saved before whole-number entry was required.
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'UPDATE enquiry_sku_lines SET quantity_milli = 1005 '
                    'WHERE id = ?', (line['id'],),
                )
        finally:
            connection.close()
        historical = self.client.get(endpoint).json['line']
        self.assertEqual(historical['quantity'], '1.005')
        self.assertEqual(historical['line_total'], '1.01')
        updated = self.client.put(endpoint, json={
            'unit_price': '2.00',
        }).json['line']
        self.assertEqual(updated['quantity'], '1.005')
        self.assertEqual(updated['line_total'], '2.01')

    def test_numeric_validation_and_untrusted_metadata_totals(self):
        for fields in ({'quantity': '0'}, {'quantity': '-1'},
                       {'quantity': '0.0001'}, {'quantity': True},
                       {'quantity': 'NaN'}, {'quantity': '1e3'},
                       {'unit_price': '-0.01'}, {'unit_price': '1.001'},
                       {'unit_price': 'Infinity'}, {'currency': 'EUR'},
                       {'sku': ''}, {'description': ''},
                       {'line_total': '999'}, {'enquiry_id': 999},
                       {'created_by': self.ids['admin']},
                       {'quantity': '1000000'}, {'unit_price': '1000000000'}):
            self.assertEqual(self.add(**fields).status_code, 400)
        self.assertEqual(self.add(unit_price='0').status_code, 201)

    def test_view_edit_revocation_and_tl_authority(self):
        line_id = self.add().json['line']['id']
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'VIEW',
        })
        self.as_user('exec2')
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertEqual(self.add().status_code, 403)
        self.assertEqual(self.client.put(
            self.path + f'/{line_id}', json={'quantity': '2'}
        ).status_code, 403)
        self.assertEqual(self.client.delete(
            self.path + f'/{line_id}'
        ).status_code, 403)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/level', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        })
        self.as_user('exec2')
        self.assertEqual(self.add().status_code, 201)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/revoke', json={
            'user_id': self.ids['exec2'],
        })
        self.as_user('exec2')
        self.assertEqual(self.client.get(self.path).status_code, 404)
        self.assertEqual(self.add().status_code, 404)
        self.assign('exec1', 'tl1')
        self.as_user('tl1')
        self.assertEqual(self.add().status_code, 201)
        self.as_user('tl2')
        self.assertEqual(self.client.get(self.path).status_code, 404)

    def test_line_parent_isolation_and_anonymous_access(self):
        line_id = self.add().json['line']['id']
        other = self.enquiry(self.parent, 'OTHER').json['enquiry']['id']
        other_path = f'/api/enquiries/{other}/lines/{line_id}'
        self.assertEqual(self.client.get(other_path).status_code, 404)
        self.assertEqual(self.client.put(other_path, json={}).status_code, 404)
        self.assertEqual(self.client.delete(other_path).status_code, 404)
        self.as_user(None)
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(self.add().status_code, 401)

    def test_lookup_draft_cache_reuse_no_automatic_line_changes(self):
        endpoint = f'/api/enquiries/{self.enquiry_id}/sku-lookup'
        with patch('backend.enquiries.lines.lookup_product', return_value={
                'found': True, 'sku': 'SKU-001', 'title': 'Product title',
                'price': 20.0, 'sale_price': 12.5, 'qty': 8}) as lookup:
            response = self.client.post(endpoint, json={'sku': ' SKU-001 '})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['draft']['unit_price'], '12.50')
            lookup.assert_called_once_with('SKU-001')
        self.assertEqual(self.client.get(self.path).json['lines'], [])
        with patch('backend.enquiries.lines.lookup_product',
                   return_value={'found': False}):
            self.assertEqual(self.client.post(
                endpoint, json={'sku': 'MISSING'}
            ).status_code, 404)
        with patch('backend.enquiries.lines.lookup_product',
                   side_effect=RuntimeError('provider error')):
            self.assertEqual(self.client.post(
                endpoint, json={'sku': 'SKU-001'}
            ).status_code, 502)

    def test_lookup_denies_view_and_rechecks_revocation_after_network(self):
        endpoint = f'/api/enquiries/{self.enquiry_id}/sku-lookup'
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'VIEW',
        })
        self.as_user('exec2')
        with patch('backend.enquiries.lines.lookup_product') as lookup:
            self.assertEqual(self.client.post(
                endpoint, json={'sku': 'SKU-001'}
            ).status_code, 403)
            lookup.assert_not_called()
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/level', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        })
        self.as_user('exec2')

        def revoke(_):
            connection = database.get_db()
            try:
                with connection:
                    connection.execute(
                        'UPDATE client_lead_shares SET is_active = 0 '
                        'WHERE lead_id = ? AND user_id = ?',
                        (self.parent, self.ids['exec2']),
                    )
            finally:
                connection.close()
            return {'found': True, 'title': 'Product', 'price': 1}

        with patch('backend.enquiries.lines.lookup_product',
                   side_effect=revoke):
            self.assertEqual(self.client.post(
                endpoint, json={'sku': 'SKU-001'}
            ).status_code, 404)

    def test_revision_failure_rolls_back_line_creation(self):
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'CREATE TRIGGER reject_revision BEFORE INSERT '
                    'ON enquiry_line_revisions BEGIN '
                    "SELECT RAISE(ABORT, 'test failure'); END"
                )
        finally:
            connection.close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.add()
        self.assertEqual(self.client.get(self.path).json['lines'], [])

    def test_version_ten_upgrade_keeps_existing_enquiries(self):
        path = Path(database.DB_PATH).parent / 'legacy_lines.db'
        migrate_database(path, MIGRATIONS[:10])
        connection = sqlite3.connect(path)
        try:
            before = connection.execute(
                'SELECT COUNT(*) FROM client_enquiries'
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), list(range(11, len(MIGRATIONS) + 1)))
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM client_enquiries'
            ).fetchone()[0], before)
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM enquiry_sku_lines'
            ).fetchone()[0], 0)
        finally:
            connection.close()

    def test_creation_requires_currency_and_complete_initial_sku_lines(self):
        payload = {'client_id': self.parent, 'reference': 'NEW-DEAL',
                   'enquiry_date': '2026-10-14', 'subject': 'Request'}
        self.assertEqual(self.client.post(
            '/api/enquiries', json=payload
        ).status_code, 400)
        payload['deal_currency'] = 'INR'
        self.assertEqual(self.client.post(
            '/api/enquiries', json=payload
        ).status_code, 400)
        item = {'sku': 'NEW', 'description': 'New part', 'quantity': '2',
                'unit_price': '12.50', 'currency': 'INR'}
        payload['lines'] = [item, dict(item, unit_price='invalid')]
        self.assertEqual(self.client.post(
            '/api/enquiries', json=payload
        ).status_code, 400)
        connection = database.get_db()
        try:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM client_enquiries "
                "WHERE reference='NEW-DEAL'"
            ).fetchone()[0], 0)
        finally:
            connection.close()
        payload['lines'] = [item, dict(item, sku='NEW-2')]
        response = self.client.post('/api/enquiries', json=payload)
        self.assertEqual(response.status_code, 201)
        enquiry_id = response.json['enquiry']['id']
        self.assertEqual(response.json['enquiry']['deal_currency'], 'INR')
        result = self.client.get(f'/api/enquiries/{enquiry_id}/lines').json
        self.assertEqual(result['subtotals'], {'INR': '50.00'})
        self.assertEqual(self.client.get(self.path).json['lines'], [])

    def test_bulk_lookup_currency_conversion_and_authorization(self):
        connection=database.get_db()
        with connection:connection.execute("UPDATE app_settings SET value='85371090' WHERE key='hsn_code'")
        connection.close()
        with patch('backend.enquiries.lines.lookup_product', return_value={
                'found': True, 'sku': 'NEW', 'title': 'Fetched part',
                'price': 20, 'sale_price': 10, 'qty': 5}), \
                patch('backend.enquiries.lines.lookup_rate', return_value=90):
            response = self.client.post('/api/enquiries/sku-lookup', json={
                'client_id': self.parent, 'skus': ['NEW', 'NEXT'],
                'currency': 'INR',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json['drafts'][0]['unit_price'], '900.00'
            )
            self.assertEqual(len(response.json['drafts']), 2)
            self.assertEqual(response.json['drafts'][0]['hsn_code'],'85371090')
            self.assertEqual(response.json['shared_hsn_code'],'85371090')
            self.assertEqual(response.json['drafts'][0]['catalog_prices'], {
                'USD': {'price': '20.00', 'sale_price': '10.00'},
                'INR': {'price': '1800.00', 'sale_price': '900.00'},
            })
        self.as_user('exec2')
        with patch('backend.enquiries.lines.lookup_product') as lookup:
            self.assertEqual(self.client.post(
                '/api/enquiries/sku-lookup', json={
                    'client_id': self.parent, 'skus': ['NEW'],
                    'currency': 'USD',
                }
            ).status_code, 404)
            lookup.assert_not_called()

    def test_bulk_lookup_rejects_duplicate_skus_before_provider_calls(self):
        for scope in ({'client_id':self.parent},{'enquiry_id':self.enquiry_id}):
            with patch('backend.enquiries.lines.lookup_product') as lookup, \
                    patch('backend.enquiries.lines.lookup_rate') as rate:
                response=self.client.post('/api/enquiries/sku-lookup',json={
                    **scope,'skus':[' PART-A ','part-a'],'currency':'USD'})
                self.assertEqual(response.status_code,400,response.json)
                self.assertIn('Duplicate SKUs: part-a',response.json['error'])
                lookup.assert_not_called();rate.assert_not_called()

    def test_bulk_add_is_atomic_and_keeps_enquiry_items_independent(self):
        endpoint = self.path + '/bulk'
        item = {'sku': 'BULK', 'description': 'Part', 'quantity': '1',
                'unit_price': '1.25', 'currency': 'USD'}
        self.assertEqual(self.client.post(endpoint, json={
            'lines': [item, dict(item, quantity='0')],
        }).status_code, 400)
        self.assertEqual(self.client.get(self.path).json['lines'], [])
        self.assertEqual(self.client.post(endpoint, json={
            'lines': [item, dict(item, sku='BULK-2')],
        }).status_code, 201)
        self.assertEqual(self.client.get(self.path).json['subtotals'],
                         {'USD': '2.50'})

    def test_unavailable_inr_rate_never_labels_usd_amount_as_inr(self):
        with patch('backend.enquiries.lines.lookup_product', return_value={
                'found': True, 'title': 'Part', 'price': 10}), \
                patch('backend.enquiries.lines.lookup_rate',
                      return_value=None):
            response = self.client.post('/api/enquiries/sku-lookup', json={
                'enquiry_id': self.enquiry_id, 'skus': ['NEW'],
                'currency': 'INR',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['drafts'][0]['unit_price'], '')
            self.assertIn(
                'Rate unavailable', response.json['drafts'][0]['error']
            )

    def test_catalog_display_rate_failure_keeps_usd_deal_price(self):
        with patch('backend.enquiries.lines.lookup_product', return_value={
                'found': True, 'title': 'Part', 'price': 20,
                'sale_price': 10}), \
                patch('backend.enquiries.lines.lookup_rate',
                      side_effect=RuntimeError('Rate unavailable')):
            response = self.client.post('/api/enquiries/sku-lookup', json={
                'client_id': self.parent, 'skus': ['NEW'], 'currency': 'USD',
            })
        self.assertEqual(response.status_code, 200)
        row = response.json['drafts'][0]
        self.assertEqual(row['unit_price'], '10.00')
        self.assertEqual(row['catalog_prices']['USD'], {
            'price': '20.00', 'sale_price': '10.00',
        })
        self.assertEqual(row['catalog_prices']['INR'], {})

    def test_version_eleven_preserves_unassigned_legacy_currency(self):
        path = Path(database.DB_PATH).parent / 'legacy_currency.db'
        migrate_database(path, MIGRATIONS[:11])
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute(
                    "INSERT INTO users (username,password_hash) "
                    "VALUES ('owner','test-placeholder')"
                )
                connection.execute(
                    "INSERT INTO client_leads (name,created_by) "
                    "VALUES ('Client',1)"
                )
                connection.execute(
                    'INSERT INTO client_enquiries '
                    '(client_id,reference,enquiry_date,subject,created_by, '
                    'updated_by) '
                    "VALUES (1,'LEGACY','2026-10-14','Old request',1,1)"
                )
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), list(range(12, len(MIGRATIONS) + 1)))
        connection = sqlite3.connect(path)
        try:
            self.assertIsNone(connection.execute(
                'SELECT deal_currency FROM client_enquiries'
            ).fetchone()[0])
        finally:
            connection.close()


    def test_bulk_lookup_keeps_successes_and_distinguishes_missing_from_network_failures(self):
        def product(sku):
            if sku == 'AVAILABLE':
                return {'found': True, 'title': 'Available part', 'price': 10, 'qty': 5}
            if sku == 'MISSING':
                return {'found': False}
            raise RuntimeError('Catalog unavailable')
        with patch('backend.enquiries.lines.lookup_product', side_effect=product), \
                patch('backend.enquiries.lines.lookup_rate', return_value=90):
            response = self.client.post('/api/enquiries/sku-lookup', json={
                'client_id': self.parent, 'skus': ['AVAILABLE', 'MISSING', 'OFFLINE'], 'currency': 'USD',
            })
        self.assertEqual(response.status_code, 200)
        available, missing, offline = response.json['drafts']
        self.assertEqual(available['lookup_status'], 'found')
        self.assertEqual(available['unit_price'], '10.00')
        self.assertEqual(available['stock'], 5)
        self.assertEqual(missing['lookup_status'], 'not_found')
        self.assertIn('manually', missing['error'])
        self.assertEqual(offline['lookup_status'], 'unavailable')
        self.assertFalse(offline['found'])
        self.assertEqual(self.client.get(self.path).json['lines'], [])


if __name__ == '__main__':
    unittest.main()
