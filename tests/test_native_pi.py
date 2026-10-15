"""Native PI snapshots, commercial edits, exports and live authorization."""
from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import test_clients_orders
from backend import database
from backend.orders import pi_exports


class NativePiTests(unittest.TestCase):
    setUpBase = test_clients_orders.WorkspaceTests.setUp
    direct = test_clients_orders.WorkspaceTests.direct
    as_user = test_clients_orders.WorkspaceTests.as_user
    create = test_clients_orders.WorkspaceTests.create
    assign = test_clients_orders.WorkspaceTests.assign
    enquiry = test_clients_orders.WorkspaceTests.enquiry
    share = test_clients_orders.WorkspaceTests.share

    def setUp(self):
        self.setUpBase()
        self.company = {'seller':['Fixture Seller','Fixture Street','GST: TEST'],
            'bank':['Fixture bank','Company account fixture'], 'bank_charges':'Sender pays',
            'payment_terms':{'USD':'100% Advance','INR':'100% Advance'},
            'tax_rates':{'USD':'0','INR':'0.18'},
            'terms':{'USD':['1. Valid 7 days','2. PAYMENT Advance'], 'INR':['1. Valid 7 days','2. PAYMENT Advance']}}
        c=database.get_db()
        with c:c.execute('INSERT INTO company_pi_settings(id,profile_json) VALUES(1,?)',(json.dumps(self.company),))
        c.close()
        self.order_id=self.direct()['order']['id']
        self.base=f'/api/orders/{self.order_id}/invoices'

    def preview(self,**changes):
        result=self.client.post(self.base+'/preview',json={'currency':'USD',**changes})
        self.assertEqual(result.status_code,201,result.json)
        return result.json

    def issue(self,preview):
        return self.client.post(self.base+'/issue',json={'preview_id':preview['preview_id']})

    def edits(self,doc):
        return {'lines':[{k:line[k] for k in ('id','sku','description','hsn_code','item_condition','uom','quantity','unit_price')}
                          for line in doc['totals']['lines']]}

    def test_native_exports_without_reference_workbooks_and_idempotent_issuance(self):
        with patch('backend.orders.invoices.template',side_effect=AssertionError('No template at runtime')):
            preview=self.preview()
            exact=self.client.get(preview['pdf_url'])
            self.assertEqual(exact.status_code,200)
            self.assertTrue(exact.data.startswith(b'%PDF-'))
            issued=self.issue(preview)
            self.assertEqual(issued.status_code,201,issued.json)
            self.assertEqual(self.issue(preview).json,issued.json)
            xlsx=self.client.get(issued.json['xlsx_url'])
            pdf=self.client.get(issued.json['pdf_url'])
            self.assertTrue(pdf.data.startswith(b'%PDF-'))
            self.assertEqual(pdf.data,self.client.get(issued.json['pdf_url']).data)
            with ZipFile(BytesIO(xlsx.data)) as book:
                self.assertEqual(len([n for n in book.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')]),1)
                self.assertEqual(len([n for n in book.namelist() if n.startswith('xl/media/')]),4)
                self.assertFalse(any('vbaProject' in n for n in book.namelist()))
                strings=book.read('xl/sharedStrings.xml').decode()
                self.assertIn('=Not an Excel formula',strings)
                self.assertIn('Fixture bank',strings)
                self.assertNotIn('AFGHANISTAN',strings.upper())
                sheet=ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
                self.assertFalse(sheet.findall('.//{*}f'))
            self.assertEqual(len(self.client.get(f'/api/orders/{self.order_id}').json['invoices']),1)
            self.assertEqual(self.client.put(self.base+'/preview/'+preview['preview_id'],json={}).status_code,409)

    def test_edits_recalculate_in_selected_currency_and_keep_source_order_unchanged(self):
        self.assertEqual(self.client.post(self.base+'/preview',json={'currency':'INR'}).status_code,400)
        preview=self.preview(currency='INR',usd_inr_rate='80')
        self.assertEqual(preview['document']['totals']['subtotal'],'2961.60')
        changes=self.edits(preview['document'])
        changes['lines'][0].update(quantity='2',unit_price='100.01',description='<Edited> & safe')
        changes.update(shipping_charges='25.50',order={'po_reference':'Edited PO'},
            delivery={'buyer_text':'New buyer\nSeparate address\nCountry: USA\nEmail: buyer@example.com'})
        saved=self.client.put(self.base+'/preview/'+preview['preview_id'],json=changes)
        self.assertEqual(saved.status_code,200,saved.json)
        total=saved.json['document']['totals']
        self.assertEqual((total['subtotal'],total['shipping'],total['tax'],total['grand_total']),('200.02','25.50','40.59','266.11'))
        self.assertIn('Rupees',total['amount_in_words'])
        self.assertEqual(saved.json['document']['source_conversion']['usd_inr_rate'],'80')
        self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['lines'][0]['unit_price'],'12.34')
        self.assertEqual(self.issue(saved.json).status_code,201)

    def test_protected_fields_validation_and_incomplete_metadata(self):
        preview=self.preview()
        url=self.base+'/preview/'+preview['preview_id']
        for changes in ({'company':{}},{'reference':'fake'},{'assets':{}},{'order':{'client_id':123}},{'date':'bad'},
                        {'shipping_charges':'-1'},{'lines':[]}):
            self.assertEqual(self.client.put(url,json=changes).status_code,400,changes)
        changes=self.edits(preview['document'])
        for value in ('1.5','0','9999999'):
            changes['lines'][0]['quantity']=value
            self.assertEqual(self.client.put(url,json=changes).status_code,400)
        changes['lines'][0].update(quantity='2',hsn_code='')
        self.assertEqual(self.client.put(url,json=changes).status_code,200)
        self.assertEqual(self.issue(preview).status_code,400)
        self.assertEqual(len(self.client.get(f'/api/orders/{self.order_id}').json['invoices']),0)

    def test_permissions_preview_ownership_and_revocation(self):
        preview=self.preview()
        self.share('VIEW');self.as_user('exec2')
        for method,url,body in [('post',self.base+'/preview',{'currency':'USD'}),
                                ('put',self.base+'/preview/'+preview['preview_id'],{}),
                                ('post',self.base+'/issue',{'preview_id':preview['preview_id']})]:
            self.assertEqual(getattr(self.client,method)(url,json=body).status_code,403)
        self.assertEqual(self.client.get(preview['pdf_url']).status_code,403)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/level',json={'user_id':self.ids['exec2'],'access_level':'EDIT'})
        self.as_user('exec2')
        self.assertEqual(self.client.get(preview['pdf_url']).status_code,404)
        self.as_user('exec1');issued=self.issue(preview)
        self.assertEqual(issued.status_code,201)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/level',json={'user_id':self.ids['exec2'],'access_level':'VIEW'})
        self.as_user('exec2')
        self.assertEqual(self.client.get(issued.json['pdf_url']).status_code,200)
        self.as_user('admin')
        self.client.post(f'/api/client-access/{self.parent}/revoke',json={'user_id':self.ids['exec2']})
        self.as_user('exec2')
        self.assertEqual(self.client.get(issued.json['pdf_url']).status_code,404)

    def test_order_changes_reject_stale_preview(self):
        preview=self.preview()
        c=database.get_db()
        with c:c.execute("UPDATE client_orders SET updated_at='2099-01-01' WHERE id=?",(self.order_id,))
        c.close()
        self.assertEqual(self.issue(preview).status_code,409)

    def test_long_documents_paginate_without_render_errors(self):
        doc=self.preview()['document']
        line=doc['totals']['lines'][0]
        doc['totals']['lines']=[{**line,'id':i,'description':'Long description '*100} for i in range(50)]
        doc['order']['notes']='Long note '*500
        doc['delivery']['consignee_text']='Long party address\n'*120
        raw=pi_exports.pdf(doc)
        self.assertTrue(raw.startswith(b'%PDF-'))
        self.assertGreater(raw.count(b'/Type /Page'),2)
        with ZipFile(BytesIO(pi_exports.xlsx(doc))) as book:
            self.assertIn('xl/worksheets/sheet1.xml',book.namelist())

    def test_payment_clause_does_not_replace_other_commercial_terms(self):
        doc=self.preview()['document']
        doc['company']['terms']['USD']=['2. PAYMENT Advance','4. SHIPMENT: DISPATCH WITHIN 24 HOURS OF PAYMENT CONFIRMATION']
        doc['order']['payment_terms']='Agreed advance'
        output=pi_exports.terms(doc)
        self.assertIn('2. PAYMENT Agreed advance',output)
        self.assertIn('4. SHIPMENT: DISPATCH WITHIN 24 HOURS OF PAYMENT CONFIRMATION',output)

    def test_editable_preparer_phone_and_free_shipping_preserve_numeric_totals(self):
        preview=self.preview()
        url=self.base+'/preview/'+preview['preview_id']
        self.assertEqual(self.client.put(url,json={'prepared_phone':'invalid'}).status_code,400)
        saved=self.client.put(url,json={'prepared_phone':'+91 97252 18537','shipping_charges':'0.00'})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['document']['prepared_phone'],'+919725218537')
        self.assertEqual(saved.json['document']['totals']['shipping'],'0.00')
        self.assertEqual(saved.json['document']['totals']['grand_total'],'37.02')
        cells=[cell for section in saved.json['layout']['sections'] for row in section['rows'] for cell in row]
        shipping=next(cell for cell in cells if cell['field']=='shipping_charges')
        self.assertEqual(shipping['display_text'],'Free')
        self.assertEqual(next(cell for cell in cells if cell['field']=='prepared_phone')['label'],'Tel: ')
        issued=self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            strings=book.read('xl/sharedStrings.xml').decode()
            self.assertIn('Free',strings)
            self.assertIn('Tel: +919725218537',strings)

    def test_company_grid_keeps_bold_borders_fonts_and_warning_highlight(self):
        preview=self.preview()
        model=preview['layout']
        self.assertEqual(len(model['widths']),11)
        header=next(s for s in model['sections'] if s['name']=='header')['rows']
        self.assertTrue(header[0][0]['line_bottom'])
        self.assertTrue(any(c.get('line_bottom') and c['field']=='order.payment_terms' for row in header for c in row))
        parties=next(s for s in model['sections'] if s['name']=='parties')['rows']
        self.assertEqual([(c['col'],c['span']) for c in parties[0]],[(0,5),(5,6)])
        self.assertTrue(parties[2][1]['line_top'])
        bank=next(s for s in model['sections'] if s['name']=='bank')['rows']
        self.assertTrue(any(c['style']=='warning' for row in bank for c in row))
        self.assertEqual(bank[-1][-1]['style'],'bold_amount')
        with ZipFile(BytesIO(pi_exports.xlsx(preview['document']))) as book:
            styles=book.read('xl/styles.xml').decode()
            self.assertIn('Cambria',styles)
            self.assertIn('FFFFFF00',styles)
            self.assertIn('FFFF0000',styles)
            self.assertIn('style="medium"',styles)
            self.assertNotIn('FFD0D0D0',styles)
            self.assertNotIn('_xlnm.Print_Titles',book.read('xl/workbook.xml').decode())
            self.assertTrue(ET.fromstring(book.read('xl/drawings/drawing1.xml')).findall('.//{*}srcRect'))


if __name__=='__main__':unittest.main()
