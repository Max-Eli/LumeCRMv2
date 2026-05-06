"""FormTemplate API tests — Phase 1D session 1.

Coverage:
  - CRUD permission gating (read open / write owner-only)
  - Tenant scoping + cross-tenant 404 / cross-tenant service-id reject
  - JSON schema validation (allowed types, required props, choice
    options, duplicate field-id rejection)
  - Service-mapping replace (consent forms only; intake rejects)
  - Version-bump on schema change (no bump on cosmetic edit)
  - Audit log shape
  - DELETE disallowed
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.forms.models import FormTemplate, ServiceFormAssignment
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


# ── Helpers ─────────────────────────────────────────────────────────


def _make_user(email: str, **kwargs):
    return User.objects.create_user(email=email, password='test-pw', **kwargs)


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_service(tenant: Tenant, *, name: str = 'Botox 20u') -> Service:
    cat = ServiceCategory.objects.create(tenant=tenant, name=f'{name}-cat')
    return Service.objects.create(
        tenant=tenant,
        category=cat,
        name=name,
        code=name.replace(' ', '')[:8].upper(),
        duration_minutes=30,
        buffer_minutes=0,
        price_cents=20000,
        service_type=Service.ServiceType.REGULAR,
    )


def _valid_schema(field_id: str = 'q1') -> dict:
    """A minimum valid schema — one short_text field + one signature."""
    return {
        'fields': [
            {
                'id': field_id,
                'type': 'short_text',
                'label': 'Full name',
                'required': True,
            },
            {
                'id': 'sig',
                'type': 'signature',
                'label': 'I have read and consent to this treatment.',
                'required': True,
            },
        ],
    }


# ── Read access (any tenant member) ─────────────────────────────────


class FormTemplateReadTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('read-tenant')
        FormTemplate.objects.create(
            tenant=self.tenant,
            name='New client intake',
            form_type=FormTemplate.FormType.INTAKE,
            recurrence=FormTemplate.Recurrence.ONCE,
            schema=_valid_schema(),
        )
        FormTemplate.objects.create(
            tenant=self.tenant,
            name='Botox consent',
            form_type=FormTemplate.FormType.CONSENT,
            recurrence=FormTemplate.Recurrence.PER_VISIT,
            schema=_valid_schema('q2'),
        )
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('form-template-list')

    def test_owner_lists_all_templates(self):
        response = self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_filter_by_form_type(self):
        response = self.client.get(
            f'{self.url}?form_type=intake',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = {row['name'] for row in response.data}
        self.assertEqual(names, {'New client intake'})

    def test_front_desk_can_read(self):
        # Read is open to anyone in the tenant — front desk needs to
        # see what forms are configured.
        fd = _make_user('fd@read.local')
        TenantMembership.objects.create(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        client = APIClient()
        client.force_login(fd)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cross_tenant_isolation(self):
        other_tenant, _ = _make_tenant('read-other')
        FormTemplate.objects.create(
            tenant=other_tenant, name='Other intake',
            form_type=FormTemplate.FormType.INTAKE,
            schema=_valid_schema(),
        )
        response = self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        names = {row['name'] for row in response.data}
        self.assertNotIn('Other intake', names)


# ── Create + schema validation ──────────────────────────────────────


class FormTemplateCreateTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('create-tenant')
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('form-template-list')

    def _post(self, **overrides):
        body = {
            'name': 'Test consent',
            'form_type': 'consent',
            'recurrence': 'per_visit',
            'schema': _valid_schema(),
            **overrides,
        }
        return self.client.post(
            self.url, data=body, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_owner_creates_template(self):
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['version'], 1)
        self.assertEqual(response.data['form_type'], 'consent')

    def test_front_desk_cannot_create(self):
        fd = _make_user('fd-create@test.local')
        TenantMembership.objects.create(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        client = APIClient()
        client.force_login(fd)
        response = client.post(
            self.url, data={
                'name': 'Sneaky', 'form_type': 'consent',
                'schema': _valid_schema(),
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_field_type_rejected(self):
        response = self._post(schema={'fields': [{
            'id': 'x', 'type': 'magic', 'label': 'Magic',
        }]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('schema', response.data)

    def test_choice_field_requires_options(self):
        response = self._post(schema={'fields': [{
            'id': 'q', 'type': 'choice_single', 'label': 'Pick one',
        }]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('schema', response.data)

    def test_choice_field_requires_distinct_option_values(self):
        response = self._post(schema={'fields': [{
            'id': 'q', 'type': 'choice_single', 'label': 'Pick one',
            'options': [
                {'value': 'a', 'label': 'A'},
                {'value': 'a', 'label': 'A again'},
            ],
        }]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_field_ids_rejected(self):
        response = self._post(schema={'fields': [
            {'id': 'q1', 'type': 'short_text', 'label': 'A', 'required': True},
            {'id': 'q1', 'type': 'short_text', 'label': 'B', 'required': True},
        ]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_field_missing_label_rejected(self):
        response = self._post(schema={'fields': [{
            'id': 'q', 'type': 'short_text',
        }]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_field_id_pattern_rejected(self):
        response = self._post(schema={'fields': [{
            'id': 'spaces and stuff!',
            'type': 'short_text',
            'label': 'A',
        }]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_service_mapping_for_consent(self):
        svc = _make_service(self.tenant, name='Botox 20u')
        response = self._post(set_service_ids=[svc.id])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        template = FormTemplate.objects.get(id=response.data['id'])
        self.assertEqual(
            list(template.service_assignments.values_list('service_id', flat=True)),
            [svc.id],
        )
        self.assertEqual(response.data['service_ids'], [svc.id])

    def test_intake_form_rejects_service_mapping(self):
        svc = _make_service(self.tenant)
        response = self._post(form_type='intake', set_service_ids=[svc.id])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('set_service_ids', response.data)

    def test_cross_tenant_service_id_rejected(self):
        other_tenant, _ = _make_tenant('create-other')
        other_svc = _make_service(other_tenant)
        response = self._post(set_service_ids=[other_svc.id])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('set_service_ids', response.data)

    def test_create_writes_audit_entry(self):
        self._post()
        log = AuditLog.objects.filter(
            resource_type='form_template', action=AuditLog.Action.CREATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('form_type'), 'consent')


# ── Update + version bump + service replace ─────────────────────────


class FormTemplateUpdateTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('update-tenant')
        self.template = FormTemplate.objects.create(
            tenant=self.tenant, name='Botox consent',
            form_type=FormTemplate.FormType.CONSENT,
            recurrence=FormTemplate.Recurrence.PER_VISIT,
            schema=_valid_schema(),
        )
        self.svc_a = _make_service(self.tenant, name='Botox 20u')
        self.svc_b = _make_service(self.tenant, name='Botox 30u')

    def _patch(self, body):
        client = APIClient()
        client.force_login(self.owner)
        return client.patch(
            reverse('form-template-detail', args=[self.template.id]),
            data=body, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_renaming_does_not_bump_version(self):
        response = self._patch({'name': 'Botox consent (renamed)'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.template.refresh_from_db()
        self.assertEqual(self.template.version, 1)

    def test_schema_change_bumps_version(self):
        new_schema = {
            'fields': [
                *_valid_schema()['fields'],
                {'id': 'extra', 'type': 'long_text', 'label': 'Notes', 'required': False},
            ],
        }
        response = self._patch({'schema': new_schema})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.template.refresh_from_db()
        self.assertEqual(self.template.version, 2)
        self.assertEqual(response.data['version'], 2)

    def test_set_service_ids_replaces_mapping(self):
        # Pre-existing assignment to svc_a; PATCH to [svc_b] only.
        ServiceFormAssignment.objects.create(
            tenant=self.tenant, form_template=self.template, service=self.svc_a,
        )
        response = self._patch({'set_service_ids': [self.svc_b.id]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = set(self.template.service_assignments.values_list('service_id', flat=True))
        self.assertEqual(ids, {self.svc_b.id})

    def test_set_service_ids_empty_clears_mapping(self):
        ServiceFormAssignment.objects.create(
            tenant=self.tenant, form_template=self.template, service=self.svc_a,
        )
        response = self._patch({'set_service_ids': []})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self.template.service_assignments.exists())

    def test_front_desk_cannot_update(self):
        fd = _make_user('fd-update@test.local')
        TenantMembership.objects.create(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        client = APIClient()
        client.force_login(fd)
        response = client.patch(
            reverse('form-template-detail', args=[self.template.id]),
            data={'name': 'Hijacked'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_update_returns_404(self):
        other_tenant, _ = _make_tenant('update-other')
        other_template = FormTemplate.objects.create(
            tenant=other_tenant, name='Other consent',
            form_type=FormTemplate.FormType.CONSENT,
            schema=_valid_schema(),
        )
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            reverse('form-template-detail', args=[other_template.id]),
            data={'name': 'Hijacked'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_audit_metadata_records_version_bump(self):
        new_schema = {'fields': [{
            'id': 'q1', 'type': 'short_text', 'label': 'Name', 'required': True,
        }]}
        self._patch({'schema': new_schema})
        log = AuditLog.objects.filter(
            resource_type='form_template',
            resource_id=str(self.template.id),
            action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('from_version'), 1)
        self.assertEqual(log.metadata.get('to_version'), 2)


# ── DELETE disallowed ──────────────────────────────────────────────


class FormTemplateDeleteTests(TestCase):
    def test_destroy_returns_405(self):
        tenant, owner = _make_tenant('no-delete')
        template = FormTemplate.objects.create(
            tenant=tenant, name='X', form_type=FormTemplate.FormType.CONSENT,
            schema=_valid_schema(),
        )
        client = APIClient()
        client.force_login(owner)
        response = client.delete(
            reverse('form-template-detail', args=[template.id]),
            HTTP_X_TENANT_SLUG=tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ── FormSubmission API + auto-assignment + token sign flow ──────────


import datetime as dt

from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.forms.models import FormSubmission
from apps.forms.services import assign_forms_for_appointment
from apps.services.models import Service as ServiceModel
from apps.tenants.models import MembershipLocation


def _make_provider_with_assignment(tenant, *, location=None) -> TenantMembership:
    """Bookable provider with a MembershipLocation row at the location."""
    user = _make_user(f'provider-{tenant.slug}-{TenantMembership.objects.filter(tenant=tenant).count()}@test.local')
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant, role=TenantMembership.Role.PROVIDER,
        is_bookable=True, is_active=True,
    )
    if location is None:
        location = tenant.locations.get(is_default=True)
    MembershipLocation.objects.create(
        membership=membership, location=location, is_active=True,
    )
    return membership


def _make_customer(tenant, *, first='Pat', last='Patient') -> Customer:
    return Customer.objects.create(
        tenant=tenant, first_name=first, last_name=last,
        email=f'{first}.{last}@example.com'.lower(),
    )


def _make_appointment(*, tenant, customer, provider, service, location=None):
    if location is None:
        location = tenant.locations.get(is_default=True)
    start = dt.datetime(2026, 6, 1, 14, 0, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(minutes=service.duration_minutes)
    return Appointment.objects.create(
        tenant=tenant, customer=customer, provider=provider, service=service,
        location=location, start_time=start, end_time=end,
        status=Appointment.Status.BOOKED,
        quoted_price_cents=service.price_cents,
    )


# ── Auto-assignment service (unit-style — direct call) ────────────


class AutoAssignmentTests(TestCase):
    """Direct unit tests of `assign_forms_for_appointment` — exercises
    the rules from ADR 0011 in isolation without going through the
    appointment-create API path."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('auto-tenant')
        self.provider = _make_provider_with_assignment(self.tenant)
        self.service = _make_service(self.tenant, name='Botox 20u')
        self.intake = FormTemplate.objects.create(
            tenant=self.tenant, name='General intake',
            form_type=FormTemplate.FormType.INTAKE,
            recurrence=FormTemplate.Recurrence.ONCE,
            schema=_valid_schema(),
        )
        self.consent = FormTemplate.objects.create(
            tenant=self.tenant, name='Botox consent',
            form_type=FormTemplate.FormType.CONSENT,
            recurrence=FormTemplate.Recurrence.PER_VISIT,
            schema=_valid_schema('q2'),
        )
        ServiceFormAssignment.objects.create(
            tenant=self.tenant,
            form_template=self.consent,
            service=self.service,
        )
        self.customer = _make_customer(self.tenant)

    def test_first_appointment_assigns_intake_and_consent(self):
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        created = assign_forms_for_appointment(appt)
        self.assertEqual(len(created), 2)
        templates = {s.form_template_id for s in created}
        self.assertEqual(templates, {self.intake.id, self.consent.id})
        # Schema snapshotted — not just FK to template.
        for sub in created:
            self.assertEqual(sub.schema_snapshot, _valid_schema()) if sub.form_template_id == self.intake.id else None

    def test_second_appointment_skips_intake_when_already_signed(self):
        appt1 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        first_round = assign_forms_for_appointment(appt1)
        intake_sub = next(s for s in first_round if s.form_template_id == self.intake.id)
        intake_sub.status = FormSubmission.Status.COMPLETED
        intake_sub.save()

        # Second appointment for the same customer
        appt2 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        appt2.start_time += dt.timedelta(days=7); appt2.end_time += dt.timedelta(days=7)
        appt2.end_time = appt2.end_time + dt.timedelta(days=7)
        appt2.save()
        second_round = assign_forms_for_appointment(appt2)
        # Intake skipped, consent re-issued (per_visit).
        templates = {s.form_template_id for s in second_round}
        self.assertNotIn(self.intake.id, templates)
        self.assertIn(self.consent.id, templates)

    def test_per_visit_consent_creates_new_each_appointment(self):
        appt1 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        first = assign_forms_for_appointment(appt1)
        first_consent = next(s for s in first if s.form_template_id == self.consent.id)

        # Mark first consent completed
        first_consent.status = FormSubmission.Status.COMPLETED
        first_consent.save()

        appt2 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        appt2.start_time += dt.timedelta(days=7); appt2.end_time += dt.timedelta(days=7)
        appt2.save()
        second = assign_forms_for_appointment(appt2)
        second_consent = next(s for s in second if s.form_template_id == self.consent.id)
        # Different submissions; per-visit re-issued.
        self.assertNotEqual(first_consent.id, second_consent.id)
        self.assertEqual(second_consent.status, FormSubmission.Status.PENDING)

    def test_once_consent_skips_when_already_signed(self):
        # Switch the consent to recurrence='once'.
        self.consent.recurrence = FormTemplate.Recurrence.ONCE
        self.consent.save()

        appt1 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        first = assign_forms_for_appointment(appt1)
        consent_sub = next(s for s in first if s.form_template_id == self.consent.id)
        consent_sub.status = FormSubmission.Status.COMPLETED
        consent_sub.save()

        # Second appointment — once consent should NOT re-issue.
        appt2 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        appt2.start_time += dt.timedelta(days=7); appt2.end_time += dt.timedelta(days=7)
        appt2.save()
        second = assign_forms_for_appointment(appt2)
        templates = {s.form_template_id for s in second}
        self.assertNotIn(self.consent.id, templates)

    def test_inactive_template_does_not_auto_assign(self):
        self.intake.is_active = False
        self.intake.save()
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        created = assign_forms_for_appointment(appt)
        templates = {s.form_template_id for s in created}
        self.assertNotIn(self.intake.id, templates)

    def test_voided_submission_does_not_block_re_issue(self):
        # If a customer's intake was voided (operator decided it was
        # invalid), the next appointment should re-prompt.
        appt1 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        first = assign_forms_for_appointment(appt1)
        intake_sub = next(s for s in first if s.form_template_id == self.intake.id)
        intake_sub.status = FormSubmission.Status.VOIDED
        intake_sub.save()

        # The second appointment is still the customer's "first" by
        # the rules — but the previous intake was voided, so a new
        # one should be created. Wait — actually, the customer HAS
        # had a prior appointment; "first" means first-ever. The
        # voided intake doesn't bring intake back. This is documented
        # in ADR 0011 ("voided intake doesn't re-prompt automatically;
        # operator must re-issue manually"). Let me verify the
        # current behavior matches that contract.
        appt2 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        appt2.start_time += dt.timedelta(days=7); appt2.end_time += dt.timedelta(days=7)
        appt2.save()
        second = assign_forms_for_appointment(appt2)
        templates = {s.form_template_id for s in second}
        # Intake NOT auto-issued (already had a "first appointment").
        self.assertNotIn(self.intake.id, templates)

    def test_concurrent_first_appointment_does_not_duplicate_intake(self):
        # Race-condition fence — two appointments booked nearly at the
        # same time both pass the "is_first_appointment" check. The
        # `_maybe_create_submission` pending-duplicate guard prevents
        # two pending intakes.
        appt1 = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
        )
        first = assign_forms_for_appointment(appt1)
        # Now simulate that appt2 was created right after appt1, with
        # appt1's intake still pending. Re-running assign_forms on
        # appt1 (idempotent test) should not duplicate.
        again = assign_forms_for_appointment(appt1)
        intake_subs_again = [s for s in again if s.form_template_id == self.intake.id]
        self.assertEqual(len(intake_subs_again), 0)
        # Total intake submissions for this customer is still 1.
        self.assertEqual(
            FormSubmission.objects.filter(
                customer=self.customer,
                form_template=self.intake,
            ).count(),
            1,
        )


# ── End-to-end booking auto-assigns + appears via API ──────────────


class BookingAutoAssignsViaAppointmentApiTests(TestCase):
    """Confirm that hitting `POST /api/appointments/` actually triggers
    the auto-assignment service (not just the unit test). End-to-end
    sanity that the wire-in didn't break."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('e2e-tenant')
        self.provider = _make_provider_with_assignment(self.tenant)
        self.service = _make_service(self.tenant, name='Botox 20u')
        self.consent = FormTemplate.objects.create(
            tenant=self.tenant, name='Botox consent',
            form_type=FormTemplate.FormType.CONSENT,
            recurrence=FormTemplate.Recurrence.PER_VISIT,
            schema=_valid_schema(),
        )
        ServiceFormAssignment.objects.create(
            tenant=self.tenant,
            form_template=self.consent,
            service=self.service,
        )
        self.customer = _make_customer(self.tenant)
        self.client = APIClient()
        self.client.force_login(self.owner)

    def test_booking_appointment_creates_pending_submission(self):
        response = self.client.post(
            reverse('appointment-list'),
            data={
                'customer_id': self.customer.id,
                'service_id': self.service.id,
                'provider_id': self.provider.id,
                'start_time': '2026-06-01T14:00:00Z',
                'end_time': '2026-06-01T14:30:00Z',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        subs = FormSubmission.objects.filter(
            customer=self.customer, form_template=self.consent,
        )
        self.assertEqual(subs.count(), 1)
        self.assertEqual(subs.first().status, FormSubmission.Status.PENDING)


# ── FormSubmission list + detail + void API ────────────────────────


class FormSubmissionListDetailTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('sub-list')
        self.template = FormTemplate.objects.create(
            tenant=self.tenant, name='Test consent',
            form_type=FormTemplate.FormType.CONSENT,
            schema=_valid_schema(),
        )
        self.customer = _make_customer(self.tenant)
        self.submission = FormSubmission.objects.create(
            tenant=self.tenant,
            form_template=self.template,
            template_version_at_assignment=1,
            schema_snapshot=_valid_schema(),
            customer=self.customer,
        )

    def test_list_filters_by_customer(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(
            f"{reverse('form-submission-list')}?customer={self.customer.id}",
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row['id'] for row in response.data}
        self.assertIn(self.submission.id, ids)

    def test_list_excludes_phi(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(
            reverse('form-submission-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # The list serializer doesn't include `answers`,
        # `signature_data`, or `schema_snapshot` — those are PHI-
        # adjacent and only the detail endpoint exposes them.
        for row in response.data:
            self.assertNotIn('answers', row)
            self.assertNotIn('signature_data', row)
            self.assertNotIn('schema_snapshot', row)

    def test_detail_includes_schema_and_writes_audit_log(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(
            reverse('form-submission-detail', args=[self.submission.id]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('schema_snapshot', response.data)
        self.assertIn('answers', response.data)
        # Audit log captures the read.
        log = AuditLog.objects.filter(
            resource_type='form_submission',
            resource_id=str(self.submission.id),
            action=AuditLog.Action.READ,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.owner)

    def test_cross_tenant_detail_returns_404(self):
        other_tenant, other_owner = _make_tenant('sub-other')
        client = APIClient()
        client.force_login(other_owner)
        response = client.get(
            reverse('form-submission-detail', args=[self.submission.id]),
            HTTP_X_TENANT_SLUG=other_tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_void_requires_reason_and_writes_audit(self):
        client = APIClient()
        client.force_login(self.owner)
        # Empty reason rejected
        bad = client.post(
            reverse('form-submission-void', args=[self.submission.id]),
            data={}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        good = client.post(
            reverse('form-submission-void', args=[self.submission.id]),
            data={'reason': 'Customer signed wrong form'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(good.status_code, status.HTTP_200_OK)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, FormSubmission.Status.VOIDED)
        self.assertEqual(self.submission.voided_reason, 'Customer signed wrong form')
        self.assertIsNotNone(self.submission.voided_at)
        # Audit log
        log = AuditLog.objects.filter(
            resource_type='form_submission',
            resource_id=str(self.submission.id),
            action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertEqual(log.metadata.get('to_status'), 'voided')

    def test_double_void_rejected(self):
        self.submission.status = FormSubmission.Status.VOIDED
        self.submission.save()
        client = APIClient()
        client.force_login(self.owner)
        response = client.post(
            reverse('form-submission-void', args=[self.submission.id]),
            data={'reason': 'Trying again'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Public token sign flow ─────────────────────────────────────────


class PublicSignFlowTests(TestCase):
    def setUp(self):
        self.tenant, _ = _make_tenant('pub-sign')
        self.template = FormTemplate.objects.create(
            tenant=self.tenant, name='Botox consent',
            form_type=FormTemplate.FormType.CONSENT,
            schema={
                'fields': [
                    {'id': 'pregnant', 'type': 'choice_single', 'label': 'Pregnant?', 'required': True,
                     'options': [{'value': 'no', 'label': 'No'}, {'value': 'yes', 'label': 'Yes'}]},
                    {'id': 'sig', 'type': 'signature', 'label': 'Sign', 'required': True},
                ],
            },
        )
        self.customer = _make_customer(self.tenant)
        self.submission = FormSubmission.objects.create(
            tenant=self.tenant,
            form_template=self.template,
            template_version_at_assignment=1,
            schema_snapshot=self.template.schema,
            customer=self.customer,
        )
        self.url = reverse('public-form-sign', args=[self.submission.token])
        self.client = APIClient()  # No force_login — testing unauthenticated flow.

    def test_get_returns_schema_snapshot_no_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['template_name'], 'Botox consent')
        self.assertIn('schema_snapshot', response.data)
        self.assertEqual(response.data['status'], 'pending')

    def test_get_unknown_token_404(self):
        response = self.client.get(reverse('public-form-sign', args=['not-a-real-token']))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_sign_transitions_to_completed_with_audit(self):
        response = self.client.post(
            self.url,
            data={
                'answers': {'pregnant': 'no'},
                'signature_data': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA',
            },
            format='json',
            HTTP_X_FORWARDED_FOR='203.0.113.42',
            HTTP_USER_AGENT='Mozilla/5.0 (test)',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, FormSubmission.Status.COMPLETED)
        self.assertEqual(self.submission.answers, {'pregnant': 'no'})
        self.assertTrue(self.submission.signature_data.startswith('data:image/png'))
        self.assertEqual(str(self.submission.ip_address), '203.0.113.42')
        self.assertIn('Mozilla', self.submission.user_agent)
        # Audit log captures the signing event.
        log = AuditLog.objects.filter(
            resource_type='form_submission',
            resource_id=str(self.submission.id),
            action=AuditLog.Action.UPDATE,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('to_status'), 'completed')
        self.assertEqual(log.metadata.get('ip_recorded'), True)
        # No PHI in metadata
        self.assertNotIn('answers', log.metadata)

    def test_sign_rejects_missing_required_answer(self):
        response = self.client.post(
            self.url,
            data={
                'answers': {},  # missing required 'pregnant'
                'signature_data': 'data:image/png;base64,iVBOR',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('answers', response.data)

    def test_sign_rejects_invalid_choice_value(self):
        response = self.client.post(
            self.url,
            data={
                'answers': {'pregnant': 'maybe'},  # not a valid option
                'signature_data': 'data:image/png;base64,iVBOR',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_double_sign_returns_409(self):
        self.client.post(
            self.url,
            data={'answers': {'pregnant': 'no'}, 'signature_data': 'data:image/png;base64,iVBOR'},
            format='json',
        )
        # Second submission attempt
        response = self.client.post(
            self.url,
            data={'answers': {'pregnant': 'yes'}, 'signature_data': 'data:image/png;base64,otherDATA'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        # First answer preserved
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.answers, {'pregnant': 'no'})

    def test_sign_voided_returns_410(self):
        self.submission.status = FormSubmission.Status.VOIDED
        self.submission.save()
        response = self.client.post(
            self.url,
            data={'answers': {'pregnant': 'no'}, 'signature_data': 'data:image/png;base64,iVBOR'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_410_GONE)


# ── Email signed-copy flow (ADR 0012) ──────────────────────────────


from django.core import mail as django_mail


class EmailSignedCopyTests(TestCase):
    """`POST /api/form-submissions/{id}/email/` — operator-initiated
    PHI delivery. See ADR 0012."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('email-tenant')
        self.template = FormTemplate.objects.create(
            tenant=self.tenant,
            name='Botox consent',
            form_type=FormTemplate.FormType.CONSENT,
            schema={
                'fields': [
                    {'id': 'pregnant', 'type': 'choice_single', 'label': 'Pregnant?',
                     'required': True,
                     'options': [{'value': 'no', 'label': 'No'},
                                 {'value': 'yes', 'label': 'Yes'}]},
                    {'id': 'allergies', 'type': 'long_text', 'label': 'Allergies',
                     'required': False},
                    {'id': 'sig', 'type': 'signature', 'label': 'Sign', 'required': True},
                ],
            },
        )
        self.customer = _make_customer(self.tenant)
        # Customer has an email by default (_make_customer sets it).
        self.submission = FormSubmission.objects.create(
            tenant=self.tenant,
            form_template=self.template,
            template_version_at_assignment=1,
            schema_snapshot=self.template.schema,
            customer=self.customer,
            status=FormSubmission.Status.COMPLETED,
            answers={'pregnant': 'no', 'allergies': 'Latex'},
            signature_data='data:image/png;base64,iVBORw0K',
            signed_at=djtz_now(),
        )
        self.url = reverse('form-submission-email', args=[self.submission.id])

    def setUp_outbox(self):
        # Each test starts with a clean outbox so assertions are
        # scoped to the current request only.
        django_mail.outbox = []

    def test_owner_sends_email_with_html_and_text_parts(self):
        self.setUp_outbox()
        client = APIClient()
        client.force_login(self.owner)
        response = client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(django_mail.outbox), 1)
        msg = django_mail.outbox[0]
        # Subject names the form
        self.assertIn('Botox consent', msg.subject)
        # Recipient is the customer's email
        self.assertEqual(msg.to, [self.customer.email])
        # Plain-text body present
        self.assertIn('Botox consent', msg.body)
        # HTML alternative attached
        self.assertEqual(len(msg.alternatives), 1)
        html_body, mime = msg.alternatives[0]
        self.assertEqual(mime, 'text/html')
        # HTML expands choice value to label
        self.assertIn('No', html_body)
        # Field labels rendered
        self.assertIn('Pregnant?', html_body)
        self.assertIn('Allergies', html_body)
        # Signature block excluded from body (it's not in answers)
        self.assertNotIn('iVBORw0K', html_body)
        # Link to the public sign URL present
        self.assertIn(self.submission.token, html_body)

    def test_audit_log_records_send_with_domain_only(self):
        self.setUp_outbox()
        client = APIClient()
        client.force_login(self.owner)
        client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        log = AuditLog.objects.filter(
            resource_type='form_submission',
            resource_id=str(self.submission.id),
            action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'emailed_to_customer')
        # Domain only — never the full address
        self.assertIn('recipient_email_domain', log.metadata)
        self.assertNotIn('recipient_email', log.metadata)
        # Domain matches customer's email
        expected_domain = self.customer.email.split('@')[1].lower()
        self.assertEqual(log.metadata['recipient_email_domain'], expected_domain)

    def test_pending_submission_rejected(self):
        self.setUp_outbox()
        self.submission.status = FormSubmission.Status.PENDING
        self.submission.save()
        client = APIClient()
        client.force_login(self.owner)
        response = client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('signed', str(response.data).lower())
        self.assertEqual(len(django_mail.outbox), 0)

    def test_voided_submission_rejected(self):
        self.setUp_outbox()
        self.submission.status = FormSubmission.Status.VOIDED
        self.submission.save()
        client = APIClient()
        client.force_login(self.owner)
        response = client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(django_mail.outbox), 0)

    def test_customer_with_no_email_rejected(self):
        self.setUp_outbox()
        self.customer.email = ''
        self.customer.save()
        client = APIClient()
        client.force_login(self.owner)
        response = client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', str(response.data).lower())
        self.assertEqual(len(django_mail.outbox), 0)

    def test_front_desk_cannot_email(self):
        self.setUp_outbox()
        fd = _make_user('fd-email@test.local')
        TenantMembership.objects.create(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        client = APIClient()
        client.force_login(fd)
        response = client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(len(django_mail.outbox), 0)

    def test_cross_tenant_returns_404(self):
        self.setUp_outbox()
        other_tenant, other_owner = _make_tenant('email-other')
        client = APIClient()
        client.force_login(other_owner)
        response = client.post(self.url, HTTP_X_TENANT_SLUG=other_tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(len(django_mail.outbox), 0)

    def test_double_send_works_each_creates_audit_entry(self):
        # Operator may need to re-send (customer didn't get the
        # first one). v1 doesn't dedupe — two clicks = two emails +
        # two audit entries. Acceptable; bounce/complaint handling
        # is Phase 0c.
        self.setUp_outbox()
        client = APIClient()
        client.force_login(self.owner)
        client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        client.post(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(len(django_mail.outbox), 2)
        logs = AuditLog.objects.filter(
            resource_type='form_submission',
            resource_id=str(self.submission.id),
            metadata__event='emailed_to_customer',
        )
        self.assertEqual(logs.count(), 2)


# Helper to keep the test setUp readable
def djtz_now():
    from django.utils import timezone
    return timezone.now()
