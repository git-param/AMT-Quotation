"""Fresh provider reads and aggregate stock validation without network access."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.orders.catalog import lookup_stock, validate_stock_batch
from backend import database
from backend.migrations import migrate_database


class StockTests(unittest.TestCase):
    def test_stock_lookup_explicitly_bypasses_provider_cache(self):
        with patch.dict(os.environ, {'SHOPIFY_SHOP':'example.invalid',
                                    'SHOPIFY_CLIENT_ID':'fixture',
                                    'SHOPIFY_CLIENT_SECRET':'fixture'}):
            from backend.quotation_tool import shopify
        with patch.object(shopify, 'fetch_sku', return_value={'found':True,'Quantity':2}) as lookup:
            self.assertEqual(lookup_stock('PART')['Quantity'],2)
            lookup.assert_called_once_with('PART',refresh=True)

    def test_refresh_ignores_cached_stock_and_updates_cache(self):
        with patch.dict(os.environ, {'SHOPIFY_SHOP':'example.invalid',
                                    'SHOPIFY_CLIENT_ID':'fixture',
                                    'SHOPIFY_CLIENT_SECRET':'fixture'}):
            from backend.quotation_tool import shopify
        response=Mock(status_code=200)
        response.json.return_value={'data':{'productVariants':{'edges':[{'node':{
            'sku':'PART','price':'10','inventoryQuantity':2,'product':{'title':'Part'}
        }}]}}}
        cache={'PART':({'found':True,'Quantity':100},shopify.time.time())}
        with patch.object(shopify,'_sku_cache',cache), \
                patch.object(shopify,'_get_token',return_value='fixture'), \
                patch.object(shopify.requests,'post',return_value=response) as request:
            self.assertEqual(shopify.fetch_sku('PART')['Quantity'],100)
            request.assert_not_called()
            self.assertEqual(shopify.fetch_sku('PART',refresh=True)['Quantity'],2)
            request.assert_called_once()
            self.assertEqual(shopify.fetch_sku('PART')['Quantity'],2)
            self.assertEqual(request.call_count,1)

    def test_batch_checks_each_sku_once_and_reports_all_failures(self):
        products=[{'found':True,'Quantity':2},{'found':True,'Quantity':0},RuntimeError('Offline')]
        with patch('backend.orders.catalog.enforce_sku_lookup_limit'), \
                patch('backend.orders.catalog.lookup_stock',side_effect=products) as lookup:
            with self.assertRaises(ValueError) as error:
                validate_stock_batch([('PART-A',2),('part-a',1),('PART-B',1),('PART-C',1)])
            message=str(error.exception)
            self.assertIn('PART-A: requested 3, but only 2 available',message)
            self.assertIn('PART-B: requested 1, but only 0 available',message)
            self.assertIn('PART-C: stock lookup failed',message)
            self.assertEqual(lookup.call_count,3)

    def test_stock_batch_limit_blocks_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stock.db'
            migrate_database(path)
            with patch.object(database, 'DB_PATH', str(path)):
                connection = database.get_db()
                with connection:
                    connection.execute(
                        "UPDATE app_settings SET value='1' WHERE key='sku_lookup_limit'"
                    )
                connection.close()
                with patch('backend.orders.catalog.lookup_stock') as lookup:
                    with self.assertRaisesRegex(ValueError, 'at most 1 SKU'):
                        validate_stock_batch([('A', 1), ('B', 1)])
                    lookup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
