"""Discount persistence, PI arithmetic, exports and preview stability."""
from decimal import Decimal
from io import BytesIO
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import test_native_pi
import test_bulk_pi
from backend.orders.invoices import calculate
from backend.orders.pi_document import edit
from backend.orders.pi_layout import layout


class DiscountTests(unittest.TestCase):
    setUpBase = test_native_pi.NativePiTests.setUpBase
    setUp = test_native_pi.NativePiTests.setUp
    direct = test_native_pi.NativePiTests.direct
    as_user = test_native_pi.NativePiTests.as_user
    create = test_native_pi.NativePiTests.create
    assign = test_native_pi.NativePiTests.assign
    enquiry = test_native_pi.NativePiTests.enquiry
    share = test_native_pi.NativePiTests.share
    preview = test_native_pi.NativePiTests.preview
    issue = test_native_pi.NativePiTests.issue
    edits = test_native_pi.NativePiTests.edits

    def save(self, **changes):
        data = dict(type='percent', value='10', scope='all', line_ids=[], show_on_pi=True)
        data.update(changes)
        return self.client.put(f'/api/orders/{self.order_id}/discount', json=data)

    def test_visible_sku_and_preview_edits_do_not_compound(self):
        response = self.save()
        self.assertEqual(response.status_code, 200, response.json)
        preview = self.preview()
        doc = preview['document']
        self.assertEqual(doc['totals']['lines'][0]['line_total'], '33.32')
        self.assertEqual(doc['totals']['grand_total'], '43.32')
        self.assertIn('Discount: 10.00%', str(layout(doc)))
        for _ in range(3):
            doc = edit(doc, self.edits(doc))
            self.assertEqual(doc['totals']['grand_total'], '43.32')
        issued = self.issue(preview)
        self.assertEqual(issued.status_code, 201, issued.json)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            self.assertTrue(any('-3.70' in (node.text or '') for node in sheet.findall('.//{*}f')))

    def test_total_visibility_and_removal(self):
        self.assertEqual(self.save(scope='total', type='amount', value='5').status_code, 200)
        doc = self.preview()['document']
        self.assertEqual(doc['totals']['summary_discount'], '5.00')
        self.assertEqual(doc['totals']['grand_total'], '42.02')
        model = layout(doc)
        bank = next(section for section in model['sections'] if section['name'] == 'bank')
        labels = [cell['text'] for row in bank['rows'] for cell in row]
        self.assertLess(labels.index('Discount'), labels.index('Shipping'))
        self.assertEqual(self.save(scope='total', type='amount', value='5', show_on_pi=False).status_code, 200)
        hidden = self.preview()['document']
        self.assertEqual(hidden['totals']['grand_total'], '42.02')
        self.assertEqual(hidden['totals']['lines'][0]['line_total'], '32.02')
        self.assertNotIn('Discount', str(layout(hidden)))
        self.assertEqual(self.client.delete(f'/api/orders/{self.order_id}/discount').status_code, 200)
        self.assertEqual(self.preview()['document']['totals']['grand_total'], '47.02')

    def test_validation_and_foreign_line_ids(self):
        for data in [dict(value='101'), dict(value='-1'), dict(value=True), dict(value='NaN'),
                     dict(type='amount', value='999'), dict(scope='single', line_ids=[]),
                     dict(scope='single', line_ids=[999999]), dict(show_on_pi='yes')]:
            self.assertEqual(self.save(**data).status_code, 400, data)

    def test_single_multiple_and_bulk_exports(self):
        test_bulk_pi.BulkPiTests.items(self, 5)
        lines = self.client.get(f'/api/orders/{self.order_id}').json['lines']
        first, second = lines[0]['id'], lines[1]['id']
        for scope, ids in [('single', [first]), ('multiple', [first, second])]:
            self.assertEqual(self.save(scope=scope, line_ids=ids).status_code, 200)
            doc = self.preview(bulk_description='Mixed spare parts')['document']
            discounted = [line['id'] for line in doc['totals']['lines'] if Decimal(line['discount_amount'])]
            self.assertEqual(discounted, ids)
        self.assertEqual(self.save(scope='total', type='amount', value='7').status_code, 200)
        preview = self.preview(bulk_description='Mixed spare parts')
        doc = preview['document']
        summary_items = next(section for section in layout(doc)['sections'] if section['name']=='items')
        self.assertEqual(summary_items['rows'][1][-1]['text'], doc['totals']['goods_total'])
        issued = self.issue(preview)
        self.assertEqual(issued.status_code, 201, issued.json)
        self.assertTrue(self.client.get(issued.json['pdf_url']).data.startswith(b'%PDF-'))
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            self.assertTrue(any('-7.00' in (node.text or '') for node in sheet.findall('.//{*}f')))

    def test_read_only_and_other_client_cannot_change_discount(self):
        self.share('VIEW')
        self.as_user('exec2')
        self.assertEqual(self.save().status_code, 403)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order_id}/discount').status_code, 403)
        self.as_user('tl2')
        self.assertEqual(self.save().status_code, 404)

    def test_currency_conversion_gst_and_fixed_discount_survive_edits(self):
        self.assertEqual(self.save(type='amount', value='2').status_code, 200)
        doc = self.preview(currency='INR')['document']
        self.assertEqual(doc['totals']['discount_total'], '160.00')
        self.assertEqual(doc['totals']['subtotal'], '2801.60')
        self.assertEqual(doc['totals']['tax'], '648.29')
        for _ in range(2):
            doc = edit(doc, self.edits(doc))
            self.assertEqual(doc['totals']['discount_total'], '160.00')


class AllocationTests(unittest.TestCase):
    def test_hidden_total_cent_allocation_reconciles(self):
        lines = [dict(id=i, unit_price='0.01', quantity='1', currency='USD') for i in range(50)]
        state = dict(order=dict(currency='USD', shipping_charges='0', discount=dict(
            type='amount', value='0.26', scope='total', line_ids=[], show_on_pi=False)), lines=lines)
        totals = calculate(state, 'USD', None, Decimal(0))
        self.assertEqual(totals['grand_total'], '0.24')
        self.assertTrue(all(Decimal(line['line_total']) >= 0 for line in totals['lines']))


if __name__ == '__main__':
    unittest.main()
