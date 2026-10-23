"""Read the shared pricing catalog when Postgres is configured."""
import os
from pathlib import Path


def connect():
    if not os.environ.get('PGHOST'):
        env_file = Path('/etc/aeliya/.pg.env')
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip().startswith('PG'):
                        os.environ.setdefault(key.strip(), value.strip().strip('"\''))
    if not os.environ.get('PGHOST'):
        raise RuntimeError('Shared pricing database is not configured')
    from psycopg2 import connect as pg_connect
    from psycopg2.extras import RealDictCursor
    return pg_connect(cursor_factory=RealDictCursor, connect_timeout=10)
