# Security change log

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
