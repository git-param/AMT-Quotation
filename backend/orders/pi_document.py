"""Validated editable PI snapshots, independent of a reference workbook."""
import base64
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from backend.config import ROOT_DIR
from backend.client_leads.details import text,phone
from backend.enquiries.lines import number, serialize
from backend.orders.company import get_profile
from backend.orders.parties import text_delivery
from backend.orders.service import header, order_line

ASSETS = ('header.png', 'address.png', 'payment_options.png', 'signature.png')
ORDER_FIELDS = {'po_reference', 'payment_terms', 'delivery_terms', 'destination',
                'delivery_time', 'dispatch_method', 'notes'}
LINE_FIELDS = {'id','sku','description','hsn_code','item_condition','uom','quantity','unit_price'}


def company_phone(company):
    if company.get('prepared_phone'):
        return phone(company['prepared_phone'])
    for line in company.get('seller',[]):
        match=re.match(r'^\s*(?:Tel|Telephone|Phone)\s*:?\s*(.+)',line,re.I)
        if match:
            try:return phone(match[1].split('/')[0].strip())
            except ValueError:continue
    return ''


def party_block(party, address):
    party = party or {}
    address = address or {}
    return '\n'.join(filter(None, [party.get('name'), *[address.get(key) for key in
        ('line1','line2','city','state','postal_code')],
        'Country: '+address['country'] if address.get('country') else '',
        *[label+party[key] for key,label in (('phone','Tel: '),('pic','PIC: '),
          ('email','Email: '),('gst_number','GST: ')) if party.get(key)]]))


def inr_locations(doc):
    """Use the domestic country in both PI locations for INR invoices."""
    if doc['currency'] != 'INR':
        return doc
    source_delivery = doc['source_state'].get('delivery') or {}
    countries = {'india', str(doc['order'].get('destination', '')).strip().casefold(),
                 str((source_delivery.get('shipping_address') or {}).get('country', '')).strip().casefold(),
                 str(doc['source_state']['order'].get('destination', '')).strip().casefold()}
    lines = doc['delivery']['consignee_text'].splitlines()
    result = []
    inserted = False
    for index, line in enumerate(lines):
        if index > 0 and (re.match(r'^\s*Country\s*:', line, re.I)
                          or (line.strip() and line.strip().casefold() in countries)):
            if not inserted:
                result.append('INDIA')
                inserted = True
        else:
            result.append(line)
    if not inserted:
        contact = next((index for index, line in enumerate(result) if index > 0 and
            re.match(r'^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel|Telephone|Phone|PIC|E-?mail)\s*:', line, re.I)), len(result))
        result.insert(contact, 'INDIA')
    doc['delivery']['consignee_text'] = '\n'.join(result)
    doc['order']['destination'] = 'INDIA'
    return doc


def prepare(state, user, currency, rate):
    from backend.orders.invoices import calculate
    from backend.database import get_db
    connection = get_db()
    try:
        company = get_profile(connection)
    finally:
        connection.close()
    if currency not in ('USD','INR'):
        raise ValueError('Choose USD or INR PI currency.')
    if not state['lines']:
        raise ValueError('Add order items before opening a PI preview.')
    if state['legacy_lines_requiring_review']:
        raise ValueError('Complete the historical quantity review before previewing a PI.')
    tax = Decimal(company['tax_rates'][currency])
    if not tax.is_finite() or not 0 <= tax <= 1:
        raise ValueError('Company PI tax configuration is invalid.')
    totals = calculate(state,currency,rate,tax)
    order = deepcopy(state['order'])
    order['payment_terms'] = order['payment_terms'] or company['payment_terms'][currency]
    destination = state['delivery'] or {}
    consignee = destination.get('consignee_text',party_block(destination.get('consignee'),destination.get('shipping_address')))
    buyer = destination.get('buyer_text') or party_block(destination.get('buyer'),destination.get('billing_address')) or consignee
    notify = destination.get('notify_text') or party_block(destination.get('notify_party'),destination.get('notify_party',{}).get('address')) or consignee
    assets = {}
    for name in ASSETS:
        path = ROOT_DIR/'assets'/'PI-img'/name
        try:
            assets[name] = base64.b64encode(path.read_bytes()).decode('ascii')
        except OSError as error:
            raise ValueError('Company PI image is missing: '+name) from error
    return inr_locations({'schema_version':2,'reference':'AMT/PI/'+uuid4().hex[:16].upper(),
        'date':datetime.now(timezone(timedelta(hours=5,minutes=30))).date().isoformat(),
        'prepared_by':user['username'],'prepared_phone':company_phone(company),'currency':currency,'order':order,
        'delivery':{'consignee_text':consignee,'buyer_text':buyer,'notify_text':notify,
                    'instructions':destination.get('instructions','')},
        'totals':totals,'source_conversion':deepcopy(totals),'shared_hsn_code':state.get('shared_hsn_code',''),
        'source_state':state,'company':company,'assets':assets,
        'source_updated_at':state['order']['updated_at']})


def edit(document, edits):
    from backend.orders.invoices import calculate
    if not isinstance(edits,dict) or set(edits)-{'date','prepared_phone','order','delivery','lines','shipping_charges','terms'}:
        raise ValueError('Invalid PI preview fields. Company details and invoice identity cannot be edited.')
    doc = deepcopy(document)
    if 'terms' in edits:
        doc['terms'] = text(edits['terms'],20000,'terms and conditions')
    if 'prepared_phone' in edits:
        doc['prepared_phone']=phone(edits['prepared_phone'])
    if 'date' in edits:
        raw = text(edits['date'],10,'PI date')
        try:
            if date.fromisoformat(raw).isoformat() != raw:
                raise ValueError()
        except ValueError as error:
            raise ValueError('PI date must use YYYY-MM-DD.') from error
        doc['date'] = raw
    if 'order' in edits:
        if not isinstance(edits['order'],dict) or set(edits['order'])-ORDER_FIELDS:
            raise ValueError('Invalid PI commercial fields.')
        validated = header(edits['order'],doc['order'])
        for key in ORDER_FIELDS:
            doc['order'][key] = validated[key]
    if 'delivery' in edits:
        if not isinstance(edits['delivery'],dict) or set(edits['delivery'])-{
                'consignee_text','buyer_text','notify_text','instructions'}:
            raise ValueError('Invalid PI party fields.')
        snapshot,_,_ = text_delivery(edits['delivery'],doc['delivery'],doc['order']['destination'],True)
        doc['delivery'] = {key:snapshot[key] for key in ('consignee_text','buyer_text','notify_text','instructions')}
    lines = doc['totals']['lines']
    if 'lines' in edits:
        values = edits['lines']
        if not isinstance(values,list) or len(values)!=len(lines):
            raise ValueError('Keep the original order lines in the PI preview.')
        originals = {line['id']:line for line in lines}
        result,seen = [],set()
        for line in values:
            if (not isinstance(line,dict) or set(line)!=LINE_FIELDS or type(line['id']) is not int
                    or line['id'] not in originals or line['id'] in seen):
                raise ValueError('Invalid or duplicate preview item.')
            seen.add(line['id'])
            validated = order_line({**{k:v for k,v in line.items() if k!='id'},'currency':doc['currency']})
            if doc.get('shared_hsn_code'):
                validated['hsn_code'] = doc['shared_hsn_code']
            result.append({**originals[line['id']],**serialize(validated),'id':line['id']})
        lines = result
    shipping = edits.get('shipping_charges',doc['totals']['shipping'])
    shipping_minor = number(shipping,2,Decimal('999999999.99'))
    # Editable prices are already in the explicitly selected PI currency. Never
    # convert an edited displayed rate a second time.
    state = {'order':{**doc['order'],'currency':doc['currency'],
                      'shipping_charges':format(Decimal(shipping_minor)/100,'.2f')},
             'lines':[{**line,'currency':doc['currency']} for line in lines]}
    doc['totals'] = calculate(state,doc['currency'],None,Decimal(doc['totals']['tax_rate']))
    return inr_locations(doc)


def validate_ready(doc):
    if any(not line.get('hsn_code') or not line.get('item_condition') for line in doc['totals']['lines']):
        raise ValueError('Complete HSN code and item condition on every preview item.')
    for key in ('payment_terms','delivery_terms','destination','delivery_time','dispatch_method'):
        if not doc['order'][key]:
            raise ValueError('Complete '+key.replace('_',' ')+' in the PI preview.')
    text_delivery(doc['delivery'],{},doc['order']['destination'],False)
