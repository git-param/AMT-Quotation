"""SKU comparison for lookup validation; retain the entered codes for display."""

from backend.database import get_db

DEFAULT_SKU_LOOKUP_LIMIT = 50
MAX_SKU_LOOKUP_LIMIT = 500


def sku_lookup_limit(connection=None):
    """Read the admin's per-request limit without caching a stale value."""
    owned = connection is None
    if owned:
        connection = get_db()
    try:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'sku_lookup_limit'"
        ).fetchone()
        try:
            value = int(row[0]) if row else DEFAULT_SKU_LOOKUP_LIMIT
        except (TypeError, ValueError):
            value = DEFAULT_SKU_LOOKUP_LIMIT
        return value if 1 <= value <= MAX_SKU_LOOKUP_LIMIT else DEFAULT_SKU_LOOKUP_LIMIT
    finally:
        if owned:
            connection.close()


def enforce_sku_lookup_limit(count, connection=None):
    limit = sku_lookup_limit(connection)
    if count > limit:
        raise ValueError(f'You can look up at most {limit} SKU{"s" if limit != 1 else ""} at a time.')


def duplicate_skus(skus):
    seen = set()
    duplicates = []
    for sku in skus:
        key = sku.strip().lower()
        if key in seen:
            duplicates.append(sku.strip())
        seen.add(key)
    return duplicates
