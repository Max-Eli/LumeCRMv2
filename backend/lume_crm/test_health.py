"""
Tests for the liveness + readiness endpoints.

Both must:
  - return JSON
  - work unauthenticated (the load balancer can't carry session cookies)
  - bypass CSRF (HTTP GETs from the LB don't have a CSRF token)

Readiness must additionally fail with 503 when the database is
unavailable — without that signal the ALB will keep routing traffic
to a task whose connection pool is broken.
"""

from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TestCase, override_settings


@override_settings(ALLOWED_HOSTS=['testserver'])
class HealthEndpointsTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_liveness_returns_alive(self):
        resp = self.client.get('/healthz/live')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'alive'})

    def test_readiness_returns_ready_when_db_ok(self):
        resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'ready'})

    def test_readiness_returns_503_when_db_fails(self):
        # Patch the connections proxy that the view imports. The
        # readiness handler catches DatabaseError; anything else would
        # propagate, and the test would fail with the underlying type
        # (which is the desired signal — surface the real cause).
        with patch('lume_crm.health.connections') as mocked:
            mocked.__getitem__.return_value.cursor.side_effect = DatabaseError(
                'connection refused',
            )
            resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(
            resp.json(),
            {'status': 'not-ready', 'reason': 'database'},
        )

    def test_liveness_does_not_touch_db(self):
        # Patching the entire connections proxy: if liveness so much
        # as imports it, this assertion fails. Liveness MUST stay
        # database-free or transient RDS issues turn into restart loops.
        with patch('lume_crm.health.connections') as mock_conn:
            mock_conn.__getitem__.side_effect = AssertionError(
                'liveness should not touch the database',
            )
            resp = self.client.get('/healthz/live')
        self.assertEqual(resp.status_code, 200)
