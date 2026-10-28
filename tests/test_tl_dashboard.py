"""Team reporting, scoped PI downloads, lookup attribution and retention."""
import json
import unittest
from unittest.mock import patch
from flask import Flask

import test_pi_search
from backend import database
from backend.quotation_tool.routes import bp as quotation_bp


class TeamDashboardTests(unittest.TestCase):
    setUp = test_pi_search.PiSearchTests.setUp
    direct = test_pi_search.PiSearchTests.direct
    as_user = test_pi_search.PiSearchTests.as_user
    create = test_pi_search.PiSearchTests.create
    enquiry = test_pi_search.PiSearchTests.enquiry
    assign = test_pi_search.PiSearchTests.assign
    invoice = test_pi_search.PiSearchTests.invoice

    def get(self, section='summary', **query):
        return self.client.get('/api/tl-dashboard/'+section, query_string=query)

    def log(self, user, skus, ts='2026-10-15 10:00:00'):
        connection = database.get_db()
        with connection:
            connection.execute('INSERT INTO search_logs(user_name,skus,ts) VALUES(?,?,?)', (user, skus, ts))
        connection.close()

    def test_separate_page_and_role_authorization(self):
        self.assertEqual(self.get().status_code, 403)
        for user in ('tl1', 'admin', 'manager'):
            self.as_user(user)
            with self.client.get('/tl-dashboard') as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'team.js', response.data)
            self.assertEqual(self.get().status_code, 200)
        self.as_user(None)
        self.assertEqual(self.get().status_code, 401)
        self.assertEqual(self.client.get('/tl-dashboard').status_code, 302)

    def test_summary_attributes_creator_and_excludes_removed_pis(self):
        order, first = self.invoice()
        _, removed = self.invoice(order_id=order)
        connection = database.get_db()
        with connection:
            connection.execute('UPDATE order_invoices SET created_by=? WHERE id=?', (self.ids['admin'], first))
            connection.execute("UPDATE order_invoices SET deleted_at='2026-10-16T00:00:00Z' WHERE id=?", (removed,))
        connection.close()
        self.as_user('admin')
        data = self.get().json
        rows = {row['username']:row for row in data['rows']}
        self.assertEqual(rows['exec1']['clients'], 1)
        self.assertEqual(rows['exec1']['pis'], 0)
        self.assertEqual(rows['admin']['pis'], 1)
        self.assertEqual(data['totals'], {'clients':1, 'pis':1})
        self.assertTrue(data['can_cleanup'])

    def test_team_scope_and_forged_user_filters(self):
        self.invoice()
        self.log('exec1', 'A'); self.log('exec2', 'B')
        self.assign('exec1', 'tl1'); self.assign('exec2', 'tl2')
        self.as_user('tl1')
        data = self.get().json
        self.assertEqual({u['username'] for u in data['users']}, {'exec1', 'tl1'})
        self.assertEqual(data['totals'], {'clients':1, 'pis':1})
        self.assertFalse(data['can_cleanup'])
        self.assertEqual([row['sku'] for row in self.get('lookups').json['rows']], ['A'])
        for endpoint in ('summary', 'pis', 'lookups'):
            self.assertEqual(self.get(endpoint, user_id=self.ids['exec2']).status_code, 403)
        self.assign('exec1', 'tl2'); self.as_user('tl1')
        self.assertEqual(self.get().json['totals'], {'clients':0, 'pis':0})
        self.assertEqual(self.get('lookups').json['total'], 0)

    def test_date_filters_use_inclusive_ist_days_and_validate_input(self):
        _, invoice = self.invoice()
        connection = database.get_db()
        with connection:
            for table, ident in (('client_leads', self.parent), ('order_invoices', invoice)):
                connection.execute('UPDATE '+table+' SET created_at=? WHERE id=?', ('2026-10-15T20:00:00Z', ident))
        connection.close()
        self.as_user('admin')
        self.assertEqual(self.get(**{'from':'2026-10-16','to':'2026-10-16'}).json['totals'], {'clients':1, 'pis':1})
        self.assertEqual(self.get(**{'to':'2026-10-15'}).json['totals'], {'clients':0, 'pis':0})
        for query in ({'from':'bad'}, {'from':'2026-10-17','to':'2026-10-16'}, {'user_id':'bad'}):
            self.assertEqual(self.get(**query).status_code, 400)

    def test_pi_list_groups_clients_and_keeps_duplicate_pi_numbers(self):
        order, first = self.invoice(reference='SAME')
        _, second = self.invoice(reference='SAME', order_id=order, legacy=True)
        other = self.client.post('/api/leads', json={'name':'Another client'}).json['lead']['id']
        third_order = self.direct(client_id=other)['order']['id']
        self.invoice(order_id=third_order)
        self.as_user('admin')
        data = self.get('pis', user_id=self.ids['exec1']).json
        self.assertEqual((data['total'], data['clients']), (3, 2))
        self.assertEqual({row['id'] for row in data['rows'] if row['reference']=='SAME'}, {first,second})
        for row in data['rows']:
            self.assertEqual(row['client_pis'], 2 if row['client_id']==self.parent else 1)
            self.assertEqual(self.client.get(row['excel_url']).data, b'Excel fixture')
            if row['id']==second:
                self.assertIsNone(row['pdf_url'])
            else:
                self.assertEqual(self.client.get(row['pdf_url']).data, b'PDF fixture')
        self.assertEqual(self.get('pis').status_code, 400)

    def test_lookup_frequencies_user_date_sku_and_pagination(self):
        self.log('exec1', 'part, PART ,B')
        self.log('exec1', 'Part', '2026-10-16 00:00:00')
        self.log('exec2', 'PART', '2026-10-14 23:59:59')
        self.as_user('admin')
        data = self.get('lookups').json
        self.assertEqual((data['requests'],data['unique_skus'],data['total']), (3,2,3))
        self.assertEqual(data['rows'][0]['searches'], 2)
        data = self.get('lookups', user_id=self.ids['exec1'], **{'from':'2026-10-16','to':'2026-10-16'}).json
        self.assertEqual((data['requests'],data['rows'][0]['searches']), (1,1))
        self.assertEqual(self.get('lookups', sku='%').json['total'], 0)
        self.assertEqual(self.get('lookups', sku='par').json['total'], 2)
        for n in range(26): self.log('exec1', 'SKU'+str(n))
        page = self.get('lookups', page=2).json
        self.assertEqual((page['total'],page['pages'],len(page['rows'])), (29,2,4))

    def test_cleanup_admin_only_preview_guard_cutoff_and_audit(self):
        self.invoice()
        self.log('exec1', 'OLD', '2020-01-01 23:59:59')
        self.log('exec2', 'KEEP', '2020-01-02 00:00:00')
        path = '/api/tl-dashboard/lookup-cleanup'
        self.as_user('tl1')
        self.assertEqual(self.client.get(path, query_string={'before':'2020-01-02'}).status_code, 403)
        self.assertEqual(self.client.delete(path, json={'before':'2020-01-02','expected_count':1}).status_code, 403)
        self.as_user('admin')
        self.assertEqual(self.client.get(path, query_string={'before':'2020-01-02'}).json['count'], 1)
        self.assertEqual(self.client.delete(path, json={'before':'2020-01-02','expected_count':2}).status_code, 409)
        result = self.client.delete(path, json={'before':'2020-01-02','expected_count':1})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['count'], 1)
        self.assertEqual(self.get('lookups').json['rows'][0]['sku'], 'KEEP')
        self.assertEqual(self.get().json['totals'], {'clients':1,'pis':1})
        connection = database.get_db()
        audit = connection.execute("SELECT details FROM audit_logs WHERE action='lookup_history_cleanup'").fetchone()
        connection.close()
        self.assertEqual(json.loads(audit[0])['deleted_records'], 1)
        for body in ([], 'before', {'before':'2099-01-01','expected_count':0}, {'before':'bad'}, {'before':'2020-01-02'}):
            self.assertEqual(self.client.delete(path,json=body).status_code, 400)

    def test_manual_bulk_and_single_lookups_are_logged_but_stock_checks_are_not(self):
        self.direct()
        connection = database.get_db()
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM search_logs').fetchone()[0], 0)
        connection.close()
        with patch('backend.enquiries.lines.lookup_product', return_value={'found':True,'price':10,'Quantity':5}), patch('backend.enquiries.lines.lookup_rate', return_value=80):
            response = self.client.post('/api/enquiries/sku-lookup', json={'client_id':self.parent,'skus':['A','B'],'currency':'USD'})
            self.assertEqual(response.status_code, 200, response.json)
            response = self.client.post(f'/api/enquiries/{self.enquiry_id}/sku-lookup', json={'sku':'A'})
            self.assertEqual(response.status_code, 200, response.json)
        self.as_user('admin')
        rows = self.get('lookups').json['rows']
        self.assertEqual([(row['user_name'],row['sku'],row['searches']) for row in rows], [('exec1','A',2),('exec1','B',1)])

    def test_quotation_lookup_uses_database_identity(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-only-key')
        app.register_blueprint(quotation_bp)
        client = app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = self.ids['exec1']
            session['username'] = 'forged-other-user'
        with patch('backend.quotation_tool.routes.fetch_sku', return_value={'found':True}), patch('backend.quotation_tool.routes.threading.Thread') as thread:
            self.assertEqual(client.post('/api/lookup',json={'skus':['A']}).status_code, 200)
            self.assertEqual(thread.call_args.kwargs['args'][0], 'exec1')


if __name__ == '__main__':
    unittest.main()
