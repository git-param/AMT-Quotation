# AMT Quotation

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
