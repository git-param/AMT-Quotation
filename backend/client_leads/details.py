"""CRM field validation and privacy-preserving duplicate detection."""

import json
import re

SCALARS = {'name': 150, 'company': 150, 'email': 254, 'phone': 40,
           'notes': 2000, 'business_details': 2000, 'status': 20}
JSON_FIELDS = ('contact_persons', 'emails', 'phones',
               'billing_address', 'shipping_address')


def text(value, limit, label):
    """Reject malformed/oversized strings and trim surrounding whitespace."""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError('Invalid ' + label)
    return value.strip()


def email(value):
    """Validate supplied emails; empty optional primary values are allowed."""
    value = text(value, 254, 'email').lower()
    pattern = (
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+"
    )
    if value and not re.fullmatch(pattern, value):
        raise ValueError('Enter a valid email address.')
    return value


def phone(value):
    """Normalize formatted phone numbers to optional + and 7?15 digits."""
    value = text(value, 40, 'phone')
    value = re.sub(r'[ ()\-.]', '', value)
    if value and not re.fullmatch(r'\+?[0-9]{7,15}', value):
        raise ValueError('Phone numbers must contain 7 to 15 digits.')
    return value


def collection(value, label):
    """Bound repeated CRM fields to keep input and storage predictable."""
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError('Provide up to 20 ' + label)
    return value


def address(value):
    """Validate structured addresses while permitting an empty address."""
    fields = {'line1', 'line2', 'city', 'state', 'postal_code', 'country'}
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError('Invalid address fields.')
    result = {key: text(item, 200, 'address') for key, item in value.items()}
    if result and (not result.get('line1') or not result.get('country')):
        raise ValueError('Addresses require line1 and country.')
    return result


def validated_details(data, existing=None):
    """Preserve omitted fields and forbid ownership/lifecycle overrides."""
    if (not isinstance(data, dict)
            or set(data) - set(SCALARS) - set(JSON_FIELDS)):
        raise ValueError('Invalid fields; ownership is server assigned.')
    existing = existing or {}
    result = {}
    for field, limit in SCALARS.items():
        default = 'lead' if field == 'status' else ''
        result[field] = text(data.get(field, existing.get(field, default)),
                             limit, field)
    if not result['name']:
        raise ValueError('A client name is required.')
    if result['status'] not in ('lead', 'prospect', 'customer'):
        raise ValueError('Choose lead, prospect, or customer status.')
    result['email'] = email(result['email'])
    result['phone'] = phone(result['phone'])
    for field, validator in (('emails', email), ('phones', phone)):
        values = collection(data.get(field, existing.get(field, [])), field)
        normalized = [validator(item) for item in values]
        if any(not item for item in normalized):
            raise ValueError('Remove blank entries from ' + field)
        result[field + '_json'] = json.dumps(list(dict.fromkeys(normalized)))
    contacts = []
    for item in collection(data.get('contact_persons', existing.get(
            'contact_persons', [])), 'contact persons'):
        if (not isinstance(item, dict)
                or set(item) - {'name', 'email', 'phone'}):
            raise ValueError('Invalid contact person fields.')
        name = text(item.get('name', ''), 150, 'contact name')
        if not name:
            raise ValueError('Each contact person requires a name.')
        contacts.append({'name': name, 'email': email(item.get('email', '')),
                         'phone': phone(item.get('phone', ''))})
    result['contact_persons_json'] = json.dumps(contacts)
    for field in ('billing_address', 'shipping_address'):
        result[field + '_json'] = json.dumps(address(data.get(
            field, existing.get(field, {}))))
    return result


def decode(row):
    """Expose structured fields without rewriting legacy contact values."""
    result = dict(row)
    for field in JSON_FIELDS:
        result[field] = json.loads(result.pop(field + '_json'))
    return result


def identities(client):
    """Extract comparable identity keys, including all contact channels."""
    key = tuple(' '.join(client[field].casefold().split())
                for field in ('name', 'company'))
    emails = {client['email'].strip().lower(), *client['emails']}
    phones = {re.sub(r'[^0-9]', '', client['phone'])}
    phones.update(re.sub(r'[^0-9]', '', item) for item in client['phones'])
    for contact in client['contact_persons']:
        emails.add(contact.get('email', '').strip().lower())
        phones.add(re.sub(r'[^0-9]', '', contact.get('phone', '')))
    return key, emails - {''}, phones - {''}


def duplicate_exists(connection, values, owner, exclude_id=0):
    """Detect duplicates within ownership without returning private records.

    Call under BEGIN IMMEDIATE to serialize competing creates/edits. Existing
    duplicate legacy rows remain intact; inactive rows also reserve identity.
    """
    candidate = decode(values)
    key, emails, phones = identities(candidate)
    rows = connection.execute(
        'SELECT * FROM client_leads WHERE created_by = ? AND id != ?',
        (owner, exclude_id),
    )
    for row in rows:
        other_key, other_emails, other_phones = identities(decode(row))
        if (key == other_key
                or emails & other_emails or phones & other_phones):
            return True
    return False
