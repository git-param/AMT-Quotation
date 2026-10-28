"""Production quotation behavior kept when the app is modularized."""
import unittest
from unittest.mock import patch
from flask import Flask

from backend.quotation_tool.blog_lookup import lookup_ref
from backend.quotation_tool.images import _host_ok
from backend.quotation_tool.price_history import search_price_history
from backend.quotation_tool.quote_builder import _q_build_table
from backend.quotation_tool.shopify import fetch_skus_batch, _sku_cache
from backend.quotation_tool.routes import api_quotation_letter


class ProductionParityTests(unittest.TestCase):
    def test_partner_lookup_requires_reference_in_post_and_leaves_price_unknown(self):
        ref = 'AM395/1.150'
        entry = {
            'title': {'$t': 'Pump motor'},
            'content': {'$t': '<p>REF: AM395/1.150</p><p>CONDITION: USED 4 PCS</p>'},
            'link': [{'rel': 'alternate', 'href': 'https://atlasship.blogspot.com/post'}],
        }
        response = type('Response', (), {
            'status_code': 200, 'raise_for_status': lambda self: None,
            'json': lambda self: {'feed': {'entry': [entry]}},
        })()
        with patch('backend.quotation_tool.blog_lookup.requests.get', return_value=response):
            result = lookup_ref(ref)
        self.assertEqual(result['source'], 'atlas')
        self.assertEqual(result['Quantity'], 4)
        self.assertIsNone(result['price'])
        self.assertEqual(result['condition'], 'USED')

    def test_price_recheck_and_partner_link_are_not_presented_as_an_offer(self):
        rows = [{'found': True, 'sku': 'A', 'title': 'Part', 'condition': 'Used',
                 'price': 100, 'sale_price': 80, 'Quantity': 1,
                 'source': 'atlas', 'url': 'https://atlasship.blogspot.com/post'}]
        html = _q_build_table(rows, 'USD', 0)
        self.assertIn('Price recheck needed', html)
        self.assertIn('Attached', html)
        self.assertNotIn('href="https://atlasship', html)

    def test_image_proxy_rejects_untrusted_hosts(self):
        self.assertTrue(_host_ok('https://1.bp.blogspot.com/image.jpg'))
        self.assertFalse(_host_ok('https://bp.blogspot.com.evil.test/image.jpg'))
        self.assertFalse(_host_ok('http://127.0.0.1/image.jpg'))

    def test_price_history_uses_calendar_order_and_computes_change(self):
        rows = [
            dict(year=2026, month=10, day=1, sku='26733', price=125,
                 created_at='2026-10-01', exec_name='System', remarks='', ref='',
                 entry_type='', lot_set_pack=''),
            dict(year=2026, month=9, day=1, sku='26733', price=100,
                 created_at='2026-09-01', exec_name='Alice', remarks='', ref='',
                 entry_type='', lot_set_pack=''),
        ]
        class Cursor:
            def execute(self, query, params):
                self.query = query
            def fetchall(self):
                return rows
            def close(self):
                pass
        class Connection:
            def cursor(self):
                return Cursor()
            def close(self):
                pass
        with patch('backend.quotation_tool.price_history.connect', return_value=Connection()):
            result = search_price_history('26733')
        self.assertEqual(result[0]['delta_pct'], 25)
        self.assertTrue(result[0]['automated'])
        self.assertEqual(result[0]['date'], '2026-10-01')

    def test_shopify_batch_preserves_sale_price_and_uses_one_request(self):
        def post(url, headers, json, timeout):
            self.assertIn('sku:', json['query'])
            return type('Response', (), {
                'status_code': 200,
                'json': lambda self: {'data': {'productVariants': {'edges': [
                    {'node': {'sku': 'BATCH-1', 'price': '95',
                              'compareAtPrice': '100', 'inventoryQuantity': 2,
                              'product': {'title': 'Pump', 'onlineStoreUrl': 'https://example.com',
                                          'tags': ['Condition: Used']}}},
                    {'node': {'sku': 'BATCH-2', 'price': '25',
                              'compareAtPrice': None, 'inventoryQuantity': 1,
                              'product': {'title': 'Motor', 'onlineStoreUrl': '', 'tags': []}}},
                ]}}},
            })()
        _sku_cache.clear()
        with patch('backend.quotation_tool.shopify._get_token', return_value='test'), \
                patch('backend.quotation_tool.shopify._storefront_condition',
                      return_value='Used'), \
                patch('backend.quotation_tool.shopify.requests.post', side_effect=post) as request:
            rows = fetch_skus_batch(['BATCH-1', 'BATCH-2'])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(rows['BATCH-1']['price'], 100)
        self.assertEqual(rows['BATCH-1']['sale_price'], 95)
        self.assertEqual(rows['BATCH-1']['condition'], 'Used/Second Hand')
        self.assertIsNone(rows['BATCH-2']['sale_price'])

    def test_letter_api_returns_html_text_and_rows(self):
        app = Flask(__name__)
        product = {'sku_input': '26733', 'sku': '26733', 'found': True,
                   'title': 'Pump', 'condition': 'Used', 'price': 100.0,
                   'sale_price': None, 'Quantity': 1, 'url': ''}
        with app.test_request_context('/api/quotation/letter', method='POST',
                                      json={'skus': ['26733'], 'currency': 'USD'}), \
                patch('backend.quotation_tool.routes._lookup_rows', return_value=[product]), \
                patch('backend.quotation_tool.routes.enforce_sku_lookup_limit'), \
                patch('backend.quotation_tool.routes.threading.Thread'), \
                patch('backend.quotation_tool.routes.request_actor_name', return_value='Tester'):
            response = api_quotation_letter.__wrapped__()
        data = response.get_json()
        self.assertIn('Dear Sir/Madam', data['html'])
        self.assertIn('Pump', data['text'])
        self.assertEqual(data['found'], 1)
        self.assertEqual(data['rows'][0]['sku'], '26733')


if __name__ == '__main__':
    unittest.main()
