"""Currency persistence, explicit conversion and both PI export layouts."""
from decimal import Decimal
from io import BytesIO
import json
import unittest
from zipfile import ZipFile

from backend import database
from backend.orders.invoices import amount_words, calculate
from backend.orders.locations import phone_block, CALLING_CODES, COUNTRIES
from backend.orders.parties import parse_block
import test_native_pi
import test_settings


class CurrencyPiTests(unittest.TestCase):
    setUp = test_native_pi.NativePiTests.setUp
    setUpBase = test_native_pi.NativePiTests.setUpBase
    direct = test_native_pi.NativePiTests.direct
    as_user = test_native_pi.NativePiTests.as_user
    create = test_native_pi.NativePiTests.create
    assign = test_native_pi.NativePiTests.assign
    enquiry = test_native_pi.NativePiTests.enquiry
    share = test_native_pi.NativePiTests.share
    preview = test_native_pi.NativePiTests.preview
    issue = test_native_pi.NativePiTests.issue

    def rates(self):
        connection = database.get_db()
        with connection:
            connection.execute("INSERT INTO app_settings(key,value) VALUES('currency_rates',?)",
                               (json.dumps({'AED':'4','GBP':'0.8','EUR':'0.9','INR':'80'}),))
        connection.close()

    def test_new_currencies_persist_print_and_use_correct_amount_words(self):
        for code, words, minor in [('AED','UAE Dirhams','Fils'),('GBP','Pounds Sterling','Pence'),('EUR','Euros','Cents')]:
            with self.subTest(currency=code):
                order = self.direct(currency=code, pi_reference=code+'/123', lines=[{
                    'sku':'PART','description':'Part','quantity':'1','unit_price':'123.45','currency':code,
                    'hsn_code':'85371090','item_condition':'New','uom':'PCs'}])
                self.base = f"/api/orders/{order['order']['id']}/invoices"
                preview = self.preview(currency=code)
                self.assertIn(words, preview['document']['totals']['amount_in_words'])
                self.assertIn(minor, preview['document']['totals']['amount_in_words'])
                issued = self.issue(preview)
                self.assertEqual(issued.status_code,201,issued.json)
                self.assertTrue(self.client.get(issued.json['pdf_url']).data.startswith(b'%PDF-'))
                with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
                    self.assertIn(words,book.read('xl/sharedStrings.xml').decode())

    def test_configured_cross_conversion_and_discount_edits_use_saved_rates(self):
        self.rates()
        self.client.put(f'/api/orders/{self.order_id}/discount',json={'type':'amount','value':'1','scope':'all','line_ids':[],'show_on_pi':True})
        preview = self.preview(currency='AED')
        self.assertEqual(preview['document']['totals']['lines'][0]['unit_price'],'49.36')
        self.assertEqual(preview['document']['totals']['shipping'],'40.00')
        self.assertEqual(preview['document']['totals']['exchange_rates']['AED'],'4')
        self.assertEqual(preview['document']['totals']['discount_total'],'4.00')
        connection = database.get_db()
        with connection:
            connection.execute("UPDATE app_settings SET value=? WHERE key='currency_rates'", (json.dumps({'AED':'8'}),))
        connection.close()
        saved = self.client.put(self.base+'/preview/'+preview['preview_id'],json={'shipping_charges':'40.00'})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['document']['totals']['discount_total'],'4.00')
        self.assertEqual(saved.json['document']['totals']['lines'][0]['unit_price'],'49.36')

    def test_missing_conversion_rate_is_actionable_and_bulk_words_match_currency(self):
        result = self.client.post(self.base+'/preview',json={'currency':'EUR'})
        self.assertEqual(result.status_code,400)
        self.assertIn('Configuration',result.json['error'])
        self.rates()
        self.client.post(f'/api/orders/{self.order_id}/lines/bulk',json={'lines':[
            {'sku':str(i),'description':'Part','quantity':'1','unit_price':'10','currency':'USD',
             'hsn_code':'85371090','item_condition':'New','uom':'PCs'} for i in range(4)]})
        preview = self.preview(currency='GBP',bulk_description='Spare parts')
        issued = self.issue(preview)
        self.assertEqual(issued.status_code,201,issued.json)
        with ZipFile(BytesIO(self.client.get(issued.json['xlsx_url']).data)) as book:
            self.assertIn('Pounds Sterling',book.read('xl/sharedStrings.xml').decode())
        self.assertTrue(self.client.get(issued.json['pdf_url']).data.startswith(b'%PDF-'))


class CurrencySettingsTests(test_settings.SettingsTests):
    def test_only_admin_can_set_positive_rates(self):
        self.as_user('tl1')
        self.assertEqual(self.client.put('/api/currency-rates',json={'rates':{'AED':'4'}}).status_code,403)
        self.as_user('admin')
        for value in ('0','-1','NaN',True,'1.1234567'):
            self.assertEqual(self.client.put('/api/currency-rates',json={'rates':{'AED':value}}).status_code,400)
        saved = self.client.put('/api/currency-rates',json={'rates':{'AED':'4','GBP':'0.8','EUR':'0.9'}})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(self.client.get('/api/currency-rates').json,saved.json)


class CurrencyWordsTests(unittest.TestCase):
    def test_words_are_currency_specific_and_round_cents(self):
        self.assertEqual(amount_words(Decimal('1.999'),'EUR'),'Two Euros Only')
        self.assertIn('Fifty Fils',amount_words(Decimal('1.50'),'AED'))
        self.assertIn('Fifty Pence',amount_words(Decimal('1.50'),'GBP'))

    def test_country_codes_cover_the_country_picker_and_remain_editable(self):
        self.assertTrue(COUNTRIES.issubset(CALLING_CODES))
        result = phone_block('Company\nStreet\nTel: 2025550123', 'USA')
        self.assertIn('Tel/Phone: +1 2025550123', result)
        self.assertEqual(parse_block(result,'USA')[1]['phone'],'+12025550123')
        self.assertIn('+971 501234567',phone_block('Company\nTel: 0501234567','UAE'))
        self.assertIn('+919876543210',phone_block('Company\nTel: +919876543210','UK'))
        self.assertEqual(parse_block('Company\nTel/Phone: +1','USA')[1]['phone'],'')

    def test_cross_conversion_uses_both_currency_rates(self):
        totals = calculate({'order':{'currency':'GBP','shipping_charges':'8'},'lines':[
            {'id':1,'currency':'GBP','unit_price':'8','quantity':'1'}]}, 'EUR',
            {'USD':'1','GBP':'0.8','EUR':'0.9'}, Decimal('0'))
        self.assertEqual(totals['lines'][0]['unit_price'],'9.00')
        self.assertEqual(totals['shipping'],'9.00')
        self.assertEqual(totals['amount_in_words'],'Eighteen Euros Only')
