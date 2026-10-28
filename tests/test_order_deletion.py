"""PI ownership, team deletion, retained records and scoped audit logs."""
import json
import unittest

import test_orders
from backend import database


class OrderDeletionTests(unittest.TestCase):
    setUp=test_orders.OrderTests.setUp
    as_user=test_orders.OrderTests.as_user
    create=test_orders.OrderTests.create
    assign=test_orders.OrderTests.assign
    enquiry=test_orders.OrderTests.enquiry
    payload=test_orders.OrderTests.payload
    order=test_orders.OrderTests.order
    share=test_orders.OrderTests.share

    def test_owner_team_lead_and_admins_can_delete_with_actor_and_time(self):
        self.assign('exec1','tl1')
        for actor in ('exec1','tl1','admin','manager'):
            self.as_user('exec1')
            state=self.order();order_id=state['order']['id'];reference=state['order']['reference']
            self.as_user(actor)
            result=self.client.delete(f'/api/orders/{order_id}')
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(self.client.get(f'/api/orders/{order_id}').status_code,404)
            self.assertEqual(self.client.delete(f'/api/orders/{order_id}').status_code,404)
            log=self.client.get(f'/api/orders/deletions?client_id={self.parent}').json['deletions']
            self.assertEqual(log[0]['reference'],reference)
            self.assertEqual(log[0]['actor_name'],actor)
            self.assertTrue(log[0]['deleted_at'])
            connection=database.get_db()
            try:
                row=connection.execute('SELECT deleted_at,deleted_by FROM client_orders WHERE id=?',(order_id,)).fetchone()
                self.assertEqual(row['deleted_by'],self.ids[actor])
                self.assertTrue(row['deleted_at'])
                audit=connection.execute("SELECT * FROM audit_logs WHERE action='order_delete' AND entity_id=?",(str(order_id),)).fetchall()
                self.assertEqual(len(audit),1)
                self.assertEqual(json.loads(audit[0]['details'])['snapshot']['order']['reference'],reference)
                self.assertTrue(connection.execute('SELECT 1 FROM order_sku_lines WHERE order_id=?',(order_id,)).fetchone())
                self.assertFalse(connection.execute('PRAGMA foreign_key_check').fetchall())
            finally:connection.close()
        self.as_user('exec1')
        self.assertEqual(self.client.get(f'/api/orders?client_id={self.parent}').json['total'],0)
        lead=self.client.get(f'/api/leads/{self.parent}').json['lead']
        self.assertEqual(lead['order_count'],0)

    def test_shared_edit_access_does_not_grant_deletion_or_cross_team_logs(self):
        state=self.order();order_id=state['order']['id']
        self.share('EDIT');self.as_user('exec2')
        self.assertTrue(self.client.get(f'/api/orders/{order_id}').json['order']['can_edit'])
        self.assertFalse(self.client.get(f'/api/orders/{order_id}').json['order']['can_delete_order'])
        self.assertEqual(self.client.delete(f'/api/orders/{order_id}').status_code,403)
        self.as_user('tl2')
        self.assertEqual(self.client.delete(f'/api/orders/{order_id}').status_code,404)
        self.as_user('exec1');self.assertEqual(self.client.delete(f'/api/orders/{order_id}').status_code,200)
        self.as_user('tl2')
        self.assertEqual(self.client.get('/api/orders/deletions').json['deletions'],[])
        self.as_user(None)
        self.assertEqual(self.client.delete(f'/api/orders/{order_id}').status_code,401)
