"""Validated editable PI snapshots, independent of a reference workbook."""
import base64
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from backend.config import ROOT_DIR
from backend.client_leads.details import text,phone
from backend.enquiries.lines import number, serialize
from backend.orders.company import get_profile
from backend.orders.parties import text_delivery, parse_block, LABELS
from backend.orders.locations import country_block, gst_number, with_gst, without_gst, address_only, COPIED_CONTACT
from backend.orders.service import header, order_line

ASSETS = ('header.png', 'address.png', 'payment_options.png', 'signature.png')
ORDER_FIELDS = {'po_reference', 'pi_reference', 'payment_terms', 'delivery_terms', 'destination',
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
        *[label+party[key] for key,label in (('phone','Tel/Phone: '),('pic','PIC: '),
          ('email','Email: '),('gst_number','GST: ')) if party.get(key)]]))


def sync_locations(doc):
    """The selected order country owns both highlighted PI locations."""
    source_delivery = doc['source_state'].get('delivery') or {}
    country = doc['order']['destination'].strip().upper()
    if not country:
        explicit = re.search(r'^\s*Country\s*:\s*(.+)$',doc['delivery']['consignee_text'],re.I|re.M)
        country = (explicit[1].strip() if explicit else
            (source_delivery.get('shipping_address') or {}).get('country','')).upper()
    if not country and doc['currency'] == 'INR':
        country = 'INDIA'
    previous = [(source_delivery.get('shipping_address') or {}).get('country'),
                doc['source_state']['order'].get('destination')]
    doc['delivery']['consignee_text'] = re.sub(r'^(\s*)(?:Tel|Telephone|Phone)\s*:', r'\1Tel/Phone:',
        country_block(doc['delivery']['consignee_text'], country, previous), flags=re.I|re.M)
    number_value=gst_number(doc['delivery']['consignee_text'])
    doc['delivery']['consignee_text']=with_gst(doc['delivery']['consignee_text'],number_value)
    doc['order']['destination'] = country
    doc['consignee_gst_number'] = gst_number(doc['delivery']['consignee_text'])
    for key in ('buyer_text','notify_text'):doc['delivery'][key]=without_gst(doc['delivery'][key])
    return doc


def prepare(state, user, currency, rate, bulk_description=None):
    from backend.orders.invoices import calculate
    from backend.database import get_db
    connection = get_db()
    try:
        company = get_profile(connection)
    finally:
        connection.close()
    if currency not in ('USD','INR'):
        raise ValueError('Choose USD or INR PI currency.')
    reference = text(state['order']['pi_reference'],100,'Proforma Invoice No.')
    if not reference:
        raise ValueError('Enter the Proforma Invoice No. in order details before opening a PI preview.')
    tax = Decimal(company['tax_rates'][currency])
    if not tax.is_finite() or not 0 <= tax <= 1:
        raise ValueError('Company PI tax configuration is invalid.')
    if rate is None and any(code!=currency for code in [state['order']['currency'],*[line['currency'] for line in state['lines']]]):
        from backend.quotation_tool.shopify import get_inr_rate
        quoted_rate=get_inr_rate()
        if quoted_rate is None:raise ValueError('The quotation exchange rate is unavailable. Try again shortly.')
        try:rate=format(Decimal(str(quoted_rate)).quantize(Decimal('0.000001')),'.6f')
        except Exception as error:raise ValueError('The quotation exchange rate is unavailable. Try again shortly.') from error
    totals = calculate(state,currency,rate,tax)
    order = deepcopy(state['order'])
    order['payment_terms'] = order['payment_terms'] or company['payment_terms'][currency]
    destination = state['delivery'] or {}
    consignee = destination.get('consignee_text',party_block(destination.get('consignee'),destination.get('shipping_address')))
    buyer = destination.get('buyer_text') or party_block(destination.get('buyer'),destination.get('billing_address')) or consignee
    notify = destination.get('notify_text') or party_block(destination.get('notify_party'),destination.get('notify_party',{}).get('address')) or consignee
    if buyer == consignee or (address_only(buyer)==address_only(consignee) and not any(COPIED_CONTACT.match(line) for line in buyer.splitlines()[1:])):
        buyer = address_only(buyer)
    if notify == consignee or (address_only(notify)==address_only(consignee) and not any(COPIED_CONTACT.match(line) for line in notify.splitlines()[1:])):
        notify = address_only(notify)
    assets = {}
    for name in ASSETS:
        path = ROOT_DIR/'assets'/'PI-img'/name
        try:
            assets[name] = base64.b64encode(path.read_bytes()).decode('ascii')
        except OSError as error:
            raise ValueError('Company PI image is missing: '+name) from error
    bulk = len(totals['lines']) > 4
    description = text(bulk_description or '', 2000, 'first-page description')
    if bulk and not description:
        raise ValueError('Enter the first-page description for this bulk PI. The products will be listed in Annexure-1.')
    return sync_locations({'schema_version':2,'reference':reference,
        'pi_format':'bulk' if bulk else 'normal', 'bulk_description':description if bulk else '',
        'date':datetime.now(timezone(timedelta(hours=5,minutes=30))).date().isoformat(),
        'prepared_by':user['username'],'prepared_phone':company_phone(company),'currency':currency,'order':order,
        'delivery':{'consignee_text':consignee,'buyer_text':buyer,'notify_text':notify,
                    'instructions':destination.get('instructions','')},
        'totals':totals,'source_conversion':deepcopy(totals),'shared_hsn_code':state.get('shared_hsn_code',''),
        'source_state':state,'company':company,'assets':assets,
        'source_updated_at':state['order']['updated_at']})


def edit(document, edits):
    from backend.orders.invoices import calculate
    if not isinstance(edits,dict) or set(edits)-{'date','prepared_phone','order','delivery','lines','shipping_charges','terms','consignee_gst_number','bulk_description'}:
        raise ValueError('Invalid PI preview fields. Company details and invoice identity cannot be edited.')
    doc = deepcopy(document)
    if 'bulk_description' in edits:
        if doc.get('pi_format') != 'bulk':
            raise ValueError('A first-page summary description is only available for bulk PIs.')
        doc['bulk_description'] = text(edits['bulk_description'],2000,'first-page description')
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
        if not doc['order']['pi_reference']:
            raise ValueError('Enter the Proforma Invoice No.')
        doc['reference'] = doc['order']['pi_reference']
    if 'delivery' in edits:
        if not isinstance(edits['delivery'],dict) or set(edits['delivery'])-{
                'consignee_text','buyer_text','notify_text','instructions'}:
            raise ValueError('Invalid PI party fields.')
        snapshot,_,_ = text_delivery(edits['delivery'],doc['delivery'],doc['order']['destination'],True)
        doc['delivery'] = {key:snapshot[key] for key in ('consignee_text','buyer_text','notify_text','instructions')}
    if 'consignee_gst_number' in edits:
        number_value = text(edits['consignee_gst_number'],200,'consignee GST number')
        doc['delivery']['consignee_text'] = with_gst(doc['delivery']['consignee_text'], number_value)
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
    discount = state['order'].get('discount')
    if discount and discount['type'] == 'amount':
        discount = deepcopy(discount)
        source = doc['source_state']['order']['currency']
        if source != doc['currency']:
            from backend.orders.invoices import money
            rate = Decimal(doc['source_conversion']['usd_inr_rate'])
            value = Decimal(discount['value'])
            discount['value'] = format(money(value * rate if source == 'USD' else value / rate), '.2f')
        state['order']['discount'] = discount
    doc['totals'] = calculate(state,doc['currency'],None,Decimal(doc['totals']['tax_rate']))
    return sync_locations(doc)


def recalculate(document, edits):
    """Calculate numeric edits independently of incomplete party/commercial text."""
    if not isinstance(edits,dict) or set(edits)-{'lines','shipping_charges'}:
        raise ValueError('Provide item prices, quantities and shipping charges.')
    numeric={}
    if 'lines' in edits:
        if not isinstance(edits['lines'],list):raise ValueError('Provide item lines.')
        originals={line['id']:line for line in document['totals']['lines']}
        values=[]
        for line in edits['lines']:
            if not isinstance(line,dict) or type(line.get('id')) is not int or line['id'] not in originals:
                raise ValueError('Invalid preview item.')
            original=originals[line['id']]
            values.append({key:line.get(key,original[key]) if key in ('quantity','unit_price') else original[key] for key in LINE_FIELDS})
        numeric['lines']=values
    if 'shipping_charges' in edits:numeric['shipping_charges']=edits['shipping_charges']
    return edit(document,numeric)


def print_document(document, edits):
    """Render in-progress text without saving or applying issuance validation."""
    doc = deepcopy(document)
    # Calculate valid numeric changes independently of unfinished contact text.
    numeric = {}
    if isinstance(edits.get('lines'),list):
        originals = {line['id']:line for line in doc['totals']['lines']}
        numeric['lines'] = []
        for line in edits['lines']:
            if not isinstance(line,dict) or type(line.get('id')) is not int or line['id'] not in originals:
                continue
            original = originals[line['id']]
            numeric['lines'].append({key:line.get(key,original[key]) if key in ('quantity','unit_price') else original[key]
                for key in LINE_FIELDS})
    if 'shipping_charges' in edits:numeric['shipping_charges']=edits['shipping_charges']
    try:
        doc = edit(doc,numeric)
    except ValueError:
        # Unfinished numeric inputs can still be printed using the last totals.
        pass
    for key in ('date','prepared_phone','terms','bulk_description'):
        if isinstance(edits.get(key),str):doc[key]=edits[key][:20000]
    if isinstance(edits.get('order'),dict):
        for key in ORDER_FIELDS:
            if isinstance(edits['order'].get(key),str):doc['order'][key]=edits['order'][key][:5000]
        doc['reference']=doc['order']['pi_reference']
    if isinstance(edits.get('delivery'),dict):
        for key in ('consignee_text','buyer_text','notify_text','instructions'):
            if isinstance(edits['delivery'].get(key),str):doc['delivery'][key]=edits['delivery'][key][:20000]
    if isinstance(edits.get('consignee_gst_number'),str):
        doc['delivery']['consignee_text']=with_gst(doc['delivery']['consignee_text'],edits['consignee_gst_number'][:200])
    if isinstance(edits.get('lines'),list):
        changes={line.get('id'):line for line in edits['lines'] if isinstance(line,dict) and type(line.get('id')) is int}
        for line in doc['totals']['lines']:
            for key in ('description','hsn_code','item_condition','uom'):
                value=changes.get(line['id'],{}).get(key)
                if isinstance(value,str):line[key]=value[:20000]
    return sync_locations(doc)


class PiDetailsRequired(ValueError):
    def __init__(self, fields):
        self.missing_fields = fields
        super().__init__('Complete these details before generating or downloading the PI PDF:\n' + '\n'.join('• ' + field for field in fields))


def missing_details(doc):
    missing = []
    reference = str(doc.get('reference', '')).strip()
    if not reference or reference.endswith('/'):
        missing.append('Proforma Invoice No. (complete prefix and number)')
    if not str(doc['order'].get('po_reference', '')).strip():
        missing.append('Purchase Order No.')
    country = str(doc['order'].get('destination', '')).strip()
    values = {}
    for line in doc['delivery'].get('consignee_text', '').splitlines()[1:]:
        match = re.fullmatch(r'\s*([^:]+):\s*(.*)', line)
        if match:
            key = LABELS.get(match[1].strip().lower())
            if key: values[key] = match[2].strip()
    if not (country or values.get('country')):
        missing.append('Consignee country')
    for key, label in [('gst_number', 'GST No.'), ('phone', 'Tel/Phone'), ('pic', 'PIC'), ('email', 'Email')]:
        if not values.get(key): missing.append('Consignee ' + label)
    return missing


def validate_pdf_details(doc):
    missing = missing_details(doc)
    if missing:
        raise PiDetailsRequired(missing)
    try:
        parse_block(doc['delivery']['consignee_text'], doc['order'].get('destination', ''))
    except ValueError as error:
        raise ValueError('Consignee details: ' + str(error)) from error


def validate_ready(doc):
    validate_pdf_details(doc)
    if doc.get('pi_format') == 'bulk':
        if not text(doc.get('bulk_description',''),2000,'first-page description'):
            raise ValueError('Enter the first-page description for this bulk PI.')
    if not str(doc.get('reference','')).strip():
        raise ValueError('Enter the Proforma Invoice No.')
    if not str(doc['order'].get('po_reference','')).strip():
        raise ValueError('Enter the Purchase Order No.')
