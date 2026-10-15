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
to pending drafts. If an order has no saved payment terms, PI issuance reads them
from F8 in the configured company template and stores the effective terms and
source in the issued snapshot. Existing saved payment terms take precedence.

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

## Company templates and PI generation

Configure the existing company workbooks once on the server:

```dotenv
PI_TEMPLATE_USD=C:/company-templates/pi-usd.xlsm
PI_TEMPLATE_INR=C:/company-templates/pi-inr.xlsm
```

When unset, the local defaults are the existing `Updated PI Format USD - 180626
2.xlsm` and `Updated PI Format INR 1 2 2.xlsm` files in the server account's
Downloads directory. Keep those files accessible to the application account.
Use the original company formats documented in [PI fields](pi_order_fields.md).
Unexpected layouts and missing company/bank configuration fail before issuance.
There is no per-client or per-order bank-details input. Do not commit company
bank values or the templates to source control.

`POST /api/orders/{id}/invoices` requires `currency: "USD" | "INR"` and, only
when conversion is needed, an explicit positive `usd_inr_rate`. The rate means
**INR per 1 USD**, supports up to six decimal places, and has an upper bound of
1,000,000. USD to INR multiplies; INR to USD divides. Same-currency amounts stay
unchanged. No live or quotation-cache rate is silently applied to a PI.

Converted unit rates round HALF_UP to two decimal places before multiplication
by whole-unit quantity. Each line amount and converted shipping round separately
to two decimal places. Shipping uses the order currency; each SKU uses its own
saved currency. All calculations use Decimal and scaled database integers.
Subtotal is the sum of generated line amounts. USD uses the original template's
subtotal + shipping rule; INR reads the GST percentage from the existing
template's J33 formula and applies it to items plus shipping, preserving the
workbook's commercial calculation. Currency, rate, calculation rule, tax rate,
totals and amount in words are recorded in the issued snapshot.

Every generation stores a unique PI reference, full issued order snapshot,
generated workbook bytes, actor/time and an audit event in one transaction.
The original template retains seller, GST/IEC, company contacts, bank data,
charges policy, commercial terms, formatting, styles, and VBA content. VBA is
never executed; amount in words is calculated in Python. Additional item rows
copy original styles and expand merged ranges and print area; old cached
calculation chains are removed. Order notes and delivery instructions print
after the original terms; the payment clause uses the saved order payment terms. The supplied templates' four-row limits are not used
as a data limit: up to 50 active order lines are supported.

`GET /api/orders/{id}/invoices/{invoice_id}/download` returns that exact saved
XLSM after rechecking current client access. Editing an order, client, rate, or
company template does not alter an issued document. Older PIs remain downloadable
after subsequent generations. Generated reference/date fields cannot be manually
overwritten. PI issuance does not automatically change the order's business status.

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
Excel successfully opened both real company-template workbooks with 50 item lines
and exported them to PDF with macros disabled. Production documents are generated
as XLSM; PDF is not a server export format in this implementation.
