"""Authorization, immutable price baselines and rejected-discount audit evidence."""
from unittest.mock import patch
import unittest

import test_clients_orders
from backend import database
from backend.settings import bp as settings_bp
from backend.security.audit import audit_request


class SkuDiscountPolicyTests(unittest.TestCase):
    setUpBase=test_clients_orders.WorkspaceTests.setUp
    direct=test_clients_orders.WorkspaceTests.direct
    as_user=test_clients_orders.WorkspaceTests.as_user
    create=test_clients_orders.WorkspaceTests.create
    assign=test_clients_orders.WorkspaceTests.assign
    enquiry=test_clients_orders.WorkspaceTests.enquiry
    share=test_clients_orders.WorkspaceTests.share
    def setUp(self):
        self.setUpBase()
        app=self.client.application
        app._got_first_request=False
        app.register_blueprint(settings_bp)
        app.after_request(audit_request)
        self.as_user('admin')
        self.assertEqual(self.client.put('/api/pi-discount-limit',json={'maximum_percent':'10'}).status_code,200)
        self.as_user('exec1')
        result=self.direct(lines=[{'sku':'POLICY','description':'Original description',
            'quantity':'1','unit_price':'100.00','currency':'USD','manual_entry':True,
            'hsn_code':'0012','item_condition':'New','uom':'PCs'}])
        self.order_id=result['order']['id']
        self.line_id=result['lines'][0]['id']
        self.url=f'/api/orders/{self.order_id}'

    def discount(self,kind='percent',value='10',scope='all',visible=True):
        return self.client.put(self.url+'/discount',json={
            'type':kind,'value':value,'scope':scope,'line_ids':[], 'show_on_pi':visible})

    def lookup_line(self):
        db=database.get_db()
        with db:db.execute('UPDATE order_sku_lines SET manual_entry=0 WHERE id=?',(self.line_id,))
        db.close()

    def test_only_admin_configures_limit(self):
        self.assertEqual(self.client.put('/api/pi-discount-limit',json={'maximum_percent':'99'}).status_code,403)
        self.as_user('tl1')
        self.assertEqual(self.client.put('/api/pi-discount-limit',json={'maximum_percent':'99'}).status_code,403)
        self.as_user('admin')
        for value in ('-1','100.01',True,'NaN'):
            self.assertEqual(self.client.put('/api/pi-discount-limit',json={'maximum_percent':value}).status_code,400)

    def test_lookup_is_quantity_only_and_source_cannot_be_changed(self):
        self.lookup_line()
        for data in ({'description':'Changed'},{'unit_price':'99'},{'hsn_code':'1234'},
                     {'manual_entry':True},{'catalog_original_price':'999'}):
            self.assertEqual(self.client.put(self.url+f'/lines/{self.line_id}',json=data).status_code,400)
        with patch('backend.orders.catalog.lookup_stock',return_value={'found':True,'Quantity':100}):
            self.assertEqual(self.client.put(self.url+f'/lines/{self.line_id}',json={'quantity':'2','uom':'Lot'}).status_code,200)
        self.assertEqual(self.client.put(self.url+'/line-commercial-details',json={'lines':[
            {'id':self.line_id,'hsn_code':'1234','item_condition':'Used'}]}).status_code,400)

    def test_admin_and_tl_can_edit_lookup_metadata(self):
        self.lookup_line()
        self.assign('exec1','tl1')
        for role in ('admin','tl1'):
            self.as_user(role)
            with patch('backend.orders.catalog.lookup_stock',return_value={'found':True,'Quantity':100}):
                response=self.client.put(self.url+f'/lines/{self.line_id}',json={'description':role+' edited'})
            self.assertEqual(response.status_code,200,response.json)

    def test_percent_and_amount_limits_persist_audit_after_rollback(self):
        for kind,value,scope,visible in [('percent','10.01','all',True),('amount','10.01','total',True),
                                         ('amount','10.01','all',False)]:
            response=self.discount(kind,value,scope,visible)
            self.assertEqual(response.status_code,400,response.json)
        db=database.get_db()
        self.assertEqual(db.execute("SELECT count(*) FROM audit_logs WHERE action='discount_limit_exceeded'").fetchone()[0],3)
        self.assertIsNone(db.execute('SELECT discount_json FROM client_orders WHERE id=?',(self.order_id,)).fetchone()[0])
        db.close()
        self.assertEqual(self.discount().status_code,200)

    def test_repeated_price_reductions_and_combined_discount(self):
        url=self.url+f'/lines/{self.line_id}'
        self.assertEqual(self.client.put(url,json={'unit_price':'95'}).status_code,200)
        self.assertEqual(self.client.put(url,json={'unit_price':'89'}).status_code,400)
        self.assertEqual(self.discount().status_code,400)
        self.assertEqual(self.discount(value='5').status_code,200)

    def test_invoice_save_calculate_print_and_privileged_price_limit(self):
        self.lookup_line()
        preview=self.client.post(self.url+'/invoices/preview',json={'currency':'USD'})
        self.assertEqual(preview.status_code,201,preview.json)
        doc=preview.json['document'];line=doc['totals']['lines'][0]
        full={k:line[k] for k in ('id','sku','description','quantity','unit_price','hsn_code','item_condition','uom')}
        full['unit_price']='89'
        base=self.url+'/invoices/preview/'+preview.json['preview_id']
        quantity_only=self.client.post(base+'/calculate',json={'lines':[{'id':self.line_id,'quantity':'2','unit_price':100,'uom':'Kit'}]})
        self.assertEqual(quantity_only.status_code,200,quantity_only.json)
        for method,url,payload in [('put',self.url+'/invoices/preview/'+preview.json['preview_id'],{'lines':[full]}),
                                   ('post',base+'/calculate',{'lines':[{'id':self.line_id,'unit_price':'89'}]}),
                                   ('post',base+'/print',{'lines':[full]})]:
            response=getattr(self.client,method)(url,json=payload)
            self.assertEqual(response.status_code,400,response.json)
        self.as_user('admin')
        # Admin owns its own previews, but remains subject to the same discount cap.
        preview=self.client.post(self.url+'/invoices/preview',json={'currency':'USD'})
        base=self.url+'/invoices/preview/'+preview.json['preview_id']
        response=self.client.post(base+'/calculate',json={'lines':[{'id':self.line_id,'unit_price':'89'}]})
        self.assertEqual(response.status_code,400,response.json)

    def test_lookup_creation_uses_server_catalog_not_client_price(self):
        product={'found':True,'Quantity':100,'price':'100','title':'Catalog title','condition':'New'}
        line={'sku':'FETCHED','description':'Catalog title','quantity':'1','unit_price':'1',
              'currency':'USD','hsn_code':'','item_condition':'New','uom':'PCs','manual_entry':False}
        with patch('backend.orders.catalog.lookup_stock',return_value=product):
            response=self.client.post(self.url+'/lines',json=line)
            self.assertEqual(response.status_code,400,response.json)
            line['unit_price']='100'
            response=self.client.post(self.url+'/lines',json=line)
            self.assertEqual(response.status_code,201,response.json)

    def test_currency_conversion_keeps_original_baseline(self):
        db=database.get_db()
        with db:db.execute("INSERT INTO app_settings(key,value) VALUES('currency_rates',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('{"INR":"80"}',))
        db.close()
        url=self.url+f'/lines/{self.line_id}'
        response=self.client.put(url,json={'currency':'INR','unit_price':'8000'})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.client.put(url,json={'unit_price':'7199'}).status_code,400)
        self.assertEqual(self.discount('amount','10','total').status_code,200)
        self.assertEqual(self.discount('amount','10.01','total').status_code,400)

    def test_total_and_per_line_amount_scopes(self):
        response=self.client.post(self.url+'/lines',json={'sku':'SECOND','description':'Manual second',
            'quantity':'1','unit_price':'100','currency':'USD','manual_entry':True})
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(self.discount('amount','11','all').status_code,400)
        self.assertEqual(self.discount('amount','20','total').status_code,200)
        self.assertEqual(self.discount('amount','20.01','total',False).status_code,400)

    def test_lowered_limit_blocks_issuing_previously_opened_preview(self):
        self.assertEqual(self.discount().status_code,200)
        preview=self.client.post(self.url+'/invoices/preview',json={'currency':'USD'}).json
        self.as_user('admin')
        self.assertEqual(self.client.put('/api/pi-discount-limit',json={'maximum_percent':'5'}).status_code,200)
        self.as_user('exec1')
        response=self.client.post(self.url+'/invoices/issue',json={'preview_id':preview['preview_id']})
        self.assertEqual(response.status_code,400,response.json)

    def test_catalog_original_snapshot_and_preview_currency_are_preserved(self):
        product={'found':True,'Quantity':100,'price':'150.99','sale_price':'143.44',
                 'title':'Original price item','condition':'New'}
        with patch('backend.orders.catalog.lookup_stock',return_value=product):
            response=self.client.post(self.url+'/lines',json={'sku':'ORIGINAL','description':'Original price item',
                'quantity':'1','unit_price':'143.44','currency':'USD','manual_entry':False,
                'hsn_code':'','item_condition':'New','uom':'PCs'})
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(self.discount().status_code,200)
        preview=self.client.post(self.url+'/invoices/preview',json={'currency':'INR','usd_inr_rate':'80'})
        self.assertEqual(preview.status_code,201,preview.json)
        lines=preview.json['document']['totals']['lines']
        self.assertEqual(lines[-1]['catalog_original_price'],'12079.20')
        self.assertEqual(lines[-1]['line_total'],'10871.28')
        edits=[{k:line[k] for k in ('id','sku','description','quantity','unit_price','hsn_code','item_condition','uom')} for line in lines]
        response=self.client.post(self.url+'/invoices/preview/'+preview.json['preview_id']+'/calculate',json={'lines':edits})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['totals']['lines'][-1]['line_total'],'10871.28')
