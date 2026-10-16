"""Select the PI layout while preserving legacy preview snapshots."""
from backend.orders.normal_pi.layout import WIDTHS, terms


def layout(doc):
    if doc.get('pi_format') == 'bulk':
        from backend.orders.bulk_pi.layout import layout as render
    else:
        from backend.orders.normal_pi.layout import layout as render
    return render(doc)
