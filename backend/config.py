from pathlib import Path
import os
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
# The database path is resolved while this module is imported. Load the project
# settings first so AMT_QUOTATION_DB_PATH in backend/.env is honored on startup.
load_dotenv(ROOT_DIR / 'backend' / '.env', override=False)
BASE_DIR = str(ROOT_DIR)
FRONTEND_DIR = ROOT_DIR / 'frontend'
DATABASE_DIR = ROOT_DIR / 'database'
DB_PATH = os.getenv('AMT_QUOTATION_DB_PATH') or str(DATABASE_DIR / 'quotation.db')
SECRET_KEY_PATH = ROOT_DIR / 'backend' / 'secret.key'
