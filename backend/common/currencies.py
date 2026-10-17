"""Supported invoice currencies and explicit USD-based conversion rates."""
import json
from decimal import Decimal

CURRENCIES = ('USD', 'INR', 'AED', 'GBP', 'EUR')
SYMBOLS = {'USD': '$', 'INR': '₹', 'AED': 'AED', 'GBP': '£', 'EUR': '€'}
UNITS = {'USD': ('US Dollars', 'Cents'), 'INR': ('Rupees', 'Paisa'),
         'AED': ('UAE Dirhams', 'Fils'), 'GBP': ('Pounds Sterling', 'Pence'), 'EUR': ('Euros', 'Cents')}


def currency_symbol(currency):
    return SYMBOLS[currency]


def configured_rates(connection):
    row = connection.execute("SELECT value FROM app_settings WHERE key='currency_rates'").fetchone()
    return json.loads(row[0]) if row else {}


def conversion_rates(currencies):
    from backend.database import get_db
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
            raise ValueError('Configure the '+currency+' exchange rate in Configuration before converting this PI.')
        rate = Decimal(str(value))
        if not rate.is_finite() or rate <= 0:
            raise ValueError('The '+currency+' exchange rate is unavailable. Check Configuration.')
        result[currency] = str(rate)
    return result
