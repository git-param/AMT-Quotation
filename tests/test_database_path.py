"""Deployment database selection must not silently replace historical data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend import database


class DatabasePathTests(unittest.TestCase):
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
