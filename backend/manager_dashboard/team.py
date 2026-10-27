"""Team production, client-oriented PI lists and scoped lookup history."""
from datetime import date, datetime, timedelta, timezone
from functools import wraps
import json

from flask import jsonify, request, send_file
from backend.common.auth import get_current_user, get_permissions, manager_required
from backend.client_leads.discovery import integer
from backend.config import FRONTEND_DIR
from backend.database import get_db
from backend.security.audit import record_action
from backend.manager_dashboard.routes import bp
from backend.orders.service import order_query

IST = timezone(timedelta(hours=5, minutes=30))


def dashboard_required(function):
    @manager_required
    @wraps(function)
    def wrapped(*args, **kwargs):
        if get_current_user()['role'] not in ('sales_tl', 'admin', 'manager'):
            return jsonify(error='TL or admin access is required.'), 403
        return function(*args, **kwargs)
    return wrapped


def valid_date(value):
    if not isinstance(value, str):
        raise ValueError('Enter a date in YYYY-MM-DD format.')
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except ValueError:
        raise ValueError('Enter a date in YYYY-MM-DD format.') from None


def context(connection):
    user = get_current_user()
    admin = user['role'] in ('admin', 'manager')
    query = 'SELECT id,username,role,is_active FROM users'
    parameters = []
    if not admin:
        query += ' WHERE id=?'
        parameters.append(user['id'])
        if 'leads.view_team' in get_permissions(user):
            query += " OR (supervisor_user_id=? AND is_active=1 AND role IN ('user','sales_executive'))"
            parameters.append(user['id'])
    members = [dict(row) for row in connection.execute(query+' ORDER BY username COLLATE NOCASE,id', parameters)]
    selected = request.args.get('user_id', '')
    if selected:
        selected = integer(selected, 'user')
        if selected not in {row['id'] for row in members}:
            raise PermissionError('That user is outside your team.')
    start, end = request.args.get('from', ''), request.args.get('to', '')
    if start:valid_date(start)
    if end:valid_date(end)
    if start and end and start > end:
        raise ValueError('The start date must not be after the end date.')
    return user, admin, members, selected, start, end


def period(column, start, end, utc=True):
    expression = f"date({column},'+330 minutes')" if utc else f'date({column})'
    clause, values = '', []
    for value, operator in ((start, '>='), (end, '<=')):
        if value:
            clause += f' AND {expression} {operator} ?'
            values.append(value)
    return clause, values


def selected_members(members, selected):
    return [row for row in members if not selected or row['id'] == selected]


@bp.route('/tl-dashboard')
@dashboard_required
def team_page():
    return send_file(str(FRONTEND_DIR / 'manager_dashboard' / 'team.html'))


@bp.route('/api/tl-dashboard/summary')
@dashboard_required
def team_summary():
    connection = get_db()
    try:
        connection.execute('BEGIN')
        user, admin, members, selected, start, end = context(connection)
        visible = selected_members(members, selected)
        client_period, cp = period('l.created_at', start, end)
        invoice_period, ip = period('i.created_at', start, end)
        orders, op = order_query(user)
        marks = ','.join('?' for _ in visible)
        rows = connection.execute(
            'SELECT u.id,u.username,u.role,u.is_active,'
            '(SELECT COUNT(*) FROM client_leads l WHERE l.created_by=u.id AND l.deleted_at IS NULL'+client_period+') AS clients,'
            '(SELECT COUNT(*) FROM order_invoices i JOIN ('+orders+') o ON o.id=i.order_id '
            'WHERE i.created_by=u.id AND i.deleted_at IS NULL'+invoice_period+') AS pis '
            'FROM users u WHERE u.id IN ('+marks+') ORDER BY u.username COLLATE NOCASE,u.id',
            [*cp,*op,*ip,*[row['id'] for row in visible]]).fetchall()
        return jsonify(users=members,rows=[dict(row) for row in rows],
            totals={'clients':sum(row['clients'] for row in rows),'pis':sum(row['pis'] for row in rows)},
            can_cleanup=admin,scope='All users' if admin else 'Your assigned team',
            today=datetime.now(IST).date().isoformat())
    except ValueError as error:return jsonify(error=str(error)),400
    except PermissionError as error:return jsonify(error=str(error)),403
    finally:connection.close()


@bp.route('/api/tl-dashboard/pis')
@dashboard_required
def team_pis():
    connection = get_db()
    try:
        connection.execute('BEGIN')
        user, _, members, selected, start, end = context(connection)
        if not selected:raise ValueError('Select a user to see their PI list.')
        page = integer(request.args.get('page','1'),'page',1000000)
        orders, parameters = order_query(user)
        dates, values = period('i.created_at',start,end)
        query = ' FROM order_invoices i JOIN ('+orders+') o ON o.id=i.order_id WHERE i.deleted_at IS NULL AND i.created_by=?'+dates
        parameters += [selected,*values]
        total = connection.execute('SELECT COUNT(*)'+query,parameters).fetchone()[0]
        clients = connection.execute('SELECT COUNT(DISTINCT o.client_id)'+query,parameters).fetchone()[0]
        rows = connection.execute('SELECT i.id,i.reference,i.currency,i.created_at,i.workbook_format,'
            '(i.pdf IS NOT NULL) AS has_pdf,o.id AS order_id,o.reference AS order_reference,'
            'o.client_id,o.client_name,o.client_company,COUNT(*) OVER(PARTITION BY o.client_id) AS client_pis'+query+
            ' ORDER BY o.client_name COLLATE NOCASE,o.client_id,i.created_at DESC,i.id DESC LIMIT 25 OFFSET ?',
            [*parameters,(page-1)*25]).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            base = f'/api/orders/{row["order_id"]}/invoices/{row["id"]}/download'
            item.update(excel_url=base+'?format='+row['workbook_format'],pdf_url=base+'?format=pdf' if row['has_pdf'] else None)
            results.append(item)
        return jsonify(rows=results,total=total,clients=clients,page=page,pages=(total+24)//25,
            username=next(row['username'] for row in members if row['id']==selected))
    except ValueError as error:return jsonify(error=str(error)),400
    except PermissionError as error:return jsonify(error=str(error)),403
    finally:connection.close()


def lookup_base(admin, members, selected, start, end):
    dates, values = period('s.ts',start,end,utc=False)
    where = ' WHERE 1=1'
    if selected or not admin:
        names = [row['username'] for row in selected_members(members,selected)]
        where += ' AND s.user_name IN ('+','.join('?' for _ in names)+')'
        values = [*names,*values]
    return 'SELECT s.* FROM search_logs s'+where+dates, values


@bp.route('/api/tl-dashboard/lookups')
@dashboard_required
def team_lookups():
    connection = get_db()
    try:
        connection.execute('BEGIN')
        _,admin,members,selected,start,end = context(connection)
        page = integer(request.args.get('page','1'),'page',1000000)
        term = request.args.get('sku','').strip()
        if len(term)>100:raise ValueError('SKU search is limited to 100 characters.')
        base, values = lookup_base(admin,members,selected,start,end)
        # Split legacy comma-separated lookup batches without losing historical searches.
        cte = 'WITH RECURSIVE base AS ('+base+'),parts(id,user_name,ts,rest,sku) AS ('\
            "SELECT id,user_name,ts,COALESCE(skus,'')||',','' FROM base UNION ALL "\
            "SELECT id,user_name,ts,substr(rest,instr(rest,',')+1),trim(substr(rest,1,instr(rest,',')-1)) FROM parts WHERE rest!=''),"\
            "items AS (SELECT DISTINCT id,user_name,ts,upper(sku) AS sku FROM parts WHERE sku!='') "
        grouped = 'SELECT user_name,sku,COUNT(*) AS searches,MAX(ts) AS last_lookup FROM items'
        parameters = list(values)
        if term:
            grouped += " WHERE sku LIKE ? ESCAPE '!'"
            parameters.append('%'+term.replace('!','!!').replace('%','!%').replace('_','!_')+'%')
        grouped += ' GROUP BY user_name,sku'
        total = connection.execute(cte+'SELECT COUNT(*) FROM ('+grouped+')',parameters).fetchone()[0]
        rows = connection.execute(cte+grouped+' ORDER BY searches DESC,last_lookup DESC,user_name,sku LIMIT 25 OFFSET ?',
            [*parameters,(page-1)*25]).fetchall()
        requests = connection.execute('SELECT COUNT(*) FROM ('+base+')',values).fetchone()[0]
        unique = connection.execute(cte+'SELECT COUNT(DISTINCT sku) FROM items',values).fetchone()[0]
        return jsonify(rows=[dict(row) for row in rows],total=total,page=page,pages=(total+24)//25,requests=requests,unique_skus=unique)
    except ValueError as error:return jsonify(error=str(error)),400
    except PermissionError as error:return jsonify(error=str(error)),403
    finally:connection.close()


@bp.route('/api/tl-dashboard/lookup-cleanup',methods=['GET','DELETE'])
@dashboard_required
def cleanup_lookups():
    user = get_current_user()
    if user['role'] not in ('admin','manager'):
        return jsonify(error='Only admins can delete lookup history.'),403
    data = request.args if request.method=='GET' else request.get_json(silent=True)
    connection = get_db()
    try:
        if (data is None or (request.method=='DELETE' and not isinstance(data,dict))
                or 'before' not in data):raise ValueError('Choose the cutoff date first.')
        before = valid_date(data['before'])
        if before>datetime.now(IST).date():raise ValueError('Choose today or an earlier date.')
        cutoff = before.isoformat()+' 00:00:00'
        connection.execute('BEGIN IMMEDIATE' if request.method=='DELETE' else 'BEGIN')
        count = connection.execute('SELECT COUNT(*) FROM search_logs WHERE ts<?',(cutoff,)).fetchone()[0]
        if request.method=='DELETE':
            if set(data)!={'before','expected_count'} or type(data['expected_count']) is not int:
                raise ValueError('Review the matching record count before deleting.')
            if data['expected_count']!=count:
                return jsonify(error='The matching record count changed. Review the cleanup again.'),409
            connection.execute('DELETE FROM search_logs WHERE ts<?',(cutoff,))
            record_action('lookup_history_cleanup', 'search_logs', 'all',
                          {'before': before.isoformat(), 'deleted_records': count,
                           'timezone': 'Asia/Kolkata'}, actor=user,
                          connection=connection)
            connection.commit()
        return jsonify(count=count,before=before.isoformat())
    except ValueError as error:return jsonify(error=str(error)),400
    finally:connection.rollback();connection.close()
