import re
import json
import requests
import threading
import time
from bs4 import BeautifulSoup

import os
from dotenv import load_dotenv

load_dotenv()
SHOP = os.getenv("SHOPIFY_SHOP", "")
CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")

def _require_credentials():
    """Fail only when a Shopify API call is made, not while importing the app."""
    if not all((SHOP, CLIENT_ID, CLIENT_SECRET)):
        raise RuntimeError(
            "Shopify credentials are missing. Set SHOPIFY_SHOP, "
            "SHOPIFY_CLIENT_ID, and SHOPIFY_CLIENT_SECRET in the environment "
            "or the project .env file."
        )

CONDITION_KEYS = ['condition','product_condition','item_condition','google_product_condition']
CONDITION_NS   = ['next_cart','custom','global','mm-google-shopping','google','google_shopping']

_token_cache = {'token': None, 'expires': 0}
_token_lock  = threading.Lock()
_sku_cache   = {}
_sku_lock    = threading.Lock()

def _mf_alias(ns, key):
    return 'mf_' + re.sub(r'[^A-Za-z0-9_]', '_', ns + '_' + key)

def _cond_suffix(c):
    c = (c or '').lower().strip()
    if c == 'new':  return '/Surplus'
    if c == 'used': return '/Second Hand'
    return ''


def _storefront_condition(url):
    """Read the condition displayed by the storefront theme when Admin omits it."""
    if not url:
        return ''
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if response.status_code != 200:
            return ''
        label = BeautifulSoup(response.text, 'html.parser').select_one(
            '.amt-pdp-condition-label'
        )
        if not label:
            return ''
        value = label.parent.select_one('.amt-pdp-condition-value')
        if value:
            return value.get_text(' ', strip=True)
        text = label.get_text(' ', strip=True)
        return text.split(':', 1)[1].strip() if ':' in text else ''
    except requests.RequestException:
        return ''

def _get_token():
    _require_credentials()
    now = time.time()
    with _token_lock:
        if _token_cache['token'] and now < _token_cache['expires']:
            return _token_cache['token']
    r = requests.post(
        f'https://{SHOP}/admin/oauth/access_token',
        json={'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET,
              'grant_type': 'client_credentials'}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f'Token error {r.status_code}')
    data = r.json()
    if 'access_token' not in data:
        raise RuntimeError('No access_token in response')
    with _token_lock:
        _token_cache.update(token=data['access_token'], expires=now + 3600)
    return _token_cache['token']

def fetch_sku(sku_raw, *, refresh=False):
    sku = sku_raw.strip()
    key = sku.upper()
    with _sku_lock:
        if not refresh and key in _sku_cache:
            cached, ts = _sku_cache[key]
            if time.time() - ts < 900:
                return cached

    token = _get_token()
    seen, mf_parts = set(), []
    for ns in CONDITION_NS:
        for k in CONDITION_KEYS:
            a = _mf_alias(ns, k)
            if a not in seen:
                seen.add(a)
                mf_parts.append(f'{a}: metafield(namespace:"{ns}", key:"{k}") {{ value }}')
    mf_block = '\n        '.join(mf_parts)

    safe  = sku.replace('\\','\\\\').replace('"','\\"')
    query = (
        '{ productVariants(first:1, query:"sku:\\"' + safe + '\\"") { edges { node {\n'
        '    sku price compareAtPrice inventoryQuantity\n'
        '    ' + mf_block + '\n'
        '    product { title onlineStoreUrl\n'
        '      ' + mf_block + '\n'
        '    }\n'
        '  } } } }'
    )

    last = None
    for attempt in range(3):
        r = requests.post(
            f'https://{SHOP}/admin/api/2026-01/graphql.json',
            headers={'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'},
            json={'query': query}, timeout=15)
        last = r
        if r.status_code == 429:
            time.sleep((attempt + 1) * 2)
            continue
        if r.status_code != 200:
            raise RuntimeError(f'GraphQL error {r.status_code}')
        break

    gql = last.json()
    if gql.get('errors'):
        msgs = '; '.join(e.get('message', '?') for e in gql['errors'][:2])
        raise RuntimeError(f'GraphQL: {msgs}')
    edges = ((gql.get('data') or {}).get('productVariants') or {}).get('edges', [])

    if not edges:
        result = {'found': False}
    else:
        node    = edges[0]['node']
        product = node.get('product') or {}

        def pick(aliases):
            for a in aliases:
                v = ((node.get(a) or {}).get('value') or
                     (product.get(a) or {}).get('value'))
                if v: return v
            return ''

        cond_al = [_mf_alias(ns, k) for ns in CONDITION_NS for k in CONDITION_KEYS]
        url     = product.get('onlineStoreUrl', '')
        cond    = pick(cond_al) or _storefront_condition(url)

        result = {
            'found':     True,
            'sku':       node.get('sku', sku),
            'title':     product.get('title', ''),
            'condition': (cond + _cond_suffix(cond)) if cond else '',
            'url':       url,
            'qty':       node.get('inventoryQuantity', ''),
            'price':     float(node['compareAtPrice']) if (node.get('compareAtPrice') and node.get('price') and float(node['compareAtPrice']) > float(node['price'])) else (float(node['price']) if node.get('price') else None),
            'sale_price': float(node['price']) if (node.get('compareAtPrice') and node.get('price') and float(node['compareAtPrice']) > float(node['price'])) else None,
        }

    with _sku_lock:
        _sku_cache[key] = (result, time.time())
    return result


def fetch_skus_batch(skus, chunk=40):
    """Resolve bulk requests with Shopify OR queries and reuse the SKU cache."""
    result = {}
    pending = []
    for raw in skus:
        key = raw.strip().upper()
        with _sku_lock:
            cached = _sku_cache.get(key)
        if cached and time.time() - cached[1] < 900:
            result[key] = cached[0]
        elif key not in pending:
            pending.append(key)
    if not pending:
        return result

    seen = set()
    fields = []
    for namespace in CONDITION_NS:
        for field in CONDITION_KEYS:
            alias = _mf_alias(namespace, field)
            if alias not in seen:
                seen.add(alias)
                fields.append(f'{alias}: metafield(namespace:"{namespace}", key:"{field}") {{ value }}')
    meta = '\n'.join(fields)
    token = _get_token()
    for start in range(0, len(pending), chunk):
        part = pending[start:start + chunk]
        search = ' OR '.join('sku:"' + sku.replace('\\', '\\\\').replace('"', '\\"') + '"' for sku in part)
        query = ('{ productVariants(first:' + str(len(part) * 2) + ', query:' + json.dumps(search) +
                 ') { edges { node { sku price compareAtPrice inventoryQuantity ' + meta +
                 ' product { title onlineStoreUrl ' + meta + ' } } } }')
        response = None
        for attempt in range(3):
            try:
                response = requests.post(
                    f'https://{SHOP}/admin/api/2026-01/graphql.json',
                    headers={'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'},
                    json={'query': query}, timeout=30)
            except requests.RequestException:
                response = None
                break
            if response.status_code != 429:
                break
            time.sleep((attempt + 1) * 2)
        found = {}
        valid = False
        if response is not None and response.status_code == 200:
            try:
                payload = response.json()
                if not payload.get('errors'):
                    valid = True
                    for edge in ((payload.get('data') or {}).get('productVariants') or {}).get('edges', []):
                        node = edge.get('node') or {}
                        key = str(node.get('sku') or '').strip().upper()
                        if key:
                            product = node.get('product') or {}
                            condition = next((value for alias in seen if
                                              (value := ((node.get(alias) or {}).get('value') or
                                                         (product.get(alias) or {}).get('value')))), '')
                            url = product.get('onlineStoreUrl', '')
                            if not condition:
                                condition = _storefront_condition(url)
                            price = float(node['price']) if node.get('price') else None
                            compare = float(node['compareAtPrice']) if node.get('compareAtPrice') else None
                            discount = compare is not None and price is not None and compare > price
                            found[key] = {
                                'found': True, 'sku': node.get('sku', key),
                                'title': product.get('title', ''),
                                'condition': condition + _cond_suffix(condition) if condition else '',
                                'url': url,
                                'qty': node.get('inventoryQuantity', ''),
                                'price': compare if discount else price,
                                'sale_price': price if discount else None,
                            }
            except (ValueError, TypeError, KeyError):
                valid = False
                found = {}
        for key in part:
            if key in found:
                value = found[key]
            elif valid:
                value = {'found': False}
            else:
                try:
                    value = fetch_sku(key)
                except Exception as error:
                    value = {'found': False, 'error': str(error)[:120]}
            result[key] = value
            if valid:
                with _sku_lock:
                    _sku_cache[key] = (value, time.time())
    return result

def get_inr_rate():
    # Use the same dated reference rate as PI conversions.
    from backend.common.currencies import configured_rates
    from backend.common.live_rates import refresh_if_due
    from backend.database import get_db
    def cached():
        connection = get_db()
        try:
            return configured_rates(connection).get('INR')
        finally:
            connection.close()
    value = cached()
    if value is None:
        refresh_if_due()
        value = cached()
    return float(value) if value is not None else None

# ── Routes ────────────────────────────────────────────────────────────────────
