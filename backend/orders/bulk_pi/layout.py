"""A one-lot PI summary followed by the complete, editable Annexure-1."""
from copy import deepcopy
from decimal import Decimal

from backend.orders.normal_pi.layout import WIDTHS, layout as normal_layout, terms


def quantity_summary(doc):
    units = {}
    for line in doc['totals']['lines']:
        unit = line.get('uom') or 'PCs'
        units[unit] = units.get(unit, Decimal('0')) + Decimal(line['quantity'])
    return '; '.join(f'{value:g} {unit}' for unit, value in units.items())


def layout(doc):
    summary = deepcopy(doc)
    originals = doc['totals']['lines']
    codes = {line.get('hsn_code', '') for line in originals}
    conditions = {line.get('item_condition', '') for line in originals}
    summary['totals']['lines'] = [{**originals[0],
        'description': doc.get('bulk_description', ''),
        'hsn_code': next(iter(codes)) if len(codes) == 1 else 'As per Annexure-1',
        'item_condition': next(iter(conditions)) if len(conditions) == 1 else 'As per Annexure-1',
        'quantity': '1', 'uom': 'Lot', 'unit_price': doc['totals']['subtotal'],
        'line_total': doc['totals']['subtotal']}]
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
                cell.update(numeric=True, calculated='subtotal')
    # Keep the annexure reference visible even while editing the summary text.
    items['rows'][2][1]['text'] = 'As per Annexure-1'

    annexure = normal_layout(doc)['sections'][2]
    annexure['name'] = 'annexure'
    annexure['annexure'] = True
    for cell in annexure['rows'][0]:
        if cell['col'] == 6:
            cell['text'] = 'Qty / UOM'
        elif cell['col'] == 8:
            cell['text'] = 'Unit Price ('+doc['currency']+')'
        elif cell['col'] == 9:
            cell['text'] = 'Total Price ('+doc['currency']+')'
    title = dict(col=0, span=11, text='Annexure-1 | '+doc['reference'],
                 style='title', field=None, label='', value=None)
    annexure['rows'].insert(0, [title])
    model['sections'].append(annexure)

    def cell(col, span, text, style='', calculated=None):
        return dict(col=col, span=span, text=str(text), style=style,
                    field=None, label='', value=None, calculated=calculated)
    totals = doc['totals']
    rows = [[cell(0, 8, 'Total quantity: '+quantity_summary(doc), 'bold'),
             cell(8, 1, 'Subtotal'), cell(9, 2, totals['subtotal'], 'amount', 'subtotal')],
            [cell(0, 8, ''), cell(8, 1, 'Shipping'), cell(9, 2, totals['shipping'], 'amount', 'shipping')]]
    if Decimal(totals['tax_rate']):
        rows.append([cell(0, 8, ''), cell(8, 1, f'GST {Decimal(totals["tax_rate"])*100:g}%'),
                     cell(9, 2, totals['tax'], 'amount', 'tax')])
    rows.append([cell(0, 8, 'Amount in words: '+totals['amount_in_words'], 'bold', 'amount_in_words'),
                 cell(8, 1, 'Grand Total', 'bold'), cell(9, 2, totals['grand_total'], 'bold_amount', 'grand_total')])
    model['sections'].append({'name': 'annexure_totals', 'annexure': True, 'rows': rows})
    return model
