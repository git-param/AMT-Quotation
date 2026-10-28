# PI template field checklist for future client orders

Inspected read-only on 14 October 2026:

- `Updated PI Format USD - 180626 2.xlsm`
- `Updated PI Format INR 1 2 2.xlsm`

Both workbooks have one PI sheet. VBA was neither executed nor modified.
This checklist records template fields and the user's requested future order
requirements; blank cells and labels alone do not establish validation rules.
Workbook terms are template content, not instructions to change this application.
Actual mandatory/conditional rules belong to the future order/PI module.

## Client and party details to capture

| Field | Evidence / intended use |
| --- | --- |
| Company / legal party name | Consignee, buyer and notify-party address blocks |
| Complete address, country | USD A12:E17 and INR A12:E17 consignee blocks; country dropdown at A17 |
| Buyer / billing details | F11 onward; defaults to same as consignee, but allow a separate party |
| Consignee / shipping details | A11 onward; preserve an order-specific snapshot |
| Notify-party details | USD F17 onward; INR F18 onward; defaults to same as consignee |
| Telephone | USD A18; INR A19 |
| Person in charge (PIC) | USD A19; INR A20 |
| Email | USD A20; INR A21 |
| Buyer GST number | INR A18; not a separate buyer field in the USD template |

Module 4.3 captures company, contacts, emails/phones and billing/shipping
addresses. GST and separate notify-party/order snapshots remain future-order
requirements; they must not be guessed from a client's current details.
Country values should be normalized rather than copying the hidden helper list,
which includes repeated countries and aliases such as USA/United States.

## PI and PI header fields

PI number (F4/H4), PI date (F5/H5), purchase-order reference (F6/H6),
prepared-by employee and telephone (F7/I7), payment terms (F8), delivery terms
(F9), destination (H9, linked to A17), delivery time (F10), dispatch/courier (I10),
and document currency/template selection. Treat the purchase-order reference
and notify-party choice as fields whose mandatory rules still need confirmation.

Supplier identity/address, supplier GSTIN/IEC, supplier contacts, bank account
configuration, bank location and charges policy are issuer/configuration data.
They must be snapshotted or versioned with each issued PI; do not copy actual
bank account values into source code or public documentation.

## Line items and totals

Serial number, description, HSN code, condition, quantity, unit of measure,
unit rate, line amount, subtotal, shipping, grand total and amount in words.
SKU is needed to trace quotation/order items even though neither sheet has a
separate SKU column. INR additionally has GST rate/amount and a weight/UOM tax
invoice note; actual order weight should be collected in the future workflow.
Payment, warranty, availability and shipment terms should be preserved as
issued document snapshots, not fetched later from mutable client records.

## USD versus INR and layout risks

| Detail | USD workbook | INR workbook |
| --- | --- | --- |
| Item header | Row 21 | Row 22 |
| Four formatted item rows | 23?26 | 24?27 |
| Example line formula | J23 = I23 * G23 | J24 = I24 * G24 |
| Subtotal | J31 = SUM(J23:J30) | J32 = SUM(J24:J31) |
| Shipping | J32, sample text Free | J31, sample text Free |
| Tax | Destination import/local-tax exclusion text | J33 = J32 * 18% |
| Grand total | J33 = SUM(J31:J32) | J34 = J32 + J33 |
| Amount in words | C33 calls VBA SpellNumber | C34 contains static sample words |
| Delivery sample | 6?7 days, international couriers | 4?6 days, local courier |
| Print layout | A4 portrait, 69% scale | A4 portrait, 70% scale |

More than four items requires expanding styled rows, moving the bank/totals and
terms blocks, rebuilding line/subtotal/tax formulas and updating print areas.
The current subtotal ranges reach into rows below the four item slots; only the
example line has a stored multiplication formula. Do not reuse those ranges
blindly after insertion. Neither sheet defines manual row page breaks. Macro
behavior for automatic row expansion was not verified. Excel print rendering
and macro-dependent number-to-words must be verified in the PI implementation;
the INR static amount-in-words must be replaced by generated output.

This phase does not implement orders or PI generation or change either workbook.
