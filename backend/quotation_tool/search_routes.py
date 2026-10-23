from flask import Blueprint, request, jsonify, send_file, session, redirect, make_response
import os
import sqlite3
import requests
import threading
from backend.config import BASE_DIR
from backend.common.auth import login_required
from backend.quotation_tool.search_service import _zoho_img_get_token, _search_zoho, _search_blog, _BLOG_FEEDS
from backend.quotation_tool.price_history import search_price_history
from backend.quotation_tool.pricing_db import connect as pricing_connect

bp = Blueprint('quotation_search', __name__)

@bp.route('/api/zoho-image/<item_id>')
@login_required
def zoho_image_proxy(item_id):
    """Proxy Zoho item image through server using APEX's stored OAuth token."""
    try:
        token = _zoho_img_get_token()
        if not token:
            return '', 503
        # Get org_id and region from token cache context
        if os.environ.get('PGHOST') or os.path.isfile('/etc/aeliya/.pg.env'):
            con = pricing_connect()
            cur = con.cursor()
            cur.execute('SELECT org_id, region FROM pricing.zoho_tokens LIMIT 1')
            row = cur.fetchone()
            cur.close()
            con.close()
        else:
            apex_dir = os.path.join(os.path.dirname(BASE_DIR), 'Pricing-App')
            con = sqlite3.connect(os.path.join(apex_dir, 'pricesync.db'))
            con.row_factory = sqlite3.Row
            row = con.execute('SELECT org_id, region FROM zoho_tokens LIMIT 1').fetchone()
            con.close()
        if not row:
            return '', 503
        row = dict(row)
        org_id = row['org_id']
        region = row.get('region') or 'com'

        url  = f'https://www.zohoapis.{region}/inventory/v1/items/{item_id}/image?organization_id={org_id}'
        resp = requests.get(url, headers={'Authorization': f'Zoho-oauthtoken {token}'}, timeout=15)
        ct   = resp.headers.get('Content-Type', '')
        if not resp.ok or 'text/html' in ct or 'application/json' in ct:
            import logging
            logging.warning(f'Zoho image proxy: HTTP {resp.status_code} ct={ct} body={resp.text[:300]}')
            return '', 404
        from flask import Response
        return Response(resp.content,
                        content_type=ct or 'image/jpeg',
                        headers={'Cache-Control': 'public, max-age=86400'})
    except Exception as ex:
        import logging
        logging.warning(f'Zoho image proxy exception: {ex}')
        return '', 500


@bp.route('/api/search-all')
@login_required
def api_search_all():
    q = (request.args.get('q') or '').strip()
    if not q or len(q) < 2:
        return jsonify({'results': [], 'counts': {}, 'error': 'Query too short'})

    buckets = {'zoho': [], 'atlas': [], 'alreza': [], 'price': [], 'errors': {}}
    threads = []

    def run(fn, key, *args):
        try:
            buckets[key] = fn(*args)
        except Exception as ex:
            buckets['errors'][key] = str(ex)

    t1 = threading.Thread(target=run, args=(_search_zoho,  'zoho',   q))
    t2 = threading.Thread(target=run, args=(_search_blog,  'atlas',  _BLOG_FEEDS['atlas'],  'atlas',  q))
    t3 = threading.Thread(target=run, args=(_search_blog,  'alreza', _BLOG_FEEDS['alreza'], 'alreza', q))
    t4 = threading.Thread(target=run, args=(search_price_history, 'price', q))
    for t in [t1, t2, t3, t4]:
        t.start()
    for t in [t1, t2, t3, t4]:
        t.join(timeout=15)

    all_results = buckets['zoho'] + buckets['atlas'] + buckets['alreza']
    counts = {
        'total':  len(all_results),
        'zoho':   len(buckets['zoho']),
        'atlas':  len(buckets['atlas']),
        'alreza': len(buckets['alreza']),
        'price':  len(buckets['price']),
    }
    return jsonify({'results': all_results, 'price_history': buckets['price'],
                    'counts': counts, 'errors': buckets['errors']})


