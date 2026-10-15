# Client defaults and future order delivery snapshots

Module 4.4 reuses `client_leads.billing_address_json` and
`client_leads.shipping_address_json`. The latter is the client's reusable
**default** shipping address, not a mandatory delivery destination for orders.
API field `shipping_address` remains unchanged for backward compatibility.

`client_address_history` records immutable-by-API snapshots of both saved
addresses, with client ID, version ID, actor and recorded timestamp. Migration 9
captures a baseline of currently saved addresses with no invented actor.
Earlier unrecorded changes cannot be reconstructed. Creation records an initial
snapshot; edits append a snapshot only when an address changes. No history
edit/delete API exists. Client and actor FKs use restrictive deletion.
Authorized detail requests alone can retrieve this history.

## Future order model contract (design only)

An order belongs to one client; a client may have any number of orders. The
future Orders module should create its own delivery/address record containing:

- Order ID and client ID.
- Optional selected `client_address_history.id` plus address kind, validated to
  belong to that order's client.
- Copied billing and shipping/consignee address snapshots, never references that
  resolve to the client's mutable current defaults at export time.
- Consignee legal name, country, telephone, PIC and email; separate buyer and
  notify-party snapshots when required.
- Delivery terms/destination, courier/dispatch method and delivery time, plus
  order-specific instructions.
- Delivery snapshot version, actor and recorded timestamp.

The workflow must let users select a saved address version **or enter a different
order-only address**. Choosing a default copies its values into that order;
changing one order's destination never updates the client or another order.
Updating client defaults never changes existing orders or issued PI snapshots.
The order's client ID and selected saved-address version must be authorized
server-side. Inactive clients should remain readable for history; the future
module must explicitly decide whether new orders are permitted for them.

See [PI field checklist](pi_order_fields.md) for USD/INR party, GST, delivery,
line-item and document-snapshot requirements. This module deliberately creates
no order, consignee/delivery, enquiry, SKU-line or PI tables/endpoints. Those
fields belong to the future order delivery record, not extra client columns.

## Module 5.3 implementation

The contract above is now implemented in `client_orders` and
`order_delivery_versions` (migration 14). Orders retain immutable client/enquiry
links; delivery versions store copied billing/shipping snapshots, separate
consignee/buyer/notify-party details, instructions, saved-address version/kind,
actor and timestamp. Saved-address selection is validated against the order's
original client. Custom order destinations never update saved client addresses.
Order edits append versions rather than changing existing snapshots.

Order SKU lines also have independent IDs and optional original-enquiry-line
snapshots. Full order revisions record each committed create/edit/line change.
Current client VIEW/EDIT permissions govern reading/writing these records; new
orders require an active client. Existing order history remains readable when
the client is inactive. Final PI issuance and its supplier/bank/document
snapshots remain a later module; no final PI documents are generated here.
