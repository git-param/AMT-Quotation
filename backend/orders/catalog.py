"""Recent provider stock used to validate order additions after SKU lookup."""
from decimal import Decimal, InvalidOperation
from threading import Lock
import time

from backend import database

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
    with _lock:cached=_stock.get((database.DB_PATH,str(sku).strip().casefold()))
    if not cached or time.monotonic()-cached[1]>900:return
    available=cached[0]
    if available<=0:raise ValueError(f'SKU {sku} cannot be added: out of stock (0 available).')
    if Decimal(str(quantity))>available:
        raise ValueError(f'SKU {sku} cannot be added: requested {quantity}, but only {available:g} available.')
