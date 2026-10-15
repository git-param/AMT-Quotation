"""Transactional SQLite migrations, independent of Flask and credentials.

Run ``python -m backend.migrations status|migrate --database PATH``.
All pending migrations and their tracking records commit as one transaction.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from backend.migration_definitions import MIGRATIONS


class MigrationError(RuntimeError):
    """An incompatible migration history or schema was detected."""


def migration_checksum(name, statements):
    """Fingerprint the migration name and exact ordered statements."""
    payload = json.dumps([name, statements], ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def connect_database(database_path, read_only=False):
    """Open SQLite with FK enforcement; never create a read-only target."""
    path = Path(database_path).resolve()
    if read_only:
        connection = sqlite3.connect(
            path.as_uri() + '?mode=ro', uri=True, timeout=30
        )
        connection.execute('PRAGMA query_only = ON')
    else:
        connection = sqlite3.connect(str(path), timeout=30)
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def _validate_definitions(migrations):
    versions = [version for version, _, _ in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise MigrationError('Migration versions must be contiguous from 1.')


def _read_history(connection):
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if not exists:
        return []
    return connection.execute(
        'SELECT version, name, checksum FROM schema_migrations '
        'ORDER BY version'
    ).fetchall()


def _validate_history(history, migrations):
    if len(history) > len(migrations):
        raise MigrationError('Database is newer than this application.')
    for stored, expected in zip(history, migrations):
        version, name, statements = expected
        if tuple(stored) != (
                version, name, migration_checksum(name, statements)):
            raise MigrationError(
                'Migration history has a gap or an altered migration.'
            )


def _validate_legacy_schema(connection):
    """Allow extra legacy columns while requiring existing API fields."""
    required = {
        'users': {'id', 'username', 'password_hash', 'role', 'created_at'},
        'search_logs': {
            'id', 'user_name', 'user_ip', 'skus', 'found_count',
            'not_found', 'ts',
        },
        'copy_logs': {
            'id', 'user_name', 'user_ip', 'copy_type', 'sku_count', 'ts',
        },
    }
    for table, columns in required.items():
        actual = {
            row[1] for row in connection.execute(
                'PRAGMA table_info(' + table + ')'
            )
        }
        if not columns.issubset(actual):
            raise MigrationError('Incompatible legacy schema: ' + table)


def migrate_database(database_path, migrations=MIGRATIONS):
    """Apply pending versions atomically and return their version numbers.

    BEGIN IMMEDIATE serializes competing startup processes. Individual execute
    calls preserve transactional DDL; executescript would implicitly commit.
    Any failure rolls back every pending version, including tracking changes.
    """
    _validate_definitions(migrations)
    connection = connect_database(database_path)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                name TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL CHECK (length(checksum) = 64),
                applied_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)
        history = _read_history(connection)
        _validate_history(history, migrations)
        applied = []
        for version, name, statements in migrations[len(history):]:
            for statement in statements:
                connection.execute(statement)
            if version == 1:
                _validate_legacy_schema(connection)
            connection.execute(
                'INSERT INTO schema_migrations (version, name, checksum) '
                'VALUES (?, ?, ?)',
                (version, name, migration_checksum(name, statements)),
            )
            applied.append(version)
        _validate_legacy_schema(connection)
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise MigrationError('Database contains foreign key violations.')
        # A transactional parent-table replacement can leave SQLite's deferred
        # violation counter set after the original table is dropped, even though
        # its replacement satisfies every FK. Reset deferral only after checking
        # the complete final schema while BEGIN IMMEDIATE excludes other writers.
        # PRAGMA foreign_keys stays enabled throughout the migration.
        connection.execute('PRAGMA defer_foreign_keys = OFF')
        connection.commit()
        return applied
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def migration_status(database_path):
    """Return validated applied/pending versions without changing the file."""
    connection = connect_database(database_path, read_only=True)
    try:
        history = _read_history(connection)
        _validate_definitions(MIGRATIONS)
        _validate_history(history, MIGRATIONS)
        return {
            'applied': [row[0] for row in history],
            'pending': [row[0] for row in MIGRATIONS[len(history):]],
        }
    finally:
        connection.close()


def main():
    """Provide an explicit migration command without starting the app."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'migrate'))
    parser.add_argument('--database', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'status':
        result = migration_status(args.database)
    else:
        result = {'applied': migrate_database(args.database)}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
