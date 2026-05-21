"""Tests for the customer portal.

Covers seven invariants:

  1. **Email enumeration resistance** — request endpoint returns
     the same 200 + body whether the email matches or not.
  2. **Magic-link single-use** — second consume of the same token
     returns 410 GONE.
  3. **Magic-link expiry** — expired tokens return 410 GONE.
  4. **Cross-tenant token rejection** — a token issued for tenant
     A is not consumable on tenant B's host.
  5. **Session middleware** — valid cookie → `request.customer`
     populated; invalid/expired/revoked cookie → anonymous.
  6. **Tenant guard on authenticated endpoints** — a session
     attached to tenant A returns 403 on tenant B's host (defense
     in depth).
  7. **Cancel rules** — only future booked/confirmed appointments
     are cancellable; past or wrong-status returns 400; cross-
     customer appointments return 404.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as djtz
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .middleware import PORTAL_SESSION_COOKIE
from .models import (
    SESSION_EXPIRY,
    SESSION_IDLE_TIMEOUT,
    CustomerPortalSession,
    CustomerPortalToken,
)

User = get_user_model()


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = User.objects.create_user(email=f'{slug}-owner@test.local', password='pw')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_customer(
    tenant: Tenant, *,
    email: str = 'pat@test.local',
    first_name: str = 'Pat',
    last_name: str = 'Patient',
) -> Customer:
    return Customer.objects.create(
        tenant=tenant,
        first_name=first_name, last_name=last_name,
        email=email, phone='+15551234567',
        status=Customer.Status.ACTIVE,
    )


def _make_provider(tenant: Tenant) -> TenantMembership:
    user = User.objects.create_user(
        email=f'p-{tenant.slug}@test.local', password='pw',
    )
    m = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.PROVIDER,
        is_bookable=True, is_active=True,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return m


def _ensure_service(tenant: Tenant) -> Service:
    """Return a default Service for the tenant, creating the
    backing ServiceCategory + Service lazily. Reused across
    `_make_appointment` calls so the unique-together constraint
    on `(tenant, name)` doesn't fire."""
    cat, _ = ServiceCategory.objects.get_or_create(
        tenant=tenant, name=f'cat-{tenant.slug}',
    )
    service, _ = Service.objects.get_or_create(
        tenant=tenant, category=cat, name='Service',
        defaults={
            'duration_minutes': 30, 'price_cents': 10000,
            'service_type': Service.ServiceType.REGULAR,
        },
    )
    return service


def _make_appointment(*, tenant, customer, provider, start: dt.datetime,
                      status: str = Appointment.Status.BOOKED) -> Appointment:
    service = _ensure_service(tenant)
    appt = Appointment.objects.create(
        tenant=tenant, customer=customer, provider=provider, service=service,
        location=tenant.locations.get(is_default=True),
        start_time=start, end_time=start + dt.timedelta(minutes=30),
        status=status,
    )
    return appt


# ── Auth flow ────────────────────────────────────────────────────────


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MagicLinkRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, _ = _make_tenant('login')
        cls.customer = _make_customer(cls.tenant, email='pat@test.local')

    def setUp(self):
        mail.outbox = []

    def test_known_email_issues_token_and_sends_email(self):
        response = APIClient().post(
            reverse('portal-auth-request-magic-link'),
            data={'email': 'pat@test.local'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CustomerPortalToken.objects.filter(customer=self.customer).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('sign-in', mail.outbox[0].subject.lower())
        # The token value lands in the email body.
        token = CustomerPortalToken.objects.get(customer=self.customer)
        self.assertIn(token.token, mail.outbox[0].body)

    def test_unknown_email_returns_same_response_no_token(self):
        response = APIClient().post(
            reverse('portal-auth-request-magic-link'),
            data={'email': 'stranger@test.local'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Same 200, same body — email enumeration defense.
        self.assertEqual(response.status_code, 200)
        self.assertIn('we just sent', response.data['detail'].lower())
        self.assertEqual(CustomerPortalToken.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_case_insensitive_email_match(self):
        response = APIClient().post(
            reverse('portal-auth-request-magic-link'),
            data={'email': 'PAT@TEST.LOCAL'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CustomerPortalToken.objects.filter(customer=self.customer).count(), 1)

    def test_inactive_customer_not_matched(self):
        self.customer.status = Customer.Status.INACTIVE
        self.customer.save(update_fields=['status'])
        response = APIClient().post(
            reverse('portal-auth-request-magic-link'),
            data={'email': 'pat@test.local'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CustomerPortalToken.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)


class MagicLinkConsumeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, _ = _make_tenant('consume')
        cls.other_tenant, _ = _make_tenant('consume-other')
        cls.customer = _make_customer(cls.tenant)

    def test_consume_valid_token_creates_session(self):
        token = CustomerPortalToken.issue(customer=self.customer)
        response = APIClient().post(
            reverse('portal-auth-consume'),
            data={'token': token.token}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email'], 'pat@test.local')
        self.assertEqual(response.data['tenant']['slug'], self.tenant.slug)
        # Token now used.
        token.refresh_from_db()
        self.assertIsNotNone(token.used_at)
        # Session row exists.
        self.assertEqual(
            CustomerPortalSession.objects.filter(customer=self.customer).count(), 1,
        )
        # Cookie set on response.
        self.assertIn(PORTAL_SESSION_COOKIE, response.cookies)

    def test_consume_twice_returns_gone(self):
        token = CustomerPortalToken.issue(customer=self.customer)
        client = APIClient()
        first = client.post(
            reverse('portal-auth-consume'),
            data={'token': token.token}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(first.status_code, 200)
        second = client.post(
            reverse('portal-auth-consume'),
            data={'token': token.token}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(second.status_code, 410)

    def test_consume_expired_token_returns_gone(self):
        token = CustomerPortalToken.issue(customer=self.customer)
        token.expires_at = djtz.now() - dt.timedelta(seconds=1)
        token.save(update_fields=['expires_at'])
        response = APIClient().post(
            reverse('portal-auth-consume'),
            data={'token': token.token}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 410)

    def test_consume_cross_tenant_rejected(self):
        # Token issued for `self.customer` on `self.tenant` — try to
        # consume it under `self.other_tenant`'s host.
        token = CustomerPortalToken.issue(customer=self.customer)
        response = APIClient().post(
            reverse('portal-auth-consume'),
            data={'token': token.token}, format='json',
            HTTP_X_TENANT_SLUG=self.other_tenant.slug,
        )
        self.assertEqual(response.status_code, 410)


# ── Authenticated endpoints ──────────────────────────────────────────


class _PortalAuthenticatedTestCase(TestCase):
    """Shared base: signs the test client in as a portal customer
    using a valid session cookie. Subclasses get `self.client_with_session`
    pre-authed to `self.customer`."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, _ = _make_tenant('auth')
        cls.customer = _make_customer(cls.tenant)
        cls.provider = _make_provider(cls.tenant)

    def _portal_client(self, customer=None) -> APIClient:
        c = customer or self.customer
        session = CustomerPortalSession.issue(customer=c)
        client = APIClient()
        client.cookies[PORTAL_SESSION_COOKIE] = session.token
        return client

    def setUp(self):
        self.client_with_session = self._portal_client()


class PortalMeTests(_PortalAuthenticatedTestCase):
    def test_me_returns_customer_and_tenant(self):
        response = self.client_with_session.get(
            reverse('portal-me'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email'], 'pat@test.local')
        self.assertEqual(response.data['tenant']['primary_color'], self.tenant.primary_color)

    def test_me_requires_auth(self):
        response = APIClient().get(
            reverse('portal-me'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (401, 403))

    def test_me_patch_updates_marketing_consents(self):
        response = self.client_with_session.patch(
            reverse('portal-me'),
            data={'sms_marketing_opt_in': True, 'phone': '+15559998888'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.sms_marketing_opt_in)
        self.assertEqual(self.customer.phone, '+15559998888')
        # Consent timestamp + source captured.
        self.assertIsNotNone(self.customer.sms_marketing_consent_at)
        self.assertEqual(self.customer.sms_marketing_consent_source, 'portal')

    def test_cross_tenant_session_rejected(self):
        # Mint a session for our customer/tenant, but hit it from a
        # different tenant's host.
        other_tenant, _ = _make_tenant('auth-other')
        response = self.client_with_session.get(
            reverse('portal-me'),
            HTTP_X_TENANT_SLUG=other_tenant.slug,
        )
        self.assertEqual(response.status_code, 403)


class PortalAppointmentsTests(_PortalAuthenticatedTestCase):
    def test_list_returns_only_own_appointments(self):
        future = djtz.now() + dt.timedelta(days=2)
        past = djtz.now() - dt.timedelta(days=2)
        my_future = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=future,
        )
        my_past = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=past, status=Appointment.Status.COMPLETED,
        )
        # Someone else's appointment — must NOT appear.
        other_customer = _make_customer(self.tenant, email='other@test.local')
        _make_appointment(
            tenant=self.tenant, customer=other_customer,
            provider=self.provider, start=future,
        )

        response = self.client_with_session.get(
            reverse('portal-appointments'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        ids = [row['id'] for row in response.data]
        self.assertIn(my_future.id, ids)
        self.assertIn(my_past.id, ids)
        self.assertEqual(len(ids), 2)

    def test_cancel_future_booked_succeeds(self):
        future = djtz.now() + dt.timedelta(days=2)
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=future,
        )
        response = self.client_with_session.post(
            reverse('portal-appointment-cancel', kwargs={'pk': appt.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200, response.data)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)
        self.assertEqual(appt.cancelled_reason, 'cancelled_by_customer')

    def test_cancel_past_appointment_rejected(self):
        past = djtz.now() - dt.timedelta(days=2)
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=past,
        )
        response = self.client_with_session.post(
            reverse('portal-appointment-cancel', kwargs={'pk': appt.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.BOOKED)

    def test_cancel_other_customer_appointment_404(self):
        other_customer = _make_customer(self.tenant, email='other@test.local')
        future = djtz.now() + dt.timedelta(days=2)
        appt = _make_appointment(
            tenant=self.tenant, customer=other_customer,
            provider=self.provider, start=future,
        )
        response = self.client_with_session.post(
            reverse('portal-appointment-cancel', kwargs={'pk': appt.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 404)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.BOOKED)


class PortalLogoutTests(_PortalAuthenticatedTestCase):
    def test_logout_revokes_session(self):
        # Mint a session via the helper, then hit logout.
        # Look up the session token from the client's cookie.
        token = self.client_with_session.cookies[PORTAL_SESSION_COOKIE].value
        session = CustomerPortalSession.objects.get(token=token)

        response = self.client_with_session.post(
            reverse('portal-auth-logout'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertIsNotNone(session.revoked_at)

        # Subsequent request with the same cookie is anonymous.
        response = self.client_with_session.get(
            reverse('portal-me'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (401, 403))


class SessionExpiryTests(_PortalAuthenticatedTestCase):
    def test_idle_timeout_invalidates_session(self):
        token = self.client_with_session.cookies[PORTAL_SESSION_COOKIE].value
        session = CustomerPortalSession.objects.get(token=token)
        # Back-date `last_seen_at` past the idle window.
        CustomerPortalSession.objects.filter(pk=session.pk).update(
            last_seen_at=djtz.now() - SESSION_IDLE_TIMEOUT - dt.timedelta(minutes=1),
        )
        response = self.client_with_session.get(
            reverse('portal-me'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (401, 403))

    def test_absolute_expiry_invalidates_session(self):
        token = self.client_with_session.cookies[PORTAL_SESSION_COOKIE].value
        session = CustomerPortalSession.objects.get(token=token)
        CustomerPortalSession.objects.filter(pk=session.pk).update(
            expires_at=djtz.now() - dt.timedelta(seconds=1),
        )
        response = self.client_with_session.get(
            reverse('portal-me'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (401, 403))


# ── Memberships / Packages / Forms read views ──────────────────────


class PortalMembershipsTests(_PortalAuthenticatedTestCase):
    def test_list_returns_only_own_subscriptions(self):
        from decimal import Decimal

        from apps.invoices.models import Invoice, InvoiceLineItem
        from apps.memberships.models import MembershipPlan, Subscription

        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Gold', price_cents=10000,
            billing_interval=MembershipPlan.BillingInterval.MONTHLY,
        )
        inv = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=Invoice.Status.OPEN,
        )
        line = InvoiceLineItem.objects.create(
            invoice=inv, description='Gold',
            quantity=1, unit_price_cents=10000, tax_rate_percent=Decimal('0'),
        )
        Subscription.objects.create(
            tenant=self.tenant, customer=self.customer, plan=plan,
            source_invoice_line=line, name='Gold',
            price_cents=10000,
            status=Subscription.Status.ACTIVE,
        )
        # Cross-tenant — must not leak.
        other_tenant, _ = _make_tenant('memb-other')
        other_customer = _make_customer(other_tenant, email='other-memb@test.local')
        other_plan = MembershipPlan.objects.create(
            tenant=other_tenant, name='Other Gold', price_cents=5000,
            billing_interval=MembershipPlan.BillingInterval.MONTHLY,
        )
        other_inv = Invoice.objects.create(
            tenant=other_tenant, customer=other_customer,
            status=Invoice.Status.OPEN,
        )
        other_line = InvoiceLineItem.objects.create(
            invoice=other_inv, description='Other Gold',
            quantity=1, unit_price_cents=5000, tax_rate_percent=Decimal('0'),
        )
        Subscription.objects.create(
            tenant=other_tenant, customer=other_customer, plan=other_plan,
            source_invoice_line=other_line, name='Other Gold',
            price_cents=5000,
            status=Subscription.Status.ACTIVE,
        )

        response = self.client_with_session.get(
            reverse('portal-memberships'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        names = [row['name'] for row in response.data]
        self.assertEqual(names, ['Gold'])

    def test_requires_auth(self):
        response = APIClient().get(
            reverse('portal-memberships'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (401, 403))


class PortalPackagesTests(_PortalAuthenticatedTestCase):
    def test_list_returns_only_own_packages_active_first(self):
        from decimal import Decimal

        from apps.invoices.models import Invoice, InvoiceLineItem
        from apps.packages.models import PurchasedPackage, PurchasedPackageItem
        from apps.services.models import Service, ServiceCategory

        cat = ServiceCategory.objects.create(tenant=self.tenant, name='Cat')
        service = Service.objects.create(
            tenant=self.tenant, category=cat, name='Facial',
            duration_minutes=30, price_cents=10000,
            service_type=Service.ServiceType.REGULAR,
        )
        inv = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=Invoice.Status.OPEN,
        )
        line = InvoiceLineItem.objects.create(
            invoice=inv, description='5x Facials',
            quantity=1, unit_price_cents=40000, tax_rate_percent=Decimal('0'),
        )
        pp_active = PurchasedPackage.objects.create(
            tenant=self.tenant, customer=self.customer,
            source_template=None, source_invoice_line=line,
            name='5x Facials', price_cents=40000,
            status=PurchasedPackage.Status.ACTIVE,
        )
        PurchasedPackageItem.objects.create(
            purchased_package=pp_active, service=service,
            service_name='Facial', quantity_purchased=5, quantity_remaining=3,
            unit_value_cents=10000,
        )

        line2 = InvoiceLineItem.objects.create(
            invoice=inv, description='3x Peels',
            quantity=1, unit_price_cents=30000, tax_rate_percent=Decimal('0'),
        )
        PurchasedPackage.objects.create(
            tenant=self.tenant, customer=self.customer,
            source_template=None, source_invoice_line=line2,
            name='3x Peels', price_cents=30000,
            status=PurchasedPackage.Status.PENDING,
        )

        other_tenant, _ = _make_tenant('pkg-other')
        other_customer = _make_customer(other_tenant, email='pkg-other@test.local')
        other_inv = Invoice.objects.create(
            tenant=other_tenant, customer=other_customer,
            status=Invoice.Status.OPEN,
        )
        other_line = InvoiceLineItem.objects.create(
            invoice=other_inv, description='Foreign',
            quantity=1, unit_price_cents=5000, tax_rate_percent=Decimal('0'),
        )
        PurchasedPackage.objects.create(
            tenant=other_tenant, customer=other_customer,
            source_template=None, source_invoice_line=other_line,
            name='Foreign', price_cents=5000,
            status=PurchasedPackage.Status.ACTIVE,
        )

        response = self.client_with_session.get(
            reverse('portal-packages'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        names = [row['name'] for row in response.data]
        self.assertEqual(names, ['5x Facials', '3x Peels'])
        active_row = response.data[0]
        self.assertEqual(active_row['items'][0]['quantity_remaining'], 3)
        self.assertEqual(active_row['items'][0]['quantity_purchased'], 5)


class PortalFormsTests(_PortalAuthenticatedTestCase):
    def test_list_returns_only_own_forms_pending_first(self):
        from apps.forms.models import FormSubmission, FormTemplate

        template = FormTemplate.objects.create(
            tenant=self.tenant, name='Intake',
            form_type=FormTemplate.FormType.INTAKE,
            schema={'fields': []},
            recurrence='one_time',
        )
        pending = FormSubmission.objects.create(
            tenant=self.tenant, form_template=template, customer=self.customer,
            template_version_at_assignment=1, schema_snapshot={'fields': []},
            status=FormSubmission.Status.PENDING,
        )
        completed = FormSubmission.objects.create(
            tenant=self.tenant, form_template=template, customer=self.customer,
            template_version_at_assignment=1, schema_snapshot={'fields': []},
            status=FormSubmission.Status.COMPLETED,
            signed_at=djtz.now(),
            answers={}, signature_data='',
        )

        other_tenant, _ = _make_tenant('forms-other')
        other_customer = _make_customer(other_tenant, email='forms-other@test.local')
        other_template = FormTemplate.objects.create(
            tenant=other_tenant, name='Foreign intake',
            form_type=FormTemplate.FormType.INTAKE,
            schema={'fields': []},
            recurrence='one_time',
        )
        FormSubmission.objects.create(
            tenant=other_tenant, form_template=other_template, customer=other_customer,
            template_version_at_assignment=1, schema_snapshot={'fields': []},
            status=FormSubmission.Status.PENDING,
        )

        response = self.client_with_session.get(
            reverse('portal-forms'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        ids = [row['id'] for row in response.data]
        self.assertEqual(ids, [pending.id, completed.id])
        self.assertEqual(response.data[0]['sign_url'], f'/sign/{pending.token}')
        self.assertIsNone(response.data[1]['sign_url'])

    def test_list_does_not_leak_answers_or_signatures(self):
        from apps.forms.models import FormSubmission, FormTemplate

        template = FormTemplate.objects.create(
            tenant=self.tenant, name='Intake',
            form_type=FormTemplate.FormType.INTAKE,
            schema={'fields': []},
            recurrence='one_time',
        )
        FormSubmission.objects.create(
            tenant=self.tenant, form_template=template, customer=self.customer,
            template_version_at_assignment=1, schema_snapshot={'fields': []},
            status=FormSubmission.Status.COMPLETED,
            signed_at=djtz.now(),
            answers={'phi_field': 'sensitive answer'},
            signature_data='base64-signature-data',
        )
        response = self.client_with_session.get(
            reverse('portal-forms'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        body = str(response.data)
        self.assertNotIn('sensitive answer', body)
        self.assertNotIn('base64-signature-data', body)
        self.assertNotIn('answers', response.data[0])
        self.assertNotIn('signature_data', response.data[0])


class PortalRescheduleTests(_PortalAuthenticatedTestCase):
    """`POST /api/portal/appointments/<id>/reschedule/` — customer
    self-reschedule. Moves a future booked/confirmed appointment to a
    new available slot for the same provider."""

    def _give_full_schedule(self):
        from apps.tenants.models import ProviderSchedule

        ml = MembershipLocation.objects.get(
            membership=self.provider,
            location=self.tenant.locations.get(is_default=True),
        )
        ProviderSchedule.objects.update_or_create(
            membership_location=ml,
            defaults={
                'weekly_hours': {
                    d: [{'start': '09:00', 'end': '17:00'}]
                    for d in (
                        'monday', 'tuesday', 'wednesday', 'thursday',
                        'friday', 'saturday', 'sunday',
                    )
                },
            },
        )

    def _first_open_slot(self, appt, on_date):
        from apps.booking.availability import compute_provider_slots

        slots = compute_provider_slots(
            provider=appt.provider, service=appt.service,
            location=appt.location, on_date=on_date,
            lead_minutes=self.tenant.online_booking_lead_minutes,
            exclude_appointment_id=appt.id,
        )
        return slots[0].start if slots else None

    def _reschedule(self, pk, start_time):
        return self.client_with_session.post(
            reverse('portal-appointment-reschedule', kwargs={'pk': pk}),
            data={'start_time': start_time},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_reschedule_to_available_slot_succeeds(self):
        self._give_full_schedule()
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=djtz.now() + dt.timedelta(days=2),
        )
        target_date = (djtz.now() + dt.timedelta(days=5)).date()
        new_start = self._first_open_slot(appt, target_date)
        self.assertIsNotNone(new_start, 'expected an open slot to test against')

        response = self._reschedule(appt.pk, new_start.isoformat())
        self.assertEqual(response.status_code, 200, response.data)
        appt.refresh_from_db()
        self.assertEqual(appt.start_time, new_start)
        # A reschedule preserves the appointment's length.
        self.assertEqual(
            appt.end_time - appt.start_time, dt.timedelta(minutes=30),
        )
        self.assertEqual(appt.status, Appointment.Status.BOOKED)

    def test_reschedule_to_unavailable_time_rejected(self):
        # No schedule for the provider → no slot is ever available.
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=djtz.now() + dt.timedelta(days=2),
        )
        response = self._reschedule(
            appt.pk, (djtz.now() + dt.timedelta(days=5)).isoformat(),
        )
        self.assertEqual(response.status_code, 400)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.BOOKED)

    def test_reschedule_past_appointment_rejected(self):
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=djtz.now() - dt.timedelta(days=2),
        )
        response = self._reschedule(
            appt.pk, (djtz.now() + dt.timedelta(days=3)).isoformat(),
        )
        self.assertEqual(response.status_code, 400)

    def test_reschedule_other_customers_appointment_404(self):
        other = _make_customer(self.tenant, email='other-resched@test.local')
        appt = _make_appointment(
            tenant=self.tenant, customer=other,
            provider=self.provider, start=djtz.now() + dt.timedelta(days=2),
        )
        response = self._reschedule(
            appt.pk, (djtz.now() + dt.timedelta(days=3)).isoformat(),
        )
        self.assertEqual(response.status_code, 404)

    def test_reschedule_cancelled_appointment_rejected(self):
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, start=djtz.now() + dt.timedelta(days=2),
            status=Appointment.Status.CANCELLED,
        )
        response = self._reschedule(
            appt.pk, (djtz.now() + dt.timedelta(days=3)).isoformat(),
        )
        self.assertEqual(response.status_code, 400)
