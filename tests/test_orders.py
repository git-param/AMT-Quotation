"""Orders, independent copies, addresses and live client permissions."""

import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import test_enquiries
from backend import database
from backend.enquiries.lines import bp as lines_bp
from backend.orders.routes import bp
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database


class OrderTests(unittest.TestCase):
    """Use private clients, team assignments and actual sharing endpoints."""

    as_user = test_enquiries.EnquiryTests.as_user
    create = test_enquiries.EnquiryTests.create
    assign = test_enquiries.EnquiryTests.assign
    enquiry = test_enquiries.EnquiryTests.enquiry

    def setUp(self):
        test_enquiries.EnquiryTests.setUp(self)
        self.client.application.register_blueprint(lines_bp)
        self.client.application.register_blueprint(bp)
        self.parent = self.create('exec1')
        self.client.put(f'/api/leads/{self.parent}', json={
            'billing_address': {'line1': 'Billing A', 'country': 'India'},
            'shipping_address': {'line1': 'Shipping B', 'country': 'India'},
        })
        self.enquiry_id = self.enquiry(self.parent).json['enquiry']['id']
        self.line_id = self.client.get(
            f'/api/enquiries/{self.enquiry_id}/lines'
        ).json['lines'][0]['id']
        self.address_id = self.client.get(
            f'/api/leads/{self.parent}'
        ).json['address_history'][0]['id']

    def payload(self, **changes):
        result = {
            'enquiry_id': self.enquiry_id, 'order_date': '2026-10-14',
            'currency': 'USD', 'source_line_ids': [self.line_id],
            'delivery': {'saved_address_id': self.address_id,
                         'saved_address_kind': 'shipping',
                         'consignee': {'name': 'Consignee Ltd'}},
        }
        result.update(changes)
        return result

    def order(self, **changes):
        response = self.client.post('/api/orders',
                                    json=self.payload(**changes))
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def share(self, level):
        self.as_user('admin')
        self.assertEqual(self.client.post(
            f'/api/client-access/{self.parent}/grant', json={
                'user_id': self.ids['exec2'], 'access_level': level,
            },
        ).status_code, 200)

    def test_multiple_orders_generated_refs_and_immutable_relationships(self):
        first, second = self.order(), self.order()
        self.assertNotEqual(first['order']['reference'],
                            second['order']['reference'])
        self.assertRegex(first['order']['reference'], r'^ORD-\d{6,}$')
        self.assertEqual(self.client.get('/api/orders', query_string={
            'client_id': self.parent, 'enquiry_id': self.enquiry_id,
        }).json['total'], 2)
        path = f"/api/orders/{first['order']['id']}"
        for key in ('reference', 'client_id', 'enquiry_id', 'created_by',
                    'created_at', 'updated_by', 'lines'):
            self.assertEqual(
                self.client.put(path, json={key: 'spoof'}).status_code, 400
            )
        updated = self.client.put(path, json={
            'po_reference': 'PO-001', 'pi_reference': 'PI-001',
            'pi_date': '2026-10-15', 'status': 'confirmed',
            'payment_terms': 'Advance', 'delivery_terms': 'DAP Mumbai',
            'delivery_time': '4 days', 'dispatch_method': 'Courier',
        })
        self.assertEqual(updated.status_code, 200)
        for key in ('reference', 'client_id', 'enquiry_id', 'created_by',
                    'created_at'):
            self.assertEqual(updated.json['order'][key], first['order'][key])

    def test_recent_lookup_stock_blocks_out_of_stock_and_excess_order_quantities(self):
        from backend.orders.catalog import remember_stock
        state=self.order();base=f'/api/orders/{state["order"]["id"]}/lines'
        data={'sku':'STOCK-CHECK','description':'Stock checked part','quantity':'1','unit_price':'10.00','currency':'USD',
              'hsn_code':'85371090','item_condition':'Used','uom':'Kit'}
        remember_stock('STOCK-CHECK',0)
        result=self.client.post(base,json=data)
        self.assertEqual(result.status_code,400);self.assertIn('out of stock',result.json['error'])
        remember_stock('STOCK-CHECK',2)
        result=self.client.post(base,json={**data,'quantity':'3'})
        self.assertEqual(result.status_code,400);self.assertIn('only 2 available',result.json['error'])
        self.assertEqual(self.client.post(base,json={**data,'quantity':'2'}).status_code,201)
        self.assertEqual(self.client.post(base,json=data).status_code,400)
        self.assertEqual(self.client.post(base,json={**data,'uom':'unsupported'}).status_code,400)

    def test_independent_copies_decimal_totals_and_stable_order_line_ids(self):
        first, second = self.order(), self.order()
        order_id = first['order']['id']
        order_line = first['lines'][0]
        self.client.put(
            f'/api/enquiries/{self.enquiry_id}/lines/{self.line_id}',
            json={'quantity': '3', 'unit_price': '10',
                  'description': 'Changed enquiry'},
        )
        unchanged = self.client.get(f'/api/orders/{order_id}').json
        self.assertEqual(unchanged['lines'][0]['description'],
                         order_line['description'])
        self.assertEqual(
            unchanged['lines'][0]['source_snapshot']['quantity'], '1'
        )
        path = f"/api/orders/{order_id}/lines/{order_line['id']}"
        updated = self.client.put(path, json={
            'quantity': '2', 'unit_price': '12.34',
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['subtotals'], {'USD': '24.68'})
        self.assertEqual(updated.json['lines'][0]['id'], order_line['id'])
        self.assertEqual(self.client.post(
            f'/api/orders/{order_id}/lines', json={
            'sku': 'INR-ITEM', 'description': 'Local spare', 'quantity': '3',
            'unit_price': '0.10', 'currency': 'INR',
        }).status_code, 201)
        self.assertEqual(self.client.get(f'/api/orders/{order_id}').json[
            'subtotals'], {'USD': '24.68', 'INR': '0.30'})
        self.assertEqual(self.client.get(
            f"/api/orders/{second['order']['id']}"
        ).json['lines'][0]['quantity'], '1')
        original = self.client.get(
            f'/api/enquiries/{self.enquiry_id}/lines/{self.line_id}'
        ).json['line']
        self.assertEqual(original['quantity'], '3')
        self.assertEqual(original['unit_price'], '10.00')

    def test_order_delivery_history_is_separate_from_client_defaults(self):
        first = self.order()
        order_id = first['order']['id']
        self.client.put(f'/api/leads/{self.parent}', json={
            'shipping_address': {'line1': 'New client default',
                                 'country': 'India'},
        })
        self.assertEqual(self.client.get(f'/api/orders/{order_id}').json[
            'delivery']['shipping_address']['line1'], 'Shipping B')
        updated = self.client.put(f'/api/orders/{order_id}', json={
            'delivery': {
                'shipping_address': {'line1': 'Order only', 'country': 'USA'},
                'consignee': {'name': 'US recipient',
                              'email': 'pic@example.com',
                              'phone': '+12345678901', 'pic': 'PIC'},
                'notify_party': {'name': 'Notify agent'},
                'buyer': {'name': 'Buyer', 'gst_number': 'GST-reference'},
                'instructions': 'Use side entrance',
            },
        })
        self.assertEqual(updated.status_code, 200)
        delivery = updated.json['delivery']
        self.assertIsNone(delivery['saved_address_id'])
        self.assertEqual(delivery['shipping_address']['line1'], 'Order only')
        self.assertEqual(len(updated.json['delivery_history']), 2)
        original = updated.json['delivery_history'][1]
        self.assertEqual(original['shipping_address']['line1'], 'Shipping B')
        self.assertEqual(original['saved_address_id'], self.address_id)
        client = self.client.get(f'/api/leads/{self.parent}').json['lead']
        self.assertEqual(client['shipping_address']['line1'],
                         'New client default')
        self.assertEqual(client['billing_address']['line1'], 'Billing A')
        sibling = self.order(delivery={
            'shipping_address': {'line1': 'Another destination',
                                 'country': 'UK'},
            'consignee': {'name': 'Other receiver'},
        })
        self.assertEqual(sibling['delivery']['shipping_address']['line1'],
                         'Another destination')
        self.assertEqual(self.client.get(f'/api/orders/{order_id}').json[
            'delivery']['shipping_address']['line1'], 'Order only')

    def test_validation_and_atomic_failure_leave_no_partial_order(self):
        invalid = [
            {'source_line_ids': [], 'lines': []},
            {'source_line_ids': [self.line_id, self.line_id]},
            {'order_date': '2026-02-30'}, {'pi_date': 'bad'},
            {'currency': 'EUR'}, {'status': 'deleted'},
            {'reference': 'USER-REF'},
            {'delivery': {'shipping_address': {'line1': 'Street'},
                          'consignee': {'name': 'Receiver'}}},
            {'delivery': {'shipping_address': {'line1': 'Street',
                                              'country': 'UK'},
                          'consignee': {'name': 'Receiver',
                                        'email': 'invalid'}}},
        ]
        for change in invalid:
            self.assertEqual(self.client.post('/api/orders', json=self.payload(
                **change
            )).status_code, 400, change)
        item = {'sku': 'MANUAL', 'description': 'Spare', 'quantity': '1',
                'unit_price': '1.00', 'currency': 'USD'}
        for change in ({'quantity': '1.5'}, {'quantity': True},
                       {'unit_price': 'NaN'}, {'unit_price': '0.001'},
                       {'line_total': '999'}, {'order_id': 999}):
            self.assertEqual(self.client.post('/api/orders', json=self.payload(
                source_line_ids=[], lines=[dict(item, **change)]
            )).status_code, 400)
        self.assertEqual(self.client.get('/api/orders').json['total'], 0)
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'CREATE TRIGGER reject_order_revision BEFORE INSERT '
                    "ON order_revisions BEGIN SELECT RAISE(ABORT,'fail'); END"
                )
        finally:
            connection.close()
        self.assertEqual(self.client.post('/api/orders',
                                         json=self.payload()).status_code, 409)
        connection = database.get_db()
        try:
            for table in ('client_orders', 'order_sku_lines',
                          'order_delivery_versions', 'order_revisions'):
                self.assertEqual(connection.execute(
                    'SELECT COUNT(*) FROM ' + table
                ).fetchone()[0], 0)
        finally:
            connection.close()

    def test_cross_enquiry_lines_and_foreign_client_addresses_rejected(self):
        other = self.create('exec2')
        other_enquiry = self.enquiry(other, 'OTHER').json['enquiry']['id']
        foreign_line = self.client.get(
            f'/api/enquiries/{other_enquiry}/lines'
        ).json['lines'][0]['id']
        foreign_address = self.client.get(
            f'/api/leads/{other}'
        ).json['address_history'][0]['id']
        self.as_user('admin')
        self.assertEqual(self.client.post('/api/orders', json=self.payload(
            source_line_ids=[foreign_line]
        )).status_code, 400)
        self.assertEqual(self.client.post('/api/orders', json=self.payload(
            delivery={'saved_address_id': foreign_address,
                      'saved_address_kind': 'shipping',
                      'consignee': {'name': 'Receiver'}}
        )).status_code, 400)
        order = self.order()
        path = f"/api/orders/{order['order']['id']}/lines"
        self.assertEqual(self.client.post(path, json={
            'source_line_id': self.line_id,
        }).status_code, 409)
        self.assertEqual(self.client.post(path, json={
            'source_line_id': foreign_line,
        }).status_code, 400)
        self.assertEqual(self.client.get(path).json['lines'][0]['id'],
                         order['lines'][0]['id'])

    def test_visibility_search_filters_pagination_and_write_permissions(self):
        orders = [self.order()['order'] for _ in range(3)]
        path = f"/api/orders/{orders[0]['id']}"
        self.as_user('exec2')
        for query in ({}, {'client_id': self.parent},
                      {'enquiry_id': self.enquiry_id},
                      {'q': orders[0]['reference']}):
            self.assertEqual(
                self.client.get('/api/orders', query_string=query).json[
                    'total'], 0
            )
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(
            self.client.put(path, json={'notes': 'No'}).status_code, 404
        )
        self.assertEqual(self.client.post('/api/orders',
                                         json=self.payload()).status_code, 404)
        self.assign('exec1', 'tl1')
        self.as_user('tl2')
        self.assertEqual(self.client.get(path).status_code, 404)
        for actor in ('exec1', 'tl1', 'admin', 'manager'):
            self.as_user(actor)
            data = self.client.get('/api/orders', query_string={
                'page_size': 2, 'page': 2, 'sort': 'reference',
                'direction': 'asc',
            }).json
            self.assertEqual(data['total'], 3)
            self.assertEqual(len(data['orders']), 1)
            self.assertEqual(self.client.put(path, json={
                'notes': actor,
            }).status_code, 200)
        self.as_user('exec1')
        self.assertEqual(self.client.get('/api/orders', query_string={
            'q': orders[1]['reference'], 'status': 'draft',
        }).json['total'], 1)
        self.assertEqual(self.client.get('/api/orders', query_string={
            'sort': 'invalid',
        }).status_code, 400)
        self.as_user(None)
        self.assertEqual(self.client.get('/api/orders').status_code, 401)
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post('/api/orders',
                                         json=self.payload()).status_code, 401)

    def test_view_edit_shares_and_creator_cannot_bypass_revoked_access(self):
        original = self.order()
        order_id = original['order']['id']
        line_id = original['lines'][0]['id']
        path = f'/api/orders/{order_id}'
        self.share('VIEW')
        self.as_user('exec2')
        self.assertEqual(self.client.get(path).status_code, 200)
        for method, url, data in (
                ('put', path, {'notes': 'Forbidden'}),
                ('post', '/api/orders', self.payload()),
                ('post', path + '/lines', {'source_line_id': self.line_id}),
                ('put', path + f'/lines/{line_id}', {'quantity': '2'})):
            self.assertEqual(
                getattr(self.client, method)(url, json=data).status_code, 403
            )
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/level', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        })
        self.as_user('exec2')
        created = self.order()
        self.assertEqual(created['order']['created_by'], self.ids['exec2'])
        self.assertEqual(created['order']['owner_name'], 'exec1')
        self.assertEqual(
            self.client.put(path, json={'notes': 'Permitted'}).status_code, 200
        )
        self.assertEqual(
            self.client.delete(path + f'/lines/{line_id}').status_code, 403
        )
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/revoke', json={
            'user_id': self.ids['exec2'],
        })
        self.as_user('exec2')
        for url in (path, path + '/lines',
                    f"/api/orders/{created['order']['id']}"):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get('/api/orders').json['total'], 0)
        self.assertEqual(
            self.client.put(path, json={'notes': 'Revoked'}).status_code, 404
        )

    def test_line_removal_history_and_deleted_parent_visibility(self):
        order = self.order()
        order_id, line_id = order['order']['id'], order['lines'][0]['id']
        path = f'/api/orders/{order_id}'
        self.assign('exec1', 'tl1')
        self.as_user('tl1')
        removed = self.client.delete(path + f'/lines/{line_id}')
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json['subtotals'], {})
        self.assertEqual(self.client.get(path + f'/lines/{line_id}').json[
            'line']['is_active'], 0)
        self.assertEqual(self.client.get(path).json['revisions'][0]['action'],
                         'line_remove')
        self.as_user('admin')
        self.client.delete(f'/api/enquiries/{self.enquiry_id}')
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertIsNotNone(
            self.client.get(path).json['order']['enquiry_deleted_at']
        )
        self.client.delete(f'/api/leads/{self.parent}')
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get('/api/orders').json['total'], 0)
        connection = database.get_db()
        try:
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM client_orders'
            ).fetchone()[0], 1)
            self.assertEqual(
                connection.execute('PRAGMA foreign_key_check').fetchall(), []
            )
        finally:
            connection.close()

    def test_inactive_client_blocks_creation_but_keeps_history_editable(self):
        order = self.order()
        self.client.post(f'/api/leads/{self.parent}/deactivate')
        self.assertEqual(self.client.post('/api/orders',
                                         json=self.payload()).status_code, 400)
        path = f"/api/orders/{order['order']['id']}"
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(
            self.client.put(path, json={'notes': 'History'}).status_code, 200
        )

    def test_bulk_lines_are_atomic_and_isolated_to_selected_order(self):
        first, second = self.order(), self.order()
        path = f"/api/orders/{first['order']['id']}/lines/bulk"
        item = {'sku': 'MANUAL', 'description': 'Part', 'quantity': '2',
                'unit_price': '12.50', 'currency': 'USD'}
        self.assertEqual(self.client.post(path, json={
            'lines': [item, dict(item, quantity='1.5')],
        }).status_code, 400)
        added = self.client.post(path, json={'lines': [item]})
        self.assertEqual(added.status_code, 201)
        self.assertEqual(added.json['subtotals'], {'USD': '25.00'})
        self.assertEqual(len(self.client.get(
            f"/api/orders/{second['order']['id']}"
        ).json['lines']), 1)
        line_id = first['lines'][0]['id']
        wrong = f"/api/orders/{second['order']['id']}/lines/{line_id}"
        self.assertEqual(self.client.get(wrong).status_code, 404)
        self.assertEqual(self.client.put(wrong, json=item).status_code, 404)

    def test_management_creation_and_concurrent_reference_generation(self):
        self.assign('exec1', 'tl1')
        for actor in ('admin', 'manager', 'tl1'):
            self.as_user(actor)
            order = self.order()
            self.assertEqual(order['order']['created_by'], self.ids[actor])
            self.assertEqual(order['order']['owner_name'], 'exec1')
        app = self.client.application

        def create(_):
            client = app.test_client()
            with client.session_transaction() as session:
                session['user_id'] = self.ids['exec1']
            response = client.post('/api/orders', json=self.payload())
            return response.status_code, response.json['order']['reference']

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        self.assertEqual([result[0] for result in results], [201, 201])
        self.assertEqual(len({result[1] for result in results}), 2)

    def test_version_thirteen_upgrade_preserves_existing_enquiry_records(self):
        path = Path(database.DB_PATH).parent / 'orders_upgrade.db'
        migrate_database(path, MIGRATIONS[:13])
        connection = sqlite3.connect(path)
        tables = ('users', 'client_leads', 'client_enquiries',
                  'enquiry_sku_lines', 'client_address_history')
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
                    "VALUES(1,'SAVED','2026-10-14','Historical',1,1)"
                )
                connection.execute(
                    'INSERT INTO enquiry_sku_lines(enquiry_id,sku,description,'
                    'quantity_milli,unit_price_minor,currency,created_by,'
                    "updated_by) VALUES(1,'A','Saved part',1005,100,'USD',1,1)"
                )
            columns = {table: ','.join(row[1] for row in connection.execute(
                'PRAGMA table_info(' + table + ')')) for table in tables}
            before = {table: connection.execute(
                'SELECT ' + columns[table] + ' FROM ' + table
            ).fetchall() for table in tables}
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), list(range(14, len(MIGRATIONS) + 1)))
        self.assertEqual(migrate_database(path), [])
        connection = sqlite3.connect(path)
        try:
            after = {table: connection.execute(
                'SELECT ' + columns[table] + ' FROM ' + table
            ).fetchall() for table in tables}
            self.assertEqual(before, after)
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM client_orders'
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                'PRAGMA foreign_key_check'
            ).fetchall(), [])
        finally:
            connection.close()
