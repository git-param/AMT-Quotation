"""Client-authorized editable previews and idempotent native PI issuance."""
from io import BytesIO
import json
from uuid import uuid4

from flask import jsonify, request, send_file

from backend.common.auth import authenticated_required,get_current_user
from backend.database import get_db
from backend.orders.routes import bp
from backend.orders.service import details,read_order,record_revision
from backend.orders.pi_document import prepare,edit,validate_ready,validate_pdf_details,print_document,recalculate,missing_details
from backend.orders import pi_exports
from backend.orders.pi_layout import layout
from backend.orders.filenames import invoice_filename
from backend.settings import user_pi_defaults
from backend.scalability.pi_render import files as render_invoice_files


def validation_error(error):
    return jsonify(error=str(error), missing_fields=getattr(error, 'missing_fields', [])), 400


def authorized(connection,order_id):
    user=get_current_user()
    if not user:
        return None,None,(jsonify(error='Not logged in'),401)
    order=read_order(connection,user,order_id)
    if not order:
        return None,None,(jsonify(error='Order not found.'),404)
    if not order['can_edit']:
        return None,None,(jsonify(error='Client access is read-only.'),403)
    return user,order,None


def preview_row(connection,order_id,preview_id,user):
    return connection.execute('SELECT p.* FROM invoice_previews p LEFT JOIN order_invoices i ON i.id=p.issued_invoice_id '
        'WHERE p.id=? AND p.order_id=? AND p.created_by=? AND (p.issued_invoice_id IS NULL OR i.deleted_at IS NULL)',
        (preview_id,order_id,user['id'])).fetchone()


def issued_response(connection,order_id,invoice_id,doc):
    base=f'/api/orders/{order_id}/invoices/{invoice_id}/download'
    status=connection.execute('SELECT status FROM client_orders WHERE id=?',(order_id,)).fetchone()[0]
    return jsonify(id=invoice_id,reference=doc['reference'],order_status=status,
        xlsx_url=base+'?format=xlsx',pdf_url=base+'?format=pdf',
        xlsx_filename=invoice_filename(doc['reference'],'xlsx'),
        pdf_filename=invoice_filename(doc['reference'],'pdf')),201


@bp.route('/api/orders/<int:order_id>/invoices/preview',methods=['POST'])
@bp.route('/api/orders/<int:order_id>/invoices/preview/<preview_id>',methods=['PUT'])
@authenticated_required
def save_preview(order_id,preview_id=None):
    connection=get_db()
    try:
        user,order,error=authorized(connection,order_id)
        if error:return error
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise ValueError('Provide PI preview fields.')
        if order['status']=='cancelled':raise ValueError('Cancelled orders cannot generate a PI.')
        original_updated_at=order['updated_at']
        original_document_json=None
        assigned_ref=None
        if preview_id:
            row=preview_row(connection,order_id,preview_id,user)
            if not row:return jsonify(error='PI preview not found.'),404
            if row['issued_invoice_id']:
                return jsonify(error='This PI has already been issued. Open a new preview for further changes.'),409
            original_document_json=row['document_json']
            if request.args.get('for_generation')=='1':
                doc=print_document(json.loads(original_document_json),data)
                validate_ready(doc)
            else:doc=edit(json.loads(original_document_json),data)
            if doc['reference']!=order['pi_reference']:
                if order['updated_at']!=doc['source_updated_at']:
                    return jsonify(error='The order changed after this preview was opened. Open a new PI preview.'),409
        else:
            if set(data)-{'currency','usd_inr_rate','bulk_description'}:raise ValueError('Invalid PI preview fields.')
            if not order['pi_reference']:
                prefix=user_pi_defaults(connection,order['created_by'])['pi_prefix']
                if prefix:
                    assigned_ref=prefix+'/'
                    order=dict(order)
                    order['pi_reference']=assigned_ref
            doc=prepare(details(connection,order),user,data.get('currency'),data.get('usd_inr_rate'),data.get('bulk_description'))
            preview_id=uuid4().hex
        # Validate the draft here; render only when the PDF is actually requested.
        missing = missing_details(doc)
        if not missing:
            validate_pdf_details(doc)
    except ValueError as error:
        return validation_error(error)
    finally:
        connection.close()

    connection=get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user,order,error=authorized(connection,order_id)
        if error:return error
        if order['status']=='cancelled':raise ValueError('Cancelled orders cannot generate a PI.')
        if order['updated_at']!=original_updated_at:
            return jsonify(error='The order changed while the PI preview was prepared. Open a new PI preview.'),409
        if original_document_json is not None:
            row=preview_row(connection,order_id,preview_id,user)
            if not row:return jsonify(error='PI preview not found.'),404
            if row['issued_invoice_id']:
                return jsonify(error='This PI has already been issued. Open a new preview for further changes.'),409
            if row['document_json']!=original_document_json:
                return jsonify(error='The PI preview changed while it was prepared. Review the latest preview and try again.'),409
            if doc['reference']!=order['pi_reference']:
                connection.execute("UPDATE client_orders SET pi_reference=?,updated_by=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (doc['reference'],user['id'],order_id))
                doc['source_updated_at']=connection.execute('SELECT updated_at FROM client_orders WHERE id=?',(order_id,)).fetchone()[0]
                doc['source_state']['order']['pi_reference']=doc['reference']
                record_revision(connection,order_id,user,'edit')
            connection.execute("UPDATE invoice_previews SET document_json=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                               (json.dumps(doc),preview_id))
        else:
            if assigned_ref:
                connection.execute("UPDATE client_orders SET pi_reference=?,updated_by=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                    (assigned_ref,user['id'],order_id))
                doc['source_updated_at']=connection.execute('SELECT updated_at FROM client_orders WHERE id=?',(order_id,)).fetchone()[0]
                doc['source_state']['order']['updated_at']=doc['source_updated_at']
                record_revision(connection,order_id,user,'edit')
            connection.execute('INSERT INTO invoice_previews(id,order_id,created_by,document_json) VALUES(?,?,?,?)',
                               (preview_id,order_id,user['id'],json.dumps(doc)))
        connection.commit()
        return jsonify(preview_id=preview_id,document=doc,layout=layout(doc),
            missing_fields=missing, pdf_url=f'/api/orders/{order_id}/invoices/preview/{preview_id}/pdf'),200 if request.method=='PUT' else 201
    except ValueError as error:
        return validation_error(error)
    finally:
        connection.rollback();connection.close()


@bp.route('/api/orders/<int:order_id>/invoices/preview/<preview_id>/pdf')
@authenticated_required
def preview_pdf(order_id,preview_id):
    connection=get_db()
    try:
        user,order,error=authorized(connection,order_id)
        if error:return error
        row=preview_row(connection,order_id,preview_id,user)
        if not row:return jsonify(error='PI preview not found.'),404
        doc=json.loads(row['document_json'])
    except ValueError as error:return validation_error(error)
    finally:connection.close()
    try:
        validate_pdf_details(doc)
        return send_file(BytesIO(pi_exports.pdf(doc)),mimetype='application/pdf',
                         download_name=invoice_filename(doc['reference'],'pdf'),max_age=0)
    except ValueError as error:return validation_error(error)


@bp.route('/api/orders/<int:order_id>/invoices/preview/<preview_id>/print',methods=['POST'])
@authenticated_required
def print_preview(order_id,preview_id):
    connection=get_db()
    try:
        user,order,error=authorized(connection,order_id)
        if error:return error
        row=preview_row(connection,order_id,preview_id,user)
        if not row:return jsonify(error='PI preview not found.'),404
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='Provide PI preview fields.'),400
        doc=print_document(json.loads(row['document_json']),data)
    except ValueError as error:return validation_error(error)
    finally:connection.close()
    try:
        validate_pdf_details(doc)
        return send_file(BytesIO(pi_exports.pdf(doc)),mimetype='application/pdf',download_name=invoice_filename(doc['reference'],'pdf'),max_age=0)
    except ValueError as error:return validation_error(error)


@bp.route('/api/orders/<int:order_id>/invoices/preview/<preview_id>/calculate',methods=['POST'])
@authenticated_required
def calculate_preview(order_id,preview_id):
    connection=get_db()
    try:
        user,order,error=authorized(connection,order_id)
        if error:return error
        row=preview_row(connection,order_id,preview_id,user)
        if not row:return jsonify(error='PI preview not found.'),404
        if row['issued_invoice_id']:return jsonify(error='This PI has already been issued.'),409
        doc=recalculate(json.loads(row['document_json']),request.get_json(silent=True))
        totals=doc['totals']
        if doc.get('pi_format')=='bulk':
            from backend.orders.bulk_pi.layout import annexure_words, quantity_summary
            totals={**totals,'annexure_amount_in_words':annexure_words(doc),
                    'annexure_quantity':quantity_summary(doc)}
        return jsonify(totals=totals)
    except ValueError as error:return validation_error(error)
    finally:connection.close()


@bp.route('/api/orders/<int:order_id>/invoices/issue',methods=['POST'])
@authenticated_required
def issue_preview(order_id):
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or set(data)!={'preview_id'} or not isinstance(data['preview_id'],str):
        return validation_error(ValueError('Choose an existing PI preview.'))
    preview_id=data['preview_id']
    # Reads and rendering do not occupy SQLite's single writer slot.
    connection=get_db()
    try:
        user,order,error=authorized(connection,order_id)
        if error:return error
        row=preview_row(connection,order_id,preview_id,user)
        if not row:return jsonify(error='PI preview not found.'),404
        if order['status']=='cancelled':raise ValueError('Cancelled orders cannot generate a PI.')
        invoice_id=row['issued_invoice_id']
        doc=json.loads(row['document_json'])
        if invoice_id:return issued_response(connection,order_id,invoice_id,doc)
        if order['updated_at']!=doc['source_updated_at']:
            return jsonify(error='The order changed after this preview was opened. Open a new PI preview.'),409
        validate_ready(doc)
        document_json=row['document_json']
    except ValueError as error:return validation_error(error)
    finally:connection.close()

    try:
        workbook,pdf=render_invoice_files(doc)
    except ValueError as error:
        return validation_error(error)
    connection=get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user,order,error=authorized(connection,order_id)
        if error:return error
        row=preview_row(connection,order_id,preview_id,user)
        if not row:return jsonify(error='PI preview not found.'),404
        if order['status']=='cancelled':raise ValueError('Cancelled orders cannot generate a PI.')
        invoice_id=row['issued_invoice_id']
        if not invoice_id:
            if row['document_json']!=document_json or order['updated_at']!=doc['source_updated_at']:
                return jsonify(error='The order or PI preview changed while the files were prepared. Review the latest preview and try again.'),409
            # The approved snapshot and both files commit atomically.
            cursor=connection.execute('INSERT INTO order_invoices(order_id,reference,currency,snapshot_json,workbook,created_by,workbook_format,pdf) '
                "VALUES(?,?,?,?,?,?,'xlsx',?)",(order_id,doc['reference'],doc['currency'],document_json,workbook,user['id'],pdf))
            invoice_id=cursor.lastrowid
            connection.execute('UPDATE invoice_previews SET issued_invoice_id=? WHERE id=?',(invoice_id,row['id']))
            connection.execute("UPDATE client_orders SET pi_reference=?,pi_date=?,status='completed',updated_by=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (doc['reference'],doc['date'],user['id'],order_id))
            record_revision(connection,order_id,user,'edit')
            connection.execute('INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) VALUES(?,?,?,?,?,?)',
                (user['id'],user['username'],'pi_generate','order',str(order_id),json.dumps({'invoice_id':invoice_id,
                 'reference':doc['reference'],'currency':doc['currency'],'preview_id':row['id'],'formats':['xlsx','pdf']})))
        connection.commit()
        return issued_response(connection,order_id,invoice_id,doc)
    except ValueError as error:return validation_error(error)
    finally:connection.rollback();connection.close()
