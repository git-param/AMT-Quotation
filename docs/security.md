# Security change log

## Device registration (migration 32)

Every browser session must supply a physical adapter MAC address and device name after password validation. New registrations remain pending until an approved Admin uses Dashboard > Device Management. The waiting screen polls approval status every five seconds. Rejected and revoked registrations stay blocked; a new request does not reset those decisions. A MAC is unique across accounts. Admins cannot decide their own registration through the web API.

For Windows, start the server as usual and run `python desktop_launcher.py --url https://your-server/login` from the project directory on the employee PC. The launcher uses only Python's standard library; the Flask server still uses the project environment. It chooses an active physical adapter, preferring one with a default network route, and opens the login page in the user's browser. If Windows denies access to `Get-NetAdapter`, it reads `ipconfig /all` instead. It supplies the MAC and Windows computer name to the login request without showing device fields. A direct browser visit cannot read a physical MAC and shows instructions to use the launcher. No MAC is generated when an adapter is unavailable.

For the first Admin only, sign in to create a pending registration, then run this command locally on the database host after checking the request and MAC:

```text
python -m backend.security.bootstrap_device --database database/quotation.db --username ADMIN_USERNAME --mac 02:11:22:33:44:55
```

Use the actual database path from `backend/config.py`. This local command records an audit event. Subsequent approvals use Device Management. The migration leaves existing user and business records intact, but existing sessions without a registered device must sign in again.

MAC addresses are client reported matching identifiers. They can be spoofed and do not prove possession of a physical device. The launcher and browser request can be altered by a user. Strong device assurance would require managed certificates or comparable hardware backed attestation. Legacy API keys cannot access protected APIs because they have no approved device session.

This document records security releases, operating requirements, and known limits.

## Version 1 — 2026-10-19

### Implemented

- Added one revocable server-side session per account. A new login invalidates the previous login for that account. Sessions have a 30-minute idle timeout and 12-hour absolute lifetime by default.
- Password changes, administrator password resets, and account deactivation revoke existing sessions. Session cookies contain an opaque random token; only its SHA-256 hash is stored in SQLite.
- Added synchronizer-token CSRF protection for authenticated POST, PUT, PATCH, and DELETE requests. The shared frontend request wrapper sends the token from a strict same-site cookie in `X-CSRF-Token`.
- Added Redis fixed-window rate limiting when `REDIS_URL` is configured. A bounded in-memory fallback supports local development and a temporary Redis outage on a single web process.
- Applied limits to source IP traffic, authenticated API traffic, login attempts by IP and account, SKU lookups, and PI mutations. Rejections return HTTP 429 with `Retry-After`.
- Added append-only `security_events` for login success/failure, throttling, logout, CSRF rejection, password changes, and basic credential-stuffing signals.
- Added `Secure`/`HttpOnly`/`SameSite` cookie configuration, 2 MiB request limits, clickjacking protection, MIME-sniffing protection, referrer policy, permissions policy, opener isolation, and HSTS when HTTPS mode is enabled.
- Removed direct trust of client-provided `X-Forwarded-For`. Proxy headers are used only through Werkzeug `ProxyFix` when `AMT_TRUSTED_PROXY_COUNT` is explicitly configured.
- Removed the hard-coded `manager/admin123` bootstrap. A first admin is created only from an explicit 12+ character bootstrap password environment variable.
- New and changed passwords now require 12 to 128 characters.

### Required production configuration

```text
AMT_HTTPS=true
REDIS_URL=redis://:<password>@<private-redis-host>:6379/0
AMT_TRUSTED_PROXY_COUNT=1
AMT_SESSION_IDLE_MINUTES=30
AMT_SESSION_ABSOLUTE_HOURS=12
```

Set `AMT_TRUSTED_PROXY_COUNT` to the exact number of trusted reverse proxies between the client and Waitress. Leave it unset when Waitress receives client connections directly. An incorrect value allows forged client IP information or records the proxy instead of the client.

For a new empty database only, set the bootstrap credentials before the first startup:

```text
AMT_BOOTSTRAP_ADMIN_USERNAME=manager
AMT_BOOTSTRAP_ADMIN_PASSWORD=<unique-password-of-at-least-12-characters>
```

Remove both bootstrap variables after the account is created. Existing databases are not changed.

Redis must be private and unavailable from the public internet. For multiple application processes or hosts, Redis is required because the memory fallback is local to one process and resets on restart.

### Known limits and next work

- One active session is enforced per account. A browser cannot provide a trustworthy physical-device identity; managed device certificates or WebAuthn enrollment are required for a physical-device policy.
- Security events are stored but there is no administrator review screen or external alert delivery yet.
- MFA is not implemented. Administrator accounts should receive TOTP or WebAuthn MFA before public internet exposure.
- A strict Content Security Policy is not enabled because existing pages contain inline scripts/styles and dynamic HTML. Remove those patterns and deploy CSP in report-only mode before enforcement.
- Redis fallback favors application availability. Login endpoints retain their local limits during Redis failure, but multiple processes do not share fallback counters.
- HTTPS must be terminated at the reverse proxy. `AMT_HTTPS=true` must only be enabled when users access the application exclusively through HTTPS.

### Verification

- 3 focused security tests pass: single-session invalidation, CSRF enforcement, response headers, and login event recording.
- 21 migration tests pass, including upgrades and concurrent startup.
- 16 RBAC and account lifecycle tests pass.
- 9 affected sidebar and account-management frontend tests pass.
- The complete Python run executed 257 tests with 6 failures in pre-existing party text, GST/PDF layout, and live exchange-rate expectations. The live-rate failure was reproduced on an untouched checkout of the starting commit; the other five were already present in the previous full-suite baseline.
