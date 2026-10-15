# Clients & Orders workspace

`/clients-orders` is the client directory and profile workspace. `/leads` remains
a compatible alias. `/enquiries` bookmarks redirect into the workspace; historical
enquiry APIs remain authorized and available for compatibility. Orders open in
an embedded order editor inside the client profile, using the existing order
module. There is no active enquiry creation screen in navigation.

Client master fields, ownership, supervision, active VIEW/EDIT sharing, soft
deletion, and management-only SKU removal retain their existing rules. Client
profiles expose independent pending drafts and existing orders/PI references.
Filters, pagination, totals, histories, exports, and writes use current client
authorization. An inactive client remains readable; it cannot receive new orders.

## Simplified client and order forms

Client creation/editing and profiles show one editable `location` field in place
of reusable billing/shipping address inputs. Client status and business details
are removed from the active forms/profile. Migration 17 adds Location and copies
any existing shipping/billing location into it; old addresses, status, business
details and history remain preserved and compatible with existing APIs. Location
is searchable with the client directory's existing authorization scope.

Order creation/editing no longer asks for PI reference/date, payment terms or
status. Those server fields remain intact on existing records; new orders default
to pending drafts. Native PI previews use the company payment terms when an order
has no saved terms. Existing saved payment terms take precedence. Commercial
terms can be adjusted inside the PI preview without changing the source order.

Consignee, Buyer Details and Notify Details are editable multiline text boxes.
Consignee starts with the client's company/name, Location, telephone, person in
charge (when present) and email. Buyer/Notify follow Consignee by default. Editing
either recipient independently unchecks its ?Same as consignee? option; checking
it again copies the current Consignee block. Existing order text/snapshots take
precedence over current client defaults when editing.

The delivery API accepts `consignee_text`, `buyer_text`, `notify_text` (up to 4,000
characters each) and optional `instructions`. The first nonblank line is the
legal name, following freeform lines hold address/location and unique additions.
Recognized `Tel:`, `PIC:`, `Email:`, `GST:`/`GSTIN:` and `Country:` labels populate
validated contact snapshots. Email/telephone validation remains active. Country
can also come from the saved order destination. PI readiness still requires a
consignee name and location/country. Mixed text and structured input is rejected;
the historical structured delivery API remains supported. Every edit appends a
new immutable delivery version, and generated PIs keep their issued content.

## Completing item details before PI generation

The order workspace now uses Items & PI, Order details, and History tabs. The
centered dialog has a fixed close header and a single scrolling document; small
screens use item cards with visible HSN/condition inputs.

The Items & PI tab identifies missing HSN codes and item conditions before
issuance. Review the highlighted fields, enter the correct values, and select
**Save item details**. Preview PI stays disabled while order item edits are
unsaved. Missing HSN/condition can also be completed inside the PI preview;
issuance validates both fields on every line. Classification values are never guessed from an
example template. Drafts and historical records remain editable under their
existing client permissions.

`PUT /api/orders/{id}/line-commercial-details` accepts `lines` containing unique
`id`, `hsn_code` and `item_condition` values. Up to 50 active lines are updated
atomically with current EDIT authorization and one complete revision. Prices,
quantities, currencies, source links, and ownership are unchanged. Cross-order,
removed, duplicate or invalid line IDs roll back the complete request. Order
responses expose `pi_line_requirements`; attempted issuance with incomplete item
fields returns `code: pi_lines_incomplete` and a `missing_lines` list.

## Order API

`POST /api/orders` now accepts `client_id` without `enquiry_id`. The old
`enquiry_id`/`source_line_ids` contract remains supported and checked against
the original client. Parent IDs, ownership and order references cannot be edited.
Multiple orders for a client have independent IDs, lines and delivery snapshots.

Headers include the existing commercial fields plus `destination` and decimal
`shipping_charges` in the order's currency. Lines accept `hsn_code`,
`item_condition`, and `uom` alongside SKU, description, whole-unit quantity,
decimal unit price, and USD/INR currency. Consignee, buyer, notify-party details,
notify address, order billing/shipping addresses and instructions remain order
snapshots. Saved client addresses are copied and never changed by an order.

A new direct-client order can save an empty draft. Existing field/precision and
address-shape validations still apply to supplied values. Confirmation requires
items and complete delivery details. PI generation separately validates item,
party, delivery, and required commercial fields. `GET /api/orders` adds
`exclude_drafts=1`; the existing status, client, text, sorting and pagination
parameters retain their behavior. Client detail/directory payloads add
`order_count` and `pending_order_count`.

## Editable PI previews and native Excel/PDF generation

The active UI uses **Preview PI** after selecting USD or INR and any required
exchange rate. Users edit the PI date, PO/commercial fields, consignee/buyer/notify
text, item descriptions/HSN/condition/quantity/rate/UOM, shipping, instructions and
notes directly on the invoice page. **Update preview** recalculates amounts on the
server. **PDF print preview** shows the exact padded A4 document; **Edit invoice**
returns to the editable page. Preview edits apply to the issued PI, leaving the
source order intact. Seller/bank details, branding, reference, currency and
ownership cannot be supplied or overridden by preview edits.

**Generate XLSX** and **Generate PDF** issue both formats together from one saved
snapshot and PI reference. Subsequent downloads return the stored bytes. Issuance
is idempotent for the same preview ID, rejects a changed source order, rechecks
current client EDIT access and records an order revision and audit event.
Preview endpoints also require the preview creator; downloads require current
client visibility. Cancelled orders cannot issue invoices.

Native renderers use `assets/PI-img/header.png`, `address.png`,
`payment_options.png` and `signature.png`. Assets and company settings are frozen
in each snapshot. No reference workbook, Excel installation, VBA, country lists
or helper worksheets are needed for native generation. PDF uses A4 margins,
a single branding/title box and page numbers; long content and up to 50 lines paginate.
XLSX is an ordinary macro-free workbook with embedded images, a defined print
area and wrapped commercial content. Seller, company bank information, taxes,
shipping, total, amount in words and existing commercial clauses are retained.

`backend/orders/pi_layout.py` defines the original A:K company invoice layout
for the editable preview and both native exports: Cambria typography, supplier
beside PI/commercial details, consignee beside stacked buyer/notify blocks,
bank information beside totals, bold headings/bank rows, the red-on-yellow
bank-charge warning, and the highlighted final INR clause. Borders use bold
black section/column boundaries; light worksheet row lines are omitted. The
image and invoice title share one header box without a divider above the title.
Dividers below the title/payment terms, above notify details and around shipping
totals match the marked layout. Continuation pages do not repeat the branding
header. Payment/signature images follow the terms above the address strip.

Company seller/bank/payment/tax/terms configuration lives in the singleton
`company_pi_settings` table. It is company-owned, never a client/order input.
For an existing deployment, install `requirements.txt`, back up the database,
apply migration 18, then explicitly import its configured historical workbooks
once:

```powershell
python -m backend.orders.company import-legacy
```

The command reads `PI_TEMPLATE_USD` and `PI_TEMPLATE_INR` from `backend/.env`,
validates the established company layouts, copies settings and records an audit
entry. It does not run during native generation. Missing company configuration
blocks preview with an actionable error. Re-importing deliberately updates the
company configuration; issued snapshots and files remain unchanged.

Conversion retains the existing explicit rule: enter INR per 1 USD; multiply
USD to INR and divide INR to USD. Converted unit prices round HALF_UP to two
decimals before multiplication by whole-unit quantity; shipping converts and
rounds separately. Existing company tax rates apply to items plus shipping.
Preview edits use the displayed PI currency and are never converted twice.
Original source prices, conversion rate/rule and final totals are all retained.
The editable `prepared_phone` prints beside Prepared By, initially using a
configured company contact when available. It is saved in the PI snapshot and
uses the existing phone validation. Zero shipping prints as **Free** in all
three views while remaining numeric zero for calculations.

Native API contracts:
- `POST /api/orders/{id}/invoices/preview`: `{currency, usd_inr_rate?}`.
- `PUT /api/orders/{id}/invoices/preview/{preview_id}`: any of `date`, `prepared_phone`, `order`
  (commercial fields only), `delivery` (three text blocks/instructions), `lines`
  (same unique IDs, editable commercial fields), `shipping_charges`.
- `GET /api/orders/{id}/invoices/preview/{preview_id}/pdf`: exact saved preview.
- `POST /api/orders/{id}/invoices/issue`: `{preview_id}`; returns reference,
  `xlsx_url` and `pdf_url`.
- `GET /api/orders/{id}/invoices/{invoice_id}/download?format=xlsx|pdf|xlsm`:
  stored issued format; a historical PI without PDF returns 404 for PDF.

The old `POST /api/orders/{id}/invoices` contract remains available to legacy
integrations and still uses the configured XLSM layouts. Historical XLSM bytes,
references, snapshots and download URLs are unchanged.

## Migrations and historical records

Migration 15 makes the enquiry FK optional while retaining IDs, existing enquiry
links, order references, PI references, source snapshots, delivery versions and
revisions. Nondeleted enquiries without an order become `LEGACY-ENQ-{id}` pending
drafts (cancelled enquiries remain cancelled). Their authors/timestamps and
original enquiry records remain intact. No commercial details, HSN codes, item
conditions, shipping prices or completed delivery parties are invented. The
original request and SKU history remain readable inside the order detail.

Legacy fractional enquiry quantities cannot silently become whole-unit order
quantities. They remain in the source records, appear as outstanding reviews,
and block PI generation. Add an appropriate whole-unit order line and explicitly
map it to the source using
`POST /api/orders/{id}/legacy-lines/{source_id}/review` with
`replacement_line_id`. Migration 16 stores those reviewed mappings and actor/time;
the API records an audit event and revision without changing the original line.
Removing a replacement makes the review outstanding again.

Migrations retain checksums and transactional DDL. The final foreign-key check
runs before commit. SQLite can retain a deferred-violation counter during a
parent-table replacement; the runner resets deferral only after the complete
final schema passes the foreign-key check, while the write lock is held.
`PRAGMA foreign_keys` stays enabled. Invalid foreign keys still roll back.

Before upgrading a deployed database, take a SQLite backup, verify an upgrade of
that copy and restart the application with the updated code. Initialization
applies pending migrations; explicit commands are also available:

```powershell
python -m backend.migrations status --database database/quotation.db
python -m backend.migrations migrate --database database/quotation.db
```

## Verification

Run `.venv/Scripts/python.exe -m unittest discover -s tests` and
`node --test tests/test_orders_frontend.cjs tests/test_sidebar.cjs tests/test_sku_drafts.cjs`.
The workspace tests cover direct orders, empty drafts, multiple independent orders,
current VIEW/EDIT/revoked access, currency validation/conversion, PI snapshots,
populated version-14 upgrades, explicit legacy review, template expansion and
company-data preservation. Local company workbook integration coverage skips
only when those external fixtures are unavailable.

Desktop/mobile browser smoke testing also verified client creation/editing/search,
draft save/edit, order SKU fields, INR PI generation and profile card refresh.
Native PI tests cover company field protection, edited totals, original price
provenance, idempotent issuance, stale previews, live permissions, long documents
and formula-safe XLSX cells. Browser checks exercise editable previews, exact PDF
preview and both download buttons. Excel also opened and printed the generated
native USD/INR workbooks with macros disabled.
