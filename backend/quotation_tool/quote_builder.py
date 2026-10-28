"""Quotation table rendering shared with the production letter API."""

Q_MIN_DISC_PCT = 5     # under this, a gap is not presented as a discount at all
Q_MAX_DISC_PCT = 7     # over this, it is a pricing error rather than an offer
# The sales are set at whole percentages but the prices are charm priced, so
# the percentage recomputed from them lands just off: a real 5% sale on
# 121.02 -> 114.97 computes as 4.9992%, which a strict > 5 test rejects, and
# the Discount column then vanishes from the entire quote. A tenth of a
# percent of slack fixes that and is far smaller than the 1% gap between the
# 5/6/7 bands, so it cannot turn one band into another.
Q_DISC_PCT_SLACK = 0.1


def _q_disc_pct(r):
    """Exact percentage, not rounded: 5.4% must survive a > 5 test."""
    try:
        price = float(r.get('price')) if r.get('price') is not None else None
        sale = float(r.get('sale_price')) if r.get('sale_price') is not None else None
    except (TypeError, ValueError):
        return 0.0
    if price is None or sale is None or price <= 0 or not (sale < price):
        return 0.0
    return (1.0 - sale / price) * 100.0


def _q_is_real_discount(r):
    return _q_disc_pct(r) >= Q_MIN_DISC_PCT - Q_DISC_PCT_SLACK


def _q_eff_price(r):
    """Never quote above our own store price, even when the gap is too small to show."""
    try:
        price = float(r.get('price')) if r.get('price') is not None else None
        sale = float(r.get('sale_price')) if r.get('sale_price') is not None else None
    except (TypeError, ValueError):
        return None
    if price is not None and sale is not None and sale < price:
        return sale
    return price


def _q_is_partner(r):
    return str((r or {}).get('source') or '') in ('atlas', 'alreza')


def _q_esc(v):
    import html as _h
    return _h.escape('' if v is None else str(v), quote=True)


def _q_inr(v):
    """Indian digit grouping, two decimals - matches toLocaleString('en-IN')."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ''
    neg = v < 0
    v = abs(v)
    whole = int(v)
    frac = ('%.2f' % (v - whole))[2:]
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ','.join(parts) + ',' + tail
    return ('-' if neg else '') + s + '.' + frac


def _q_build_table(rows, currency, rate):
    is_inr = str(currency).upper() == 'INR'
    GREY, BLACK, WHITE = '#CCCCCC', '#000000', '#FFFFFF'
    th = ('background:%s;color:%s;font-family:Calibri,Arial,sans-serif;font-size:11pt;'
          'font-weight:bold;padding:8px 10px;border:1px solid #B8B8B8;text-align:center;'
          % (GREY, BLACK))

    def thw(w, extra=''):
        return '%swidth:%s%%;%s' % (th, w, extra)

    found = [r for r in rows if r.get('found')]
    has_discount = any(_q_is_real_discount(r) for r in found)
    pcts = [int(round(_q_disc_pct(r))) for r in found if _q_is_real_discount(r)]
    valid = [p for p in pcts if p <= Q_MAX_DISC_PCT + Q_DISC_PCT_SLACK]
    disc_max = max(valid) if valid else 0
    multi = len(valid) > 1 and len(set(valid)) > 1
    hdr_pct = ('up to %d%%' % disc_max) if (disc_max and multi) else (
        ('%d%%' % disc_max) if disc_max else '')
    price_hdr = 'Rate/Pcs (INR)' if is_inr else 'Rate/Pcs (USD)'

    out = ['<table style="border-collapse:collapse;width:100%;">\n<thead><tr>']
    out.append('<th style="%s">SKU</th>' % thw(5))
    out.append('<th style="%s">Sr No</th>' % thw(4))
    out.append('<th style="%s;text-align:left">Description</th>' % thw(20))
    out.append('<th style="%s">Condition</th>' % thw(9))
    out.append('<th style="%s">Product Details &amp; Pictures</th>' % thw(8))
    out.append('<th style="%s">Available Quantity</th>' % thw(6))
    out.append('<th style="%s">%s</th>' % (thw(8 if has_discount else 9), price_hdr))
    if has_discount:
        sub = ('<br><span style="font-size:9pt;font-weight:normal;">%s off</span>' % hdr_pct) if hdr_pct else ''
        out.append('<th style="%s">Discount%s</th>' % (thw(7), sub))
        out.append('<th style="%s">Final Price</th>' % thw(8))
    out.append('<th style="%s">Shipping</th>' % thw(6))
    out.append('<th style="%s">Lead Time</th>' % thw(8))
    out.append('</tr></thead><tbody>')

    base = 'font-family:Calibri,Arial,sans-serif;font-size:11pt;'
    tdC = base + 'color:%s;padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:center;background:%s;' % (BLACK, WHITE)
    tdL = base + 'color:%s;padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:left;background:%s;' % (BLACK, WHITE)
    tdE = base + 'color:#111827;padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:left;background:%s;' % WHITE
    tdD = base + 'color:#111827;padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:center;background:#F9F9F9;'
    tdW = ('font-family:Calibri,Arial,sans-serif;font-size:10pt;color:#92400E;padding:6px 10px;'
           'border:1px solid #E0E0E0;vertical-align:middle;text-align:center;background:#FEF3C7;')

    for i, r in enumerate(rows, 1):
        if not r.get('found'):
            out.append('<tr><td style="%s">%s</td><td style="%s">%d</td>'
                       '<td style="%s">%s</td>' % (tdC, _q_esc(r.get('sku_input')), tdC, i,
                                                   tdE, _q_esc(r.get('error') or 'SKU NOT FOUND')))
            blanks = 6 + (2 if has_discount else 0)
            out.append(('<td style="%s">&mdash;</td>' % tdC) * blanks)
            out.append('</tr>')
            continue

        def money(v):
            if v is None:
                return 'N/A'
            if is_inr and rate:
                return '&#8377;&nbsp;%s' % _q_inr(float(v) * rate)
            return '$&nbsp;%.2f' % float(v)

        rate_td = disc_td = final_td = ''
        if has_discount:
            pct = _q_disc_pct(r)
            if pct > Q_MAX_DISC_PCT + Q_DISC_PCT_SLACK:
                rate_td = '<td style="%s">%s</td>' % (tdC, money(r.get('price')))
                disc_td = '<td style="%s">&#9888; Price recheck needed</td>' % tdW
                final_td = '<td style="%s">&mdash;</td>' % tdC
            elif _q_is_real_discount(r):
                gap = float(r['price']) - float(r['sale_price'])
                rate_td = '<td style="%s">%s</td>' % (tdC, money(r.get('price')))
                disc_td = '<td style="%s"><strong>%s</strong></td>' % (tdD, money(gap))
                final_td = '<td style="%s"><strong>%s</strong></td>' % (tdC, money(r.get('sale_price')))
            else:
                pf = money(_q_eff_price(r))
                rate_td = '<td style="%s">%s</td>' % (tdC, pf)
                disc_td = '<td style="%s">&mdash;</td>' % tdD
                final_td = '<td style="%s">%s</td>' % (tdC, pf)
        else:
            rate_td = '<td style="%s">%s</td>' % (tdC, money(_q_eff_price(r)))

        Quantity = r.get('Quantity')
        qty_s = ('%s Pcs' % Quantity) if (Quantity not in (None, '')) else ''
        # Partner rows say Attached - never hand the customer the partner's link.
        if _q_is_partner(r):
            link = 'Attached'
        elif r.get('url'):
            link = ('<a href="%s" style="color:#1155CC;text-decoration:underline;">Click here</a>'
                    % _q_esc(r.get('url')))
        else:
            link = ''
        out.append('<tr>')
        out.append('<td style="%s">%s</td>' % (tdC, _q_esc(r.get('sku') or r.get('sku_input'))))
        out.append('<td style="%s">%d</td>' % (tdC, i))
        out.append('<td style="%s">%s</td>' % (tdL, _q_esc(r.get('title') or '')))
        out.append('<td style="%s">%s</td>' % (tdC, _q_esc(r.get('condition') or '')))
        out.append('<td style="%s;white-space:nowrap">%s</td>' % (tdC, link))
        out.append('<td style="%s">%s</td>' % (tdC, _q_esc(qty_s)))
        out.append(rate_td + disc_td + final_td)
        out.append('<td style="%s">Free</td>' % tdC)
        out.append('<td style="%s">Ready Stock</td>' % tdC)
        out.append('</tr>')

    ft = ('font-family:Calibri,Arial,sans-serif;font-size:10.5pt;font-weight:bold;color:%s;'
          'text-align:center;padding:7px 10px;border:1px solid #CCCCCC;background:%s;' % (BLACK, WHITE))
    spans = (4, 4, 3) if has_discount else (3, 3, 3)
    out.append('<tr><td colspan="%d" style="%s">Free worldwide shipping</td>'
               '<td colspan="%d" style="%s">30 days return/refund policy</td>'
               '<td colspan="%d" style="%s">Dispatch within 24 hours</td></tr></tbody></table>'
               % (spans[0], ft, spans[1], ft, spans[2], ft))

    tc = ([
        'Payment 100% advance via BANK TT with a purchase order.',
        'GST 18% at actual.',
        'HSN Code: 85371090.',
        'Offer subject to stock availability at the time of order confirmation.',
        'Our items are New/Surplus &amp; Used/Second Hand. We do not provide brand New Materials.',
        'Prices are valid for 7 days from the date of quotation.',
    ] if is_inr else [
        'Payment Method: Bank TT / PayPal / Stripe [100% Advance].',
        'Import duties and destination country taxes not included.',
        'HSN Code: 85371090.',
        'Offer subject to stock availability at the time of order confirmation.',
        'Our items are New/Surplus &amp; Used/Second Hand. We do not provide brand New Materials.',
        'Prices are valid for 7 days from the date of quotation.',
    ])
    tstyle = 'font-family:Calibri,Arial,sans-serif;font-size:10pt;color:#000000;'
    out.append('<p style="%smargin-top:14px;"><strong>Terms &amp; Conditions</strong></p>' % tstyle)
    out.append('<ol style="%smargin:4px 0 0 18px;padding:0;">%s</ol>'
               % (tstyle, ''.join('<li>%s</li>' % t for t in tc)))
    return ''.join(out)


def _q_strip_tags(html):
    import re as _re
    txt = _re.sub(r'<br\s*/?>', '\n', html or '')
    txt = _re.sub(r'</(p|tr|table|ol|li)>', '\n', txt)
    txt = _re.sub(r'<[^>]+>', ' ', txt)
    import html as _h
    txt = _h.unescape(txt)
    txt = _re.sub(r'[ \t]{2,}', ' ', txt)
    return _re.sub(r'\n{3,}', '\n\n', txt).strip()


