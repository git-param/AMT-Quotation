"""PI numbers are confirmed once, after serialized, successful generation."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import multiprocessing
from threading import Event
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import test_clients_orders
from backend import database
from backend.settings import pi_number_last_used


def hold_worker_lock(db_path, started, release):
    from flask import Flask
    from backend.scalability.pi_generation import serialized_generation
    database.DB_PATH=db_path
    @serialized_generation
    def hold():
        started.set()
        release.wait(15)
        return 'finished'
    with Flask(__name__).test_request_context():
        hold()


class PiGenerationNumberingTests(unittest.TestCase):
    setUpBase=test_clients_orders.WorkspaceTests.setUp
    direct=test_clients_orders.WorkspaceTests.direct
    as_user=test_clients_orders.WorkspaceTests.as_user
    create=test_clients_orders.WorkspaceTests.create
    assign=test_clients_orders.WorkspaceTests.assign
    enquiry=test_clients_orders.WorkspaceTests.enquiry
    share=test_clients_orders.WorkspaceTests.share

    def setUp(self):
        self.setUpBase()
        self.a=self.direct(lines=[self.line('A')])['order']['id']
        parent=self.create('exec2')
        self.b=self.direct(client_id=parent,lines=[self.line('B')])['order']['id']
        db=database.get_db()
        with db:
            for username,prefix in [('exec1','AMT'),('exec2','PUC')]:
                db.execute('INSERT INTO departments(name,pi_prefix) VALUES(?,?)',(prefix,prefix))
                db.execute('UPDATE users SET department=? WHERE id=?',(prefix,self.ids[username]))
        db.close()
        self.client_a=self.client_for('exec1')
        self.client_b=self.client_for('exec2')

    def line(self,sku):
        return {'sku':sku,'description':'Manual part','quantity':'1','unit_price':'100',
                'currency':'USD','manual_entry':True,'hsn_code':'1234','item_condition':'New','uom':'PCs'}

    def client_for(self,name):
        client=self.client.application.test_client()
        with client.session_transaction() as session:session['user_id']=self.ids[name]
        return client

    def preview(self,client,order):
        response=client.post(f'/api/orders/{order}/invoices/preview',json={'currency':'USD'})
        self.assertEqual(response.status_code,201,response.json)
        return response.json

    def issue(self,client,order,preview):
        return client.post(f'/api/orders/{order}/invoices/issue',json={'preview_id':preview['preview_id']})

    def counter(self):
        db=database.get_db()
        try:return pi_number_last_used(db)
        finally:db.close()

    @staticmethod
    def files(doc):
        return ('xlsx:'+doc['reference']).encode(),('pdf:'+doc['reference']).encode()

    def test_preview_update_print_and_calculate_never_consume_number(self):
        first=self.preview(self.client_a,self.a)
        second=self.preview(self.client_a,self.a)
        self.assertEqual(first['document']['reference'],'PI-PENDING')
        base=f"/api/orders/{self.a}/invoices/preview/{second['preview_id']}"
        self.assertEqual(self.client_a.put(base,json={}).status_code,200)
        self.assertEqual(self.client_a.put(base+'?for_generation=1',json={}).status_code,200)
        self.assertEqual(self.client_a.post(base+'/calculate',json={}).status_code,200)
        with patch('backend.orders.pi_preview.pi_exports.pdf',return_value=b'preview'):
            self.assertEqual(self.client_a.post(base+'/print',json={}).status_code,200)
            self.assertEqual(self.client_a.get(base+'/pdf').status_code,200)
        self.assertEqual(self.counter(),0)
        db=database.get_db()
        try:self.assertEqual(db.execute('SELECT pi_reference FROM client_orders WHERE id=?',(self.a,)).fetchone()[0],'')
        finally:db.close()

    def test_generation_overwrites_preview_number_and_commits_both_formats_once(self):
        preview=self.preview(self.client_a,self.a)
        db=database.get_db()
        with db:db.execute("INSERT INTO app_settings(key,value) VALUES('pi_number_last_used','40') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        db.close()
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=self.files) as render:
            result=self.issue(self.client_a,self.a,preview)
            self.assertEqual(result.status_code,201,result.json)
            self.assertEqual(result.json['reference'],'AMT/41')
            retry=self.issue(self.client_a,self.a,preview)
            self.assertEqual(retry.json['id'],result.json['id'])
            self.assertEqual(render.call_count,1)
        self.assertEqual(self.counter(),41)
        db=database.get_db()
        invoice=db.execute('SELECT * FROM order_invoices WHERE id=?',(result.json['id'],)).fetchone()
        self.assertEqual(invoice['workbook'],b'xlsx:AMT/41')
        self.assertEqual(invoice['pdf'],b'pdf:AMT/41')
        self.assertEqual(json.loads(invoice['snapshot_json'])['order']['pi_reference'],'AMT/41')
        db.close()

    def test_second_user_waits_without_blocking_other_database_writes(self):
        a=self.preview(self.client_a,self.a);b=self.preview(self.client_b,self.b)
        started,release=Event(),Event()
        def rendering(doc):
            if doc['reference'].startswith('AMT/'):
                started.set()
                if not release.wait(10):raise ValueError('Test render timed out')
            return self.files(doc)
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=rendering):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(self.issue,self.client_a,self.a,a)
                try:
                    self.assertTrue(started.wait(5))
                    waiting=self.issue(self.client_b,self.b,b)
                    self.assertEqual(waiting.status_code,202,waiting.json)
                    self.assertEqual(waiting.json['status'],'waiting')
                    legacy=self.client_b.post(f'/api/orders/{self.b}/invoices',json={'currency':'USD'})
                    self.assertEqual(legacy.status_code,202,legacy.json)
                    self.assertEqual(self.counter(),0)
                    db=database.get_db()
                    with db:db.execute("INSERT INTO app_settings(key,value) VALUES('test_unrelated_write','ok')")
                    db.close()
                finally:release.set()
                self.assertEqual(future.result(timeout=5).json['reference'],'AMT/1')
            result=self.issue(self.client_b,self.b,b)
            self.assertEqual(result.json['reference'],'PUC/2')
        self.assertEqual(self.counter(),2)

    def test_render_or_commit_failure_releases_lock_and_does_not_consume(self):
        a=self.preview(self.client_a,self.a);b=self.preview(self.client_b,self.b)
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=ValueError('Render failed')):
            self.assertEqual(self.issue(self.client_a,self.a,a).status_code,400)
        self.assertEqual(self.counter(),0)
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=self.files),patch('backend.orders.pi_preview.record_action',side_effect=ValueError('Commit failed')):
            self.assertEqual(self.issue(self.client_a,self.a,a).status_code,400)
        self.assertEqual(self.counter(),0)
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=self.files):
            self.assertEqual(self.issue(self.client_b,self.b,b).json['reference'],'PUC/1')

    def test_other_worker_process_also_causes_waiting(self):
        preview=self.preview(self.client_a,self.a)
        ctx=multiprocessing.get_context('spawn')
        started,release=ctx.Event(),ctx.Event()
        process=ctx.Process(target=hold_worker_lock,args=(str(database.DB_PATH),started,release))
        process.start()
        try:
            self.assertTrue(started.wait(8))
            response=self.issue(self.client_a,self.a,preview)
            self.assertEqual(response.status_code,202,response.json)
        finally:
            release.set();process.join(8)
            if process.is_alive():process.terminate();process.join()
        self.assertEqual(process.exitcode,0)
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=self.files):
            self.assertEqual(self.issue(self.client_a,self.a,preview).json['reference'],'AMT/1')

    def test_editing_confirmed_invoice_reuses_its_number(self):
        preview=self.preview(self.client_a,self.a)
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=self.files):
            first=self.issue(self.client_a,self.a,preview).json
            edited=self.client_a.post(f"/api/orders/{self.a}/invoices/{first['id']}/edit-preview",json={})
            self.assertEqual(edited.status_code,200,edited.json.get("error"))
            result=self.issue(self.client_a,self.a,edited.json)
            self.assertEqual(result.status_code,201,result.json)
        self.assertEqual(result.json['id'],first['id'])
        self.assertEqual(result.json['reference'],'AMT/1')
        self.assertEqual(self.counter(),1)

    def test_counter_change_during_render_rejects_without_saving_mismatched_files(self):
        preview=self.preview(self.client_a,self.a)
        def rendering(doc):
            db=database.get_db()
            with db:db.execute("INSERT INTO app_settings(key,value) VALUES('pi_number_last_used','50') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
            db.close()
            return self.files(doc)
        with patch('backend.orders.pi_preview.render_invoice_files',side_effect=rendering):
            self.assertEqual(self.issue(self.client_a,self.a,preview).status_code,409)
        self.assertEqual(self.counter(),50)
        db=database.get_db()
        try:self.assertEqual(db.execute('SELECT count(*) FROM order_invoices').fetchone()[0],0)
        finally:db.close()

    def test_real_exports_contain_the_confirmed_number(self):
        preview=self.preview(self.client_a,self.a)
        result=self.issue(self.client_a,self.a,preview)
        self.assertEqual(result.status_code,201,result.json.get('error'))
        self.assertEqual(result.json['pdf_filename'],'PI-1.pdf')
        db=database.get_db()
        try:invoice=db.execute('SELECT workbook,pdf FROM order_invoices WHERE id=?',(result.json['id'],)).fetchone()
        finally:db.close()
        with ZipFile(BytesIO(invoice['workbook'])) as workbook:
            strings=workbook.read('xl/sharedStrings.xml')
            self.assertIn(b'AMT/1',strings)
            self.assertNotIn(b'PI-PENDING',strings)
        self.assertTrue(invoice['pdf'].startswith(b'%PDF'))
        self.assertIn(b'AMT/1',invoice['pdf'])
        self.assertEqual(self.counter(),1)
