"""Supported invoice currencies and explicit USD-based conversion rates."""
import json
from datetime import date, timedelta
from decimal import Decimal

CURRENCIES = ('USD', 'INR', 'AED', 'GBP', 'EUR')
SYMBOLS = {'USD': '$', 'INR': '₹', 'AED': 'AED', 'GBP': '£', 'EUR': '€'}
UNITS = {'USD': ('US Dollars', 'Cents'), 'INR': ('Rupees', 'Paisa'),
         'AED': ('UAE Dirhams', 'Fils'), 'GBP': ('Pounds Sterling', 'Pence'), 'EUR': ('Euros', 'Cents')}


def currency_symbol(currency):
    return SYMBOLS[currency]


def rate_is_stale(connection):
    row = connection.execute("SELECT value FROM app_settings WHERE key='currency_rate_status'").fetchone()
    if not row:
        return False  # Legacy manually configured rates have no provider date.
    try:
        details = json.loads(row[0])
        if not details.get('fetched_at'):
            return False
        dates = details['dates']
        return any(not date.today() - timedelta(days=10) <= date.fromisoformat(dates[code]) <= date.today()
                   for code in CURRENCIES if code != 'USD')
    except (KeyError, TypeError, ValueError):
        return True


def configured_rates(connection, *, allow_stale=False):
    row = connection.execute("SELECT value FROM app_settings WHERE key='currency_rates'").fetchone()
    rates = json.loads(row[0]) if row else {}
    return rates if allow_stale or not rate_is_stale(connection) else {}


def conversion_rates(currencies):
    from backend.database import get_db
    from backend.common.live_rates import refresh_if_due
    connection = get_db()
    try:
        saved = configured_rates(connection)
    finally:
        connection.close()
    if any(code not in saved for code in set(currencies) - {'USD'}):
        refresh_if_due()
        connection = get_db()
        try:
            saved = configured_rates(connection)
        finally:
            connection.close()
    result = {'USD': '1'}
    for currency in set(currencies) - {'USD'}:
        value = saved.get(currency)
        if value is None and currency == 'INR':
            from backend.quotation_tool.shopify import get_inr_rate
            value = get_inr_rate()
        if value is None:
            raise ValueError('The live '+currency+' exchange rate is unavailable. Check Configuration before converting this PI.')
        rate = Decimal(str(value))
        if not rate.is_finite() or rate <= 0:
            raise ValueError('The '+currency+' exchange rate is unavailable. Check Configuration.')
        result[currency] = str(rate)
    return result
