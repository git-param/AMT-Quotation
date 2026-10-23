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

    def test_admin_configures_sku_lookup_limit(self):
        self.as_user('exec1')
        self.assertEqual(self.client.get('/api/sku-lookup-limit').json['max_sku_lookup'], 50)
        self.assertEqual(self.client.put('/api/sku-lookup-limit',
                                        json={'max_sku_lookup': 2}).status_code, 403)
        self.as_user('tl1')
        self.assertEqual(self.client.put('/api/sku-lookup-limit',
                                        json={'max_sku_lookup': 2}).status_code, 403)
        self.as_user('admin')
        for value in (None, 0, -1, 501, True, '2', 2.5):
            self.assertEqual(self.client.put('/api/sku-lookup-limit',
                                            json={'max_sku_lookup': value}).status_code, 400)
        self.assertEqual(self.client.put('/api/sku-lookup-limit',
                                        json={'max_sku_lookup': 2}).status_code, 200)
        self.as_user('exec1')
        self.assertEqual(self.client.get('/api/sku-lookup-limit').json['max_sku_lookup'], 2)
        connection = database.get_db()
        with connection:
            connection.execute(
                "INSERT INTO api_keys(key,label) VALUES('amtq-limit-test','Inbox')"
            )
        connection.close()
        self.as_user(None)
        headers = {'X-API-Key': 'amtq-limit-test'}
        self.assertEqual(self.client.get('/api/sku-lookup-limit',
                                         headers=headers).status_code, 403)
        self.assertEqual(self.client.put('/api/sku-lookup-limit', headers=headers,
                                         json={'max_sku_lookup': 3}).status_code, 401)
        connection = database.get_db()
        try:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action='sku_lookup_limit_update'"
            ).fetchone()[0], 1)
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

    def test_admin_department_pi_prefix_configuration_and_permissions(self):
        self.as_user('admin')
        result = self.client.post('/api/departments', json={'name': 'Sales', 'pi_prefix': 'AMT/'})
        self.assertEqual(result.status_code, 201)
        department = result.json['department_settings'][0]
        self.assertEqual(department['pi_prefix'], 'AMT')
        url = f"/api/departments/{department['id']}/pi-prefix"
        self.as_user('tl1')
        self.assertEqual(self.client.put(url, json={'pi_prefix': 'PUC'}).status_code, 403)
        self.as_user('exec1')
        self.assertEqual(self.client.put(url, json={'pi_prefix': 'PUC'}).status_code, 403)
        self.as_user('admin')
        for invalid in ('A/B', 'x' * 21, None, '<script>', 'with space'):
            self.assertEqual(self.client.put(url, json={'pi_prefix': invalid}).status_code, 400)
        self.assertEqual(self.client.put(url, json={'pi_prefix': 'PUC'}).status_code, 200)
        self.assertEqual(self.client.get('/api/departments').json['department_settings'][0]['pi_prefix'], 'PUC')
        self.assertEqual(self.client.put(url, json={'pi_prefix': ''}).status_code, 200)
        self.assertEqual(self.client.put('/api/departments/9999/pi-prefix', json={'pi_prefix': 'AMT'}).status_code, 404)

    def test_departments_admin_creation_validation_and_dropdown_choices(self):
        for name, expected in [(None, 401), ('exec1', 403), ('tl1', 403), ('admin', 201), ('manager', 201)]:
            self.as_user(name)
            response = self.client.post('/api/departments', json={'name': name or 'Anonymous'})
            self.assertEqual(response.status_code, expected)
        self.as_user('admin')
        for payload in ({}, [], {'name': ''}, {'name': ' '}, {'name': None},
                        {'name': 123}, {'name': 'x' * 101}):
            self.assertEqual(self.client.post('/api/departments', json=payload).status_code, 400)
        self.assertEqual(self.client.post('/api/departments', json={'name': '  Sales  '}).status_code, 201)
        self.assertEqual(self.client.post('/api/departments', json={'name': 'sales'}).status_code, 409)
        choices = self.client.get('/api/manager/users').json['departments']
        self.assertIn('Sales', choices)
        user = {'username': 'dept-user', 'password': 'test-password', 'department': 'Unconfigured'}
        self.assertEqual(self.client.post('/api/manager/users/add', json=user).status_code, 400)
        self.assertEqual(self.client.post('/api/manager/users/add', json={**user, 'department': 'sales'}).status_code, 200)
        created = next(u for u in self.client.get('/api/manager/users').json['users'] if u['username'] == 'dept-user')
        self.assertEqual(created['department'], 'Sales')
        self.as_user('tl1')
        self.assertIn('Sales', self.client.get('/api/departments').json['departments'])
        connection = database.get_db()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM audit_logs WHERE action='department_create'").fetchone()[0], 3)
        finally:
            connection.close()
