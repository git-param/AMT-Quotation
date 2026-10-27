import threading
import os
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash
from backend.config import DB_PATH, DATABASE_DIR
from backend.scalability.sqlite import connect, enable_wal

_db_lock = threading.Lock()

def get_db():
    return connect(DB_PATH)


def init_db():
    """Apply pending schema migrations without altering historical records."""
    from backend.migrations import migrate_database

    migrate_database(DB_PATH)


def _seed_users():
    con = get_db()
    if not con.execute("SELECT 1 FROM users WHERE role IN ('manager', 'admin') LIMIT 1").fetchone():
        password = os.getenv('AMT_BOOTSTRAP_ADMIN_PASSWORD', '')
        if password:
            from backend.security.passwords import error
            problem = error(password)
            if problem:
                con.close()
                raise RuntimeError('Invalid AMT_BOOTSTRAP_ADMIN_PASSWORD: ' + problem)
            con.execute("INSERT OR IGNORE INTO users (username,password_hash,role) VALUES (?,?,?)",
                        (os.getenv('AMT_BOOTSTRAP_ADMIN_USERNAME', 'manager'),
                         generate_password_hash(password), 'manager'))
            con.commit()
    con.close()


def log_search(user_name, user_ip, skus, found, not_found):
    with _db_lock:
        con = None
        try:
            con = get_db()
            # Lookup history uses local India time, including legacy records.
            timestamp = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M:%S')
            con.execute(
                'INSERT INTO search_logs (user_name,user_ip,skus,found_count,not_found,ts) VALUES (?,?,?,?,?,?)',
                (user_name, user_ip, ','.join(skus), found, not_found, timestamp)
            )
            actor = con.execute('SELECT id,role FROM users WHERE username=?',
                                (user_name,)).fetchone()
            con.execute(
                'INSERT INTO audit_logs(actor_user_id,actor_name,actor_role,ip_address,'
                'action,entity_type,entity_id,details) VALUES(?,?,?,?,?,?,?,?)',
                (actor['id'] if actor else None, user_name or 'Unknown',
                 actor['role'] if actor else ('api' if (user_name or '').startswith('API') else ''),
                 user_ip or '', 'sku_lookup',
                 'sku_lookup', '', json.dumps({'sku_count': len(skus),
                    'found': found, 'not_found': not_found})),
            )
            con.commit()
        except Exception:
            pass
        finally:
            if con is not None:
                con.close()


def log_copy(user_name, user_ip, copy_type, sku_count):
    with _db_lock:
        try:
            con = get_db()
            con.execute(
                'INSERT INTO copy_logs (user_name,user_ip,copy_type,sku_count) VALUES (?,?,?,?)',
                (user_name, user_ip, copy_type, sku_count)
            )
            actor = con.execute('SELECT id,role FROM users WHERE username=?',
                                (user_name,)).fetchone()
            con.execute(
                'INSERT INTO audit_logs(actor_user_id,actor_name,actor_role,ip_address,'
                'action,entity_type,entity_id,details) VALUES(?,?,?,?,?,?,?,?)',
                (actor['id'] if actor else None, user_name or 'Unknown',
                 actor['role'] if actor else ('api' if (user_name or '').startswith('API') else ''),
                 user_ip or '', 'sku_copy',
                 'copy', copy_type or '', json.dumps({'copy_type': copy_type,
                    'sku_count': sku_count})),
            )
            con.commit()
            con.close()
        except Exception:
            pass


def initialize_database():
    if os.getenv('AMT_QUOTATION_DB_PATH') and not Path(DB_PATH).is_file():
        raise RuntimeError(
            f'Configured quotation database does not exist: {DB_PATH}. '
            'Refusing to create an empty database at this path.'
        )
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_db()
    enable_wal(DB_PATH)
    _seed_users()
