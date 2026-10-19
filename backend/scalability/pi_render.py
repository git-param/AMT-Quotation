"""Expensive PI rendering, called before acquiring the SQLite writer lock."""
from backend.orders import pi_exports


def files(document):
    return pi_exports.xlsx(document), pi_exports.pdf(document)


def preview_pdf(document):
    return pi_exports.pdf(document)
