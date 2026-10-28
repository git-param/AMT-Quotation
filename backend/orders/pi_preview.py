"""Client-authorized editable previews and idempotent native PI issuance."""
from io import BytesIO
import json
import sqlite3
from uuid import uuid4

from flask import jsonify, request, send_file

from backend.common.auth import authenticated_required,get_current_user
from backend.database import get_db
from backend.orders.routes import bp
from backend.orders.service import details,read_order,record_revision
from backend.orders.service import save_delivery,order_line
from backend.orders.parties import text_delivery
from backend.orders.pi_document import prepare,edit,validate_ready,validate_pdf_details,print_document,recalculate,missing_details
from backend.orders import pi_exports
from backend.orders.pi_layout import layout
from backend.orders.filenames import invoice_filename
from backend.settings import allocate_pi_reference, next_pi_reference, pi_number_last_used
from backend.scalability.pi_generation import serialized_generation
from backend.security.audit import record_action
from backend.scalability.pi_render import files as render_invoice_files


def validation_error(error):
    return jsonify(error=str(error), missing_fields=getattr(error, 'missing_fields', [])), 400


class PreviewConflict(ValueError):
    pass


def authorized(connection,order_id):
    user=get_current_user()
    if not user:
        return None,None,(jsonify(error='Not logged in'),401)
    order=read_order(connection,user,order_id)
    if not order:
        return None,None,(jsonify(error='PI not found.'),404)
    if not order['can_edit']:
        return None,None,(jsonify(error='Client access is read-only.'),403)
    return user,order,None


def can_edit_pi_reference(user):
    """Generation confirms PI identity; preview edits cannot change it."""
    return False


def preview_layout(document,user):
    model=layout(document)
    allowed=can_edit_pi_reference(user)
    from backend.orders.policy import can_edit_catalog
    locked={i for i,line in enumerate(document['totals']['lines']) if not line.get('manual_entry') and not can_edit_catalog(user)}
    for section in model['sections']:
        for row in section['rows']:
            for cell in row:
                field=cell.get('field') or ''
                if field.startswith('lines.'):
                    parts=field.split('.')
                    if int(parts[1]) in locked and parts[-1] not in ('quantity','uom'):cell['readonly']=True
                if cell.get('field')=='order.pi_reference':
                    cell['readonly']=not allowed
    return model


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


def persist_order_edits(connection, order_id, user, order, previous, doc):
    """Copy only edited, order-backed preview fields into the order transaction."""
    order_changes = {key:doc['order'][key] for key in (
        'po_reference','pi_reference','payment_terms','delivery_terms','destination',
        'delivery_time','dispatch_method','notes')
        if doc['order'][key] != previous['order'][key] and key!='pi_reference'}
    if doc['date'] != previous['date']:
        if not doc.get('source_invoice_id') and connection.execute(
                'SELECT 1 FROM order_invoices WHERE order_id=? AND deleted_at IS NULL',
                              (order_id,)).fetchone():
            raise ValueError('Generated PI dates cannot be edited.')
        order_changes['pi_date'] = doc['date']
    if doc['totals']['shipping'] != previous['totals']['shipping']:
        from backend.enquiries.lines import number
        from decimal import Decimal
        order_changes['shipping_minor'] = number(doc['totals']['shipping'],2,Decimal('999999999.99'))
    if doc['totals'].get('bank_charges', '0.00') != previous['totals'].get('bank_charges', '0.00'):
        from backend.enquiries.lines import number
        from decimal import Decimal
        order_changes['bank_charges_minor'] = number(doc['totals']['bank_charges'],2,Decimal('999999999.99'))
    if ('shipping_minor' in order_changes or 'bank_charges_minor' in order_changes):
        if order['currency'] != doc['currency']:
            order_changes['currency'] = doc['currency']
            discount = doc['order'].get('discount')
            if discount and discount['type'] == 'amount':
                from backend.orders.invoices import money
                from decimal import Decimal
                rates = doc['source_conversion'].get('exchange_rates')
                amount = Decimal(discount['value'])
                if rates:
                    amount = amount / Decimal(rates[order['currency']]) * Decimal(rates[doc['currency']])
                else:
                    rate = Decimal(doc['source_conversion']['usd_inr_rate'])
                    amount = amount * rate if order['currency'] == 'USD' else amount / rate
                discount = {**discount,'value':format(money(amount),'.2f')}
                order_changes['discount_json'] = json.dumps(discount)
                doc['order']['discount'] = discount
            doc['order']['currency'] = doc['currency']
    if order_changes.get('destination','').strip().upper() == 'INDIA' and doc['currency'] == 'INR':
        order_changes['currency'] = 'INR'
        doc['order']['currency'] = 'INR'

    delivery_changed = doc['delivery'] != previous['delivery']
    old_lines = {line['id']:line for line in previous['totals']['lines']}
    line_changes = []
    for line in doc['totals']['lines']:
        old = old_lines[line['id']]
        changed = {key for key in ('sku','description','hsn_code','item_condition','uom','quantity','unit_price')
                   if line[key] != old[key]}
        if changed:
            line_changes.append((line,changed))
    if not order_changes and not delivery_changed and not line_changes:
        return False
    if order['updated_at'] != previous['source_updated_at']:
        raise PreviewConflict('The order changed after this preview was opened. Open a new PI preview.')

    if line_changes:
        skus = [line['sku'].strip().casefold() for line in doc['totals']['lines']]
        if len(skus) != len(set(skus)):
            raise ValueError('Keep each SKU only once in the order.')
        for line,changed in line_changes:
            row = connection.execute('SELECT * FROM order_sku_lines WHERE id=? AND order_id=? AND is_active=1',
                                     (line['id'],order_id)).fetchone()
            if not row:
                raise PreviewConflict('An order item changed after this preview was opened. Open a new PI preview.')
            line_data = {key:line[key] for key in changed}
            values = order_line({**line_data,
                **({'currency':doc['currency']} if 'unit_price' in changed else {})},row)
            columns = {'quantity':'quantity_milli','unit_price':'unit_price_minor',
                       'catalog_original_price':'catalog_original_price_minor'}
            updates = {columns.get(key,key):values[columns.get(key,key)] for key in changed}
            if 'unit_price' in changed:
                updates['currency'] = values['currency']
            connection.execute('UPDATE order_sku_lines SET '+', '.join(key+'=?' for key in updates)+
                ",updated_by=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                [*updates.values(),user['id'],line['id']])
    if delivery_changed:
        snapshot = text_delivery(doc['delivery'],previous['delivery'],doc['order']['destination'],True)
        save_delivery(connection,order_id,snapshot,user['id'])
    if order_changes:
        connection.execute('UPDATE client_orders SET '+', '.join(key+'=?' for key in order_changes)+
            ",updated_by=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            [*order_changes.values(),user['id'],order_id])
    else:
        connection.execute("UPDATE client_orders SET updated_by=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                           (user['id'],order_id))
    record_revision(connection,order_id,user,'edit')
    doc['source_state'] = details(connection,read_order(connection,user,order_id))
    doc['source_updated_at'] = doc['source_state']['order']['updated_at']
    doc['order']['pi_date'] = doc['source_state']['order']['pi_date']
    return True


@bp.route('/api/orders/<int:order_id>/invoices/<int:invoice_id>/edit-preview', methods=['POST'])
@authenticated_required
def edit_invoice_preview(order_id, invoice_id):
    connection = get_db()
    try:
        user, order, error = authorized(connection, order_id)
        if error:
            return error
        invoice = connection.execute(
            'SELECT snapshot_json FROM order_invoices '
            'WHERE id=? AND order_id=? AND deleted_at IS NULL',
            (invoice_id, order_id)).fetchone()
        if not invoice:
            return jsonify(error='PI not found.'), 404
        document = json.loads(invoice['snapshot_json'])
        if not isinstance(document, dict) or not document.get('totals'):
            return jsonify(error='This saved PI format cannot be edited.'), 409
        if not document.get('source_state') and isinstance(document.get('state'), dict):
            document = prepare(document['state'], user, invoice['currency'],
                               document['totals'].get('usd_inr_rate'))
            document['date'] = json.loads(invoice['snapshot_json']).get('date', document['date'])
        if not document.get('source_state'):
            return jsonify(error='This saved PI format cannot be edited.'), 409
        document['source_invoice_id'] = invoice_id
        document['source_updated_at'] = order['updated_at']
        document['source_state'] = details(connection, order)
        document['source_state']['order']['updated_at'] = order['updated_at']
        preview_id = uuid4().hex
        connection.execute(
            'INSERT INTO invoice_previews(id,order_id,created_by,document_json) VALUES(?,?,?,?)',
            (preview_id, order_id, user['id'], json.dumps(document)))
        connection.commit()
        return jsonify(preview_id=preview_id, document=document,
                       layout=preview_layout(document, user),
                       missing_fields=missing_details(document),
                       pdf_url=f'/api/orders/{order_id}/invoices/preview/{preview_id}/pdf')
    except (ValueError, json.JSONDecodeError) as error:
        return validation_error(error)
    finally:
        connection.rollback()
        connection.close()


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
        if preview_id:
            row=preview_row(connection,order_id,preview_id,user)
            if not row:return jsonify(error='PI preview not found.'),404
            if row['issued_invoice_id']:
                return jsonify(error='This PI has already been issued. Open a new preview for further changes.'),409
            original_document_json=row['document_json']
            previous_doc=json.loads(original_document_json)
            from backend.orders.policy import check_preview_edits
            check_preview_edits(previous_doc,data,user)
            for_generation=request.args.get('for_generation')=='1'
            if for_generation:
                doc=print_document(previous_doc,data,allow_pi_reference=can_edit_pi_reference(user))
                validate_ready(doc)
            else:doc=edit(previous_doc,data,allow_pi_reference=can_edit_pi_reference(user))
            if doc['reference']!=order['pi_reference']:
                if order['updated_at']!=doc['source_updated_at']:
                    return jsonify(error='The order changed after this preview was opened. Open a new PI preview.'),409
        else:
            if set(data)-{'currency','usd_inr_rate','bulk_description'}:raise ValueError('Invalid PI preview fields.')
            original_reference=order['pi_reference']
            order=dict(order)
            order['pi_reference']='PI-PENDING'
            doc=prepare(details(connection,order),user,data.get('currency'),data.get('usd_inr_rate'),data.get('bulk_description'))
            doc['reference_pending']=True
            doc['source_state']['order']['pi_reference']=original_reference
            preview_id=uuid4().hex
        # Validate the draft here; render only when the PDF is actually requested.
        missing = missing_details(doc)
        if not missing:
            validate_pdf_details(doc)
    except PreviewConflict as error:
        return jsonify(error=str(error)),409
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
            if not for_generation:
                persist_order_edits(connection,order_id,user,order,previous_doc,doc)
            connection.execute("UPDATE invoice_previews SET document_json=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                               (json.dumps(doc),preview_id))
        else:
            connection.execute('INSERT INTO invoice_previews(id,order_id,created_by,document_json) VALUES(?,?,?,?)',
                               (preview_id,order_id,user['id'],json.dumps(doc)))
        connection.commit()
        return jsonify(preview_id=preview_id,document=doc,layout=preview_layout(doc,user),
            missing_fields=missing, pdf_url=f'/api/orders/{order_id}/invoices/preview/{preview_id}/pdf'),200 if request.method=='PUT' else 201
    except PreviewConflict as error:
        return jsonify(error=str(error)),409
    except ValueError as error:
        return validation_error(error)
    except sqlite3.IntegrityError:
        return jsonify(error='Conflicting order or item details.'),409
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
        from backend.orders.policy import check_preview_edits
        check_preview_edits(json.loads(row['document_json']),data,user)
        doc=print_document(json.loads(row['document_json']),data,allow_pi_reference=can_edit_pi_reference(user))
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
        from backend.orders.policy import check_preview_edits
        check_preview_edits(json.loads(row['document_json']),request.get_json(silent=True),user)
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
@serialized_generation
def issue_preview(order_id):
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or set(data)!={'preview_id'} or not isinstance(data['preview_id'],str):
        return validation_error(ValueError('Choose an existing PI preview.'))
    preview_id=data['preview_id']
    connection=get_db()
    try:
        user,order,error=authorized(connection,order_id)
        if error:return error
        row=preview_row(connection,order_id,preview_id,user)
        if not row:return jsonify(error='PI preview not found.'),404
        if order['status']=='cancelled':raise ValueError('Cancelled orders cannot generate a PI.')
        doc=json.loads(row['document_json'])
        if row['issued_invoice_id']:
            return issued_response(connection,order_id,row['issued_invoice_id'],doc)
        if order['updated_at']!=doc['source_updated_at']:
            return jsonify(error='The order changed after this preview was opened. Open a new PI preview.'),409
        original_document_json=row['document_json']
        source=doc.get('source_invoice_id')
        counter=pi_number_last_used(connection)
        if source:
            invoice=connection.execute('SELECT reference FROM order_invoices WHERE id=? AND order_id=? AND deleted_at IS NULL',(source,order_id)).fetchone()
            if not invoice:return jsonify(error='The saved PI is no longer available.'),409
            reference=invoice['reference']
        else:
            reference=next_pi_reference(connection,user['id'])
        doc['reference']=reference
        doc['reference_pending']=False
        doc['order']['pi_reference']=reference
        doc['source_state']['order']['pi_reference']=reference
        from backend.orders.policy import check_document_discount
        check_document_discount(doc)
        validate_ready(doc)
    except ValueError as error:return validation_error(error)
    finally:connection.close()

    # The process-shared generation gate stays held, but rendering does not
    # block unrelated database writes. No counter change exists to roll back.
    try:
        workbook,pdf=render_invoice_files(doc)
    except ValueError as error:return validation_error(error)

    connection=get_db()
    try:
        connection.execute('BEGIN IMMEDIATE')
        user,order,error=authorized(connection,order_id)
        if error:return error
        row=preview_row(connection,order_id,preview_id,user)
        if not row:return jsonify(error='PI preview not found.'),404
        if order['status']=='cancelled':raise ValueError('Cancelled orders cannot generate a PI.')
        if row['issued_invoice_id']:
            return issued_response(connection,order_id,row['issued_invoice_id'],json.loads(row['document_json']))
        if row['document_json']!=original_document_json or order['updated_at']!=doc['source_updated_at']:
            return jsonify(error='The order or PI preview changed while the files were prepared. Review the latest preview and try again.'),409
        check_document_discount(doc)
        if source:
            invoice=connection.execute('SELECT reference FROM order_invoices WHERE id=? AND order_id=? AND deleted_at IS NULL',(source,order_id)).fetchone()
            if not invoice or invoice['reference']!=reference:
                return jsonify(error='The saved PI changed while the files were prepared. Open a new preview.'),409
        else:
            if pi_number_last_used(connection)!=counter or next_pi_reference(connection,user['id'])!=reference:
                return jsonify(error='PI numbering configuration changed during generation. Generate the PI again.'),409
            if connection.execute('SELECT 1 FROM order_invoices WHERE reference=?',(reference,)).fetchone():
                return jsonify(error='This PI number already exists. Ask an admin to check the PI number sequence.'),409
            confirmed=allocate_pi_reference(connection,user['id'])
            if confirmed!=reference:raise ValueError('The PI number changed. Generate the PI again.')
        document_json=json.dumps(doc)
        if source:
            connection.execute('UPDATE order_invoices SET reference=?,currency=?,snapshot_json=?,workbook=?,pdf=? WHERE id=?',
                (reference,doc['currency'],document_json,workbook,pdf,source))
            invoice_id=source
        else:
            cursor=connection.execute('INSERT INTO order_invoices(order_id,reference,currency,snapshot_json,workbook,created_by,workbook_format,pdf) '
                "VALUES(?,?,?,?,?,?,'xlsx',?)",(order_id,reference,doc['currency'],document_json,workbook,user['id'],pdf))
            invoice_id=cursor.lastrowid
        connection.execute('UPDATE invoice_previews SET issued_invoice_id=?,document_json=? WHERE id=?',(invoice_id,document_json,row['id']))
        connection.execute("UPDATE client_orders SET pi_reference=?,pi_date=?,status='completed',updated_by=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (reference,doc['date'],user['id'],order_id))
        record_revision(connection,order_id,user,'edit')
        record_action('pi_update' if source else 'pi_generate','order',order_id,
            {'invoice_id':invoice_id,'reference':reference,'currency':doc['currency'],
             'preview_id':row['id'],'formats':['xlsx','pdf']},actor=user,connection=connection)
        connection.commit()
        return issued_response(connection,order_id,invoice_id,doc)
    except ValueError as error:return validation_error(error)
    except sqlite3.IntegrityError:
        return jsonify(error='Another PI already uses that PI number.'),409
    finally:connection.rollback();connection.close()
