"""Shared configuration authorization, validation and audit coverage."""
import unittest

import test_leads
from backend import database
from backend.settings import bp


class SettingsTests(unittest.TestCase):
    as_user = test_leads.LeadTests.as_user

    def setUp(self):
        test_leads.LeadTests.setUp(self)
        self.client.application.register_blueprint(bp)

    def test_only_team_leads_and_admins_can_read_and_write(self):
        for name, status in [(None,401),('exec1',403),('legacy',403),('unknown',403),
                             ('tl1',200),('admin',200),('manager',200)]:
            self.as_user(name)
            self.assertEqual(self.client.get('/api/settings').status_code,status)
            self.assertEqual(self.client.put('/api/settings',json={'hsn_code':'85371090'}).status_code,status)
            response=self.client.get('/configuration')
            self.assertEqual(response.status_code,302 if name is None else status)
            response.close()

    def test_validation_persistence_and_audit(self):
        self.as_user('tl1')
        for value in ('','123','12345','123456789','85AB',None,85371090):
            self.assertEqual(self.client.put('/api/settings',json={'hsn_code':value}).status_code,400)
        for value in ('0012','853710','85371090'):
            self.assertEqual(self.client.put('/api/settings',json={'hsn_code':value}).status_code,200)
            self.assertEqual(self.client.get('/api/settings').json['hsn_code'],value)
        connection=database.get_db()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM audit_logs WHERE action='settings_update'").fetchone()[0],3)
        finally:
            connection.close()

    def test_sales_can_read_item_defaults_without_configuration_access(self):
        connection = database.get_db()
        with connection:
            connection.execute("UPDATE app_settings SET value='85371090' WHERE key='hsn_code'")
        connection.close()
        self.as_user(None)
        self.assertEqual(self.client.get('/api/sku-defaults').status_code, 401)
        self.as_user('exec1')
        response = self.client.get('/api/sku-defaults')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'shared_hsn_code': '85371090'})
        self.assertEqual(self.client.get('/api/settings').status_code, 403)
        self.assertEqual(self.client.put('/api/sku-defaults', json={'shared_hsn_code': '1234'}).status_code, 405)
        connection = database.get_db()
        with connection:
            connection.execute('UPDATE users SET is_active=0 WHERE id=?', (self.ids['exec1'],))
        connection.close()
        self.assertEqual(self.client.get('/api/sku-defaults').status_code, 401)
