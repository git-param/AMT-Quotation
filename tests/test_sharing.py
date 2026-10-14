"""Test sharing scope, history, revocation, and migration preservation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import unittest

import test_leads
from backend import database
from backend.client_access.routes import bp
from backend.migration_definitions import MIGRATIONS
from backend.migrations import migrate_database


class SharingTests(unittest.TestCase):
    """Reuse isolated lead fixture setup without duplicating its test cases."""

    as_user = test_leads.LeadTests.as_user
    create = test_leads.LeadTests.create
    visible = test_leads.LeadTests.visible
    assign = test_leads.LeadTests.assign

    def setUp(self):
        test_leads.LeadTests.setUp(self)
        self.client.application.register_blueprint(bp)

    def share(self, lead_id, recipient='exec2', action='grant'):
        return self.client.post(
            f'/api/client-access/{lead_id}/{action}',
            json={'user_id': self.ids[recipient]},
        )

    def test_grant_revoke_regrant_history_and_immediate_visibility(self):
        uid = self.create('exec1')
        unrelated = self.create('tl2')
        self.as_user('admin')
        self.assertEqual(self.share(uid).status_code, 200)
        self.assertEqual(self.share(uid).status_code, 409)
        self.assertIn(uid, self.visible('exec2'))
        self.assertNotIn(unrelated, self.visible('exec2'))
        self.as_user('exec2')
        detail = self.client.get(f'/api/leads/{uid}').json['lead']
        self.assertTrue(detail['is_shared'])
        self.assertFalse(detail['can_edit'])
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Forbidden'}
        ).status_code, 403)
        self.as_user('admin')
        self.assertEqual(self.share(uid, action='revoke').status_code, 200)
        self.assertEqual(self.share(uid, action='revoke').status_code, 409)
        self.assertNotIn(uid, self.visible('exec2'))
        self.as_user('exec2')
        self.assertEqual(self.client.get(f'/api/leads/{uid}').status_code, 404)
        self.as_user('admin')
        before = self.client.get(f'/api/client-access/{uid}').json
        self.assertFalse(before['shares'][0]['is_active'])
        self.assertEqual(before['shares'][0]['revoked_by'], self.ids['admin'])
        self.assertTrue(before['shares'][0]['revoked_at'].endswith('Z'))
        self.assertEqual(self.share(uid).status_code, 200)
        data = self.client.get(f'/api/client-access/{uid}').json
        self.assertEqual(len(data['shares']), 1)
        self.assertEqual([event['action'] for event in data['events']],
                         ['grant', 'revoke', 'grant'])
        for event in data['events']:
            self.assertEqual(event['actor_user_id'], self.ids['admin'])
            self.assertEqual(event['actor_name'], 'admin')
            self.assertTrue(event['occurred_at'].endswith('Z'))

    def test_tl_scope_cross_tl_denials_and_reassignment(self):
        own = self.create('tl1')
        executive = self.create('exec1')
        other = self.create('tl2')
        self.assign('exec1', 'tl1')
        self.as_user('tl1')
        self.assertEqual(self.share(own).status_code, 200)
        self.assertEqual(self.share(executive).status_code, 200)
        self.assertEqual(self.share(other).status_code, 404)
        self.assertEqual(self.client.get(
            f'/api/client-access/{other}'
        ).status_code, 404)
        options = self.client.get('/api/client-access').json
        self.assertEqual({lead['id'] for lead in options['leads']},
                         {own, executive})
        self.assign('exec1', 'tl2')
        self.as_user('tl1')
        self.assertEqual(
            self.share(executive, action='revoke').status_code, 404
        )
        self.as_user('tl2')
        self.assertEqual(
            self.share(executive, action='revoke').status_code, 200
        )

    def test_shared_executive_cannot_reshare_or_escalate(self):
        uid = self.create('tl1')
        self.as_user('admin')
        self.share(uid)
        self.as_user('exec2')
        for method, path in (
                ('GET', '/api/client-access'),
                ('GET', f'/api/client-access/{uid}'),
                ('POST', f'/api/client-access/{uid}/grant'),
                ('POST', f'/api/client-access/{uid}/revoke')):
            self.assertEqual(self.client.open(
                path, method=method, json={'user_id': self.ids['exec1']}
            ).status_code, 403)
        self.as_user(None)
        self.assertEqual(
            self.client.get('/api/client-access').status_code, 401
        )

    def test_recipient_and_payload_validation_and_deactivated_revocation(self):
        uid = self.create('tl1')
        self.as_user('admin')
        for name in ('admin', 'tl1', 'unknown'):
            self.assertEqual(self.share(uid, name).status_code, 400)
        for payload in ([], {}, {'user_id': True}, {'user_id': '1'},
                        {'user_id': self.ids['exec2'], 'role': 'admin'}):
            self.assertEqual(self.client.post(
                f'/api/client-access/{uid}/grant', json=payload
            ).status_code, 400)
        self.assertEqual(self.share(99999).status_code, 404)
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/grant', json={'user_id': 99999}
        ).status_code, 404)
        self.assertEqual(self.share(uid).status_code, 200)
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'UPDATE users SET is_active = 0 WHERE id = ?',
                                   (self.ids['exec2'],))
        finally:
            connection.close()
        self.assertEqual(self.share(uid).status_code, 400)
        self.assertEqual(self.share(uid, action='revoke').status_code, 200)

    def test_revocation_does_not_remove_independent_edit_or_ownership(self):
        uid = self.create('exec1')
        self.as_user('admin')
        self.assertEqual(self.share(uid, 'exec2').status_code, 200)
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    "UPDATE users SET role = 'sales_tl' WHERE id = ?",
                    (self.ids['exec2'],),
                )
                connection.execute(
                    'UPDATE users SET supervisor_user_id = ? WHERE id = ?',
                    (self.ids['exec2'], self.ids['exec1']),
                )
        finally:
            connection.close()
        self.as_user('exec2')
        self.assertTrue(self.client.get(
            f'/api/leads/{uid}'
        ).json['lead']['can_edit'])
        self.as_user('admin')
        self.assertEqual(self.share(uid, action='revoke').status_code, 200)
        self.assertIn(uid, self.visible('exec2'))
        self.assertIn(uid, self.visible('exec1'))

    def test_duplicate_concurrent_grants_create_one_event(self):
        uid = self.create('tl1')
        app = self.client.application

        def grant(_):
            client = app.test_client()
            with client.session_transaction() as session:
                session['user_id'] = self.ids['admin']
            return client.post(
                f'/api/client-access/{uid}/grant',
                json={'user_id': self.ids['exec2']},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(grant, range(2)))
        self.assertEqual(sorted(results), [200, 409])
        self.as_user('admin')
        self.assertEqual(len(self.client.get(
            f'/api/client-access/{uid}'
        ).json['events']), 1)

    def test_failed_event_write_rolls_back_the_share(self):
        uid = self.create('tl1')
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'CREATE TRIGGER reject_event BEFORE INSERT '
                    'ON client_share_events BEGIN '
                    "SELECT RAISE(ABORT, 'test failure'); END"
                )
        finally:
            connection.close()
        self.as_user('admin')
        with self.assertRaises(sqlite3.IntegrityError):
            self.share(uid)
        self.assertNotIn(uid, self.visible('exec2'))

    def test_legacy_roles_and_read_grants_do_not_escalate_sharing(self):
        uid = self.create('tl1')
        self.as_user('manager')
        self.assertEqual(self.share(uid, 'legacy').status_code, 200)
        self.assertIn(uid, self.visible('legacy'))
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    'INSERT INTO role_permissions VALUES (?, ?)',
                    ('sales_executive', 'leads.share_manage'),
                )
                connection.execute(
                    'INSERT INTO role_permissions VALUES (?, ?)',
                    ('sales_executive', 'leads.view_all'),
                )
        finally:
            connection.close()
        self.as_user('exec1')
        self.assertEqual(
            self.client.get('/api/client-access').status_code, 403
        )
        self.assertEqual(self.share(uid).status_code, 404)
        self.as_user('manager')
        self.assertEqual(self.share(uid, 'legacy', 'revoke').status_code, 200)
        self.assertNotIn(uid, self.visible('legacy'))

    def test_migration_preserves_legacy_shares_with_unknown_attribution(self):
        path = Path(database.DB_PATH).parent / 'legacy_shares.db'
        migrate_database(path, MIGRATIONS[:5])
        connection = sqlite3.connect(path)
        try:
            with connection:
                for name in ('owner', 'recipient'):
                    connection.execute(
                        'INSERT INTO users (username, password_hash) '
                        'VALUES (?, ?)', (name, 'test-placeholder'),
                    )
                connection.execute(
                    "INSERT INTO client_leads (name, created_by) "
                    "VALUES ('Lead', 1)"
                )
                connection.execute(
                    'INSERT INTO client_lead_shares (lead_id, user_id) '
                    'VALUES (1, 2)'
                )
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), [6, 7, 8])
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute(
                'SELECT lead_id, user_id, is_active, granted_by, granted_at '
                'FROM client_lead_shares'
            ).fetchone(), (1, 2, 1, None, None))
            self.assertEqual(connection.execute(
                'SELECT COUNT(*) FROM client_share_events'
            ).fetchone()[0], 0)
        finally:
            connection.close()

    def test_cross_team_edit_grant_downgrade_revoke_and_ownership(self):
        uid = self.create('exec1')
        original = self.client.get(f'/api/leads/{uid}').json['lead']
        self.assign('exec1', 'tl1')
        self.assign('exec2', 'tl2')
        self.as_user('tl1')
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/grant',
            json={'user_id': self.ids['exec2'], 'access_level': 'EDIT'},
        ).status_code, 200)
        self.as_user('exec2')
        lead = self.client.get(f'/api/leads/{uid}').json['lead']
        self.assertTrue(lead['can_edit'])
        self.assertEqual(lead['shared_access_level'], 'EDIT')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Updated client'}
        ).status_code, 200)
        for field in ('created_by', 'created_at'):
            self.assertEqual(self.client.put(f'/api/leads/{uid}', json={
                'name': 'Spoofed', field: self.ids['exec2'],
            }).status_code, 400)
        self.assertEqual(self.share(uid, 'legacy').status_code, 403)
        self.as_user('tl2')
        self.assertEqual(self.share(uid, 'legacy').status_code, 404)
        self.as_user('tl1')
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/level',
            json={'user_id': self.ids['exec2'], 'access_level': 'VIEW'},
        ).status_code, 200)
        history = self.client.get(f'/api/client-access/{uid}').json['events']
        self.assertEqual(history[0]['previous_access_level'], 'EDIT')
        self.assertEqual(history[0]['access_level'], 'VIEW')
        self.as_user('exec2')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Denied'}
        ).status_code, 403)
        self.assertIn(uid, self.visible('exec2'))
        self.as_user('tl1')
        self.assertEqual(self.share(uid, action='revoke').status_code, 200)
        self.assertNotIn(uid, self.visible('exec2'))
        self.as_user('admin')
        lead = self.client.get(f'/api/leads/{uid}').json['lead']
        self.assertEqual(lead['created_by'], original['created_by'])
        self.assertEqual(lead['created_at'], original['created_at'])
        self.assertEqual(lead['name'], 'Updated client')

    def test_admin_upgrade_and_revocation_remove_shared_edit_permission(self):
        uid = self.create('tl1')
        self.as_user('admin')
        self.assertEqual(self.share(uid).status_code, 200)
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/level',
            json={'user_id': self.ids['exec2'], 'access_level': 'EDIT'},
        ).status_code, 200)
        self.as_user('exec2')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Edited'}
        ).status_code, 200)
        self.as_user('admin')
        self.assertEqual(self.share(uid, action='revoke').status_code, 200)
        self.as_user('exec2')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Denied'}
        ).status_code, 404)

    def test_edit_share_never_delegates_management_after_role_change(self):
        uid = self.create('tl1')
        self.as_user('admin')
        self.client.post(f'/api/client-access/{uid}/grant', json={
            'user_id': self.ids['exec2'], 'access_level': 'EDIT',
        })
        connection = database.get_db()
        try:
            with connection:
                connection.execute(
                    "UPDATE users SET role = 'sales_tl' WHERE id = ?",
                    (self.ids['exec2'],),
                )
        finally:
            connection.close()
        self.as_user('exec2')
        self.assertEqual(self.client.put(
            f'/api/leads/{uid}', json={'name': 'Permitted edit'}
        ).status_code, 200)
        self.assertEqual(self.share(uid, 'legacy').status_code, 404)
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/level',
            json={'user_id': self.ids['exec2'], 'access_level': 'EDIT'},
        ).status_code, 404)

    def test_access_level_validation_and_schema_constraints(self):
        uid = self.create('tl1')
        self.as_user('admin')
        for level in ('ADMIN', 'edit', '', None, ['EDIT']):
            self.assertEqual(self.client.post(
                f'/api/client-access/{uid}/grant',
                json={'user_id': self.ids['exec2'], 'access_level': level},
            ).status_code, 400)
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/level',
            json={'user_id': self.ids['exec2'], 'access_level': 'EDIT'},
        ).status_code, 409)
        self.share(uid)
        self.assertEqual(self.client.post(
            f'/api/client-access/{uid}/level',
            json={'user_id': self.ids['exec2']},
        ).status_code, 400)
        connection = database.get_db()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE client_lead_shares SET access_level = 'ADMIN'"
                )
        finally:
            connection.close()

    def test_version_six_upgrade_preserves_shares_and_history_as_view(self):
        path = Path(database.DB_PATH).parent / 'version_six.db'
        migrate_database(path, MIGRATIONS[:6])
        connection = sqlite3.connect(path)
        try:
            with connection:
                for name in ('owner', 'recipient'):
                    connection.execute(
                        'INSERT INTO users (username, password_hash) '
                        'VALUES (?, ?)', (name, 'test-placeholder'),
                    )
                connection.execute(
                    "INSERT INTO client_leads (name, created_by) "
                    "VALUES ('Existing client', 1)"
                )
                connection.execute(
                    'INSERT INTO client_lead_shares (lead_id, user_id) '
                    'VALUES (1, 2)'
                )
                connection.execute(
                    'INSERT INTO client_share_events '
                    '(lead_id, user_id, action, actor_user_id, actor_name) '
                    "VALUES (1, 2, 'grant', 1, 'owner')"
                )
        finally:
            connection.close()
        self.assertEqual(migrate_database(path), [7, 8])
        connection = sqlite3.connect(path)
        try:
            self.assertEqual(connection.execute(
                'SELECT lead_id, user_id, access_level FROM client_lead_shares'
            ).fetchone(), (1, 2, 'VIEW'))
            self.assertEqual(connection.execute(
                'SELECT action, actor_name, access_level, '
                'previous_access_level '
                'FROM client_share_events'
            ).fetchone(), ('grant', 'owner', 'VIEW', None))
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
