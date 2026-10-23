from pathlib import Path
import os
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / 'backend' / '.env', override=False)
BASE_DIR = str(ROOT_DIR)
FRONTEND_DIR = ROOT_DIR / 'frontend'
DATABASE_DIR = ROOT_DIR / 'database'


def resolve_database_path(root, configured=None):
    """Keep the original root-level database; retain the local modular layout."""
    if configured:
        return str(Path(configured))
    original = root / 'quotation.db'
    if original.is_file():
        return str(original)
    return str(root / 'database' / 'quotation.db')


DB_PATH = resolve_database_path(ROOT_DIR, os.getenv('AMT_QUOTATION_DB_PATH'))
SECRET_KEY_PATH = ROOT_DIR / 'backend' / 'secret.key'
