"""Immutable PI workbooks, using the company's configured XLSM templates.

Edit OOXML directly so styles, logos, print settings and company/bank details
survive without executing VBA or requiring Excel on the application server.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import json
import os
from pathlib import Path
import re
import textwrap
from uuid import uuid4
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

from flask import jsonify, request, send_file

from backend.common.auth import authenticated_required, get_current_user
from backend.database import get_db
from backend.settings import allocate_pi_reference
from backend.security.audit import record_action
from backend.enquiries.lines import number
from backend.common.currencies import CURRENCIES, UNITS
from backend.orders.routes import bp
from backend.orders.service import details, read_order, record_revision, delivery

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
Q = '{' + NS + '}'
ET.register_namespace('', NS)
CENT = Decimal('0.01')


def company_payment_terms(raw, sheet):
    """Use the configured template's terms when the simplified form omits them."""
    cell = sheet.find('.//' + Q + 'c[@r="F8"]')
    if cell is None:
        raise ValueError('Company template payment terms are missing.')
    value = cell.find(Q + 'v')
    if cell.get('t') == 's' and value is not None:
        with ZipFile(BytesIO(raw)) as workbook:
            strings = ET.fromstring(workbook.read('xl/sharedStrings.xml'))
            content = ''.join(strings.findall(Q + 'si')[int(value.text)].itertext())
    elif cell.get('t') == 'inlineStr':
        content = ''.join(cell.find(Q + 'is').itertext())
    else:
        content = ''
    match = re.fullmatch(r'Payment Terms\s*:\s*(.+)', content.strip(), flags=re.I)
    if not match or len(match[1]) > 2000:
        raise ValueError('Configure payment terms in the company PI template.')
    return match[1].strip()


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def words_integer(value):
    small = ('Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven '
             'Twelve Thirteen Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen').split()
    tens = ('Zero Ten Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety').split()
    if value < 20:
        return small[value]
    if value < 100:
        return tens[value // 10] + (' ' + small[value % 10] if value % 10 else '')
    if value < 1000:
        return small[value // 100] + ' Hundred' + (
            ' ' + words_integer(value % 100) if value % 100 else '')
    for scale, label in ((10**12, 'Trillion'), (10**9, 'Billion'),
                         (10**6, 'Million'), (1000, 'Thousand')):
        if value >= scale:
            return words_integer(value // scale) + ' ' + label + (
                ' ' + words_integer(value % scale) if value % scale else '')


def amount_words(value, currency):
    value = money(value)
    whole = int(value)
    cents = int((value - whole) * 100)
    major, minor = UNITS[currency]
    return (words_integer(whole) + ' ' + major
            + (' and ' + words_integer(cents) + ' ' + minor if cents else '') + ' Only')


def template(currency):
    defaults = {'USD': 'Updated PI Format USD - 180626 2.xlsm',
                'INR': 'Updated PI Format INR 1 2 2.xlsm'}
    downloads = Path.home() / 'Downloads'
    default = downloads / defaults[currency]
    if not default.is_file():
        default = downloads / ('pi-' + currency + '.xlsm')
    path = Path(os.environ.get('PI_TEMPLATE_' + currency, str(default)))
    try:
        raw = path.read_bytes()
        with ZipFile(BytesIO(raw)) as workbook:
            sheet = ET.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
            shared = ET.fromstring(workbook.read('xl/sharedStrings.xml'))
            strings = [''.join(node.itertext()) for node in shared.findall(Q + 'si')]
    except (OSError, BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError('Company PI template is unavailable. Configure PI_TEMPLATE_'
                         + currency + ' on the server.') from error
    # Fail closed if a different layout is configured. Never overwrite unknown
    # cells, or issue a document missing the company's bank information.
    def cell_text(ref):
        cell = sheet.find('.//' + Q + 'c[@r="' + ref + '"]')
        if cell is None:
            return ''
        value = cell.find(Q + 'v')
        if value is None:
            return ''.join(cell.itertext())
        return strings[int(value.text)] if cell.get('t') == 's' else value.text
    first = 23 if currency == 'USD' else 24
    if (cell_text('A2') != 'PROFORMA INVOICE'
            or cell_text('A' + str(first + 4)) != 'BANK DETAIL'
            or not cell_text('A5') or not cell_text('A' + str(first + 7))):
        raise ValueError('Company PI template layout or bank configuration is invalid.')
    tax = Decimal(0)
    if currency == 'INR':
        formula = sheet.find('.//' + Q + 'c[@r="J33"]/' + Q + 'f')
        match = re.fullmatch(r'J32\s*\*\s*(\d+(?:\.\d+)?)%',
                             formula.text.strip() if formula is not None else '')
        if not match:
            raise ValueError('INR template must define its validated GST percentage in J33.')
        tax = Decimal(match[1]) / 100
        if not 0 <= tax <= 1:
            raise ValueError('Invalid company template GST percentage.')
    return raw, sheet, first, tax


def calculate(state, currency, rate, tax_rate):
    order = state['order']
    sources = {line['currency'] for line in state['lines']} | {order['currency']}
    conversion = any(code != currency for code in sources)
    exchange_rates = rate if isinstance(rate, dict) else None
    if conversion:
        if exchange_rates is not None:
            if any(code not in exchange_rates for code in sources | {currency}):
                raise ValueError('Configure exchange rates for all item and PI currencies.')
            exchange_rates = {key: Decimal(str(value)) for key, value in exchange_rates.items()}
            if any(not value.is_finite() or value <= 0 for value in exchange_rates.values()):
                raise ValueError('Exchange rates must be positive.')
        elif not sources.union({currency}).issubset({'USD','INR'}):
            raise ValueError('Configure exchange rates before converting this PI.')
        elif rate is None:
            raise ValueError('Enter INR per 1 USD to convert currencies.')
        if exchange_rates is None:
            scaled = number(rate, 6, Decimal('1000000'), True)
            rate = Decimal(scaled) / 1000000
    elif rate is not None:
        raise ValueError('No exchange rate is needed when all amounts use PI currency.')

    def convert(value, source):
        value = Decimal(value)
        if source != currency:
            value = (value / exchange_rates[source] * exchange_rates[currency] if exchange_rates
                     else value * rate if source == 'USD' else value / rate)
        return money(value)

    lines = []
    for line in state['lines']:
        # When a customer discount is entered, calculate it from the original
        # catalog rate captured at lookup. Keep the agreed sale rate for orders
        # without an additional customer discount.
        source_price = line['unit_price']
        discount = order.get('discount') or {}
        uses_original = (discount.get('scope') in ('all', 'total')
                         or line['id'] in discount.get('line_ids', []))
        if uses_original and line.get('catalog_original_price') is not None:
            source_price = line['catalog_original_price']
        base_price = line.get('policy_base_price')
        if base_price is None:
            base_price = Decimal(line.get('policy_price_minor') if line.get('policy_price_minor') is not None else Decimal(line['unit_price'])*100)/100
        base_currency=line.get('policy_currency') or line['currency']
        if line.get('policy_base_price') is None and base_currency!=line['currency']:
            from backend.common.currencies import configured_rates
            from backend.database import get_db
            db=get_db()
            try:base_rates={'USD':'1',**configured_rates(db)}
            finally:db.close()
            if not base_rates.get(base_currency) or not base_rates.get(line['currency']):
                raise ValueError('Configure rates for the original item price currency.')
            base_price=Decimal(base_price)/Decimal(str(base_rates[base_currency]))*Decimal(str(base_rates[line['currency']]))
        policy_base = convert(base_price,line['currency'])
        if uses_original and line.get('catalog_original_price') is not None:
            if money(line['unit_price'])!=money(base_price):source_price=line['unit_price']
            policy_base=convert(line['catalog_original_price'],line['currency'])
        price = convert(source_price, line['currency'])
        # Round converted unit price first, then extend by whole-unit quantity.
        total = money(price * Decimal(line['quantity']))
        lines.append({**line, 'source_currency': line['currency'],
                      'source_unit_price': source_price, 'currency': currency, 'policy_base_price':format(policy_base,'.2f'),
                      'unit_price': format(price, '.2f'), 'line_total': format(total, '.2f'),
                      **{key:format(convert(line[key],line['currency']),'.2f') for key in ('catalog_original_price','catalog_sale_price') if line.get(key) is not None}})
    from backend.orders.discounts import apply
    lines, summary_discount, discount_total = apply(lines, order.get('discount'),
        lambda value: convert(value, order['currency']), currency)
    from backend.orders.policy import check_reduction
    for line in lines:
        check_reduction(Decimal(line['policy_base_price'])*Decimal(line['quantity']),
                        Decimal(line['line_total']),sku=line['sku'])
    if summary_discount:
        gross=sum((Decimal(line['line_total']) for line in lines),Decimal(0))
        baseline=sum((Decimal(line['policy_base_price'])*Decimal(line['quantity']) for line in lines),Decimal(0))
        check_reduction(baseline,gross-summary_discount)
    subtotal = sum((Decimal(line['line_total']) for line in lines), Decimal(0)) - summary_discount
    shipping = convert(order['shipping_charges'], order['currency'])
    bank_charges = convert(order.get('bank_charges', '0'), order['currency'])
    # Total discounts reduce the goods subtotal before GST is calculated.
    tax = money((subtotal + shipping + bank_charges) * tax_rate)
    grand = money(subtotal + shipping + bank_charges + tax)
    return {'currency': currency, 'usd_inr_rate': str(rate) if conversion and not exchange_rates else None,
            'exchange_rates': {key:str(value) for key,value in exchange_rates.items()} if exchange_rates else None,
            'conversion_rule': ('USD-based rates: source amount / source rate * target rate; rounded HALF_UP to 2 decimals' if exchange_rates else '1 USD = rate INR; converted unit rates rounded HALF_UP '
                               'to 2 decimals before quantity; shipping rounded separately'),
            'lines': lines, 'subtotal': format(subtotal, '.2f'),
            'summary_discount': format(summary_discount, '.2f'),
            'discount_total': format(discount_total, '.2f'),
            'goods_total': format(subtotal + summary_discount, '.2f'),
            'shipping': format(shipping, '.2f'), 'tax_rate': str(tax_rate),
            'bank_charges': format(bank_charges, '.2f'),
            'tax': format(tax, '.2f'), 'grand_total': format(grand, '.2f'),
            'amount_in_words': amount_words(grand, currency)}


def render(raw, sheet, first, state, totals, reference, issued, prepared_by):
    """Expand the four styled slots and move every downstream print range."""
    data = sheet.find(Q + 'sheetData')
    count = len(totals['lines'])
    extra = max(0, count - 4)
    threshold = first + 4

    def shift(value):
        return re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)', lambda m: m[1] + str(
            int(m[2]) + extra if int(m[2]) >= threshold else int(m[2])), value)

    style_row = deepcopy(data.find(Q + f'row[@r="{first}"]'))
    if extra:
        for node in sheet.iter():
            for key in ('r', 'ref', 'sqref'):
                if key in node.attrib:
                    if key == 'r' and node.tag == Q + 'row':
                        node.set(key, str(int(node.get(key)) + extra
                                         if int(node.get(key)) >= threshold else int(node.get(key))))
                    else:
                        node.set(key, shift(node.get(key)))
            if node.tag == Q + 'f' and node.text:
                node.text = shift(node.text)
        merges = sheet.find(Q + 'mergeCells')
        originals = list(merges) if merges is not None else []
        for index in range(4, count):
            row = deepcopy(style_row)
            row.set('r', str(first + index))
            for cell in row:
                cell.set('r', re.sub(r'\d+', str(first + index), cell.get('r')))
            data.append(row)
            for merge in originals:
                if re.fullmatch(r'[A-Z]+' + str(first) + r':[A-Z]+' + str(first), merge.get('ref', '')):
                    new_merge = deepcopy(merge)
                    new_merge.set('ref', re.sub(r'\d+', str(first + index), merge.get('ref')))
                    merges.append(new_merge)
        if merges is not None:
            merges.set('count', str(len(merges)))

    def put(ref, value, numeric=False):
        cell = sheet.find('.//' + Q + 'c[@r="' + ref + '"]')
        if cell is None:
            row_number = re.search(r'\d+', ref)[0]
            row = data.find(Q + 'row[@r="' + row_number + '"]')
            if row is None:
                row = ET.SubElement(data, Q + 'row', r=row_number)
            cell = ET.SubElement(row, Q + 'c', r=ref)
        for child in list(cell):
            cell.remove(child)
        cell.set('t', 'n' if numeric else 'inlineStr')
        if numeric:
            ET.SubElement(cell, Q + 'v').text = str(value)
        else:
            ET.SubElement(ET.SubElement(cell, Q + 'is'), Q + 't').text = str(value)

    order, dest = state['order'], state['delivery']
    def address_text(value):
        return '\n'.join(str(v) for v in value.values() if v)
    def party_text(value):
        contacts = '\n'.join(str(value.get(k, '')) for k in
                             ('name', 'pic', 'email', 'phone', 'gst_number') if value.get(k))
        return '\n'.join(filter(None, [contacts, address_text(value.get('address', {}))]))
    for ref, value in {
        'H4': reference, 'H5': issued, 'H6': order['po_reference'],
        'F7': 'Prepared By: ' + prepared_by,
        'F8': 'Payment Terms: ' + order['payment_terms'],
        'F9': 'Delivery Terms: ' + order['delivery_terms'], 'H9': order['destination'],
        'F10': 'Delivery Time: ' + order['delivery_time'],
        'I10': 'Dispatch By: ' + order['dispatch_method'],
        'A12': dest['consignee']['name'], 'A13': address_text(dest['shipping_address']),
        'A17': dest['shipping_address']['country'],
        'F12': (party_text(dest['buyer']) or dest['consignee']['name'])
               + '\n' + address_text(dest['billing_address'])
               if dest['buyer'].get('name') or dest['billing_address'] else '(Same as consignee)',
        ('F18' if totals['currency'] == 'USD' else 'F19'):
            party_text(dest['notify_party']) or '(Same as consignee)',
    }.items():
        put(ref, value)
    # Freeform buyer/notify blocks must appear exactly as edited, including
    # unique commercial lines. Historical structured parties retain old layout.
    if 'buyer_text' in dest:
        put('F12', dest['buyer_text'] or '(Same as consignee)')
    if 'notify_text' in dest:
        put('F18' if totals['currency'] == 'USD' else 'F19',
            dest['notify_text'] or '(Same as consignee)')
    if 'consignee_text' in dest:
        # Contact/country labels remain in their established template cells.
        # Grow merged party areas vertically so multiline text remains visible.
        for start, end, content in ((12, 16, dest.get('buyer_text', '')),
                (18 if totals['currency'] == 'USD' else 19,
                 20 if totals['currency'] == 'USD' else 21, dest.get('notify_text', '')),
                (13, 16, dest['shipping_address'].get('line1', ''))):
            line_count = sum(max(1, (len(line) + 39) // 40) for line in content.splitlines())
            height = min(409, max(19, (line_count * 15 + end - start) // (end - start + 1)))
            for number in range(start, end + 1):
                row = data.find(Q + f'row[@r="{number}"]')
                if row is not None:
                    row.set('ht', str(max(float(row.get('ht', 19)), height)))
                    row.set('customHeight', '1')
    offset = 0 if totals['currency'] == 'USD' else 1
    if offset:
        put('A18', 'GST No: ' + dest['consignee'].get('gst_number', ''))
    for row, key, label in ((18, 'phone', 'Tel: '), (19, 'pic', 'PIC: '), (20, 'email', 'Email: ')):
        put('A' + str(row + offset), label + dest['consignee'].get(key, ''))
    put('B' + str(first - 1), 'Item rates in ' + totals['currency'])
    for index in range(max(4, count)):
        line = totals['lines'][index] if index < count else None
        for col, key in (('A', None), ('B', 'description'), ('E', 'hsn_code'),
                         ('F', 'item_condition'), ('G', 'quantity'), ('H', 'uom'),
                         ('I', 'unit_price'), ('J', 'line_total')):
            value = (index + 1 if key is None else line[key]) if line else ''
            if col == 'B' and line:
                value = line['sku'] + ' / ' + value
            put(col + str(first + index), value, bool(line) and col in ('A', 'G', 'I', 'J'))
        if line:
            row = data.find(Q + f'row[@r="{first + index}"]')
            row.set('ht', str(min(409, max(32, 15 * (1 + len(line['description']) // 32)))))
            row.set('customHeight', '1')
    if totals['currency'] == 'USD':
        values = {31: totals['subtotal'], 32: totals['shipping'], 33: totals['grand_total']}
        words_row = 33
    else:
        values = {31: totals['shipping'],
                  32: str(Decimal(totals['subtotal']) + Decimal(totals['shipping'])),
                  33: totals['tax'], 34: totals['grand_total']}
        words_row = 34
    for row, value in values.items():
        put('J' + str(row + extra), value, True)
    put('C' + str(words_row + extra), totals['amount_in_words'])
    # Keep the template's payment clause consistent with the issued order header.
    put('A' + str((36 if totals['currency'] == 'USD' else 37) + extra),
        '2. PAYMENT ' + re.sub(r'\badvance\b','ADVANCE',order['payment_terms'],flags=re.I))
    # Add wrapped notes below the complete original terms, expanding the print
    # area rather than truncating long notes in one merged cell.
    note_row = (52 if totals['currency'] == 'USD' else 51) + extra
    note_style = sheet.find('.//' + Q + 'c[@r="A' + str(46 + extra) + '"]')
    merges = sheet.find(Q + 'mergeCells')
    for paragraph in filter(None, [dest['instructions'], order['notes']]):
        for line in paragraph.splitlines():
            for chunk in textwrap.wrap(line, width=110) or ['']:
                ref = 'A' + str(note_row)
                put(ref, chunk)
                if note_style is not None and note_style.get('s'):
                    sheet.find('.//' + Q + f'c[@r="{ref}"]').set('s', note_style.get('s'))
                row = data.find(Q + f'row[@r="{note_row}"]')
                row.set('ht', '32')
                row.set('customHeight', '1')
                if merges is not None:
                    ET.SubElement(merges, Q + 'mergeCell', ref=f'A{note_row}:K{note_row}')
                note_row += 1
    if merges is not None:
        merges.set('count', str(len(merges)))
    # ElementTree drops namespace declarations used only by Ignorable tokens.
    # Removing the advisory attribute avoids undeclared-prefix repair in Excel.
    ignorable = '{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable'
    sheet.attrib.pop(ignorable, None)
    # OOXML requires sorted row/cell order.
    def column_number(cell):
        value = 0
        for ch in re.match('[A-Z]+', cell.get('r'))[0]:
            value = value * 26 + ord(ch) - 64
        return value
    for row in data:
        row[:] = sorted(row, key=column_number)
    data[:] = sorted(data, key=lambda row: int(row.get('r')))
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, 'w') as target:
        for item in source.infolist():
            # Cached calculation chains reference the original rows.
            if item.filename == 'xl/calcChain.xml':
                continue
            content = source.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                content = ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
            elif item.filename == 'xl/workbook.xml':
                book = ET.fromstring(content)
                book.attrib.pop(ignorable, None)
                for node in book.findall('.//' + Q + 'definedName'):
                    if node.text:
                        node.text = shift(node.text)
                    if node.get('name') == '_xlnm.Print_Area':
                        # Keep helper country columns outside printed pages.
                        node.text = re.sub(r'(\$[A-Z]+\$)(\d+)$', lambda match:
                            match[1] + str(max(int(match[2]), note_row)), node.text)
                content = ET.tostring(book, encoding='utf-8', xml_declaration=True)
            elif item.filename in ('[Content_Types].xml', 'xl/_rels/workbook.xml.rels'):
                root = ET.fromstring(content)
                for node in list(root):
                    if ('calcChain' in node.get('PartName', '')
                            or node.get('Type', '').endswith('/calcChain')):
                        root.remove(node)
                content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            target.writestr(item, content)
    return output.getvalue()


@bp.route('/api/orders/<int:order_id>/invoices', methods=['POST'])
@authenticated_required
def generate_invoice(order_id):
    connection = get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user = get_current_user()
        order = read_order(connection, user, order_id)
        if not order:
            return jsonify(error='PI not found.'), 404
        if not order['can_edit']:
            return jsonify(error='Client access is read-only.'), 403
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) - {'currency', 'usd_inr_rate'}
                or data.get('currency') not in ('USD', 'INR')):
            raise ValueError('Choose USD or INR PI currency.')
        if order['status'] == 'cancelled':
            raise ValueError('Cancelled orders cannot generate a PI.')
        generated_reference = allocate_pi_reference(connection, user['id'])
        order = dict(order)
        order['pi_reference'] = generated_reference
        state = details(connection, order)
        if state['order'].get('discount'):
            raise ValueError('Use Preview PI to generate a discounted invoice with PDF and Excel exports.')
        if Decimal(state['order'].get('bank_charges', '0')):
            raise ValueError('Use Preview PI to include bank charges in the invoice.')
        state['order']['delivery_terms'] = 'DAP'
        if not state['lines'] or state['legacy_lines_requiring_review']:
            raise ValueError('Complete and review all order SKU lines before generating a PI.')
        if any(not line.get('hsn_code') or not line.get('item_condition') for line in state['lines']):
            missing = state['pi_line_requirements']
            return jsonify(error='Complete HSN code and item condition for: '
                           + ', '.join(line['sku'] for line in missing)
                           + '. Save item details, then generate the PI.',
                           code='pi_lines_incomplete', missing_lines=missing), 400
        if not state['delivery']:
            raise ValueError('Complete the order delivery details before generating a PI.')
        from backend.orders.pi_document import validate_ready, party_block
        destination = state['delivery'] or {}
        validate_ready({'reference': order['pi_reference'], 'currency': data['currency'], 'order': state['order'], 'delivery': {
            'consignee_text': destination.get('consignee_text') or party_block(destination.get('consignee'), destination.get('shipping_address')),
        }})
        client = connection.execute('SELECT * FROM client_leads WHERE id = ?', (order['client_id'],)).fetchone()
        validated_delivery, _, _ = delivery(connection, client, {}, state['delivery'],
                                             destination=order['destination'])
        state['delivery'].update(validated_delivery)
        for key in ('delivery_terms', 'destination', 'delivery_time', 'dispatch_method'):
            if not order[key]:
                raise ValueError('Complete ' + key.replace('_', ' ') + ' before generating a PI.')
        raw, sheet, first, tax = template(data['currency'])
        payment_source = 'order'
        if not state['order']['payment_terms']:
            state['order']['payment_terms'] = company_payment_terms(raw, sheet)
            payment_source = 'company_template'
        totals = calculate(state, data['currency'], data.get('usd_inr_rate'), tax)
        reference = order['pi_reference']
        issued = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
        workbook = render(raw, sheet, first, state, totals, reference, issued, user['username'])
        snapshot = {'state': state, 'totals': totals, 'reference': reference, 'date': issued,
                    'payment_terms_source': payment_source}
        cursor = connection.execute('INSERT INTO order_invoices '
            '(order_id, reference, currency, snapshot_json, workbook, created_by) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (order_id, reference, data['currency'], json.dumps(snapshot), workbook, user['id']))
        connection.execute("UPDATE client_orders SET pi_reference = ?, pi_date = ?, status = 'completed', "
            "updated_by = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (reference, issued, user['id'], order_id))
        record_revision(connection, order_id, user, 'edit')
        record_action('pi_generate', 'order', order_id,
                      {'invoice_id': cursor.lastrowid, 'reference': reference,
                       'currency': data['currency'],
                       'usd_inr_rate': totals['usd_inr_rate']}, actor=user,
                      connection=connection)
        connection.commit()
        return jsonify(id=cursor.lastrowid, reference=reference, totals=totals,
                       download_url=f'/api/orders/{order_id}/invoices/{cursor.lastrowid}/download'), 201
    except ValueError as error:
        return jsonify(error=str(error), missing_fields=getattr(error, 'missing_fields', [])), 400
    finally:
        connection.rollback()
        connection.close()


@bp.route('/api/orders/<int:order_id>/invoices/<int:invoice_id>',methods=['DELETE'])
@authenticated_required
def remove_invoice(order_id, invoice_id):
    connection=get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user=get_current_user()
        order=read_order(connection,user,order_id)
        if not order:return jsonify(error='PI not found.'),404
        if not order['can_edit'] or not order['can_delete_order']:
            return jsonify(error='PI removal is not permitted.'),403
        invoice=connection.execute('SELECT id,reference,currency FROM order_invoices '
            'WHERE id=? AND order_id=? AND deleted_at IS NULL',(invoice_id,order_id)).fetchone()
        if not invoice:return jsonify(error='PI not found.'),404
        connection.execute("UPDATE order_invoices SET deleted_by=?,deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (user['id'],invoice_id))
        record_revision(connection,order_id,user,'edit')
        record_action('pi_remove', 'order', order_id,
                      {'invoice_id': invoice_id, 'reference': invoice['reference'],
                       'currency': invoice['currency']}, actor=user,
                      connection=connection)
        connection.commit()
        return jsonify(message='PI removed.')
    finally:connection.rollback();connection.close()


@bp.route('/api/orders/<int:order_id>/invoices/<int:invoice_id>/download')
@authenticated_required
def download_invoice(order_id, invoice_id):
    from backend.orders.filenames import invoice_filename
    connection = get_db()
    try:
        if not read_order(connection, get_current_user(), order_id):
            return jsonify(error='PI not found.'), 404
        invoice = connection.execute('SELECT * FROM order_invoices WHERE id = ? AND order_id = ? AND deleted_at IS NULL',
                                     (invoice_id, order_id)).fetchone()
        if not invoice:
            return jsonify(error='PI not found.'), 404
        output_format=request.args.get('format',invoice['workbook_format'])
        from backend.orders.pi_document import missing_details
        from backend.orders import pi_exports
        document=json.loads(invoice['snapshot_json'])
        missing=missing_details(document)
        has_missing_contacts=any(field in missing for field in (
            'Consignee Tel/Phone','Consignee PIC','Consignee Email','Consignee GST No.'))
        if output_format=='pdf':
            if invoice['pdf'] is None:
                return jsonify(error='This historical PI does not have a saved PDF.'),404
            from backend.orders.pi_document import validate_pdf_details
            try:
                validate_pdf_details(document)
            except ValueError as error:
                return jsonify(error=str(error), missing_fields=getattr(error, 'missing_fields', [])), 400
            output=pi_exports.pdf(document) if has_missing_contacts else invoice['pdf']
            return send_file(BytesIO(output),as_attachment=True,
                download_name=invoice_filename(invoice['reference'],'pdf'),mimetype='application/pdf')
        if output_format!=invoice['workbook_format']:
            return jsonify(error='The requested PI format is not available.'),400
        output=pi_exports.xlsx(document) if has_missing_contacts and output_format=='xlsx' else invoice['workbook']
        return send_file(BytesIO(output), as_attachment=True,
                         download_name=invoice_filename(invoice['reference'],output_format),
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if output_format=='xlsx'
                         else 'application/vnd.ms-excel.sheet.macroEnabled.12')
    finally:
        connection.close()
