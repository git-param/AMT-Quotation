"""Editable commercial text blocks with validated, compatible contact snapshots."""

import re

from backend.client_leads.details import email, phone, text
from backend.orders.locations import without_gst, phone_block, CALLING_CODES

TEXT_FIELDS = ('consignee_text', 'buyer_text', 'notify_text')
LABELS = {'tel': 'phone', 'tel/phone': 'phone', 'telephone': 'phone', 'phone': 'phone',
          'email': 'email', 'e-mail': 'email', 'pic': 'pic',
          'gst': 'gst_number', 'gst no': 'gst_number', 'gst no.': 'gst_number', 'gst number': 'gst_number',
          'gstin': 'gst_number',
          'country': 'country', 'location': 'location', 'address': 'location'}


def parse_block(value, country=''):
    """Keep every line while validating recognized contact labels.

    The first line is the legal name. Remaining unlabeled lines are the freeform
    address/location; commercial additions stay verbatim in the issued text.
    """
    value = text(value, 4000, 'party text')
    country_match = re.search(r'^Country\s*:\s*(.+)$', value, re.I|re.M)
    value = phone_block(value, country_match[1].strip() if country_match else country)
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    party = {key: '' for key in ('name', 'phone', 'email', 'pic', 'gst_number')}
    unfinished_phone = False
    location = []
    explicit_country = ''
    if lines:
        party['name'] = text(re.sub(r'^(?:name|company)\s*:\s*', '', lines[0], flags=re.I),
                             200, 'legal party name')
    for line in lines[1:]:
        match = re.fullmatch(r'([^:]+):\s*(.*)', line)
        key = LABELS.get(match[1].strip().lower()) if match else None
        if key == 'country':
            explicit_country = text(match[2], 200, 'country')
        elif key == 'location':
            if match[2]:
                location.append(match[2])
        elif key:
            # Do not silently discard duplicate labels or conflicting contacts.
            content = match[2].strip()
            if key == 'phone' and '*required' in content:
                unfinished_phone = True
            if party[key] and content != party[key]:
                raise ValueError('Use one ' + key.replace('_', ' ') + ' label per party block.')
            party[key] = content.replace('*required', '').strip() if key == 'phone' else ('' if '*required' in content else content)
        else:
            location.append(line)
    party['email'] = email(party['email'])
    party['phone'] = '' if party['phone'] in CALLING_CODES.values() or (
        unfinished_phone and len(re.sub(r'\D', '', party['phone'])) < 7) else phone(party['phone'])
    for key in ('pic', 'gst_number'):
        party[key] = text(party[key], 200, key)
    country = explicit_country or text(country, 200, 'destination')
    if location and country and location[-1].casefold() == country.casefold():
        location.pop()
    address = {'line1': '\n'.join(location), 'country': country} if location or country else {}
    return value, party, address


def text_delivery(data, old, country, draft):
    """New text UI coexists with historical structured delivery records."""
    blocks = {}
    parties = {}
    addresses = {}
    for key in TEXT_FIELDS:
        fallback = blocks.get('consignee_text', '')
        linked = key != 'consignee_text' and old.get(key) == old.get('consignee_text')
        value = data.get(key, fallback if linked else old.get(key, fallback))
        if key!='consignee_text' and isinstance(value,str):value=without_gst(value)
        blocks[key], parties[key], addresses[key] = parse_block(value, country)
    if not draft:
        if not parties['consignee_text']['name']:
            raise ValueError('Consignee requires a legal name on the first line.')
        shipping = addresses['consignee_text']
        if not shipping.get('country'):
            raise ValueError('Add a consignee country or order destination.')
    return {
        **blocks,
        'consignee': parties['consignee_text'],
        'buyer': parties['buyer_text'], 'notify_party': {
            **parties['notify_text'], 'address': addresses['notify_text']},
        'shipping_address': addresses['consignee_text'],
        'billing_address': addresses['buyer_text'],
        'instructions': text(data.get('instructions', old.get('instructions', '')),
                             2000, 'delivery instructions'),
    }, None, None
