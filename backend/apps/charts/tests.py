"""Tests for the chart-notes API.

Covers the four invariants that define correctness:

  1. Tenant scoping — list + retrieve + create are tenant-bound.
  2. Permission gating — front-desk roles get 403; provider /
     owner / manager get through. Clinical-status snapshot
     captured correctly.
  3. Edit window — within 60 min, the original author can edit;
     after, the API rejects. Non-author editors are rejected
     even within the window.
  4. Audit logging — read + write writes entries; PHI body is
     never in metadata (only body length).
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as djtz
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.tenants.models import (
    JobTitle,
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import EDIT_WINDOW_MINUTES, ChartNote

User = get_user_model()


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_user(email: str, **kwargs):
    return User.objects.create_user(email=email, password='test-pw', **kwargs)


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_provider(
    tenant: Tenant, *,
    is_clinical: bool = True,
    location=None,
    first_name: str = 'Sarah',
    last_name: str = 'Provider',
) -> TenantMembership:
    user = _make_user(
        f'p-{tenant.slug}-{TenantMembership.objects.filter(tenant=tenant).count()}@test.local',
        first_name=first_name, last_name=last_name,
    )
    job_title, _ = JobTitle.objects.get_or_create(
        tenant=tenant,
        name='Nurse Practitioner' if is_clinical else 'Aesthetician',
        defaults={'is_clinical': is_clinical},
    )
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.PROVIDER,
        job_title=job_title,
        is_bookable=True, is_active=True,
    )
    if location is None:
        location = tenant.locations.get(is_default=True)
    MembershipLocation.objects.create(
        membership=membership, location=location, is_active=True,
    )
    return membership


def _make_front_desk(tenant: Tenant) -> tuple[User, TenantMembership]:
    user = _make_user(f'fd-{tenant.slug}@test.local', first_name='Front', last_name='Desk')
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.FRONT_DESK,
        is_active=True,
    )
    MembershipLocation.objects.create(
        membership=membership,
        location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user, membership


def _make_customer(tenant: Tenant, **kwargs) -> Customer:
    defaults = {
        'first_name': 'Pat', 'last_name': 'Patient',
        'email': f'pat-{tenant.slug}@test.local',
    }
    defaults.update(kwargs)
    return Customer.objects.create(tenant=tenant, **defaults)


def _client_for(user) -> APIClient:
    client = APIClient()
    client.force_login(user)
    return client


# ── Permission gating ──────────────────────────────────────────────


class ChartNotePermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('chart-perm')
        cls.provider = _make_provider(cls.tenant, is_clinical=True)
        cls.fd_user, cls.fd_membership = _make_front_desk(cls.tenant)
        cls.customer = _make_customer(cls.tenant)

        cls.note = ChartNote.objects.create(
            tenant=cls.tenant, customer=cls.customer,
            body='Initial observation.', author=cls.provider,
            author_was_clinical=True,
        )

    def test_anonymous_blocked(self):
        client = APIClient()
        response = client.get(
            reverse('chart-note-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_front_desk_blocked_from_list(self):
        response = _client_for(self.fd_user).get(
            reverse('chart-note-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_front_desk_blocked_from_retrieve(self):
        response = _client_for(self.fd_user).get(
            reverse('chart-note-detail', kwargs={'pk': self.note.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_front_desk_blocked_from_create(self):
        response = _client_for(self.fd_user).post(
            reverse('chart-note-list'),
            data={'customer_id': self.customer.pk, 'body': 'Front desk attempt.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_provider_can_list(self):
        response = _client_for(self.provider.user).get(
            reverse('chart-note-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_list(self):
        response = _client_for(self.owner).get(
            reverse('chart-note-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ── Create + tenant scoping ─────────────────────────────────────────


class ChartNoteCreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('chart-create')
        cls.provider = _make_provider(cls.tenant, is_clinical=True)
        cls.aesth_provider = _make_provider(
            cls.tenant, is_clinical=False, first_name='Alex', last_name='Aesth',
        )
        cls.customer = _make_customer(cls.tenant)

    def setUp(self):
        self.client = _client_for(self.provider.user)

    def test_clinical_provider_can_sign(self):
        response = self.client.post(
            reverse('chart-note-list'),
            data={'customer_id': self.customer.pk, 'body': 'Treated.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        note = ChartNote.objects.get(pk=response.data['id'])
        self.assertTrue(note.author_was_clinical)
        self.assertEqual(note.author, self.provider)

    def test_non_clinical_provider_signs_with_clinical_flag_false(self):
        # Non-clinical provider can still hold SIGN_CHART (it's a
        # role default on `provider`). The clinical-status snapshot
        # captures the *job-title* clinical flag, not whether they
        # can sign at all. ADR 0015's legal-status anchor.
        client = _client_for(self.aesth_provider.user)
        response = client.post(
            reverse('chart-note-list'),
            data={'customer_id': self.customer.pk, 'body': 'Aesthetician note.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        note = ChartNote.objects.get(pk=response.data['id'])
        self.assertFalse(note.author_was_clinical)

    def test_cross_tenant_customer_rejected(self):
        other_tenant, _ = _make_tenant('chart-other-tenant')
        other_customer = _make_customer(other_tenant)
        response = self.client.post(
            reverse('chart-note-list'),
            data={'customer_id': other_customer.pk, 'body': 'cross-tenant'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ChartNote.objects.count(), 0)

    def test_empty_body_rejected(self):
        response = self.client.post(
            reverse('chart-note-list'),
            data={'customer_id': self.customer.pk, 'body': ''},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Edit window ─────────────────────────────────────────────────────


class ChartNoteEditWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('chart-edit')
        cls.author = _make_provider(cls.tenant, is_clinical=True)
        cls.other_provider = _make_provider(
            cls.tenant, is_clinical=True, first_name='Other', last_name='NP',
        )
        cls.customer = _make_customer(cls.tenant)

    def _make_note(self, *, signed_at=None):
        note = ChartNote.objects.create(
            tenant=self.tenant, customer=self.customer,
            body='Initial.', author=self.author, author_was_clinical=True,
        )
        if signed_at is not None:
            # auto_now_add ignores explicit values on create; backfill
            # via update so we can simulate a note from the past.
            ChartNote.objects.filter(pk=note.pk).update(signed_at=signed_at)
            note.refresh_from_db()
        return note

    def test_author_can_edit_within_window(self):
        note = self._make_note()
        client = _client_for(self.author.user)
        response = client.patch(
            reverse('chart-note-detail', kwargs={'pk': note.pk}),
            data={'body': 'Corrected typo: 0.5mL not 5mL.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        note.refresh_from_db()
        self.assertIn('0.5mL', note.body)

    def test_author_cannot_edit_after_window(self):
        # Signed 2 hours ago — past the 60-min window.
        old_time = djtz.now() - dt.timedelta(minutes=EDIT_WINDOW_MINUTES + 60)
        note = self._make_note(signed_at=old_time)
        client = _client_for(self.author.user)
        response = client.patch(
            reverse('chart-note-detail', kwargs={'pk': note.pk}),
            data={'body': 'Tried to edit a locked note.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('locked', str(response.data).lower())

    def test_other_provider_cannot_edit_authors_note(self):
        note = self._make_note()
        client = _client_for(self.other_provider.user)
        response = client.patch(
            reverse('chart-note-detail', kwargs={'pk': note.pk}),
            data={'body': 'Hijack attempt.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_rejects_non_body_fields(self):
        note = self._make_note()
        client = _client_for(self.author.user)
        response = client.patch(
            reverse('chart-note-detail', kwargs={'pk': note.pk}),
            data={'body': 'OK', 'author': 999, 'signed_at': '2026-01-01T00:00:00Z'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Audit logging ──────────────────────────────────────────────────


class ChartNoteAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('chart-audit')
        cls.provider = _make_provider(cls.tenant, is_clinical=True)
        cls.customer = _make_customer(cls.tenant)

    def setUp(self):
        self.client = _client_for(self.provider.user)
        self.note = ChartNote.objects.create(
            tenant=self.tenant, customer=self.customer,
            body='Treatment notes with sensitive PHI content.',
            author=self.provider, author_was_clinical=True,
        )

    def test_read_writes_audit_entry(self):
        self.client.get(
            reverse('chart-note-detail', kwargs={'pk': self.note.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='chart_note',
            action=AuditLog.Action.READ,
            resource_id=str(self.note.pk),
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.provider.user)
        # PHI body must NOT appear in audit metadata.
        meta_str = str(log.metadata)
        self.assertNotIn('sensitive PHI', meta_str)
        self.assertNotIn('Treatment notes', meta_str)

    def test_create_audit_captures_body_length_only(self):
        body = 'X' * 250
        response = self.client.post(
            reverse('chart-note-list'),
            data={'customer_id': self.customer.pk, 'body': body},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='chart_note',
            action=AuditLog.Action.CREATE,
            resource_id=str(response.data['id']),
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('body_length_chars'), 250)
        # Body content itself must NOT be in metadata.
        self.assertNotIn(body, str(log.metadata))

    def test_list_audit_entry(self):
        self.client.get(
            reverse('chart-note-list') + f'?customer={self.customer.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='chart_note_list',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('customer_id'), str(self.customer.pk))


# ── Addenda (Session 2) ─────────────────────────────────────────────


class ChartNoteAddendumTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('chart-add')
        cls.author = _make_provider(cls.tenant, is_clinical=True)
        cls.other_provider = _make_provider(
            cls.tenant, is_clinical=True,
            first_name='Other', last_name='NP',
        )
        cls.fd_user, cls.fd_membership = _make_front_desk(cls.tenant)
        cls.customer = _make_customer(cls.tenant)

    def _make_locked_note(self):
        # Sign a note dated 2 hours ago so it's past the edit window.
        old = djtz.now() - dt.timedelta(minutes=EDIT_WINDOW_MINUTES + 60)
        note = ChartNote.objects.create(
            tenant=self.tenant, customer=self.customer,
            body='Initial.', author=self.author, author_was_clinical=True,
        )
        ChartNote.objects.filter(pk=note.pk).update(signed_at=old)
        note.refresh_from_db()
        return note

    def _addendum_url(self, parent_id: int) -> str:
        return reverse('chart-note-addendum', kwargs={'pk': parent_id})

    def test_clinical_signer_can_add_addendum_to_locked_parent(self):
        parent = self._make_locked_note()
        client = _client_for(self.author.user)
        response = client.post(
            self._addendum_url(parent.pk),
            data={'body': 'Correction: dose was 0.5mL not 5mL.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        addendum = ChartNote.objects.get(pk=response.data['id'])
        self.assertEqual(addendum.parent_note_id, parent.pk)
        self.assertEqual(addendum.customer_id, self.customer.pk)
        self.assertEqual(addendum.author, self.author)

    def test_other_clinical_signer_can_add_addendum(self):
        # Addenda are not author-locked — any clinical signer can
        # contribute corrective context.
        parent = self._make_locked_note()
        client = _client_for(self.other_provider.user)
        response = client.post(
            self._addendum_url(parent.pk),
            data={'body': 'Spoke with patient on follow-up.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_front_desk_blocked_from_addendum(self):
        parent = self._make_locked_note()
        response = _client_for(self.fd_user).post(
            self._addendum_url(parent.pk),
            data={'body': 'Front desk attempt.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_addendum_rejected_on_unlocked_parent(self):
        # Parent within edit window — the right path is to edit, not
        # add an addendum.
        parent = ChartNote.objects.create(
            tenant=self.tenant, customer=self.customer,
            body='Fresh.', author=self.author, author_was_clinical=True,
        )
        client = _client_for(self.author.user)
        response = client.post(
            self._addendum_url(parent.pk),
            data={'body': 'Trying to addendum a fresh note.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('typo-correction window', str(response.data).lower())

    def test_addendum_rejected_on_voided_parent(self):
        parent = self._make_locked_note()
        parent.is_voided = True
        parent.voided_at = djtz.now()
        parent.voided_by = self.owner.memberships.first()  # type: ignore[attr-defined]
        parent.voided_reason = 'wrong patient'
        parent.save()

        client = _client_for(self.author.user)
        response = client.post(
            self._addendum_url(parent.pk),
            data={'body': 'Trying to attach to a voided note.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('voided', str(response.data).lower())

    def test_no_nested_addenda(self):
        # Addendum on top of an addendum is rejected.
        parent = self._make_locked_note()
        client = _client_for(self.author.user)
        first = client.post(
            self._addendum_url(parent.pk),
            data={'body': 'First addendum.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        # Lock the addendum by backdating its signed_at.
        addendum_id = first.data['id']
        old = djtz.now() - dt.timedelta(minutes=EDIT_WINDOW_MINUTES + 60)
        ChartNote.objects.filter(pk=addendum_id).update(signed_at=old)

        nested = client.post(
            self._addendum_url(addendum_id),
            data={'body': 'Trying nested.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(nested.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('addenda cannot have addenda', str(nested.data).lower())

    def test_list_returns_addenda_flat_with_parent_note_id(self):
        parent = self._make_locked_note()
        client = _client_for(self.author.user)
        client.post(
            self._addendum_url(parent.pk),
            data={'body': 'Addendum content.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = client.get(
            reverse('chart-note-list') + f'?customer={self.customer.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [n['id'] for n in response.data]
        self.assertEqual(len(ids), 2)
        # Both flat in the list; one carries parent_note_id.
        parent_ids = {n.get('parent_note_id') for n in response.data}
        self.assertEqual(parent_ids, {None, parent.pk})

    def test_addendum_audit_log_carries_parent_id(self):
        parent = self._make_locked_note()
        client = _client_for(self.author.user)
        response = client.post(
            self._addendum_url(parent.pk),
            data={'body': 'Audit me.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='chart_note',
            action=AuditLog.Action.CREATE,
            resource_id=str(response.data['id']),
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'addendum_created')
        self.assertEqual(log.metadata.get('parent_note_id'), parent.pk)


# ── Voiding (Session 2) ─────────────────────────────────────────────


class ChartNoteVoidTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('chart-void')
        cls.author = _make_provider(cls.tenant, is_clinical=True)
        cls.fd_user, _ = _make_front_desk(cls.tenant)
        cls.customer = _make_customer(cls.tenant)

    def _make_locked_note(self):
        old = djtz.now() - dt.timedelta(minutes=EDIT_WINDOW_MINUTES + 60)
        note = ChartNote.objects.create(
            tenant=self.tenant, customer=self.customer,
            body='Wrong-patient note.', author=self.author,
            author_was_clinical=True,
        )
        ChartNote.objects.filter(pk=note.pk).update(signed_at=old)
        note.refresh_from_db()
        return note

    def _void_url(self, note_id: int) -> str:
        return reverse('chart-note-void', kwargs={'pk': note_id})

    def test_owner_can_void_locked_note(self):
        note = self._make_locked_note()
        response = _client_for(self.owner).post(
            self._void_url(note.pk),
            data={'reason': 'Wrong patient.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        note.refresh_from_db()
        self.assertTrue(note.is_voided)
        self.assertIsNotNone(note.voided_at)
        self.assertEqual(note.voided_reason, 'Wrong patient.')

    def test_provider_cannot_void(self):
        # Provider has SIGN_CHART but NOT EDIT_SIGNED_CHART.
        note = self._make_locked_note()
        response = _client_for(self.author.user).post(
            self._void_url(note.pk),
            data={'reason': 'I want to remove this.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('edit_signed_chart', str(response.data).lower())

    def test_front_desk_cannot_void(self):
        note = self._make_locked_note()
        response = _client_for(self.fd_user).post(
            self._void_url(note.pk),
            data={'reason': 'Just trying.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_void_rejects_unlocked_note(self):
        # Within the edit window, the right answer is to edit, not void.
        fresh = ChartNote.objects.create(
            tenant=self.tenant, customer=self.customer,
            body='Fresh note.', author=self.author, author_was_clinical=True,
        )
        response = _client_for(self.owner).post(
            self._void_url(fresh.pk),
            data={'reason': 'Tried to void a fresh note.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('typo-correction window', str(response.data).lower())

    def test_void_requires_reason(self):
        note = self._make_locked_note()
        response = _client_for(self.owner).post(
            self._void_url(note.pk),
            data={'reason': ''},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_double_void_rejected(self):
        note = self._make_locked_note()
        client = _client_for(self.owner)
        first = client.post(
            self._void_url(note.pk),
            data={'reason': 'First void.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        second = client.post(
            self._void_url(note.pk),
            data={'reason': 'Trying again.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already voided', str(second.data).lower())

    def test_voided_note_excluded_with_include_voided_false(self):
        note = self._make_locked_note()
        client = _client_for(self.owner)
        client.post(
            self._void_url(note.pk),
            data={'reason': 'Wrong patient.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = client.get(
            reverse('chart-note-list')
            + f'?customer={self.customer.pk}&include_voided=false',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [n['id'] for n in response.data]
        self.assertNotIn(note.pk, ids)

    def test_voided_note_included_by_default(self):
        # Default (no include_voided param) returns voided notes so
        # the UI can render them struck-through.
        note = self._make_locked_note()
        client = _client_for(self.owner)
        client.post(
            self._void_url(note.pk),
            data={'reason': 'Test.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = client.get(
            reverse('chart-note-list') + f'?customer={self.customer.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [n['id'] for n in response.data]
        self.assertIn(note.pk, ids)
        # And carries is_voided=True.
        voided = next(n for n in response.data if n['id'] == note.pk)
        self.assertTrue(voided['is_voided'])
        self.assertEqual(voided['voided_reason'], 'Test.')

    def test_voided_note_cannot_be_edited(self):
        # Voided notes are by definition locked (we reject voiding
        # unlocked notes), so the lock check always fires too. The
        # specific guarantee we want is that the rejection mentions
        # the void — clearer for the author than the generic "this
        # is locked, write a new note" message.
        note = self._make_locked_note()
        _client_for(self.owner).post(
            self._void_url(note.pk),
            data={'reason': 'Wrong patient.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = _client_for(self.author.user).patch(
            reverse('chart-note-detail', kwargs={'pk': note.pk}),
            data={'body': 'Trying to edit a voided note.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('voided', str(response.data).lower())

    def test_void_audit_log_records_reason(self):
        note = self._make_locked_note()
        _client_for(self.owner).post(
            self._void_url(note.pk),
            data={'reason': 'Wrong patient — duplicate from yesterday.'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='chart_note',
            action=AuditLog.Action.UPDATE,
            resource_id=str(note.pk),
        ).order_by('-timestamp').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'voided')
        self.assertEqual(
            log.metadata.get('reason'),
            'Wrong patient — duplicate from yesterday.',
        )
        # Body itself MUST NOT appear (PHI hygiene).
        self.assertNotIn('Wrong-patient note', str(log.metadata))
