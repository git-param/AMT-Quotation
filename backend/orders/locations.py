"""Country choices and consistent PI country/GST text handling."""
import json
import re

from backend.config import FRONTEND_DIR

COUNTRIES = frozenset(json.loads((FRONTEND_DIR / 'common' / 'countries.json').read_text(encoding='utf-8')))
GST_LINE = re.compile(r'^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?)\s*:\s*(.*)$', re.I)
CONTACT_LINE = re.compile(r'^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel|Telephone|Phone|PIC|E-?mail)\s*:', re.I)
COPIED_CONTACT = re.compile(r'^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel|Telephone|Phone|PIC|E-?mail)\s*:', re.I)


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
    return '\n'.join(result)


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
