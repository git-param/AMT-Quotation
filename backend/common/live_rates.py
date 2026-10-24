"""Scheduled USD reference rates from Frankfurter's official-source feed."""
import json
import logging
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests

from backend.database import get_db

SOURCE_NAME = 'Frankfurter (central banks and official sources)'
SOURCE_URL = 'https://frankfurter.dev/'
API_URL = 'https://api.frankfurter.dev/v2/rates'
QUOTES = ('INR', 'AED', 'GBP', 'EUR')
DEFAULT_HOURS = 24
IST = timezone(timedelta(hours=5, minutes=30))
MAX_PROVIDER_DATE_AHEAD = 1
_refresh_lock = threading.Lock()
_wake = threading.Event()
_started = False


def _setting(connection, key, default=None):
    row = connection.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def schedule(connection):
    try:
        hours = int(_setting(connection, 'currency_rate_refresh_hours', str(DEFAULT_HOURS)))
    except (TypeError, ValueError):
        hours = DEFAULT_HOURS
    return hours if 1 <= hours <= 168 else DEFAULT_HOURS


def status(connection):
    try:
        details = json.loads(_setting(connection, 'currency_rate_status', '{}'))
    except (TypeError, ValueError):
        details = {}
    return {**details, 'refresh_hours': schedule(connection), 'source': SOURCE_NAME,
            'source_url': SOURCE_URL, 'api_url': API_URL}


def _fetch():
    response = requests.get(API_URL, params={'base': 'USD', 'quotes': ','.join(QUOTES),
                                             'expand': 'providers'}, timeout=12)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError('The rate provider returned an invalid response.')
    rates, dates, providers = {}, {}, {}
    today = datetime.now(IST).date()
    for row in rows:
        if not isinstance(row, dict) or row.get('base') != 'USD' or row.get('quote') not in QUOTES:
            continue
        code = row['quote']
        if code in rates:
            raise ValueError('The rate provider returned duplicate currencies.')
        try:
            rate = Decimal(str(row['rate']))
            published = date.fromisoformat(row['date'])
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise ValueError('The rate provider returned invalid rate data.') from error
        if not rate.is_finite() or not 0 < rate <= 1000000:
            raise ValueError('The rate provider returned an invalid exchange rate.')
        if published < today - timedelta(days=10):
            raise ValueError('The rate provider returned an outdated exchange rate.')
        if published > today + timedelta(days=MAX_PROVIDER_DATE_AHEAD):
            raise ValueError('The rate provider returned a future-dated exchange rate.')
        rates[code] = str(rate)
        dates[code] = published.isoformat()
        providers[code] = row.get('providers') if isinstance(row.get('providers'), list) else []
    if set(rates) != set(QUOTES):
        raise ValueError('The rate provider did not return all supported currencies.')
    return rates, dates, providers


def refresh_if_due(force=False):
    """Fetch once per configured period; keep the last valid set on failure."""
    if not _refresh_lock.acquire(blocking=False):
        return False
    try:
        connection = get_db()
        try:
            current = status(connection)
            now = datetime.now(IST)
            last = current.get('fetched_at')
            attempted = current.get('attempted_at')
            if not force:
                if last:
                    try:
                        if now - datetime.fromisoformat(last) < timedelta(hours=current['refresh_hours']):
                            return False
                    except ValueError:
                        pass
                if attempted:
                    try:
                        if now - datetime.fromisoformat(attempted) < timedelta(minutes=30):
                            return False
                    except ValueError:
                        pass
            details = {key: current[key] for key in ('fetched_at', 'dates', 'providers') if key in current}
            details['attempted_at'] = now.isoformat()
            try:
                rates, dates, providers = _fetch()
                details.update(fetched_at=now.isoformat(), dates=dates, providers=providers)
                details.pop('last_error', None)
                with connection:
                    connection.execute("INSERT INTO app_settings(key,value) VALUES('currency_rates',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(rates),))
                    connection.execute("INSERT INTO app_settings(key,value) VALUES('currency_rate_status',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(details),))
                return True
            except (requests.RequestException, ValueError) as error:
                details['last_error'] = str(error)[:200]
                with connection:
                    connection.execute("INSERT INTO app_settings(key,value) VALUES('currency_rate_status',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(details),))
                logging.warning('Currency rate refresh failed: %s', error)
                if force:
                    raise ValueError('Could not refresh rates from Frankfurter: ' + str(error)) from error
                return False
        finally:
            connection.close()
    finally:
        _refresh_lock.release()


def wake_scheduler():
    _wake.set()


def start_scheduler():
    global _started
    if _started:
        return
    _started = True

    def run():
        while True:
            try:
                refresh_if_due()
            except Exception:
                logging.exception('Currency rate scheduler failed')
            _wake.wait(60)
            _wake.clear()

    threading.Thread(target=run, name='currency-rate-refresh', daemon=True).start()
