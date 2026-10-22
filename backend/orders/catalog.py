"""Stock hints for lookup and fresh availability checks before SKU saves."""
from decimal import Decimal, InvalidOperation
from threading import Lock
import time

from backend import database
from backend.common.skus import enforce_sku_lookup_limit

_stock={}
_lock=Lock()


def remember_stock(sku, available):
    try:
        value=Decimal(str(available))
        if not value.is_finite() or value<0:return
    except (InvalidOperation,ValueError):return
    now=time.monotonic()
    with _lock:
        for key,(_,checked) in list(_stock.items()):
            if now-checked>900:_stock.pop(key,None)
        _stock[(database.DB_PATH,str(sku).strip().casefold())]=(value,now)


def validate_stock(sku, quantity):
    validate_stock_batch([(sku, quantity)])


def lookup_stock(sku):
    from backend.quotation_tool.shopify import fetch_sku
    return fetch_sku(sku, refresh=True)


def validate_stock_batch(items, connection=None):
    """Look up every SKU afresh and report all shortages before writing rows.

    Quantities are aggregated per SKU so historical duplicate lines cannot
    each pass against the same available inventory.
    """
    required = {}
    for sku, quantity in items:
        key = sku.strip().casefold()
        name, previous = required.get(key, (sku.strip(), Decimal(0)))
        required[key] = (name, previous + Decimal(str(quantity)))
    enforce_sku_lookup_limit(len(required), connection)
    issues = []
    for sku, quantity in required.values():
        try:
            product = lookup_stock(sku)
            if not product.get('found'):
                issues.append(f'SKU {sku}: not found; availability could not be verified.')
                continue
            available = Decimal(str(product.get('qty')))
            if not available.is_finite():
                raise ValueError('Invalid stock')
            available = max(Decimal(0), available)
            remember_stock(sku, available)
            if quantity > available:
                issues.append(f'SKU {sku}: requested {quantity:g}, but only {available:g} available.'+
                              (' Out of stock.' if available == 0 else ''))
        except Exception:
            issues.append(f'SKU {sku}: stock lookup failed or availability is unknown. Try saving again.')
    if issues:
        raise ValueError('Cannot save SKU items. '+' '.join(issues))
