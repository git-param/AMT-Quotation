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
    def direct(self, **changes):
        changes.setdefault('delivery', {
            'shipping_address': {'line1': 'Order destination', 'country': 'USA'},
            'consignee': {'name': 'Consignee', 'phone': '+12025550123', 'email': 'consignee@example.com',
                          'pic': 'Fixture Contact', 'gst_number': '24TEST123'},
            'notify_party': {'name': 'Notify', 'address': {'line1': 'Notify address', 'country': 'USA'}},
        })
        return test_clients_orders.WorkspaceTests.direct(self, **changes)
    as_user = test_clients_orders.WorkspaceTests.as_user
    create = test_clients_orders.WorkspaceTests.create
    assign = test_clients_orders.WorkspaceTests.assign
    enquiry = test_clients_orders.WorkspaceTests.enquiry
    share = test_clients_orders.WorkspaceTests.share

    def setUp(self):
        self.setUpBase()
        rate_patch=patch('backend.quotation_tool.shopify.get_inr_rate',return_value=80)
        rate_patch.start();self.addCleanup(rate_patch.stop)
        self.company = {'seller':['Fixture Seller','Fixture Street','GST: TEST'],
            'bank':['Fixture bank','Company account fixture'], 'bank_charges':'Sender pays',
            'payment_terms':{'USD':'100% Advance','INR':'100% Advance'},
            'tax_rates':{'USD':'0','INR':'0.18'},
            'terms':{'USD':['1. Valid 7 days','2. PAYMENT Advance'], 'INR':['1. Valid 7 days','2. PAYMENT Advance']}}
        c=database.get_db()
        with c:c.execute('INSERT INTO company_pi_settings(id,profile_json) VALUES(1,?)',(json.dumps(self.company),))
        c.close()
        self.order_id=self.direct(pi_reference='AMT/1234')['order']['id']
        self.base=f'/api/orders/{self.order_id}/invoices'

    def preview(self,**changes):
        result=self.client.post(self.base+'/preview',json={'currency':'USD',**changes})
        self.assertEqual(result.status_code,201,result.json)
        return result.json

    def issue(self,preview):
        return self.client.post(self.base+'/issue',json={'preview_id':preview['preview_id']})

    def test_normal_pi_default_heading_notice_date_and_download_names(self):
        from backend.orders.normal_pi.layout import ITEM_HEADING, SHIPPING_NOTICE

        preview=self.preview()
        doc=preview['document']
        sections={section['name']:section for section in preview['layout']['sections']}
        self.assertEqual(preview['layout']['shipping_notice'],SHIPPING_NOTICE)
        rows=sections['items']['rows']
        self.assertEqual(rows[1][1]['text'],ITEM_HEADING)
        self.assertEqual(rows[2][1]['text'],doc['totals']['lines'][0]['description'])
        self.assertIn('filename=PI-1234.pdf',self.client.get(preview['pdf_url']).headers['Content-Disposition'])
        with ZipFile(BytesIO(pi_exports.xlsx(doc))) as book:
            strings_xml=book.read('xl/sharedStrings.xml')
            strings=strings_xml.decode()
            sheet=ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            self.assertIn(ITEM_HEADING,strings)
            self.assertIn(SHIPPING_NOTICE,strings)
            values=[''.join(node.itertext()) for node in ET.fromstring(strings_xml)]
            self.assertIn('Proforma Invoice Date:',values)
            label_index=values.index('Proforma Invoice Date:')
            label=next(cell for cell in sheet.findall('.//{*}c')
                       if cell.find('{*}v') is not None and cell.find('{*}v').text==str(label_index))
            self.assertTrue(label.attrib['r'].startswith('F'))
            self.assertTrue(any(merge.attrib['ref'].startswith(label.attrib['r']+':G')
                                for merge in sheet.findall('.//{*}mergeCell')))
            date_row=label.attrib['r'][1:]
            self.assertTrue(any(merge.attrib['ref']==f'H{date_row}:K{date_row}'
                                for merge in sheet.findall('.//{*}mergeCell')))
            styles=ET.fromstring(book.read('xl/styles.xml'))
            style=styles.find('{*}cellXfs')[int(label.attrib['s'])]
            font=styles.find('{*}fonts')[int(style.attrib['fontId'])]
            self.assertEqual(font.find('{*}sz').attrib['val'],'12')
            alignment=style.find('{*}alignment')
            if alignment is not None:
                self.assertNotEqual(alignment.get('wrapText'),'1')
                self.assertNotEqual(alignment.get('shrinkToFit'),'1')
        issued=self.issue(preview)
        self.assertEqual(issued.status_code,201,issued.json)
        for extension in ('xlsx','pdf'):
            self.assertEqual(issued.json[extension+'_filename'],'PI-1234.'+extension)
            self.assertIn('filename=PI-1234.'+extension,
                          self.client.get(issued.json[extension+'_url']).headers['Content-Disposition'])

    def test_pi_rendering_does_not_hold_sqlite_writer_lock(self):
        preview=self.preview()
        original=pi_exports.xlsx
        def render(document):
            other=database.get_db()
            try:
                other.execute('BEGIN IMMEDIATE')
            finally:
                other.rollback();other.close()
            return original(document)
        with patch('backend.orders.pi_exports.xlsx',side_effect=render):
            issued=self.issue(preview)
        self.assertEqual(issued.status_code,201,issued.json)

    def test_preview_rendering_does_not_hold_sqlite_writer_lock(self):
        original=pi_exports.pdf
        def render(document):
            other=database.get_db()
            try:other.execute('BEGIN IMMEDIATE')
            finally:other.rollback();other.close()
            return original(document)
        with patch('backend.orders.pi_exports.pdf',side_effect=render):
            preview=self.preview()
        self.assertTrue(preview['preview_id'])

    def test_pi_issue_rejects_preview_changed_during_render(self):
        preview=self.preview()
        original=pi_exports.xlsx
        def render(document):
            other=database.get_db()
            try:
                row=other.execute('SELECT document_json FROM invoice_previews WHERE id=?',
                                  (preview['preview_id'],)).fetchone()
                changed=json.loads(row[0]);changed['render_race_marker']=True
                with other:
                    other.execute('UPDATE invoice_previews SET document_json=? WHERE id=?',
                                  (json.dumps(changed),preview['preview_id']))
            finally:other.close()
            return original(document)
        with patch('backend.orders.pi_exports.xlsx',side_effect=render):
            response=self.issue(preview)
        self.assertEqual(response.status_code,409,response.json)
        connection=database.get_db()
        try:self.assertEqual(connection.execute('SELECT COUNT(*) FROM order_invoices WHERE order_id=?',
                                                (self.order_id,)).fetchone()[0],0)
        finally:connection.close()

    def edits(self,doc):
        return {'lines':[{k:line[k] for k in ('id','sku','description','hsn_code','item_condition','uom','quantity','unit_price')}
                          for line in doc['totals']['lines']]}

    def test_native_exports_without_reference_workbooks_and_idempotent_issuance(self):
        with patch('backend.orders.invoices.template',side_effect=AssertionError('No template at runtime')):
            preview=self.preview()
            self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['order']['status'],'draft')
            self.assertEqual(preview['document']['reference'],'AMT/1234')
            exact=self.client.get(preview['pdf_url'])
            self.assertEqual(exact.status_code,200)
            self.assertTrue(exact.data.startswith(b'%PDF-'))
            issued=self.issue(preview)
            self.assertEqual(issued.status_code,201,issued.json)
            self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['order']['status'],'completed')
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
                self.assertTrue(sheet.findall('.//{*}f'))
            self.assertEqual(len(self.client.get(f'/api/orders/{self.order_id}').json['invoices']),1)
            self.assertEqual(self.client.put(self.base+'/preview/'+preview['preview_id'],json={}).status_code,409)

    def test_department_prefix_defaults_flow_to_editable_preview_and_issued_files(self):
        connection = database.get_db()
        with connection:
            connection.executemany('INSERT INTO departments(name,pi_prefix) VALUES(?,?)', [('Sales', 'AMT'), ('Purchase', 'PUC')])
            connection.execute("UPDATE users SET department='Sales' WHERE id=?", (self.ids['exec1'],))
            connection.execute("UPDATE users SET department='Purchase' WHERE id=?", (self.ids['exec2'],))
        connection.close()
        self.as_user('exec1')
        self.assertEqual(self.client.get('/api/orders/pi-defaults').json, {'department': 'Sales', 'pi_prefix': 'AMT'})
        order = self.direct()
        self.assertEqual(order['order']['pi_reference'], 'AMT/')
        order_id = order['order']['id']
        self.base = f'/api/orders/{order_id}/invoices'
        preview = self.preview()
        self.assertEqual(preview['document']['reference'], 'AMT/')
        self.assertEqual(self.issue(preview).status_code, 400)
        updated = self.client.put(self.base+'/preview/'+preview['preview_id'], json={'order': {'pi_reference': 'AMT/123214'}})
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(self.client.get(f'/api/orders/{order_id}').json['order']['pi_reference'], 'AMT/123214')
        self.assertIn('AMT/123214', json.dumps(updated.json['layout']))
        cells = [cell for section in updated.json['layout']['sections'] for row in section['rows'] for cell in row]
        field = next(cell for cell in cells if cell.get('field') == 'order.pi_reference')
        self.assertFalse(field.get('readonly'))
        issued = self.issue(updated.json)
        self.assertEqual(issued.status_code, 201, issued.json)
        self.assertEqual(issued.json['reference'], 'AMT/123214')
        self.assertTrue(self.client.get(issued.json['pdf_url']).data.startswith(b'%PDF-'))
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            self.assertIn('AMT/123214', book.read('xl/sharedStrings.xml').decode())
        self.as_user('exec2')
        self.assertEqual(self.client.get('/api/orders/pi-defaults').json['pi_prefix'], 'PUC')
        self.as_user('exec1')
        custom = self.direct(pi_reference='CUSTOM/99')
        self.assertEqual(custom['order']['pi_reference'], 'CUSTOM/99')
        self.base = f"/api/orders/{custom['order']['id']}/invoices"
        self.assertEqual(self.preview()['document']['reference'], 'CUSTOM/99')

    def test_blank_existing_order_uses_its_creator_department_in_preview(self):
        connection = database.get_db()
        with connection:
            connection.execute("INSERT INTO departments(name,pi_prefix) VALUES('Sales','AMT')")
            connection.execute("UPDATE users SET department='Sales' WHERE id=?", (self.ids['exec1'],))
        connection.close()
        self.client.put(f'/api/orders/{self.order_id}', json={'pi_reference': ''})
        self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['pi_defaults']['pi_prefix'], 'AMT')
        self.as_user('admin')
        preview = self.preview()
        self.assertEqual(preview['document']['reference'], 'AMT/')

    def test_pi_number_is_required_and_reusable_with_fresh_previews(self):
        self.client.put(f'/api/orders/{self.order_id}',json={'pi_reference':''})
        missing=self.client.post(self.base+'/preview',json={'currency':'USD'})
        self.assertEqual(missing.status_code,400)
        self.assertIn('Proforma Invoice No.',missing.json['error'])
        self.client.put(f'/api/orders/{self.order_id}',json={'pi_reference':'SALES/2026/001'})
        first=self.preview()
        second=self.preview()
        issued=self.issue(first)
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertEqual(issued.json['reference'],'SALES/2026/001')
        # Stale previews remain blocked; a fresh preview can reuse the number.
        self.assertEqual(self.issue(second).status_code,409)
        repeated=self.issue(self.preview())
        self.assertEqual(repeated.status_code,201,repeated.json)
        self.assertNotEqual(repeated.json['id'],issued.json['id'])
        self.assertEqual(repeated.json['reference'],issued.json['reference'])
        self.assertEqual(self.issue(first).json['id'],issued.json['id'])
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            self.assertIn('SALES/2026/001',book.read('xl/sharedStrings.xml').decode())

    def test_reopening_completed_order_preserves_pi_and_retry_does_not_complete_again(self):
        preview=self.preview();issued=self.issue(preview)
        self.assertEqual(issued.status_code,201,issued.json)
        path=f'/api/orders/{self.order_id}'
        response=self.client.put(path+'/status',json={'status':'draft'})
        self.assertEqual(response.status_code,200,response.json)
        retried=self.issue(preview)
        self.assertEqual(retried.json['id'],issued.json['id'])
        self.assertEqual(retried.json['order_status'],'draft')
        self.assertEqual(self.client.get(issued.json['xlsx_url']).status_code,200)
        self.assertEqual(self.client.get(path).json['order']['status'],'draft')

    def test_failed_pi_generation_keeps_order_pending(self):
        preview=self.preview()
        with patch('backend.orders.pi_exports.xlsx',side_effect=ValueError('Workbook generation failed.')):
            response=self.issue(preview)
        self.assertEqual(response.status_code,400,response.json)
        saved=self.client.get(f'/api/orders/{self.order_id}').json
        self.assertEqual(saved['order']['status'],'draft')
        self.assertEqual(saved['invoices'],[])

    def test_remove_pi_hides_record_and_downloads_but_retains_files_and_audit(self):
        preview=self.preview();issued=self.issue(preview)
        invoice_id=issued.json['id'];path=f'/api/orders/{self.order_id}'
        response=self.client.delete(path+f'/invoices/{invoice_id}')
        self.assertEqual(response.status_code,200,response.json)
        saved=self.client.get(path).json
        self.assertEqual(saved['invoices'],[])
        self.assertEqual(saved['order']['status'],'completed')
        self.assertEqual(self.client.get(issued.json['xlsx_url']).status_code,404)
        self.assertEqual(self.client.get(issued.json['pdf_url']).status_code,404)
        self.assertEqual(self.client.get('/api/pi-search').json['total'],0)
        self.assertEqual(self.issue(preview).status_code,404)
        self.assertEqual(self.client.get(preview['pdf_url']).status_code,404)
        connection=database.get_db()
        try:
            record=connection.execute('SELECT * FROM order_invoices WHERE id=?',(invoice_id,)).fetchone()
            self.assertIsNotNone(record['deleted_at']);self.assertTrue(record['workbook']);self.assertTrue(record['pdf'])
            audit=connection.execute("SELECT details FROM audit_logs WHERE action='pi_remove'").fetchone()
            self.assertEqual(json.loads(audit['details'])['invoice_id'],invoice_id)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally:connection.close()

    def test_remove_pi_requires_order_visibility_and_delete_permission(self):
        issued=self.issue(self.preview());path=f'/api/orders/{self.order_id}/invoices/{issued.json["id"]}'
        self.as_user('exec2');self.assertEqual(self.client.delete(path).status_code,404)
        self.share('VIEW');self.as_user('exec2')
        self.assertEqual(self.client.delete(path).status_code,403)
        self.as_user(None);self.assertEqual(self.client.delete(path).status_code,401)

    def test_other_order_can_edit_and_issue_an_already_used_pi_number(self):
        first=self.issue(self.preview())
        self.assertEqual(first.status_code,201,first.json)
        other=self.direct(pi_reference='OTHER/001')
        other_id=other['order']['id']
        base=f'/api/orders/{other_id}/invoices'
        preview=self.client.post(base+'/preview',json={'currency':'USD'}).json
        saved=self.client.put(base+'/preview/'+preview['preview_id'],
                              json={'order':{'pi_reference':'AMT/1234'}})
        self.assertEqual(saved.status_code,200,saved.json)
        issued=self.client.post(base+'/issue',json={'preview_id':preview['preview_id']})
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertNotEqual(first.json['id'],issued.json['id'])
        connection=database.get_db()
        try:
            with connection:
                # Order identities and child records use IDs, even when labels match.
                connection.execute('UPDATE client_orders SET reference=? WHERE id=?',
                                   (other['order']['reference'],self.order_id))
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally:connection.close()
        for invoice in (first,issued):
            self.assertEqual(self.client.get(invoice.json['pdf_url']).status_code,200)

    def test_prepared_telephone_defaults_to_user_account_and_remains_editable(self):
        connection = database.get_db()
        with connection:
            connection.execute("UPDATE users SET phone_country_code='+91',phone_number='9876543210' WHERE id=?", (self.ids['exec1'],))
        connection.close()
        preview = self.preview()
        self.assertEqual(preview['document']['prepared_phone'], '+919876543210')
        cells = [cell for section in preview['layout']['sections'] for row in section['rows'] for cell in row]
        self.assertFalse(next(cell for cell in cells if cell.get('field') == 'prepared_phone').get('readonly'))
        updated = self.client.put(self.base+'/preview/'+preview['preview_id'], json={'prepared_phone': '+1 202-555-0123'})
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(updated.json['document']['prepared_phone'], '+12025550123')
        connection = database.get_db()
        try:
            self.assertEqual(connection.execute('SELECT phone_number FROM users WHERE id=?', (self.ids['exec1'],)).fetchone()[0], '9876543210')
        finally:
            connection.close()
        self.assertEqual(self.preview()['document']['prepared_phone'], '+919876543210')
        self.as_user('admin')
        self.assertEqual(self.preview()['document']['prepared_phone'], '')

    def test_gst_warning_only_for_inr_and_never_blocks_exports(self):
        import re
        from backend.orders.pi_document import missing_details
        original = self.preview()['document']
        without_gst = re.sub(r'^GST No\.:.*\n?', '', original['delivery']['consignee_text'], flags=re.M)
        for currency in ('USD','INR','AED','GBP','EUR'):
            document = deepcopy(original)
            document['currency'] = currency
            document['delivery']['consignee_text'] = without_gst
            self.assertEqual('Consignee GST No.' in missing_details(document), currency == 'INR')
        preview = self.preview(currency='INR', usd_inr_rate='80')
        url = self.base+'/preview/'+preview['preview_id']
        saved = self.client.put(url+'?for_generation=1', json={'delivery': {'consignee_text': without_gst}})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertIn('Consignee GST No.',saved.json['missing_fields'])
        self.assertEqual(self.client.post(url+'/print',json={}).status_code,200)
        self.assertEqual(self.client.get(saved.json['pdf_url']).status_code,200)
        issued = self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertEqual(self.client.get(issued.json['pdf_url']).status_code,200)
        self.assertEqual(self.client.get(issued.json['xlsx_url']).status_code,200)

    def test_missing_contacts_warn_but_allow_print_generation_and_download(self):
        import re
        preview = self.preview(currency='INR',usd_inr_rate='80')
        url = self.base+'/preview/'+preview['preview_id']
        complete = preview['document']['delivery']['consignee_text']
        incomplete = re.sub(r'^(?:GST No\.|Tel/Phone|PIC|Email):.*\n?', '', complete, flags=re.M)
        changes = {'delivery': {'consignee_text': incomplete}}
        self.assertEqual(self.client.post(url+'/print', json=changes).status_code,200)
        saved = self.client.put(url+'?for_generation=1', json=changes)
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(set(saved.json['missing_fields']), {
            'Consignee GST No.', 'Consignee Tel/Phone', 'Consignee PIC', 'Consignee Email'})
        self.assertEqual(self.client.get(saved.json['pdf_url']).status_code,200)
        issued = self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertEqual(self.client.get(issued.json['pdf_url']).status_code,200)
        self.assertEqual(self.client.get(issued.json['xlsx_url']).status_code,200)

    def test_country_is_required_and_legacy_generation_cannot_bypass_details(self):
        from backend.orders.pi_document import validate_pdf_details, PiDetailsRequired
        preview = self.preview()
        document = deepcopy(preview['document'])
        document['order']['destination'] = ''
        document['delivery']['consignee_text'] = document['delivery']['consignee_text'].replace('USA\n', '')
        with self.assertRaises(PiDetailsRequired) as caught:
            validate_pdf_details(document)
        self.assertIn('Consignee country', caught.exception.missing_fields)
        self.client.put(f'/api/orders/{self.order_id}', json={
            'pi_reference': '', 'po_reference': '',
            'delivery': {'consignee_text': 'Company\nStreet address'},
        })
        response = self.client.post(self.base, json={'currency': 'USD'})
        self.assertEqual(response.status_code, 400)
        for field in ('Proforma Invoice No.', 'Purchase Order No.'):
            self.assertIn(field, response.json['error'])

    def test_print_preview_blocks_unfinished_fields_without_saving(self):
        preview=self.preview()
        changes=self.edits(preview['document'])
        changes.update(date='',prepared_phone='unfinished phone',order={'pi_reference':'','delivery_terms':''},
            delivery={'consignee_text':'','buyer_text':'Buyer\nEmail: unfinished','notify_text':'Notify\nTel: unfinished'})
        changes['lines'][0]['quantity']=''
        result=self.client.post(self.base+'/preview/'+preview['preview_id']+'/print',json=changes)
        self.assertEqual(result.status_code,400)
        for label in ('Proforma Invoice No.',):
            self.assertIn(label, result.json['error'])
        connection=database.get_db()
        try:
            row=connection.execute('SELECT document_json FROM invoice_previews WHERE id=?',(preview['preview_id'],)).fetchone()
            self.assertEqual(json.loads(row[0]),preview['document'])
        finally:connection.close()
        self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['order']['pi_reference'],'AMT/1234')
        self.as_user('tl2')
        self.assertEqual(self.client.post(self.base+'/preview/'+preview['preview_id']+'/print',json={}).status_code,404)

    def test_deleted_order_retains_issued_files_but_blocks_download_and_preview_access(self):
        preview=self.preview();issued=self.issue(preview)
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order_id}').status_code,200)
        self.assertEqual(self.client.get(issued.json['pdf_url']).status_code,404)
        self.assertEqual(self.client.get(preview['pdf_url']).status_code,404)
        self.assertEqual(self.client.post(self.base+'/preview',json={'currency':'USD'}).status_code,404)
        connection=database.get_db()
        try:
            self.assertTrue(connection.execute('SELECT pdf FROM order_invoices WHERE order_id=?',(self.order_id,)).fetchone()[0])
        finally:connection.close()

    def test_preview_pi_number_edits_update_order_and_issue_matching_exports(self):
        preview=self.preview()
        saved=self.client.put(self.base+'/preview/'+preview['preview_id'],json={'order':{'pi_reference':'SALES/EDITED/001'}})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['document']['reference'],'SALES/EDITED/001')
        self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['order']['pi_reference'],'SALES/EDITED/001')
        self.assertEqual(self.client.put(self.base+'/preview/'+preview['preview_id'],json={'order':{'pi_reference':''}}).status_code,400)
        issued=self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertEqual(issued.json['reference'],'SALES/EDITED/001')

    def test_copied_contacts_stay_in_consignee_and_manual_preview_contacts_survive(self):
        from backend.orders.locations import address_only
        block='Client company\nStreet address\nCountry: USA\nTel: +919876543210\nPIC: Person\nEmail: client@example.com'
        self.client.put(f'/api/orders/{self.order_id}',json={'delivery':{
            'consignee_text':block,'buyer_text':block,'notify_text':block}})
        preview=self.preview(currency='INR',usd_inr_rate='80')
        doc=preview['document']
        self.assertIn('Tel/Phone:',doc['delivery']['consignee_text'])
        for key in ('buyer_text','notify_text'):
            self.assertEqual(doc['delivery'][key],address_only(block))
            self.assertNotIn('PIC:',doc['delivery'][key])
        fields=[cell['field'] for section in preview['layout']['sections'] for row in section['rows'] for cell in row]
        self.assertNotIn('buyer_gst_number',fields)
        saved=self.client.put(self.base+'/preview/'+preview['preview_id'],json={'delivery':{
            'buyer_text':doc['delivery']['buyer_text']+'\nTel: +919999999999\nPIC: Buyer\nEmail: buyer@example.com'}})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertIn('Email: buyer@example.com',saved.json['document']['delivery']['buyer_text'])

    def test_same_as_consignee_prints_reference_in_buyer_and_notify_for_both_formats(self):
        block='Client company\nStreet address\nCountry: USA\nTel: +919876543210\nEmail: client@example.com'
        response=self.client.put(f'/api/orders/{self.order_id}',json={'delivery':{
            'consignee_text':block,'buyer_text':'Client company\nStreet address','notify_text':'Client company\nStreet address'}})
        self.assertEqual(response.status_code,200,response.json)
        for count in (1,5):
            if count==5:
                result=self.client.post(f'/api/orders/{self.order_id}/lines/bulk',json={'lines':[
                    {'sku':f'LINKED-{index}','description':'Part','quantity':'1','unit_price':'10','currency':'USD'} for index in range(4)]})
                self.assertEqual(result.status_code,201,result.json)
            preview=self.preview(**({'bulk_description':'Electrical spare parts'} if count==5 else {}))
            parties=next(section for section in preview['layout']['sections'] if section['name']=='parties')
            linked=[cell for row in parties['rows'] for cell in row if cell.get('field') in ('delivery.buyer_text','delivery.notify_text')]
            self.assertEqual([cell['text'] for cell in linked],['(Same as consignee)']*2)
            self.assertEqual([cell['value'] for cell in linked],['(Same as consignee)']*2)
            with ZipFile(BytesIO(pi_exports.xlsx(preview['document']))) as book:
                self.assertIn('(Same as consignee)',book.read('xl/sharedStrings.xml').decode())
            self.assertTrue(pi_exports.pdf(preview['document']).startswith(b'%PDF-'))
        stored=self.client.get(f'/api/orders/{self.order_id}').json['delivery']
        self.assertEqual(stored['buyer_text'],'Client company\nStreet address')
        self.assertEqual(stored['notify_text'],'Client company\nStreet address')

    def test_custom_party_and_contacts_are_retained_beside_linked_notify(self):
        block='Client company\nStreet address\nCountry: USA'
        buyer='Client company\nStreet address\nEmail: buyer@example.com'
        self.client.put(f'/api/orders/{self.order_id}',json={'delivery':{
            'consignee_text':block,'buyer_text':buyer,'notify_text':'Client company\nStreet address'}})
        preview=self.preview()
        parties=next(section for section in preview['layout']['sections'] if section['name']=='parties')
        cells={cell.get('field'):cell for row in parties['rows'] for cell in row}
        self.assertIn('Email: buyer@example.com',cells['delivery.buyer_text']['text'])
        self.assertEqual(cells['delivery.notify_text']['text'],'(Same as consignee)')
        saved=self.client.put(self.base+'/preview/'+preview['preview_id'],json={'delivery':{
            'buyer_text':'Separate buyer\nDifferent address','notify_text':'(Same as consignee)'}})
        self.assertEqual(saved.status_code,200,saved.json)
        parties=next(section for section in saved.json['layout']['sections'] if section['name']=='parties')
        cells={cell.get('field'):cell for row in parties['rows'] for cell in row}
        self.assertIn('Separate buyer',cells['delivery.buyer_text']['text'])
        self.assertEqual(cells['delivery.notify_text']['text'],'(Same as consignee)')

    def test_party_address_and_contacts_have_export_spacing(self):
        preview=self.preview()
        parties=next(section for section in preview['layout']['sections'] if section['name']=='parties')
        cells=[cell for row in parties['rows'] for cell in row if cell.get('party')]
        self.assertEqual(len(cells),3)
        consignee=next(cell for cell in cells if cell['field']=='delivery.consignee_text')
        self.assertEqual(consignee['text'],'Consignee\nOrder destination')
        self.assertTrue(parties['rows'][-1][0]['text'].startswith('USA\n'))
        self.assertTrue(parties['rows'][-1][0]['bottom_aligned'])
        with ZipFile(BytesIO(pi_exports.xlsx(preview['document']))) as book:
            self.assertIn('Consignee\nOrder destination',book.read('xl/sharedStrings.xml').decode())

    def test_edits_recalculate_in_selected_currency_and_keep_source_order_unchanged(self):
        automatic=self.client.post(self.base+'/preview',json={'currency':'INR'})
        self.assertEqual(automatic.status_code,201,automatic.json)
        self.assertEqual(automatic.json['document']['totals']['usd_inr_rate'],'80')
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

    def test_live_calculation_and_excel_formulas_keep_line_and_invoice_totals_in_sync(self):
        preview=self.preview(currency='INR')
        changes=self.edits(preview['document'])
        changes['lines'][0].update(quantity='2',unit_price='100.01')
        changes['shipping_charges']='25.50'
        result=self.client.post(self.base+'/preview/'+preview['preview_id']+'/calculate',json=changes)
        self.assertEqual(result.status_code,200,result.json)
        total=result.json['totals']
        self.assertEqual(total['lines'][0]['line_total'],'200.02')
        self.assertEqual((total['subtotal'],total['tax'],total['grand_total']),('200.02','40.59','266.11'))
        self.assertEqual(total['currency'],'INR')
        bad=self.edits(preview['document']);bad['lines'][0]['quantity']='0'
        self.assertEqual(self.client.post(self.base+'/preview/'+preview['preview_id']+'/calculate',json=bad).status_code,400)
        with ZipFile(BytesIO(pi_exports.xlsx(preview['document']))) as book:
            sheet=ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            formulas=[node.text for node in sheet.findall('.//{*}f')]
            self.assertTrue(any('*I' in formula for formula in formulas))
            self.assertTrue(any('SUM(' in formula for formula in formulas))
            self.assertTrue(any('+N(' in formula for formula in formulas))
            formula_values=[cell.find('{*}v').text for cell in sheet.findall('.//{*}c') if cell.find('{*}f') is not None]
            self.assertIn(preview['document']['totals']['grand_total'].rstrip('0').rstrip('.'),[value.rstrip('0').rstrip('.') for value in formula_values])

    def test_gst_is_below_country_above_phone_and_removed_from_other_parties(self):
        preview=self.preview()
        saved=self.client.put(self.base+'/preview/'+preview['preview_id'],json={
            'order':{'destination':'INDIA'},'consignee_gst_number':'24TEST123',
            'delivery':{'consignee_text':'Company\nStreet\nINDIA\nTel: +919876543210\nEmail: client@example.com',
                'buyer_text':'Buyer\nStreet\nGST No.: 24TEST123','notify_text':'Notify\nStreet\nGST: 24TEST123'}})
        self.assertEqual(saved.status_code,200,saved.json)
        delivery=saved.json['document']['delivery']
        self.assertIn('INDIA\nGST No.: 24TEST123\nTel/Phone:',delivery['consignee_text'])
        self.assertNotIn('GST',delivery['buyer_text']);self.assertNotIn('GST',delivery['notify_text'])

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
        self.assertEqual(self.issue(preview).status_code,201)
        self.assertEqual(len(self.client.get(f'/api/orders/{self.order_id}').json['invoices']),1)

    def test_generation_requires_invoice_numbers_but_contact_omissions_only_warn(self):
        preview=self.preview();url=self.base+'/preview/'+preview['preview_id']+'?for_generation=1'
        for field,label in [('pi_reference','Proforma Invoice No.'),('po_reference','Purchase Order No.')]:
            result=self.client.put(url,json={'order':{field:''}})
            self.assertEqual(result.status_code,400,result.json)
            self.assertIn(label,result.json['error'])
        changes=self.edits(preview['document'])
        changes['lines'][0].update(hsn_code='',item_condition='',description='',uom='')
        changes.update(date='',prepared_phone='unfinished phone',order={'payment_terms':'','delivery_terms':'',
            'delivery_time':'','dispatch_method':''},delivery={'consignee_text':'','buyer_text':'Buyer\nEmail: unfinished',
            'notify_text':''})
        saved=self.client.put(url,json=changes)
        self.assertEqual(saved.status_code,200)
        self.assertNotIn('Consignee GST No.', saved.json['missing_fields'])
        self.assertIn('Consignee Tel/Phone', saved.json['missing_fields'])
        self.assertIn('Consignee PIC', saved.json['missing_fields'])
        self.assertIn('Consignee Email', saved.json['missing_fields'])

    def test_issuance_rejects_missing_purchase_order_number(self):
        preview=self.preview()
        self.assertEqual(self.client.put(self.base+'/preview/'+preview['preview_id'],json={'order':{'po_reference':''}}).status_code,200)
        result=self.issue(preview)
        self.assertEqual(result.status_code,400)
        self.assertIn('Purchase Order No.',result.json['error'])

    def test_numbered_invoice_can_be_generated_without_sku_items(self):
        self.order_id=self.direct(pi_reference='AMT/EMPTY',po_reference='PO-EMPTY',lines=[])['order']['id']
        self.base=f'/api/orders/{self.order_id}/invoices'
        preview=self.preview()
        issued=self.issue(preview)
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertTrue(self.client.get(issued.json['pdf_url']).data.startswith(b'%PDF-'))

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
        self.assertIn('2. PAYMENT Agreed ADVANCE',output)
        self.assertIn('4. SHIPMENT: DISPATCH WITHIN 24 HOURS OF PAYMENT CONFIRMATION',output)

    def test_editable_terms_persist_in_both_exports(self):
        preview=self.preview()
        url=self.base+'/preview/'+preview['preview_id']
        custom='1. Custom warranty <agreed> & approved\n2. Delivery after inspection'
        saved=self.client.put(url,json={'terms':custom})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(pi_exports.terms(saved.json['document']),custom)
        self.assertEqual(self.client.put(url,json={'terms':['bad']}).status_code,400)
        self.assertEqual(self.client.put(url,json={'terms':'x'*20001}).status_code,400)
        issued=self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        self.assertTrue(self.client.get(issued.json['pdf_url']).data.startswith(b'%PDF-'))
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            self.assertIn('Delivery after inspection',book.read('xl/sharedStrings.xml').decode())
        self.assertNotIn('terms',self.client.get(f'/api/orders/{self.order_id}').json['order'])

    def test_amount_in_words_can_be_edited_and_reset_to_calculated_value(self):
        preview=self.preview()
        url=self.base+'/preview/'+preview['preview_id']
        automatic=preview['document']['totals']['amount_in_words']
        bank=next(section for section in preview['layout']['sections'] if section['name']=='bank')
        words=next(cell for row in bank['rows'] for cell in row if cell.get('field')=='amount_in_words')
        self.assertEqual(words['value'],automatic)
        self.assertTrue(words['multiline'])

        custom='Agreed amount in words Only'
        saved=self.client.put(url,json={'amount_in_words':custom})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['document']['amount_in_words'],custom)
        self.assertEqual(saved.json['document']['totals']['amount_in_words'],automatic)
        with ZipFile(BytesIO(pi_exports.xlsx(saved.json['document']))) as book:
            self.assertIn(custom,book.read('xl/sharedStrings.xml').decode())
        self.assertEqual(self.client.put(url,json={'amount_in_words':42}).status_code,400)

        reset=self.client.put(url,json={'amount_in_words':''})
        self.assertEqual(reset.status_code,200,reset.json)
        self.assertNotIn('amount_in_words',reset.json['document'])
        bank=next(section for section in reset.json['layout']['sections'] if section['name']=='bank')
        words=next(cell for row in bank['rows'] for cell in row if cell.get('field')=='amount_in_words')
        self.assertEqual(words['value'],automatic)

    def test_selected_country_owns_both_locations_regardless_of_currency(self):
        usd=self.preview()['document']
        self.assertEqual(usd['order']['destination'],'USA')
        preview=self.preview(currency='INR',usd_inr_rate='80')
        doc=preview['document']
        self.assertEqual(doc['order']['destination'],'USA')
        self.assertIn('USA',doc['delivery']['consignee_text'].splitlines())
        url=self.base+'/preview/'+preview['preview_id']
        saved=self.client.put(url,json={'order':{'destination':'india'},'delivery':{
            'consignee_text':'Updated consignee\nStreet address\nCountry: USA\nGST No.: 24TEST123\nTel/Phone: +919876543210\nPIC: Person\nEmail: person@example.com'}})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['document']['order']['destination'],'INDIA')
        self.assertEqual(saved.json['document']['delivery']['consignee_text'],
            'Updated consignee\nStreet address\nINDIA\nGST No.: 24TEST123\nTel/Phone: +919876543210\nPIC: Person\nEmail: person@example.com')
        again=self.client.put(url,json={})
        self.assertEqual(again.json['document']['delivery'],saved.json['document']['delivery'])
        issued=self.issue(again.json)
        self.assertEqual(issued.status_code,201,issued.json)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            self.assertIn('INDIA',book.read('xl/sharedStrings.xml').decode())
        self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['order']['destination'],'USA')

    def test_india_consignee_gst_is_editable_and_exported_once(self):
        preview=self.preview()
        url=self.base+'/preview/'+preview['preview_id']
        saved=self.client.put(url,json={'order':{'destination':'INDIA'},'consignee_gst_number':'24AAGMO289C1ZP'})
        self.assertEqual(saved.status_code,200,saved.json)
        doc=saved.json['document']
        self.assertEqual(doc['consignee_gst_number'],'24AAGMO289C1ZP')
        self.assertIn('GST No.: 24AAGMO289C1ZP',doc['delivery']['consignee_text'])
        cells=[cell for section in saved.json['layout']['sections'] for row in section['rows'] for cell in row]
        self.assertIn('GST No.: 24AAGMO289C1ZP',next(cell for cell in cells if cell['field']=='delivery.consignee_text')['value'])
        self.assertNotIn('GST No.',next(cell for cell in cells if cell['field']=='delivery.buyer_text')['text'])
        self.assertEqual(self.client.put(url,json={'consignee_gst_number':[]} ).status_code,400)
        issued=self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            self.assertIn('GST No.: 24AAGMO289C1ZP',book.read('xl/sharedStrings.xml').decode())

    def test_consignee_gst_from_order_details_prefills_india_preview(self):
        saved=self.client.put(f'/api/orders/{self.order_id}',json={
            'destination':'INDIA','delivery':{'consignee_text':'Indian consignee\nConsignee street\nGST No.: 24ABC123'}})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['delivery']['consignee']['gst_number'],'24ABC123')
        self.assertEqual(saved.json['order']['currency'],'INR')
        preview=self.preview(currency='INR',usd_inr_rate='80')
        self.assertEqual(preview['document']['consignee_gst_number'],'24ABC123')
        self.assertIn('INDIA',preview['document']['delivery']['consignee_text'].splitlines())

    def test_shared_hsn_applies_to_every_line_and_is_snapshotted(self):
        connection=database.get_db()
        with connection:
            connection.execute("UPDATE app_settings SET value='00123456' WHERE key='hsn_code'")
        connection.close()
        state=self.client.get(f'/api/orders/{self.order_id}').json
        self.assertTrue(all(line['hsn_code']=='00123456' for line in state['lines']))
        preview=self.preview()
        changes=self.edits(preview['document'])
        changes['lines'][0]['hsn_code']='9999'
        saved=self.client.put(self.base+'/preview/'+preview['preview_id'],json=changes)
        self.assertEqual(saved.json['document']['totals']['lines'][0]['hsn_code'],'00123456')
        connection=database.get_db()
        with connection:
            connection.execute("UPDATE app_settings SET value='8888' WHERE key='hsn_code'")
        connection.close()
        self.assertEqual(self.preview()['document']['totals']['lines'][0]['hsn_code'],'8888')
        issued=self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            self.assertIn('00123456',book.read('xl/sharedStrings.xml').decode())

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
        self.assertEqual(next(cell for cell in cells if cell['field']=='prepared_phone')['aria'],'Tel')
        issued=self.issue(saved.json)
        self.assertEqual(issued.status_code,201,issued.json)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            strings=book.read('xl/sharedStrings.xml').decode()
            self.assertIn('Free',strings)
            self.assertIn('Tel:',strings)
            self.assertIn('+919725218537',strings)

    def test_company_grid_keeps_bold_borders_fonts_and_warning_highlight(self):
        preview=self.preview()
        model=preview['layout']
        self.assertEqual(len(model['widths']),11)
        header=next(s for s in model['sections'] if s['name']=='header')['rows']
        self.assertTrue(header[0][0]['line_bottom'])
        payment=next(c for row in header for c in row if c['field']=='order.payment_terms')
        self.assertTrue(payment['line_top'])
        self.assertFalse(payment.get('line_bottom',False))
        for row in header[1:]:
            right=[c for c in row if c['col']>=5]
            for cell in right[1:]:self.assertTrue(cell['open_left'])
            for cell in right[:-1]:self.assertTrue(cell['open_right'])
        with patch('reportlab.pdfgen.canvas.Canvas.drawRightString') as page_footer:
            pi_exports.pdf(preview['document'])
            page_footer.assert_not_called()
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
