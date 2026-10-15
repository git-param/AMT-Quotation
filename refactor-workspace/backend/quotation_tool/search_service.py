import os
import sqlite3
import requests
import threading
from datetime import datetime
from backend.config import BASE_DIR

def _search_zoho(q):
    import json as _json
    cat_db = os.path.join(os.path.dirname(BASE_DIR), 'Pricing-App', 'catalog.db')
    like = f'%{q}%'
    con  = sqlite3.connect(cat_db)
    con.row_factory = sqlite3.Row
    rows = con.execute('''
        SELECT sku, item_name, stock_on_hand, condition,
               weight_lbs, weight_unit, brand, image_docs_json,
               zoho_item_id, raw_json
        FROM zoho_inventory
        WHERE (sku LIKE ? OR item_name LIKE ? OR brand LIKE ? OR mpn LIKE ? OR description LIKE ?)
          AND (status IS NULL OR status != 'inactive')
        ORDER BY
          CASE WHEN sku = ? THEN 0 WHEN sku LIKE ? THEN 1 ELSE 2 END,
          item_name COLLATE NOCASE
        LIMIT 60
    ''', (like, like, like, like, like, q, f'{q}%')).fetchall()
    con.close()
    results = []
    for r in rows:
        w  = r['weight_lbs']
        wu = (r['weight_unit'] or 'kg').lower()
        # Resolve image: prefer stored docs, fall back to raw_json image_document_id
        img = None
        item_id = r['zoho_item_id'] or ''
        try:
            docs = _json.loads(r['image_docs_json'] or '[]')
            if docs and isinstance(docs, list):
                img = docs[0].get('url') or docs[0].get('document_url')
        except Exception:
            pass
        if not img and item_id:
            try:
                raw = _json.loads(r['raw_json'] or '{}')
                if raw.get('image_document_id'):
                    img = f'/api/zoho-image/{item_id}'
            except Exception:
                pass
        results.append({
            'source':    'zoho',
            'sku':       r['sku'],
            'title':     r['item_name'] or '',
            'stock':     r['stock_on_hand'] if r['stock_on_hand'] is not None else 0,
            'condition': r['condition'] or '',
            'weight':    f'{w} {wu}' if w else '',
            'brand':     r['brand'] or '',
            'snippet':   '',
            'url':       '',
            'image':     img or '',
        })
    return results

def _blog_thumb(url):
    """Resize Blogger CDN image URL to thumbnail."""
    import re
    return re.sub(r'/s\d+/', '/s300/', url) if url else ''

def _search_blog(feed_url, source_key, q, max_results=20):
    import re
    url = f'{feed_url}?q={requests.utils.quote(q)}&alt=json&max-results={max_results}'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        entries = r.json().get('feed', {}).get('entry', [])
    except Exception:
        return []

    from bs4 import BeautifulSoup
    results = []
    for e in entries:
        title   = e.get('title', {}).get('$t', '')
        link    = next((l['href'] for l in e.get('link', []) if l.get('rel') == 'alternate'), '')
        content = (e.get('content') or e.get('summary') or {}).get('$t', '')
        imgs    = re.findall(r'src=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', content, re.I)
        snippet = BeautifulSoup(content, 'html.parser').get_text()[:200].strip()
        results.append({
            'source':    source_key,
            'sku':       '',
            'title':     title,
            'stock':     None,
            'condition': '',
            'weight':    '',
            'brand':     '',
            'snippet':   snippet,
            'url':       link,
            'image':     _blog_thumb(imgs[0]) if imgs else '',
        })
    return results

_BLOG_FEEDS = {
    'atlas':  'https://atlasship.blogspot.com/feeds/posts/default',
    'alreza': 'https://www.alrezaenterprise.com/feeds/posts/default',
}

_zoho_img_token_cache = {'token': None, 'expires_at': None}
_zoho_img_token_lock  = threading.Lock()

def _zoho_img_get_token():
    """Return a valid Zoho access token, refreshing if needed."""
    import json as _json
    from datetime import timezone, timedelta
    with _zoho_img_token_lock:
        cached = _zoho_img_token_cache
        if cached['token'] and cached['expires_at']:
            try:
                exp = datetime.fromisoformat(cached['expires_at'])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp > datetime.now(timezone.utc) + timedelta(minutes=5):
                    return cached['token']
            except Exception:
                pass

        apex_dir  = os.path.join(os.path.dirname(BASE_DIR), 'Pricing-App')
        db_path   = os.path.join(apex_dir, 'pricesync.db')
        cfg_path  = os.path.join(apex_dir, 'config.json')

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute('SELECT * FROM zoho_tokens LIMIT 1').fetchone()
        con.close()
        if not row:
            return None

        token   = (row['access_token']  or '').strip()
        refresh = (row['refresh_token'] or '').strip()
        org_id  = row['org_id']
        region  = row.get('region') or 'com'
        exp_str = (row['expires_at']    or '').strip()

        # Check if stored token still valid
        if token and exp_str:
            try:
                exp = datetime.fromisoformat(exp_str)
                if exp.tzinfo is None:
                    from datetime import timezone
                    exp = exp.replace(tzinfo=timezone.utc)
                from datetime import timezone, timedelta
                if exp > datetime.now(timezone.utc) + timedelta(minutes=5):
                    cached['token'] = token
                    cached['expires_at'] = exp_str
                    return token
            except Exception:
                pass

        # Refresh
        if not refresh:
            return None
        try:
            cfg = _json.load(open(cfg_path))
            org_cfg = next((o for o in (cfg.get('zoho_orgs') or []) if o.get('org_id') == org_id), None)
            if not org_cfg:
                return None
            client_id     = org_cfg.get('client_id', '')
            client_secret = org_cfg.get('client_secret', '')
            r = requests.post(
                f'https://accounts.zoho.{region}/oauth/v2/token',
                data={'grant_type': 'refresh_token', 'client_id': client_id,
                      'client_secret': client_secret, 'refresh_token': refresh},
                timeout=15)
            if not r.ok:
                return None
            new_token = r.json().get('access_token')
            if new_token:
                from datetime import timezone, timedelta
                exp = (datetime.now(timezone.utc) + timedelta(seconds=3600)).isoformat()
                # Update DB
                con = sqlite3.connect(db_path)
                con.execute('UPDATE zoho_tokens SET access_token=?, expires_at=? WHERE org_id=?',
                            (new_token, exp, org_id))
                con.commit()
                con.close()
                cached['token'] = new_token
                cached['expires_at'] = exp
                return new_token
        except Exception:
            pass
        return None

