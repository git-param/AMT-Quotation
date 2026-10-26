"""Test schema upgrades without Flask or changes to production data."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import database
from backend.config import DB_PATH
from backend.migration_definitions import LEGACY_SCHEMA, MIGRATIONS
from backend.migrations import (
    MigrationError,
    connect_database,
    migrate_database,
    migration_status,
)


@contextmanager
def test_connection(path):
    """Commit test writes and close handles explicitly for Windows cleanup."""
    connection = connect_database(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def legacy_snapshot(connection):
    """Capture legacy schema, rows, and sequences without printing values."""
    tables = ('users', 'search_logs', 'copy_logs')
    snapshot = {}
    for table in tables:
        snapshot[table] = connection.execute(
            'SELECT ' + ', '.join(row[1] for row in connection.execute(
                'PRAGMA table_info(' + table + ')'
            ) if row[1] not in ('is_active', 'supervisor_user_id', 'department', 'phone_country_code', 'phone_number'))
            + ' FROM ' + table + ' ORDER BY id'
        ).fetchall()
        snapshot[table + '_columns'] = [
            row for row in connection.execute(
                'PRAGMA table_info(' + table + ')'
            ) if row[1] not in ('is_active', 'supervisor_user_id', 'department', 'phone_country_code', 'phone_number')
        ]
        snapshot[table + '_schema'] = connection.execute(
            'SELECT type, name, sql FROM sqlite_master '
            "WHERE tbl_name = ? AND name NOT IN "
            "('idx_users_active_role', 'idx_users_supervisor') "
            "AND NOT (type = 'table' AND name = 'users') "
            'ORDER BY type, name', (table,)
        ).fetchall()
    snapshot['sequences'] = connection.execute(
        "SELECT name, seq FROM sqlite_sequence "
        "WHERE name IN ('users', 'search_logs', 'copy_logs') ORDER BY name"
    ).fetchall()
    return snapshot


class MigrationTests(unittest.TestCase):
    """Validate transaction safety, compatibility, and new constraints."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'quotation.db'

    def create_legacy_database(self):
        with test_connection(self.path) as connection:
            for statement in LEGACY_SCHEMA:
                connection.execute(statement)
            connection.execute(
                'INSERT INTO users (username, password_hash, role) '
                "VALUES ('fixture', 'noncredential-test-value', 'user')"
            )
            connection.execute(
                'INSERT INTO search_logs (user_name, skus, found_count) '
                "VALUES ('fixture', '001,002', 2)"
            )
            connection.execute(
                'INSERT INTO copy_logs (user_name, copy_type, sku_count) '
                "VALUES ('fixture', 'formal_usd', 2)"
            )

    def test_fresh_schema_and_idempotency(self):
        self.assertEqual(
            migrate_database(self.path),
            list(range(1, len(MIGRATIONS) + 1))
        )
        self.assertEqual(migrate_database(self.path), [])
        self.assertEqual(
            migration_status(self.path),
            {'applied': list(range(1, len(MIGRATIONS) + 1)),
             'pending': []}
        )
        with test_connection(self.path) as connection:
            self.assertEqual(
                connection.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute('PRAGMA integrity_check').fetchone()[0],
                'ok',
            )
            self.assertEqual(
                connection.execute('PRAGMA foreign_key_check').fetchall(), []
            )

    def test_existing_legacy_api_key_survives_migration(self):
        self.create_legacy_database()
        with test_connection(self.path) as connection:
            connection.execute(
                "CREATE TABLE api_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "key TEXT UNIQUE NOT NULL, label TEXT DEFAULT '', "
                "created_at TEXT DEFAULT (datetime('now','localtime')), last_used TEXT)"
            )
            connection.execute(
                'INSERT INTO api_keys(key, label) VALUES (?, ?)',
                ('amtq-existing-key', 'Inbox'),
            )
        migrate_database(self.path)
        with test_connection(self.path) as connection:
            row = connection.execute(
                'SELECT id, key, label FROM api_keys'
            ).fetchone()
            self.assertEqual(tuple(row), (1, 'amtq-existing-key', 'Inbox'))

    def test_existing_schema_and_records_are_unchanged(self):
        self.create_legacy_database()
        with test_connection(self.path) as connection:
            before = legacy_snapshot(connection)
        migrate_database(self.path)
        with test_connection(self.path) as connection:
            self.assertTrue(before == legacy_snapshot(connection))

    def test_department_upgrade_preserves_users_and_defaults_to_unassigned(self):
        migrate_database(self.path, MIGRATIONS[:23])
        with test_connection(self.path) as connection:
            connection.execute(
                "INSERT INTO users(username,password_hash,role) "
                "VALUES('existing','test-hash','admin')"
            )
            before = connection.execute('SELECT * FROM users').fetchall()
        self.assertEqual(migrate_database(self.path, MIGRATIONS[:25]), [24, 25])
        with test_connection(self.path) as connection:
            rows = connection.execute('SELECT * FROM users').fetchall()
            self.assertEqual([row[:-1] for row in rows], before)
            self.assertEqual(rows[0][-1], '')
        self.assertEqual(migrate_database(self.path, MIGRATIONS[:25]), [])

    def test_configured_departments_preserve_and_import_existing_values(self):
        migrate_database(self.path, MIGRATIONS[:24])
        with test_connection(self.path) as connection:
            for name, department in [('one', 'Sales'), ('two', 'sales'), ('three', ''), ('four', 'Support')]:
                connection.execute('INSERT INTO users(username,password_hash,department) VALUES(?,?,?)',
                                   (name, 'fixture', department))
            before = connection.execute('SELECT * FROM users ORDER BY id').fetchall()
        self.assertEqual(migrate_database(self.path, MIGRATIONS[:25]), [25])
        with test_connection(self.path) as connection:
            self.assertEqual(connection.execute('SELECT * FROM users ORDER BY id').fetchall(), before)
            self.assertEqual(connection.execute('SELECT name FROM departments ORDER BY name').fetchall(),
                             [('Sales',), ('Support',)])

    def test_phone_upgrade_preserves_users_and_leaves_phone_empty(self):
        migrate_database(self.path, MIGRATIONS[:25])
        with test_connection(self.path) as connection:
            connection.execute("INSERT INTO users(username,password_hash,department) VALUES('existing','fixture','Sales')")
            before = connection.execute('SELECT * FROM users').fetchall()
        self.assertEqual(migrate_database(self.path, MIGRATIONS[:26]), [26])
        with test_connection(self.path) as connection:
            rows = connection.execute('SELECT * FROM users').fetchall()
            self.assertEqual([row[:-2] for row in rows], before)
            self.assertEqual(rows[0][-2:], ('', ''))
        self.assertEqual(migrate_database(self.path, MIGRATIONS[:26]), [])

    def test_department_prefix_upgrade_preserves_departments_and_users(self):
        migrate_database(self.path, MIGRATIONS[:26])
        with test_connection(self.path) as connection:
            connection.execute("INSERT INTO departments(name) VALUES('Sales')")
            connection.execute("INSERT INTO users(username,password_hash,department) VALUES('fixture','fixture','Sales')")
            users = connection.execute('SELECT * FROM users').fetchall()
            departments = connection.execute('SELECT * FROM departments').fetchall()
        self.assertEqual(migrate_database(self.path, MIGRATIONS[:27]), [27])
        with test_connection(self.path) as connection:
            self.assertEqual(connection.execute('SELECT * FROM users').fetchall(), users)
            rows = connection.execute('SELECT * FROM departments').fetchall()
            self.assertEqual([row[:-1] for row in rows], departments)
            self.assertEqual(rows[0][-1], '')

    def test_multi_currency_upgrade_preserves_rows_indexes_files_and_sequences(self):
        migrate_database(self.path, MIGRATIONS[:27])
        tables = ('client_enquiries','enquiry_sku_lines','client_orders','order_sku_lines','order_invoices')
        with test_connection(self.path) as connection:
            connection.execute("INSERT INTO users(username,password_hash) VALUES('fixture','test')")
            connection.execute("INSERT INTO client_leads(name,created_by) VALUES('Client',1)")
            connection.execute("INSERT INTO client_orders(reference,client_id,order_date,currency,created_by,updated_by) VALUES('ORDER-1',1,'2026-10-17','USD',1,1)")
            connection.execute("INSERT INTO order_sku_lines(order_id,sku,description,quantity_milli,unit_price_minor,currency,created_by,updated_by) VALUES(1,'SKU','Part',1000,100,'USD',1,1)")
            connection.execute("INSERT INTO order_invoices(order_id,reference,currency,snapshot_json,workbook,created_by,workbook_format,pdf) VALUES(1,'PI-1','USD','{}',?,1,'xlsx',?)",(b'workbook',b'pdf'))
            connection.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='client_orders'")
            before = {table: connection.execute('SELECT * FROM '+table).fetchall() for table in tables}
            indexes = connection.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name").fetchall()
        self.assertEqual(migrate_database(self.path), [28, 29, 30, 31, 32, 33])
        with test_connection(self.path) as connection:
            for table in tables:
                rows = connection.execute('SELECT * FROM '+table).fetchall()
                if table == 'client_orders':
                    self.assertEqual([row[:-1] for row in rows], before[table])
                    self.assertTrue(all(row[-1] == 0 for row in rows))
                else:
                    self.assertEqual(rows, before[table])
            current_indexes = connection.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name").fetchall()
            self.assertTrue(set(indexes).issubset(set(current_indexes)))
            cursor=connection.execute("INSERT INTO client_orders(reference,client_id,order_date,currency,created_by,updated_by) VALUES('ORDER-2',1,'2026-10-17','AED',1,1)")
            self.assertEqual(cursor.lastrowid,101)
            connection.execute("UPDATE order_sku_lines SET currency='GBP'")
            connection.execute("UPDATE order_invoices SET currency='EUR'")
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_reusable_references_upgrade_preserves_records_files_and_sequences(self):
        migrate_database(self.path, MIGRATIONS[:20])
        tables = ('client_orders','order_invoices','invoice_previews','order_sku_lines')
        with test_connection(self.path) as connection:
            connection.execute("INSERT INTO users(username,password_hash) VALUES('fixture','test')")
            connection.execute("INSERT INTO client_leads(name,created_by) VALUES('Client',1)")
            connection.execute("INSERT INTO client_orders(reference,client_id,order_date,currency,created_by,updated_by) "
                               "VALUES('ORDER-1',1,'2026-10-16','USD',1,1)")
            connection.execute("INSERT INTO order_invoices(order_id,reference,currency,snapshot_json,workbook,created_by,workbook_format,pdf) "
                               "VALUES(1,'PI-1','USD','{}',?,1,'xlsx',?)",(b'workbook fixture',b'pdf fixture'))
            connection.execute("INSERT INTO invoice_previews(id,order_id,created_by,document_json,issued_invoice_id) "
                               "VALUES('preview',1,1,'{}',1)")
            connection.execute("INSERT INTO order_sku_lines(order_id,sku,description,quantity_milli,unit_price_minor,currency,created_by,updated_by) "
                               "VALUES(1,'SKU','Part',1000,100,'USD',1,1)")
            connection.execute("UPDATE sqlite_sequence SET seq=100 WHERE name IN ('client_orders','order_invoices')")
            before = {table:connection.execute('SELECT * FROM '+table).fetchall() for table in tables}
        self.assertEqual(migrate_database(self.path, MIGRATIONS[:21]),[21])
        with test_connection(self.path) as connection:
            for table, rows in before.items():
                self.assertEqual(connection.execute('SELECT * FROM '+table).fetchall(),rows)
            for table in ('client_orders','order_invoices'):
                columns = ','.join(row[1] for row in connection.execute('PRAGMA table_info('+table+')') if row[1]!='id')
                cursor = connection.execute('INSERT INTO '+table+' ('+columns+') SELECT '+columns+' FROM '+table+' WHERE id=1')
                self.assertEqual(cursor.lastrowid,101)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_version_two_upgrade_preserves_credentials_and_roles(self):
        self.create_legacy_database()
        migrate_database(self.path, MIGRATIONS[:2])
        with test_connection(self.path) as connection:
            before = legacy_snapshot(connection)
        self.assertEqual(
            migrate_database(self.path), list(range(3, len(MIGRATIONS) + 1))
        )
        with test_connection(self.path) as connection:
            self.assertTrue(before == legacy_snapshot(connection))
            self.assertEqual(connection.execute(
                'SELECT is_active FROM users'
            ).fetchone()[0], 1)

    def test_version_four_upgrade_leaves_supervisors_unassigned(self):
        self.create_legacy_database()
        migrate_database(self.path, MIGRATIONS[:4])
        with test_connection(self.path) as connection:
            before = legacy_snapshot(connection)
        self.assertEqual(
            migrate_database(self.path), list(range(5, len(MIGRATIONS) + 1))
        )
        with test_connection(self.path) as connection:
            self.assertTrue(before == legacy_snapshot(connection))
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM users '
                'WHERE supervisor_user_id IS NOT NULL'
            ).fetchone()[0], 0)

    def test_actual_database_copy_preserves_every_legacy_record(self):
        """SQLite backup handles a live source and never prints its rows."""
        source_path = Path(DB_PATH)
        if not source_path.exists():
            self.skipTest('Existing application database is not available.')
        before_hash = hashlib.sha256(source_path.read_bytes()).digest()
        source = connect_database(source_path, read_only=True)
        destination = sqlite3.connect(self.path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        with test_connection(self.path) as connection:
            before = legacy_snapshot(connection)
        pending = migration_status(self.path)['pending']
        self.assertEqual(migrate_database(self.path), pending)
        with test_connection(self.path) as connection:
            self.assertTrue(before == legacy_snapshot(connection))
            self.assertEqual(
                connection.execute('PRAGMA integrity_check').fetchone()[0],
                'ok',
            )
        self.assertTrue(
            before_hash == hashlib.sha256(source_path.read_bytes()).digest()
        )

    def test_failed_initial_batch_rolls_back_schema_and_tracking(self):
        broken = MIGRATIONS + ((len(MIGRATIONS) + 1, 'broken', (
            'CREATE TABLE transient_test (id INTEGER)',
            'INSERT INTO nonexistent_table VALUES (1)',
        )),)
        with self.assertRaises(sqlite3.OperationalError):
            migrate_database(self.path, broken)
        with test_connection(self.path) as connection:
            self.assertEqual(connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall(), [])

    def test_failed_upgrade_preserves_committed_versions(self):
        migrate_database(self.path, MIGRATIONS[:1])
        with test_connection(self.path) as connection:
            before = legacy_snapshot(connection)
        broken = MIGRATIONS + ((len(MIGRATIONS) + 1, 'broken', ('INVALID SQL',)),)
        with self.assertRaises(sqlite3.OperationalError):
            migrate_database(self.path, broken)
        self.assertEqual(
            migration_status(self.path),
            {'applied': [1],
             'pending': list(range(2, len(MIGRATIONS) + 1))}
        )
        with test_connection(self.path) as connection:
            self.assertTrue(before == legacy_snapshot(connection))
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'roles'"
            ).fetchone())

    def test_altered_migration_is_rejected(self):
        migrate_database(self.path)
        altered = ((1, 'changed_name', LEGACY_SCHEMA),) + MIGRATIONS[1:]
        with self.assertRaises(MigrationError):
            migrate_database(self.path, altered)

    def test_unknown_version_is_rejected(self):
        migrate_database(self.path)
        with self.assertRaises(MigrationError):
            migrate_database(self.path, MIGRATIONS[:1])

    def test_deferred_foreign_key_violations_still_roll_back(self):
        migrate_database(self.path)
        invalid = MIGRATIONS + ((len(MIGRATIONS) + 1, 'orphan_fixture', (
            'PRAGMA defer_foreign_keys = ON',
            "INSERT INTO client_leads(name,created_by) VALUES('orphan',999999)",
        )),)
        with self.assertRaises(MigrationError):
            migrate_database(self.path, invalid)
        with test_connection(self.path) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM client_leads').fetchone()[0], 0)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(migration_status(self.path)['pending'], [])

    def test_history_gap_is_rejected(self):
        migrate_database(self.path)
        with test_connection(self.path) as connection:
            connection.execute(
                'DELETE FROM schema_migrations WHERE version = 1'
            )
        with self.assertRaises(MigrationError):
            migrate_database(self.path)

    def test_concurrent_startups_apply_only_once(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                migrate_database, (self.path, self.path)
            ))
        self.assertEqual(
            sorted(results), [[], list(range(1, len(MIGRATIONS) + 1))]
        )

    def test_new_foreign_keys_constraints_and_indexes(self):
        migrate_database(self.path)
        connection = connect_database(self.path)
        self.addCleanup(connection.close)
        statements = (
            "INSERT INTO enquiry_sources (code, name) VALUES ('', 'Email')",
            "INSERT INTO enquiry_sources (code, name, is_active) "
            "VALUES ('email', 'Email', 2)",
            "INSERT INTO role_permissions VALUES ('unknown', 'unknown')",
            "INSERT INTO audit_logs (actor_user_id, action, entity_type) "
            "VALUES (999, 'create', 'enquiry')",
            "INSERT INTO audit_logs (action, entity_type) "
            "VALUES ('', 'enquiry')",
        )
        for statement in statements:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(statement)
        connection.execute(
            "INSERT INTO permissions (code) VALUES ('fixture.read')"
        )
        connection.execute(
            "INSERT INTO role_permissions VALUES ('user', 'fixture.read')"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM roles WHERE code = 'user'")
        connection.execute(
            "INSERT INTO users (username, password_hash) "
            "VALUES ('fixture', 'noncredential-test-value')"
        )
        uid = connection.execute('SELECT id FROM users').fetchone()[0]
        connection.execute(
            'INSERT INTO audit_logs (actor_user_id, actor_name, action, '
            'entity_type) VALUES (?, ?, ?, ?)',
            (uid, 'fixture', 'create', 'enquiry'),
        )
        connection.execute('DELETE FROM users WHERE id = ?', (uid,))
        self.assertEqual(connection.execute(
            'SELECT actor_user_id, actor_name FROM audit_logs'
        ).fetchone(), (None, 'fixture'))
        indexes = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )}
        self.assertTrue({
            'idx_audit_logs_actor_time', 'idx_audit_logs_entity_time',
            'idx_audit_logs_time', 'idx_enquiry_sources_active_name',
            'idx_role_permissions_permission',
        }.issubset(indexes))

    def test_status_is_read_only_and_missing_file_is_not_created(self):
        with self.assertRaises(sqlite3.OperationalError):
            migration_status(self.path)
        self.assertFalse(self.path.exists())
        self.create_legacy_database()
        before = self.path.read_bytes()
        self.assertEqual(
            migration_status(self.path),
            {'applied': [],
             'pending': list(range(1, len(MIGRATIONS) + 1))}
        )
        self.assertTrue(before == self.path.read_bytes())

    def test_application_initializer_uses_migrations(self):
        with patch.object(database, 'DB_PATH', str(self.path)), \
                patch.object(database, 'DATABASE_DIR', self.path.parent), \
                patch.dict(os.environ, {'AMT_BOOTSTRAP_ADMIN_PASSWORD': 'fixture-admin-pass'}):
            database.initialize_database()
            database.initialize_database()
            connection = database.get_db()
            try:
                self.assertEqual(connection.execute(
                    'PRAGMA foreign_keys'
                ).fetchone()[0], 1)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'manager'"
                ).fetchone()[0], 1)
            finally:
                connection.close()
        self.assertEqual(
            migration_status(self.path),
            {'applied': list(range(1, len(MIGRATIONS) + 1)),
             'pending': []}
        )


if __name__ == '__main__':
    unittest.main()
