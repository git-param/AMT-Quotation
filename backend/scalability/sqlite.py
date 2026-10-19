"""SQLite concurrency settings for a single-host deployment."""
import sqlite3


BUSY_TIMEOUT_MS = 30_000


def connect(path):
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
    connection.execute('PRAGMA foreign_keys = ON')
    connection.row_factory = sqlite3.Row
    return connection


def enable_wal(path):
    """Set the persistent journal mode after migrations, outside a transaction."""
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        mode = connection.execute('PRAGMA journal_mode = WAL').fetchone()[0]
        if mode.lower() != 'wal':
            raise RuntimeError(f'Could not enable SQLite WAL mode: {mode}')
    finally:
        connection.close()
