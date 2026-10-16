"""Search saved PIs using the same client visibility as order downloads."""
from flask import jsonify, request, send_file

from backend.common.auth import authenticated_required, get_current_user
from backend.client_leads.discovery import integer
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.orders.routes import bp
from backend.orders.service import order_query


@bp.route('/search-pi')
@authenticated_required
def search_pi_page():
    return send_file(str(FRONTEND_DIR / 'orders' / 'pi-search.html'))


@bp.route('/api/pi-search')
@authenticated_required
def search_pi():
    try:
        page = integer(request.args.get('page', '1'), 'page', 1000000)
        size = integer(request.args.get('page_size', '25'), 'page size', 100)
        term = request.args.get('q', '').strip()
        currency = request.args.get('currency', 'all')
        if len(term) > 200:
            raise ValueError('Search is limited to 200 characters.')
        if currency not in ('all', 'USD', 'INR'):
            raise ValueError('Choose all currencies, USD or INR.')
        scoped, parameters = order_query(get_current_user())
        query = ' FROM order_invoices i JOIN ('+scoped+') o ON o.id=i.order_id WHERE 1=1'
        if term:
            pattern = '%'+term.replace('!', '!!').replace('%', '!%').replace('_', '!_')+'%'
            columns = ('i.reference', 'o.reference', 'o.po_reference', 'o.client_name', 'o.client_company')
            query += ' AND ('+' OR '.join(column+" LIKE ? ESCAPE '!'" for column in columns)+')'
            parameters.extend([pattern]*len(columns))
        if currency != 'all':
            query += ' AND i.currency=?'
            parameters.append(currency)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    connection = get_db()
    try:
        connection.execute('BEGIN')
        total = connection.execute('SELECT COUNT(*)'+query, parameters).fetchone()[0]
        rows = connection.execute(
            'SELECT i.id,i.reference,i.currency,i.created_at,i.workbook_format,'
            '(i.pdf IS NOT NULL) AS has_pdf,o.id AS order_id,o.reference AS order_reference,'
            'o.client_id,o.client_name,o.client_company,o.po_reference'+query+
            ' ORDER BY i.created_at DESC,i.id DESC LIMIT ? OFFSET ?',
            [*parameters,size,(page-1)*size]).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            base = f'/api/orders/{row["order_id"]}/invoices/{row["id"]}/download'
            item['excel_url'] = base+'?format='+row['workbook_format']
            item['pdf_url'] = base+'?format=pdf' if row['has_pdf'] else None
            results.append(item)
        return jsonify(invoices=results,total=total,page=page,pages=(total+size-1)//size)
    finally:
        connection.close()
