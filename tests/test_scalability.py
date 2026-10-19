"""Concurrency settings that must hold for each new app connection."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.migrations import migrate_database
from backend.scalability.sqlite import connect, enable_wal, BUSY_TIMEOUT_MS


class SqliteConcurrencyTests(unittest.TestCase):
    def test_wal_and_busy_timeout_survive_new_connections(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'quotation.db'
            migrate_database(path)
            enable_wal(path)
            connection = connect(str(path))
            try:
                self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
                self.assertEqual(connection.execute('PRAGMA busy_timeout').fetchone()[0], BUSY_TIMEOUT_MS)
                self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            finally:
                connection.close()


if __name__ == '__main__':
    unittest.main()
