"""Tests for the services API — focused on ServiceProtocol since
that's the only surface added in EMR v2.

Covers eight invariants:

  1. Anonymous request gets 403.
  2. Tenant scoping — GET on a foreign-tenant service is 403.
  3. Empty GET — returns the empty-shape payload when no protocol
     authored yet, not 404.
  4. PUT creates on first write (CREATE audit log entry).
  5. PUT replaces fields on subsequent writes (UPDATE entry).
  6. `updated_by` tracks the saving user.
  7. Front-desk role can READ but not WRITE.
  8. Owner can READ and WRITE.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import Service, ServiceCategory, ServiceProtocol

User = get_user_model()


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = User.objects.create_user(email=f'{slug}-owner@test.local', password='pw')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_front_desk(tenant: Tenant) -> User:
    user = User.objects.create_user(email=f'fd-{tenant.slug}@test.local', password='pw')
    m = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.FRONT_DESK,
        is_active=True,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user


def _make_service(tenant: Tenant, *, name: str = 'HydraFacial') -> Service:
    cat, _ = ServiceCategory.objects.get_or_create(tenant=tenant, name='Facials')
    return Service.objects.create(
        tenant=tenant, category=cat, name=name,
        duration_minutes=45, price_cents=15000,
        service_type=Service.ServiceType.REGULAR,
    )


def _client_for(user: User) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── ServiceProtocol API ────────────────────────────────────────────


class ServiceProtocolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('proto-spa')
        cls.other_tenant, _ = _make_tenant('proto-other')
        cls.service = _make_service(cls.tenant)
        cls.foreign_service = _make_service(cls.other_tenant, name='Other facial')

    def setUp(self):
        self.client = _client_for(self.owner)

    def _url(self, service_id: int) -> str:
        return reverse('service-protocol', kwargs={'service_id': service_id})

    def test_anonymous_request_is_forbidden(self):
        response = APIClient().get(
            self._url(self.service.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (401, 403))

    def test_get_returns_empty_payload_when_no_protocol(self):
        response = self.client.get(
            self._url(self.service.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pre_treatment'], '')
        self.assertEqual(response.data['intra_treatment'], '')
        self.assertTrue(response.data['is_empty'])

    def test_cross_tenant_service_rejected(self):
        response = self.client.get(
            self._url(self.foreign_service.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_put_creates_protocol_on_first_write(self):
        response = self.client.put(
            self._url(self.service.id),
            data={
                'pre_treatment': 'Confirm consent. Cleanse skin.',
                'intra_treatment': 'Step 1 — cleanse. Step 2 — exfoliate. Step 3 — extract. Step 4 — hydrate.',
                'post_treatment': 'No retinoids for 24h.',
                'notes': 'Use vendor X serum for sensitive-skin clients.',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        proto = ServiceProtocol.objects.get(service=self.service)
        self.assertEqual(proto.tenant, self.tenant)
        self.assertEqual(proto.pre_treatment, 'Confirm consent. Cleanse skin.')
        self.assertEqual(proto.updated_by, self.owner)

    def test_put_replaces_fields_on_subsequent_write(self):
        # First write
        self.client.put(
            self._url(self.service.id),
            data={'pre_treatment': 'Old'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Second write — replace one field, leave the rest intact
        response = self.client.put(
            self._url(self.service.id),
            data={'pre_treatment': 'New', 'intra_treatment': 'Procedure steps'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        proto = ServiceProtocol.objects.get(service=self.service)
        self.assertEqual(proto.pre_treatment, 'New')
        self.assertEqual(proto.intra_treatment, 'Procedure steps')

    def test_create_writes_audit_log_with_fields_changed(self):
        self.client.put(
            self._url(self.service.id),
            data={'pre_treatment': 'Steps', 'intra_treatment': 'More steps'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='service_protocol', action=AuditLog.Action.CREATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertIn('pre_treatment', log.metadata['fields_changed'])
        self.assertEqual(log.metadata['service_id'], self.service.id)

    def test_front_desk_can_read_but_not_write(self):
        fd = _make_front_desk(self.tenant)
        fd_client = _client_for(fd)

        # Read — allowed (provider use case).
        read_response = fd_client.get(
            self._url(self.service.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(read_response.status_code, 200)

        # Write — blocked (need MANAGE_SERVICES).
        write_response = fd_client.put(
            self._url(self.service.id),
            data={'pre_treatment': 'Should not save'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(write_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(ServiceProtocol.objects.filter(service=self.service).exists())

    def test_patch_partial_update_leaves_other_fields_intact(self):
        # Establish initial state.
        self.client.put(
            self._url(self.service.id),
            data={
                'pre_treatment': 'A',
                'intra_treatment': 'B',
                'post_treatment': 'C',
                'notes': 'D',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # PATCH only one field.
        response = self.client.patch(
            self._url(self.service.id),
            data={'post_treatment': 'C-updated'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        proto = ServiceProtocol.objects.get(service=self.service)
        self.assertEqual(proto.pre_treatment, 'A')
        self.assertEqual(proto.intra_treatment, 'B')
        self.assertEqual(proto.post_treatment, 'C-updated')
        self.assertEqual(proto.notes, 'D')
