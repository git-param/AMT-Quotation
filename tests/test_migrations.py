"""Test schema upgrades without Flask or changes to production data."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
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
            ) if row[1] not in ('is_active', 'supervisor_user_id'))
            + ' FROM ' + table + ' ORDER BY id'
        ).fetchall()
        snapshot[table + '_columns'] = [
            row for row in connection.execute(
                'PRAGMA table_info(' + table + ')'
            ) if row[1] not in ('is_active', 'supervisor_user_id')
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
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        )
        self.assertEqual(migrate_database(self.path), [])
        self.assertEqual(
            migration_status(self.path),
            {'applied': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
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

    def test_existing_schema_and_records_are_unchanged(self):
        self.create_legacy_database()
        with test_connection(self.path) as connection:
            before = legacy_snapshot(connection)
        migrate_database(self.path)
        with test_connection(self.path) as connection:
            self.assertTrue(before == legacy_snapshot(connection))

    def test_version_two_upgrade_preserves_credentials_and_roles(self):
        self.create_legacy_database()
        migrate_database(self.path, MIGRATIONS[:2])
        with test_connection(self.path) as connection:
            before = legacy_snapshot(connection)
        self.assertEqual(
            migrate_database(self.path), [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
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
            migrate_database(self.path), [5, 6, 7, 8, 9, 10, 11, 12, 13]
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
        broken = MIGRATIONS + ((14, 'broken', (
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
        broken = MIGRATIONS + ((14, 'broken', ('INVALID SQL',)),)
        with self.assertRaises(sqlite3.OperationalError):
            migrate_database(self.path, broken)
        self.assertEqual(
            migration_status(self.path),
            {'applied': [1],
             'pending': [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]}
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
            sorted(results), [[], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]]
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
             'pending': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]}
        )
        self.assertTrue(before == self.path.read_bytes())

    def test_application_initializer_uses_migrations(self):
        with patch.object(database, 'DB_PATH', str(self.path)), \
                patch.object(database, 'DATABASE_DIR', self.path.parent):
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
            {'applied': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
             'pending': []}
        )


if __name__ == '__main__':
    unittest.main()
