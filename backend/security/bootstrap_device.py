"""One-time local bootstrap for the first Admin device. Run only on the DB host."""
import argparse
from pathlib import Path

from backend.migrations import connect_database
from backend.security.mac import normalize_mac


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--username', required=True)
    parser.add_argument('--mac', required=True)
    args = parser.parse_args()
    mac = normalize_mac(args.mac)
    if not mac:
        parser.error('Invalid MAC address')
    connection = connect_database(args.database)
    try:
        connection.row_factory = __import__('sqlite3').Row
        with connection:
            user = connection.execute(
                "SELECT id FROM users WHERE username=? AND is_active=1 AND role IN ('admin','manager')",
                (args.username,)).fetchone()
            if not user:
                parser.error('Active Admin account not found')
            row = connection.execute(
                'SELECT id,user_id,status FROM device_registrations WHERE mac_address=?',
                (mac,)).fetchone()
            if not row or row['user_id'] != user['id'] or row['status'] != 'pending':
                parser.error('Pending registration for that Admin and MAC address not found')
            # A locally run bootstrap is explicitly attributed in audit logs.
            connection.execute(
                "UPDATE device_registrations SET status='approved',"
                "decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),decided_by=? WHERE id=?",
                (user['id'], row['id']))
            connection.execute(
                "INSERT INTO audit_logs(actor_user_id,actor_name,action,entity_type,entity_id,details) "
                "VALUES(?,?,?,?,?,'{}')", (user['id'], args.username,
                'device.bootstrap', 'device_registration', str(row['id'])))
        print('First Admin device approved. Use Device Management for all later requests.')
    finally:
        connection.close()


if __name__ == '__main__':
    main()
