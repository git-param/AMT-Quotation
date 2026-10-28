# AMT Quotation

For production serving, concurrent-user testing and the versioned scalability change log, see [Scalability](docs/scalability.md).
For session controls, CSRF, rate limiting, security events, and production settings, see [Security](docs/security.md).

## Quotation API keys

Existing keys in the legacy `api_keys` SQLite table are preserved by migration 30
when the new app uses the same database. The live monolith used a root-level
`quotation.db`; this app now uses that same file when it exists. In a checkout
without the root-level file, it uses the existing `database/quotation.db`.
`AMT_QUOTATION_DB_PATH` remains an optional override. Back up the live file
before deployment. An explicit override to a missing file stops startup instead
of creating a blank database there.
Send a key in the `X-API-Key` header to call quotation API endpoints such as
`GET /api/me` and `POST /api/lookup` without a browser session. A valid key gets
`{"auth":"api_key","role":"api","username":"api-key"}` from `/api/me`;
missing or invalid credentials get HTTP 401. Keys do not grant access to account
or management APIs.

An account with `users.manage` permission can create a key with
`POST /api/manager/api-keys/create` and JSON `{"label":"Inbox"}`. The plaintext
key is returned only on creation. `GET /api/manager/api-keys` lists metadata,
and `POST /api/manager/api-keys/<id>/revoke` disables a key. These management
requests require a browser session and its CSRF token.

Admins can set the maximum number of SKUs per lookup on the Configuration page
or with `PUT /api/sku-lookup-limit` and JSON `{"max_sku_lookup":25}`. The default
is 50, and the allowed range is 1 to 500. Quotation and enquiry lookup requests,
including API-key requests, reject larger batches before calling providers.
Fresh stock checks during order and enquiry saves use the same limit; a save
with more distinct SKUs than the configured limit returns an error.

## Production quotation catalog

The quotation tool also supports the live catalog workflow: batched Shopify
lookups, Atlas and Al Reza reference fallback, guarded discounts, image
downloads, a quotation letter API, price history, and manager activity reports.
`POST /api/quotation/letter` accepts `{"skus":["26733"],"currency":"USD"}`;
set `"letter":false` to receive the quotation table alone. The response
includes HTML, plain text, and lookup rows. The configured SKU limit applies.

The local Zoho search and image reader uses the adjacent `Pricing-App` SQLite
catalog. When `PGHOST` is set, or `/etc/aeliya/.pg.env` exists, it reads the
shared `pricing` Postgres schema used by the supplied live app. Install the
updated requirements before enabling that source. Price history and line-level
quote logs require the shared Postgres database; without it, lookup and
quotations still work, and `GET /api/price-history` reports unavailable.
In the quotation page, search a numeric SKU and open the **Price History** tab
to see its pricing timeline. The tab shows when prices changed, by whom, and why.
The shared Pricing App IP policy is documented in [Security](docs/security.md).

The active CRM workflow is now **Clients & PI** at `/clients-orders`: search
clients, manage their profiles, save independent Pending PI, and generate
USD/INR proforma invoices. Company seller/bank details remain in server-configured
PI templates. See [workspace setup, API, migrations and verification](docs/clients_orders_workspace.md).
The module notes below also describe historical functionality retained for compatibility.

## Project structure

```text
app.py                         Application entry point
backend/
  app.py                       Flask application factory
  config.py                    Project, frontend, and database paths
  database.py                  Database initialization and activity logs
  migrations.py                Transactional migration runner and CLI
  migration_definitions.py     Immutable, ordered schema versions
  secret.key                   Existing session signing key
  common/
    auth.py                    Authentication and role checks
    request.py                 Client IP helper
  login/
    routes.py                  Login, logout, profile, password changes
  manager_dashboard/
    routes.py                  Dashboard statistics and user management
  quotation_tool/
    routes.py                  Quotation page, lookup, rates, and cache
    shopify.py                 Shopify lookup and currency services
    search_routes.py           Combined search and Zoho image endpoints
    search_service.py          Zoho and blog search services
frontend/
  login/
    login.html
    login.css
    login.js
  manager_dashboard/
    manager.html
    manager.css
    manager.js
  quotation_tool/
    quotation.html
    quotation.css
    quotation.js
database/
  quotation.db                 Existing users and activity history
```

## Run on Windows

From the project root, use the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5062/login>. Stop any previously running instance
with Ctrl+C before starting the restructured app. The URLs `/login`, `/`,
`/manager`, and `/api/...` remain the same. Frontend CSS and JavaScript are
served at `/static/<module>/<filename>`.

## Currency reference rates

The app fetches USD-based INR, AED, GBP, and EUR reference rates from
[Frankfurter](https://frankfurter.dev/), which combines central bank and other
official sources. An admin sets the refresh interval (1–168 hours) in
Configuration; the default is 24 hours. The background refresh runs while
`app.py` is running. Configuration shows each published rate date, the last
fetch time, and the provider site, and offers a manual **Refresh now** action.
These are daily reference rates, not intraday trading quotes. Each successful
refresh uses the latest available rate returned by the provider. A failed fetch
keeps the last valid rates visible. Issued invoices retain their recorded
amounts.

For a new environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

The existing database and secret key have been moved, preserving accounts,
passwords, history, and session signing. Back up `database/quotation.db`
and `backend/secret.key` together. The Zoho integration still expects the
existing sibling `Pricing-App` directory next to this project.

## Database migrations

Application startup now applies pending migrations before the existing user
seeding logic. Flask, SQLite, authentication, URLs, and legacy records remain
unchanged. No migration rewrites, renames, or deletes an existing table or row.

### Upgrading the existing VPS database

The `.env` file contains settings; quotation accounts, search/copy history,
clients, orders, and invoices live in the SQLite database. The shared Pricing
App Postgres catalog, including price history, is separate. On the VPS, keep
the original root-level `quotation.db` in `/app`, one level above
`backend/app.py`. The app selects it automatically. Preserve that file and
`backend/secret.key` across deployments.
If the live file is elsewhere, use the optional `AMT_QUOTATION_DB_PATH` override.

Stop the old app and other database writers. Make a SQLite-aware backup of the
existing file (the backup API includes committed WAL data), and verify the
backup before starting the new code. Then inspect the existing file:

```bash
python3 -m backend.migrations status --database /app/quotation.db
```

On the first new-app startup, `initialize_database()` applies only pending
versions to that same file, records them in `schema_migrations`, and then serves
requests. You may instead run `python3 -m backend.migrations migrate --database
/app/quotation.db` while the app is stopped. Do not replace the live file with
the checkout's `database/quotation.db`; doing that replaces its history. If an
upgrade fails, its pending schema changes roll back and startup fails.

| Version | Purpose |
| --- | --- |
| 1: `legacy_baseline` | Creates the existing users/log tables and indexes on fresh databases; adopts existing tables without rewriting records. |
| 2: `crm_foundation` | Adds roles, permissions, role_permissions, enquiry_sources, and audit_logs with constraints and indexes. |

`users.role` remains the authority for current access checks. The new role
catalog starts with user/manager descriptions; permissions, enquiry sources,
and audit logs start empty. There are no new routes, user assignments, audit
writers, clients, enquiries, orders, or PI features in this phase. Future modules
can reference enquiry sources and existing user IDs for ownership. Audit rows
support an optional actor FK and a name snapshot; deleting a user clears only
the new actor FK, retaining the audit row and snapshot. Permission references
use restrictive deletion. Audit details must be redacted by future writers;
the schema alone does not filter sensitive values or guarantee append-only use.

`schema_migrations` stores each version, name, SHA-256 checksum, and UTC
application timestamp. Startup validates history and refuses missing, changed,
or newer migrations. Add a new version rather than editing applied definitions.
Each statement runs through `execute`, not `executescript`, inside one
`BEGIN IMMEDIATE` transaction for all pending versions. A failure rolls back
both DDL and tracking records. Concurrent startup processes serialize, with a
30-second SQLite lock timeout. Foreign keys are enabled on application and
migration connections; future SQLite callers must enable them too.

Inspect the existing database without starting Flask or changing schema:

```powershell
.\.venv\Scripts\python.exe -B -m backend.migrations status --database database/quotation.db
```

After backing up, apply migrations explicitly, or let the next app startup
apply them:

```powershell
.\.venv\Scripts\python.exe -B -m backend.migrations migrate --database database/quotation.db
```

The CLI does not seed accounts, load Shopify credentials, or create a signing
key. It requires an existing parent directory. Migration status requires an
existing database and never creates one.

### Module 2: roles and permissions

Migration 3 (`rbac`) adds an active-account flag and role index to `users`,
plus role/permission catalog entries. Existing user IDs, role strings, password
hashes, logs, signing keys, and session formats are preserved. At version 2 the
permission catalog is empty; version 3 activates these grants:

| Role | Quotation/search/copy | Own profile/password | Activity dashboard | User administration |
| --- | --- | --- | --- | --- |
| Sales Executive (`sales_executive`) | Yes | Yes | No | No |
| Sales TL (`sales_tl`) | Yes | Yes | Yes | No |
| Admin (`admin`) | Yes | Yes | Yes | Yes |
| Legacy `user` | Yes | Yes | No | No |
| Legacy `manager` | Yes | Yes | Yes | Yes |

Sales TL sees the existing application-wide quotation activity statistics.
There is no team ownership model or team filtering in this module. Legacy
managers retain their existing administrative access as Admin equivalents.
The dashboard user-management controls appear only for accounts with
`users.manage`; backend checks enforce all access regardless of the UI.

Every protected endpoint revalidates the active account and reads current
database role permissions. API denials return JSON 401 (no valid account) or
403 (insufficient permission); page denials redirect to login or display an
access-denied page. Unknown roles have no grants. Static files, login, and
logout remain public; static page markup provides no API access.

Admins can create users, assign supported roles, deactivate/reactivate users,
and use the existing password-reset API. Self role/status changes and removing
the last active Admin equivalent are blocked. The existing `/delete` API is
retained as a deactivation alias: it no longer deletes account records.
Role changes affect open sessions on their next request. Deactivation prevents
login and clears sessions when they next request a protected endpoint.

There are no client, PI, or audit-dashboard features in this module. Existing
session signing and password-reset session behavior remain unchanged.
Before rolling back to pre-RBAC code, assess the authorization consequences:
that code ignores deactivation and does not recognize the three new roles.
Do not restore old access checks on an exposed deployment without an equivalent
access gate. Prefer a forward fix that retains the current accounts and grants.

### Backup and rollback

Before upgrading, stop all app instances and SQLite writers. Make a dated,
protected backup of the database and session signing key, and record the code
revision. For a live database, use SQLite's backup API or a SQLite-aware backup
tool; copying only a live `.db` file can omit committed WAL data. Verify the
backup with `PRAGMA integrity_check` and record legacy table counts. Keep the
signing key private and retain it unchanged during a schema-only rollback.

An unsuccessful migration automatically rolls back; do not delete tracking rows
or manually drop tables to retry. Correct the unapplied migration or deployment
problem, then retry. A newly created empty database file can remain after a
failed fresh setup, but its schema changes are rolled back.

There is intentionally no destructive automatic down migration. For a successful
upgrade, these additive tables allow the prior code to use the original tables;
test that code rollback on a copy first. Restore a pre-upgrade database only with
all writers stopped and after preserving the current database and reconciling
post-backup activity: restoration otherwise loses newer records. Retain the
matching SQLite sidecars when archiving the current database, and avoid mixing
old WAL files with a restored database. Prefer a forward corrective migration
when new records must be retained. Never regenerate credentials or replace the
database with a fresh one as part of rollback.

### Migration tests

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Tests use temporary databases and SQLite's backup API to test a copy of the
existing database. They compare every legacy row, schema definition, and legacy
sequence without printing user records or credentials. Coverage includes fresh
setup, repeated upgrades, application initialization, concurrent startup,
transaction rollback, checksum/history rejection, read-only status, integrity,
foreign keys, and new constraints. The existing-database test is skipped when
the application database is unavailable. No production upgrade is performed by
the tests.

### Module 3: enquiry source management

Open **Enquiry Sources** from the quotation header or dashboard. Admins,
Sales TLs, and legacy managers have `sources.manage`; Sales Executives and
legacy users cannot access the page or its APIs. Names in navigation are shown
without roles.

Migration 4 (`enquiry_sources`) adds nullable channel/contact/update fields
and a case-insensitive unique contact index to the existing source table.
Existing rows, IDs, codes, names, timestamps, and active flags are preserved.
Unclassified legacy sources remain visible and can be completed through Edit.
New sources require a name, Email/WhatsApp channel, and valid contact. Emails
are normalized to lowercase; WhatsApp numbers use + and country code, with
spacing/hyphens/parentheses removed. Contacts cannot be duplicated, including
inactive contacts. Editing preserves source identity and active status.

APIs: `GET/POST /api/sources`, `PUT /api/sources/<id>`, and
`POST /api/sources/<id>/deactivate` or `/activate`. No permanent-delete API
exists. Deactivation is idempotent and preserves records for future historical
references; future enquiry modules must reference stable IDs and offer only
active sources for new selections. This phase adds no clients, enquiries,
orders, or PI functionality.

Run the full unittest command above to cover source CRUD, duplicate/invalid
contacts, permission denials, deactivation/reactivation, disabled accounts,
and preservation of source rows through the version-3-to-4 migration.

### Module 4.1: private client leads

**Client Leads** is available from the quotation, dashboard, and sources
headers. Any active authenticated account can create a lead, including an
account without quotation permissions. Name is required; company, email, phone,
and notes are optional. The server assigns `created_by` and a UTC creation
timestamp; input containing ownership, timestamp, or unknown fields is rejected.
Ownership-transfer and delete endpoints remain unavailable.

Migration 5 (`private_client_leads`) adds `client_leads`, indexed by creator,
and `client_lead_shares` with foreign keys. Creator deletion is restricted so
historical lead ownership remains intact. Shares support explicit existing
access grants, but this module provides no sharing API or UI. Sharing and
permissions management are deferred to Module 4.2.

AMT had no supervisor hierarchy. With approval, migration 5 adds the sole
nullable self-referencing `users.supervisor_user_id` FK and an index. All
assignments start NULL; no supervisors are inferred. Admins and legacy managers
configure this relationship in the existing user-management table, or through
`POST /api/manager/users/<id>/supervisor` with `supervisor_user_id` (integer or
null). An active executive (`sales_executive` or legacy `user`) can be assigned
only to an active Sales TL. Self-supervision is rejected by both API and schema;
clearing an assignment is supported. No parallel team table is introduced.

List and detail APIs enforce access within parameterized SQL:

- Every active user can read their own leads and explicitly shared leads.
- Sales TLs also read leads from active executives currently assigned to them.
  Without assignments they cannot read executives' private leads; other TLs'
  private leads are not automatically visible.
- Admin and legacy manager grants (`leads.view_all`) allow all leads.
  Additional configured role grants use the existing `role_permissions` table.
- Creator username and stable creator ID are returned with authorized records.
- Unauthorized detail requests return the same 404 as missing IDs. Query-string
  ownership overrides cannot broaden scope; cached session role claims are ignored.

Supervisor changes affect visibility immediately. Deactivation retains the
relationship but prevents login and removes team-derived access to inactive
executives' leads; Admins still see historical leads. Demoted supervisors lose
team access through RBAC, and executive role changes stop team-derived access.
Deleting an unreferenced supervisor clears the link with `ON DELETE SET NULL`;
users who created leads must be deactivated rather than deleted. Reactivation
restores access according to the retained relationship.

Endpoints: `GET /leads`, `GET/POST /api/leads`, and
`GET /api/leads/<id>`. No enquiries, orders, PI generation, sharing screens,
or permission-management screens are implemented. Rollback to pre-module code
should retain the additive schema and records; prefer a forward migration over
removing ownership or share tables. The standard test suite covers creation by
all roles, supervisor configuration, private/shared access, cross-TL isolation,
ownership manipulation, disabled/deleted accounts, and prior RBAC behavior.
Browser layout and interactive testing must be completed separately.

### Client lead editing

`PUT /api/leads/<id>` updates name, company, email, phone, and notes using a
detail payload (omitted fields are preserved). Users can edit
own leads; Sales TLs can also edit their currently assigned active executives'
leads; Admins and legacy managers can edit all leads. Explicit sharing and
view-only role grants do not authorize edits. List/detail responses include
server-derived `can_edit` for UI actions. The prefilled edit form includes Cancel.

Update authorization is enforced again inside the SQL UPDATE predicate.
Ownership and creation timestamps are preserved, and attempts to supply them
are rejected. No permanent deletion or archive endpoints are introduced.
No schema changes or new migrations are required for editing.

### Module 4.2: client access and sharing

**Client Access / Sharing** is a separate section linked from Client Leads,
the dashboard, and the quotation header for authorized managers. Here a client
means the existing client lead, referenced by its stable `client_leads.id`.
No second client table or ownership hierarchy is introduced.

Admins and legacy managers can manage shares for any client. Sales TLs can
manage their own leads and those of their assigned active executives using the
existing ownership/supervision scope. Neither VIEW nor EDIT shares, nor
`leads.view_all` read grants alone, authorize sharing. The `leads.share_manage` permission is
required in addition to the manager role and per-client SQL scope. Executives
cannot reshare or escalate access, even if a lead is shared with them.

Recipients must be active Sales Executives (including legacy `user` accounts).
TLs can choose executives outside their team, but only share clients they may
manage. Source-client ownership never changes. Owner grants are rejected as
redundant. Revocation is supported for existing recipients even if they have
since been deactivated or changed roles.

Migration 6 (`client_sharing`) adds active state and grant/revoke metadata to
existing `client_lead_shares` rows, plus indexed `client_share_events` history.
The existing composite primary key prevents duplicate lead/recipient rows.
Existing shares stay active; their original actor/timestamp fields remain NULL
because that information was not recorded. No historical attribution is
invented. Regrants reuse the same row; every successful grant/revoke cycle has
its own timestamped event and actor ID/name snapshot. Foreign keys restrict
deletion of linked leads, recipients, and actors. No share or history deletion
API is provided.

Share state and event insertion are committed together under `BEGIN IMMEDIATE`.
Concurrent duplicate grants produce one successful grant and one 409, with
one event. A failed event write rolls back the access change. Revocation flips
active state without deleting records. Subsequent list/detail requests stop
returning the client through that share immediately; ownership, supervision,
and independent RBAC grants remain effective. An already loaded browser must
refresh to reflect the new permissions; previously viewed content cannot be
withdrawn. Shared-access badges show VIEW or EDIT in the Client Leads list,
and identify independently editable VIEW recipients.

APIs: `GET /api/client-access` lists manageable clients and eligible recipients;
`GET /api/client-access/<lead_id>` lists scoped share state and history;
`POST /api/client-access/<lead_id>/grant` accepts `user_id` and `access_level`;
`/revoke` accepts only `user_id`. Unauthorized clients return 404, and unauthorized roles/anonymous
sessions are rejected by backend permission checks. Duplicate grants or revokes
without an active share return 409. This module includes no enquiries, orders,
PI features, permanent deletion, or general permission-management editor.

Before upgrading, use the database backup/rollback guidance above. If rolling
back to pre-sharing code, note that it ignores `is_active` and could restore
revoked share access: retain the new visibility checks or use a forward fix.
Tests cover grant/revoke/regrant, legacy-share preservation, actor/timestamp
history, concurrent duplicates, atomic failure rollback, unauthorized sharing,
read-only enforcement, cross-TL isolation, and preserved independent access.
Browser layout and interactive testing remain a separate validation step.

### VIEW and EDIT client sharing

Migration 7 (`client_share_levels`) adds a constrained `access_level` column
(VIEW/EDIT) to the existing shares and event history, plus nullable
`previous_access_level` on events. No tables are duplicated or rebuilt. Versions
1?6 are unchanged. Existing shares and historical events retain their records
and default to VIEW, preserving their original read-only behavior.

Admins and authorized TLs can grant either level to active executives, including
executives outside their team. VIEW allows reading only; EDIT additionally
allows updating client details through the existing scoped update API.
Independent ownership, supervision, and role grants still apply. Neither level
transfers ownership or permits onward sharing. Management queries use the
independent ownership/supervision scope, never shared edit permission.

Use `POST /api/client-access/<lead_id>/level` with `user_id` and `access_level`
to change an active grant. Grant requests also accept an explicit access level;
omitting it defaults to VIEW for compatibility with existing API callers.
Invalid levels are rejected. Same-level changes and duplicate active grants
return 409. Inactive shares must be regranted. Every level change is recorded
as a grant event with previous/new levels, actor and timestamp; revocations
record the level being removed. Original grant events remain in history.

The access screen provides a level selector for new grants and for each active
recipient. The lead list shows the shared level and exposes Edit only when the
server authorizes it. Downgrading EDIT to VIEW immediately removes shared edit
permission; revocation removes both shared reading and editing on the next
request. Independent access remains effective. Creator and creation timestamps
are never updated by sharing or lead editing.

Tests cover cross-team TL grants, VIEW/EDIT validation, upgrades/downgrades,
revocation, recipient edit access, prevention of onward sharing even after role
changes, ownership preservation, and version-6-to-7 data preservation. Browser
layout and interactive verification remain outstanding. Older code cannot honor
EDIT grants, so prefer a forward fix and retain schema/history on code rollback.

### Module 4.3: client details and CRM fields

Migration 8 (`client_crm_details`) extends `client_leads` without copying,
renaming or deleting existing rows. The same IDs, owners, creation timestamps,
share grants and share events remain authoritative. New fields default to empty
structured data, status `lead`, and active availability. Previous migrations
are unchanged.

The create/edit/details form supports company, business details, multiple named
contact persons, primary and additional email/phone contacts, structured billing
and shipping addresses, notes, and `lead`/`prospect`/`customer` status. Availability
(Active/Inactive) is separate from CRM status. Name remains required; optional
contacts may be empty. Supplied emails are validated and lowercased; phones
normalize separators and require 7?15 digits with optional +. Contact persons
require a name; supplied addresses require line1 and country. Lists are limited
to 20 entries. Unknown/ownership/timestamp/lifecycle fields are rejected.

PUT preserves omitted fields, including structured CRM fields, and supports
explicit empty values to clear optional details. Authorized VIEW recipients can
inspect all client details through a read-only Details form; EDIT recipients
can update details but cannot transfer ownership or reshare.

Duplicate checks reject matching normalized name+company, or an overlapping
email/phone across any contact channel, within the original creator's clients.
Inactive clients are included. These checks run under BEGIN IMMEDIATE so
concurrent duplicate creates cannot both succeed. Separate owners' private
clients are not merged or exposed, and existing duplicate records are never
rewritten by migration. Duplicate errors reveal no matching client IDs/details.
An authorized edit is checked against the original owner's records.

Owners, authorized supervising TLs, Admins and legacy managers can deactivate
or reactivate via `POST /api/leads/<id>/deactivate` and `/activate`. Shared EDIT
permission permits detail editing only, not lifecycle management. Deactivation
retains details, relationships, share levels and event history. Authorized users
can still inspect/edit retained details. New grants or level changes require
reactivation; existing shares can still be revoked. No permanent deletion API
exists. Client Access labels inactive clients and disables grant/level controls.

Tests cover CRM round trips, partial edits, malformed/invalid values, duplicates,
concurrent creation, VIEW/EDIT restrictions, lifecycle authority, historical
preservation and prior RBAC modules. Browser layout/interaction testing remains
outstanding. Read-only analysis of the supplied USD/INR PI templates and the
future client-order field checklist is saved in [docs/pi_order_fields.md](docs/pi_order_fields.md).
No enquiries, orders or PI generation are implemented by this module.

### Module 4.4: client discovery and integration

The Client Leads section now uses server-side discovery. `GET /api/leads`
accepts `q` (company, name, contact person, primary/additional email/phone),
`status` (all/lead/prospect/customer), `active` (all/active/inactive),
`ownership` (all/own/others), `creator` (user ID), `access`
(all/shared/VIEW/EDIT), and `source` (source ID). All filters are ANDed with the
existing visibility SQL; creator filters never grant access. Counts, rows and
page metadata use one read transaction and identical scope. Wildcard characters
in search are literal. Phone queries support formatting separators.

`page` defaults to 1; `page_size` defaults to 25 and is capped at 100.
`sort` allows created/name/company/status and `direction` allows asc/desc;
client ID breaks ties deterministically. Empty/out-of-range pages return no
records with scoped totals. Unknown legacy query parameters remain ignored,
never authorization overrides. Ownership and creator are the same existing
`created_by` relationship, not duplicate fields. Pagination uses LIMIT/OFFSET;
substring/JSON contact searches still scan authorized candidates at large scale.

`GET /api/leads/options` exposes creator options from visible clients and active
configured source choices, without granting source-management access. Inactive
sources appear in filters only when linked to a visible client. The existing
Enquiry Sources table and contact validators remain authoritative. Migration 9
adds one nullable `enquiry_source_id` FK and discovery indexes. New/changed source
links require an active configured Email/WhatsApp source. Existing inactive
links can be retained during unrelated edits; sources and clients are not deleted.
Legacy clients start with no source rather than an inferred assignment.

Details are available for every authorized row, separately from Edit, with
company/business information, structured contacts, saved addresses, notes,
status/availability, creator/owner, shared VIEW/EDIT indicators, enquiry source,
and saved address history. VIEW remains read-only; EDIT permits detail updates
without ownership or onward-sharing rights. Deactivated clients remain visible
by default and can be filtered; existing lifecycle and sharing restrictions are
unchanged. Inactive sources retain their labels on linked client details.

Client billing/default shipping addresses stay separate from future order
shipping/consignee information. Migration 9 adds `client_address_history` with
an initial baseline for existing records. Address updates append snapshots in
the same transaction; previous snapshots are retained. The same-as-billing
checkbox affects only reusable client defaults, not every future order. Read
[the future order address contract](docs/order_address_design.md) together with
[the PI checklist](docs/pi_order_fields.md). No order creation or order/PI/SKU
schema is introduced.

Tests cover scoped search/counts/pagination/sorting, manipulated filters,
creator options, sharing/revocation, inactive clients and sources, source
validation, address snapshot retention and migrations, alongside all earlier
RBAC/CRM tests. Python/JavaScript checks are run locally; browser layout and
interactive verification remain outstanding.

### Module 5.1: client enquiries

**Enquiries** is available from navigation and the client detail view. Each
client may have multiple enquiries; enquiries keep their original client ID,
creator and creation timestamp. Migration 10 adds only `client_enquiries`
with restrictive client/user FKs and indexes for client, status/date and creator.
References are globally unique, case-insensitively, and limited to 80 characters
(letters, digits, spaces, slash, underscore, dot, hyphen). Reference, ISO enquiry
date and subject are required; description is optional (up to 5000 characters).
Statuses: open, in_progress, closed, cancelled. Updated-by and UTC timestamps
are server-assigned. Client reassignment and metadata overrides are rejected.

Client visibility controls enquiry lists, details, search and totals. Client
edit permission controls creation and editing, including EDIT shares and existing
TL supervision/Admin/legacy manager rules. VIEW shares never grant editing.
Creating an enquiry does not establish independent access: revoking the parent
client share removes access even to enquiries that recipient created. Neither
enquiry creation nor EDIT sharing authorizes onward sharing. Inactive clients
retain readable/editable enquiry history but cannot receive new enquiries until
reactivated. Closed/cancelled enquiries remain stored. Management-only soft
deletion is described below.

APIs: `GET /api/enquiries` supports q, client_id, creator, status, page/page_size
(default 25, maximum 100), sort (date/created/reference/status), direction.
Counts and pagination use the same client-scoped query in a single read
transaction. `GET /api/enquiries/<id>` returns 404 for inaccessible/missing IDs.
`POST /api/enquiries` creates; `PUT /api/enquiries/<id>` preserves omitted fields.
Writes recheck permissions inside BEGIN IMMEDIATE; duplicate references return
409 without exposing the conflicting record. The UI provides searchable client
selection, filtered enquiry lists and detail/create/edit views. A client detail
shows its first ten enquiries and links to the full scoped list.

Future enquiry SKU lines should reference `client_enquiries.id` with multiple
lines per enquiry; future orders may reference an enquiry ID and must validate
that their client matches the enquiry's client. No placeholder SKU/order tables
are created here. PI delivery/consignee snapshots remain separate from client
defaults as specified in [the address design](docs/order_address_design.md) and
[PI field checklist](docs/pi_order_fields.md). Enquiries do not modify saved
addresses or implement order management or PI generation.

Tests cover multiple enquiries, case-insensitive duplicates, validation,
immutable relationships, scoped counts/search/pagination, TL isolation,
VIEW/EDIT sharing and revocation, inactive clients, restrictive FKs and migration
preservation, plus prior modules. Browser layout and interactive testing remain
outstanding. Back up the database before upgrades using the guidance above.

### Module 5.2: enquiry SKU lines

Migration 11 adds `enquiry_sku_lines` and `enquiry_line_revisions`, linked to
existing enquiry IDs with restrictive FKs. Client/enquiry ownership and all
applied migrations remain unchanged. Each enquiry has its own independent lines.
Line ID, enquiry ID, creator and creation timestamp are immutable. Create/edit/
remove actions append full timestamped snapshots with actor IDs in the same
transaction as the line change. Removal is soft (`is_active=0`), excludes the
line from current totals, and retains its ID, parent and revision history.

SKU and description are required. Quantity must be a positive whole number,
up to 999999. Historical fractional quantities remain unchanged. Unit price
is nonnegative, up to 999999999.99,
with at most two decimals. Supported currencies are USD and INR, matching the
existing quotation/PI formats. Plain decimal input is required; exponents,
nonfinite values, booleans, invalid precision and client-supplied totals or
relationships are rejected. Quantities/prices are stored as scaled integers;
Python Decimal calculates each rounded line total using ROUND_HALF_UP. Currency
subtotals sum the rounded line totals and are returned as decimal strings.
Mixed currencies are never combined or automatically converted.

APIs: `GET/POST /api/enquiries/<id>/lines`, and
`GET/PUT/DELETE /api/enquiries/<id>/lines/<line_id>`. GET detail also returns
revisions for retained removed lines. All operations derive access from the
parent enquiry/client: VIEW reads only; EDIT and independent client edit rights
manage lines. Parent and line IDs are checked together. Writes revalidate rights
inside BEGIN IMMEDIATE; revoked client access blocks further reading/writing.
Existing enquiries on inactive clients remain manageable under their client
rights, consistent with Module 5.1. No line restoration API is added.

`POST /api/enquiries/<id>/sku-lookup` accepts a single SKU and returns a draft
for review, without saving or overwriting lines. It reuses `fetch_sku` and its
15-minute Shopify cache, including sale-price selection. Existing lookup assumes
Shopify pricing is USD; this module preserves that assumption and does not infer
currency conversion. Requested quantity defaults to one, not available stock.
Lookup requires enquiry edit rights and rechecks authorization after the network
call. Missing SKU/price and provider failure produce controlled errors. Users
can enter items/prices manually, including INR. Stock/condition information is
shown as a lookup hint rather than a stock reservation or order commitment.

The enquiry detail page provides the line table, SKU fetch, create/edit form,
soft removal controls and per-currency subtotals. VIEW recipients have no write
controls. Future orders should copy a selected revision's immutable values into
independent order lines and optionally reference the original line/revision ID;
they must validate the enquiry/client relationship. Never reuse mutable enquiry
lines as order/PI financial records. Addresses and delivery snapshots remain
separate as described in docs/order_address_design.md; docs/pi_order_fields.md
covers later HSN/UOM/condition/tax/PI fields, which are not implemented here.

Tests cover decimal rounding, mixed currency totals, validation, stable IDs,
revision rollback/history, soft removal, parent isolation, VIEW/EDIT rights,
revocation including during SKU lookup, mocked provider outcomes, migrations,
and earlier RBAC/CRM modules. Browser layout and interactive testing remain
outstanding. No orders, shipping details or PI generation are implemented.

### Required SKU cart and enquiry deal currency

Migration 12 adds nullable `client_enquiries.deal_currency` (USD/INR). Existing
records are not assigned a guessed currency; mixed/older enquiries remain
editable and show Legacy / not set until reviewed. Previous migrations remain
unchanged. New enquiries now require an explicit deal currency and 1?50 complete
initial SKU lines. POST includes `lines` alongside enquiry fields; each initial
line must use the chosen currency. Header, line records and revisions commit
atomically, so invalid rows cannot leave an empty enquiry behind.

The create form includes multiline/comma-separated SKU entry, bulk Look Up SKUs,
manual rows, editable SKU/description/quantity/unit price and row removal. Failed
lookups must be completed manually or removed. The selected deal currency applies
to the new draft cart. Changing a draft's currency clears its prices: users must
fetch again or enter prices explicitly. Existing lines retain independent,
editable currencies; changing deal metadata never silently converts saved prices.
Edit enquiry opens both the header and its saved SKU section.

`POST /api/enquiries/sku-lookup` accepts exactly one of client_id/enquiry_id,
1?50 skus, and currency. It uses existing Shopify SKU/cache and USD/INR rate
services. INR drafts convert the Shopify USD price with Decimal rounding, and
show the rate used. If conversion is unavailable, the draft price stays empty;
USD amounts are never labelled INR. Each lookup is reviewed before persistence,
and authority is checked before and after provider calls. No stock is reserved.
The reused rate service can return its cached fallback; the displayed rate is
for enquiry estimates and should be reviewed before future order/PI pricing.

Add SKU line uses the same bulk review UI; `POST /api/enquiries/<id>/lines/bulk`
atomically saves complete reviewed rows. Individual saved-line editing and
decimal totals retain VIEW/EDIT rules; deletion requires management rights. Each
enquiry keeps its own independent line records, revisions, and currency metadata.
Creation reference/date/subject and every saved SKU field remain editable by
client-authorized users; immutable ownership and parent IDs are preserved.

### Management-only deletion

Delete actions are available on client lists/details, enquiry lists/details,
and persisted SKU lines. Confirmation is required in the UI. Backend DELETE
APIs independently authorize the current account and original client's scope:
Admins and legacy managers can delete any accessible record; Sales TLs can
delete their own clients and those of their assigned active executives.
Sales Executives cannot delete persisted records, including their own records
or clients shared with EDIT access. Sharing never grants deletion authority.

`DELETE /api/leads/<id>` and `DELETE /api/enquiries/<id>` mark records deleted
with the actor and timestamp. Migration 13 adds nullable deletion fields and
indexes without modifying earlier migrations or existing rows. Deleted records
are excluded from lists, filters, counts, sharing screens and normal APIs.
Deleting a client also hides its enquiries and lines; deleting an enquiry
also makes its lines inaccessible. These descendants are retained in the
database rather than modified or removed. Ownership, addresses, sharing history,
references and foreign keys remain intact. References remain reserved.

`DELETE /api/enquiries/<id>/lines/<line_id>` reuses soft removal and revision
history, now restricted to the same management roles and client scope. All
deletion operations are transactional. Deactivated clients remain distinct
from deleted clients; the activation endpoint cannot restore deleted records.
Unsaved draft items can still be adjusted or removed before submission.

### TL Dashboard

The separate **TL Dashboard** sidebar page (`/tl-dashboard`) is available to
Sales TLs, admins and legacy managers with `management.view`. TL reports cover
the TL and their assigned active executives; admins and managers see all users.
The existing Dashboard page remains available separately.

User and inclusive date filters apply to client creation counts, saved PI counts
and SKU lookup history. Clients are attributed to their creator and PIs to the
user who generated them. Removed clients/orders/PIs are excluded from available
PI lists. **See PI list** opens invoices grouped by client, with the original
Excel and available PDF downloads, under current client access permissions.

SKU history includes quotation lookups and manual enquiry/order item lookups,
including missing SKUs. Automatic stock checks when saving items are excluded.
Each SKU counts once per lookup request; legacy comma-separated batches are
included. New lookup timestamps use IST explicitly; historical local lookup
timestamps are interpreted as IST. Other record timestamps are converted from
UTC for date filtering and display.

Admins and legacy managers can preview and delete lookup records strictly older
than a cutoff date. Cleanup covers all users regardless of dashboard filters,
requires confirmation of the current matching count, and records an audit entry.
Records on the selected date, client/order records and generated PIs are retained.

Application startup applies migration 13 using the existing migration runner.
Follow the backup instructions above before upgrading. No automatic purge or
restore endpoint is included. Tests cover management permissions, cross-team
isolation, sharing, descendant access, historical preservation and upgrades.
