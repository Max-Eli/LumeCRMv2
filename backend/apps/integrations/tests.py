"""Tests for the integrations API.

Covers permission gating, list shape (one entry per provider with
or without connection state), connect-begin placeholder behavior,
disconnect lifecycle + audit shape, and tenant isolation.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
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
            auth_data={'access_token': 'fake-token'},
        )
        self.client_ = _client_for(self.owner)

    def test_disconnect_clears_auth_and_externals(self):
        response = self.client_.post(
            reverse('integrations-disconnect', args=[self.connection.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, Connection.Status.DISCONNECTED)
        self.assertEqual(self.connection.auth_data, {})
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
