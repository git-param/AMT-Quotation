"""Unified workspace, PI issuance and populated-database upgrade coverage."""

from decimal import Decimal
from io import BytesIO
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import test_orders
from backend import database
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database
from backend.orders.invoices import Q, calculate, render, template


def fixture_template(path, currency):
    """No real company/bank data in test artifacts."""
    first = 23 if currency == 'USD' else 24
    root = ET.Element(Q + 'worksheet')
    data = ET.SubElement(root, Q + 'sheetData')
    for number in range(1, 54):
        row = ET.SubElement(data, Q + 'row', r=str(number))
        for col in ('A', 'B', 'E', 'F', 'G', 'H', 'I', 'J', 'K'):
            ET.SubElement(row, Q + 'c', r=col + str(number))
    strings = ['PROFORMA INVOICE', 'Company fixture', 'BANK DETAIL', 'Company bank fixture', 'Payment Terms: 100% Advance']
    for ref, index in (('A2', 0), ('A5', 1), ('F8',4), (f'A{first+4}', 2), (f'A{first+7}', 3)):
        cell = root.find('.//' + Q + f'c[@r="{ref}"]')
        cell.set('t', 's')
        ET.SubElement(cell, Q + 'v').text = str(index)
    if currency == 'INR':
        ET.SubElement(root.find('.//' + Q + 'c[@r="J33"]'), Q + 'f').text = 'J32*18%'
    merges = ET.SubElement(root, Q + 'mergeCells')
    for row in range(first, first + 4):
        for start, end in (('B', 'D'), ('J', 'K')):
            ET.SubElement(merges, Q + 'mergeCell', ref=f'{start}{row}:{end}{row}')
    merges.set('count', str(len(merges)))
    book = ET.Element(Q + 'workbook')
    names = ET.SubElement(book, Q + 'definedNames')
    ET.SubElement(names, Q + 'definedName', name='_xlnm.Print_Area').text = 'PI!$A$1:$K$51'
    shared = ET.Element(Q + 'sst')
    for value in strings:
        ET.SubElement(ET.SubElement(shared, Q + 'si'), Q + 't').text = value
    with ZipFile(path, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', ET.tostring(root))
        z.writestr('xl/workbook.xml', ET.tostring(book))
        z.writestr('xl/sharedStrings.xml', ET.tostring(shared))
        z.writestr('xl/vbaProject.bin', b'Unexecuted test fixture')


class WorkspaceTests(unittest.TestCase):
    setUp = test_orders.OrderTests.setUp
    as_user = test_orders.OrderTests.as_user
    create = test_orders.OrderTests.create
    assign = test_orders.OrderTests.assign
    enquiry = test_orders.OrderTests.enquiry
    share = test_orders.OrderTests.share
    order = test_orders.OrderTests.order
    payload = test_orders.OrderTests.payload

    def direct(self, **changes):
        data = {
            'client_id': self.parent, 'order_date': '2026-10-15', 'currency': 'USD',
            'payment_terms': '100% advance', 'delivery_terms': 'DAP',
            'destination': 'USA', 'delivery_time': '6 days', 'dispatch_method': 'Courier',
            'shipping_charges': '10.00', 'po_reference': 'PO/123',
            'delivery': {'shipping_address': {'line1': 'Order destination', 'country': 'USA'},
                         'consignee': {'name': 'Consignee', 'phone': '+12025550123', 'email': 'consignee@example.com', 'pic': 'Fixture Contact', 'gst_number': '24TEST123'},
                         'notify_party': {'name': 'Notify', 'address': {
                             'line1': 'Notify address', 'country': 'USA'}}},
            'lines': [{'sku': 'PART', 'description': '=Not an Excel formula', 'quantity': '3',
                       'unit_price': '12.34', 'currency': 'USD',
                       'hsn_code': '85371090', 'item_condition': 'Used', 'uom': 'PCs'}],
        }
        data.update(changes)
        response = self.client.post('/api/orders', json=data)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def templates(self):
        paths = {}
        for currency in ('USD', 'INR'):
            path = Path(database.DB_PATH).parent / (currency + '.xlsm')
            fixture_template(path, currency)
            paths['PI_TEMPLATE_' + currency] = str(path)
        context = patch.dict(os.environ, paths)
        context.start()
        self.addCleanup(context.stop)

    def test_empty_drafts_multiple_independent_orders_and_confirmation(self):
        first = self.direct(lines=[], delivery={})
        second = self.direct()
        self.assertIsNone(first['order']['enquiry_id'])
        self.assertNotEqual(first['order']['id'], second['order']['id'])
        path = f"/api/orders/{first['order']['id']}"
        self.assertEqual(self.client.put(path, json={'status': 'confirmed'}).status_code, 400)
        self.assertEqual(self.client.put(path, json={'notes': 'Pending delivery'}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/orders/{second['order']['id']}").json['order']['notes'], '')
        self.assertEqual(self.client.get('/api/orders?status=draft').json['total'], 2)
        self.assertEqual(self.client.get('/api/orders?exclude_drafts=1').json['total'], 0)
        lead = self.client.get(f'/api/leads/{self.parent}').json['lead']
        self.assertEqual((lead['order_count'], lead['pending_order_count']), (2, 2))
        self.assertEqual(self.client.get('/api/orders?q=PO%2F123').json['total'], 2)
        self.assertEqual(self.client.get('/enquiries').location, '/clients-orders')

    def test_direct_order_and_invoice_permissions_rechecked_for_each_request(self):
        self.templates()
        order_id = self.direct(pi_reference='AMT/1234')['order']['id']
        path = f'/api/orders/{order_id}'
        invoice = self.client.post(path + '/invoices', json={'currency': 'USD'})
        self.assertEqual(invoice.status_code, 201, invoice.json)
        self.as_user('exec2')
        for endpoint in (path, invoice.json['download_url'], path + '/legacy-enquiry'):
            self.assertEqual(self.client.get(endpoint).status_code, 404)
        self.assertEqual(self.client.post('/api/orders', json={
            'client_id': self.parent, 'order_date': '2026-10-15', 'currency': 'USD',
        }).status_code, 404)
        self.share('VIEW')
        self.as_user('exec2')
        self.assertEqual(self.client.get(invoice.json['download_url']).status_code, 200)
        self.assertEqual(self.client.post(path + '/invoices', json={'currency': 'INR'}).status_code, 403)
        self.assertEqual(self.client.put(path, json={'notes': 'Spoof'}).status_code, 403)
        self.as_user('admin')
        self.assertEqual(self.client.post(f'/api/client-access/{self.parent}/level', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        }).status_code, 200)
        self.as_user('exec2')
        self.assertEqual(self.client.put(path, json={'notes': 'Shared edit'}).status_code, 200)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/revoke', json={'user_id': self.ids['exec2']})
        self.as_user('exec2')
        self.assertEqual(self.client.get(invoice.json['download_url']).status_code, 404)

    def test_pi_currency_conversion_and_immutable_workbook(self):
        self.templates()
        state = self.direct(pi_reference='AMT/1234')
        order_id = state['order']['id']
        path = f'/api/orders/{order_id}'
        for currency, rate in (('EUR', None), ('INR', None), ('INR', '0'), ('INR', '-1'),
                               ('INR', True), ('INR', '1e2'), ('INR', '80.1234567'),
                               ('USD', '80'), ('INR', 'NaN')):
            payload = {'currency': currency}
            if rate is not None:
                payload['usd_inr_rate'] = rate
            self.assertEqual(self.client.post(path + '/invoices', json=payload).status_code, 400)
        issued = self.client.post(path + '/invoices', json={'currency': 'INR', 'usd_inr_rate': '80'})
        self.assertEqual(issued.status_code, 201, issued.json)
        totals = issued.json['totals']
        self.assertEqual((totals['subtotal'], totals['shipping'], totals['tax'], totals['grand_total']),
                         ('2961.60', '800.00', '677.09', '4438.69'))
        self.assertIn('Rupees', totals['amount_in_words'])
        workbook = self.client.get(issued.json['download_url']).data
        self.client.put(path + '/lines/' + str(state['lines'][0]['id']), json={'unit_price': '999'})
        self.client.put(path, json={'notes': 'Changed later'})
        self.assertEqual(workbook, self.client.get(issued.json['download_url']).data)
        with ZipFile(BytesIO(workbook)) as generated:
            sheet = ET.fromstring(generated.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(sheet.find('.//' + Q + 'c[@r="A37"]/' + Q + 'is/' + Q + 't').text,
                             '2. PAYMENT 100% advance')
            self.assertIn('Billing A', sheet.find('.//' + Q + 'c[@r="F12"]/' + Q + 'is/' + Q + 't').text)
        self.assertEqual(self.client.put(path, json={'pi_reference': 'SPOOF'}).status_code, 400)
        self.assertEqual(self.client.get(path).json['invoices'][0]['reference'], issued.json['reference'])
        connection = database.get_db()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action='pi_generate'").fetchone()[0], 1)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        finally:
            connection.close()

    def test_usd_division_mixed_currencies_and_rounding_before_quantity(self):
        state = self.direct()
        state['lines'] = [dict(state['lines'][0], currency='INR', unit_price='1.00', quantity='3'),
                          dict(state['lines'][0], currency='USD', unit_price='2.01', quantity='2')]
        totals = calculate(state, 'USD', '3', Decimal(0))
        self.assertEqual(totals['lines'][0]['unit_price'], '0.33')
        self.assertEqual(totals['subtotal'], '5.01')
        self.assertEqual(totals['grand_total'], '15.01')
        self.assertEqual(state['lines'][0]['unit_price'], '1.00')

    def test_editable_party_blocks_keep_custom_lines_and_use_company_payment_terms(self):
        self.templates()
        consignee = ('Marine Buyer\nDock 7, New York\nCountry: USA\n'
                     'Tel: +12345678901\nPIC: Alice\nEmail: buyer@example.com')
        buyer = consignee + '\nBuyer registration: BUYER-123'
        notify = consignee + '\nNotify reference: N-456'
        state = self.direct(pi_reference='AMT/1234', payment_terms='', delivery={
            'consignee_text': consignee+'\nGST No.: 24TEST123', 'buyer_text': buyer, 'notify_text': notify,
        })
        path = f"/api/orders/{state['order']['id']}"
        self.assertEqual(state['delivery']['consignee']['email'], 'buyer@example.com')
        self.assertEqual(state['delivery']['buyer_text'], buyer)
        self.assertEqual(self.client.put(path, json={'delivery': {
            'consignee_text': consignee.replace('buyer@example.com', 'invalid-email'),
        }}).status_code, 400)
        self.assertEqual(self.client.get(path).json['delivery']['buyer_text'], buyer)
        issued = self.client.post(path + '/invoices', json={'currency': 'USD'})
        self.assertEqual(issued.status_code, 201, issued.json)
        workbook = self.client.get(issued.json['download_url']).data
        with ZipFile(BytesIO(workbook)) as generated:
            sheet = ET.fromstring(generated.read('xl/worksheets/sheet1.xml'))
            get = lambda ref: sheet.find('.//' + Q + f'c[@r="{ref}"]/' + Q + 'is/' + Q + 't').text
            self.assertEqual(get('F12'), buyer)
            self.assertEqual(get('F18'), notify)
            self.assertEqual(get('F8'), 'Payment Terms: 100% Advance')
            self.assertEqual(get('A12'), 'Marine Buyer')
            self.assertIn('Dock 7', get('A13'))
            self.assertEqual(get('A20'), 'Email: buyer@example.com')
        self.assertEqual(self.client.get(path).json['order']['payment_terms'], '')

    def test_party_defaults_follow_consignee_until_buyer_is_customized(self):
        consignee = 'Buyer\nDock Road\nCountry: USA\nTel:\nPIC:\nEmail:'
        state = self.direct(delivery={'consignee_text': consignee})
        self.assertEqual(state['delivery']['buyer_text'], consignee)
        self.assertEqual(state['delivery']['notify_text'], consignee)
        path = f"/api/orders/{state['order']['id']}"
        revised = consignee + '\nOrder instructions'
        response = self.client.put(path, json={'delivery': {'consignee_text': revised}})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['delivery']['buyer_text'], revised)
        custom = revised + '\nBuyer-specific reference'
        self.client.put(path, json={'delivery': {'buyer_text': custom}})
        response = self.client.put(path, json={'delivery': {'consignee_text': consignee}})
        self.assertEqual(response.json['delivery']['buyer_text'], custom)
        self.assertEqual(response.json['delivery']['notify_text'], consignee)

    def test_location_edit_preserves_hidden_legacy_client_fields(self):
        before = self.client.get(f'/api/leads/{self.parent}').json['lead']
        result = self.client.put(f'/api/leads/{self.parent}', json={'location': 'Dock 9\nUSA'})
        self.assertEqual(result.status_code, 200, result.json)
        for key in ('billing_address', 'shipping_address', 'status', 'business_details'):
            self.assertEqual(result.json['lead'][key], before[key])
        self.assertEqual(self.client.get('/api/leads?q=Dock%209').json['total'], 1)

    def test_location_migration_keeps_existing_address_and_status_data(self):
        path = Path(database.DB_PATH).parent / 'location-upgrade.db'
        migrate_database(path, MIGRATIONS[:16])
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute("INSERT INTO users(username,password_hash) VALUES('owner','fixture')")
                connection.execute('INSERT INTO client_leads(name,created_by,status,business_details,shipping_address_json) '
                    "VALUES('Legacy client',1,'customer','Keep old details',?)",
                    ('{"line1":"Dock 1","city":"New York","country":"USA"}',))
            before = connection.execute('SELECT shipping_address_json,status,business_details FROM client_leads').fetchone()
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), list(range(17, len(MIGRATIONS)+1)))
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute('SELECT shipping_address_json,status,business_details FROM client_leads').fetchone(), before)
            self.assertEqual([line for line in connection.execute('SELECT location FROM client_leads').fetchone()[0].splitlines() if line],
                             ['Dock 1', 'New York', 'USA'])
        finally:
            connection.close()

    def test_incomplete_commercial_fields_fail_atomically(self):
        self.templates()
        state = self.direct(delivery_terms='')
        path = f"/api/orders/{state['order']['id']}"
        self.assertEqual(self.client.post(path + '/invoices', json={'currency': 'USD'}).status_code, 400)
        self.client.put(path, json={'delivery_terms': 'DAP'})
        self.client.put(path + '/lines/' + str(state['lines'][0]['id']), json={'hsn_code': ''})
        self.assertEqual(self.client.post(path + '/invoices', json={'currency': 'USD'}).status_code, 400)
        self.assertEqual(self.client.get(path).json['invoices'], [])

        self.client.put(path + '/lines/' + str(state['lines'][0]['id']), json={'hsn_code': '85371090'})
        with patch.dict(os.environ, {'PI_TEMPLATE_USD': 'missing-company-template.xlsm'}):
            self.assertEqual(self.client.post(path + '/invoices', json={'currency': 'USD'}).status_code, 400)
        self.assertEqual(self.client.get(path).json['invoices'], [])

    def test_missing_pi_fields_are_actionable_and_commercial_batch_is_scoped_and_atomic(self):
        self.templates()
        state = self.direct(pi_reference='AMT/1234')
        order_id, line_id = state['order']['id'], state['lines'][0]['id']
        path = f'/api/orders/{order_id}'
        self.client.put(path + '/lines/' + str(line_id), json={'hsn_code': '', 'item_condition': ''})
        response = self.client.post(path + '/invoices', json={'currency': 'USD'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['code'], 'pi_lines_incomplete')
        self.assertEqual(response.json['missing_lines'][0]['sku'], 'PART')
        self.assertEqual(response.json['missing_lines'][0]['fields'], ['hsn_code', 'item_condition'])
        original_price = self.client.get(path).json['lines'][0]['unit_price']
        valid = {'id': line_id, 'hsn_code': '85371090', 'item_condition': 'Used'}
        other_id = self.direct()['lines'][0]['id']
        for invalid in ({'id': other_id, 'hsn_code': '1', 'item_condition': 'New'},
                        dict(valid, id=10**100), dict(valid, unit_price='1'), dict(valid, hsn_code='X'*21)):
            result = self.client.put(path + '/line-commercial-details', json={'lines': [valid, invalid]})
            self.assertEqual(result.status_code, 400, result.json)
            self.assertEqual(self.client.get(path).json['lines'][0]['hsn_code'], '')
        self.share('VIEW')
        self.as_user('exec2')
        self.assertEqual(self.client.put(path + '/line-commercial-details', json={'lines': [valid]}).status_code, 403)
        self.as_user('exec1')
        saved = self.client.put(path + '/line-commercial-details', json={'lines': [valid]})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json['pi_line_requirements'], [])
        self.assertEqual(saved.json['lines'][0]['unit_price'], original_price)
        self.assertEqual(self.client.post(path + '/invoices', json={'currency': 'USD'}).status_code, 201)

    def test_populated_version_fourteen_upgrade_preserves_ids_revisions_and_references(self):
        self.order(pi_reference='HISTORICAL-PI')
        path = Path(database.DB_PATH).parent / 'populated-14.db'
        migrate_database(path, MIGRATIONS[:14])
        source = database.get_db()
        target = sqlite3.connect(path)
        tables = ('users', 'client_leads', 'client_address_history', 'client_enquiries',
                  'enquiry_sku_lines', 'client_orders', 'order_sku_lines',
                  'order_delivery_versions', 'order_revisions', 'audit_logs')
        snapshots = {}
        try:
            with target:
                for name in tables:
                    columns = ','.join(row[1] for row in target.execute('PRAGMA table_info(' + name + ')'))
                    rows = [tuple(row) for row in source.execute('SELECT ' + columns + ' FROM ' + name)]
                    if rows:
                        target.executemany('INSERT INTO ' + name + '(' + columns + ') VALUES (' + ','.join('?' for _ in rows[0]) + ')', rows)
                    snapshots[name] = (columns, rows)
        finally:
            source.close()
            target.close()
        self.assertEqual(migrate_database(path), list(range(15, len(MIGRATIONS) + 1)))
        target = sqlite3.connect(path)
        try:
            for name, (columns, rows) in snapshots.items():
                self.assertEqual(target.execute('SELECT ' + columns + ' FROM ' + name).fetchall(), rows)
            self.assertEqual(target.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(target.execute('SELECT COUNT(*) FROM client_orders').fetchone()[0], 1)
        finally:
            target.close()

    def test_fractional_legacy_lines_require_explicit_review_and_retain_original(self):
        path = Path(database.DB_PATH).parent / 'fractional.db'
        migrate_database(path, MIGRATIONS[:14])
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.execute("INSERT INTO users(username,password_hash,role) VALUES('legacy','fixture','sales_executive')")
                connection.execute("INSERT INTO client_leads(name,created_by) VALUES('Legacy client',1)")
                connection.execute("INSERT INTO client_enquiries(client_id,reference,enquiry_date,subject,created_by,updated_by) VALUES(1,'OLD','2026-10-01','Saved request',1,1)")
                connection.execute("INSERT INTO enquiry_sku_lines(enquiry_id,sku,description,quantity_milli,unit_price_minor,currency,created_by,updated_by) VALUES(1,'OLD-SKU','Fractional quantity',1500,100,'USD',1,1)")
        finally:
            connection.close()
        migrate_database(path)
        with patch.object(database, 'DB_PATH', str(path)):
            with self.client.session_transaction() as session:
                session['user_id'] = 1
            state = self.client.get('/api/orders/1').json
            self.assertEqual(state['legacy_lines_requiring_review'][0]['quantity'], '1.500')
            line = self.client.post('/api/orders/1/lines', json={
                'sku': 'REVIEWED', 'description': 'Reviewed units', 'quantity': '2',
                'unit_price': '1', 'currency': 'USD',
            }).json['lines'][0]
            result = self.client.post('/api/orders/1/legacy-lines/1/review', json={'replacement_line_id': line['id']})
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(result.json['legacy_lines_requiring_review'], [])
            self.assertEqual(self.client.get('/api/orders/1/legacy-enquiry').json['lines'][0]['quantity'], '1.500')
            self.as_user('admin')
            # Role/user comes from this DB, never the cached session role.
            self.assertEqual(self.client.get('/api/orders/1').status_code, 200)

    def test_real_company_templates_expand_without_changing_company_or_bank_content(self):
        defaults = Path.home() / 'Downloads'
        names = {'USD': 'Updated PI Format USD - 180626 2.xlsm', 'INR': 'Updated PI Format INR 1 2 2.xlsm'}
        if not all((defaults / name).exists() or (defaults / ('pi-'+code+'.xlsm')).exists() for code,name in names.items()):
            self.skipTest('Local company workbook integration fixtures are unavailable.')
        state = self.direct(notes='Order notes ' * 100)
        state['lines'] *= 50
        for currency in ('USD', 'INR'):
            raw, sheet, first, tax = template(currency)
            totals = calculate(state, currency, '80' if currency == 'INR' else None, tax)
            generated = render(raw, sheet, first, state, totals, 'TEST/PI/1', '2026-10-15', 'Fixture')
            with ZipFile(BytesIO(raw)) as original, ZipFile(BytesIO(generated)) as output:
                self.assertTrue(original.read('xl/styles.xml') == output.read('xl/styles.xml'))
                self.assertTrue(original.read('xl/vbaProject.bin') == output.read('xl/vbaProject.bin'))
                self.assertTrue(original.read('xl/sharedStrings.xml') == output.read('xl/sharedStrings.xml'))
                result = ET.fromstring(output.read('xl/worksheets/sheet1.xml'))
                original_sheet = ET.fromstring(original.read('xl/worksheets/sheet1.xml'))
                # Compare references and content without leaking company bank values on failure.
                for row in range(first + 4, first + 10):
                    old = original_sheet.find('.//' + Q + f'c[@r="A{row}"]')
                    new = result.find('.//' + Q + f'c[@r="A{row+46}"]')
                    self.assertTrue(ET.tostring(old).replace(f'A{row}'.encode(), b'BANK') ==
                                    ET.tostring(new).replace(f'A{row+46}'.encode(), b'BANK'))
                self.assertEqual(result.find('.//' + Q + f'c[@r="J{first+49}"]/' + Q + 'v').text,
                                 totals['lines'][-1]['line_total'])
                self.assertEqual(result.find('.//' + Q + f'c[@r="B{first}"]').get('t'), 'inlineStr')
                names_xml = ET.fromstring(output.read('xl/workbook.xml'))
                self.assertIn(':$K$', names_xml.find('.//' + Q + 'definedName').text)
                self.assertNotIn('xl/calcChain.xml', output.namelist())
                merges = result.find(Q + 'mergeCells')
                self.assertEqual(int(merges.get('count')), len(merges))


if __name__ == '__main__':
    unittest.main()
