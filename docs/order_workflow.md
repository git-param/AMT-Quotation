# Order composer

Add Order and editable pending drafts use one continuous form. Proforma Invoice
No. and Purchase Order No. come first, followed by location, currency, order date,
delivery defaults, parties and items. All order header fields stay visible.
The embedded popup uses only its outer Close button; standalone orders retain
Cancel. Saving uses the existing draft API and preserves existing order status.

Consignee is the shipment recipient. Buyer and Notify retain separate stored
text blocks. Linked parties show a compact address preview and continue to
follow the existing address-only synchronization rules. Unchecking Same as
consignee opens that party's editor. Editing a linked address retains the
existing automatic unlink behavior. Saved custom parties reopen expanded.

Delivery defaults, India/INR and GST behavior, SKU validation, server totals,
PI references, permissions, snapshots and configured issuer/bank details use
the existing implementation. No schema change is required.

Manual order items load the configured HSN before showing the editor using the
read-only authenticated `/api/sku-defaults` endpoint. Configuration management
remains restricted to the existing roles. Lookup results with found=false are
shown in a separate message box instead of becoming incomplete selected lines.
Successful rows remain selected and can be saved independently. Each missing
SKU has an Add manually action that prefills its SKU and shared HSN; the user
completes description, quantity and price. Catalog failures offer retry/manual
entry without claiming the SKU does not exist. Stock validation remains in force.

The order form focuses an invalid control before showing native validation. Save errors retain the
current values and present a focused inline error. Items added during creation
stay in the draft while editing other fields. Pending cards open the editor only
when can_edit is true, with client/enquiry scope checked again by the editor.

## Verification

From the repository root:

```powershell
node --test tests/test_orders_frontend.cjs tests/test_pi_preview.cjs tests/test_sku_drafts.cjs tests/test_sidebar.cjs
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
.venv/Scripts/python.exe tests/run_order_workflow_browser.py
```

The browser test requires Windows, Microsoft Edge, Node 22+ and access to local
browser debugging ports. It starts a local server against a fresh fixture DB,
uses synthetic issuer settings, and never writes production orders. Artifacts
are written under the ignored `.verification` directory. It covers blank draft
creation, single-form field order, close controls, required/conditional validation, failed
save/retry, country/GST/currency behavior, linked and separate parties, reopening
and editing, initial and subsequent SKU lines, automatic manual HSN, partial
lookup success and missing-SKU manual recovery, INR PI Excel/PDF downloads, and
desktop/mobile/embedded layouts.
