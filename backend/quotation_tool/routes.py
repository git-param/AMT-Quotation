from flask import Blueprint, request, jsonify, send_file, redirect, make_response
import threading
from backend.config import FRONTEND_DIR
from backend.common.auth import login_required, request_actor_name
from backend.common.request import _get_ip
from backend.common.skus import duplicate_skus, enforce_sku_lookup_limit
from backend.database import log_search, log_copy
from backend.quotation_tool.shopify import fetch_sku, get_inr_rate, _sku_cache, _sku_lock, _token_cache, _token_lock

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

    results = []
    for sku in skus_raw:
        try:
            d = fetch_sku(sku)
            results.append({'sku_input': sku, **d})
        except Exception as e:
            results.append({'sku_input': sku, 'found': False, 'error': str(e)[:120]})

    found     = sum(1 for r in results if r.get('found'))
    not_found = len(results) - found

    threading.Thread(
        target=log_search,
        args=(user_name, user_ip, skus_raw, found, not_found),
        daemon=True
    ).start()

    return jsonify({'results': results, 'found': found, 'not_found': not_found})


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


