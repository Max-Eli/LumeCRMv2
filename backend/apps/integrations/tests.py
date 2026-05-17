"""Tests for the integrations API.

Covers permission gating, list shape (one entry per provider with
or without connection state), connect-begin placeholder behavior,
disconnect lifecycle + audit shape, and tenant isolation.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.tenants.models import MembershipLocation, Tenant, TenantMembership
from apps.tenants.services import create_tenant_with_defaults

from .models import Connection

User = get_user_model()


def _make_user(email: str, **kwargs) -> User:
    return User.objects.create_user(email=email, password='test-password', **kwargs)


def _make_tenant_with_owner(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(),
        slug=slug,
        owner_user=owner,
        # Middleware only resolves ACTIVE tenants; the default TRIAL
        # status would cause request.tenant to come back None and
        # every test would 403 at the permission gate.
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_membership(*, user, tenant, role) -> TenantMembership:
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True,
    )
    MembershipLocation.objects.create(
        membership=membership,
        location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return membership


def _client_for(user) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


# ── Permission gating ────────────────────────────────────────────────


class IntegrationPermissionTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('permgate')

    def test_anonymous_user_blocked(self):
        client = APIClient()
        response = client.get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_allowed(self):
        response = _client_for(self.owner).get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_front_desk_blocked(self):
        fd_user = _make_user('fd@test.local')
        _make_membership(
            user=fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        response = _client_for(fd_user).get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_allowed(self):
        mgr_user = _make_user('mgr@test.local')
        _make_membership(
            user=mgr_user, tenant=self.tenant,
            role=TenantMembership.Role.MANAGER,
        )
        response = _client_for(mgr_user).get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ── List ──────────────────────────────────────────────────────────────


class IntegrationListTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('listtest')
        self.client_ = _client_for(self.owner)

    def test_list_returns_all_known_providers(self):
        response = self.client_.get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        keys = {row['key'] for row in response.data}
        self.assertEqual(
            keys,
            {'meta_facebook', 'meta_instagram', 'meta_whatsapp'},
        )

    def test_list_shape_for_disconnected_provider(self):
        response = self.client_.get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        fb = next(r for r in response.data if r['key'] == 'meta_facebook')
        self.assertEqual(fb['status'], 'disconnected')
        self.assertIsNone(fb['connection_id'])
        self.assertIsNone(fb['external_name'])
        self.assertEqual(fb['display_name'], 'Facebook Page Messenger')
        # OAuth not ready until Session 2.
        self.assertFalse(fb['oauth_ready'])

    def test_list_shape_for_connected_provider(self):
        # Manually create a connected row to exercise the serialize path.
        Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_FACEBOOK,
            status=Connection.Status.CONNECTED,
            external_id='1234567890',
            external_name='Acme Med Spa',
        )
        response = self.client_.get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        fb = next(r for r in response.data if r['key'] == 'meta_facebook')
        self.assertEqual(fb['status'], 'connected')
        self.assertIsNotNone(fb['connection_id'])
        self.assertEqual(fb['external_name'], 'Acme Med Spa')


# ── Connect begin (placeholder) ──────────────────────────────────────


class IntegrationConnectBeginTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('begintest')
        self.client_ = _client_for(self.owner)

    def test_returns_501_oauth_not_ready_in_v1(self):
        response = self.client_.post(
            reverse('integrations-connect-begin', args=['meta_facebook']),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)
        self.assertEqual(response.data['code'], 'oauth_not_ready')

    def test_unknown_provider_returns_400(self):
        response = self.client_.post(
            reverse('integrations-connect-begin', args=['some_random_provider']),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_attempt_writes_audit_entry(self):
        before = AuditLog.objects.filter(
            resource_type='integration_connection',
        ).count()
        self.client_.post(
            reverse('integrations-connect-begin', args=['meta_facebook']),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        after = AuditLog.objects.filter(
            resource_type='integration_connection',
        ).count()
        self.assertEqual(after, before + 1)
        entry = AuditLog.objects.filter(
            resource_type='integration_connection',
        ).latest('timestamp')
        self.assertEqual(entry.metadata['event'], 'connect_begin_attempted')
        self.assertEqual(entry.metadata['provider'], 'meta_facebook')


# ── Disconnect ───────────────────────────────────────────────────────


class IntegrationDisconnectTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('disconnecttest')
        self.connection = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_FACEBOOK,
            status=Connection.Status.CONNECTED,
            external_id='1234567890',
            external_name='Acme Med Spa',
        )
        # ADR 0027 — auth_data is encrypted; set via helper, not direct.
        self.connection.set_auth_data({'access_token': 'fake-token'})
        self.connection.save(update_fields=['auth_data'])
        self.client_ = _client_for(self.owner)

    def test_disconnect_clears_auth_and_externals(self):
        response = self.client_.post(
            reverse('integrations-disconnect', args=[self.connection.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, Connection.Status.DISCONNECTED)
        # Encrypted blob cleared to empty string; decrypt yields {}.
        self.assertEqual(self.connection.auth_data, '')
        self.assertEqual(self.connection.auth_data_dict, {})
        self.assertEqual(self.connection.external_id, '')
        self.assertEqual(self.connection.external_name, '')
        self.assertIsNotNone(self.connection.disconnected_at)

    def test_disconnect_writes_audit_entry(self):
        self.client_.post(
            reverse('integrations-disconnect', args=[self.connection.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        entry = (
            AuditLog.objects
            .filter(
                resource_type='integration_connection',
                metadata__event='connection_disconnected',
            )
            .latest('timestamp')
        )
        self.assertEqual(entry.metadata['provider'], 'meta_facebook')
        self.assertEqual(entry.metadata['previous_status'], 'connected')
        self.assertEqual(entry.metadata['previous_external_id'], '1234567890')

    def test_disconnect_already_disconnected_is_noop(self):
        self.connection.status = Connection.Status.DISCONNECTED
        self.connection.save()
        response = self.client_.post(
            reverse('integrations-disconnect', args=[self.connection.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ── Tenant isolation ─────────────────────────────────────────────────


class IntegrationTenantIsolationTests(TestCase):
    def test_other_tenants_connections_not_visible_or_disconnectable(self):
        tenant_a, owner_a = _make_tenant_with_owner('iso-a')
        tenant_b, _owner_b = _make_tenant_with_owner('iso-b')
        connection_b = Connection.objects.create(
            tenant=tenant_b,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='b-account',
            external_name='Tenant B',
        )

        client = _client_for(owner_a)
        # Tenant A's list should not include tenant B's IG account name.
        list_resp = client.get(
            reverse('integrations-list'),
            HTTP_X_TENANT_SLUG=tenant_a.slug,
        )
        ig = next(r for r in list_resp.data if r['key'] == 'meta_instagram')
        self.assertNotEqual(ig['external_name'], 'Tenant B')
        self.assertEqual(ig['status'], 'disconnected')

        # Tenant A trying to disconnect tenant B's connection should 404.
        disc_resp = client.post(
            reverse('integrations-disconnect', args=[connection_b.pk]),
            HTTP_X_TENANT_SLUG=tenant_a.slug,
        )
        self.assertEqual(disc_resp.status_code, status.HTTP_404_NOT_FOUND)


# ── Token encryption helper (ADR 0027 §1) ───────────────────────────


from . import security as _security  # noqa: E402


class TokenEncryptionTests(TestCase):
    def test_round_trip_dict(self):
        token = {'access_token': 'abc.def.ghi', 'page_id': '123', 'scopes': ['a', 'b']}
        ciphertext = _security.encrypt_auth_data(token)
        # The blob must NOT contain the plaintext token anywhere.
        self.assertNotIn('abc.def.ghi', ciphertext)
        self.assertNotIn('access_token', ciphertext)
        self.assertEqual(_security.decrypt_auth_data(ciphertext), token)

    def test_empty_input_round_trips(self):
        self.assertEqual(_security.decrypt_auth_data(''), {})
        self.assertEqual(_security.decrypt_auth_data('   '), {})
        empty_cipher = _security.encrypt_auth_data({})
        self.assertEqual(_security.decrypt_auth_data(empty_cipher), {})

    def test_corrupt_ciphertext_raises(self):
        with self.assertRaises(_security.EncryptionError):
            _security.decrypt_auth_data('not-a-valid-fernet-token')

    def test_connection_model_accessors(self):
        from apps.tenants.services import create_tenant_with_defaults
        owner = User.objects.create_user(email='enc-owner@test.local', password='test')
        tenant = create_tenant_with_defaults(
            name='Enc', slug='enctest', owner_user=owner,
            status=Tenant.Status.ACTIVE,
        )
        conn = Connection.objects.create(
            tenant=tenant,
            provider=Connection.Provider.META_INSTAGRAM,
        )
        # Empty by default.
        self.assertEqual(conn.auth_data_dict, {})

        conn.set_auth_data({'access_token': 'secret-token-value'})
        conn.save(update_fields=['auth_data'])
        # The raw column is opaque ciphertext, not the plaintext.
        self.assertNotIn('secret-token-value', conn.auth_data)
        # Accessor decrypts.
        self.assertEqual(
            conn.auth_data_dict['access_token'], 'secret-token-value',
        )

        # Clear wipes the blob.
        conn.clear_auth_data()
        conn.save(update_fields=['auth_data'])
        conn.refresh_from_db()
        self.assertEqual(conn.auth_data, '')
        self.assertEqual(conn.auth_data_dict, {})


# ── OAuth flow (ADR 0027 §2) ────────────────────────────────────────


from unittest.mock import patch  # noqa: E402

from django.test import override_settings  # noqa: E402

from . import meta as _meta  # noqa: E402


@override_settings(
    INSTAGRAM_APP_ID='test-ig-app-id',
    INSTAGRAM_APP_SECRET='test-ig-app-secret',
    META_WEBHOOK_VERIFY_TOKEN='test-verify-token',
    META_OAUTH_REDIRECT_URI='https://api.xn--lumcrm-5ua.test/api/integrations/meta/oauth/callback/',
)
class OAuthConnectBeginTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('oauthbegin')
        self.client_ = _client_for(self.owner)

    def test_oauth_ready_returns_authorize_url(self):
        url = reverse('integrations-connect-begin', args=['meta_instagram'])
        response = self.client_.post(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # FRONTEND CONTRACT — these exact field names are consumed by
        # `frontend/src/lib/integrations.ts:ConnectBeginResponse` and the
        # connect-button redirect logic in
        # `frontend/src/app/(app)/org/integrations/page.tsx:handleConnect`.
        # If you rename a key here, grep both files first and update the
        # consumer in the same commit. A previous incident (2026-05-16)
        # shipped a renamed key without updating the frontend; the OAuth
        # flow completed server-side but the browser never redirected,
        # showing only a "Connect flow launched" toast.
        self.assertEqual(
            set(response.data.keys()),
            {'authorize_url', 'state', 'connection_id'},
        )
        self.assertIn('state', response.data)
        # State is stored on the session.
        session = self.client_.session
        self.assertEqual(session.get('meta_oauth_state'), response.data['state'])
        self.assertEqual(session.get('meta_oauth_provider'), 'meta_instagram')
        # Authorize URL targets the Instagram Login OAuth dialog with
        # the Instagram product's App ID (NOT the parent Meta App ID).
        self.assertTrue(
            response.data['authorize_url'].startswith(
                'https://www.instagram.com/oauth/authorize?'
            )
        )
        self.assertIn('client_id=test-ig-app-id', response.data['authorize_url'])
        # `instagram_business_manage_messages` is the Instagram-Login
        # scope name (not the Facebook-Login bare `instagram_manage_messages`).
        # ADR 0027 revision 2 swapped from FB Login to IG Login.
        self.assertIn(
            'instagram_business_manage_messages',
            response.data['authorize_url'],
        )
        self.assertIn(f'state={response.data["state"]}', response.data['authorize_url'])
        # Connection row created in CONNECTING state.
        connection = Connection.objects.get(
            tenant=self.tenant, provider='meta_instagram',
        )
        self.assertEqual(connection.status, Connection.Status.CONNECTING)


@override_settings(
    INSTAGRAM_APP_ID='', INSTAGRAM_APP_SECRET='',
    META_WEBHOOK_VERIFY_TOKEN='',
)
class OAuthConnectBeginNotReadyTests(TestCase):
    """When env credentials aren't set, the endpoint still returns 501
    with code='oauth_not_ready' (matches the pre-ADR-0027 behavior)."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('oauthnotready')
        self.client_ = _client_for(self.owner)

    def test_not_ready_returns_501(self):
        url = reverse('integrations-connect-begin', args=['meta_instagram'])
        response = self.client_.post(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)
        self.assertEqual(response.data['code'], 'oauth_not_ready')


class OAuthStateTokenTests(TestCase):
    """Direct unit coverage of state generation + consumption helpers."""

    def test_state_is_random_per_call(self):
        a = _meta.generate_state_token()
        b = _meta.generate_state_token()
        self.assertNotEqual(a, b)
        # 32 bytes url-safe base64 ~= 43 chars.
        self.assertGreaterEqual(len(a), 40)

    def test_consume_rejects_missing_state(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        request = RequestFactory().get('/cb')
        request.session = SessionStore()
        with self.assertRaises(_meta.MetaOAuthError):
            _meta.consume_state_from_session(request, 'some-state')

    def test_consume_rejects_mismatched_state(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        request = RequestFactory().get('/cb')
        request.session = SessionStore()
        _meta.store_state_in_session(
            request, 'real-state',
            tenant_id=1, provider='meta_instagram',
        )
        with self.assertRaises(_meta.MetaOAuthError):
            _meta.consume_state_from_session(request, 'wrong-state')

    def test_consume_one_time_use(self):
        """Same state can't be replayed (clears on first consume)."""
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        request = RequestFactory().get('/cb')
        request.session = SessionStore()
        _meta.store_state_in_session(
            request, 'reuse-state',
            tenant_id=1, provider='meta_instagram',
        )
        binding = _meta.consume_state_from_session(request, 'reuse-state')
        self.assertEqual(binding['tenant_id'], 1)
        # Second consume must fail.
        with self.assertRaises(_meta.MetaOAuthError):
            _meta.consume_state_from_session(request, 'reuse-state')

    def test_consume_rejects_expired_state(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        request = RequestFactory().get('/cb')
        request.session = SessionStore()
        _meta.store_state_in_session(
            request, 'old-state',
            tenant_id=1, provider='meta_instagram',
        )
        # Forge an old timestamp.
        request.session['meta_oauth_issued_at'] = 0
        request.session.modified = True
        with self.assertRaises(_meta.MetaOAuthError):
            _meta.consume_state_from_session(request, 'old-state')


@override_settings(
    INSTAGRAM_APP_ID='test-ig-app-id',
    INSTAGRAM_APP_SECRET='test-ig-app-secret',
    META_WEBHOOK_VERIFY_TOKEN='test-verify-token',
    META_OAUTH_REDIRECT_URI='http://localhost:8000/api/integrations/meta/oauth/callback/',
    PUBLIC_BASE_URL='http://localhost:3000',
)
class OAuthCallbackTests(TestCase):
    """End-to-end exercise of the callback view with IG Login calls mocked."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('cbtest')
        self.client_ = _client_for(self.owner)
        # Kick off OAuth so session has the state + connection row exists.
        begin = self.client_.post(
            reverse('integrations-connect-begin', args=['meta_instagram']),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.state = begin.data['state']

    @staticmethod
    def _resp(body):
        class _R:
            status_code = 200
            text = ''
            def json(self):
                return body
        return _R()

    def _mock_get(self, *args, **kwargs):
        """Stub graph.instagram.com GETs (only the /me profile call here;
        the long-token exchange is POSTed)."""
        url = args[0]
        if '/me' in url:
            return self._resp({
                'user_id': '17841405822304914',
                'username': 'acmemedspa',
                'name': 'Acme Med Spa',
            })
        return self._resp({})

    def _mock_post(self, *args, **kwargs):
        """Stub IG POST endpoints: code exchange, long-token exchange, subscribe-apps."""
        url = args[0]
        if 'api.instagram.com/oauth/access_token' in url:
            return self._resp({
                'access_token': 'short-lived-ig-token',
                'user_id': '17841405822304914',
                'permissions': [
                    'instagram_business_basic',
                    'instagram_business_manage_messages',
                ],
            })
        if 'graph.instagram.com/access_token' in url:
            # Long-lived token exchange — POST not GET per the
            # empirical workaround noted in _ig_exchange_short_for_long_token.
            return self._resp({
                'access_token': 'long-lived-ig-token',
                'token_type': 'bearer',
                'expires_in': 5184000,
            })
        if 'subscribed_apps' in url:
            return self._resp({'success': True})
        return self._resp({})

    def test_successful_callback_persists_encrypted_tokens(self):
        with patch('apps.integrations.meta.requests.get', side_effect=self._mock_get), \
             patch('apps.integrations.meta.requests.post', side_effect=self._mock_post):
            response = self.client_.get(
                reverse('integrations-meta-oauth-callback')
                + f'?code=test-code&state={self.state}'
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn('connected=instagram', response['Location'])

        connection = Connection.objects.get(
            tenant=self.tenant, provider='meta_instagram',
        )
        self.assertEqual(connection.status, Connection.Status.CONNECTED)
        # external_id holds the IG user_id (what Meta sends as
        # entry[].id in webhook payloads, used for fast routing).
        self.assertEqual(connection.external_id, '17841405822304914')
        self.assertIn('acmemedspa', connection.external_name)
        # Decrypts back to what we stored.
        payload = connection.auth_data_dict
        self.assertEqual(payload['ig_user_id'], '17841405822304914')
        self.assertEqual(payload['access_token'], 'long-lived-ig-token')
        self.assertEqual(payload['ig_username'], 'acmemedspa')
        # Tokens NEVER stored in plaintext (sanity).
        self.assertNotIn('long-lived-ig-token', connection.auth_data)

    def test_invalid_state_redirects_with_error(self):
        response = self.client_.get(
            reverse('integrations-meta-oauth-callback')
            + '?code=test-code&state=wrong-state'
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('integration_error=invalid_state', response['Location'])

    def test_meta_returns_error_redirects(self):
        response = self.client_.get(
            reverse('integrations-meta-oauth-callback')
            + '?error=access_denied&state=' + self.state
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('integration_error=consent_cancelled', response['Location'])


# ── Webhook (ADR 0027 §3-4) ─────────────────────────────────────────


import json as _json  # noqa: E402

from apps.customers.models import Customer  # noqa: E402

from .models import SocialMessage, SocialThread  # noqa: E402


@override_settings(
    META_APP_ID='test-app-id',
    META_APP_SECRET='test-app-secret',
    META_WEBHOOK_VERIFY_TOKEN='test-verify-token',
)
class MetaWebhookHandshakeTests(TestCase):
    def setUp(self):
        self.url = reverse('integrations-webhook-meta')

    def test_valid_token_echoes_challenge(self):
        client = APIClient()
        response = client.get(
            self.url,
            {'hub.mode': 'subscribe',
             'hub.verify_token': 'test-verify-token',
             'hub.challenge': 'random-challenge-789'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), 'random-challenge-789')

    def test_wrong_token_returns_403(self):
        client = APIClient()
        response = client.get(
            self.url,
            {'hub.mode': 'subscribe',
             'hub.verify_token': 'WRONG',
             'hub.challenge': 'x'},
        )
        self.assertEqual(response.status_code, 403)

    def test_wrong_mode_returns_403(self):
        client = APIClient()
        response = client.get(
            self.url,
            {'hub.mode': 'unsubscribe',
             'hub.verify_token': 'test-verify-token',
             'hub.challenge': 'x'},
        )
        self.assertEqual(response.status_code, 403)


@override_settings(
    META_APP_ID='test-app-id',
    META_APP_SECRET='test-app-secret',
    META_WEBHOOK_VERIFY_TOKEN='test-verify-token',
    META_TEST_MODE=True,  # bypass signature for ingestion tests
)
class MetaWebhookIngestionTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('ingtest')
        self.connection = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-id-999',
            external_name='Acme Med Spa (@acmemedspa)',
        )
        self.url = reverse('integrations-webhook-meta')

    def _payload(self, *, page_id='page-id-999', sender_id='psid-1', mid='m-1', text='hi'):
        return {
            'object': 'instagram',
            'entry': [{
                'id': page_id,
                'time': 1700000000000,
                'messaging': [{
                    'sender': {'id': sender_id},
                    'recipient': {'id': page_id},
                    'timestamp': 1700000000000,
                    'message': {'mid': mid, 'text': text},
                }],
            }],
        }

    def test_inbound_message_creates_customer_and_thread(self):
        client = APIClient()
        response = client.post(
            self.url,
            data=_json.dumps(self._payload()),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages_created'], 1)

        # Social-guest customer created.
        customer = Customer.objects.get(
            tenant=self.tenant,
            external_source='instagram',
            external_id='psid-1',
        )
        self.assertTrue(customer.is_social_guest)
        self.assertEqual(
            customer.acquisition_source,
            Customer.AcquisitionSource.INSTAGRAM,
        )
        self.assertFalse(customer.email_marketing_opt_in)
        self.assertFalse(customer.sms_marketing_opt_in)

        # Thread + message rows.
        thread = SocialThread.objects.get(tenant=self.tenant, customer=customer)
        self.assertEqual(thread.provider, 'instagram')
        self.assertIsNone(thread.read_at)  # unread

        message = SocialMessage.objects.get(tenant=self.tenant, thread=thread)
        self.assertEqual(message.direction, SocialMessage.Direction.INBOUND)
        self.assertEqual(message.body, 'hi')
        self.assertEqual(message.external_message_id, 'm-1')

    def test_duplicate_mid_is_idempotent(self):
        client = APIClient()
        client.post(
            self.url,
            data=_json.dumps(self._payload()),
            content_type='application/json',
        )
        # Replay the exact same payload.
        response = client.post(
            self.url,
            data=_json.dumps(self._payload()),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages_created'], 0)
        self.assertEqual(response.data['messages_duplicate'], 1)
        # Still only one row.
        self.assertEqual(
            SocialMessage.objects.filter(tenant=self.tenant).count(),
            1,
        )

    def test_second_message_in_existing_thread_reuses_customer(self):
        client = APIClient()
        client.post(
            self.url,
            data=_json.dumps(self._payload(mid='m-1', text='first')),
            content_type='application/json',
        )
        client.post(
            self.url,
            data=_json.dumps(self._payload(mid='m-2', text='second')),
            content_type='application/json',
        )
        # Single customer + thread; two messages.
        self.assertEqual(
            Customer.objects.filter(
                tenant=self.tenant, external_source='instagram',
            ).count(),
            1,
        )
        self.assertEqual(
            SocialThread.objects.filter(tenant=self.tenant).count(), 1,
        )
        self.assertEqual(
            SocialMessage.objects.filter(tenant=self.tenant).count(), 2,
        )

    def test_unknown_page_id_does_not_crash(self):
        client = APIClient()
        response = client.post(
            self.url,
            data=_json.dumps(self._payload(page_id='unknown-page')),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pages_unmatched'], 1)
        # No customers / threads / messages created.
        self.assertEqual(
            Customer.objects.filter(
                tenant=self.tenant, external_source='instagram',
            ).count(),
            0,
        )

    def test_echo_message_is_skipped(self):
        """Outbound echoes (`is_echo: True`) must not double-count."""
        payload = self._payload()
        payload['entry'][0]['messaging'][0]['message']['is_echo'] = True
        client = APIClient()
        response = client.post(
            self.url,
            data=_json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages_created'], 0)

    def test_cross_tenant_isolation(self):
        """A second tenant has its own Connection; webhooks for tenant A's
        page MUST NOT create rows under tenant B."""
        tenant_b, _ = _make_tenant_with_owner('ingtest-b')
        Connection.objects.create(
            tenant=tenant_b,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-id-OTHER',
        )
        client = APIClient()
        client.post(
            self.url,
            data=_json.dumps(self._payload(page_id='page-id-999')),
            content_type='application/json',
        )
        # tenant_b sees nothing.
        self.assertEqual(
            Customer.objects.filter(
                tenant=tenant_b, external_source='instagram',
            ).count(),
            0,
        )
        self.assertEqual(
            SocialMessage.objects.filter(tenant=tenant_b).count(), 0,
        )


@override_settings(
    META_APP_ID='test-app-id',
    META_APP_SECRET='test-app-secret-shh',
    META_WEBHOOK_VERIFY_TOKEN='test-verify-token',
    META_TEST_MODE=False,  # exercise real signature checks
)
class MetaWebhookSignatureTests(TestCase):
    """When META_TEST_MODE is OFF, the signature gate must enforce."""

    def setUp(self):
        self.url = reverse('integrations-webhook-meta')

    def _good_signature(self, body: bytes) -> str:
        import hashlib, hmac
        return 'sha256=' + hmac.new(
            b'test-app-secret-shh', body, hashlib.sha256,
        ).hexdigest()

    def test_valid_signature_accepted(self):
        body = _json.dumps({'entry': []}).encode()
        client = APIClient()
        response = client.post(
            self.url,
            data=body,
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=self._good_signature(body),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['received'])

    def test_invalid_signature_returns_200_with_received_false(self):
        body = _json.dumps({'entry': []}).encode()
        client = APIClient()
        response = client.post(
            self.url,
            data=body,
            content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256='sha256=deadbeef',
        )
        # 200, NOT 4xx — ADR 0027 §3.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['received'])
        self.assertEqual(response.data['reason'], 'invalid_signature')

    def test_missing_signature_returns_200_with_received_false(self):
        body = _json.dumps({'entry': []}).encode()
        client = APIClient()
        response = client.post(
            self.url, data=body, content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['received'])


# ── Social-guest merge endpoint (ADR 0027 §8b) ──────────────────────


class SocialGuestMergeTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('mergetest')
        self.client_ = _client_for(self.owner)
        self.connection = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-merge-1',
        )
        self.guest = Customer.objects.create(
            tenant=self.tenant,
            first_name='Instagram visitor abc123',
            last_name='',
            acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
            external_source='instagram',
            external_id='psid-abc',
            is_social_guest=True,
            instagram_handle='maria.beauty',
        )
        self.real = Customer.objects.create(
            tenant=self.tenant,
            first_name='Maria',
            last_name='Lopez',
            email='maria@example.com',
            phone='+15551234567',
        )
        self.thread = SocialThread.objects.create(
            tenant=self.tenant,
            provider='instagram',
            connection=self.connection,
            customer=self.guest,
            external_thread_id='psid-abc',
            last_message_at='2026-05-15T10:00:00Z',
        )
        SocialMessage.objects.create(
            tenant=self.tenant,
            thread=self.thread,
            direction='inbound',
            body='hi',
            external_message_id='mid-1',
        )

    def test_merge_moves_thread_and_preserves_acquisition(self):
        url = reverse(
            'customer-merge-into',
            args=[self.guest.id, self.real.id],
        )
        response = self.client_.post(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, 200)

        self.thread.refresh_from_db()
        self.assertEqual(self.thread.customer_id, self.real.id)

        self.real.refresh_from_db()
        self.assertEqual(
            self.real.acquisition_source,
            Customer.AcquisitionSource.INSTAGRAM,
        )
        self.assertEqual(self.real.instagram_handle, 'maria.beauty')

        self.guest.refresh_from_db()
        self.assertEqual(self.guest.status, Customer.Status.INACTIVE)
        self.assertFalse(self.guest.is_social_guest)

    def test_merge_real_customer_into_real_is_rejected(self):
        # Both are real (not guests).
        other_real = Customer.objects.create(
            tenant=self.tenant, first_name='Other', last_name='Person',
        )
        url = reverse(
            'customer-merge-into', args=[other_real.id, self.real.id],
        )
        response = self.client_.post(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'source_not_guest')

    def test_merge_into_self_rejected(self):
        # Set up a single guest pointing at itself.
        url = reverse(
            'customer-merge-into', args=[self.guest.id, self.guest.id],
        )
        response = self.client_.post(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertIn(response.status_code, (400, 404))

    def test_merge_into_another_guest_rejected(self):
        other_guest = Customer.objects.create(
            tenant=self.tenant,
            first_name='Instagram visitor xyz',
            is_social_guest=True,
            acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
        )
        url = reverse(
            'customer-merge-into', args=[self.guest.id, other_guest.id],
        )
        response = self.client_.post(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'target_is_guest')

    def test_merge_preserves_existing_acquisition_on_target(self):
        """If the real customer already has a non-MANUAL acquisition
        source (e.g. zenoti_import), the merge keeps it — the IG
        attribution is informational only."""
        self.real.acquisition_source = Customer.AcquisitionSource.ZENOTI_IMPORT
        self.real.save(update_fields=['acquisition_source'])
        url = reverse(
            'customer-merge-into', args=[self.guest.id, self.real.id],
        )
        self.client_.post(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.real.refresh_from_db()
        # Stayed zenoti_import.
        self.assertEqual(
            self.real.acquisition_source,
            Customer.AcquisitionSource.ZENOTI_IMPORT,
        )


# ── Public booking sets acquisition_source = online_booking ─────────


class BookingAcquisitionSourceTests(TestCase):
    """Sanity check: customers created via the public booking page
    carry the right first-touch attribution."""

    def test_booking_create_sets_online_booking(self):
        from apps.booking.services import find_or_create_customer
        tenant, _ = _make_tenant_with_owner('bookatt')
        customer, created = find_or_create_customer(
            tenant=tenant,
            first_name='Jane',
            last_name='Doe',
            email='jane@example.com',
            phone='+15550001111',
        )
        self.assertTrue(created)
        self.assertEqual(
            customer.acquisition_source,
            Customer.AcquisitionSource.ONLINE_BOOKING,
        )


# ── Data Deletion Callback (Meta Platform Terms) ────────────────────


@override_settings(
    META_APP_ID='test-app-id',
    META_APP_SECRET='test-app-secret',
    META_WEBHOOK_VERIFY_TOKEN='test-verify-token',
    META_TEST_MODE=True,  # skip signature verification in tests
    PUBLIC_BASE_URL='https://api.xn--lumcrm-5ua.test',
)
class MetaDataDeletionTests(TestCase):
    """Meta sends a `signed_request` POST when a user removes the app.
    We verify, revoke their connections, persist an audit row, return
    a confirmation URL the user can hit to verify processing."""

    def _signed_request_for(self, user_id: str) -> str:
        """Build a signed_request payload — in TEST_MODE the signature
        is not verified, so we use a placeholder."""
        import base64
        import json as _json
        payload = {
            'user_id': user_id,
            'algorithm': 'HMAC-SHA256',
            'issued_at': 1234567890,
        }
        payload_b64 = base64.urlsafe_b64encode(
            _json.dumps(payload).encode('utf-8')
        ).rstrip(b'=').decode('ascii')
        return f'sig.{payload_b64}'

    def test_clears_tokens_for_authorising_user(self):
        tenant, _ = _make_tenant_with_owner('deletion-clear')
        conn = Connection.objects.create(
            tenant=tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-123',
            external_name='Acme Spa IG',
        )
        conn.set_auth_data({
            'page_id': 'page-123',
            'page_access_token': 'PAT-xyz',
            'fb_user_id': 'fb-user-42',
        })
        conn.save()

        response = APIClient().post(
            reverse('integrations-meta-data-deletion'),
            data={'signed_request': self._signed_request_for('fb-user-42')},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirmation_code', response.data)
        self.assertIn('url', response.data)

        conn.refresh_from_db()
        self.assertEqual(conn.status, Connection.Status.DISCONNECTED)
        self.assertEqual(conn.auth_data, '')

    def test_audit_row_persisted(self):
        tenant, _ = _make_tenant_with_owner('deletion-audit')
        conn = Connection.objects.create(
            tenant=tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-555',
        )
        conn.set_auth_data({'fb_user_id': 'fb-user-99'})
        conn.save()

        response = APIClient().post(
            reverse('integrations-meta-data-deletion'),
            data={'signed_request': self._signed_request_for('fb-user-99')},
        )
        from apps.integrations.models import DataDeletionRequest
        row = DataDeletionRequest.objects.get(
            confirmation_code=response.data['confirmation_code'],
        )
        self.assertEqual(row.status, DataDeletionRequest.Status.PROCESSED)
        self.assertEqual(row.external_user_id, 'fb-user-99')
        self.assertEqual(row.affected_connection_ids, [conn.pk])
        self.assertEqual(row.affected_page_ids, ['page-555'])

    def test_unmatched_user_still_returns_confirmation(self):
        """A user can remove the app before completing OAuth. We still
        respond with a valid confirmation so Meta doesn't spin."""
        response = APIClient().post(
            reverse('integrations-meta-data-deletion'),
            data={'signed_request': self._signed_request_for('no-match')},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirmation_code', response.data)

    def test_missing_signed_request_returns_400(self):
        response = APIClient().post(
            reverse('integrations-meta-data-deletion'),
            data={},
        )
        self.assertEqual(response.status_code, 400)

    def test_status_endpoint_returns_processed_row(self):
        tenant, _ = _make_tenant_with_owner('deletion-status')
        conn = Connection.objects.create(
            tenant=tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-777',
        )
        conn.set_auth_data({'fb_user_id': 'fb-user-77'})
        conn.save()
        post_response = APIClient().post(
            reverse('integrations-meta-data-deletion'),
            data={'signed_request': self._signed_request_for('fb-user-77')},
        )
        code = post_response.data['confirmation_code']
        get_response = APIClient().get(
            reverse('integrations-meta-data-deletion-status', args=[code]),
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.data['status'], 'processed')
        self.assertEqual(get_response.data['integrations_revoked'], 1)

    def test_status_endpoint_unknown_code_404(self):
        response = APIClient().get(
            reverse('integrations-meta-data-deletion-status', args=['nope']),
        )
        self.assertEqual(response.status_code, 404)


# ── Social inbox API ────────────────────────────────────────────────


def _make_thread_with_message(*, tenant, connection, customer, body='hi'):
    from apps.integrations.models import SocialMessage, SocialThread
    now = timezone.now()
    thread = SocialThread.objects.create(
        tenant=tenant,
        provider=SocialThread.Provider.INSTAGRAM,
        connection=connection,
        customer=customer,
        external_thread_id='psid-' + str(customer.pk),
        external_username='@' + customer.first_name.lower(),
        last_message_at=now,
        last_inbound_at=now,
    )
    msg = SocialMessage.objects.create(
        tenant=tenant,
        thread=thread,
        direction=SocialMessage.Direction.INBOUND,
        body=body,
        external_message_id='mid-' + str(thread.pk),
        status=SocialMessage.Status.RECEIVED,
        received_at=now,
    )
    return thread, msg


class SocialThreadListTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('socinbox')
        self.client_ = _client_for(self.owner)
        self.conn = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-x',
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            first_name='Maria',
            last_name='Beauty',
            instagram_handle='maria.beauty',
            is_social_guest=True,
            acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
        )
        self.thread, _ = _make_thread_with_message(
            tenant=self.tenant,
            connection=self.conn,
            customer=self.customer,
            body='hey do you have any openings tomorrow?',
        )

    def test_list_returns_threads(self):
        response = self.client_.get(
            reverse('social-thread-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        row = response.data['threads'][0]
        self.assertEqual(row['provider'], 'instagram')
        self.assertTrue(row['is_unread'])
        self.assertEqual(row['customer']['full_name'], 'Maria Beauty')
        self.assertEqual(
            row['customer']['acquisition_source'], 'instagram',
        )

    def test_list_no_body_in_summary(self):
        """The list endpoint must NOT carry message bodies — PHI stays
        on the detail endpoint where access is audit-logged."""
        response = self.client_.get(
            reverse('social-thread-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        row = response.data['threads'][0]
        self.assertNotIn('body', row)
        self.assertNotIn('messages', row)

    def test_unread_filter(self):
        # Mark as read, then ?unread=1 should return zero.
        self.thread.read_at = timezone.now()
        self.thread.save()
        response = self.client_.get(
            reverse('social-thread-list') + '?unread=1',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.data['count'], 0)

    def test_tenant_isolation(self):
        # Another tenant's owner cannot see this tenant's threads.
        other_tenant, other_owner = _make_tenant_with_owner('other-socinbox')
        response = _client_for(other_owner).get(
            reverse('social-thread-list'),
            HTTP_X_TENANT_SLUG=other_tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_front_desk_forbidden(self):
        """Front-desk role lacks MANAGE_INTEGRATIONS — gets 403."""
        fd = _make_user('fd@test.local')
        _make_membership(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        response = _client_for(fd).get(
            reverse('social-thread-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 403)


class SocialThreadDetailTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('socdetail')
        self.client_ = _client_for(self.owner)
        self.conn = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-x',
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            first_name='Sam',
            last_name='Lee',
            acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
        )
        self.thread, self.msg = _make_thread_with_message(
            tenant=self.tenant,
            connection=self.conn,
            customer=self.customer,
            body='hi! what services do you offer?',
        )

    def test_detail_returns_messages(self):
        response = self.client_.get(
            reverse('social-thread-detail', args=[self.thread.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['thread']['id'], self.thread.pk)
        self.assertEqual(len(response.data['messages']), 1)
        self.assertEqual(
            response.data['messages'][0]['body'],
            'hi! what services do you offer?',
        )

    def test_detail_writes_audit_log(self):
        before = AuditLog.objects.filter(
            resource_type='social_thread', action=AuditLog.Action.READ,
        ).count()
        self.client_.get(
            reverse('social-thread-detail', args=[self.thread.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        after = AuditLog.objects.filter(
            resource_type='social_thread', action=AuditLog.Action.READ,
        ).count()
        self.assertEqual(after, before + 1)
        entry = AuditLog.objects.filter(
            resource_type='social_thread',
        ).latest('timestamp')
        # PHI safety — audit metadata must NOT include the message body.
        self.assertNotIn('body', entry.metadata)
        self.assertEqual(entry.metadata['event'], 'thread_read')
        self.assertEqual(entry.metadata['message_count'], 1)

    def test_cross_tenant_404(self):
        other_tenant, other_owner = _make_tenant_with_owner('other-socdetail')
        response = _client_for(other_owner).get(
            reverse('social-thread-detail', args=[self.thread.pk]),
            HTTP_X_TENANT_SLUG=other_tenant.slug,
        )
        self.assertEqual(response.status_code, 404)

    def test_mark_read_stamps_read_at(self):
        self.assertIsNone(self.thread.read_at)
        response = self.client_.post(
            reverse('social-thread-mark-read', args=[self.thread.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.thread.refresh_from_db()
        self.assertIsNotNone(self.thread.read_at)

    def test_mark_read_idempotent(self):
        already_read_at = timezone.now() - timezone.timedelta(hours=1)
        self.thread.read_at = already_read_at
        self.thread.save()
        self.client_.post(
            reverse('social-thread-mark-read', args=[self.thread.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.thread.refresh_from_db()
        # Should NOT have re-stamped.
        self.assertEqual(self.thread.read_at, already_read_at)


# ── Outbound send / reply endpoint (Session 2C, ADR 0027 §7) ────────


from unittest.mock import patch as _patch_outbound  # noqa: E402


class SocialThreadReplyTests(TestCase):
    """End-to-end coverage of the reply endpoint with Meta's send call mocked."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('reply')
        self.client_ = _client_for(self.owner)
        self.conn = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-x',
        )
        self.conn.set_auth_data({
            'ig_user_id': '17841',
            'access_token': 'IGAA-test-token',
            'ig_username': 'spa',
        })
        self.conn.save()
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            first_name='Reply',
            last_name='Subject',
            acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
        )
        # Anchor the 24h window — a recent inbound message lets us reply.
        self.thread, self.inbound = _make_thread_with_message(
            tenant=self.tenant,
            connection=self.conn,
            customer=self.customer,
            body='hi! can you book me in?',
        )

    def _meta_response(self, body):
        class _R:
            status_code = 200
            text = ''
            url = 'https://graph.instagram.com/17841/messages'
            def json(self):
                return body
        return _R()

    def test_happy_path_creates_outbound_message(self):
        with _patch_outbound(
            'apps.integrations.meta.requests.post',
            return_value=self._meta_response({
                'recipient_id': 'psid-1',
                'message_id': 'mid.outbound_42',
            }),
        ):
            response = self.client_.post(
                reverse('social-thread-reply', args=[self.thread.pk]),
                data=_json.dumps({'body': 'Of course! What time works?'}),
                content_type='application/json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['direction'], 'outbound')
        self.assertEqual(response.data['status'], 'sent')

        msg = SocialMessage.objects.get(pk=response.data['id'])
        self.assertEqual(msg.external_message_id, 'mid.outbound_42')
        self.assertEqual(msg.sent_by, self.owner)

        # Thread should be marked read + last_message_at bumped.
        self.thread.refresh_from_db()
        self.assertIsNotNone(self.thread.read_at)

    def test_empty_body_rejected(self):
        response = self.client_.post(
            reverse('social-thread-reply', args=[self.thread.pk]),
            data=_json.dumps({'body': '   '}),
            content_type='application/json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'body_empty')

    def test_oversized_body_rejected(self):
        response = self.client_.post(
            reverse('social-thread-reply', args=[self.thread.pk]),
            data=_json.dumps({'body': 'x' * 1001}),
            content_type='application/json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'body_too_long')

    def test_reply_window_expired(self):
        # Push last_inbound_at >24h into the past — Meta's window has closed.
        self.thread.last_inbound_at = timezone.now() - timezone.timedelta(hours=25)
        self.thread.save()
        response = self.client_.post(
            reverse('social-thread-reply', args=[self.thread.pk]),
            data=_json.dumps({'body': 'hi'}),
            content_type='application/json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'reply_window_expired')

    def test_no_inbound_anchor(self):
        self.thread.last_inbound_at = None
        self.thread.save()
        response = self.client_.post(
            reverse('social-thread-reply', args=[self.thread.pk]),
            data=_json.dumps({'body': 'hi'}),
            content_type='application/json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'no_inbound_anchor')

    def test_disconnected_connection_rejected(self):
        self.conn.status = Connection.Status.DISCONNECTED
        self.conn.save()
        response = self.client_.post(
            reverse('social-thread-reply', args=[self.thread.pk]),
            data=_json.dumps({'body': 'hi'}),
            content_type='application/json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'connection_disconnected')

    def test_meta_rejection_marks_message_failed(self):
        # Mock a 400 response from Meta.
        class _Err:
            status_code = 400
            text = ''
            url = 'https://graph.instagram.com/17841/messages'
            def json(self):
                return {'error': {'message': 'message too short', 'code': 100}}
        with _patch_outbound(
            'apps.integrations.meta.requests.post',
            return_value=_Err(),
        ):
            response = self.client_.post(
                reverse('social-thread-reply', args=[self.thread.pk]),
                data=_json.dumps({'body': 'hi'}),
                content_type='application/json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['code'], 'meta_rejected')

        # The QUEUED row should have been flipped to FAILED, not deleted.
        msg = SocialMessage.objects.filter(
            thread=self.thread,
            direction=SocialMessage.Direction.OUTBOUND,
        ).latest('created_at')
        self.assertEqual(msg.status, SocialMessage.Status.FAILED)

    def test_audit_log_omits_body_text(self):
        before = AuditLog.objects.filter(
            resource_type='social_message',
        ).count()
        with _patch_outbound(
            'apps.integrations.meta.requests.post',
            return_value=self._meta_response({'message_id': 'mid.test'}),
        ):
            self.client_.post(
                reverse('social-thread-reply', args=[self.thread.pk]),
                data=_json.dumps({'body': 'I have a hereditary condition — see you Thursday!'}),
                content_type='application/json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
        after = AuditLog.objects.filter(resource_type='social_message').count()
        self.assertEqual(after, before + 1)
        entry = AuditLog.objects.filter(
            resource_type='social_message',
        ).latest('timestamp')
        # CRITICAL: body text must NEVER appear in audit metadata. We
        # log length only per ADR 0027 §9.
        self.assertNotIn('hereditary', _json.dumps(entry.metadata))
        self.assertIn('body_length', entry.metadata)

    def test_front_desk_forbidden(self):
        fd = _make_user('reply-fd@test.local')
        _make_membership(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        response = _client_for(fd).post(
            reverse('social-thread-reply', args=[self.thread.pk]),
            data=_json.dumps({'body': 'hi'}),
            content_type='application/json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 403)


# ── Token refresh management command (Session 2C) ──────────────────


from io import StringIO  # noqa: E402

from django.core.management import call_command  # noqa: E402


class RefreshMetaTokensCommandTests(TestCase):
    def setUp(self):
        self.tenant, _ = _make_tenant_with_owner('refresh')

    def _make_conn(self, *, expires_at, access_token='IGAA-old'):
        conn = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='ig-user-x',
        )
        conn.set_auth_data({
            'ig_user_id': 'ig-user-x',
            'access_token': access_token,
            'expires_at': expires_at,
        })
        conn.save()
        return conn

    def test_in_window_refreshes(self):
        # Token expires in 5 days (well inside 14-day window) +
        # is at least 24h old (issued 30 days ago).
        now = int(timezone.now().timestamp())
        conn = self._make_conn(expires_at=now + 5 * 24 * 3600)

        class _R:
            status_code = 200
            text = ''
            url = 'https://graph.instagram.com/refresh_access_token'
            def json(self):
                return {'access_token': 'IGAA-new', 'expires_in': 5184000}

        out = StringIO()
        with _patch_outbound(
            'apps.integrations.meta.requests.get',
            return_value=_R(),
        ):
            call_command('refresh_meta_tokens', stdout=out)

        conn.refresh_from_db()
        payload = conn.auth_data_dict
        self.assertEqual(payload['access_token'], 'IGAA-new')
        # New expiry should be ~60 days out from now.
        self.assertGreater(payload['expires_at'], now + 30 * 24 * 3600)
        self.assertIn('Refreshed=1', out.getvalue())

    def test_outside_window_skipped(self):
        # Expires in 60 days — way outside the default 14-day window.
        now = int(timezone.now().timestamp())
        conn = self._make_conn(expires_at=now + 60 * 24 * 3600)
        original_token = conn.auth_data_dict['access_token']

        with _patch_outbound(
            'apps.integrations.meta.requests.get',
        ) as mock_get:
            call_command('refresh_meta_tokens', stdout=StringIO())
            mock_get.assert_not_called()

        conn.refresh_from_db()
        self.assertEqual(conn.auth_data_dict['access_token'], original_token)

    def test_permanent_error_flags_connection(self):
        now = int(timezone.now().timestamp())
        conn = self._make_conn(expires_at=now + 5 * 24 * 3600)

        class _Err:
            status_code = 400
            text = ''
            url = 'https://graph.instagram.com/refresh_access_token'
            def json(self):
                return {
                    'error': {
                        'message': 'Session has expired on Wednesday',
                        'code': 190,
                    },
                }

        with _patch_outbound(
            'apps.integrations.meta.requests.get',
            return_value=_Err(),
        ):
            call_command('refresh_meta_tokens', stdout=StringIO())

        conn.refresh_from_db()
        self.assertEqual(conn.status, Connection.Status.ERROR)
        self.assertIn('reconnect', conn.last_error_message.lower())

    def test_dry_run_makes_no_meta_calls(self):
        now = int(timezone.now().timestamp())
        self._make_conn(expires_at=now + 5 * 24 * 3600)
        with _patch_outbound(
            'apps.integrations.meta.requests.get',
        ) as mock_get:
            call_command('refresh_meta_tokens', '--dry-run', stdout=StringIO())
            mock_get.assert_not_called()


# ── Media archive (Session 2D — copy Meta-hosted media to S3) ──────


class MediaArchiveTests(TestCase):
    """Inbound media gets copied off Meta's CDN before it expires."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('media')
        self.conn = Connection.objects.create(
            tenant=self.tenant,
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id='page-m',
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            first_name='Photo', last_name='Sender',
            acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
        )
        self.thread, _ = _make_thread_with_message(
            tenant=self.tenant,
            connection=self.conn,
            customer=self.customer,
        )

    def _make_msg_with_media(self, urls: list[str]) -> SocialMessage:
        return SocialMessage.objects.create(
            tenant=self.tenant,
            thread=self.thread,
            direction=SocialMessage.Direction.INBOUND,
            body='see attached',
            media_urls='\n'.join(urls),
            external_message_id='mid-media-' + str(self.thread.pk) + str(timezone.now().timestamp()),
            status=SocialMessage.Status.RECEIVED,
            received_at=timezone.now(),
        )

    def test_archive_one_writes_to_default_storage(self):
        from apps.integrations import media_archive

        msg = self._make_msg_with_media(['https://meta.test/photo.jpg'])

        class _R:
            status_code = 200
            content = b'fake-jpeg-bytes'
            headers = {'Content-Type': 'image/jpeg', 'Content-Length': '15'}
        with _patch_outbound(
            'apps.integrations.media_archive.requests.get',
            return_value=_R(),
        ):
            count = media_archive.archive_message_media(msg)
        self.assertEqual(count, 1)

        msg.refresh_from_db()
        keys = msg.archived_media_keys.splitlines()
        self.assertEqual(len(keys), 1)
        # Storage key includes tenant + thread + message scope so
        # ops can grep ahead of a takedown / deletion request.
        self.assertIn(f'social-media/{self.tenant.id}/', keys[0])
        self.assertIn(f'{msg.pk}', keys[0])
        self.assertTrue(keys[0].endswith('.jpg') or keys[0].endswith('.jpeg'))

    def test_archive_skips_oversized_file(self):
        from apps.integrations import media_archive

        msg = self._make_msg_with_media(['https://meta.test/huge.bin'])

        class _R:
            status_code = 200
            content = b'x' * (media_archive.MAX_BYTES_PER_FILE + 1)
            headers = {'Content-Length': str(media_archive.MAX_BYTES_PER_FILE + 1)}
        with _patch_outbound(
            'apps.integrations.media_archive.requests.get',
            return_value=_R(),
        ):
            count = media_archive.archive_message_media(msg)
        self.assertEqual(count, 0)

        msg.refresh_from_db()
        self.assertEqual(msg.archived_media_keys, '')

    def test_archive_continues_on_partial_failure(self):
        from apps.integrations import media_archive

        msg = self._make_msg_with_media([
            'https://meta.test/good.jpg',
            'https://meta.test/bad.jpg',
        ])

        class _Good:
            status_code = 200
            content = b'ok'
            headers = {'Content-Type': 'image/jpeg', 'Content-Length': '2'}

        class _Bad:
            status_code = 404
            content = b''
            headers = {}

        responses = [_Good(), _Bad()]

        def _side_effect(url, **kwargs):
            return responses.pop(0)

        with _patch_outbound(
            'apps.integrations.media_archive.requests.get',
            side_effect=_side_effect,
        ):
            count = media_archive.archive_message_media(msg)
        # One succeeded, one failed → 1 archived key written.
        self.assertEqual(count, 1)
        msg.refresh_from_db()
        self.assertEqual(len(msg.archived_media_keys.splitlines()), 1)

    def test_serialise_prefers_archived_keys(self):
        """When archived_media_keys is set, the serialised payload
        returns signed URLs from default_storage rather than the
        expired Meta URLs."""
        from apps.integrations.views import _resolve_media_urls

        msg = self._make_msg_with_media(['https://meta.test/expired.jpg'])
        msg.archived_media_keys = 'social-media/1/1/1-0.jpg'
        msg.save()

        urls = _resolve_media_urls(msg)
        self.assertEqual(len(urls), 1)
        # In dev the storage backend is the local filesystem; in
        # prod default_storage.url() returns an S3 signed URL. Both
        # should NOT match the expired Meta URL.
        self.assertNotIn('meta.test', urls[0])
