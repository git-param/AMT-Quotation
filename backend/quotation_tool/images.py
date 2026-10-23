"""Catalog image lookup and browser downloads."""
import io
import json
import mimetypes
import os
import re
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from flask import Blueprint, jsonify, make_response, request, send_file

from backend.common.auth import login_required
from backend.common.skus import enforce_sku_lookup_limit
from backend.config import BASE_DIR
from backend.quotation_tool.blog_lookup import lookup_ref
from backend.quotation_tool.pricing_db import connect as pricing_connect
from backend.quotation_tool.search_service import _zoho_img_get_token

bp = Blueprint('quotation_images', __name__)
HOSTS = ('blogger.googleusercontent.com', 'bp.blogspot.com',
         'lh3.googleusercontent.com', 'atlasship.blogspot.com',
         'alrezaenterprise.com', 'zoho.com', 'zoho.in', 'zoho.eu',
         'zoho.com.au', 'zoho.jp', 'zoho.com.cn', 'zoho.sa', 'zoho.ca',
         'zohocdn.com')
MAX_IMAGE = 25 * 1024 * 1024


def _host_ok(url):
    parsed = urlparse(str(url or ''))
    host = (parsed.hostname or '').lower()
    return parsed.scheme in ('http', 'https') and any(
        host == allowed or host.endswith('.' + allowed) for allowed in HOSTS)


def _fetch_public_image(url):
    if not _host_ok(url):
        raise ValueError('That image host is not allowed')
    for _ in range(4):
        with requests.get(url, timeout=25, stream=True, allow_redirects=False,
                          headers={'User-Agent': 'Mozilla/5.0'}) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get('Location', ''))
                if not _host_ok(url):
                    raise ValueError('Redirect to a disallowed host')
                continue
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
            if not content_type.startswith('image/'):
                raise ValueError('Not an image')
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_IMAGE:
                    raise ValueError('Image too large')
            return bytes(data), content_type
    raise ValueError('Too many image redirects')


def _fetch_zoho_image(url):
    item_id = url.removeprefix('/api/zoho-image/')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', item_id):
        raise ValueError('Invalid Zoho item ID')
    token = _zoho_img_get_token()
    if not token:
        raise ValueError('Zoho image token unavailable')
    if os.environ.get('PGHOST') or os.path.isfile('/etc/aeliya/.pg.env'):
        connection = pricing_connect()
        cursor = connection.cursor()
        try:
            cursor.execute('SELECT org_id, region FROM pricing.zoho_tokens LIMIT 1')
            row = cursor.fetchone()
        finally:
            cursor.close()
            connection.close()
    else:
        path = os.path.join(os.path.dirname(BASE_DIR), 'Pricing-App', 'pricesync.db')
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute('SELECT org_id, region FROM zoho_tokens LIMIT 1').fetchone()
        finally:
            connection.close()
    if not row:
        raise ValueError('Zoho organization unavailable')
    row = dict(row)
    region = row.get('region') or 'com'
    if region not in ('com', 'in', 'eu', 'com.au', 'jp', 'com.cn', 'sa', 'ca'):
        raise ValueError('Invalid Zoho region')
    api = f'https://www.zohoapis.{region}/inventory/v1/items/{item_id}/image'
    with requests.get(api, params={'organization_id': row['org_id']}, timeout=25,
                      stream=True, allow_redirects=False,
                      headers={'Authorization': f'Zoho-oauthtoken {token}'}) as response:
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
        if not content_type.startswith('image/'):
            raise ValueError('Not an image')
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > MAX_IMAGE:
                raise ValueError('Image too large')
        return bytes(data), content_type


def _catalog_images(skus):
    if os.environ.get('PGHOST') or os.path.isfile('/etc/aeliya/.pg.env'):
        connection = pricing_connect()
        try:
            cursor = connection.cursor()
            cursor.execute('''SELECT sku, zoho_item_id, image_docs_json, raw_json
                FROM pricing.zoho_inventory WHERE UPPER(TRIM(sku)) = ANY(%s)''',
                ([sku.upper() for sku in skus],))
            rows = cursor.fetchall()
            cursor.close()
        finally:
            connection.close()
    else:
        path = os.path.join(os.path.dirname(BASE_DIR), 'Pricing-App', 'catalog.db')
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            placeholders = ','.join('?' for _ in skus)
            rows = connection.execute(
                f'SELECT sku, zoho_item_id, image_docs_json, raw_json FROM zoho_inventory '
                f'WHERE UPPER(TRIM(sku)) IN ({placeholders})',
                [sku.upper() for sku in skus]).fetchall()
        finally:
            connection.close()
    images = []
    for row in rows:
        try:
            docs = json.loads(row['image_docs_json'] or '[]')
            urls = [doc.get('url') or doc.get('document_url') for doc in docs
                    if isinstance(doc, dict) and (doc.get('url') or doc.get('document_url'))]
        except (ValueError, TypeError):
            urls = []
        if not urls and row['zoho_item_id']:
            try:
                if json.loads(row['raw_json'] or '{}').get('image_document_id'):
                    urls = [f'/api/zoho-image/{row["zoho_item_id"]}']
            except (ValueError, TypeError):
                pass
        images.append({'sku': row['sku'], 'image': urls[0] if urls else '', 'images': urls})
    found = {str(item['sku']).upper() for item in images}
    missing = [sku for sku in skus if sku.upper() not in found][:25]
    with ThreadPoolExecutor(max_workers=8) as pool:
        hits = list(pool.map(lookup_ref, missing))
    for sku, hit in zip(missing, hits):
        if hit and hit.get('images'):
            urls = hit['images']
            images.append({'sku': sku, 'image': urls[0], 'images': urls, 'source': 'blog'})
    return images


@bp.route('/api/images', methods=['POST'])
@login_required
def api_images():
    payload = request.get_json(silent=True)
    skus = payload.get('skus') if isinstance(payload, dict) else None
    if not isinstance(skus, list) or any(not isinstance(sku, str) for sku in skus):
        return jsonify(error='Provide a list of SKUs.'), 400
    skus = [sku.strip() for sku in skus if sku.strip()]
    if not skus:
        return jsonify(images=[])
    try:
        enforce_sku_lookup_limit(len(skus))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    try:
        return jsonify(images=_catalog_images(skus))
    except Exception:
        return jsonify(error='Could not load catalog images.'), 503


@bp.route('/api/image-proxy')
@login_required
def api_image_proxy():
    url = request.args.get('url', '')
    try:
        data, content_type = _fetch_public_image(url)
    except ValueError as error:
        return jsonify(error=str(error)), 403
    except requests.RequestException:
        return jsonify(error='Could not fetch that image'), 502
    response = make_response(data)
    response.headers['Content-Type'] = content_type
    response.headers['Cache-Control'] = 'private, max-age=3600'
    return response


@bp.route('/api/download-images-zip', methods=['POST'])
@login_required
def api_download_images_zip():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='Invalid image request'), 400
    entries = payload.get('sku_images')
    if not entries:
        skus = payload.get('skus')
        if not isinstance(skus, list) or any(not isinstance(sku, str) for sku in skus):
            return jsonify(error='Provide a list of SKUs.'), 400
        try:
            enforce_sku_lookup_limit(len(skus))
            entries = [{'sku': item['sku'], 'urls': item['images']}
                       for item in _catalog_images(skus) if item['images']]
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='Could not load catalog images.'), 503
    if not isinstance(entries, list) or len(entries) > 500 or any(
            not isinstance(item, dict) or not isinstance(item.get('sku'), str)
            or not isinstance(item.get('urls'), list) for item in entries):
        return jsonify(error='Invalid image list'), 400
    output = io.BytesIO()
    added = 0
    total_bytes = 0
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in entries:
            sku = re.sub(r'[^A-Za-z0-9._-]', '_', item['sku'])[:100].strip('._') or 'SKU'
            for index, url in enumerate(item['urls'][:24], 1):
                if not isinstance(url, str):
                    continue
                try:
                    data, content_type = (_fetch_zoho_image(url)
                                          if url.startswith('/api/zoho-image/')
                                          else _fetch_public_image(url))
                    if total_bytes + len(data) > 100 * 1024 * 1024 or added >= 200:
                        break
                    extension = mimetypes.guess_extension(content_type) or '.jpg'
                    archive.writestr(f'{sku}/{sku}_{index}{extension}', data)
                    added += 1
                    total_bytes += len(data)
                except (ValueError, requests.RequestException):
                    continue
    if not added:
        return jsonify(error='Could not download any images'), 404
    output.seek(0)
    return send_file(output, mimetype='application/zip', as_attachment=True,
                     download_name='product_images.zip')
