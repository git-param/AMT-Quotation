"""Resolve SKUs missing from Shopify against the Atlas and Al Reza catalogs."""
import html
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from backend.quotation_tool.search_service import _BLOG_FEEDS, _blog_thumb

_cache = {}
_lock = threading.Lock()


def _normal(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def _text(markup):
    markup = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', markup or '')
    return html.unescape(re.sub(r'<[^>]+>', '\n', markup)).replace('\xa0', ' ')


def _field(text, label):
    match = re.search(r'^\s*' + label + r'\s*[:\-]\s*(.+)$', text, re.I | re.M)
    return match.group(1).strip(' .;') if match else ''


def _images(markup):
    images = []
    for url in re.findall(r'src=["\']([^"\']+?\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
                          markup or '', re.I):
        full = re.sub(r'/s\d+(?:-c)?/|/w\d+-h\d+(?:-[a-z-]+)?/', '/s0/', url)
        if full not in images:
            images.append(full)
        if len(images) == 24:
            break
    return images


def lookup_ref(ref):
    key = _normal(ref)
    if not key:
        return None
    with _lock:
        if key in _cache:
            return _cache[key]
    found = None
    for source, feed in _BLOG_FEEDS.items():
        try:
            response = requests.get(feed, params={'q': ref, 'alt': 'json', 'max-results': 5},
                                    headers={'User-Agent': 'Mozilla/5.0'}, timeout=12)
            response.raise_for_status()
            entries = response.json().get('feed', {}).get('entry', [])
        except (requests.RequestException, ValueError, TypeError):
            continue
        for entry in entries:
            markup = (entry.get('content') or entry.get('summary') or {}).get('$t', '')
            body = _text(markup)
            labels = ' '.join(c.get('term', '') for c in entry.get('category', []))
            if key not in _normal(body + ' ' + labels):
                continue
            raw_condition = _field(body, 'CONDITION')
            condition = raw_condition
            quantity = _field(body, r'(?:QTY|QUANTITY)(?:\s+AVAILABLE)?')
            match = re.search(r'\b(\d+)\s*(?:PCS?|PIECES?|NOS?|UNITS?)\b', raw_condition, re.I)
            if match:
                quantity = match.group(1)
                condition = raw_condition[:match.start()].strip(' -/.')
            quantity_match = re.match(r'\d+', quantity)
            links = entry.get('link') or []
            images = _images(markup)
            found = {
                'found': True, 'sku': ref, 'title': (entry.get('title') or {}).get('$t', ''),
                'condition': condition, 'qty': int(quantity_match.group()) if quantity_match else '',
                'price': None, 'sale_price': None,
                'url': next((link.get('href', '') for link in links
                             if link.get('rel') == 'alternate'), ''),
                'source': source, 'image': _blog_thumb(images[0]) if images else '',
                'images': images, 'brand': _field(body, r'(?:BRAND|MAKE|MANUFACTURER)'),
                'weight': _field(body, 'WEIGHT'), 'ref': _field(body, r'REF(?:\.?\s*NO\.?)?') or ref,
            }
            break
        if found:
            break
    with _lock:
        _cache[key] = found
    return found


def fill_missing(results):
    missing = [row for row in results if not row.get('found')][:25]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=8) as pool:
        hits = list(pool.map(lambda row: lookup_ref(row['sku_input']), missing))
    for row, hit in zip(missing, hits):
        if hit:
            row.update(hit)
