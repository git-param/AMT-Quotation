"""Use the invoice number as a portable PI download filename."""
import re


def invoice_filename(reference, extension):
    number = str(reference).strip().split('/', 1)[-1]
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', number).strip(' .-')
    if stem.upper().startswith('PI-'):
        stem = stem[3:]
    return 'PI-'+(stem or 'Invoice')+'.'+extension
