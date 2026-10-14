"""Ordered, additive schema definitions; applied migrations are immutable."""

LEGACY_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    UNIQUE NOT NULL,
            password_hash TEXT   NOT NULL,
            role         TEXT    DEFAULT 'user',
            created_at   TEXT    DEFAULT (datetime('now','localtime'))
        )""",
    """CREATE TABLE IF NOT EXISTS search_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name   TEXT    DEFAULT 'Unknown',
            user_ip     TEXT,
            skus        TEXT,
            found_count INTEGER DEFAULT 0,
            not_found   INTEGER DEFAULT 0,
            ts          TEXT    DEFAULT (datetime('now','localtime'))
        )""",
    """CREATE TABLE IF NOT EXISTS copy_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name   TEXT    DEFAULT 'Unknown',
            user_ip     TEXT,
            copy_type   TEXT,
            sku_count   INTEGER DEFAULT 0,
            ts          TEXT    DEFAULT (datetime('now','localtime'))
        )""",
    """CREATE INDEX IF NOT EXISTS idx_search_ts   ON search_logs(ts)""",
    """CREATE INDEX IF NOT EXISTS idx_search_user ON search_logs(user_name)""",
    """CREATE INDEX IF NOT EXISTS idx_copy_ts     ON copy_logs(ts)""",
)

# users.role remains the authority for the existing authentication system.
# These catalogs do not grant permissions until a future module uses them.
CRM_FOUNDATION = (
    """CREATE TABLE roles (
        code TEXT PRIMARY KEY NOT NULL CHECK (length(trim(code)) > 0),
        description TEXT NOT NULL DEFAULT ''
    )""",
    """INSERT INTO roles (code, description) VALUES
        ('user', 'Existing quotation user'),
        ('manager', 'Existing quotation manager')""",
    """CREATE TABLE permissions (
        code TEXT PRIMARY KEY NOT NULL CHECK (length(trim(code)) > 0),
        description TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE role_permissions (
        role_code TEXT NOT NULL REFERENCES roles(code) ON DELETE RESTRICT,
        permission_code TEXT NOT NULL
            REFERENCES permissions(code) ON DELETE RESTRICT,
        PRIMARY KEY (role_code, permission_code)
    )""",
    """CREATE INDEX idx_role_permissions_permission
        ON role_permissions(permission_code)""",
    """CREATE TABLE enquiry_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE CHECK (length(trim(code)) > 0),
        name TEXT NOT NULL CHECK (length(trim(name)) > 0),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )""",
    """CREATE INDEX idx_enquiry_sources_active_name
        ON enquiry_sources(is_active, name)""",
    """CREATE TABLE audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        actor_name TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL CHECK (length(trim(action)) > 0),
        entity_type TEXT NOT NULL CHECK (length(trim(entity_type)) > 0),
        entity_id TEXT,
        details TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT
            (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )""",
    """CREATE INDEX idx_audit_logs_actor_time
        ON audit_logs(actor_user_id, created_at)""",
    """CREATE INDEX idx_audit_logs_entity_time
        ON audit_logs(entity_type, entity_id, created_at)""",
    """CREATE INDEX idx_audit_logs_time ON audit_logs(created_at)""",
)

# Add new versions here; never edit the name or SQL of an applied version.
MIGRATIONS = (
    (1, 'legacy_baseline', LEGACY_SCHEMA),
    (2, 'crm_foundation', CRM_FOUNDATION),
)
