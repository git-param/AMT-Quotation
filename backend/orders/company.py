"""Company-owned PI settings and legacy workbook compatibility import."""
from copy import deepcopy
import argparse
import json
from io import BytesIO
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from backend.database import get_db
from backend.orders.company_profile import COMPANY_PI_PROFILE


def get_profile(connection):
    profile = deepcopy(COMPANY_PI_PROFILE)
    for currency in ('AED', 'GBP', 'EUR'):
        for key in ('payment_terms', 'tax_rates', 'terms'):
            profile[key].setdefault(currency, profile[key]['USD'])
    return profile


def import_legacy(connection):
    """Copy configured company information once; never used by native exports."""
    from backend.orders.invoices import Q, template, company_payment_terms
    profile = {'payment_terms': {}, 'tax_rates': {}, 'terms': {}}
    for currency in ('USD', 'INR'):
        raw, sheet, first, tax = template(currency)
        with ZipFile(BytesIO(raw)) as workbook:
            strings = [''.join(node.itertext()) for node in ET.fromstring(
                workbook.read('xl/sharedStrings.xml')).findall(Q+'si')]
        def value(ref):
            cell = sheet.find('.//'+Q+f'c[@r="{ref}"]')
            if cell is None:
                return ''
            v = cell.find(Q+'v')
            if cell.get('t') == 's' and v is not None:
                return strings[int(v.text)]
            return ''.join(cell.find(Q+'is').itertext()) if cell.get('t') == 'inlineStr' else ''
        if currency == 'USD':
            profile['seller'] = [value('A'+str(row)) for row in range(5,11) if value('A'+str(row))]
            profile['bank'] = [value('A'+str(row)) for row in range(first+5,first+9) if value('A'+str(row))]
            profile['bank_charges'] = value('A'+str(first+9))
        start = 35 if currency == 'USD' else 36
        profile['terms'][currency] = [value('A'+str(row)) for row in range(start,start+6) if value('A'+str(row))]
        profile['payment_terms'][currency] = company_payment_terms(raw,sheet)
        profile['tax_rates'][currency] = str(tax)
    if not profile.get('seller') or not profile.get('bank'):
        raise ValueError('Company seller and bank configuration is incomplete.')
    connection.execute('INSERT INTO company_pi_settings(id,profile_json) VALUES(1,?) '
        "ON CONFLICT(id) DO UPDATE SET profile_json=excluded.profile_json,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (json.dumps(profile),))
    connection.execute("INSERT INTO audit_logs(action,entity_type,entity_id,details) VALUES('company_pi_import','company','1','{}')")
    return profile


if __name__ == '__main__':
    from dotenv import load_dotenv
    from backend.config import ROOT_DIR
    load_dotenv(ROOT_DIR/'backend'/'.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['import-legacy'])
    parser.parse_args()
    connection = get_db()
    try:
        with connection:
            import_legacy(connection)
        print('Company PI configuration imported. Native exports no longer require the source workbooks.')
    finally:
        connection.close()
