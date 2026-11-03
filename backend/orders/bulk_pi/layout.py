"""A one-lot PI summary followed by the complete, editable Annexure-1."""
from copy import deepcopy
from decimal import Decimal

from backend.orders.normal_pi.layout import WIDTHS, layout as normal_layout, terms, display_uom
from backend.orders.invoices import amount_words

# Original Annexure-1 workbook columns B:G.
ANNEXURE_WIDTHS = [8.5703125, 53, 14, 14.140625, 15, 16.140625]


def quantity_summary(doc):
    if doc.get('annexure_quantity'):
        return doc['annexure_quantity']
    units = {}
    for line in doc['totals']['lines']:
        unit = display_uom(line.get('uom') or 'PCs')
        units[unit] = units.get(unit, Decimal('0')) + Decimal(line['quantity'])
    return '; '.join(f'{value:g}{unit}' for unit, value in units.items())


def layout(doc):
    summary = deepcopy(doc)
    originals = doc['totals']['lines']
    codes = {line.get('hsn_code', '') for line in originals}
    conditions = {line.get('item_condition', '') for line in originals}
    summary['totals']['lines'] = [{**originals[0],
        'description': doc.get('bulk_description', ''),
        'hsn_code': next(iter(codes)) if len(codes) == 1 else 'As per Annexure-1',
        'item_condition': next(iter(conditions)) if len(conditions) == 1 else 'As per Annexure-1',
        'quantity': '1', 'uom': 'Lot', 'unit_price': doc['totals'].get('goods_total', doc['totals']['subtotal']),
        'line_total': doc['totals'].get('goods_total', doc['totals']['subtotal'])}]
    summary['totals']['lines'][0].pop('discount_label', None)
    summary['totals']['lines'][0].pop('net_unit_price', None)
    model = normal_layout(summary)
    items = next(section for section in model['sections'] if section['name'] == 'items')
    for cell in items['rows'][0]:
        if cell['col'] == 8:
            cell['text'] = 'Rate / Lot'
    for cell in items['rows'][1]:
        if cell.get('field') == 'lines.0.description':
            cell.update(field='bulk_description', label='', aria='First-page description',
                        text=doc.get('bulk_description', ''),
                        value=doc.get('bulk_description', ''))
        else:
            cell['field'] = None
            cell.pop('uom_field', None)
            if cell['col'] == 6:
                cell.update(text='1 Lot')
                cell.pop('uom', None)
            if cell['col'] in (8, 9):
                cell.update(numeric=True, calculated='goods_total' if 'goods_total' in doc['totals'] else 'subtotal')
    model['sections'].append(annexure_section(doc))
    model['annexure_widths'] = ANNEXURE_WIDTHS
    return model


def annexure_words(doc):
    # The words sit beside the annexure's grand total.
    words = amount_words(Decimal(doc['totals']['grand_total']), doc['currency'])
    words = words.removesuffix(' Only').replace(' US Dollars', ' dollars').lower()
    return doc['currency']+' '+words[:1].upper()+words[1:]+' Only'


def annexure_section(doc):
    def cell(col, text='', style='', field=None, value=None, **extra):
        return dict(col=col, span=1, text=str(text), style=style, field=field,
                    label='', value=value, annexure=True, **extra)
    def blanks():
        return [cell(col) for col in range(6)]
    title = cell(0, 'Annexure-1', 'annexure_title')
    title['span'] = 6
    rows = [[title], [cell(col, label, 'head') for col, label in enumerate([
        'Sr No.', 'Item Description', 'Condition', 'Quantity',
        'Unit Price\n('+doc['currency']+')', 'Total Price\n('+doc['currency']+')'])]]
    for index, line in enumerate(doc['totals']['lines']):
        prefix = f'lines.{index}.'
        rows.append([
            cell(0, index+1, 'center'),
            cell(1, line['description'], field=prefix+'description', value=line['description'], multiline=True),
            cell(2, line['item_condition'], field=prefix+'item_condition', value=line['item_condition']),
            cell(3, line['quantity'], 'center', field=prefix+'quantity', value=line['quantity'], type='number', uom=display_uom(line.get('uom') or 'PCs')),
            cell(4, line['unit_price'], 'amount', field=prefix+'unit_price', value=line['unit_price'], type='number', accounting=True),
            cell(5, line['line_total'], 'amount', field=prefix+'line_total', value=line['line_total'], type='number',
                 accounting=True, calculated=prefix+'line_total')])
        if line.get('discount_label'):
            rows[-1][1]['discount_note'] = line['discount_label']
            rows[-1][1]['text'] += '\n' + line['discount_label']
            rows[-1][1]['display_text'] = rows[-1][1]['text']
        if line.get('net_unit_price'):
            rows[-1][4]['text'] = line['net_unit_price']
            rows[-1][4]['display_text'] = line['net_unit_price']
            rows[-1][4]['value'] = line['net_unit_price']
            rows[-1][4]['discounted_rate'] = True
        if Decimal(line.get('discount_amount', '0')):
            rows[-1][5]['readonly'] = True
    totals = doc['totals']
    # Keep a spacer before the subtotal and charges, as on the cover PI.
    rows.append(blanks())
    heights = [22.5,36]+[21.95]*len(doc['totals']['lines'])+[14.1]
    if Decimal(totals.get('summary_discount', '0')):
        discount_row = blanks()
        discount_row[4] = cell(4, 'Discount', 'bold')
        discount_row[5] = cell(5, '-'+totals['summary_discount'], 'amount', accounting=True)
        rows.append(discount_row)
        heights.append(14.1)
    subtotal = blanks()
    subtotal[2] = cell(2, 'Total', 'bold_center')
    subtotal[3] = cell(3, quantity_summary(doc), 'bold_center', field='annexure_quantity', value=quantity_summary(doc), aria='Total quantity', calculated='annexure_quantity', auto_quantity=True)
    subtotal[4] = cell(4, 'Subtotal')
    subtotal[5] = cell(5, totals['subtotal'], 'amount', accounting=True, calculated='subtotal')
    rows.append(subtotal)
    heights.append(14.1)
    if Decimal(totals.get('bank_charges', '0')):
        bank_row = blanks()
        bank_row[4] = cell(4, 'Bank charge')
        bank_row[5] = cell(5, totals['bank_charges'], 'amount', accounting=True, calculated='bank_charges')
        rows.append(bank_row)
        heights.append(14.1)
    if Decimal(totals['shipping']):
        shipping_row = blanks()
        shipping_row[4] = cell(4, 'Shipping charge')
        shipping_row[5] = cell(5, totals['shipping'], 'amount', accounting=True, calculated='shipping')
        rows.append(shipping_row)
        heights.append(14.1)
    if Decimal(totals['tax']):
        tax_row = blanks()
        tax_row[4] = cell(4, f'GST {Decimal(totals["tax_rate"])*100:g}%', 'bold')
        tax_row[5] = cell(5, totals['tax'], 'amount', accounting=True, calculated='tax')
        rows.append(tax_row)
        heights.append(14.1)
    summary_row = len(rows)
    rows.append([cell(0, 'Amount\nin\nWords', 'bold', nowrap=True),
                 cell(1, annexure_words(doc), 'bold', calculated='annexure_amount_in_words'),
                 cell(2),
                 cell(3),
                 cell(4, 'Total ('+doc['currency']+')', 'bold_center'),
                 cell(5, totals['grand_total'], 'bold_amount', accounting=True, calculated='grand_total')])
    heights.append(40.9)
    for total_cell in rows[-1]:
        total_cell.update(total_cell=True)
    rows.append(blanks())
    heights.append(14.1)
    return dict(name='annexure', annexure=True, widths=ANNEXURE_WIDTHS,
                rows=rows, row_heights=heights, summary_row=summary_row)
