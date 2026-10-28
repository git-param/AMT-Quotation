# Scalability change log

Record each scalability release here with its deployment steps, evidence, and remaining limits.

## Version 2 — 2026-10-20

- Creating or updating a PI preview validates the draft and returns the editable layout without rendering a PDF. PDF rendering runs when the user opens a PDF preview or issues the invoice, avoiding a duplicate render on every editor action.
- The saved and unsaved PDF preview endpoints close their SQLite read connections before rendering. Normal and bulk PDF fonts now register under one lock so simultaneous first requests cannot race.
- Verification: 14 focused native PI preview tests passed, including four simultaneous PDF requests in separate sessions. The full native PI suite ran 45 tests; three existing party/GST expectation failures and one bulk XLSX `date_label` error remain. These were outside the preview timing changes.
- This reduces preview latency and database contention. PDF and workbook rendering remain CPU intensive in a single Waitress process; measure representative concurrent export traffic before sizing production capacity.

## Version 1 — 2026-10-19

### Implemented

- Added `backend/scalability/serve.py` to run Flask under Waitress. The default binds to `127.0.0.1:5062` with 16 request threads and a 256-connection limit. Put an HTTPS reverse proxy in front for remote access.
- Added `backend/scalability/rate_scheduler.py` so the periodic currency update runs in one separate process, independent of the web server. Keep exactly one scheduler instance running. The old `python app.py` development command still starts its embedded scheduler.
- Added `backend/scalability/sqlite.py`. App connections have a 30-second busy timeout and foreign keys enabled. Startup enables persistent SQLite WAL mode after migrations. Keep the database and its WAL files on the **same local host**, on a local filesystem. Do not put the SQLite database on a network share.
- PI preview PDF validation and PI PDF/XLSX issuance now render before the `BEGIN IMMEDIATE` write transaction. The write phase rechecks access, order version and preview content; a changed snapshot returns HTTP 409. Issuance remains idempotent and commits both files, invoice metadata, order status and audit history together.
- Added `backend/scalability/load_test.py` for a read-only, authenticated concurrent-user probe. It reports p50, p95, p99, errors and elapsed time. It uses one account in separate sessions and does **not** measure simultaneous writes or PI generation.

### Deploy on Windows

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m backend.scalability.serve --host 127.0.0.1 --port 5062 --threads 16
```

In a **separate** long-lived process:

```powershell
.\.venv\Scripts\python.exe -m backend.scalability.rate_scheduler
```

Use one web server command and one scheduler command. Both use the existing `database/quotation.db` and `backend/secret.key`. Back them up together using SQLite's backup API or an SQLite-aware tool; copying a live `.db` file alone can miss committed WAL data. Install a service supervisor for automatic restart, and terminate TLS at a reverse proxy before allowing remote users.

### Measure

In a test environment with representative data, set credentials for a dedicated test account, then run:

```powershell
$env:AMT_LOAD_USERNAME = 'load_test_user'
$env:AMT_LOAD_PASSWORD = '<test-account-password>'
.\.venv\Scripts\python.exe -m backend.scalability.load_test --users 100 --requests-per-user 10
```

The command ramps up logins four at a time, then starts 100 authenticated sessions together for 1,000 GET requests across `/api/me`, `/api/leads`, and `/api/orders`. Observe server CPU, memory, response times and SQLite lock errors alongside its output. Use a staging copy and a separate scenario for login bursts, concurrent order edits, Shopify lookups and PI generation before declaring 100-user capacity. Tune Waitress threads based on those measurements; 100 users does not imply 100 web threads.

Local smoke result on 2026-10-19: a temporary empty database, one account in 100 separate sessions, 16 Waitress threads and a 256-connection limit completed 1,000 GET requests with 0 errors. GET latency was p50 819 ms, p95 892 ms and p99 937 ms. Elapsed time including the login ramp was 31.8 seconds. These numbers are a functional baseline for this machine; they do not represent a populated production database or write/export load.

Python verification: 21 migration tests passed; new tests confirmed WAL/busy timeout, rendering outside the writer lock, and rejection of a preview changed during rendering. The full suite ran 254 tests with five failures in existing party-text, GST-warning and PDF-spacing expectations. All five were reproduced on an untouched checkout of the starting commit.

### Remaining limits

- SQLite WAL still permits only one writer at a time. Several other order and enquiry writes perform network checks while holding `BEGIN IMMEDIATE`; these need the same snapshot/revalidation treatment if the mixed-write load test exposes contention.
- Shopify SKU caching is in process memory and does not coordinate across multiple web processes. Shopify API throttling may limit lookup throughput.
- Invoice PDF/XLSX bytes are still stored as SQLite BLOBs. Move them to shared object storage when database growth or backup duration becomes a problem.
- Multi-host web scaling requires a shared database such as PostgreSQL, a shared cache, and coordinated background jobs. This version is designed for one application host.


PI generation now uses a process-shared file lock per database (see
`backend/scalability/pi_generation.py`). Competing native/legacy generation
requests receive HTTP 202 and the native preview waits/retries with a loading
indicator. Preview operations do not allocate PI numbers. Native issuance reads
a candidate under the generation gate, renders without a SQLite writer lock,
then rechecks and atomically confirms the counter with both stored files.
