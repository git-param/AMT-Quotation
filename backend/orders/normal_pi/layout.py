"""Established company PI grid, shared by the native exports and editor.

Column widths and emphasis follow the original A:K company Excel layout. This
is a layout definition only; it never opens a workbook or changes PI amounts.
"""
from decimal import Decimal
import re
from backend.orders.locations import party_parts, address_only

WIDTHS = [5,15.85546875,19.5703125,11.7109375,14.42578125,
          15.7109375,8.7109375,8,16,8.7109375,8.140625]


def display_uom(unit):
    return 'Set' if unit.lower() == 'set' else unit


def rate_heading(lines):
    units = {display_uom(line.get('uom') or 'PCs') for line in lines}
    if len(units) <= 1:
        return 'Rate / ' + next(iter(units), 'PCs')
    return 'Rate / PCs\nor\nRate / Lot' if 'PCs' in units else 'Rate / Lot'


def terms(doc):
    if 'terms' in doc:
        return doc['terms']
    values = list(doc['company']['terms'][doc['currency']])
    for index,value in enumerate(values):
        match=re.match(r'^(\s*\d+[.)]\s*)?PAYMENT\b',value,re.I)
        if match:values[index]=(match[1] or '')+'PAYMENT '+doc['order']['payment_terms']
    return '\n'.join(values)


def layout(doc):
    def c(col,span,text='',style='',field=None,label='',value=None,**extra):
        return dict(col=col,span=span,text=str(text),style=style,field=field,
                    label=label,value=value,**extra)
    def editable(col,span,label,value,path,style='',**extra):
        return c(col,span,label+str(value),style,path,label,value,**extra)
    def party_cell(col,span,value,path,**extra):
        if path in ('delivery.buyer_text','delivery.notify_text'):
            normalize=lambda text:'\n'.join(line.strip() for line in text.splitlines() if line.strip())
            consignee=normalize(address_only(doc['delivery']['consignee_text']))
            if (consignee and normalize(value)==consignee) or value.strip()=='(Same as consignee)':
                value='(Same as consignee)'
        primary,secondary=party_parts(value)
        return c(col,span,'\n\n'.join(part for part in (primary,secondary) if part),field=path,value=value,
                 multiline=True,party=True,**extra)
    order,total=doc['order'],doc['totals']
    seller=list(doc['company']['seller'])
    date_parts=re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})',doc['date'])
    date_display='/'.join((date_parts[3],date_parts[2],date_parts[1])) if date_parts else doc['date']
    metadata=[
        [c(5,2,'Proforma Invoice No:'),editable(7,4,'',doc['reference'],'order.pi_reference','bold',aria='Proforma Invoice No.')],
        [c(5,2,'Proforma Invoice Date:'),editable(7,4,'',doc['date'],'date',type='date',aria='Proforma Invoice Date',display_text=date_display)],
        [c(5,2,'Purchase Order:'),editable(7,4,'',order['po_reference'],'order.po_reference',aria='Purchase Order')],
        [c(5,2,'Prepared By: '+doc['prepared_by']),editable(7,4,'Tel: ',doc.get('prepared_phone',''),'prepared_phone',type='tel',aria='Tel')],
        [editable(5,6,'Payment Terms: ',order['payment_terms'],'order.payment_terms','bold',line_top=True)],
        [editable(5,2,'Delivery Terms: ',order['delivery_terms'],'order.delivery_terms')]]
    header=[[c(0,11,'PROFORMA INVOICE','title',line_bottom=True)]]
    for index in range(7):
        left=c(0,5,'SUPPLIER/SELLER','bold') if index==0 else c(0,5,seller[index-1] if index<=len(seller) else '')
        if index<5:right=metadata[index]
        elif index==5:right=[*metadata[5],editable(7,4,'',order['destination'],'order.destination',aria='Destination')]
        else:right=[editable(5,3,'Delivery Time: ',order['delivery_time'],'order.delivery_time'),
                    editable(8,3,'Dispatch By: ',order['dispatch_method'],'order.dispatch_method')]
        for offset,cell in enumerate(right):
            cell['open_left'] = offset>0
            cell['open_right'] = offset<len(right)-1
            if index<4:cell['header_metadata'] = True
        header.append([left,*right])
    # Additional configured seller lines are retained, rather than discarded.
    for value in seller[6:]:header.append([c(0,5,value),c(5,6)])
    parties=[
        [c(0,5,'CONSIGNEE','bold'),c(5,6,'BUYER Details','bold')],
        [party_cell(0,5,doc['delivery']['consignee_text'],'delivery.consignee_text',editor_rows=3),
         party_cell(5,6,doc['delivery']['buyer_text'],'delivery.buyer_text')],
        [c(0,5,'',placeholder=True),c(5,6,'Notify Details','bold',line_top=True)],
        [c(0,5,'',placeholder=True),party_cell(5,6,doc['delivery']['notify_text'],'delivery.notify_text')]]
    primary,secondary=party_parts(doc['delivery']['consignee_text'])
    parties[1][0]['text']=primary
    parties[1][0]['bottom_contacts']=True
    parties[-1][0].update(text=secondary,bottom_aligned=True)
    item_header=[c(start,span,label,'head') for start,span,label in
        [(0,1,'Sno'),(1,3,'Description'),(4,1,'HSN Code'),(5,1,'Condition'),
         (6,2,'QTY'),(8,1,rate_heading(total['lines'])),(9,2,'Total Amount')]]
    next(cell for cell in item_header if cell['col'] == 8)['rate_heading'] = True
    items=[item_header]
    for index,line in enumerate(total['lines']):
        prefix=f'lines.{index}.'
        items.append([c(0,1,index+1,'center'),
            editable(1,3,'',line['description'],prefix+'description',multiline=True),
            editable(4,1,'',line['hsn_code'],prefix+'hsn_code','center',readonly=bool(doc.get('shared_hsn_code'))),
            editable(5,1,'',line['item_condition'],prefix+'item_condition','center'),
            editable(6,2,'',line['quantity'],prefix+'quantity','center',uom=display_uom(line['uom']),uom_field=prefix+'uom',type='number'),
            editable(8,1,'',line['unit_price'],prefix+'unit_price','amount',type='number'),
            editable(9,2,'',line['line_total'],prefix+'line_total','amount',numeric=True,type='number',calculated=f'lines.{index}.line_total')])
        if line.get('discount_label'):
            items[-1][1]['discount_note'] = line['discount_label']
            items[-1][1]['text'] += '\n' + line['discount_label']
            items[-1][1]['display_text'] = items[-1][1]['text']
        if line.get('net_unit_price'):
            items[-1][-2]['text'] = line['net_unit_price']
            items[-1][-2]['display_text'] = line['net_unit_price']
        if Decimal(line.get('discount_amount', '0')):
            items[-1][-1]['readonly'] = True
    # The original reserves four ruled item rows, even for a one-line invoice.
    while len(items)<5:items.append([c(cell['col'],cell['span']) for cell in item_header])
    for row in items[1:]:
        next(cell for cell in row if cell['col'] == 8)['open_right'] = True
        next(cell for cell in row if cell['col'] == 9)['open_left'] = True
    bank=[c(0,8,'BANK DETAIL','bank_title')]+[c(0,8,value,'bold') for value in doc['company']['bank']]
    bank.append(c(0,8,doc['company'].get('bank_charges',''),'warning'))
    tax_label=f'GST {(Decimal(total["tax_rate"])*100).normalize():f}%'
    free=Decimal(total['shipping'])==0
    summaries=[(editable(9,2,'',total['shipping'],'shipping_charges','amount',type='number',free=free,display_text='Free' if free else total['shipping']),'Shipping'),
               (c(9,2,total['subtotal'],'amount',numeric=True,calculated='subtotal'),'Sub Total')]
    if Decimal(total.get('summary_discount', '0')):
        discount=(c(9,2,'-'+total['summary_discount'],'amount',numeric=True), 'Discount')
        if doc['currency']=='INR':
            summaries=[(c(9,2,total['goods_total'],'amount',numeric=True,calculated='goods_total'),'Goods Subtotal'),
                       discount,
                       (c(9,2,total['subtotal'],'amount',numeric=True,calculated='subtotal'),'Net Subtotal'),
                       summaries[0]]
        else:
            summaries.insert(0, discount)
    if Decimal(total['tax_rate']):summaries.append((c(9,2,total['tax'],'amount',numeric=True,calculated='tax'),tax_label))
    count=max(len(bank),len(summaries)+1)
    bank_rows=[]
    for index in range(count):
        left=bank[index] if index<len(bank) else c(0,8)
        start=count-len(summaries)
        if index>=start:
            amount,label=summaries[index-start];right=[c(8,1,label,'center',open_right=True),{**amount,'open_left':True}]
        else:right=[c(8,1,open_right=True),c(9,2,open_left=True)]
        bank_rows.append([left,*right])
    bank_rows.append([c(0,2,'Amount In Word','bold'),c(2,6,total['amount_in_words'],'bold',calculated='amount_in_words'),
                      c(8,1,'Grand Total','bold',open_right=True),c(9,2,total['grand_total'],'bold_amount',numeric=True,calculated='grand_total',open_left=True)])
    clauses=[[c(0,11,'Terms & Conditions:-','bold')]]
    term_text = terms(doc)
    for index,value in enumerate(term_text.splitlines() or ['']):
        final=bool(re.match(r'^\s*\d+[.)]\s*THE FINAL TAX (?:INVOICE|INVOCIE)',value,re.I))
        clauses.append([c(0,11,value,'final_term' if final else 'terms',
            field='terms' if index==0 else None, value=term_text if index==0 else None,
            multiline=True, aria='Terms and conditions', preview_hidden=index>0)])
    return {'widths':WIDTHS,'currency':doc['currency'],'sections':[
        {'name':'header','rows':header},{'name':'parties','rows':parties},
        {'name':'items','rows':items},{'name':'bank','rows':bank_rows},
        {'name':'terms','rows':clauses}]}
