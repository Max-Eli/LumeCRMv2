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


class InvoiceMembershipCategoryRedemptionTests(TestCase):
    """Category-credit memberships — one credit covers any service in
    the category, redeemed at that service's full a-la-carte price."""

    def setUp(self):
        from apps.memberships.models import (
            MembershipPlan,
            MembershipPlanItem,
            Subscription,
            SubscriptionItem,
        )

        self.tenant, self.owner = _make_tenant_with_owner('inv-mbr-cat')
        self.provider_user = _make_user('inv-mbr-cat-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)

        self.facials = ServiceCategory.objects.create(
            tenant=self.tenant, name='Facials',
        )

        def _facial(name, price):
            return Service.objects.create(
                tenant=self.tenant, category=self.facials, name=name,
                code=name.replace(' ', '')[:8].upper(),
                duration_minutes=30, buffer_minutes=0,
                price_cents=price, tax_rate_percent=Decimal('0'),
                service_type=Service.ServiceType.REGULAR,
            )

        self.basic_facial = _facial('Basic Facial', 8000)
        self.deluxe_facial = _facial('Deluxe Facial', 12000)
        # A service outside the category — must NOT be redeemable.
        self.botox = _make_service(self.tenant, name='Botox', price_cents=20000)

        # Sale invoice — closed, subscription ACTIVE.
        sale_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.basic_facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() - dt.timedelta(days=15),
        )
        self.sale_invoice = Invoice.objects.get(appointment=sale_appt)

        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Facial Club', price_cents=9000,
        )
        MembershipPlanItem.objects.create(
            plan=plan, category=self.facials, quantity_per_cycle=2,
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
            self.tenant, customer=self.customer, service=self.basic_facial,
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

    def test_sale_creates_category_subscription_item(self):
        item = self.SubscriptionItem.objects.get(subscription=self.subscription)
        self.assertIsNone(item.service_id)
        self.assertEqual(item.category_id, self.facials.pk)
        self.assertEqual(item.category_name, 'Facials')
        self.assertEqual(item.service_name, '')
        self.assertEqual(item.quantity_per_cycle, 2)
        self.assertEqual(item.quantity_remaining, 2)
        # A category credit has no fixed value — depends on what's redeemed.
        self.assertEqual(item.unit_value_cents, 0)

    def test_redeem_any_service_in_category(self):
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.deluxe_facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        item = self.SubscriptionItem.objects.get(subscription=self.subscription)
        self.assertEqual(item.quantity_remaining, 1)
        line = self.redeem_invoice.line_items.order_by('-id').first()
        self.assertEqual(line.service_id, self.deluxe_facial.pk)
        self.assertEqual(line.unit_price_cents, 0)
        self.assertIn('redeemed from membership', line.description)

    def test_redeem_service_outside_category_rejected(self):
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.botox.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_redeem_until_depleted_then_409(self):
        for svc in (self.basic_facial, self.deluxe_facial):
            response = self.client.post(
                self._redeem_url(self.redeem_invoice.pk),
                data={
                    'subscription_id': self.subscription.pk,
                    'service_id': svc.pk,
                },
                format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
            self.assertEqual(
                response.status_code, status.HTTP_200_OK, response.data,
            )
        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.basic_facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_redeem_audit_records_category_credit_kind(self):
        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.basic_facial.pk,
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
        self.assertEqual(log.metadata.get('credit_kind'), 'category')

    def test_redemption_history_shows_redeemed_service_name(self):
        self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': self.subscription.pk,
                'service_id': self.deluxe_facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = self.client.get(
            reverse('subscription-detail', kwargs={'pk': self.subscription.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        redemptions = response.data['redemptions']
        self.assertEqual(len(redemptions), 1)
        # The category item has no service_name — the history must
        # still surface the actually-redeemed service.
        self.assertEqual(redemptions[0]['service_name'], 'Deluxe Facial')
        self.assertEqual(redemptions[0]['credit_kind'], 'category')
        self.assertEqual(redemptions[0]['category_name'], 'Facials')

    def test_direct_service_credit_preferred_over_category(self):
        # A plan carrying BOTH a direct Basic-Facial credit and a
        # Facials category credit: redeeming a Basic Facial must draw
        # the direct credit first, leaving the category credit intact.
        from apps.memberships.models import (
            MembershipPlan,
            MembershipPlanItem,
            Subscription,
        )

        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Overlap Club', price_cents=15000,
        )
        MembershipPlanItem.objects.create(
            plan=plan, service=self.basic_facial, quantity_per_cycle=1,
        )
        MembershipPlanItem.objects.create(
            plan=plan, category=self.facials, quantity_per_cycle=1,
        )
        sale_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.basic_facial,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
            start=timezone.now() - dt.timedelta(days=10),
        )
        sale_invoice = Invoice.objects.get(appointment=sale_appt)
        self.client.post(
            reverse('invoice-add-line', kwargs={'pk': sale_invoice.pk}),
            data={'membership_plan_id': plan.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        sale_invoice.close(by_user=self.owner, payment_method='cash')
        sub = Subscription.objects.get(
            source_invoice_line__invoice=sale_invoice,
        )

        response = self.client.post(
            self._redeem_url(self.redeem_invoice.pk),
            data={
                'subscription_id': sub.pk,
                'service_id': self.basic_facial.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        direct = self.SubscriptionItem.objects.get(
            subscription=sub, service=self.basic_facial,
        )
        category = self.SubscriptionItem.objects.get(
            subscription=sub, category=self.facials,
        )
        self.assertEqual(direct.quantity_remaining, 0)
        self.assertEqual(category.quantity_remaining, 1)


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


# ── Email invoice to client ───────────────────────────────────────────


class InvoiceEmailTests(TestCase):
    """POST /api/invoices/{id}/email/ — send the customer their PDF.

    Gated by PROCESS_PAYMENT (owner / manager / front_desk). Customer
    must have an email on file; missing-email is a 400 with a
    structured detail. Every send writes an audit-log entry whether
    or not it succeeded so reads of "did we ever email this person?"
    survive across staff turnover.
    """

    def setUp(self):
        from django.core import mail
        mail.outbox = []

        self.tenant, self.owner = _make_tenant_with_owner('email-tenant')
        self.provider = _make_membership(
            user=_make_user('email-provider@test.local'), tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.fd_user = _make_user('email-fd@test.local')
        self.fd = _make_membership(
            user=self.fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        self.mkt_user = _make_user('email-mkt@test.local')
        self.mkt = _make_membership(
            user=self.mkt_user, tenant=self.tenant,
            role=TenantMembership.Role.MARKETING,
        )
        self.customer = _make_customer(self.tenant)
        self.customer.email = 'pat-recipient@test.local'
        self.customer.save(update_fields=['email'])

        self.service = _make_service(self.tenant, price_cents=15000, tax='0')
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)

        self.client = APIClient()
        self.client.force_login(self.owner)

    def _email_url(self, pk: int) -> str:
        return reverse('invoice-email', args=[pk])

    def test_owner_sends_email_to_customer(self):
        from django.core import mail
        response = self.client.post(
            self._email_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['recipient'], 'pat-recipient@test.local')
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['pat-recipient@test.local'])
        self.assertIn(self.invoice.invoice_number, sent.subject)
        self.assertIn(self.tenant.name, sent.subject)
        # Plain-text body + HTML alternative + PDF attachment.
        self.assertIn(self.invoice.invoice_number, sent.body)
        self.assertEqual(len(sent.attachments), 1)
        filename, content, mimetype = sent.attachments[0]
        self.assertTrue(filename.endswith('.pdf'))
        self.assertEqual(mimetype, 'application/pdf')
        self.assertTrue(content.startswith(b'%PDF-'))

    def test_front_desk_can_email(self):
        from django.core import mail
        c = APIClient()
        c.force_login(self.fd_user)
        response = c.post(
            self._email_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

    def test_marketing_blocked(self):
        from django.core import mail
        c = APIClient()
        c.force_login(self.mkt_user)
        response = c.post(
            self._email_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(len(mail.outbox), 0)

    def test_anonymous_blocked(self):
        from django.core import mail
        c = APIClient()
        response = c.post(
            self._email_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(len(mail.outbox), 0)

    def test_customer_with_no_email_returns_400(self):
        from django.core import mail
        self.customer.email = ''
        self.customer.save(update_fields=['email'])

        response = self.client.post(
            self._email_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data['detail'].lower())
        self.assertEqual(len(mail.outbox), 0)

        # Audit log captures the failed attempt so it's not silent.
        log = AuditLog.objects.filter(
            resource_type='invoice_email',
            resource_id=str(self.invoice.pk),
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('outcome'), 'failed_missing_email')

    def test_cross_tenant_returns_404(self):
        other_tenant, other_owner = _make_tenant_with_owner('email-other-tenant')
        c = APIClient()
        c.force_login(other_owner)
        response = c.post(
            self._email_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=other_tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_successful_send_writes_audit_log(self):
        self.client.post(
            self._email_url(self.invoice.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='invoice_email',
            resource_id=str(self.invoice.pk),
            action=AuditLog.Action.UPDATE,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('outcome'), 'sent')
        self.assertEqual(log.metadata.get('recipient'), 'pat-recipient@test.local')

    def test_each_send_is_a_fresh_email(self):
        from django.core import mail
        # No deduplication — each click sends another email.
        self.client.post(self._email_url(self.invoice.pk), HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.client.post(self._email_url(self.invoice.pk), HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(len(mail.outbox), 2)


# ── Standalone invoice creation (walk-in sale) ──────────────────────────


class StandaloneInvoiceCreateTests(TestCase):
    """`POST /api/invoices/create-standalone/` — the walk-in sale flow:
    open a blank invoice for a customer with no appointment."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('standalone-inv')
        self.customer = _make_customer(self.tenant)
        self.url = reverse('invoice-create-standalone')

    def _post(self, user, customer_id):
        client = APIClient()
        client.force_login(user)
        return client.post(
            self.url, data={'customer_id': customer_id}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_owner_creates_blank_open_standalone_invoice(self):
        resp = self._post(self.owner, self.customer.id)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        invoice = Invoice.objects.get(pk=resp.data['id'])
        self.assertEqual(invoice.status, Invoice.Status.OPEN)
        self.assertIsNone(invoice.appointment)
        self.assertEqual(invoice.customer_id, self.customer.id)
        self.assertEqual(invoice.line_items.count(), 0)
        self.assertTrue(invoice.invoice_number)

    def test_unknown_customer_rejected(self):
        resp = self._post(self.owner, 999999)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('customer_id', resp.data)

    def test_customer_from_another_tenant_rejected(self):
        other_tenant, _ = _make_tenant_with_owner('standalone-other')
        foreign = _make_customer(other_tenant)
        resp = self._post(self.owner, foreign.id)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_role_without_process_payment_denied(self):
        mkt_user = _make_user('mkt-standalone@test.local')
        _make_membership(
            user=mkt_user, tenant=self.tenant,
            role=TenantMembership.Role.MARKETING,
        )
        resp = self._post(mkt_user, self.customer.id)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_creation_writes_audit_log(self):
        resp = self._post(self.owner, self.customer.id)
        log = (
            AuditLog.objects
            .filter(
                resource_type='invoice',
                resource_id=str(resp.data['id']),
                action=AuditLog.Action.CREATE,
            )
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'standalone_invoice_created')


# ── Line price + discount edits (with manager override) ────────────


class InvoicePriceAndDiscountTests(TestCase):
    """Owner / manager can edit a line's unit price and add a
    per-line or invoice-level discount. Front-desk (no
    EDIT_INVOICE_PRICE) must supply an owner/manager's email +
    password as a manager override on the same request.
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('inv-price')
        # Manager who can authorize overrides. `_make_user` hardcodes
        # a password, so set a known one explicitly after create.
        self.manager_user = _make_user('mgr-price@test.local')
        self.manager_user.set_password('mgr-pw-123!')
        self.manager_user.save(update_fields=['password'])
        _make_membership(
            user=self.manager_user, tenant=self.tenant,
            role=TenantMembership.Role.MANAGER,
        )
        # Front-desk: no EDIT_INVOICE_PRICE — needs override.
        self.fd_user = _make_user('fd-price@test.local')
        self.fd_user.set_password('fd-pw-123!')
        self.fd_user.save(update_fields=['password'])
        _make_membership(
            user=self.fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        self.provider_user = _make_user('prov-price@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        # $100 service, 10% tax — so the discount/tax interplay shows up.
        self.service = _make_service(
            self.tenant, price_cents=10000, tax='10',
        )
        self.appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, status=Appointment.Status.CHECKED_IN,
            created_by=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=self.appt)
        self.line = self.invoice.line_items.first()
        self.client = APIClient()

    def _edit_line_url(self, invoice_pk, line_pk):
        return reverse(
            'invoice-edit-line',
            kwargs={'pk': invoice_pk, 'line_pk': line_pk},
        )

    def _set_discount_url(self, invoice_pk):
        return reverse(
            'invoice-set-discount', kwargs={'pk': invoice_pk},
        )

    # ── Manager / Owner direct edits ─────────────────────────────────

    def test_owner_can_edit_unit_price(self):
        self.client.force_login(self.owner)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {'unit_price_cents': 8000},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.line.refresh_from_db()
        self.assertEqual(self.line.unit_price_cents, 8000)
        self.invoice.refresh_from_db()
        # 8000 + 10% tax = 8800.
        self.assertEqual(self.invoice.subtotal_cents, 8000)
        self.assertEqual(self.invoice.tax_cents, 800)
        self.assertEqual(self.invoice.total_cents, 8800)

    def test_manager_can_set_line_discount_amount(self):
        self.client.force_login(self.manager_user)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {
                'discount_kind': 'amount',
                'discount_input': '15.00',
                'discount_reason': 'VIP regular',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.line.refresh_from_db()
        # $15 off a $100 line → 1500 cents discount, basis 8500, tax 850.
        self.assertEqual(self.line.discount_cents, 1500)
        self.assertEqual(self.line.discount_reason, 'VIP regular')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.line_discounts_total_cents, 1500)
        self.assertEqual(self.invoice.tax_cents, 850)
        # 10000 − 1500 + 850 = 9350.
        self.assertEqual(self.invoice.total_cents, 9350)

    def test_owner_can_set_line_discount_percent(self):
        self.client.force_login(self.owner)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {'discount_kind': 'percent', 'discount_input': '20'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.line.refresh_from_db()
        # 20% of $100 = $20 → 2000 cents off.
        self.assertEqual(self.line.discount_cents, 2000)
        self.invoice.refresh_from_db()
        # Basis 8000, tax 800, total = 10000 − 2000 + 800 = 8800.
        self.assertEqual(self.invoice.total_cents, 8800)

    def test_line_discount_capped_at_subtotal(self):
        """A $999 discount or 200% discount on a $100 line both cap at
        the line's subtotal — no negative line items."""
        self.client.force_login(self.owner)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {'discount_kind': 'amount', 'discount_input': '999.00'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.line.refresh_from_db()
        self.assertEqual(self.line.discount_cents, 10000)  # capped
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.total_cents, 0)

    # ── Front-desk: manager-override required ────────────────────────

    def test_front_desk_without_override_rejected(self):
        self.client.force_login(self.fd_user)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {'unit_price_cents': 8000},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('authorized_by_email', resp.data)

    def test_front_desk_with_valid_override_allowed(self):
        self.client.force_login(self.fd_user)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {
                'unit_price_cents': 8000,
                'authorized_by_email': 'mgr-price@test.local',
                'authorized_by_password': 'mgr-pw-123!',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.line.refresh_from_db()
        self.assertEqual(self.line.unit_price_cents, 8000)

    def test_front_desk_with_wrong_override_password_rejected(self):
        self.client.force_login(self.fd_user)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {
                'unit_price_cents': 8000,
                'authorized_by_email': 'mgr-price@test.local',
                'authorized_by_password': 'wrong-pw',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_front_desk_override_with_non_manager_rejected(self):
        """Even with valid creds, the authorizer must be owner/manager
        on the tenant — front-desk-A can't authorize for front-desk-B."""
        other_fd = _make_user('other-fd@test.local')
        other_fd.set_password('other-pw!')
        other_fd.save(update_fields=['password'])
        _make_membership(
            user=other_fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        self.client.force_login(self.fd_user)
        resp = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {
                'unit_price_cents': 8000,
                'authorized_by_email': 'other-fd@test.local',
                'authorized_by_password': 'other-pw!',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_override_audit_records_authorizer(self):
        self.client.force_login(self.fd_user)
        self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {
                'unit_price_cents': 8000,
                'authorized_by_email': 'mgr-price@test.local',
                'authorized_by_password': 'mgr-pw-123!',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(self.invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'line_edited')
        self.assertEqual(
            log.metadata.get('authorized_by_email'),
            'mgr-price@test.local',
        )
        self.assertEqual(log.metadata.get('before')['unit_price_cents'], 10000)
        self.assertEqual(log.metadata.get('after')['unit_price_cents'], 8000)

    # ── Invoice-level discount ──────────────────────────────────────

    def test_owner_can_set_invoice_discount_amount(self):
        self.client.force_login(self.owner)
        resp = self.client.patch(
            self._set_discount_url(self.invoice.pk),
            {
                'invoice_discount_kind': 'amount',
                'invoice_discount_input': '10.00',
                'invoice_discount_reason': 'First-visit promo',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.invoice.refresh_from_db()
        # $10 off the $100 invoice (no per-line discount). Tax 10% on
        # the $90 basis = $9. Total = 10000 − 0 − 1000 + 900 = 9900.
        self.assertEqual(self.invoice.invoice_discount_cents, 1000)
        self.assertEqual(self.invoice.tax_cents, 900)
        self.assertEqual(self.invoice.total_cents, 9900)

    def test_invoice_discount_distributed_pro_rata(self):
        # Add a 2nd line (qty=2 product at $50, no tax) so the invoice
        # has lines of different sizes — pro-rata share is meaningful.
        from apps.products.models import Product
        product = Product.objects.create(
            tenant=self.tenant, name='Cream', sku='CR',
            price_cents=5000, tax_rate_percent=Decimal('0'),
            track_inventory=False, stock_quantity=0,
        )
        self.client.force_login(self.owner)
        self.client.post(
            reverse('invoice-add-line', kwargs={'pk': self.invoice.pk}),
            data={'product_id': product.pk, 'quantity': 2},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Subtotal: $100 service + $100 product = $200. No line discounts.
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.subtotal_cents, 20000)

        # Apply $40 invoice-level discount. Pro-rata across $100/$100 →
        # $20 share each.
        self.client.patch(
            self._set_discount_url(self.invoice.pk),
            {'invoice_discount_kind': 'amount', 'invoice_discount_input': '40.00'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.invoice_discount_cents, 4000)
        # Per-line shares.
        lines = list(self.invoice.line_items.order_by('id'))
        self.assertEqual(lines[0].invoice_discount_share_cents, 2000)
        self.assertEqual(lines[1].invoice_discount_share_cents, 2000)
        # Tax: service line basis $80 × 10% = $8. Product line tax 0.
        self.assertEqual(self.invoice.tax_cents, 800)
        # Total: 20000 − 0 − 4000 + 800 = 16800.
        self.assertEqual(self.invoice.total_cents, 16800)

    def test_invoice_discount_capped_at_subtotal(self):
        self.client.force_login(self.owner)
        resp = self.client.patch(
            self._set_discount_url(self.invoice.pk),
            {'invoice_discount_kind': 'amount', 'invoice_discount_input': '999.00'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.invoice.refresh_from_db()
        # Capped at $100 (subtotal); total = 0.
        self.assertEqual(self.invoice.invoice_discount_cents, 10000)
        self.assertEqual(self.invoice.total_cents, 0)

    def test_invoice_discount_can_be_cleared(self):
        self.client.force_login(self.owner)
        # First set $10 off.
        self.client.patch(
            self._set_discount_url(self.invoice.pk),
            {'invoice_discount_kind': 'amount', 'invoice_discount_input': '10.00'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Then clear it.
        resp = self.client.patch(
            self._set_discount_url(self.invoice.pk),
            {'invoice_discount_input': '0'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.invoice_discount_cents, 0)
        self.assertEqual(self.invoice.total_cents, 11000)

    # ── Paid lock ────────────────────────────────────────────────────

    def test_edits_rejected_on_paid_invoice(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.client.force_login(self.owner)
        edit = self.client.patch(
            self._edit_line_url(self.invoice.pk, self.line.pk),
            {'unit_price_cents': 8000},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(edit.status_code, 409)
        disc = self.client.patch(
            self._set_discount_url(self.invoice.pk),
            {'invoice_discount_kind': 'amount', 'invoice_discount_input': '5'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(disc.status_code, 409)


# ── Charges + Refunds nested on invoice detail (Phase 2 chunk 2.5) ─


class InvoiceChargesSerializationTests(TestCase):
    """The invoice-detail endpoint exposes Stripe Connect Charge rows
    + their nested Refund ledger so the operator UI can render a full
    payment-history timeline without a second endpoint.

    PCI safety: only last4 + brand are emitted, never the full PAN.
    Ops-only Stripe identifiers (PI / Charge ID) stay out of the
    operator-facing wire shape.
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('charges-ser')
        self.customer = _make_customer(self.tenant)
        # Build a $100 invoice directly (no appointment) so the
        # serializer fields we care about are populated without a
        # full booking fixture.
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            subtotal_cents=10_000, tax_cents=0, total_cents=10_000,
            status=Invoice.Status.OPEN,
            created_by=self.owner,
        )

        # Stand up a MerchantAccount + two Charges (one succeeded
        # with a refund, one failed) to exercise the full surface.
        from apps.payments.models import Charge, MerchantAccount, Refund
        merchant = MerchantAccount.objects.create(
            tenant=self.tenant,
            stripe_account_id='acct_charges_ser',
            charges_enabled=True, payouts_enabled=True,
            details_submitted=True,
        )
        self.succeeded_charge = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=merchant,
            amount_cents=10_000,
            fee_cents=320, net_cents=9_680,
            stripe_payment_intent_id='pi_ser_ok',
            stripe_charge_id='ch_ser_ok',
            status=Charge.Status.SUCCEEDED,
            last4='4242', brand='visa',
            refunded_cents=2_000,
            created_by=self.owner,
            initiated_via='operator',
        )
        Refund.objects.create(
            tenant=self.tenant, charge=self.succeeded_charge,
            amount_cents=2_000,
            reason='Partial refund for promo adjustment',
            stripe_refund_id='re_ser_partial',
            status=Refund.Status.SUCCEEDED,
            created_by=self.owner,
        )
        self.failed_charge = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=merchant,
            amount_cents=10_000,
            stripe_payment_intent_id='pi_ser_fail',
            status=Charge.Status.FAILED,
            failure_code='card_declined',
            failure_message='Your card was declined.',
            last4='', brand='',
            created_by=self.owner,
            initiated_via='operator',
        )
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _detail_url(self):
        return reverse('invoice-detail', args=[self.invoice.pk])

    def test_invoice_detail_includes_charges_array(self):
        resp = self.client.get(
            self._detail_url(), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('charges', resp.data)
        self.assertEqual(len(resp.data['charges']), 2)

    def test_charges_ordered_newest_first(self):
        resp = self.client.get(
            self._detail_url(), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # failed_charge was created after succeeded_charge → newer →
        # first in the ordered list.
        ids = [c['id'] for c in resp.data['charges']]
        self.assertEqual(ids, [self.failed_charge.pk, self.succeeded_charge.pk])

    def test_succeeded_charge_exposes_safe_card_descriptors(self):
        resp = self.client.get(
            self._detail_url(), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        succ = next(c for c in resp.data['charges'] if c['id'] == self.succeeded_charge.pk)
        self.assertEqual(succ['last4'], '4242')
        self.assertEqual(succ['brand'], 'visa')
        self.assertEqual(succ['status'], 'succeeded')
        self.assertEqual(succ['amount_cents'], 10_000)
        self.assertEqual(succ['fee_cents'], 320)
        self.assertEqual(succ['net_cents'], 9_680)
        self.assertEqual(succ['refunded_cents'], 2_000)
        self.assertEqual(succ['refundable_cents'], 8_000)
        self.assertFalse(succ['is_fully_refunded'])

    def test_succeeded_charge_nests_refund_ledger(self):
        resp = self.client.get(
            self._detail_url(), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        succ = next(c for c in resp.data['charges'] if c['id'] == self.succeeded_charge.pk)
        self.assertEqual(len(succ['refunds']), 1)
        refund = succ['refunds'][0]
        self.assertEqual(refund['amount_cents'], 2_000)
        self.assertEqual(refund['reason'], 'Partial refund for promo adjustment')
        self.assertEqual(refund['status'], 'succeeded')
        self.assertEqual(refund['created_by_email'], self.owner.email)

    def test_failed_charge_exposes_failure_metadata(self):
        resp = self.client.get(
            self._detail_url(), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        failed = next(c for c in resp.data['charges'] if c['id'] == self.failed_charge.pk)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['failure_code'], 'card_declined')
        self.assertEqual(failed['failure_message'], 'Your card was declined.')
        self.assertEqual(failed['refundable_cents'], 0)
        self.assertEqual(failed['refunds'], [])

    def test_invoice_with_no_charges_returns_empty_array(self):
        # Different invoice with no charges. The empty-list shape is
        # what the frontend renders the "no payment history yet" state
        # against; a missing key would crash JSX naively.
        empty = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            subtotal_cents=5_000, tax_cents=0, total_cents=5_000,
            status=Invoice.Status.OPEN,
        )
        resp = self.client.get(
            reverse('invoice-detail', args=[empty.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['charges'], [])

    def test_stripe_internal_ids_NOT_exposed_to_operator(self):
        # PI / Charge IDs are ops-only — surfaced in /platform/tenants
        # detail for reconciliation, never on the operator surface.
        resp = self.client.get(
            self._detail_url(), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        for charge in resp.data['charges']:
            self.assertNotIn('stripe_payment_intent_id', charge)
            self.assertNotIn('stripe_charge_id', charge)


# ── Apply planned credit (one-click checkout) ───────────────────────


class ApplyPlannedCreditTests(TestCase):
    """`POST /api/invoices/<id>/apply-planned-credit/` redeems the credit
    the booking already chose (Appointment.planned_*_item): it decrements
    the credit at checkout, adds a $0 redemption line, links the ledger
    to the appointment, and clears the intent so it can't double-apply."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('inv-planned')
        self.prov_user = _make_user('inv-planned-prov@test.local')
        self.provider = _make_membership(
            user=self.prov_user, tenant=self.tenant,
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
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _url(self):
        return reverse('invoice-apply-planned-credit', kwargs={'pk': self.invoice.pk})

    def _post(self):
        return self.client.post(
            self._url(), data={}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def _make_package_item(self, *, customer=None, remaining=3):
        from apps.packages.models import PurchasedPackage, PurchasedPackageItem
        pp = PurchasedPackage.objects.create(
            tenant=self.tenant, customer=customer or self.customer,
            name='3x Botox', status=PurchasedPackage.Status.ACTIVE,
            purchased_at=timezone.now(),
        )
        return PurchasedPackageItem.objects.create(
            purchased_package=pp, service=self.service,
            service_name=self.service.name, quantity_purchased=3,
            quantity_remaining=remaining,
            unit_value_cents=self.service.price_cents,
        )

    def _plan_package(self, item):
        self.appt.planned_package_item = item
        self.appt.save(update_fields=['planned_package_item'])

    def test_apply_decrements_adds_zero_line_and_clears_intent(self):
        item = self._make_package_item(remaining=3)
        self._plan_package(item)
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        item.refresh_from_db()
        self.assertEqual(item.quantity_remaining, 2)
        line = self.invoice.line_items.order_by('-id').first()
        self.assertEqual(line.unit_price_cents, 0)
        self.assertEqual(line.service_id, self.service.pk)
        self.appt.refresh_from_db()
        self.assertIsNone(self.appt.planned_package_item_id)

    def test_apply_is_idempotent(self):
        item = self._make_package_item(remaining=2)
        self._plan_package(item)
        self.assertEqual(self._post().status_code, status.HTTP_200_OK)
        # Second call: intent already cleared → 400, no further decrement.
        self.assertEqual(self._post().status_code, status.HTTP_400_BAD_REQUEST)
        item.refresh_from_db()
        self.assertEqual(item.quantity_remaining, 1)

    def test_no_planned_credit_returns_400(self):
        self.assertEqual(self._post().status_code, status.HTTP_400_BAD_REQUEST)

    def test_blocked_on_non_open_invoice(self):
        item = self._make_package_item()
        self._plan_package(item)
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.assertEqual(self._post().status_code, status.HTTP_409_CONFLICT)
