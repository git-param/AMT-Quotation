"""SKU comparison for lookup validation; retain the entered codes for display."""


def duplicate_skus(skus):
    seen = set()
    duplicates = []
    for sku in skus:
        key = sku.strip().lower()
        if key in seen:
            duplicates.append(sku.strip())
        seen.add(key)
    return duplicates
