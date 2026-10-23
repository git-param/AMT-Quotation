"""Deployment database selection must not silently replace historical data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend import database
from backend.config import resolve_database_path


class DatabasePathTests(unittest.TestCase):
    def test_existing_original_database_wins_without_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'database').mkdir()
            (root / 'database' / 'quotation.db').touch()
            self.assertEqual(resolve_database_path(root),
                             str(root / 'database' / 'quotation.db'))
            (root / 'quotation.db').touch()
            self.assertEqual(resolve_database_path(root), str(root / 'quotation.db'))
            self.assertEqual(resolve_database_path(root, str(root / 'other.db')),
                             str(root / 'other.db'))

    def test_explicit_missing_database_stops_before_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'persistent' / 'quotation.db'
            with patch.dict(os.environ, {'AMT_QUOTATION_DB_PATH': str(target)}), \
                    patch.object(database, 'DB_PATH', str(target)):
                with self.assertRaisesRegex(RuntimeError, 'Refusing to create'):
                    database.initialize_database()
            self.assertFalse(target.exists())

    def test_environment_database_path_wins_at_config_import(self):
        with tempfile.TemporaryDirectory() as directory:
            target = str(Path(directory) / 'quotation.db')
            environment = dict(os.environ, AMT_QUOTATION_DB_PATH=target)
            result = subprocess.run(
                [sys.executable, '-c', 'from backend.config import DB_PATH; print(DB_PATH)'],
                env=environment, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), target)


if __name__ == '__main__':
    unittest.main()
