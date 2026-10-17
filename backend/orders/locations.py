"""Country choices and consistent PI country/GST text handling."""
import json
import re

from backend.config import FRONTEND_DIR

COUNTRIES = frozenset(json.loads((FRONTEND_DIR / 'common' / 'countries.json').read_text(encoding='utf-8')))
CALLING_CODES = json.loads((FRONTEND_DIR / 'common' / 'calling-codes.json').read_text(encoding='utf-8'))
GST_LINE = re.compile(r'^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?)\s*:\s*(.*)$', re.I)
CONTACT_LINE = re.compile(r'^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel(?:/Phone)?|Telephone|Phone|PIC|E-?mail)\s*:', re.I)
COPIED_CONTACT = re.compile(r'^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel(?:/Phone)?|Telephone|Phone|PIC|E-?mail)\s*:', re.I)


def phone_block(value, country):
    """Add a calling code to national numbers; retain explicit international edits."""
    prefix = CALLING_CODES.get(str(country).strip().upper())
    if not prefix:
        return value
    def replace(match):
        number = match[1].strip()
        if re.fullmatch(r'\+[0-9]{1,3}', number) or not number:
            number = prefix
        elif number.startswith('00'):
            number = '+' + number[2:]
        elif not number.startswith('+') and re.fullmatch(r'[0-9 ()-]+', number):
            digits = re.sub(r'[^0-9]', '', number)
            if country.strip().upper() in ('UK','UNITED KINGDOM','UAE','UNITED ARAB EMIRATES','INDIA'):
                digits = digits.lstrip('0')
            number = prefix + ' ' + digits
        return 'Tel/Phone: ' + number
    return re.sub(r'^\s*(?:Tel/Phone|Tel|Telephone|Phone)\s*:[ \t]*(.*)$', replace, value, flags=re.I|re.M)


def address_only(value):
    return '\n'.join(line for i,line in enumerate(value.splitlines()) if not i or (
        not COPIED_CONTACT.match(line) and not re.match(r'^\s*Country\s*:',line,re.I)
        and line.strip().upper() not in COUNTRIES)).rstrip()


def party_parts(value):
    """Keep company/address text above country and contact text."""
    lines = value.splitlines()
    boundary = next((i for i, line in enumerate(lines) if i and (
        not line.strip() or re.match(r'^\s*Country\s*:', line, re.I)
        or CONTACT_LINE.match(line) or line.strip().upper() in COUNTRIES)), len(lines))
    return '\n'.join(lines[:boundary]).rstrip(), '\n'.join(lines[boundary:]).lstrip()


def country_block(value, country, previous=()):
    """Replace country lines without rewriting names, addresses or contacts."""
    if not country:
        return value
    known = COUNTRIES | {str(item).strip().upper() for item in previous if item}
    result, inserted = [], False
    for index, line in enumerate(value.splitlines()):
        if index and (re.match(r'^\s*Country\s*:', line, re.I) or line.strip().upper() in known):
            if not inserted:
                result.append(country)
                inserted = True
        else:
            result.append(line)
    if not inserted:
        position = next((i for i, line in enumerate(result) if i and CONTACT_LINE.match(line)), len(result))
        result.insert(position, country)
    return phone_block('\n'.join(result), country)


def gst_number(value):
    return next((match[1].strip() for line in value.splitlines()[1:] if (match := GST_LINE.match(line))), '')


def without_gst(value):
    return '\n'.join(line for index, line in enumerate(value.splitlines()) if not index or not GST_LINE.match(line))


def with_gst(value, number):
    lines = without_gst(value).splitlines()
    if number:
        country=next((i for i,line in enumerate(lines) if i and (
            re.match(r'^\s*Country\s*:',line,re.I) or line.strip().upper() in COUNTRIES)),None)
        contact=next((i for i,line in enumerate(lines) if i and CONTACT_LINE.match(line)),len(lines))
        lines.insert(country+1 if country is not None else contact,'GST No.: '+number)
    return '\n'.join(lines)
