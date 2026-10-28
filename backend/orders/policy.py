"""Server-owned SKU editing and discount limits shared by order and PI paths."""
from decimal import Decimal, ROUND_HALF_UP

from flask import g, has_request_context, request

from backend.database import get_db


class DiscountLimitError(ValueError):
    pass


def can_edit_catalog(user):
    return bool(user and user['role'] in ('admin', 'manager', 'sales_tl'))


def maximum_discount(connection=None):
    own = connection is None
    db = connection or get_db()
    try:
        row = db.execute("SELECT value FROM app_settings WHERE key='max_pi_discount_percent'").fetchone()
        return Decimal(row[0]) if row else Decimal('0')
    finally:
        if own:
            db.close()


def check_reduction(base, net, *, sku='', connection=None):
    if not has_request_context():
        return
    base, net = Decimal(base), Decimal(net)
    limit = maximum_discount(connection)
    allowed = (base * limit / 100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    reduction = base - net
    if reduction > allowed:
        g.discount_policy_violation = {
            'sku': sku, 'base_amount': str(base), 'attempted_net_amount': str(net),
            'reduction': str(reduction), 'maximum_percent': str(limit),
            'endpoint': request.path,
        }
        raise DiscountLimitError(f'Discount exceeds the administrator limit of {limit}%'
                                 + (f' for SKU {sku}.' if sku else '.'))


def check_percent(value, connection=None):
    if has_request_context() and Decimal(value) > maximum_discount(connection):
        # Use an exact percentage comparison even when the monetary base rounds to cents.
        limit = maximum_discount(connection)
        g.discount_policy_violation = {'attempted_percent': str(value),
            'maximum_percent': str(limit), 'endpoint': request.path}
        raise DiscountLimitError(f'Discount exceeds the administrator limit of {limit}%.')


def check_line_edit(values, existing, user, connection=None):
    old = dict(existing)
    if values.get('manual_entry', old.get('manual_entry', 0)) != old.get('manual_entry', 0):
        raise ValueError('The SKU source cannot be changed after creation.')
    for key in ('catalog_original_price_minor', 'catalog_sale_price_minor'):
        if key in values and values[key] != old.get(key):
            raise ValueError('Catalog price snapshots cannot be edited.')
    if 'unit_price_minor' in values or 'currency' in values:
        base = Decimal(old.get('policy_price_minor') if old.get('policy_price_minor') is not None
                       else old['unit_price_minor']) / 100
        source = old.get('policy_currency') or old['currency']
        target = values.get('currency', old['currency'])
        if source != target:
            from backend.common.currencies import configured_rates
            db=connection or get_db()
            try:rates = {'USD': Decimal(1), **configured_rates(db)}
            finally:
                if connection is None:db.close()
            if not rates.get(source) or not rates.get(target):
                raise ValueError('Configure current exchange rates before changing item currency.')
            base = (base / Decimal(str(rates[source])) * Decimal(str(rates[target]))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        check_reduction(base, Decimal(values.get('unit_price_minor',old['unit_price_minor']))/100,
                        sku=old['sku'], connection=connection)

    if not old.get('manual_entry') and not can_edit_catalog(user):
        fields = ('sku', 'description', 'unit_price_minor', 'currency', 'hsn_code', 'item_condition')
        if any(key in values and values[key] != old.get(key) for key in fields):
            raise ValueError('Only Admins and Sales TLs can edit lookup SKU details. You can change quantity and UoM.')


def check_preview_edits(document, edits, user):
    """Check unsaved calculate/print changes too; never trust client source flags."""
    if not isinstance(edits, dict) or not isinstance(edits.get('lines'), list):
        return
    stored = {line['id']: line for line in document['source_state']['lines']}
    displayed = {line['id']: line for line in document['totals']['lines']}
    for change in edits['lines']:
        if not isinstance(change, dict) or change.get('id') not in displayed:
            continue
        original = displayed[change['id']]
        source = stored[change['id']]
        if 'unit_price' in change:
            try:
                net = Decimal(str(change['unit_price']))
                base = Decimal(str(original.get('policy_base_price',original['unit_price'])))
                if net.is_finite():
                    check_reduction(base, net, sku=original['sku'])
            except (ArithmeticError, TypeError):
                pass

        if not source.get('manual_entry') and not can_edit_catalog(user):
            for key in ('sku','description','unit_price','hsn_code','item_condition'):
                same=str(change.get(key,original[key]))==str(original[key])
                if key=='unit_price' and key in change:
                    try:same=Decimal(str(change[key]))==Decimal(str(original[key]))
                    except ArithmeticError:same=False
                if key in change and not same:
                    raise ValueError('Only Admins and Sales TLs can edit lookup SKU details. You can change quantity and UoM.')


def check_document_discount(document):
    discount=document['order'].get('discount')
    if discount and discount['type']=='percent':check_percent(discount['value'])
    lines=document['totals']['lines']
    for line in lines:
        base=Decimal(str(line.get('policy_base_price',line['unit_price'])))*Decimal(line['quantity'])
        check_reduction(base,Decimal(line['line_total']),sku=line['sku'])
    summary=Decimal(document['totals'].get('summary_discount','0'))
    if summary:
        base=sum((Decimal(str(line.get('policy_base_price',line['unit_price'])))*Decimal(line['quantity']) for line in lines),Decimal(0))
        net=sum((Decimal(line['line_total']) for line in lines),Decimal(0))-summary
        check_reduction(base,net)
