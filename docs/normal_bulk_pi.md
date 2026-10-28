# Normal and bulk proforma invoices

The supplied `PI-9206 1.pdf` and `LIST-Annexure-1.xlsm` were inspected as layout
references without executing VBA. The PDF uses a one-lot cover description and
an Annexure-1 listing individual products. Sample leftovers and inconsistent
formula/tax rows in the workbook are not application rules or runtime inputs.

## Separate implementations

- `backend/orders/normal_pi/layout.py` and `exports.py` preserve the previous
  company-grid implementation (only the exporter's layout import moved).
- `backend/orders/bulk_pi/layout.py` and `exports.py` implement the one-lot
  summary and complete Annexure-1 independently.
- `pi_layout.py` and `pi_exports.py` are stable dispatch interfaces;
  `pi_grid_exports.py` retains the old imports for compatibility.
- `frontend/orders/pi-preview.js` renders the shared editable preview and print
  view; `frontend/orders/orders.css` owns the preview page framing.

The branding image sits above the invoice grid and stays outside its border.
The centered `PROFORMA INVOICE` heading is also outside the grid border.
The payment/signature area remains framed; the address/location artwork and
computer-generated notice follow it below the frame. These boundaries are kept
consistent in the shared preview, normal PDF/XLSX exports, and bulk cover and
annexure exports.

The PI reference is editable by Admin/Manager and Sales TL accounts. Sales
Executives see it read-only, and the order and preview APIs enforce the same
role boundary.

A newly prepared snapshot records `pi_format`: normal for zero to four order
products, bulk for more than four. Legacy previews without this marker continue
to use the original renderer, including previews created before this change
with more than four products. Already issued downloads remain stored files.

## Bulk behavior

Before opening a bulk PI, sales enters a first-page description (maximum 2,000
characters). It stays editable in the cover and PDF print-edit flow. The cover
shows one Lot, the common HSN/condition or an Annexure-1 reference for mixed
values, and the complete product subtotal. The lot is presentation only:
`totals.lines`, order products and calculations retain every actual product.

Annexure-1 contains every product, its description, HSN, condition, quantity/UOM,
unit price and amount. HSN is retained as an additional column alongside the
reference's item columns. Quantities are summarized per UOM. Subtotal, shipping,
GST and grand total come from the same validated snapshot on both pages.
Company identity, bank details, signatures and payment configuration remain the
existing issuer snapshot; users do not re-enter bank details.

The PDF starts Annexure-1 on a new page and repeats the annexure headings for
long lists. The XLSX places the cover and Annexure-1 on the same `Proforma Invoice`
worksheet, separated by three blank rows and a print page break. Cover subtotal/rate formulas reference the annexure subtotal;
annexure line and total formulas have cached server amounts. No macros or
external reference workbooks are required at runtime.

The yellow shipping notice appears once on the first page when the order
destination is outside India. It is omitted for India in normal and bulk PIs,
  including the annexure. Preview, PDF and XLSX use Cambria Bold at 11 pt for
the notice.

Opening and issuance require a nonblank bulk description. In-progress print preview
retains the existing ability to print unsaved/unfinished text. Preview edits
apply to the invoice snapshot, not source order products. Permissions, stale
snapshot checks and idempotent issuance use the same APIs. PI and order
references may be reused; records and downloads remain identified by their IDs.

## Verification

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_orders_frontend.cjs tests/test_pi_preview.cjs tests/test_sku_drafts.cjs tests/test_sidebar.cjs
.venv/Scripts/python.exe tests/run_order_workflow_browser.py
```

Coverage includes the four/five-product boundary, required/edited/unsaved cover
description, annexure edits, USD/INR amounts and XLSX formulas, five/nine/fifty
product exports, continued annexures, legacy snapshots, normal PI regressions,
and the real browser prompt/edit/print/issue/download flow.
