"""Read pricing changes for a numeric SKU from the shared pricing database."""
import re
from datetime import date
import os
from flask import Blueprint, jsonify, request, current_app
from backend.common.auth import login_required
from backend.quotation_tool.pricing_db import connect

bp = Blueprint('quotation_price_history', __name__)


def price_age_map(skus):
    """Return latest pricing month per SKU; IDs cannot represent chronology."""
    if not (os.environ.get('PGHOST') or os.path.isfile('/etc/aeliya/.pg.env')):
        return {}
    keys = sorted({str(sku or '').strip().upper() for sku in skus if str(sku or '').strip()})
    if not keys:
        return {}
    connection = connect()
    try:
        cursor = connection.cursor()
        cursor.execute('''SELECT UPPER(TRIM(sku)) AS sku,
                   MAX(make_date(year, month, 1)) AS last_priced
            FROM pricing.pricing_history
            WHERE COALESCE(is_archived, 0) = 0 AND year BETWEEN 2000 AND 2100
              AND month BETWEEN 1 AND 12 AND UPPER(TRIM(sku)) = ANY(%s)
            GROUP BY 1''', (keys,))
        rows = cursor.fetchall()
        cursor.close()
    finally:
        connection.close()
    today = date.today()
    return {row['sku']: {'last_priced': row['last_priced'].strftime('%Y-%m'),
                         'days': (today - row['last_priced']).days}
            for row in rows if row['last_priced']}


def search_price_history(value):
    sku = str(value or '').strip().lstrip("'")
    if not re.fullmatch(r'\d{3,12}', sku):
        return []
    connection = connect()
    try:
        cursor = connection.cursor()
        cursor.execute('''
            SELECT id, year, month, day, sku, price, lot_set_pack, remarks,
                   ref, entry_type, exec_name, created_at
            FROM pricing.pricing_history
            WHERE sku = %s AND COALESCE(is_archived, 0) = 0
            ORDER BY year DESC, month DESC, day DESC, id DESC LIMIT 60
        ''', (sku,))
        rows = cursor.fetchall()
        cursor.close()
    finally:
        connection.close()
    out = []
    for index, row in enumerate(rows):
        price = float(row['price']) if row['price'] is not None else None
        older = rows[index + 1] if index + 1 < len(rows) else None
        previous = float(older['price']) if older and older['price'] is not None else None
        try:
            date = f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"
        except (ValueError, TypeError):
            date = str(row['created_at'] or '')[:10]
        who = str(row['exec_name'] or '').strip()
        out.append({
            'source': 'price', 'sku': row['sku'], 'date': date,
            'created_at': str(row['created_at'] or '')[:19], 'price': price,
            'prev_price': previous,
            'delta_pct': round((price - previous) / previous * 100, 1)
                         if price is not None and previous not in (None, 0) else None,
            'automated': who.lower() in ('system', 'auto', ''), 'by': who or 'Unknown',
            'remarks': str(row['remarks'] or '').strip(), 'ref': str(row['ref'] or '').strip(),
            'entry_type': str(row['entry_type'] or '').strip(),
            'lot': str(row['lot_set_pack'] or '').strip(),
        })
    return out


@bp.route('/api/price-history')
@login_required
def api_price_history():
    sku = (request.args.get('sku') or request.args.get('q') or '').strip()
    if not sku:
        return jsonify(rows=[], error='Enter a SKU')
    try:
        rows = search_price_history(sku)
    except Exception as error:
        current_app.logger.warning('Price history lookup failed: %s', error)
        return jsonify(rows=[], error='Lookup failed'), 503
    return jsonify(rows=rows, count=len(rows), sku=sku)
