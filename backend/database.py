import sqlite3
import threading
from werkzeug.security import generate_password_hash
from backend.config import DB_PATH, DATABASE_DIR

_db_lock = threading.Lock()

def get_db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = get_db()
    con.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    UNIQUE NOT NULL,
            password_hash TEXT   NOT NULL,
            role         TEXT    DEFAULT 'user',
            created_at   TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS search_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name   TEXT    DEFAULT 'Unknown',
            user_ip     TEXT,
            skus        TEXT,
            found_count INTEGER DEFAULT 0,
            not_found   INTEGER DEFAULT 0,
            ts          TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS copy_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name   TEXT    DEFAULT 'Unknown',
            user_ip     TEXT,
            copy_type   TEXT,
            sku_count   INTEGER DEFAULT 0,
            ts          TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_search_ts   ON search_logs(ts);
        CREATE INDEX IF NOT EXISTS idx_search_user ON search_logs(user_name);
        CREATE INDEX IF NOT EXISTS idx_copy_ts     ON copy_logs(ts);
    ''')
    con.commit()
    con.close()


def _seed_users():
    con = get_db()
    if not con.execute("SELECT 1 FROM users WHERE role='manager' LIMIT 1").fetchone():
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
