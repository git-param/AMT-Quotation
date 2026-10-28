"""Audit line-level quotations in the shared pricing database."""
import os
from backend.quotation_tool.pricing_db import connect
from backend.quotation_tool.quote_builder import _q_eff_price


def log_quote_lines(user_name, source, results):
    if not (os.environ.get('PGHOST') or os.path.isfile('/etc/aeliya/.pg.env')):
        return
    rows = []
    for item in results:
        if not item.get('found'):
            continue
        sku = str(item.get('sku') or item.get('sku_input') or '').strip()
        if sku:
            rows.append((user_name or 'Unknown', source, sku,
                         str(item.get('title') or '')[:300],
                         str(item.get('condition') or '')[:80],
                         item.get('price'), item.get('sale_price'),
                         _q_eff_price(item), str(item.get('Quantity') or '')[:20],
                         str(item.get('source') or 'shopify')[:20]))
    if not rows:
        return
    connection = connect()
    try:
        cursor = connection.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS public.quotation_quote_lines (
            id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_name TEXT, source TEXT, sku TEXT NOT NULL, title TEXT,
            condition TEXT, store_price NUMERIC(12,2), sale_price NUMERIC(12,2),
            quoted_price NUMERIC(12,2), qty_available TEXT, data_source TEXT,
            currency TEXT NOT NULL DEFAULT 'USD', found BOOLEAN NOT NULL DEFAULT TRUE)''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_qql_sku_ts
                          ON public.quotation_quote_lines (upper(sku), ts)''')
        cursor.executemany('''INSERT INTO public.quotation_quote_lines
            (user_name, source, sku, title, condition, store_price, sale_price,
             quoted_price, qty_available, data_source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', rows)
        connection.commit()
        cursor.close()
    finally:
        connection.close()
