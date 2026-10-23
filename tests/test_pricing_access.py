"""Pricing App security policy behavior."""
import unittest
from unittest.mock import patch

from backend.security import pricing_access


class PricingAccessTests(unittest.TestCase):
    def test_reads_shared_config_and_user_ips(self):
        class Cursor:
            def __init__(self):
                self.queries = []
            def execute(self, query):
                self.queries.append(query)
            def fetchall(self):
                if len(self.queries) == 1:
                    return [{'key': 'ip_enforce', 'value': '1'},
                            {'key': 'office_ips', 'value': '8.8.8.0/24'}]
                return [{'username': 'Alice', 'ips': '1.1.1.1'}]
            def close(self):
                pass
        cursor = Cursor()
        class Connection:
            def cursor(self):
                return cursor
            def close(self):
                pass
        pricing_access._cache.update(at=0.0, policy=None)
        with patch.object(pricing_access, 'connect', return_value=Connection()):
            policy = pricing_access.load_policy()
        self.assertIn('public.sec_config', cursor.queries[0])
        self.assertIn('public.sec_user_ips', cursor.queries[1])
        self.assertEqual(policy['_users']['alice'], '1.1.1.1')
        pricing_access._cache.update(at=0.0, policy=None)

    def test_office_user_and_admin_rules(self):
        policy = {'ip_enforce': '1', 'office_ips': '8.8.8.0/24',
                  '_users': {'alice': '1.1.1.1'}}
        with patch.object(pricing_access, 'load_policy', return_value=policy):
            self.assertTrue(pricing_access.access_decision('Alice', 'sales_executive', '1.1.1.1')[0])
            self.assertTrue(pricing_access.access_decision('Bob', 'sales_executive', '8.8.8.8')[0])
            self.assertFalse(pricing_access.access_decision('Bob', 'sales_executive', '9.9.9.9')[0])
            self.assertTrue(pricing_access.access_decision('Admin', 'admin', '9.9.9.9')[0])
            policy['admin_anywhere'] = '0'
            self.assertFalse(pricing_access.access_decision('Admin', 'admin', '9.9.9.9')[0])

    def test_database_unavailable_uses_last_good_policy(self):
        policy = {'ip_enforce': '1', 'office_ips': '8.8.8.8', '_users': {}}
        pricing_access._cache.update(at=0.0, policy=policy)
        with patch.object(pricing_access, 'connect', side_effect=OSError('offline')):
            self.assertEqual(pricing_access.load_policy(), policy)
        pricing_access._cache.update(at=0.0, policy=None)


if __name__ == '__main__':
    unittest.main()
