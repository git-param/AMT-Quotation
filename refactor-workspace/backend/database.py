import sqlite3
import threading
from werkzeug.security import generate_password_hash
from backend.config import DB_PATH, DATABASE_DIR

_db_lock = threading.Lock()

def get_db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute('PRAGMA foreign_keys = ON')
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Apply pending schema migrations without altering historical records."""
    from backend.migrations import migrate_database

    migrate_database(DB_PATH)


def _seed_users():
    con = get_db()
    if not con.execute("SELECT 1 FROM users WHERE role IN ('manager', 'admin') LIMIT 1").fetchone():
        con.execute("INSERT OR IGNORE INTO users (username,password_hash,role) VALUES (?,?,?)",
                    ('manager', generate_password_hash('admin123'), 'manager'))
        con.commit()
    con.close()


def log_search(user_name, user_ip, skus, found, not_found):
    with _db_lock:
        try:
            con = get_db()
            con.execute(
                'INSERT INTO search_logs (user_name,user_ip,skus,found_count,not_found) VALUES (?,?,?,?,?)',
                (user_name, user_ip, ','.join(skus), found, not_found)
            )
            con.commit()
            con.close()
        except Exception:
            pass


def log_copy(user_name, user_ip, copy_type, sku_count):
    with _db_lock:
        try:
            con = get_db()
            con.execute(
                'INSERT INTO copy_logs (user_name,user_ip,copy_type,sku_count) VALUES (?,?,?,?)',
                (user_name, user_ip, copy_type, sku_count)
            )
            con.commit()
            con.close()
        except Exception:
            pass


def initialize_database():
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    _seed_users()
