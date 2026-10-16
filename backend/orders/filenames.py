"""Use the invoice reference as a portable download filename."""
import re


def invoice_filename(reference, extension):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', str(reference)).strip().rstrip('. ')
    return (stem or 'PI')+'.'+extension
