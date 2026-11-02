"""Which links may reach a client (QUOTE_NO_EXT_LINKS_31OCT).

An allow-list of our own domains, not a block-list of one blog: Atlas and
Al Reza rows came with their own blog post and Blogger photo URLs, and the
lookup table, email and WhatsApp copies handed those straight to clients.
Any new outside site is dropped by default.
"""
import re
from urllib.parse import urlparse

PARTNER_SOURCES = ('atlas', 'alreza')
PARTNER_LINK_TEXT = 'Attached'

OWN_DOMAINS = (
    'aeliyamarinetech.com', 'aeliyamarine.com', 'auto2mation.com',
    '2c5f32-3.myshopify.com', 'aeliyamarine-tech-private-limited.myshopify.com',
    '200.141.3.14.sslip.io',
    # our eBay listings and their photos
    'ebayimg.com',
)
_EBAY = re.compile(r'(^|\.)ebay\.(com|ca|de|fr|it|es|ie|at|ch|nl|be|pl|in|ph'
                   r'|co\.uk|com\.au|com\.sg|com\.hk|com\.my)$')


def is_partner(row):
    return str((row or {}).get('source') or '') in PARTNER_SOURCES


def own_url(url):
    """The URL when it is ours (or a path on this app), else ''."""
    url = str(url or '').strip()
    if not url:
        return ''
    if url.startswith('/') and not url.startswith('//'):
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    if parsed.scheme not in ('http', 'https') or not host:
        return ''
    if any(host == d or host.endswith('.' + d) for d in OWN_DOMAINS) or _EBAY.search(host):
        return url
    return ''


def scrub_row(row):
    """Strip every outside link from a lookup row before it leaves the server."""
    if not isinstance(row, dict):
        return row
    partner = is_partner(row)
    row['url'] = '' if partner else own_url(row.get('url'))
    row['image'] = '' if partner else own_url(row.get('image'))
    if 'images' in row:
        row['images'] = [] if partner else [u for u in (own_url(u) for u in row.get('images') or []) if u]
    row['photos_attached'] = partner
    return row
