from flask import Blueprint, request, jsonify, send_file, redirect, make_response
import threading
from backend.config import FRONTEND_DIR
from backend.common.auth import login_required, request_actor_name
from backend.common.request import _get_ip
from backend.common.skus import duplicate_skus, enforce_sku_lookup_limit
from backend.database import log_search, log_copy
from backend.quotation_tool.shopify import fetch_sku, fetch_skus_batch, get_inr_rate, _sku_cache, _sku_lock, _token_cache, _token_lock
from backend.quotation_tool.blog_lookup import fill_missing
from backend.quotation_tool.quote_builder import _q_build_table, _q_strip_tags
from backend.quotation_tool.price_history import price_age_map
from backend.quotation_tool.quote_lines import log_quote_lines

bp = Blueprint('quotation_tool', __name__)

@bp.route('/')
@login_required
def index():
    return send_file(str(FRONTEND_DIR / 'quotation_tool' / 'quotation.html'))


@bp.route('/api/rate')
@login_required
def api_rate():
    return jsonify({'rate': get_inr_rate()})


@bp.route('/api/lookup', methods=['POST'])
@login_required
def api_lookup():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('skus'), list):
        return jsonify(error='Provide a list of SKUs.'), 400
    if any(not isinstance(s, str) for s in data['skus']):
        return jsonify(error='Each SKU must be text.'), 400
    skus_raw = [s.strip() for s in data['skus'] if s.strip()]
    try:
        enforce_sku_lookup_limit(len(skus_raw))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    duplicates = duplicate_skus(skus_raw)
    if duplicates:
        return jsonify(error='Duplicate SKUs: '+', '.join(duplicates)+
                       '. Enter each SKU only once.'), 400
    user_name = request_actor_name()
    user_ip   = _get_ip()

    results = _lookup_rows(skus_raw)

    found     = sum(1 for r in results if r.get('found'))
    not_found = len(results) - found

    threading.Thread(
        target=log_search,
        args=(user_name, user_ip, skus_raw, found, not_found),
        daemon=True
    ).start()
    threading.Thread(target=log_quote_lines,
                     args=(user_name, 'lookup', results), daemon=True).start()

    return jsonify({'results': results, 'found': found, 'not_found': not_found})


def _lookup_rows(skus_raw):
    try:
        found_map = fetch_skus_batch(skus_raw)
    except Exception:
        found_map = {}
    results = []
    for sku in skus_raw:
        try:
            d = found_map.get(sku.upper())
            if d is None:
                d = fetch_sku(sku)
            results.append({'sku_input': sku, **d})
        except Exception as e:
            results.append({'sku_input': sku, 'found': False, 'error': str(e)[:120]})
    try:
        fill_missing(results)
    except Exception:
        pass
    try:
        ages = price_age_map([row['sku_input'] for row in results])
    except Exception:
        ages = {}
    for row in results:
        age = ages.get(row['sku_input'].upper())
        row['price_last_updated'] = age['last_priced'] if age else None
        row['price_age_days'] = age['days'] if age else None
    return results


@bp.route('/api/quotation/letter', methods=['POST'])
@login_required
def api_quotation_letter():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('skus'), list):
        return jsonify(error='skus is required'), 400
    if any(not isinstance(sku, str) for sku in data['skus']):
        return jsonify(error='Each SKU must be text.'), 400
    skus_raw = [sku.strip() for sku in data['skus'] if sku.strip()]
    try:
        enforce_sku_lookup_limit(len(skus_raw))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    duplicates = duplicate_skus(skus_raw)
    if duplicates:
        return jsonify(error='Duplicate SKUs: ' + ', '.join(duplicates) +
                       '. Enter each SKU only once.'), 400
    currency = data.get('currency') or 'USD'
    if not isinstance(currency, str) or currency.upper() not in ('USD', 'INR'):
        return jsonify(error='currency must be USD or INR'), 400
    currency = currency.upper()
    rows = _lookup_rows(skus_raw)
    threading.Thread(target=log_quote_lines,
                     args=(request_actor_name(), 'letter', rows), daemon=True).start()
    rate = float(get_inr_rate() or 0) if currency == 'INR' else 0.0
    table = _q_build_table(rows, currency, rate)
    if data.get('letter', True):
        font = 'font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#000000;'
        save_line = '' if currency == 'INR' else (
            '<p style="%smargin:12px 0 8px 0;"><span style="background:#FFE0A0;padding:5px 14px;'
            'border-radius:3px;display:inline-block;"><strong>Save up to 7%% instantly by ordering '
            'through our e-Store. Simply click the product link(s) in the quotation table and '
            'complete your purchase today to enjoy this exclusive online discount.</strong>'
            '</span></p>' % font)
        html = (
            '<div style="%s">\n'
            '<p style="margin:0 0 10px 0;">Dear Sir/Madam,</p>\n'
            '<p style="margin:0 0 10px 0;">Greetings from Aeliya Marine Tech!</p>\n'
            '<p style="margin:0 0 10px 0;">Thank you for your inquiry.</p>\n'
            '<p style="margin:0 0 10px 0;">Please find the following quotation with the product '
            'specification link or attached photos. Kindly review the details and discuss them '
            'with your technical team for compatibility.</p>\n'
            '%s\n%s\n'
            '<p style="%smargin:8px 0 8px 0;"><strong>You are only buying what you see in the '
            'photos.</strong></p>\n'
            '<p style="%smargin:0 0 12px 0;">Feel free to reach out if you have any questions or '
            'need further information.</p>\n'
            '<p style="%smargin:0;">Best regards,</p>\n</div>'
            % (font, table, save_line, font, font, font))
    else:
        html = table
    found = sum(1 for row in rows if row.get('found'))
    return jsonify(html=html, text=_q_strip_tags(html), rows=rows,
                   found=found, not_found=len(rows)-found, currency=currency, rate=rate)


@bp.route('/api/log-copy', methods=['POST'])
@login_required
def api_log_copy():
    data      = request.json or {}
    user_name = request_actor_name()
    copy_type = data.get('copy_type', '')
    sku_count = int(data.get('sku_count', 0))
    threading.Thread(
        target=log_copy,
        args=(user_name, _get_ip(), copy_type, sku_count),
        daemon=True
    ).start()
    return jsonify({'ok': True})


@bp.route('/api/clear-cache', methods=['POST'])
@login_required
def api_clear_cache():
    with _sku_lock:
        _sku_cache.clear()
    with _token_lock:
        _token_cache.update(token=None, expires=0)
    return jsonify({'ok': True})


