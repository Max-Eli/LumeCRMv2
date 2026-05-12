"""Tests for the invoicing app.

These tests are SOC 2 evidence as much as they are regression guards:
they demonstrate that the appointment-completion gate, the
permission-gated reopen, the 60-day window, the tenant-isolation, and
the audit-trail entries actually do what ADR 0007 promises.

Test layout:

    InvoiceSignalTests       — appointment created → invoice + line item
    InvoiceCloseTests        — close transitions appointment to COMPLETED
    AppointmentCompleteGate  — direct PATCH status=completed is rejected
    InvoiceReopenTests       — perm gating, 60-day window, closed_at preserved
    InvoiceVoidTests         — void rules, paid-cannot-void
    TenantIsolationTests     — invoices scoped to current tenant
    AuditTrailTests          — every state change writes an AuditLog entry
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.invoices.models import (
    Invoice,
    InvoiceLineItem,
    InvoiceReopenWindowError,
    InvoiceStateError,
)
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import JobTitle, Tenant, TenantMembership
from apps.tenants.permissions import P
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_user(email: str, **kwargs) -> User:
    return User.objects.create_user(email=email, password='test-password', **kwargs)


def _make_tenant_with_owner(slug: str, *, name: str | None = None) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local', first_name='Owner')
    tenant = create_tenant_with_defaults(
        name=name or slug.title(),
        slug=slug,
        owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_membership(*, user: User, tenant: Tenant, role: str, location=None, **kwargs) -> TenantMembership:
    """Create a tenant membership AND assign it to a location.

    Mirrors the real Add-Employee flow where every membership has at
    least one MembershipLocation entry. Without this, the new
    "provider must be assigned to the appointment's location" check in
    `AppointmentSerializer.validate()` rejects every test that PATCHes
    an existing appointment, since the test provider has no
    location_assignments.

    Defaults to the tenant's default location to match the runtime
    Session 5 behavior. Tests that need a provider absent from a site
    pass `location=None` explicitly... actually that's an
    impossibility — every membership needs at least one site. Pass a
    specific Location instance to override the default.
    """
    from apps.tenants.models import MembershipLocation

    membership = TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True, **kwargs,
    )
    if location is None:
        location = tenant.locations.get(is_default=True)
    MembershipLocation.objects.create(
        membership=membership, location=location, is_active=True,
    )
    return membership


def _make_service(tenant: Tenant, *, name='Botox 20u', price_cents=20000, tax='0') -> Service:
    cat = ServiceCategory.objects.create(tenant=tenant, name=f'{name}-cat')
    return Service.objects.create(
        tenant=tenant,
        category=cat,
        name=name,
        code=name.replace(' ', '')[:8].upper(),
        duration_minutes=30,
        buffer_minutes=0,
        price_cents=price_cents,
        tax_rate_percent=Decimal(tax),
        service_type=Service.ServiceType.REGULAR,
    )


def _make_customer(tenant: Tenant, *, first='Pat', last='Patient') -> Customer:
    return Customer.objects.create(
        tenant=tenant,
        first_name=first,
        last_name=last,
        email=f'{first}.{last}@example.com'.lower(),
    )


def _make_appointment(
    tenant: Tenant, *,
    customer: Customer,
    service: Service,
    provider: TenantMembership,
    status: str = Appointment.Status.BOOKED,
    start: dt.datetime | None = None,
    created_by: User | None = None,
    location=None,
) -> Appointment:
    start = start or (timezone.now() + dt.timedelta(hours=1))
    end = start + dt.timedelta(minutes=service.duration_minutes)
    # Multi-location: every appointment belongs to one site. Tests that
    # don't care about location get the tenant's default — Session 1's
    # data migration guarantees one default per tenant.
    if location is None:
        location = tenant.locations.get(is_default=True)
    return Appointment.objects.create(
        tenant=tenant,
        customer=customer,
        provider=provider,
        service=service,
        location=location,
        start_time=start,
        end_time=end,
        status=status,
        quoted_price_cents=service.price_cents,
        created_by=created_by,
    )


# ── Signal: appointment created → invoice created ───────────────────────


class InvoiceSignalTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('signal-tenant')
        self.provider_user = _make_user('signal-provider@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=15000, tax='8.875')

    def test_creating_appointment_creates_one_open_invoice(self):
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, created_by=self.owner,
        )
        invoice = Invoice.objects.get(appointment=appt)
        self.assertEqual(invoice.status, Invoice.Status.OPEN)
        self.assertEqual(invoice.tenant, self.tenant)
        self.assertEqual(invoice.customer, self.customer)
        self.assertEqual(invoice.created_by, self.owner)

    def test_invoice_has_one_line_item_with_snapshot(self):
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider,
        )
        invoice = Invoice.objects.get(appointment=appt)
        lines = list(invoice.line_items.all())
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line.description, self.service.name)
        self.assertEqual(line.unit_price_cents, self.service.price_cents)
        self.assertEqual(line.tax_rate_percent, Decimal('8.875'))
        # Tax computation: 15000 * 8.875 / 100 = 1331.25 → ROUND_HALF_UP → 1331
        self.assertEqual(line.line_subtotal_cents, 15000)
        self.assertEqual(line.line_tax_cents, 1331)

    def test_invoice_totals_match_line_aggregate(self):
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider,
        )
        invoice = Invoice.objects.get(appointment=appt)
        invoice.refresh_from_db()
        self.assertEqual(invoice.subtotal_cents, 15000)
        self.assertEqual(invoice.tax_cents, 1331)
        self.assertEqual(invoice.total_cents, 16331)

    def test_signal_does_not_run_on_subsequent_appointment_save(self):
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider,
        )
        self.assertEqual(Invoice.objects.filter(appointment=appt).count(), 1)
        # Mutating the appointment must not create a second invoice.
        appt.status = Appointment.Status.CONFIRMED
        appt.save()
        self.assertEqual(Invoice.objects.filter(appointment=appt).count(), 1)

    def test_signal_writes_audit_log_entry(self):
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, created_by=self.owner,
        )
        invoice = Invoice.objects.get(appointment=appt)
        log = AuditLog.objects.get(
            resource_type='invoice',
            resource_id=str(invoice.pk),
            action=AuditLog.Action.CREATE,
        )
        self.assertEqual(log.metadata.get('source'), 'appointment_signal')
        self.assertEqual(log.metadata.get('appointment_id'), appt.pk)


# ── Close: invoice → paid + appointment → completed ─────────────────────


class InvoiceCloseTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('close-tenant')
        self.provider_user = _make_user('close-provider@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=10000, tax='0')
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

    def test_close_transitions_appointment_to_completed(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.refresh_from_db()
        self.appt.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertIsNotNone(self.invoice.closed_at)
        self.assertEqual(self.invoice.closed_by, self.owner)
        self.assertEqual(self.appt.status, Appointment.Status.COMPLETED)
        self.assertIsNotNone(self.appt.completed_at)

    def test_close_with_missing_payment_method_raises(self):
        with self.assertRaises(InvoiceStateError):
            self.invoice.close(by_user=self.owner, payment_method='')

    def test_close_with_unknown_payment_method_raises(self):
        with self.assertRaises(InvoiceStateError):
            self.invoice.close(by_user=self.owner, payment_method='bitcoin')

    def test_double_close_raises(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        with self.assertRaises(InvoiceStateError):
            self.invoice.close(by_user=self.owner, payment_method='cash')

    def test_cannot_close_invoice_for_cancelled_appointment(self):
        # Direct DB update bypasses the serializer's transition lock.
        self.appt.status = Appointment.Status.CANCELLED
        self.appt.save()
        with self.assertRaises(InvoiceStateError):
            self.invoice.close(by_user=self.owner, payment_method='cash')
        # Invoice stays open
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.OPEN)

    def test_close_writes_audit_log_entry(self):
        self.invoice.close(by_user=self.owner, payment_method='cash', payment_reference='ref-42')
        log = (
            AuditLog.objects
            .filter(resource_type='invoice', resource_id=str(self.invoice.pk), action=AuditLog.Action.UPDATE)
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('transition'), 'open→paid')
        self.assertEqual(log.metadata.get('payment_method'), 'cash')
        self.assertEqual(log.metadata.get('payment_reference'), 'ref-42')


# ── Direct PATCH status=completed must be rejected ──────────────────────


class AppointmentCompleteGate(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('gate-tenant')
        self.provider = _make_membership(
            user=self.owner, tenant=self.tenant,  # reuse owner so they have all perms
            role=TenantMembership.Role.OWNER, is_bookable=True,
        ) if False else None
        # Create a separate provider membership so the appointment has a provider
        self.provider_user = _make_user('gate-provider@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant)
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )

        self.client = APIClient()
        # Use force_login (real session) rather than force_authenticate so
        # AuthenticationMiddleware → TenantMiddleware sees the user when
        # resolving `request.tenant_membership`. force_authenticate sets
        # request.user only at the view layer, after the membership has
        # already been (not) resolved.
        self.client.force_login(self.owner)

    def _patch_status(self, new_status: str):
        url = reverse('appointment-detail', args=[self.appt.pk])
        return self.client.patch(
            url,
            data={'status': new_status},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_direct_complete_is_rejected_with_guidance(self):
        response = self._patch_status('completed')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # The error names the close endpoint so integrators see the right path.
        self.assertIn('close', str(response.data).lower())
        # Appointment unchanged
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.CHECKED_IN)

    def test_other_transitions_still_work(self):
        response = self._patch_status('cancelled')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, Appointment.Status.CANCELLED)


# ── Reopen: perm + 60-day window + closed_at preserved ──────────────────


class InvoiceReopenTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('reopen-tenant')
        self.provider_user = _make_user('reopen-provider@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=8000, tax='0')
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.refresh_from_db()
        self.first_closed_at = self.invoice.closed_at

    def test_reopen_within_window_succeeds_and_reverts_appointment(self):
        self.invoice.reopen(by_user=self.owner, reason='customer disputes amount')
        self.invoice.refresh_from_db()
        self.appt.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.OPEN)
        self.assertEqual(self.invoice.reopen_count, 1)
        self.assertEqual(self.appt.status, Appointment.Status.CHECKED_IN)
        self.assertIsNone(self.appt.completed_at)

    def test_reopen_outside_window_raises(self):
        # Push the closed_at back by 61 days
        Invoice.objects.filter(pk=self.invoice.pk).update(
            closed_at=self.first_closed_at - dt.timedelta(days=61),
        )
        self.invoice.refresh_from_db()
        with self.assertRaises(InvoiceReopenWindowError):
            self.invoice.reopen(by_user=self.owner, reason='too late')

    def test_re_close_does_not_reset_window(self):
        self.invoice.reopen(by_user=self.owner, reason='small fix')
        # Re-close
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.refresh_from_db()
        # closed_at must be unchanged from the FIRST close — that's the
        # explicit user rule and the SOC 2 traceability requirement.
        self.assertEqual(self.invoice.closed_at, self.first_closed_at)

    def test_reopen_increments_count_and_logs(self):
        self.invoice.reopen(by_user=self.owner, reason='r1')
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='r2')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.reopen_count, 2)

        logs = AuditLog.objects.filter(
            resource_type='invoice',
            resource_id=str(self.invoice.pk),
            action=AuditLog.Action.UPDATE,
            metadata__transition='paid→open',
        ).order_by('timestamp')
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs[0].metadata.get('reason'), 'r1')
        self.assertEqual(logs[1].metadata.get('reason'), 'r2')

    def test_reopen_endpoint_requires_REOPEN_INVOICE_permission(self):
        # Spin up a front-desk user — explicitly does NOT have REOPEN_INVOICE.
        fd_user = _make_user('fd@test.local')
        _make_membership(
            user=fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        client = APIClient()
        client.force_login(fd_user)

        url = reverse('invoice-reopen', args=[self.invoice.pk])
        response = client.post(
            url, data={'reason': 'unauthorized attempt'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reopen_permission_cannot_be_granted_via_extras(self):
        # Front-desk user with extra_permissions trying to grant REOPEN_INVOICE.
        # Locked-permission rule must reject this.
        fd_user = _make_user('fd-attempt@test.local')
        m = _make_membership(
            user=fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
            extra_permissions=[P.REOPEN_INVOICE],
        )
        self.assertFalse(m.has(P.REOPEN_INVOICE))


# ── Void rules ───────────────────────────────────────────────────────────


class InvoiceVoidTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('void-tenant')
        self.provider_user = _make_user('void-provider@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant)
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.BOOKED,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

    def test_void_open_invoice_succeeds(self):
        self.invoice.void(by_user=self.owner, reason='booking error')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.VOID)
        self.assertEqual(self.invoice.void_reason, 'booking error')

    def test_void_requires_reason(self):
        with self.assertRaises(InvoiceStateError):
            self.invoice.void(by_user=self.owner, reason='')

    def test_cannot_void_paid_invoice_directly(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        with self.assertRaises(InvoiceStateError):
            self.invoice.void(by_user=self.owner, reason='try to skip reopen')

    def test_double_void_raises(self):
        self.invoice.void(by_user=self.owner, reason='first')
        with self.assertRaises(InvoiceStateError):
            self.invoice.void(by_user=self.owner, reason='second')


# ── Tenant isolation ─────────────────────────────────────────────────────


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.tenant_a, self.owner_a = _make_tenant_with_owner('tenant-a')
        self.tenant_b, self.owner_b = _make_tenant_with_owner('tenant-b')

        # Create an invoice in tenant A
        prov_user_a = _make_user('a-provider@test.local')
        prov_a = _make_membership(
            user=prov_user_a, tenant=self.tenant_a,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        appt_a = _make_appointment(
            self.tenant_a,
            customer=_make_customer(self.tenant_a),
            service=_make_service(self.tenant_a),
            provider=prov_a, created_by=self.owner_a,
        )
        self.invoice_a = Invoice.objects.get(appointment=appt_a)

    def test_user_in_tenant_b_cannot_list_tenant_a_invoices(self):
        client = APIClient()
        client.force_login(self.owner_b)

        url = reverse('invoice-list')
        response = client.get(url, HTTP_X_TENANT_SLUG=self.tenant_b.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.data
        results = body.get('results', body) if isinstance(body, dict) else body
        # No invoices exist in tenant B, so result must be empty.
        self.assertEqual(len(results), 0)

    def test_user_in_tenant_b_cannot_retrieve_tenant_a_invoice(self):
        client = APIClient()
        client.force_login(self.owner_b)

        url = reverse('invoice-detail', args=[self.invoice_a.pk])
        response = client.get(url, HTTP_X_TENANT_SLUG=self.tenant_b.slug)
        # 404 not 403 — we don't acknowledge the invoice's existence to
        # an outside-tenant caller.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Invoice number generator ─────────────────────────────────────────────


class InvoiceNumberGeneratorTests(TestCase):
    """Verify the per-tenant `INV-YYYY-NNNN` numbering scheme.

    Covers: format correctness, per-tenant isolation (two tenants
    can both have INV-2026-0001), year-rollover (sequence resets on
    Jan 1), gap-tolerance (a deleted invoice doesn't reset the
    sequence), and concurrent-creation safety (the unique constraint
    is the final backstop)."""

    def setUp(self):
        self.tenant_a, self.owner_a = _make_tenant_with_owner('numgen-a')
        self.tenant_b, self.owner_b = _make_tenant_with_owner('numgen-b')
        self.prov_a_user = _make_user('numgen-prov-a@test.local')
        self.prov_b_user = _make_user('numgen-prov-b@test.local')
        self.prov_a = _make_membership(
            user=self.prov_a_user, tenant=self.tenant_a,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.prov_b = _make_membership(
            user=self.prov_b_user, tenant=self.tenant_b,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.cust_a = _make_customer(self.tenant_a)
        self.cust_b = _make_customer(self.tenant_b)
        self.svc_a = _make_service(self.tenant_a)
        self.svc_b = _make_service(self.tenant_b)

    def test_first_invoice_in_tenant_gets_sequence_0001(self):
        appt = _make_appointment(
            self.tenant_a, customer=self.cust_a, service=self.svc_a,
            provider=self.prov_a,
        )
        invoice = Invoice.objects.get(appointment=appt)
        self.assertEqual(invoice.invoice_number, f'INV-{timezone.now().year}-0001')

    def test_sequence_increments_within_tenant_and_year(self):
        for i in range(3):
            _make_appointment(
                self.tenant_a, customer=self.cust_a, service=self.svc_a,
                provider=self.prov_a,
                start=timezone.now() + dt.timedelta(hours=i + 1),
            )
        numbers = list(
            Invoice.objects
            .filter(tenant=self.tenant_a)
            .order_by('created_at')
            .values_list('invoice_number', flat=True)
        )
        year = timezone.now().year
        self.assertEqual(numbers, [f'INV-{year}-0001', f'INV-{year}-0002', f'INV-{year}-0003'])

    def test_per_tenant_isolation(self):
        """Both tenants can have INV-2026-0001."""
        appt_a = _make_appointment(
            self.tenant_a, customer=self.cust_a, service=self.svc_a,
            provider=self.prov_a,
        )
        appt_b = _make_appointment(
            self.tenant_b, customer=self.cust_b, service=self.svc_b,
            provider=self.prov_b,
        )
        inv_a = Invoice.objects.get(appointment=appt_a)
        inv_b = Invoice.objects.get(appointment=appt_b)
        year = timezone.now().year
        self.assertEqual(inv_a.invoice_number, f'INV-{year}-0001')
        self.assertEqual(inv_b.invoice_number, f'INV-{year}-0001')
        self.assertNotEqual(inv_a.tenant_id, inv_b.tenant_id)

    def test_unique_per_tenant_constraint_holds(self):
        """The partial unique constraint rejects duplicate numbers per tenant."""
        from django.db import IntegrityError
        appt = _make_appointment(
            self.tenant_a, customer=self.cust_a, service=self.svc_a,
            provider=self.prov_a,
        )
        existing = Invoice.objects.get(appointment=appt)
        with self.assertRaises(IntegrityError):
            # Try to create a second invoice with the same number.
            # We bypass the generator by using create() directly with
            # the same value — the DB constraint should reject it.
            Invoice.objects.create(
                tenant=self.tenant_a,
                customer=self.cust_a,
                invoice_number=existing.invoice_number,
                status=Invoice.Status.OPEN,
            )

    def test_blank_invoice_number_does_not_collide(self):
        """The constraint excludes empty strings so backfill races and
        intermediate creation states don't trigger false conflicts."""
        # Two rows with invoice_number='' should not collide.
        Invoice.objects.create(
            tenant=self.tenant_a, customer=self.cust_a,
            invoice_number='', status=Invoice.Status.OPEN,
        )
        Invoice.objects.create(
            tenant=self.tenant_a, customer=self.cust_a,
            invoice_number='', status=Invoice.Status.OPEN,
        )
        # Both saved successfully — assertion is "didn't raise".

    def test_year_rollover_resets_sequence(self):
        """Sequence resets at Jan 1: INV-2025-9999 → INV-2026-0001."""
        from apps.invoices.services import generate_invoice_number
        # Manually create an invoice with last year's number so the
        # generator sees it.
        Invoice.objects.create(
            tenant=self.tenant_a,
            customer=self.cust_a,
            invoice_number='INV-2025-9999',
            status=Invoice.Status.OPEN,
        )
        # Generate for THIS year — should restart at 0001.
        with transaction.atomic():
            number = generate_invoice_number(self.tenant_a, year=2026)
        self.assertEqual(number, 'INV-2026-0001')

    def test_gap_tolerance_does_not_reset_sequence(self):
        """If invoice 0002 is deleted, the next invoice is still 0004 (no reuse)."""
        for i in range(3):
            _make_appointment(
                self.tenant_a, customer=self.cust_a, service=self.svc_a,
                provider=self.prov_a,
                start=timezone.now() + dt.timedelta(hours=i + 1),
            )
        year = timezone.now().year
        # Delete the middle invoice to create a gap.
        Invoice.objects.get(invoice_number=f'INV-{year}-0002').delete()
        # Create a new appointment — its invoice should be 0004, not 0002.
        _make_appointment(
            self.tenant_a, customer=self.cust_a, service=self.svc_a,
            provider=self.prov_a,
            start=timezone.now() + dt.timedelta(hours=10),
        )
        latest = Invoice.objects.filter(tenant=self.tenant_a).order_by('-invoice_number').first()
        self.assertEqual(latest.invoice_number, f'INV-{year}-0004')

    def test_format_is_zero_padded_to_four_digits(self):
        """Sequences below 10 read as INV-YYYY-0001, not INV-YYYY-1."""
        appt = _make_appointment(
            self.tenant_a, customer=self.cust_a, service=self.svc_a,
            provider=self.prov_a,
        )
        invoice = Invoice.objects.get(appointment=appt)
        # Format check: INV-YYYY-NNNN → exactly 13 characters.
        self.assertRegex(invoice.invoice_number, r'^INV-\d{4}-\d{4}$')

    def test_serializer_exposes_invoice_number(self):
        """API response includes invoice_number for the frontend."""
        from rest_framework.test import APIClient
        appt = _make_appointment(
            self.tenant_a, customer=self.cust_a, service=self.svc_a,
            provider=self.prov_a,
        )
        invoice = Invoice.objects.get(appointment=appt)
        client = APIClient()
        client.force_login(self.owner_a)
        response = client.get(
            reverse('invoice-detail', args=[invoice.pk]),
            HTTP_X_TENANT_SLUG=self.tenant_a.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['invoice_number'], invoice.invoice_number)
        self.assertRegex(response.data['invoice_number'], r'^INV-\d{4}-\d{4}$')


# ── Product line items + inventory side effects (Phase 2A precursor) ────


class InvoiceProductLineTests(TestCase):
    """Adding products as line items + stock decrement on close +
    restock on reopen. The serializer + viewset enforce mutual
    exclusion (service XOR product per line)."""

    def setUp(self):
        from apps.products.models import Product

        self.tenant, self.owner = _make_tenant_with_owner('inv-prod')
        self.provider_user = _make_user('inv-prod-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=10000, tax='0')
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

        self.product = Product.objects.create(
            tenant=self.tenant,
            name='Vitamin C Serum',
            sku='VCS',
            price_cents=4500,
            tax_rate_percent=Decimal('8.875'),
            track_inventory=True,
            stock_quantity=20,
        )
        self.untracked = Product.objects.create(
            tenant=self.tenant,
            name='Gift Card',
            sku='GC',
            price_cents=5000,
            track_inventory=False,
            stock_quantity=0,
        )
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _add_line_url(self, invoice_pk):
        return reverse('invoice-add-line', kwargs={'pk': invoice_pk})

    # ── add_line ────────────────────────────────────────────────────

    def test_add_product_line_snapshots_price_and_tax(self):
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'product_id': self.product.pk, 'quantity': 2},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        line = self.invoice.line_items.order_by('-id').first()
        self.assertEqual(line.product_id, self.product.pk)
        self.assertIsNone(line.service_id)
        self.assertEqual(line.unit_price_cents, 4500)
        self.assertEqual(str(line.tax_rate_percent), '8.875')
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.line_subtotal_cents, 9000)

    def test_add_service_line_via_endpoint(self):
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'service_id': self.service.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        line = self.invoice.line_items.order_by('-id').first()
        self.assertEqual(line.service_id, self.service.pk)
        self.assertIsNone(line.product_id)

    def test_add_line_rejects_both_service_and_product(self):
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={
                'service_id': self.service.pk,
                'product_id': self.product.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_line_rejects_neither(self):
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'quantity': 2},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_line_unit_price_override(self):
        # Member discount: ring up the $45 serum at $35.
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'product_id': self.product.pk, 'unit_price_cents': 3500},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        line = self.invoice.line_items.order_by('-id').first()
        self.assertEqual(line.unit_price_cents, 3500)

    def test_add_line_to_paid_invoice_is_409(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'product_id': self.product.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_add_line_inactive_product_rejected(self):
        self.product.is_active = False
        self.product.save()
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'product_id': self.product.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_line_cross_tenant_product_404(self):
        from apps.products.models import Product

        other_tenant, _ = _make_tenant_with_owner('inv-prod-other')
        other_product = Product.objects.create(
            tenant=other_tenant, name='X', price_cents=100,
        )
        response = self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'product_id': other_product.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── remove_line ─────────────────────────────────────────────────

    def test_remove_line_recalculates_total(self):
        # Add a $90 retail line, then remove it.
        self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'product_id': self.product.pk, 'quantity': 2},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.refresh_from_db()
        line = self.invoice.line_items.order_by('-id').first()
        before_total = self.invoice.total_cents

        response = self.client.delete(
            reverse(
                'invoice-remove-line',
                kwargs={'pk': self.invoice.pk, 'line_pk': line.pk},
            ),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.invoice.refresh_from_db()
        self.assertLess(self.invoice.total_cents, before_total)

    def test_remove_line_404_for_other_invoice_line(self):
        # Build a totally separate invoice + line, try to remove from
        # the wrong invoice.
        other_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() + dt.timedelta(hours=4),
        )
        other_invoice = Invoice.objects.get(appointment=other_appt)
        other_line = other_invoice.line_items.first()
        response = self.client.delete(
            reverse(
                'invoice-remove-line',
                kwargs={'pk': self.invoice.pk, 'line_pk': other_line.pk},
            ),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_remove_line_rejected_on_paid_invoice(self):
        self.client.post(
            self._add_line_url(self.invoice.pk),
            data={'product_id': self.product.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.refresh_from_db()
        line = self.invoice.line_items.order_by('-id').first()
        self.invoice.close(by_user=self.owner, payment_method='cash')
        response = self.client.delete(
            reverse(
                'invoice-remove-line',
                kwargs={'pk': self.invoice.pk, 'line_pk': line.pk},
            ),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


class InvoiceInventoryTests(TestCase):
    """Stock decrement at close + restock at reopen, scoped per
    tracked-product line."""

    def setUp(self):
        from apps.products.models import Product

        self.tenant, self.owner = _make_tenant_with_owner('inv-inv')
        self.provider_user = _make_user('inv-inv-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=10000, tax='0')
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

        self.product = Product.objects.create(
            tenant=self.tenant, name='Cream', sku='CR', price_cents=2000,
            stock_quantity=10, track_inventory=True,
        )
        self.untracked = Product.objects.create(
            tenant=self.tenant, name='Gift', sku='GFT', price_cents=5000,
            stock_quantity=0, track_inventory=False,
        )

    def _add_product_line(self, product, qty):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, service=None, product=product,
            description=product.name, quantity=qty,
            unit_price_cents=product.price_cents,
            tax_rate_percent=product.tax_rate_percent,
        )

    def test_close_decrements_tracked_product_stock(self):
        self._add_product_line(self.product, qty=3)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 7)

    def test_close_skips_untracked_product(self):
        self._add_product_line(self.untracked, qty=1)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.untracked.refresh_from_db()
        # Stayed at 0 — the close worker skipped the untracked SKU.
        self.assertEqual(self.untracked.stock_quantity, 0)

    def test_close_records_inventory_snapshot_in_audit(self):
        self._add_product_line(self.product, qty=2)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        log = (
            AuditLog.objects
            .filter(
                resource_type='invoice',
                resource_id=str(self.invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertEqual(log.metadata['transition'], 'open→paid')
        snapshot = log.metadata.get('inventory') or []
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]['product_id'], self.product.pk)
        self.assertEqual(snapshot[0]['before'], 10)
        self.assertEqual(snapshot[0]['after'], 8)
        self.assertEqual(snapshot[0]['qty'], 2)

    def test_reopen_restocks(self):
        self._add_product_line(self.product, qty=4)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 6)

        # Reopen restocks — back to 10.
        self.invoice.reopen(by_user=self.owner, reason='customer changed mind')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_void_does_not_touch_stock(self):
        # Open invoice has never decremented — voiding it shouldn't
        # restock either (no over-restock bug).
        self._add_product_line(self.product, qty=4)
        self.invoice.void(by_user=self.owner, reason='comp visit')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_close_then_reopen_then_close_decrements_correctly(self):
        # Two cycles: 10 → 8 → 10 → 8.
        self._add_product_line(self.product, qty=2)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 8)

    def test_decrement_can_drive_stock_negative_for_visibility(self):
        # Sell 12 of a product where only 10 are on hand. The signed
        # IntegerField means stock goes to -2, surfacing the
        # backorder rather than silently clamping.
        self._add_product_line(self.product, qty=12)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, -2)


# ── Package sale + redemption (Phase 2B precursor) ──────────────────


class InvoicePackageSaleTests(TestCase):
    """Selling a package on an invoice creates a PENDING
    PurchasedPackage; close flips it ACTIVE; reopen reverts (only
    if no redemptions yet); void cascades to VOIDED."""

    def setUp(self):
        from apps.packages.models import (
            Package,
            PackageItem,
            PurchasedPackage,
        )

        self.tenant, self.owner = _make_tenant_with_owner('inv-pkg-sale')
        self.provider_user = _make_user('inv-pkg-sale-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.facial = _make_service(
            self.tenant, name='Facial', price_cents=10000,
        )
        self.peel = _make_service(
            self.tenant, name='Peel', price_cents=15000,
        )
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

        self.package = Package.objects.create(
            tenant=self.tenant,
            name='5 Facial Pack',
            sku='5FP',
            price_cents=40000,
            validity_days=365,
        )
        PackageItem.objects.create(
            package=self.package, service=self.facial, quantity=5,
        )
        PackageItem.objects.create(
            package=self.package, service=self.peel, quantity=1,
        )

        self.PurchasedPackage = PurchasedPackage
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _add_line_url(self):
        return reverse('invoice-add-line', kwargs={'pk': self.invoice.pk})

    # ── Sale ────────────────────────────────────────────────────────

    def test_add_package_creates_pending_purchased_package_with_items(self):
        response = self.client.post(
            self._add_line_url(),
            data={'package_id': self.package.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        line = self.invoice.line_items.order_by('-id').first()
        self.assertEqual(line.package_id, self.package.pk)
        self.assertEqual(line.unit_price_cents, 40000)

        pp = self.PurchasedPackage.objects.get(source_invoice_line=line)
        self.assertEqual(pp.status, self.PurchasedPackage.Status.PENDING)
        self.assertEqual(pp.name, '5 Facial Pack')
        self.assertEqual(pp.price_cents, 40000)
        self.assertEqual(pp.validity_days, 365)
        self.assertIsNone(pp.purchased_at)
        self.assertIsNone(pp.expires_at)

        items = list(pp.items.order_by('id'))
        self.assertEqual(len(items), 2)
        # Each item snapshots the service's a-la-carte price for
        # later reporting.
        facial_item = next(i for i in items if i.service_id == self.facial.pk)
        self.assertEqual(facial_item.quantity_purchased, 5)
        self.assertEqual(facial_item.quantity_remaining, 5)
        self.assertEqual(facial_item.unit_value_cents, 10000)

    def test_add_inactive_package_rejected(self):
        self.package.is_active = False
        self.package.save()
        response = self.client.post(
            self._add_line_url(),
            data={'package_id': self.package.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_package_with_no_items_rejected(self):
        from apps.packages.models import Package
        empty = Package.objects.create(
            tenant=self.tenant, name='Empty', price_cents=100,
        )
        response = self.client.post(
            self._add_line_url(),
            data={'package_id': empty.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_line_rejects_two_of_three_kinds(self):
        from apps.products.models import Product
        product = Product.objects.create(
            tenant=self.tenant, name='X', price_cents=1000,
        )
        response = self.client.post(
            self._add_line_url(),
            data={
                'package_id': self.package.pk,
                'product_id': product.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Close: PENDING → ACTIVE ─────────────────────────────────────

    def test_close_activates_purchased_package_and_sets_expiry(self):
        self.client.post(
            self._add_line_url(),
            data={'package_id': self.package.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        pp = self.PurchasedPackage.objects.get(
            source_invoice_line__invoice=self.invoice,
        )
        self.assertEqual(pp.status, self.PurchasedPackage.Status.ACTIVE)
        self.assertIsNotNone(pp.purchased_at)
        self.assertIsNotNone(pp.expires_at)
        # 365 days of validity → expiry roughly a year out.
        days = (pp.expires_at - pp.purchased_at).days
        self.assertEqual(days, 365)

    def test_close_records_packages_in_audit_metadata(self):
        self.client.post(
            self._add_line_url(),
            data={'package_id': self.package.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(self.invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertEqual(log.metadata['transition'], 'open→paid')
        snapshot = log.metadata.get('packages_activated') or []
        self.assertEqual(len(snapshot), 1)

    # ── Reopen ──────────────────────────────────────────────────────

    def test_reopen_with_no_redemptions_reverts_to_pending(self):
        self.client.post(
            self._add_line_url(),
            data={'package_id': self.package.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')
        pp = self.PurchasedPackage.objects.get(
            source_invoice_line__invoice=self.invoice,
        )
        self.assertEqual(pp.status, self.PurchasedPackage.Status.PENDING)
        self.assertIsNone(pp.purchased_at)
        self.assertIsNone(pp.expires_at)

    # ── Void ────────────────────────────────────────────────────────

    def test_void_cascades_to_pending_packages(self):
        self.client.post(
            self._add_line_url(),
            data={'package_id': self.package.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.void(by_user=self.owner, reason='customer changed mind')
        pp = self.PurchasedPackage.objects.get(
            source_invoice_line__invoice=self.invoice,
        )
        self.assertEqual(pp.status, self.PurchasedPackage.Status.VOIDED)
        self.assertEqual(pp.void_reason, 'invoice_voided')


class InvoicePackageRedemptionTests(TestCase):
    """Drawing down credits from an ACTIVE PurchasedPackage onto a
    different appointment's invoice."""

    def setUp(self):
        from apps.packages.models import (
            Package,
            PackageItem,
            PurchasedPackage,
            PurchasedPackageItem,
        )

        self.tenant, self.owner = _make_tenant_with_owner('inv-pkg-rdm')
        self.provider_user = _make_user('inv-pkg-rdm-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.facial = _make_service(
            self.tenant, name='Facial', price_cents=10000,
        )
        self.peel = _make_service(
            self.tenant, name='Peel', price_cents=15000,
        )

        # Sale invoice — closed, package activated.
        sale_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() - dt.timedelta(days=30),
        )
        self.sale_invoice = Invoice.objects.get(appointment=sale_appt)

        package = Package.objects.create(
            tenant=self.tenant, name='5 Facial', price_cents=40000,
            validity_days=365,
        )
        PackageItem.objects.create(
            package=package, service=self.facial, quantity=5,
        )
        # Sell + close to flip ACTIVE.
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.client.post(
            reverse('invoice-add-line', kwargs={'pk': self.sale_invoice.pk}),
            data={'package_id': package.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.sale_invoice.close(by_user=self.owner, payment_method='cash')
        self.purchased_package = PurchasedPackage.objects.get(
            source_invoice_line__invoice=self.sale_invoice,
        )

        # Redemption invoice — a future appointment for the same
        # customer where we'll redeem one credit.
        redeem_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() + dt.timedelta(days=1),
        )
        self.redeem_invoice = Invoice.objects.get(appointment=redeem_appt)

        self.PurchasedPackage = PurchasedPackage
        self.PurchasedPackageItem = PurchasedPackageItem

    def _redeem_url(self, invoice_pk):
        return reverse(
            'invoice-redeem-from-package', kwargs={'pk': invoice_pk},
        )

    def test_redeem_decrements_balance_and_creates_zero_line(self):
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        item = self.PurchasedPackageItem.objects.get(
            purchased_package=self.purchased_package,
            service=self.facial,
        )
        self.assertEqual(item.quantity_remaining, 4)
        # The new line on the redeem invoice is $0.
        line = self.redeem_invoice.line_items.order_by('-id').first()
        self.assertEqual(line.unit_price_cents, 0)
        self.assertIn('redeemed from package', line.description)

    def test_redeem_writes_ledger_row(self):
        from apps.packages.models import PackageRedemption

        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        ledger = PackageRedemption.objects.get(
            purchased_package=self.purchased_package,
        )
        self.assertEqual(ledger.quantity, 1)
        self.assertEqual(ledger.by_user, self.owner)
        self.assertIsNotNone(ledger.invoice_line)

    def test_redeem_audit_log_metadata(self):
        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(self.redeem_invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertEqual(log.metadata.get('event'), 'package_redeemed')
        self.assertEqual(log.metadata.get('remaining_after'), 4)

    def test_redeem_service_not_in_package_rejected(self):
        # The package only includes Facial. Try to redeem a Peel.
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.peel.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_redeem_until_empty_then_409(self):
        # Drain all 5 credits.
        for _ in range(5):
            response = self.client.post(
                self._redeem_url(self.redeem_invoice.pk),
                data={
                    'purchased_package_id': self.purchased_package.pk,
                    'service_id': self.facial.pk,
                },
                format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 6th attempt should fail.
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_redeem_other_customers_package_rejected(self):
        # Different customer, same tenant.
        other_customer = _make_customer(self.tenant, first='Other')
        other_appt = _make_appointment(
            self.tenant, customer=other_customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() + dt.timedelta(days=2),
        )
        other_invoice = Invoice.objects.get(appointment=other_appt)
        response = self.client.post(
            self._redeem_url(other_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_redeem_against_paid_invoice_409(self):
        self.redeem_invoice.close(by_user=self.owner, payment_method='cash')
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reopen_sale_invoice_blocked_after_redemption(self):
        # Redeem one credit, then try to reopen the SALE invoice.
        # The reopen should refuse because the redemption ledger
        # would orphan otherwise.
        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'purchased_package_id': self.purchased_package.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        with self.assertRaises(InvoiceStateError):
            self.sale_invoice.reopen(by_user=self.owner, reason='oops')


class InvoiceCustomPackageTests(TestCase):
    """Custom (per-customer, off-catalog) package sale.

    Same lifecycle as a catalog package but built inline. The
    PurchasedPackage row has source_template=NULL and snapshots
    everything else from the request.
    """

    def setUp(self):
        from apps.packages.models import PurchasedPackage

        self.tenant, self.owner = _make_tenant_with_owner('inv-custpkg')
        self.provider_user = _make_user('inv-custpkg-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.facial = _make_service(
            self.tenant, name='Facial', price_cents=10000,
        )
        self.peel = _make_service(
            self.tenant, name='Peel', price_cents=15000,
        )
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

        self.PurchasedPackage = PurchasedPackage
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _url(self):
        return reverse(
            'invoice-add-custom-package', kwargs={'pk': self.invoice.pk},
        )

    def test_add_custom_package_creates_purchased_package_with_null_template(self):
        response = self.client.post(
            self._url(),
            data={
                'name': "Jane's Wedding Bundle",
                'description': 'Bridal package — facials + peels',
                'price_cents': 35000,
                'validity_days': 180,
                'items': [
                    {'service_id': self.facial.pk, 'quantity': 3},
                    {'service_id': self.peel.pk, 'quantity': 2},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        line = self.invoice.line_items.order_by('-id').first()
        self.assertIsNone(line.service_id)
        self.assertIsNone(line.product_id)
        self.assertIsNone(line.package_id)  # all null = ad-hoc / custom
        self.assertEqual(line.unit_price_cents, 35000)

        pp = self.PurchasedPackage.objects.get(source_invoice_line=line)
        self.assertIsNone(pp.source_template)
        self.assertEqual(pp.name, "Jane's Wedding Bundle")
        self.assertEqual(pp.price_cents, 35000)
        self.assertEqual(pp.validity_days, 180)
        self.assertEqual(pp.status, self.PurchasedPackage.Status.PENDING)
        items = list(pp.items.order_by('id'))
        self.assertEqual(len(items), 2)
        facial_item = next(i for i in items if i.service_id == self.facial.pk)
        self.assertEqual(facial_item.quantity_purchased, 3)
        self.assertEqual(facial_item.quantity_remaining, 3)

    def test_close_activates_custom_package(self):
        self.client.post(
            self._url(),
            data={
                'name': 'Custom',
                'price_cents': 10000,
                'items': [{'service_id': self.facial.pk, 'quantity': 2}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        pp = self.PurchasedPackage.objects.get(
            source_invoice_line__invoice=self.invoice,
        )
        self.assertEqual(pp.status, self.PurchasedPackage.Status.ACTIVE)
        self.assertIsNotNone(pp.purchased_at)

    def test_redeem_against_custom_package(self):
        # Sell + close, then redeem one credit against a different
        # appointment's invoice.
        self.client.post(
            self._url(),
            data={
                'name': 'Custom',
                'price_cents': 10000,
                'items': [{'service_id': self.facial.pk, 'quantity': 2}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        pp = self.PurchasedPackage.objects.get(
            source_invoice_line__invoice=self.invoice,
        )

        # Future appointment for the same customer.
        future_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() + dt.timedelta(days=1),
        )
        future_invoice = Invoice.objects.get(appointment=future_appt)
        response = self.client.post(
            reverse(
                'invoice-redeem-from-package',
                kwargs={'pk': future_invoice.pk},
            ),
            data={
                'purchased_package_id': pp.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_empty_items_rejected(self):
        response = self.client.post(
            self._url(),
            data={'name': 'Empty', 'price_cents': 1000, 'items': []},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_service_rejected(self):
        response = self.client.post(
            self._url(),
            data={
                'name': 'Dup',
                'price_cents': 1000,
                'items': [
                    {'service_id': self.facial.pk, 'quantity': 1},
                    {'service_id': self.facial.pk, 'quantity': 2},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_tenant_service_rejected(self):
        other_tenant, _ = _make_tenant_with_owner('inv-custpkg-other')
        cross_service = _make_service(other_tenant, name='Cross')
        response = self.client.post(
            self._url(),
            data={
                'name': 'Cross-tenant',
                'price_cents': 1000,
                'items': [{'service_id': cross_service.pk, 'quantity': 1}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paid_invoice_rejects_custom_package(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        response = self.client.post(
            self._url(),
            data={
                'name': 'Late',
                'price_cents': 1000,
                'items': [{'service_id': self.facial.pk, 'quantity': 1}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


# ── Membership sale + redemption (Phase 2C precursor) ───────────────


class InvoiceMembershipSaleTests(TestCase):
    """Selling a membership plan on an invoice creates a PENDING
    Subscription; close flips it ACTIVE + sets period dates;
    reopen reverts only if no redemptions; void cascade-cancels."""

    def setUp(self):
        from apps.memberships.models import (
            MembershipPlan,
            MembershipPlanItem,
            Subscription,
        )

        self.tenant, self.owner = _make_tenant_with_owner('inv-mbr-sale')
        self.provider_user = _make_user('inv-mbr-sale-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.facial = _make_service(
            self.tenant, name='Facial', price_cents=10000,
        )
        self.peel = _make_service(
            self.tenant, name='Peel', price_cents=15000,
        )
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

        self.plan = MembershipPlan.objects.create(
            tenant=self.tenant,
            name='Glow Club',
            sku='GC',
            price_cents=9900,
            billing_interval=MembershipPlan.BillingInterval.MONTHLY,
        )
        MembershipPlanItem.objects.create(
            plan=self.plan, service=self.facial, quantity_per_cycle=1,
        )

        self.Subscription = Subscription
        self.MembershipPlan = MembershipPlan
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _add_line_url(self):
        return reverse('invoice-add-line', kwargs={'pk': self.invoice.pk})

    # ── Sale ────────────────────────────────────────────────────────

    def test_add_membership_creates_pending_subscription_with_items(self):
        response = self.client.post(
            self._add_line_url(),
            data={'membership_plan_id': self.plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        line = self.invoice.line_items.order_by('-id').first()
        self.assertEqual(line.membership_plan_id, self.plan.pk)
        self.assertEqual(line.unit_price_cents, 9900)

        sub = self.Subscription.objects.get(source_invoice_line=line)
        self.assertEqual(sub.status, self.Subscription.Status.PENDING)
        self.assertEqual(sub.name, 'Glow Club')
        self.assertEqual(sub.price_cents, 9900)
        self.assertEqual(
            sub.billing_interval,
            self.MembershipPlan.BillingInterval.MONTHLY,
        )
        self.assertIsNone(sub.started_at)
        self.assertIsNone(sub.current_period_starts_at)

        items = list(sub.items.order_by('id'))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].quantity_per_cycle, 1)
        self.assertEqual(items[0].quantity_remaining, 1)
        self.assertEqual(items[0].unit_value_cents, 10000)

    def test_add_inactive_plan_rejected(self):
        self.plan.is_active = False
        self.plan.save()
        response = self.client.post(
            self._add_line_url(),
            data={'membership_plan_id': self.plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_line_rejects_two_of_four_kinds(self):
        from apps.products.models import Product
        product = Product.objects.create(
            tenant=self.tenant, name='X', price_cents=1000,
        )
        response = self.client.post(
            self._add_line_url(),
            data={
                'membership_plan_id': self.plan.pk,
                'product_id': product.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Close: PENDING → ACTIVE with period dates ───────────────────

    def test_close_activates_subscription_with_monthly_period(self):
        self.client.post(
            self._add_line_url(),
            data={'membership_plan_id': self.plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        sub = self.Subscription.objects.get(
            source_invoice_line__invoice=self.invoice,
        )
        self.assertEqual(sub.status, self.Subscription.Status.ACTIVE)
        self.assertIsNotNone(sub.started_at)
        self.assertIsNotNone(sub.current_period_starts_at)
        self.assertIsNotNone(sub.current_period_ends_at)
        days = (sub.current_period_ends_at - sub.current_period_starts_at).days
        self.assertEqual(days, 30)

    def test_close_activates_annual_subscription_with_365_day_period(self):
        annual_plan = self.MembershipPlan.objects.create(
            tenant=self.tenant,
            name='Yearly',
            price_cents=99000,
            billing_interval=self.MembershipPlan.BillingInterval.ANNUAL,
        )
        from apps.memberships.models import MembershipPlanItem
        MembershipPlanItem.objects.create(
            plan=annual_plan, service=self.facial, quantity_per_cycle=12,
        )
        self.client.post(
            self._add_line_url(),
            data={'membership_plan_id': annual_plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        sub = self.Subscription.objects.get(
            source_invoice_line__invoice=self.invoice,
            plan=annual_plan,
        )
        days = (sub.current_period_ends_at - sub.current_period_starts_at).days
        self.assertEqual(days, 365)

    def test_close_records_subscription_in_audit_metadata(self):
        self.client.post(
            self._add_line_url(),
            data={'membership_plan_id': self.plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(self.invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertEqual(log.metadata['transition'], 'open→paid')
        snapshot = log.metadata.get('subscriptions_activated') or []
        self.assertEqual(len(snapshot), 1)

    # ── Reopen ──────────────────────────────────────────────────────

    def test_reopen_with_no_redemptions_reverts_to_pending(self):
        self.client.post(
            self._add_line_url(),
            data={'membership_plan_id': self.plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')
        sub = self.Subscription.objects.get(
            source_invoice_line__invoice=self.invoice,
        )
        self.assertEqual(sub.status, self.Subscription.Status.PENDING)
        self.assertIsNone(sub.started_at)
        self.assertIsNone(sub.current_period_ends_at)

    # ── Void ────────────────────────────────────────────────────────

    def test_void_cascade_cancels_pending_subscriptions(self):
        self.client.post(
            self._add_line_url(),
            data={'membership_plan_id': self.plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.void(
            by_user=self.owner, reason='customer changed mind',
        )
        sub = self.Subscription.objects.get(
            source_invoice_line__invoice=self.invoice,
        )
        self.assertEqual(sub.status, self.Subscription.Status.CANCELLED)
        self.assertEqual(sub.cancel_reason, 'invoice_voided')
        self.assertEqual(sub.cancelled_by, self.owner)


class InvoiceMembershipRedemptionTests(TestCase):
    """Drawing down credits from an ACTIVE Subscription."""

    def setUp(self):
        from apps.memberships.models import (
            MembershipPlan,
            MembershipPlanItem,
            Subscription,
            SubscriptionItem,
        )

        self.tenant, self.owner = _make_tenant_with_owner('inv-mbr-rdm')
        self.provider_user = _make_user('inv-mbr-rdm-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.facial = _make_service(
            self.tenant, name='Facial', price_cents=10000,
        )
        self.peel = _make_service(
            self.tenant, name='Peel', price_cents=15000,
        )

        # Sale invoice — closed, subscription ACTIVE.
        sale_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() - dt.timedelta(days=15),
        )
        self.sale_invoice = Invoice.objects.get(appointment=sale_appt)

        plan = MembershipPlan.objects.create(
            tenant=self.tenant,
            name='Glow Club',
            price_cents=9900,
        )
        MembershipPlanItem.objects.create(
            plan=plan, service=self.facial, quantity_per_cycle=2,
        )

        self.client = APIClient()
        self.client.force_login(self.owner)
        self.client.post(
            reverse('invoice-add-line', kwargs={'pk': self.sale_invoice.pk}),
            data={'membership_plan_id': plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.sale_invoice.close(by_user=self.owner, payment_method='cash')
        self.subscription = Subscription.objects.get(
            source_invoice_line__invoice=self.sale_invoice,
        )

        # Redemption invoice — a future appointment to redeem at.
        redeem_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() + dt.timedelta(days=1),
        )
        self.redeem_invoice = Invoice.objects.get(appointment=redeem_appt)

        self.Subscription = Subscription
        self.SubscriptionItem = SubscriptionItem

    def _redeem_url(self, invoice_pk):
        return reverse(
            'invoice-redeem-from-membership', kwargs={'pk': invoice_pk},
        )

    def test_redeem_decrements_balance_and_creates_zero_line(self):
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        item = self.SubscriptionItem.objects.get(
            subscription=self.subscription,
            service=self.facial,
        )
        self.assertEqual(item.quantity_remaining, 1)
        line = self.redeem_invoice.line_items.order_by('-id').first()
        self.assertEqual(line.unit_price_cents, 0)
        self.assertIn('redeemed from membership', line.description)

    def test_redeem_writes_ledger_row(self):
        from apps.memberships.models import SubscriptionRedemption

        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        ledger = SubscriptionRedemption.objects.get(
            subscription=self.subscription,
        )
        self.assertEqual(ledger.quantity, 1)
        self.assertEqual(ledger.by_user, self.owner)
        self.assertIsNotNone(ledger.invoice_line)

    def test_redeem_audit_log_metadata(self):
        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(self.redeem_invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertEqual(log.metadata.get('event'), 'membership_redeemed')
        self.assertEqual(log.metadata.get('remaining_after'), 1)

    def test_redeem_service_not_in_plan_rejected(self):
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.peel.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_redeem_until_empty_then_409(self):
        for _ in range(2):
            response = self.client.post(
                self._redeem_url(self.redeem_invoice.pk),
                data={
                    'subscription_id': self.subscription.pk,
                    'service_id': self.facial.pk,
                },
                format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_redeem_other_customers_subscription_rejected(self):
        other_customer = _make_customer(self.tenant, first='Other')
        other_appt = _make_appointment(
            self.tenant, customer=other_customer, service=self.facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() + dt.timedelta(days=2),
        )
        other_invoice = Invoice.objects.get(appointment=other_appt)
        response = self.client.post(
            self._redeem_url(other_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_redeem_against_paid_invoice_409(self):
        self.redeem_invoice.close(by_user=self.owner, payment_method='cash')
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_redeem_against_cancelled_subscription_409(self):
        self.subscription.status = self.Subscription.Status.CANCELLED
        self.subscription.save()
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_redeem_outside_period_409(self):
        # Roll the period end back into the past.
        self.subscription.current_period_ends_at = (
            timezone.now() - dt.timedelta(days=1)
        )
        self.subscription.save()
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reopen_sale_invoice_blocked_after_redemption(self):
        # Same protection as packages: redeeming first then trying
        # to reopen the SALE invoice must fail.
        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        with self.assertRaises(InvoiceStateError):
            self.sale_invoice.reopen(by_user=self.owner, reason='oops')


# ── PDF rendering + download endpoint ─────────────────────────────────


class InvoicePDFTests(TestCase):
    """Covers ADR 0018 — on-demand invoice PDF rendering.

    Read-only endpoint; no state changes. Tests focus on:
      - Renderer produces a valid PDF for OPEN / PAID / VOID invoices.
      - Endpoint returns the bytes with the right content-type +
        Content-Disposition.
      - Permission gate: any authenticated tenant member can download,
        cross-tenant access is rejected (404 via queryset isolation).
      - Audit-log entry on every download.
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('pdf-tenant')
        self.provider_user = _make_user('pdf-provider@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=15000, tax='8.875')
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

        self.client = APIClient()
        self.client.force_login(self.owner)

    def _pdf_url(self, pk: int) -> str:
        return reverse('invoice-pdf', args=[pk])

    # ── Renderer (unit-level) ───────────────────────────────────────

    def test_renderer_returns_valid_pdf_for_open_invoice(self):
        from apps.invoices.services import render_invoice_pdf
        pdf = render_invoice_pdf(self.invoice)
        self.assertTrue(pdf.startswith(b'%PDF-'), 'Output is not a PDF file')
        self.assertTrue(pdf.rstrip().endswith(b'%%EOF'), 'PDF trailer missing')
        self.assertGreater(len(pdf), 1000, 'PDF suspiciously small')

    def test_renderer_works_for_paid_invoice(self):
        self.invoice.close(
            by_user=self.owner,
            payment_method=Invoice.PaymentMethod.CASH,
            payment_reference='',
        )
        from apps.invoices.services import render_invoice_pdf
        pdf = render_invoice_pdf(self.invoice)
        self.assertTrue(pdf.startswith(b'%PDF-'))

    def test_renderer_works_for_void_invoice(self):
        self.invoice.void(by_user=self.owner, reason='Test void')
        from apps.invoices.services import render_invoice_pdf
        pdf = render_invoice_pdf(self.invoice)
        self.assertTrue(pdf.startswith(b'%PDF-'))

    # ── Endpoint ─────────────────────────────────────────────────────

    def test_owner_can_download_pdf(self):
        response = self.client.get(
            self._pdf_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn(self.invoice.invoice_number, response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF-'))

    def test_anonymous_blocked(self):
        anon = APIClient()
        response = anon.get(
            self._pdf_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_returns_404(self):
        other_tenant, other_owner = _make_tenant_with_owner('pdf-other-tenant')
        other_client = APIClient()
        other_client.force_login(other_owner)
        response = other_client.get(
            self._pdf_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=other_tenant.slug,
        )
        # `for_current_tenant()` filters the queryset, so the
        # invoice is invisible — DRF 404s rather than 403s.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_can_download_pdf(self):
        provider_client = APIClient()
        provider_client.force_login(self.provider_user)
        response = provider_client.get(
            self._pdf_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_download_writes_audit_log(self):
        self.client.get(
            self._pdf_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='invoice_pdf',
            resource_id=str(self.invoice.pk),
            action=AuditLog.Action.READ,
        ).first()
        self.assertIsNotNone(log, 'No audit log entry for PDF download')
        self.assertGreater(log.metadata.get('bytes', 0), 0)
