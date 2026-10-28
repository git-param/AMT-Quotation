"""Editable company PI terms, grouped by invoice currency.

Edit these lines to change the terms printed on newly generated PIs. A
``PAYMENT`` line is replaced with the payment terms saved on the order.
"""

RETURN_POLICY_URL = 'https://aeliyamarinetech.com/pages/return-and-refund-policy'
RETURN_POLICY_LABEL = 'Return And Refund Policy'
RETURN_POLICY_TEXT = "All Returns And Refunds Are Subject To The Company's Return And Refund Policy."

USD_TERMS = (
    '1. Subject To Bhavnagar Jurisdiction',
    '2. Local Taxes And Custom Duty At Destination Not Included [Importer Country]',
    '3. Shipment: Dispatch Within 24 Hours Of Payment Confirmation',
    '4. Offer Subject To Remain Unsold Against PI Confirmation',
    '5. Warranty: 30-Day Technical Warranty: Full Refund Or Replacement If The Product Is Non-Functional Or Technically Defective.',
)

INR_TERMS = (
    '1. Subject To Bhavnagar Jurisdiction',
    '2. Shipment: Dispatch Within 24 Hours Of Payment Confirmation',
    '3. Offer Subject To Remain Unsold Against PI Confirmation',
    '4. Warranty: 30-Day Technical Warranty: Full Refund Or Replacement If The Product Is Non-Functional Or Technically Defective.',
    '5. The Final Tax Invoice Will Be Based On Weight (UOM). Above Mentioned Quantity In Proforma Invoice Is For Reference Only.',
)

TERMS_BY_CURRENCY = {
    'USD': USD_TERMS,
    'INR': INR_TERMS,
    'AED': USD_TERMS,
    'GBP': USD_TERMS,
    'EUR': USD_TERMS,
}
