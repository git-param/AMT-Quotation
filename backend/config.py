from pathlib import Path
import os

ROOT_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = str(ROOT_DIR)
FRONTEND_DIR = ROOT_DIR / 'frontend'
DATABASE_DIR = ROOT_DIR / 'database'
DB_PATH = os.getenv('AMT_QUOTATION_DB_PATH') or str(DATABASE_DIR / 'quotation.db')
SECRET_KEY_PATH = ROOT_DIR / 'backend' / 'secret.key'
