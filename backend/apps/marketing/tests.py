"""Tests for the marketing API — Phase 1L session 1.

Covers the four invariants that define correctness for Audiences:

  1. Permission gating — anonymous + roles without
     `VIEW_AUDIENCE_SEGMENTS` get 403.
  2. Tenant scoping — every CRUD operation respects request.tenant.
  3. Filter spec validation — unknown dimensions, type errors, and
     bound violations all reject at save time.
  4. Suppression always wins — channel-eligible count NEVER
     includes a customer with `*_marketing_suppressed_at` set, even
     if their `*_marketing_opt_in` is True.

Plus the read-only-after-use rule on Audience updates (ADR 0016 §
"Audience model").
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as djtz
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.customers.models import Customer, CustomerTag
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import (
    Audience,
    Automation,
    Campaign,
    Channel,
    MarketingSendLog,
    MarketingTemplate,
)

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


def _make_customer(
    tenant: Tenant,
    *,
    email: str = '',
    phone: str = '',
    email_marketing_opt_in: bool = False,
    sms_marketing_opt_in: bool = False,
    email_suppressed: bool = False,
    sms_suppressed: bool = False,
    tags: list[CustomerTag] | None = None,
    created_at: 'dt.datetime | None' = None,
) -> Customer:
    c = Customer.objects.create(
        tenant=tenant,
        first_name='Pat',
        last_name='Patient',
        email=email,
        phone=phone,
        email_marketing_opt_in=email_marketing_opt_in,
        sms_marketing_opt_in=sms_marketing_opt_in,
        email_marketing_suppressed_at=djtz.now() if email_suppressed else None,
        sms_marketing_suppressed_at=djtz.now() if sms_suppressed else None,
    )
    if tags:
        c.tags.set(tags)
    if created_at is not None:
        Customer.objects.filter(pk=c.pk).update(created_at=created_at)
        c.refresh_from_db()
    return c


def _make_front_desk(tenant: Tenant) -> tuple[User, TenantMembership]:
    user = _make_user(f'fd-{tenant.slug}@test.local')
    m = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.FRONT_DESK,
        is_active=True,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user, m


def _make_marketing_user(tenant: Tenant) -> tuple[User, TenantMembership]:
    user = _make_user(f'mkt-{tenant.slug}@test.local')
    m = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.MARKETING,
        is_active=True,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user, m


def _make_provider(tenant: Tenant) -> TenantMembership:
    user = _make_user(f'p-{tenant.slug}-{TenantMembership.objects.filter(tenant=tenant).count()}@test.local')
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


def _make_service(tenant: Tenant) -> Service:
    cat = ServiceCategory.objects.create(tenant=tenant, name='Cat')
    return Service.objects.create(
        tenant=tenant, category=cat, name='Service',
        duration_minutes=30, price_cents=10000,
        service_type=Service.ServiceType.REGULAR,
    )


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Permission gating ──────────────────────────────────────────────


class MarketingPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-perm')

    def test_anonymous_blocked(self):
        response = APIClient().get(
            reverse('marketing-audience-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_allowed(self):
        response = _client_for(self.owner).get(
            reverse('marketing-audience-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_marketing_role_can_create(self):
        user, _ = _make_marketing_user(self.tenant)
        response = _client_for(user).post(
            reverse('marketing-audience-list'),
            data={'name': 'Marketing-role test', 'filter_spec': {}},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


# ── Filter spec validation ──────────────────────────────────────────


class AudienceFilterValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-filter')

    def setUp(self):
        self.client = _client_for(self.owner)

    def _create(self, filter_spec):
        return self.client.post(
            reverse('marketing-audience-list'),
            data={'name': 'Test', 'filter_spec': filter_spec},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_empty_spec_accepted(self):
        response = self._create({})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_unknown_dimension_rejected(self):
        response = self._create({'made_up_filter': 7})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('made_up_filter', response.data['filter_spec'])

    def test_int_dimension_rejects_string(self):
        response = self._create({'last_visit_within_days': '30'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_int_dimension_bounds(self):
        # last_visit_within_days bounds: 1..3650
        for value in (0, -1, 99999):
            response = self._create({'last_visit_within_days': value})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tag_ids_rejects_non_list(self):
        response = self._create({'tag_ids': 7})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tag_ids_rejects_non_int_member(self):
        response = self._create({'tag_ids': [1, 'two']})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bool_dimension_rejects_string(self):
        response = self._create({'email_marketing_opt_in': 'true'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Audience list/CRUD + tenant scoping ─────────────────────────────


class AudienceCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-crud')

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_records_initial_member_count(self):
        # No customers in tenant — count is 0.
        response = self.client.post(
            reverse('marketing-audience-list'),
            data={'name': 'Empty', 'filter_spec': {}},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['last_member_count'], 0)
        self.assertIsNotNone(response.data['last_counted_at'])

    def test_list_is_tenant_scoped(self):
        Audience.objects.create(tenant=self.tenant, name='Mine', filter_spec={})

        other_tenant, _ = _make_tenant('mkt-crud-other')
        Audience.objects.create(tenant=other_tenant, name='Theirs', filter_spec={})

        response = self.client.get(
            reverse('marketing-audience-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [a['name'] for a in response.data]
        self.assertEqual(names, ['Mine'])

    def test_unique_name_per_tenant(self):
        Audience.objects.create(tenant=self.tenant, name='Promo', filter_spec={})
        response = self.client.post(
            reverse('marketing-audience-list'),
            data={'name': 'Promo', 'filter_spec': {}},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Either 400 or 500 — DB-level unique constraint will fire.
        # Django's serializer_class handling typically wraps as 400.
        self.assertNotEqual(response.status_code, status.HTTP_201_CREATED)

    def test_audit_log_on_create(self):
        self.client.post(
            reverse('marketing-audience-list'),
            data={'name': 'Audited', 'filter_spec': {'last_visit_within_days': 30}},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='audience',
            action=AuditLog.Action.CREATE,
        ).first()
        self.assertIsNotNone(log)
        self.assertIn('last_visit_within_days', log.metadata.get('filter_dimensions', []))


# ── Read-only-after-use rule ────────────────────────────────────────


class AudienceImmutabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-immut')

    def setUp(self):
        self.client = _client_for(self.owner)
        self.audience = Audience.objects.create(
            tenant=self.tenant, name='Used', filter_spec={'last_visit_within_days': 30},
        )
        # Attach a non-DRAFT campaign — that's what triggers the lock.
        template = MarketingTemplate.objects.create(
            tenant=self.tenant, name='T', channel=Channel.EMAIL,
            subject='Hi', body='Hi {{first_name}}',
        )
        Campaign.objects.create(
            tenant=self.tenant, name='C', audience=self.audience,
            template=template, channel=Channel.EMAIL,
            status=Campaign.Status.SCHEDULED,
        )

    def test_filter_edit_rejected_when_used(self):
        response = self.client.patch(
            reverse('marketing-audience-detail', kwargs={'pk': self.audience.pk}),
            data={'filter_spec': {'last_visit_within_days': 60}},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Clone it', str(response.data))

    def test_name_edit_allowed_when_used(self):
        # Cosmetic edits are fine.
        response = self.client.patch(
            reverse('marketing-audience-detail', kwargs={'pk': self.audience.pk}),
            data={'description': 'Updated desc'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_destroy_rejected_when_used(self):
        response = self.client.delete(
            reverse('marketing-audience-detail', kwargs={'pk': self.audience.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Filter execution + suppression-always-wins ──────────────────────


class AudienceFilterExecutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-exec')
        cls.tag_vip = CustomerTag.objects.create(tenant=cls.tenant, name='VIP')
        cls.tag_postpartum = CustomerTag.objects.create(tenant=cls.tenant, name='Postpartum')

        # 5 customers covering each consent + suppression combination.
        cls.c_email_consent = _make_customer(
            cls.tenant, email='a@x.com',
            email_marketing_opt_in=True,
        )
        cls.c_no_consent = _make_customer(
            cls.tenant, email='b@x.com', phone='555-2222',
            email_marketing_opt_in=False, sms_marketing_opt_in=False,
        )
        cls.c_email_suppressed = _make_customer(
            cls.tenant, email='c@x.com',
            email_marketing_opt_in=True,
            email_suppressed=True,
        )
        cls.c_sms_consent = _make_customer(
            cls.tenant, phone='555-3333',
            sms_marketing_opt_in=True,
        )
        cls.c_vip = _make_customer(
            cls.tenant, email='vip@x.com',
            email_marketing_opt_in=True,
            tags=[cls.tag_vip],
        )

    def setUp(self):
        self.client = _client_for(self.owner)
        self.audience = Audience.objects.create(
            tenant=self.tenant, name='Test', filter_spec={},
        )

    def _preview(self, audience_id: int):
        return self.client.post(
            reverse('marketing-audience-preview', kwargs={'pk': audience_id}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_total_count_unfiltered(self):
        response = self._preview(self.audience.pk)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 5 active customers in this tenant.
        self.assertEqual(response.data['total_count'], 5)

    def test_email_eligible_excludes_suppressed(self):
        response = self._preview(self.audience.pk)
        # Email-eligible: c_email_consent + c_vip = 2.
        # c_email_suppressed has opt_in=True but is suppressed → EXCLUDED.
        # c_sms_consent has no email opt-in.
        # c_no_consent has no email opt-in.
        self.assertEqual(response.data['email_eligible_count'], 2)

    def test_sms_eligible_count(self):
        response = self._preview(self.audience.pk)
        # SMS-eligible: c_sms_consent = 1 (only one with sms_marketing_opt_in=True + phone)
        self.assertEqual(response.data['sms_eligible_count'], 1)

    def test_tag_filter(self):
        self.audience.filter_spec = {'tag_ids': [self.tag_vip.pk]}
        self.audience.save()
        response = self._preview(self.audience.pk)
        self.assertEqual(response.data['total_count'], 1)
        # VIP also has email opt-in → email-eligible.
        self.assertEqual(response.data['email_eligible_count'], 1)

    def test_email_marketing_opt_in_filter(self):
        # Audience filter set to opt_in=True — narrows total to 3
        # (c_email_consent + c_email_suppressed + c_vip all have
        # email_marketing_opt_in=True). Email-eligible drops the
        # suppressed one → 2.
        self.audience.filter_spec = {'email_marketing_opt_in': True}
        self.audience.save()
        response = self._preview(self.audience.pk)
        self.assertEqual(response.data['total_count'], 3)
        self.assertEqual(response.data['email_eligible_count'], 2)


class AudienceWinBackTests(TestCase):
    """Last-visit dimensions exercise the appointments table; cover
    both directions (recent visitors + win-back targets)."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-winback')
        cls.provider = _make_provider(cls.tenant)
        cls.service = _make_service(cls.tenant)
        cls.location = cls.tenant.locations.get(is_default=True)

        # Customer A: completed appointment 10 days ago — recent.
        cls.recent = _make_customer(cls.tenant, email='recent@x.com', email_marketing_opt_in=True)
        ten_days = djtz.now() - dt.timedelta(days=10)
        Appointment.objects.create(
            tenant=cls.tenant, customer=cls.recent,
            provider=cls.provider, service=cls.service, location=cls.location,
            start_time=ten_days, end_time=ten_days + dt.timedelta(minutes=30),
            status=Appointment.Status.COMPLETED,
        )

        # Customer B: completed appointment 200 days ago — win-back target.
        cls.dormant = _make_customer(cls.tenant, email='dormant@x.com', email_marketing_opt_in=True)
        two_hundred = djtz.now() - dt.timedelta(days=200)
        Appointment.objects.create(
            tenant=cls.tenant, customer=cls.dormant,
            provider=cls.provider, service=cls.service, location=cls.location,
            start_time=two_hundred, end_time=two_hundred + dt.timedelta(minutes=30),
            status=Appointment.Status.COMPLETED,
        )

        # Customer C: never came in.
        cls.never = _make_customer(cls.tenant, email='never@x.com', email_marketing_opt_in=True)

    def setUp(self):
        self.client = _client_for(self.owner)

    def _preview_with(self, filter_spec):
        a = Audience.objects.create(tenant=self.tenant, name=str(filter_spec), filter_spec=filter_spec)
        return self.client.post(
            reverse('marketing-audience-preview', kwargs={'pk': a.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        ).data

    def test_recent_visitors_within_30_days(self):
        data = self._preview_with({'last_visit_within_days': 30})
        # Only `recent` qualifies.
        self.assertEqual(data['total_count'], 1)

    def test_win_back_more_than_90_days(self):
        data = self._preview_with({'last_visit_more_than_days': 90})
        # `dormant` (last visit 200 days ago) + `never` (no visits at all) = 2.
        self.assertEqual(data['total_count'], 2)

    def test_no_show_doesnt_count_as_visit(self):
        # Add a no-show 5 days ago for `never` — should still NOT
        # count as a visit (only COMPLETED counts).
        five_days = djtz.now() - dt.timedelta(days=5)
        Appointment.objects.create(
            tenant=self.tenant, customer=self.never,
            provider=self.provider, service=self.service, location=self.location,
            start_time=five_days, end_time=five_days + dt.timedelta(minutes=30),
            status=Appointment.Status.NO_SHOW,
        )
        data = self._preview_with({'last_visit_within_days': 30})
        # Still 1 — `recent` only.
        self.assertEqual(data['total_count'], 1)


# ── Marketing template token validator + CRUD ───────────────────────


class MarketingTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-tpl')

    def setUp(self):
        self.client = _client_for(self.owner)

    def _create(self, data: dict):
        return self.client.post(
            reverse('marketing-template-list'),
            data=data,
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_email_template_requires_unsubscribe_token(self):
        response = self._create({
            'name': 'No unsub',
            'channel': 'email',
            'subject': 'Hi {{first_name}}',
            'body': 'Hi {{first_name}} — come visit us at {{tenant_name}}!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('unsubscribe_url', str(response.data).lower())

    def test_email_template_requires_subject(self):
        response = self._create({
            'name': 'No subject',
            'channel': 'email',
            'subject': '',
            'body': 'Hi {{first_name}}. Unsubscribe: {{unsubscribe_url}}',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sms_template_rejects_subject(self):
        response = self._create({
            'name': 'SMS with subject',
            'channel': 'sms',
            'subject': 'Should be blank',
            'body': 'Hi {{first_name}}',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_token_rejected(self):
        response = self._create({
            'name': 'Bad token',
            'channel': 'email',
            'subject': 'Hi',
            'body': 'Hi {{nonexistent_field}}. {{unsubscribe_url}}',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('nonexistent_field', str(response.data))

    def test_clinical_token_explicitly_rejected(self):
        # PHI-bearing token must reject with the explanatory message.
        response = self._create({
            'name': 'PHI in body',
            'channel': 'email',
            'subject': 'Hi',
            'body': 'Re: your {{last_appointment_service}}. {{unsubscribe_url}}',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('PHI', str(response.data))

    def test_happy_path_email_template(self):
        response = self._create({
            'name': 'Welcome email',
            'channel': 'email',
            'subject': 'Welcome to {{tenant_name}}, {{first_name}}!',
            'body': (
                "Hi {{first_name}},\n\nThanks for joining {{tenant_name}}. "
                "Unsubscribe: {{unsubscribe_url}}"
            ),
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(
            sorted(response.data['discovered_tokens']),
            ['first_name', 'tenant_name', 'unsubscribe_url'],
        )

    def test_happy_path_sms_template(self):
        response = self._create({
            'name': 'Reminder',
            'channel': 'sms',
            'subject': '',
            'body': 'Hi {{first_name}}, {{tenant_name}} reminder.',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_template_preview_renders_against_sample(self):
        # Create a template, then preview it against a synthetic
        # customer (no customer_id) and verify the body is expanded.
        c = self._create({
            'name': 'Preview test',
            'channel': 'email',
            'subject': 'Hi {{first_name}}',
            'body': 'Hi {{first_name}} from {{tenant_name}}. {{unsubscribe_url}}',
        })
        template_id = c.data['id']
        response = self.client.post(
            reverse('marketing-template-preview', kwargs={'pk': template_id}),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # Synthetic sample is "Jane" (from views.MarketingTemplateViewSet.preview).
        self.assertIn('Jane', response.data['body'])
        self.assertIn(self.tenant.name, response.data['body'])
        # `unsubscribe_url` is replaced with the preview placeholder URL.
        self.assertIn('preview-token', response.data['body'])

    def test_template_unique_name_per_tenant(self):
        self._create({
            'name': 'Promo',
            'channel': 'email',
            'subject': 'Hi',
            'body': '{{unsubscribe_url}}',
        })
        response = self._create({
            'name': 'Promo',
            'channel': 'email',
            'subject': 'Hi',
            'body': '{{unsubscribe_url}}',
        })
        # 400 from the IntegrityError handler in the view.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Campaigns: CRUD + status flow ───────────────────────────────────


class CampaignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-camp')
        cls.audience = Audience.objects.create(
            tenant=cls.tenant, name='All', filter_spec={},
        )
        cls.email_template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='ETemplate',
            channel=Channel.EMAIL,
            subject='Hi', body='Hi {{first_name}}. {{unsubscribe_url}}',
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def _create_campaign(self, **overrides):
        data = {
            'name': 'May promo',
            'audience': self.audience.pk,
            'template': self.email_template.pk,
        }
        data.update(overrides)
        return self.client.post(
            reverse('marketing-campaign-list'),
            data=data,
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_create_lands_in_draft(self):
        response = self._create_campaign()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['status'], 'draft')
        self.assertEqual(response.data['channel'], 'email')

    def test_schedule_locks_recipient_count(self):
        c = self._create_campaign()
        cid = c.data['id']
        # Add a customer with email opt-in so the count > 0.
        Customer.objects.create(
            tenant=self.tenant, first_name='C', last_name='1',
            email='c1@x.com', email_marketing_opt_in=True,
        )
        response = self.client.post(
            reverse('marketing-campaign-schedule', kwargs={'pk': cid}),
            data={'send_now': True},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'scheduled')
        self.assertEqual(response.data['recipient_count_snapshot'], 1)

    def test_cant_schedule_already_scheduled(self):
        c = self._create_campaign()
        cid = c.data['id']
        self.client.post(
            reverse('marketing-campaign-schedule', kwargs={'pk': cid}),
            data={'send_now': True},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = self.client.post(
            reverse('marketing-campaign-schedule', kwargs={'pk': cid}),
            data={'send_now': True},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_from_draft(self):
        c = self._create_campaign()
        cid = c.data['id']
        response = self.client.post(
            reverse('marketing-campaign-cancel', kwargs={'pk': cid}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'cancelled')

    def test_cancel_idempotent(self):
        c = self._create_campaign()
        cid = c.data['id']
        self.client.post(
            reverse('marketing-campaign-cancel', kwargs={'pk': cid}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = self.client.post(
            reverse('marketing-campaign-cancel', kwargs={'pk': cid}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'cancelled')

    def test_update_only_allowed_in_draft(self):
        c = self._create_campaign()
        cid = c.data['id']
        # Schedule then try to PATCH name — rejected.
        self.client.post(
            reverse('marketing-campaign-schedule', kwargs={'pk': cid}),
            data={'send_now': True},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = self.client.patch(
            reverse('marketing-campaign-detail', kwargs={'pk': cid}),
            data={'name': 'Renamed'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_rejects_unwhitelisted_fields(self):
        c = self._create_campaign()
        cid = c.data['id']
        response = self.client.patch(
            reverse('marketing-campaign-detail', kwargs={'pk': cid}),
            data={'status': 'sending'},  # not in allowlist
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Automations ─────────────────────────────────────────────────────


class AutomationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-auto')
        cls.email_template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='AutoT',
            channel=Channel.EMAIL,
            subject='Hi', body='Hi {{first_name}}. {{unsubscribe_url}}',
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def _create(self, data: dict):
        return self.client.post(
            reverse('marketing-automation-list'),
            data=data,
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_birthday_create(self):
        response = self._create({
            'name': 'Birthday wishes',
            'trigger_type': 'birthday',
            'trigger_config': {},
            'template': self.email_template.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['channel'], 'email')
        self.assertFalse(response.data['is_active'])  # default off

    def test_no_visit_days_requires_days(self):
        response = self._create({
            'name': 'Win-back',
            'trigger_type': 'no_visit_days',
            'trigger_config': {},  # missing 'days'
            'template': self.email_template.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_visit_days_bounds(self):
        response = self._create({
            'name': 'Win-back too short',
            'trigger_type': 'no_visit_days',
            'trigger_config': {'days': 3},  # below min
            'template': self.email_template.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_visit_days_happy(self):
        response = self._create({
            'name': 'Win-back 90',
            'trigger_type': 'no_visit_days',
            'trigger_config': {'days': 90},
            'template': self.email_template.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_birthday_preview_finds_birthday_month_customer(self):
        # Create a customer whose birthday is this month + email opt-in.
        today = djtz.now()
        Customer.objects.create(
            tenant=self.tenant, first_name='Birthday', last_name='Person',
            email='bp@x.com',
            date_of_birth=today.date().replace(year=1985),
            email_marketing_opt_in=True,
        )
        # And one whose birthday is NEXT month (or any other month) — excluded.
        # Use day=1 so the date is always valid regardless of which month
        # we wrap to (Feb has no 29-31; April / June / Sep / Nov have no 31).
        # The original code copied today's day-of-month, which silently
        # failed on the 29th/30th/31st of months whose successor is shorter.
        other_month = today.month % 12 + 1
        Customer.objects.create(
            tenant=self.tenant, first_name='Other', last_name='Month',
            email='other@x.com',
            date_of_birth=dt.date(1985, other_month, 1),
            email_marketing_opt_in=True,
        )

        a = self._create({
            'name': 'BD',
            'trigger_type': 'birthday',
            'trigger_config': {},
            'template': self.email_template.pk,
        })
        response = self.client.post(
            reverse('marketing-automation-preview', kwargs={'pk': a.data['id']}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_count'], 1)
        self.assertEqual(response.data['final_count'], 1)

    def test_unique_name_per_tenant(self):
        self._create({
            'name': 'Dup',
            'trigger_type': 'birthday',
            'trigger_config': {},
            'template': self.email_template.pk,
        })
        response = self._create({
            'name': 'Dup',
            'trigger_type': 'birthday',
            'trigger_config': {},
            'template': self.email_template.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Public unsubscribe ──────────────────────────────────────────────


class UnsubscribeTokenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-unsub')
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Pat', last_name='Patient',
            email='pat@x.com',
            email_marketing_opt_in=True,
        )

    def _make_token(self, channel: str = 'email') -> 'UnsubscribeToken':
        from .models import UnsubscribeToken
        import secrets
        return UnsubscribeToken.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            channel=channel,
            token=secrets.token_urlsafe(32),
        )

    def test_unknown_token_404(self):
        response = APIClient().get(
            reverse('marketing-unsubscribe', kwargs={'token': 'no-such-token'}),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_returns_state_without_mutating(self):
        t = self._make_token()
        response = APIClient().get(
            reverse('marketing-unsubscribe', kwargs={'token': t.token}),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_unsubscribed'])
        # Customer's suppression flag still null.
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.email_marketing_suppressed_at)

    def test_post_flips_suppression_for_email(self):
        t = self._make_token('email')
        response = APIClient().post(
            reverse('marketing-unsubscribe', kwargs={'token': t.token}),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_unsubscribed'])
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.email_marketing_suppressed_at)
        self.assertEqual(
            self.customer.email_marketing_suppression_source,
            'unsubscribe_link',
        )
        # SMS not flipped.
        self.assertIsNone(self.customer.sms_marketing_suppressed_at)

    def test_post_idempotent(self):
        t = self._make_token('email')
        APIClient().post(
            reverse('marketing-unsubscribe', kwargs={'token': t.token}),
        )
        first_used = t.refresh_from_db() or 0
        first_at = self.customer.__class__.objects.get(pk=self.customer.pk).email_marketing_suppressed_at

        # Second POST shouldn't reset the timestamp.
        APIClient().post(
            reverse('marketing-unsubscribe', kwargs={'token': t.token}),
        )
        second_at = self.customer.__class__.objects.get(pk=self.customer.pk).email_marketing_suppressed_at
        self.assertEqual(first_at, second_at)

    def test_audit_log_records_unsubscribe(self):
        t = self._make_token('email')
        APIClient().post(
            reverse('marketing-unsubscribe', kwargs={'token': t.token}),
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='customer',
            metadata__event='unsubscribed_via_link',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('channel'), 'email')
        self.assertIsNone(log.user)  # public flow


# ── Send worker (campaign dispatch) ─────────────────────────────────


class CampaignDispatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-disp')
        cls.audience = Audience.objects.create(
            tenant=cls.tenant, name='All', filter_spec={},
        )
        cls.template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='Promo',
            channel=Channel.EMAIL,
            subject='Hi {{first_name}}',
            body='Hi {{first_name}}, check out {{tenant_name}}. {{unsubscribe_url}}',
        )
        cls.consenting = Customer.objects.create(
            tenant=cls.tenant, first_name='Cy', last_name='Consent',
            email='consent@x.com',
            email_marketing_opt_in=True,
        )
        Customer.objects.create(
            tenant=cls.tenant, first_name='Sue', last_name='Suppress',
            email='suppress@x.com',
            email_marketing_opt_in=True,
            email_marketing_suppressed_at=djtz.now(),
        )
        Customer.objects.create(
            tenant=cls.tenant, first_name='Nori', last_name='NoConsent',
            email='nope@x.com',
            email_marketing_opt_in=False,
        )

    def setUp(self):
        self.client = _client_for(self.owner)
        self.campaign = Campaign.objects.create(
            tenant=self.tenant,
            name='May promo',
            audience=self.audience,
            template=self.template,
            channel=Channel.EMAIL,
            status=Campaign.Status.SCHEDULED,
            recipient_count_snapshot=3,
        )

    def test_dispatch_sends_to_consenting_only(self):
        from .sender import dispatch_campaign
        result = dispatch_campaign(self.campaign)
        self.assertEqual(result['sent_count'], 1)
        # The audience-execute_filter pre-applies consent — only 1
        # SendLog row, for the consenting customer.
        log_count = MarketingSendLog.objects.filter(campaign=self.campaign).count()
        self.assertEqual(log_count, 1)
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, Campaign.Status.SENT)

    def test_dispatch_endpoint_callable_from_api(self):
        response = self.client.post(
            reverse('marketing-campaign-dispatch-now', kwargs={'pk': self.campaign.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'sent')

    def test_dispatch_idempotent_on_already_sent(self):
        from .sender import dispatch_campaign
        dispatch_campaign(self.campaign)
        first_count = MarketingSendLog.objects.filter(campaign=self.campaign).count()
        dispatch_campaign(self.campaign)
        second_count = MarketingSendLog.objects.filter(campaign=self.campaign).count()
        self.assertEqual(first_count, second_count)

    def test_unsubscribe_token_generated_per_send(self):
        from .sender import dispatch_campaign
        from .models import UnsubscribeToken
        dispatch_campaign(self.campaign)
        token = UnsubscribeToken.objects.filter(
            customer=self.consenting, channel=Channel.EMAIL,
        ).first()
        self.assertIsNotNone(token)
        self.assertEqual(token.source_campaign, self.campaign)


# ── Send worker (automation fire) ───────────────────────────────────


class AutomationFireTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-fire')
        cls.template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='Birthday',
            channel=Channel.EMAIL,
            subject='Happy birthday {{first_name}}!',
            body='Cheers {{first_name}}! {{unsubscribe_url}}',
        )
        today = djtz.now().date()
        cls.bd_customer = Customer.objects.create(
            tenant=cls.tenant, first_name='BD', last_name='Person',
            email='bd@x.com',
            date_of_birth=today.replace(year=1990),
            email_marketing_opt_in=True,
        )
        cls.automation = Automation.objects.create(
            tenant=cls.tenant,
            name='BD wishes',
            trigger_type=Automation.TriggerType.BIRTHDAY,
            trigger_config={},
            template=cls.template,
            channel=Channel.EMAIL,
            is_active=True,
        )

    def test_fire_creates_campaign_and_sends(self):
        from .sender import fire_automation
        result = fire_automation(self.automation)
        self.assertEqual(result['sent_count'], 1)
        self.assertIsNotNone(result['campaign_id'])
        campaign = Campaign.objects.get(pk=result['campaign_id'])
        self.assertEqual(campaign.status, Campaign.Status.SENT)
        self.assertEqual(campaign.sent_count, 1)

    def test_fire_dedupes_within_window(self):
        from .sender import fire_automation
        fire_automation(self.automation)
        result = fire_automation(self.automation)
        self.assertEqual(result['eligible_count'], 0)
        self.assertEqual(result['sent_count'], 0)

    def test_fire_endpoint_callable_from_api(self):
        client = _client_for(self.owner)
        response = client.post(
            reverse('marketing-automation-fire', kwargs={'pk': self.automation.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['sent_count'], 1)

    def test_automation_aggregates_updated_after_fire(self):
        from .sender import fire_automation
        fire_automation(self.automation)
        self.automation.refresh_from_db()
        self.assertIsNotNone(self.automation.last_run_at)
        self.assertEqual(self.automation.last_run_eligible_count, 1)
        self.assertEqual(self.automation.last_run_sent_count, 1)


# ── Booking-flow consent capture ─────────────────────────────────────


class BookingConsentCaptureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-bookc')
        cls.location = cls.tenant.locations.get(is_default=True)
        from apps.services.models import Service, ServiceCategory
        from apps.tenants.models import (
            MembershipLocation, ProviderSchedule, TenantMembership,
        )

        cat = ServiceCategory.objects.create(tenant=cls.tenant, name='C')
        cls.service = Service.objects.create(
            tenant=cls.tenant, category=cat,
            name='Service', duration_minutes=30,
            price_cents=10000, service_type=Service.ServiceType.REGULAR,
            is_active=True, is_bookable_online=True,
        )
        provider_user = User.objects.create_user(
            email='p-bookc@test.local', first_name='Sam', last_name='Provider',
            password='pw',
        )
        cls.provider = TenantMembership.objects.create(
            user=provider_user, tenant=cls.tenant,
            role=TenantMembership.Role.PROVIDER,
            is_bookable=True, is_active=True,
        )
        ml = MembershipLocation.objects.create(
            membership=cls.provider, location=cls.location, is_active=True,
        )
        ProviderSchedule.objects.create(
            membership_location=ml,
            weekly_hours={
                d: [{'start': '09:00', 'end': '17:00'}]
                for d in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
            } | {'saturday': [], 'sunday': []},
        )

    def setUp(self):
        # Clear the throttle cache so the booking-submit endpoint
        # isn't rate-limited from prior tests in the suite.
        from django.core.cache import cache
        cache.clear()

    def _book_payload(self, **overrides):
        from apps.booking.availability import compute_provider_slots
        on_date = dt.date.today() + dt.timedelta(days=14)
        while on_date.weekday() >= 5:
            on_date += dt.timedelta(days=1)
        slots = compute_provider_slots(
            provider=self.provider, service=self.service, location=self.location,
            on_date=on_date,
        )
        first = slots[0]
        base = {
            'service_id': self.service.pk,
            'provider_id': self.provider.pk,
            'location_id': self.location.pk,
            'start_time': first.start.isoformat(),
            'customer_first_name': 'Consent',
            'customer_last_name': 'Capture',
            'customer_email': 'consent@booking.test',
            'customer_phone': '555-0500',
        }
        base.update(overrides)
        return base

    def test_default_no_consent(self):
        response = APIClient().post(
            reverse('booking-submit', kwargs={'tenant_slug': self.tenant.slug}),
            data=self._book_payload(),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        c = Customer.objects.get(email='consent@booking.test')
        self.assertFalse(c.email_marketing_opt_in)
        self.assertFalse(c.sms_marketing_opt_in)
        self.assertIsNone(c.email_marketing_consent_at)

    def test_email_consent_recorded_with_source(self):
        response = APIClient().post(
            reverse('booking-submit', kwargs={'tenant_slug': self.tenant.slug}),
            data=self._book_payload(email_marketing_opt_in=True),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        c = Customer.objects.get(email='consent@booking.test')
        self.assertTrue(c.email_marketing_opt_in)
        self.assertIsNotNone(c.email_marketing_consent_at)
        self.assertEqual(c.email_marketing_consent_source, 'booking_form')

    def test_both_channels_consent(self):
        response = APIClient().post(
            reverse('booking-submit', kwargs={'tenant_slug': self.tenant.slug}),
            data=self._book_payload(
                email_marketing_opt_in=True,
                sms_marketing_opt_in=True,
            ),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        c = Customer.objects.get(email='consent@booking.test')
        self.assertTrue(c.email_marketing_opt_in)
        self.assertTrue(c.sms_marketing_opt_in)


class CustomerMarketingHistoryTests(TestCase):
    """Customer profile Marketing tab pulls from this endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-cushist')
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Pat', last_name='Profile',
            email='pat@x.com',
        )
        other_tenant, _ = _make_tenant('mkt-cushist-other')
        cls.cross_customer = Customer.objects.create(
            tenant=other_tenant, first_name='X', last_name='Other',
            email='x@x.com',
        )
        cls.audience = Audience.objects.create(
            tenant=cls.tenant, name='All', filter_spec={},
        )
        cls.template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='T', channel=Channel.EMAIL,
            subject='Hi', body='Hi {{first_name}}. {{unsubscribe_url}}',
        )
        cls.campaign = Campaign.objects.create(
            tenant=cls.tenant, name='Spring promo',
            audience=cls.audience, template=cls.template,
            channel=Channel.EMAIL, status=Campaign.Status.SENT,
        )
        # Two rows for the focus customer + one row for a different
        # tenant's customer (must not leak).
        MarketingSendLog.objects.create(
            tenant=cls.tenant, campaign=cls.campaign, customer=cls.customer,
            channel=Channel.EMAIL, status=MarketingSendLog.Status.SENT,
            recipient_email_domain='x.com',
        )
        MarketingSendLog.objects.create(
            tenant=cls.tenant, campaign=cls.campaign, customer=cls.customer,
            channel=Channel.EMAIL, status=MarketingSendLog.Status.SUPPRESSED,
            suppression_reason='no_consent',
            recipient_email_domain='x.com',
        )
        cross_campaign = Campaign.objects.create(
            tenant=other_tenant, name='Other promo',
            audience=Audience.objects.create(
                tenant=other_tenant, name='Other', filter_spec={},
            ),
            template=MarketingTemplate.objects.create(
                tenant=other_tenant, name='Other T', channel=Channel.EMAIL,
                subject='S', body='B {{unsubscribe_url}}',
            ),
            channel=Channel.EMAIL, status=Campaign.Status.SENT,
        )
        MarketingSendLog.objects.create(
            tenant=other_tenant, campaign=cross_campaign,
            customer=cls.cross_customer,
            channel=Channel.EMAIL, status=MarketingSendLog.Status.SENT,
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_returns_rows_for_customer(self):
        response = self.client.get(
            reverse('marketing-customer-sends-list')
            + f'?customer={self.customer.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data), 2)
        names = {row['campaign_name'] for row in response.data}
        self.assertIn('Spring promo', names)

    def test_other_tenant_customer_returns_empty(self):
        # Owner queries a customer ID belonging to another tenant — the
        # tenant filter scopes the queryset, so the result is empty
        # rather than leaking the other tenant's send rows.
        response = self.client.get(
            reverse('marketing-customer-sends-list')
            + f'?customer={self.cross_customer.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_missing_customer_param_400(self):
        response = self.client.get(
            reverse('marketing-customer-sends-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OperatorMarketingOptInTests(TestCase):
    """Operator flipping email/sms_marketing_opt_in on the customer
    profile Marketing tab stamps the consent_at + consent_source so
    the legal record reflects who turned it on."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-optin')
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='O', last_name='Optin',
            email='optin@x.com',
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_operator_flip_stamps_consent_metadata(self):
        response = self.client.patch(
            reverse('customer-detail', kwargs={'pk': self.customer.pk}),
            data={'email_marketing_opt_in': True},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.email_marketing_opt_in)
        self.assertIsNotNone(self.customer.email_marketing_consent_at)
        self.assertEqual(self.customer.email_marketing_consent_source, 'manual')

    def test_no_change_does_not_restamp(self):
        # When the boolean's already True, a redundant True must not
        # stomp the existing consent_at (which may be 'booking_form' +
        # an earlier timestamp).
        original = djtz.now() - dt.timedelta(days=30)
        self.customer.email_marketing_opt_in = True
        self.customer.email_marketing_consent_at = original
        self.customer.email_marketing_consent_source = 'booking_form'
        self.customer.save()

        self.client.patch(
            reverse('customer-detail', kwargs={'pk': self.customer.pk}),
            data={'email_marketing_opt_in': True},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email_marketing_consent_source, 'booking_form')
        self.assertEqual(
            self.customer.email_marketing_consent_at.replace(microsecond=0),
            original.replace(microsecond=0),
        )


# ── Campaign preview + test-send ─────────────────────────────────────


class CampaignPreviewAndTestSendTests(TestCase):
    """`POST /campaigns/<id>/preview/` returns rendered subject + body.
    `POST /campaigns/<id>/send-test/` sends a single test email.

    Both are operator verification steps before scheduling a real
    campaign. Preview is read-only; test-send writes no SendLog rows
    and doesn't touch campaign counters."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mkt-preview')
        cls.audience = Audience.objects.create(
            tenant=cls.tenant, name='All', filter_spec={},
        )
        cls.email_template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='Hello',
            channel=Channel.EMAIL,
            subject='Hi {{first_name}}',
            body='Hi {{first_name}}, welcome to {{tenant_name}}. '
                 '{{unsubscribe_url}}',
        )
        cls.sms_template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='SMS-text',
            channel=Channel.SMS,
            subject='',
            body='Hi {{first_name}}, reply STOP to opt out.',
        )

    def setUp(self):
        from django.core import mail
        mail.outbox = []
        self.client = _client_for(self.owner)

    def _create_email_campaign(self):
        response = self.client.post(
            reverse('marketing-campaign-list'),
            data={
                'name': 'preview test',
                'audience': self.audience.pk,
                'template': self.email_template.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        return response.data['id']

    def _create_sms_campaign(self):
        response = self.client.post(
            reverse('marketing-campaign-list'),
            data={
                'name': 'sms preview test',
                'audience': self.audience.pk,
                'template': self.sms_template.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        return response.data['id']

    # ── Preview ──────────────────────────────────────────────────

    def test_preview_renders_subject_and_body_with_synthetic_sample(self):
        cid = self._create_email_campaign()
        response = self.client.post(
            reverse('marketing-campaign-preview', kwargs={'pk': cid}),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # Default sample is "Jane Sample" — verifies tokens get
        # substituted without a real customer.
        self.assertIn('Jane', response.data['subject'])
        self.assertIn('Jane', response.data['body'])
        self.assertIn(self.tenant.name, response.data['body'])

    def test_preview_with_real_customer(self):
        c = Customer.objects.create(
            tenant=self.tenant, first_name='Pat', last_name='Real',
            email='pat@real.test',
        )
        cid = self._create_email_campaign()
        response = self.client.post(
            reverse('marketing-campaign-preview', kwargs={'pk': cid}),
            data={'customer_id': c.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('Pat', response.data['subject'])
        self.assertIn('Pat', response.data['body'])

    def test_preview_cross_tenant_customer_400(self):
        other_tenant, _ = _make_tenant('mkt-preview-other')
        other_customer = Customer.objects.create(
            tenant=other_tenant, first_name='X', last_name='Other', email='x@x.test',
        )
        cid = self._create_email_campaign()
        response = self.client.post(
            reverse('marketing-campaign-preview', kwargs={'pk': cid}),
            data={'customer_id': other_customer.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Test-send ────────────────────────────────────────────────

    def test_test_send_dispatches_one_email_with_test_prefix(self):
        from django.core import mail
        cid = self._create_email_campaign()
        response = self.client.post(
            reverse('marketing-campaign-send-test', kwargs={'pk': cid}),
            data={'recipient_email': 'qa@spa.test'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['recipient'], 'qa@spa.test')
        self.assertTrue(response.data['subject'].startswith('[TEST] '))
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['qa@spa.test'])
        self.assertTrue(sent.subject.startswith('[TEST] '))
        # Synthetic sample's first_name = 'Jane'
        self.assertIn('Jane', sent.body)

    def test_test_send_writes_no_send_log(self):
        from apps.marketing.models import MarketingSendLog
        cid = self._create_email_campaign()
        self.client.post(
            reverse('marketing-campaign-send-test', kwargs={'pk': cid}),
            data={'recipient_email': 'qa@spa.test'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(MarketingSendLog.objects.filter(campaign_id=cid).count(), 0)

    def test_test_send_rejects_missing_recipient(self):
        cid = self._create_email_campaign()
        response = self.client.post(
            reverse('marketing-campaign-send-test', kwargs={'pk': cid}),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_test_send_rejects_sms_campaigns_for_now(self):
        # SMS test-send returns 400 with a clear message until Twilio
        # is wired (Phase 1L session 3).
        cid = self._create_sms_campaign()
        response = self.client.post(
            reverse('marketing-campaign-send-test', kwargs={'pk': cid}),
            data={'recipient_email': 'qa@spa.test'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email-only', response.data['detail'].lower())

    def test_test_send_writes_audit_log(self):
        from apps.audit.models import AuditLog
        cid = self._create_email_campaign()
        self.client.post(
            reverse('marketing-campaign-send-test', kwargs={'pk': cid}),
            data={'recipient_email': 'qa@spa.test'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='marketing_campaign',
            resource_id=str(cid),
            metadata__event='test_send_sent',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('recipient_domain'), 'spa.test')


# ── Twilio SMS dispatch + status callback ────────────────────────────


class TwilioSMSDispatchTests(TestCase):
    """Covers the SMS branch of `_dispatch_one` + the public Twilio
    status-callback webhook. Uses TWILIO_TEST_MODE=True (which skips
    real API calls in production via the env gate, and skips
    signature verification on the callback so tests can POST without
    HMAC-signing every request).

    The actual Twilio API call is patched out — we verify our code
    invokes the SDK with the right arguments + handles success +
    failure cases. We don't (and shouldn't) test Twilio itself."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('twilio-sms')
        cls.audience = Audience.objects.create(
            tenant=cls.tenant, name='All', filter_spec={},
        )
        cls.template = MarketingTemplate.objects.create(
            tenant=cls.tenant, name='Reminder',
            channel=Channel.SMS, subject='',
            body='Hi {{first_name}}. Reply STOP to opt out.',
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def _make_sms_customer(self):
        return _make_customer(
            self.tenant, phone='+15551234567',
            sms_marketing_opt_in=True,
        )

    def _create_and_schedule_campaign(self):
        response = self.client.post(
            reverse('marketing-campaign-list'),
            data={
                'name': 'SMS dispatch test',
                'audience': self.audience.pk,
                'template': self.template.pk,
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        cid = response.data['id']
        self.client.post(
            reverse('marketing-campaign-schedule', kwargs={'pk': cid}),
            data={'send_now': True}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        return cid

    # ── Dispatch ────────────────────────────────────────────────

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_sms_dispatch_calls_twilio_with_rendered_body(self):
        from unittest.mock import MagicMock, patch
        self._make_sms_customer()
        cid = self._create_and_schedule_campaign()

        fake_message = MagicMock(sid='SMfakeSID12345')
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_message

        with patch('apps.marketing.sender._twilio_client', return_value=fake_client):
            response = self.client.post(
                reverse('marketing-campaign-dispatch-now', kwargs={'pk': cid}),
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        # Verify Twilio was called with the right kwargs.
        fake_client.messages.create.assert_called_once()
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs['from_'], '+18885550000')
        self.assertEqual(kwargs['to'], '+15551234567')
        self.assertIn('Pat', kwargs['body'])  # First name substituted

        # The SendLog row stores Twilio's SID so the status callback
        # can correlate the eventual delivery update.
        log = MarketingSendLog.objects.filter(
            campaign_id=cid, channel=Channel.SMS,
        ).first()
        self.assertEqual(log.provider_message_id, 'SMfakeSID12345')
        self.assertEqual(log.status, MarketingSendLog.Status.SENT)

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_sms_dispatch_handles_twilio_rest_exception(self):
        from unittest.mock import MagicMock, patch
        from twilio.base.exceptions import TwilioRestException

        self._make_sms_customer()
        cid = self._create_and_schedule_campaign()

        fake_client = MagicMock()
        fake_client.messages.create.side_effect = TwilioRestException(
            uri='/test', msg='Phone number not subscribed', code=21610, status=400,
        )

        with patch('apps.marketing.sender._twilio_client', return_value=fake_client):
            response = self.client.post(
                reverse('marketing-campaign-dispatch-now', kwargs={'pk': cid}),
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        log = MarketingSendLog.objects.filter(
            campaign_id=cid, channel=Channel.SMS,
        ).first()
        self.assertEqual(log.status, MarketingSendLog.Status.FAILED)
        self.assertIn('twilio:21610', log.failure_reason)

    def test_sms_dispatch_stub_when_twilio_not_configured(self):
        # Default settings — TWILIO_* not set. Sender falls into stub
        # branch, writes a SendLog row with the stub-noprov prefix,
        # never imports the SDK.
        self._make_sms_customer()
        cid = self._create_and_schedule_campaign()

        response = self.client.post(
            reverse('marketing-campaign-dispatch-now', kwargs={'pk': cid}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        log = MarketingSendLog.objects.filter(
            campaign_id=cid, channel=Channel.SMS,
        ).first()
        self.assertTrue(log.provider_message_id.startswith('stub-noprov-sms-'))
        self.assertEqual(log.status, MarketingSendLog.Status.SENT)

    # ── Status callback ─────────────────────────────────────────

    @override_settings(TWILIO_TEST_MODE=True)
    def test_status_callback_updates_to_delivered(self):
        customer = self._make_sms_customer()
        send_log = MarketingSendLog.objects.create(
            tenant=self.tenant,
            campaign=Campaign.objects.create(
                tenant=self.tenant, name='cb', audience=self.audience,
                template=self.template, channel=Channel.SMS,
            ),
            customer=customer, channel=Channel.SMS,
            recipient_phone_last4='4567',
            status=MarketingSendLog.Status.SENT,
            provider_message_id='SMrealsid',
        )
        anon = APIClient()
        response = anon.post(
            reverse('marketing-twilio-status-callback'),
            data={
                'MessageSid': 'SMrealsid',
                'MessageStatus': 'delivered',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        send_log.refresh_from_db()
        self.assertEqual(send_log.status, MarketingSendLog.Status.DELIVERED)
        self.assertIsNotNone(send_log.delivered_at)

    @override_settings(TWILIO_TEST_MODE=True)
    def test_status_callback_updates_to_failed_with_error(self):
        customer = self._make_sms_customer()
        send_log = MarketingSendLog.objects.create(
            tenant=self.tenant,
            campaign=Campaign.objects.create(
                tenant=self.tenant, name='cb2', audience=self.audience,
                template=self.template, channel=Channel.SMS,
            ),
            customer=customer, channel=Channel.SMS,
            recipient_phone_last4='4567',
            status=MarketingSendLog.Status.SENT,
            provider_message_id='SMfailsid',
        )
        anon = APIClient()
        response = anon.post(
            reverse('marketing-twilio-status-callback'),
            data={
                'MessageSid': 'SMfailsid',
                'MessageStatus': 'undelivered',
                'ErrorCode': '30005',
                'ErrorMessage': 'Unknown destination handset',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        send_log.refresh_from_db()
        self.assertEqual(send_log.status, MarketingSendLog.Status.FAILED)
        self.assertIn('30005', send_log.failure_reason)

    @override_settings(TWILIO_TEST_MODE=True)
    def test_status_callback_unknown_sid_returns_200_unmatched(self):
        # Callback for an SID we don't have — return 200 (don't retry)
        # but flag as unmatched. Real-world reason: replay, Twilio
        # console test, or a row-insert race.
        anon = APIClient()
        response = anon.post(
            reverse('marketing-twilio-status-callback'),
            data={
                'MessageSid': 'SMnotreal',
                'MessageStatus': 'delivered',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('unmatched'))

    def test_status_callback_without_test_mode_rejects_unsigned(self):
        # In production-like mode (test mode off + auth token set),
        # an unsigned request gets 403.
        with override_settings(TWILIO_TEST_MODE=False, TWILIO_AUTH_TOKEN='real-token'):
            anon = APIClient()
            response = anon.post(
                reverse('marketing-twilio-status-callback'),
                data={'MessageSid': 'SM1', 'MessageStatus': 'delivered'},
            )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
