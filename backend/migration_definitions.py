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

# Existing role values remain unchanged; legacy roles get equivalent grants.
RBAC_SCHEMA = (
    "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 "
    "CHECK (is_active IN (0, 1))",
    "CREATE INDEX idx_users_active_role ON users(is_active, role)",
    "INSERT INTO roles (code, description) VALUES "
    "('sales_executive', 'Sales Executive'), "
    "('sales_tl', 'Sales TL'), ('admin', 'Admin')",
    "INSERT INTO permissions (code, description) VALUES "
    "('quotation.use', 'Use quotation lookup and exports'), "
    "('account.self', 'View profile and change own password'), "
    "('management.view', 'View quotation activity dashboard'), "
    "('users.manage', 'Create users, assign roles and deactivate accounts')",
    "INSERT INTO role_permissions (role_code, permission_code) "
    "SELECT roles.code, permissions.code FROM roles CROSS JOIN permissions "
    "WHERE roles.code IN ('user', 'manager', 'sales_executive', "
    "'sales_tl', 'admin') AND permissions.code IN "
    "('quotation.use', 'account.self')",
    "INSERT INTO role_permissions (role_code, permission_code) VALUES "
    "('manager', 'management.view'), ('manager', 'users.manage'), "
    "('sales_tl', 'management.view'), ('admin', 'management.view'), "
    "('admin', 'users.manage')",
)

SOURCE_SCHEMA = (
    "ALTER TABLE enquiry_sources ADD COLUMN source_type TEXT "
    "CHECK (source_type IN ('email', 'whatsapp'))",
    "ALTER TABLE enquiry_sources ADD COLUMN contact_value TEXT "
    "CHECK (contact_value IS NULL OR length(trim(contact_value)) > 0)",
    "ALTER TABLE enquiry_sources ADD COLUMN updated_at TEXT",
    "CREATE UNIQUE INDEX idx_enquiry_sources_contact "
    "ON enquiry_sources(source_type, contact_value COLLATE NOCASE) "
    "WHERE contact_value IS NOT NULL",
    "INSERT INTO permissions (code, description) VALUES "
    "('sources.manage', 'Manage email and WhatsApp enquiry sources')",
    "INSERT INTO role_permissions (role_code, permission_code) VALUES "
    "('admin', 'sources.manage'), ('sales_tl', 'sources.manage'), "
    "('manager', 'sources.manage')",
)

LEAD_SCHEMA = (
    "ALTER TABLE users ADD COLUMN supervisor_user_id INTEGER "
    "REFERENCES users(id) ON DELETE SET NULL "
    "CHECK (supervisor_user_id IS NULL OR supervisor_user_id != id)",
    "CREATE INDEX idx_users_supervisor ON users(supervisor_user_id)",
    "CREATE TABLE client_leads ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 150), "
    "company TEXT NOT NULL DEFAULT '' CHECK (length(company) <= 150), "
    "email TEXT NOT NULL DEFAULT '' CHECK (length(email) <= 254), "
    "phone TEXT NOT NULL DEFAULT '' CHECK (length(phone) <= 40), "
    "notes TEXT NOT NULL DEFAULT '' CHECK (length(notes) <= 2000), "
    "created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, "
    "created_at TEXT NOT NULL DEFAULT "
    "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))",
    "CREATE INDEX idx_client_leads_creator_id ON client_leads(created_by, id)",
    "CREATE TABLE client_lead_shares ("
    "lead_id INTEGER NOT NULL REFERENCES client_leads(id) ON DELETE RESTRICT, "
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, "
    "PRIMARY KEY (lead_id, user_id))",
    "CREATE INDEX idx_client_lead_shares_user "
    "ON client_lead_shares(user_id, lead_id)",
    "INSERT INTO permissions (code, description) VALUES "
    "('leads.view_all', 'View all client leads'), "
    "('leads.view_team', 'View supervised executive leads')",
    "INSERT INTO role_permissions (role_code, permission_code) VALUES "
    "('admin', 'leads.view_all'), ('manager', 'leads.view_all'), "
    "('sales_tl', 'leads.view_team')",
)

SHARING_SCHEMA = (
    "ALTER TABLE client_lead_shares ADD COLUMN is_active INTEGER NOT NULL "
    "DEFAULT 1 CHECK (is_active IN (0, 1))",
    "ALTER TABLE client_lead_shares ADD COLUMN granted_by INTEGER "
    "REFERENCES users(id) ON DELETE RESTRICT",
    "ALTER TABLE client_lead_shares ADD COLUMN granted_at TEXT",
    "ALTER TABLE client_lead_shares ADD COLUMN revoked_by INTEGER "
    "REFERENCES users(id) ON DELETE RESTRICT",
    "ALTER TABLE client_lead_shares ADD COLUMN revoked_at TEXT",
    "CREATE INDEX idx_lead_shares_active_user "
    "ON client_lead_shares(user_id, is_active, lead_id)",
    "CREATE TABLE client_share_events ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "lead_id INTEGER NOT NULL REFERENCES client_leads(id) ON DELETE RESTRICT, "
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, "
    "action TEXT NOT NULL CHECK (action IN ('grant', 'revoke')), "
    "actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, "
    "actor_name TEXT NOT NULL, occurred_at TEXT NOT NULL DEFAULT "
    "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))",
    "CREATE INDEX idx_share_events_lead_id "
    "ON client_share_events(lead_id, id)",
    "INSERT INTO permissions (code, description) VALUES "
    "('leads.share_manage', 'Manage client lead sharing')",
    "INSERT INTO role_permissions (role_code, permission_code) VALUES "
    "('admin', 'leads.share_manage'), ('manager', 'leads.share_manage'), "
    "('sales_tl', 'leads.share_manage')",
)

SHARE_LEVEL_SCHEMA = (
    "ALTER TABLE client_lead_shares ADD COLUMN access_level TEXT NOT NULL "
    "DEFAULT 'VIEW' CHECK (access_level IN ('VIEW', 'EDIT'))",
    "ALTER TABLE client_share_events ADD COLUMN access_level TEXT NOT NULL "
    "DEFAULT 'VIEW' CHECK (access_level IN ('VIEW', 'EDIT'))",
    "ALTER TABLE client_share_events ADD COLUMN previous_access_level TEXT "
    "CHECK (previous_access_level IN ('VIEW', 'EDIT'))",
)

CRM_DETAIL_SCHEMA = (
    "ALTER TABLE client_leads ADD COLUMN business_details TEXT NOT NULL "
    "DEFAULT '' CHECK (length(business_details) <= 2000)",
    "ALTER TABLE client_leads ADD COLUMN contact_persons_json TEXT NOT NULL "
    "DEFAULT '[]'",
    "ALTER TABLE client_leads ADD COLUMN emails_json TEXT NOT NULL "
    "DEFAULT '[]'",
    "ALTER TABLE client_leads ADD COLUMN phones_json TEXT NOT NULL "
    "DEFAULT '[]'",
    "ALTER TABLE client_leads ADD COLUMN billing_address_json TEXT NOT NULL "
    "DEFAULT '{}'",
    "ALTER TABLE client_leads ADD COLUMN shipping_address_json TEXT NOT NULL "
    "DEFAULT '{}'",
    "ALTER TABLE client_leads ADD COLUMN status TEXT NOT NULL DEFAULT 'lead' "
    "CHECK (status IN ('lead', 'prospect', 'customer'))",
    "ALTER TABLE client_leads ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 "
    "CHECK (is_active IN (0, 1))",
    "CREATE INDEX idx_clients_owner_status "
    "ON client_leads(created_by, is_active, status)",
)

# Add new versions here; never edit the name or SQL of an applied version.
MIGRATIONS = (
    (1, 'legacy_baseline', LEGACY_SCHEMA),
    (2, 'crm_foundation', CRM_FOUNDATION),
    (3, 'rbac', RBAC_SCHEMA),
    (4, 'enquiry_sources', SOURCE_SCHEMA),
    (5, 'private_client_leads', LEAD_SCHEMA),
    (6, 'client_sharing', SHARING_SCHEMA),
    (7, 'client_share_levels', SHARE_LEVEL_SCHEMA),
    (8, 'client_crm_details', CRM_DETAIL_SCHEMA),
)
