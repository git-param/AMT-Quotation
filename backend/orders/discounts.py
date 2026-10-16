"""Order discount validation and deterministic cent-based allocation."""
from decimal import Decimal, ROUND_HALF_UP
from backend.enquiries.lines import number

CENT = Decimal('0.01')


def validate(value, lines):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'type', 'value', 'scope', 'line_ids', 'show_on_pi'}:
        raise ValueError('Provide the discount type, value, scope, SKU lines and PI visibility.')
    if value['type'] not in ('percent', 'amount') or value['scope'] not in ('all', 'single', 'multiple', 'total'):
        raise ValueError('Choose a valid discount type and target.')
    if type(value['show_on_pi']) is not bool:
        raise ValueError('Choose whether to show the discount on the PI.')
    ids = value['line_ids']
    if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Choose unique SKU lines for the discount.')
    if value['scope'] in ('all', 'total') and ids:
        raise ValueError('All SKU and total discounts do not accept selected lines.')
    if (value['scope'] == 'single' and len(ids) != 1) or (value['scope'] == 'multiple' and not ids):
        raise ValueError('Select the SKU lines to discount.')
    if set(ids) - {line['id'] for line in lines}:
        raise ValueError('Choose active SKU lines belonging to this order.')
    maximum = Decimal('100') if value['type'] == 'percent' else Decimal('999999999.99')
    scaled = number(value['value'], 2, maximum, True)
    if not lines:
        raise ValueError('Add SKU lines before giving a discount.')
    return {**value, 'value': format(Decimal(scaled) / 100, '.2f')}


def apply(lines, discount, convert_amount, currency):
    """Fixed SKU amounts apply per line; a total discount excludes freight/tax."""
    result = [dict(line, gross_total=line['line_total'], discount_amount='0.00') for line in lines]
    for line in result:
        line.pop('discount_label', None)
        line.pop('net_unit_price', None)
    if not discount:
        return result, Decimal(0), Decimal(0)
    selected = [line for line in result if discount['scope'] in ('all', 'total') or line['id'] in discount['line_ids']]
    if discount['scope'] in ('single', 'multiple') and len(selected) != len(discount['line_ids']):
        raise ValueError('A discounted SKU was removed. Update the discount selection before generating a PI.')
    base = sum((Decimal(line['line_total']) for line in selected), Decimal(0))
    value = Decimal(discount['value'])
    def deduction(gross):
        amount = (gross * value / 100).quantize(CENT, rounding=ROUND_HALF_UP) if discount['type'] == 'percent' else convert_amount(value)
        if amount > gross:
            raise ValueError('Discount cannot exceed the amount being discounted.')
        return amount
    total_discount = deduction(base) if discount['scope'] == 'total' else Decimal(0)
    allocated = Decimal(0)
    for index, line in enumerate(selected):
        gross = Decimal(line['line_total'])
        if discount['scope'] == 'total':
            # Visible total discounts remain in the summary; hidden ones are
            # distributed over goods so the printed lines still reconcile.
            if discount['show_on_pi']:
                continue
            cumulative = sum((Decimal(item['gross_total']) for item in selected[:index+1]), Decimal(0))
            amount = ((total_discount * cumulative / base).quantize(CENT, rounding=ROUND_HALF_UP) - allocated
                      if base else Decimal(0))
            amount = min(amount, gross, total_discount - allocated)
            if index == len(selected) - 1:
                amount = total_discount - allocated
            allocated += amount
        else:
            amount = deduction(gross)
        line['discount_amount'] = format(amount, '.2f')
        line['line_total'] = format(gross - amount, '.2f')
        if discount['show_on_pi']:
            label = discount['value'] + '%' if discount['type'] == 'percent' else currency + ' ' + format(amount, '.2f')
            line['discount_label'] = 'Discount: ' + label + ' (-' + format(amount, '.2f') + ')'
        else:
            line['net_unit_price'] = format((gross-amount)/Decimal(line['quantity']), '.8f')
    line_discount = sum((Decimal(line['discount_amount']) for line in result), Decimal(0))
    return result, total_discount if discount['scope'] == 'total' and discount['show_on_pi'] else Decimal(0), total_discount if discount['scope'] == 'total' else line_discount
