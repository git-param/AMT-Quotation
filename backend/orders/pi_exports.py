"""Stable public export interface for isolated normal and bulk PI formats."""
from backend.orders.normal_pi.exports import asset
from backend.orders.normal_pi.layout import terms


def renderer(doc):
    if doc.get('pi_format') == 'bulk':
        from backend.orders.bulk_pi import exports
    else:
        from backend.orders.normal_pi import exports
    return exports


def pdf(doc):
    return renderer(doc).pdf(doc)


def xlsx(doc):
    return renderer(doc).xlsx(doc)
