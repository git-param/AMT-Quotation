"""Established company PI grid, shared by the native exports and editor.

Column widths and emphasis follow the original A:K company Excel layout. This
is a layout definition only; it never opens a workbook or changes PI amounts.
"""
from decimal import Decimal
import re

WIDTHS = [5,15.85546875,19.5703125,11.7109375,14.42578125,
          15.7109375,8.7109375,8,16,8.7109375,8.140625]


def terms(doc):
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
    order,total=doc['order'],doc['totals']
    seller=list(doc['company']['seller'])
    metadata=[c(5,6,'Proforma Invoice No:    '+doc['reference'],'bold'),
        editable(5,6,'Proforma Invoice Date: ',doc['date'],'date',type='date'),
        editable(5,6,'Purchase Order: ',order['po_reference'],'order.po_reference'),
        c(5,6,'Prepared By: '+doc['prepared_by']),
        editable(5,6,'Payment Terms: ',order['payment_terms'],'order.payment_terms','bold',line_bottom=True),
        editable(5,3,'Delivery Terms: ',order['delivery_terms'],'order.delivery_terms')]
    header=[[c(0,11,'PROFORMA INVOICE','title',line_bottom=True)]]
    for index in range(7):
        left=c(0,5,'SUPPLIER/SELLER','bold') if index==0 else c(0,5,seller[index-1] if index<=len(seller) else '')
        if index<5:right=[metadata[index]]
        elif index==5:right=[metadata[5],editable(8,3,'',order['destination'],'order.destination',aria='Destination')]
        else:right=[editable(5,3,'Delivery Time: ',order['delivery_time'],'order.delivery_time'),
                    editable(8,3,'Dispatch By: ',order['dispatch_method'],'order.dispatch_method')]
        header.append([left,*right])
    # Additional configured seller lines are retained, rather than discarded.
    for value in seller[6:]:header.append([c(0,5,value),c(5,6)])
    parties=[
        [c(0,5,'CONSIGNEE','bold'),c(5,6,'BUYER Details','bold')],
        [editable(0,5,'',doc['delivery']['consignee_text'],'delivery.consignee_text',multiline=True,editor_rows=3),
         editable(5,6,'',doc['delivery']['buyer_text'],'delivery.buyer_text',multiline=True)],
        [c(0,5,'',placeholder=True),c(5,6,'Notify Details','bold',line_top=True)],
        [c(0,5,'',placeholder=True),editable(5,6,'',doc['delivery']['notify_text'],'delivery.notify_text',multiline=True)]]
    item_header=[c(start,span,label,'head') for start,span,label in
        [(0,1,'Sno'),(1,3,'Description'),(4,1,'HSN Code'),(5,1,'Condition'),
         (6,2,'QTY'),(8,1,'Rate / PCs'),(9,2,'Total Amount')]]
    items=[item_header]
    for index,line in enumerate(total['lines']):
        prefix=f'lines.{index}.'
        items.append([c(0,1,index+1,'center'),
            editable(1,3,'',line['description'],prefix+'description',multiline=True,sku=line['sku'],sku_field=prefix+'sku'),
            editable(4,1,'',line['hsn_code'],prefix+'hsn_code','center'),
            editable(5,1,'',line['item_condition'],prefix+'item_condition','center'),
            editable(6,2,'',line['quantity'],prefix+'quantity','center',uom=line['uom'],uom_field=prefix+'uom',type='number'),
            editable(8,1,'',line['unit_price'],prefix+'unit_price','amount',type='number'),
            c(9,2,line['line_total'],'amount',numeric=True)])
    # The original reserves four ruled item rows, even for a one-line invoice.
    while len(items)<5:items.append([c(cell['col'],cell['span']) for cell in item_header])
    bank=[c(0,8,'BANK DETAIL','bank_title')]+[c(0,8,value,'bold') for value in doc['company']['bank']]
    bank.append(c(0,8,doc['company'].get('bank_charges',''),'warning'))
    tax_label=f'GST {Decimal(total["tax_rate"])*100:g}%'
    summaries=[(editable(9,2,'',total['shipping'],'shipping_charges','amount',type='number'),'Shipping'),
               (c(9,2,total['subtotal'],'amount',numeric=True),'Sub Total')]
    if Decimal(total['tax_rate']):summaries.append((c(9,2,total['tax'],'amount',numeric=True),tax_label))
    count=max(len(bank),len(summaries)+1)
    bank_rows=[]
    for index in range(count):
        left=bank[index] if index<len(bank) else c(0,8)
        start=count-len(summaries)
        if index>=start:
            amount,label=summaries[index-start];right=[c(8,1,label,'center',line_top=True),{**amount,'line_top':True}]
        else:right=[c(8,1),c(9,2)]
        bank_rows.append([left,*right])
    bank_rows.append([c(0,2,'Amount In Word','bold'),c(2,6,total['amount_in_words'],'bold'),
                      c(8,1,'Grand Total','bold'),c(9,2,total['grand_total'],'bold_amount',numeric=True)])
    clauses=[[c(0,11,'Terms & Conditions:-','bold')]]
    for value in terms(doc).splitlines():
        final=bool(re.match(r'^\s*\d+[.)]\s*THE FINAL TAX (?:INVOICE|INVOCIE)',value,re.I))
        clauses.append([c(0,11,value,'final_term' if final else 'terms')])
    for label,value,path in [('Delivery instructions',doc['delivery']['instructions'],'delivery.instructions'),
                              ('Order notes',order['notes'],'order.notes')]:
        # Keep empty fields editable in the preview without printing empty sections.
        if value:clauses.append([editable(0,11,label+': ',value,path,multiline=True)])
    return {'widths':WIDTHS,'currency':doc['currency'],'sections':[
        {'name':'header','rows':header},{'name':'parties','rows':parties},
        {'name':'items','rows':items},{'name':'bank','rows':bank_rows},
        {'name':'terms','rows':clauses}]}
