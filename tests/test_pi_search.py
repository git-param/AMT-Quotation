"""Saved PI search, scoped visibility, pagination and existing downloads."""
import unittest
import json

import test_clients_orders
from backend import database


class PiSearchTests(unittest.TestCase):
    setUp = test_clients_orders.WorkspaceTests.setUp
    direct = test_clients_orders.WorkspaceTests.direct
    as_user = test_clients_orders.WorkspaceTests.as_user
    create = test_clients_orders.WorkspaceTests.create
    enquiry = test_clients_orders.WorkspaceTests.enquiry
    assign = test_clients_orders.WorkspaceTests.assign
    share = test_clients_orders.WorkspaceTests.share

    def invoice(self, reference='SEARCH/PI/001', currency='USD', legacy=False, order_id=None):
        if order_id is None:
            order_id=self.direct(po_reference='SEARCH-PO')['order']['id']
        connection=database.get_db()
        try:
            with connection:
                user=connection.execute('SELECT created_by FROM client_orders WHERE id=?',(order_id,)).fetchone()[0]
                cursor=connection.execute('INSERT INTO order_invoices(order_id,reference,currency,snapshot_json,workbook,created_by,workbook_format,pdf) '
                    'VALUES(?,?,?,?,?,?,?,?)',(order_id,reference,currency,json.dumps({'reference':reference,'order':{'po_reference':'SEARCH-PO','destination':'USA'},'delivery':{'consignee_text':'Company\nStreet\nTel/Phone: +12025550123\nPIC: Person\nEmail: person@example.com\nGST No.: 24TEST123'}}),b'Excel fixture',user,'xlsm' if legacy else 'xlsx',None if legacy else b'PDF fixture'))
                return order_id,cursor.lastrowid
        finally:connection.close()

    def search(self, **query):
        return self.client.get('/api/pi-search',query_string=query)

    def test_results_include_client_order_and_correct_downloads(self):
        order_id,invoice_id=self.invoice()
        with self.client.get('/search-pi') as page:
            self.assertEqual(page.status_code,200)
        response=self.search();self.assertEqual(response.status_code,200,response.json)
        row=response.json['invoices'][0]
        self.assertEqual(row['id'],invoice_id);self.assertEqual(row['order_id'],order_id)
        self.assertEqual(row['client_id'],self.parent);self.assertTrue(row['client_name'])
        self.assertEqual(self.client.get(row['excel_url']).data,b'Excel fixture')
        self.assertEqual(self.client.get(row['pdf_url']).data,b'PDF fixture')
        self.assertNotIn('workbook',row);self.assertNotIn('snapshot_json',row)

    def test_search_by_pi_client_company_order_and_po(self):
        self.invoice()
        row=self.search().json['invoices'][0]
        for term in (row['reference'].lower(),row['client_name'],row['order_reference'],'SEARCH-PO'):
            self.assertEqual(self.search(q=term).json['total'],1,term)
        self.assertEqual(self.search(q='no-such-client').json['total'],0)
        self.client.put(f'/api/leads/{self.parent}',json={'company':'Searchable Marine Company'})
        self.assertEqual(self.search(q='marine company').json['total'],1)

    def test_same_pi_numbers_remain_separate_and_paginate(self):
        order_id,first=self.invoice();_,second=self.invoice(order_id=order_id)
        self.invoice(currency='INR')
        response=self.search(currency='USD',page_size=1,page=1).json
        self.assertEqual(response['total'],2);self.assertEqual(response['pages'],2)
        page2=self.search(currency='USD',page_size=1,page=2).json
        self.assertEqual({response['invoices'][0]['id'],page2['invoices'][0]['id']},{first,second})

    def test_legacy_excel_has_no_pdf_download(self):
        self.invoice(legacy=True)
        row=self.search().json['invoices'][0]
        self.assertEqual(row['workbook_format'],'xlsm');self.assertIsNone(row['pdf_url'])
        self.assertIn('format=xlsm',row['excel_url'])
        self.assertEqual(self.client.get(row['excel_url']).data,b'Excel fixture')

    def test_search_visibility_and_downloads_follow_current_sharing(self):
        self.invoice();self.as_user('exec2')
        self.assertEqual(self.search().json['total'],0)
        self.share('VIEW');self.as_user('exec2')
        row=self.search().json['invoices'][0]
        self.assertEqual(self.client.get(row['pdf_url']).status_code,200)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/revoke',json={'user_id':self.ids['exec2']})
        self.as_user('exec2')
        self.assertEqual(self.search().json['total'],0)
        self.assertEqual(self.client.get(row['pdf_url']).status_code,404)
        self.as_user(None)
        self.assertEqual(self.search().status_code,401)
        self.assertEqual(self.client.get('/search-pi').status_code,302)

    def test_deleted_orders_are_excluded_and_wildcards_are_literal(self):
        order_id,_=self.invoice(reference='PI%_literal')
        self.assertEqual(self.search(q='%_').json['total'],1)
        self.assertEqual(self.search(q="' OR 1=1 --").json['total'],0)
        self.assertEqual(self.client.delete(f'/api/orders/{order_id}').status_code,200)
        self.assertEqual(self.search().json['total'],0)

    def test_invalid_filters_are_rejected(self):
        self.direct()
        for query in ({'page':0},{'page_size':101},{'currency':'CHF'},{'q':'x'*201}):
            self.assertEqual(self.search(**query).status_code,400,query)

    def test_removing_one_pi_keeps_other_records_with_same_number(self):
        order_id,first=self.invoice();_,second=self.invoice(order_id=order_id)
        self.assertEqual(self.client.delete(f'/api/orders/{order_id}/invoices/{first}').status_code,200)
        results=self.search().json
        self.assertEqual(results['total'],1);self.assertEqual(results['invoices'][0]['id'],second)
        self.assertEqual(self.client.get(results['invoices'][0]['excel_url']).status_code,200)


if __name__=='__main__':
    unittest.main()
