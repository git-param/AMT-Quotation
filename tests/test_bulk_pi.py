"""Normal/bulk boundary, snapshot edits, annexure formulas and export coverage."""
from copy import deepcopy
from io import BytesIO
import json
import re
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from backend.orders import pi_exports
from backend.orders.pi_layout import layout
from backend.orders.normal_pi import exports as normal_exports
from backend.orders.normal_pi.layout import layout as normal_layout
from backend.orders.normal_pi.layout import SHIPPING_NOTICE
import test_native_pi


class BulkPiTests(unittest.TestCase):
    setUp = test_native_pi.NativePiTests.setUp
    setUpBase = test_native_pi.NativePiTests.setUpBase
    direct = test_native_pi.NativePiTests.direct
    as_user = test_native_pi.NativePiTests.as_user
    create = test_native_pi.NativePiTests.create
    assign = test_native_pi.NativePiTests.assign
    enquiry = test_native_pi.NativePiTests.enquiry
    share = test_native_pi.NativePiTests.share

    def items(self, count):
        lines = [{'sku': 'BULK-'+str(i), 'description': 'Annexure product '+str(i),
                  'quantity': str(i+1), 'unit_price': '10.25', 'currency': 'USD',
                  'hsn_code': '85371090', 'item_condition': 'New', 'uom': 'PCs'}
                 for i in range(1, count)]
        response = self.client.post(f'/api/orders/{self.order_id}/lines/bulk', json={'lines': lines})
        self.assertEqual(response.status_code, 201, response.json)

    def preview(self, currency='USD', description='Electrical and electronic spare parts'):
        response = self.client.post(self.base+'/preview', json={
            'currency': currency, 'bulk_description': description})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def test_four_remains_normal_five_requires_sales_description(self):
        self.items(4)
        normal = self.client.post(self.base+'/preview', json={'currency': 'USD'})
        self.assertEqual(normal.status_code, 201, normal.json)
        doc = normal.json['document']
        self.assertEqual(doc['pi_format'], 'normal')
        self.assertEqual(layout(doc), normal_layout(doc))
        with ZipFile(BytesIO(pi_exports.xlsx(doc))) as book:
            self.assertEqual(len(ET.fromstring(book.read('xl/workbook.xml')).findall('.//{*}sheet')), 1)
        response = self.client.post(f'/api/orders/{self.order_id}/lines/bulk', json={'lines': [{
            'sku': 'FIFTH', 'description': 'Fifth product', 'quantity': '1',
            'unit_price': '10', 'currency': 'USD'}]})
        self.assertEqual(response.status_code, 201, response.json)
        missing = self.client.post(self.base+'/preview', json={'currency': 'USD'})
        self.assertEqual(missing.status_code, 400)
        self.assertIn('first-page description', missing.json['error'])
        preview = self.preview()
        self.assertEqual(preview['document']['pi_format'], 'bulk')
        self.assertEqual(len(preview['document']['totals']['lines']), 5)
        summary = next(section for section in preview['layout']['sections'] if section['name']=='items')
        fields = [cell['field'] for row in summary['rows'] for cell in row if cell.get('field')]
        self.assertEqual(fields, ['bulk_description'])
        self.assertTrue(all(cell['text'] != 'As per Annexure-1'
                            for row in summary['rows'][2:] for cell in row))
        annexure = next(section for section in preview['layout']['sections'] if section['name']=='annexure')
        self.assertTrue(annexure['annexure'])
        self.assertEqual(len(annexure['rows']), 13)

    def test_bulk_usd_and_inr_export_one_sheet_with_annexure_and_linked_amounts(self):
        self.items(9)
        for currency in ('USD', 'INR'):
            with self.subTest(currency=currency):
                preview = self.preview(currency)
                doc = preview['document']
                raw = pi_exports.pdf(doc)
                self.assertEqual(len(re.findall(rb'/Type /Page\b', raw)), 2)
                with ZipFile(BytesIO(pi_exports.xlsx(doc))) as book:
                    names = [x.get('name') for x in ET.fromstring(book.read('xl/workbook.xml')).findall('.//{*}sheet')]
                    self.assertEqual(names, ['Proforma Invoice'])
                    strings = book.read('xl/sharedStrings.xml').decode()
                    self.assertIn(doc['bulk_description'], strings)
                    self.assertIn('Annexure product 8', strings)
                    self.assertIn('Fixture bank', strings)
                    summary = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
                    formulas = [f.text for f in summary.findall('.//{*}f')]
                    annexure = summary
                    start = int(annexure.find('.//{*}rowBreaks/{*}brk').get('id'))
                    self.assertTrue(any(f == f'J{start+18}' for f in formulas))
                    self.assertTrue(any('ROUND(G' in f.text and '*I' in f.text for f in annexure.findall('.//{*}f')))
                    strings_xml = ET.fromstring(book.read('xl/sharedStrings.xml'))
                    labels = [''.join(si.itertext()) for si in strings_xml]
                    self.assertEqual(labels.count(SHIPPING_NOTICE),1)
                    notice_index=labels.index(SHIPPING_NOTICE)
                    notice_cells=[cell for cell in annexure.findall('.//{*}c')
                                  if cell.get('t')=='s' and cell.find('{*}v') is not None
                                  and cell.find('{*}v').text==str(notice_index)]
                    self.assertEqual(len(notice_cells),1)
                    self.assertLess(int(re.search(r'\d+',notice_cells[0].get('r')).group()),start)
                    title = next(c for c in annexure.findall('.//{*}c')
                                 if c.get('t')=='s' and labels[int(c.find('{*}v').text)]=='Annexure-1')
                    self.assertEqual(title.get('r'), f'A{start+5}')
                    for gap in range(start-2,start+1):
                        self.assertFalse(annexure.findall(f'.//{{*}}row[@r="{gap}"]/{{*}}c'))
                    self.assertTrue(any(f.text.startswith('ROUND(SUM(') for f in annexure.findall('.//{*}f')))
                    cached = [cell.find('{*}v').text for cell in annexure.findall('.//{*}c') if cell.find('{*}f') is not None]
                    self.assertIn(float(doc['totals']['grand_total']), [float(v) for v in cached])
                    self.assertNotIn('xl/vbaProject.bin', book.namelist())

    def test_annexure_cover_shipping_notice_excludes_india(self):
        from backend.orders.normal_pi.layout import SHIPPING_NOTICE
        self.items(5)
        base = self.preview()['document']
        for destination, shown in (('INDIA', False), ('USA', True)):
            with self.subTest(destination=destination):
                doc = deepcopy(base)
                doc['order']['destination'] = destination
                self.assertEqual(layout(doc)['shipping_notice'], SHIPPING_NOTICE if shown else '')
                exporter = pi_exports.renderer(doc)
                original = exporter.Paragraph
                notice_styles = []
                def capture(text, style, *args, **kwargs):
                    if style.name == 'shipping_notice':
                        notice_styles.append(style)
                    return original(text, style, *args, **kwargs)
                from unittest.mock import patch
                with patch.object(exporter, 'Paragraph', side_effect=capture):
                    pdf = pi_exports.pdf(doc)
                self.assertTrue(pdf.startswith(b'%PDF'))
                self.assertEqual(len(re.findall(rb'/Type /Page\b', pdf)), 2)
                self.assertEqual(len(notice_styles), int(shown))
                if shown:
                    self.assertEqual(notice_styles[0].fontSize, 11)
                    self.assertIn('Bold', notice_styles[0].fontName)
                with ZipFile(BytesIO(pi_exports.xlsx(doc))) as book:
                    strings = book.read('xl/sharedStrings.xml').decode()
                    self.assertEqual(strings.count(SHIPPING_NOTICE), int(shown))

    def test_description_and_annexure_edits_persist_print_and_issue_without_changing_order(self):
        self.items(5)
        preview = self.preview('INR')
        original = self.client.get(f'/api/orders/{self.order_id}').json
        url = self.base+'/preview/'+preview['preview_id']
        lines = [{key:line[key] for key in ('id','sku','description','hsn_code','item_condition','uom','quantity','unit_price')}
                 for line in preview['document']['totals']['lines']]
        lines[2].update(description='Edited annexure description', quantity='2', unit_price='100.01')
        saved = self.client.put(url, json={'bulk_description': 'User edited cover description', 'lines': lines})
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json['document']['bulk_description'], 'User edited cover description')
        self.assertEqual(saved.json['document']['totals']['lines'][2]['line_total'], '200.02')
        printed = self.client.post(url+'/print', json={'bulk_description':'Unsaved print edit'})
        self.assertEqual(printed.status_code, 200)
        self.assertEqual(len(re.findall(rb'/Type /Page\b', printed.data)), 2)
        # Print edits never replace the persisted preview or order products.
        issued = self.client.post(self.base+'/issue', json={'preview_id':preview['preview_id']})
        self.assertEqual(issued.status_code, 201, issued.json)
        self.assertEqual(self.client.get(issued.json['pdf_url']).status_code, 200)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            strings = book.read('xl/sharedStrings.xml').decode()
            self.assertIn('User edited cover description', strings)
            self.assertNotIn('Unsaved print edit', strings)
            self.assertIn('Edited annexure description', strings)
        self.assertEqual(self.client.get(f'/api/orders/{self.order_id}').json['lines'], original['lines'])
        self.assertEqual(self.client.post(self.base+'/issue', json={'preview_id':preview['preview_id']}).json, issued.json)

    def test_blank_description_can_print_but_cannot_be_issued(self):
        self.items(5)
        preview = self.preview()
        url = self.base+'/preview/'+preview['preview_id']
        self.assertEqual(self.client.post(url+'/print', json={'bulk_description':''}).status_code, 200)
        saved = self.client.put(url, json={'bulk_description':''})
        self.assertEqual(saved.status_code, 200, saved.json)
        result = self.client.post(self.base+'/issue', json={'preview_id':preview['preview_id']})
        self.assertEqual(result.status_code, 400)
        self.assertIn('first-page description', result.json['error'])
        self.assertEqual(self.client.put(url, json={'pi_format':'normal'}).status_code, 400)

    def test_large_annexure_retains_all_products_and_repeats_headers(self):
        self.items(50)
        preview = self.preview()
        doc = preview['document']
        for line in doc['totals']['lines']:
            line['description'] += '\n'+'Long product details '*35
        self.assertGreater(len(re.findall(rb'/Type /Page\b', pi_exports.pdf(doc))), 2)
        with ZipFile(BytesIO(pi_exports.xlsx(doc))) as book:
            strings = book.read('xl/sharedStrings.xml').decode()
            self.assertIn('Annexure product 49', strings)
            sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            self.assertIsNotNone(sheet.find('.//{*}rowBreaks/{*}brk'))
            formulas = [f.text for f in sheet.findall('.//{*}f')]
            self.assertEqual(sum(f.startswith('ROUND(G') for f in formulas), 50)

    def test_legacy_snapshots_still_use_original_renderer(self):
        preview = self.client.post(self.base+'/preview', json={'currency':'USD'}).json
        doc = deepcopy(preview['document'])
        doc.pop('pi_format', None)
        doc.pop('bulk_description', None)
        doc['totals']['lines'] *= 5
        self.assertEqual(layout(doc), normal_layout(doc))
        self.assertEqual(pi_exports.renderer(doc), normal_exports)

    def test_reference_grid_matches_six_columns_blanks_and_totals_locations(self):
        self.items(9)
        self.client.put(f'/api/orders/{self.order_id}', json={'shipping_charges':'0'})
        preview = self.preview()
        doc = preview['document']
        section = next(section for section in preview['layout']['sections'] if section['name']=='annexure')
        self.assertEqual(section['widths'], [8.5703125,53,14,14.140625,15,16.140625])
        self.assertEqual(section['rows'][0][0]['text'], 'Annexure-1')
        self.assertEqual(section['rows'][0][0]['span'], 6)
        self.assertEqual([cell['text'] for cell in section['rows'][1]],
                         ['Sr No.','Item Description','Condition','Qty','Unit Price\n(USD)','Total Price\n(USD)'])
        self.assertTrue(all(len(row)==6 for row in section['rows'][1:-1]))
        self.assertEqual([cell['col'] for cell in section['rows'][-1]], [0,1,2,3])
        self.assertTrue(all(not cell['text'] for row in section['rows'][11:13] for cell in row))
        summary = section['rows'][13]
        self.assertEqual(summary[0]['text'], 'Amount\nin\nWords')
        self.assertTrue(summary[0]['nowrap'])
        self.assertTrue(all(cell['total_cell'] for cell in summary))
        self.assertTrue(summary[1]['text'].startswith('USD '))
        self.assertEqual([cell['text'] for cell in summary[2:5]], ['Total','47PCs','Total (USD)'])
        self.assertEqual(summary[5]['text'], doc['totals']['subtotal'])
        self.assertEqual(section['rows'][15][4]['text'], 'Final Price')
        self.assertEqual(section['rows'][15][5]['text'], doc['totals']['grand_total'])
        self.assertTrue(all(cell['rowspan']==2 for cell in section['rows'][15][4:]))
        self.assertTrue(all(not cell['text'] for cell in section['rows'][14]))
        self.assertTrue(all(not cell['text'] for cell in section['rows'][16]))
        with ZipFile(BytesIO(pi_exports.xlsx(doc))) as book:
            strings = book.read('xl/sharedStrings.xml').decode()
            self.assertNotIn('Annexure-1 |', strings)
            sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            start = int(sheet.find('.//{*}rowBreaks/{*}brk').get('id'))
            self.assertTrue(all(int(col.get('max'))<=11 for col in sheet.findall('.//{*}col')))
            self.assertEqual(sheet.find(f'.//{{*}}row[@r="{start+18}"]').get('ht'), '40.9')
            self.assertTrue(any(f'A{start+22}:K{start+26}'==merge.get('ref') for merge in sheet.findall('.//{*}mergeCell')))
            merges = {merge.get('ref') for merge in sheet.findall('.//{*}mergeCell')}
            self.assertTrue({f'I{start+20}:I{start+21}',f'J{start+20}:K{start+21}'} <= merges)
            styles = ET.fromstring(book.read('xl/styles.xml'))
            formats = styles.find('{*}cellXfs')
            borders = styles.find('{*}borders')
            for column, offset in (('A',18),('B',18),('F',18),('G',18),('I',18),('J',18),('I',20),('J',20)):
                address = f'{column}{start+offset}'
                cell = sheet.find(f'.//{{*}}c[@r="{address}"]')
                style = formats[int(cell.get('s'))]
                alignment = style.find('{*}alignment')
                self.assertEqual(alignment.get('horizontal'), 'center')
                self.assertEqual(alignment.get('vertical'), 'center')
                border = borders[int(style.get('borderId'))]
                for edge in ('left','right','top','bottom'):
                    self.assertEqual(border.find('{*}'+edge).get('style'), 'medium')

    def test_annexure_uom_and_editable_total_survive_save_print_and_exports(self):
        self.items(5)
        preview = self.preview()
        section = next(section for section in preview['layout']['sections'] if section['name']=='annexure')
        quantity = next(cell for row in section['rows'] for cell in row if cell.get('field')=='lines.0.quantity')
        self.assertEqual(quantity['uom'],'PCs')
        total = next(cell for row in section['rows'] for cell in row if cell.get('field')=='annexure_quantity')
        self.assertTrue(total['auto_quantity'])
        url = self.base+'/preview/'+preview['preview_id']
        changed = self.client.put(url,json={'annexure_quantity':'1 Lot (packed)'})
        self.assertEqual(changed.status_code,200,changed.json)
        self.assertEqual(changed.json['document']['annexure_quantity'],'1 Lot (packed)')
        original_totals = preview['document']['totals']
        self.assertEqual(changed.json['document']['totals'],original_totals)
        response = self.client.post(url+'/calculate',json={'lines':[
            {'id':line['id'],'quantity':'2','uom':'Lot' if index==0 else line['uom']}
            for index,line in enumerate(preview['document']['totals']['lines'])]})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['totals']['annexure_quantity'],'1 Lot (packed)')
        printed = self.client.post(url+'/print',json={'annexure_quantity':'2 Kits (print only)'})
        self.assertEqual(printed.status_code,200,printed.json)
        with ZipFile(BytesIO(pi_exports.xlsx(changed.json['document']))) as book:
            self.assertIn('1 Lot (packed)',book.read('xl/sharedStrings.xml').decode())
            self.assertIn('PCs',book.read('xl/styles.xml').decode())
        self.assertTrue(pi_exports.pdf(changed.json['document']).startswith(b'%PDF-'))
        reset = self.client.put(url,json={'annexure_quantity':''})
        reset_section = next(section for section in reset.json['layout']['sections'] if section['name']=='annexure')
        self.assertNotEqual(next(cell for row in reset_section['rows'] for cell in row if cell.get('field')=='annexure_quantity')['value'],'1 Lot (packed)')

    def test_rate_headings_follow_single_and_mixed_uoms(self):
        from backend.orders.normal_pi.layout import layout, rate_heading
        for unit, heading in [('PCs','PCs'),('Lot','Lot'),('Kit','Kit'),('set','Set')]:
            doc = self.preview()['document']
            doc['totals']['lines'][0]['uom'] = unit
            items = next(section for section in layout(doc)['sections'] if section['name']=='items')
            self.assertEqual(next(cell for cell in items['rows'][0] if cell['col']==8)['text'],'Rate / '+heading)
        self.assertEqual(rate_heading([{'uom':'PCs'},{'uom':'Lot'}]),'Rate / PCs\nor\nRate / Lot')
        self.assertEqual(rate_heading([{'uom':'PCs'},{'uom':'Kit'},{'uom':'set'}]),'Rate / PCs\nor\nRate / Lot')
        self.assertEqual(rate_heading([{'uom':'Kit'},{'uom':'set'}]),'Rate / Lot')

    def test_bulk_calculation_refreshes_annexure_words_and_total_quantity(self):
        self.items(5)
        preview = self.preview()
        lines = [{'id':line['id'],'quantity':'2','unit_price':'100'} for line in preview['document']['totals']['lines']]
        result = self.client.post(self.base+'/preview/'+preview['preview_id']+'/calculate', json={'lines':lines})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['totals']['annexure_quantity'],'10PCs')
        self.assertEqual(result.json['totals']['annexure_amount_in_words'],'USD One thousand dollars Only')

    def test_downloads_and_print_use_the_exact_portable_pi_reference_filename(self):
        self.items(5)
        self.client.put(f'/api/orders/{self.order_id}',json={'pi_reference':'AMT 12938721'})
        preview=self.preview()
        for response in (self.client.get(preview['pdf_url']),
                         self.client.post(self.base+'/preview/'+preview['preview_id']+'/print',json={})):
            self.assertIn('filename="PI-AMT 12938721.pdf"',response.headers['Content-Disposition'])
        issued=self.client.post(self.base+'/issue',json={'preview_id':preview['preview_id']})
        self.assertEqual(issued.status_code,201,issued.json)
        for extension in ('xlsx','pdf'):
            self.assertEqual(issued.json[extension+'_filename'],'PI-AMT 12938721.'+extension)
            response=self.client.get(issued.json[extension+'_url'])
            self.assertIn('filename="PI-AMT 12938721.'+extension+'"',response.headers['Content-Disposition'])
        from backend.orders.filenames import invoice_filename
        self.assertEqual(invoice_filename('AMT/12938721','pdf'),'PI-12938721.pdf')



if __name__ == '__main__':
    unittest.main()
