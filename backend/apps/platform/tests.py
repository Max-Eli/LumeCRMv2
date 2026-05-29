"""Tests for the platform admin surface.

Covers: permission gating (only is_superuser), tenant lifecycle
transitions (create / suspend / reactivate / update), audit log
shape on every action, and slug validation (uniqueness + reserved
words). Cross-tenant isolation isn't a concern here because the
platform IS the cross-tenant view — but we verify a non-superuser
gets a clean 403 instead of leaking platform data.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


def _make_user(email: str, *, is_superuser=False, is_platform_admin=False, **kwargs) -> User:
    user = User.objects.create_user(email=email, password='test-password', **kwargs)
    flags_changed = False
    if is_superuser:
        user.is_superuser = True
        user.is_staff = True
        flags_changed = True
    if is_platform_admin:
        user.is_platform_admin = True
        flags_changed = True
    if flags_changed:
        user.save()
    return user


def _make_tenant(slug: str, *, status_value=Tenant.Status.ACTIVE) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(),
        slug=slug,
        owner_user=owner,
        status=status_value,
    )
    return tenant, owner


def _platform_admin_client() -> tuple[User, APIClient]:
    """Sign in a platform admin (no tenant memberships)."""
    user = _make_user('platform-admin@xn--lumcrm-5ua.com', is_platform_admin=True)
    client = APIClient()
    client.force_login(user)
    return user, client


# Backwards-compat alias so existing tests keep working without diff churn —
# every spot that used `_superuser_client` now creates a platform admin.
_superuser_client = _platform_admin_client


class PlatformPermissionTests(TestCase):
    def test_anonymous_user_blocked(self):
        client = APIClient()
        response = client.get(reverse('platform-tenant-list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_regular_tenant_owner_blocked(self):
        tenant, owner = _make_tenant('regular')
        client = APIClient()
        client.force_login(owner)
        response = client.get(
            reverse('platform-tenant-list'),
            HTTP_X_TENANT_SLUG=tenant.slug,
        )
        # Tenant owner is NOT a platform admin. Platform endpoints
        # treat them like any other unauthorized caller.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_platform_admin_allowed(self):
        _user, client = _platform_admin_client()
        response = client.get(reverse('platform-tenant-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_django_superuser_alone_does_not_grant_access(self):
        """A Django superuser without is_platform_admin is blocked.

        is_superuser is the stock Django-admin flag; it's intentionally
        distinct from is_platform_admin. Pre-separation accounts that
        relied on is_superuser for platform access need to be migrated
        explicitly.
        """
        user = _make_user('django-super@test.local', is_superuser=True)
        client = APIClient()
        client.force_login(user)
        response = client.get(reverse('platform-tenant-list'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PlatformTenantListTests(TestCase):
    def setUp(self):
        self.tenant_a, _ = _make_tenant('alpha')
        self.tenant_b, _ = _make_tenant('beta', status_value=Tenant.Status.SUSPENDED)
        self.user, self.client = _superuser_client()

    def test_lists_every_tenant_regardless_of_status(self):
        response = self.client.get(reverse('platform-tenant-list'))
        slugs = {row['slug'] for row in response.data}
        self.assertEqual(slugs, {'alpha', 'beta'})

    def test_includes_member_count_and_owner_email(self):
        response = self.client.get(reverse('platform-tenant-list'))
        alpha = next(r for r in response.data if r['slug'] == 'alpha')
        self.assertEqual(alpha['member_count'], 1)
        self.assertEqual(alpha['owner_email'], 'alpha-owner@test.local')

    def test_list_includes_plan_and_billing_visibility_fields(self):
        # Platform admin must be able to scan plan / trial state /
        # Stripe enrollment at a glance, without opening Stripe.
        response = self.client.get(reverse('platform-tenant-list'))
        alpha = next(r for r in response.data if r['slug'] == 'alpha')
        # All the billing fields the admin UI renders must be present.
        for key in (
            'plan',
            'billing_cycle',
            'grandfathered',
            'billing_email',
            'trial_ends_at',
            'current_period_end',
            'trial_days_remaining',
            'has_stripe_subscription',
            'has_payment_method',
        ):
            self.assertIn(key, alpha, f'missing billing field: {key}')

    def test_trial_days_remaining_for_active_tenant_is_none(self):
        # The badge should only appear for tenants actually in trial.
        # Active (or any non-trial) tenants should serialize null so
        # the frontend hides the countdown.
        self.tenant_a.status = Tenant.Status.ACTIVE
        self.tenant_a.save()
        response = self.client.get(reverse('platform-tenant-list'))
        alpha = next(r for r in response.data if r['slug'] == 'alpha')
        self.assertIsNone(alpha['trial_days_remaining'])

    def test_trial_days_remaining_for_trial_tenant_counts_down(self):
        # 5 days from now → 5 (or possibly 4 if we just crossed a day
        # boundary in the test; assert >= 4 to avoid flakiness).
        import datetime as dt
        from django.utils import timezone as djtz
        self.tenant_a.status = Tenant.Status.TRIAL
        self.tenant_a.trial_ends_at = djtz.now() + dt.timedelta(days=5)
        self.tenant_a.save()
        response = self.client.get(reverse('platform-tenant-list'))
        alpha = next(r for r in response.data if r['slug'] == 'alpha')
        self.assertIsNotNone(alpha['trial_days_remaining'])
        self.assertGreaterEqual(alpha['trial_days_remaining'], 4)
        self.assertLessEqual(alpha['trial_days_remaining'], 5)

    def test_has_stripe_subscription_reflects_field(self):
        self.tenant_a.stripe_subscription_id = 'sub_123'
        self.tenant_a.save()
        response = self.client.get(reverse('platform-tenant-list'))
        alpha = next(r for r in response.data if r['slug'] == 'alpha')
        self.assertTrue(alpha['has_stripe_subscription'])

    def test_grandfathered_flag_visible_in_list(self):
        # Critical: ops needs to see "this is a grandfathered tenant,
        # don't touch their billing" at a glance — otherwise someone
        # could try to "fix" them.
        self.tenant_a.grandfathered = True
        self.tenant_a.save()
        response = self.client.get(reverse('platform-tenant-list'))
        alpha = next(r for r in response.data if r['slug'] == 'alpha')
        self.assertTrue(alpha['grandfathered'])


class PlatformTenantDetailBillingTests(TestCase):
    """The detail endpoint exposes the deeper billing identifiers
    (Stripe Customer/Subscription IDs, add-on quantities, usage
    counters) that don't belong on the list view."""

    def setUp(self):
        self.tenant, _ = _make_tenant('detail-spa')
        self.tenant.stripe_customer_id = 'cus_xyz'
        self.tenant.stripe_subscription_id = 'sub_xyz'
        self.tenant.addon_quantities = {'staff': 3, 'location': 1}
        self.tenant.current_period_sms_count = 42
        self.tenant.current_period_email_count = 1234
        self.tenant.save()
        self.user, self.client = _superuser_client()

    def test_detail_includes_stripe_ids_and_addons_and_usage(self):
        response = self.client.get(
            reverse('platform-tenant-detail', args=['detail-spa']),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['stripe_customer_id'], 'cus_xyz')
        self.assertEqual(response.data['stripe_subscription_id'], 'sub_xyz')
        self.assertEqual(
            response.data['addon_quantities'],
            {'staff': 3, 'location': 1},
        )
        self.assertEqual(response.data['current_period_sms_count'], 42)
        self.assertEqual(response.data['current_period_email_count'], 1234)


class PlatformTenantCreateTests(TestCase):
    def setUp(self):
        self.user, self.client = _superuser_client()

    def test_creates_tenant_with_new_owner_and_returns_temp_password(self):
        response = self.client.post(
            reverse('platform-tenant-list'),
            data={
                'name': 'Brand New Spa',
                'slug': 'brandnew',
                'owner_email': 'newowner@example.com',
                'owner_first_name': 'New',
                'owner_last_name': 'Owner',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'brandnew')
        self.assertEqual(response.data['status'], Tenant.Status.TRIAL)
        # Temp password surfaced exactly once for the new user.
        self.assertIn('owner_temp_password', response.data)
        self.assertGreater(len(response.data['owner_temp_password']), 8)
        # Tenant + owner membership both exist.
        tenant = Tenant.objects.get(slug='brandnew')
        owner = User.objects.get(email='newowner@example.com')
        self.assertTrue(
            TenantMembership.objects.filter(tenant=tenant, user=owner, role='owner').exists(),
        )

    def test_creates_tenant_attaching_existing_user_no_temp_password(self):
        existing = _make_user('returning@example.com', first_name='Already', last_name='Here')
        response = self.client.post(
            reverse('platform-tenant-list'),
            data={
                'name': 'Second Location',
                'slug': 'secondloc',
                'owner_email': 'returning@example.com',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Existing user → no temp password in response.
        self.assertNotIn('owner_temp_password', response.data)
        # Existing user attached as owner.
        self.assertTrue(
            TenantMembership.objects.filter(
                tenant__slug='secondloc',
                user=existing,
                role='owner',
            ).exists(),
        )

    def test_rejects_duplicate_slug(self):
        _make_tenant('taken')
        response = self.client.post(
            reverse('platform-tenant-list'),
            data={
                'name': 'Duplicate',
                'slug': 'taken',
                'owner_email': 'someone@example.com',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('slug', response.data)

    def test_rejects_reserved_slug(self):
        for reserved in ('admin', 'api', 'app', 'platform'):
            response = self.client.post(
                reverse('platform-tenant-list'),
                data={
                    'name': 'Reserved Name',
                    'slug': reserved,
                    'owner_email': 'someone@example.com',
                },
                format='json',
            )
            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST,
                f'reserved slug "{reserved}" should be rejected',
            )

    def test_create_writes_audit_entry(self):
        before = AuditLog.objects.filter(resource_type='platform_tenant').count()
        self.client.post(
            reverse('platform-tenant-list'),
            data={
                'name': 'Audit Test',
                'slug': 'audittest',
                'owner_email': 'audit@example.com',
            },
            format='json',
        )
        after = AuditLog.objects.filter(resource_type='platform_tenant').count()
        self.assertEqual(after, before + 1)
        entry = (
            AuditLog.objects
            .filter(resource_type='platform_tenant')
            .latest('timestamp')
        )
        self.assertEqual(entry.action, AuditLog.Action.CREATE)
        self.assertEqual(entry.metadata['event'], 'tenant_created')
        self.assertEqual(entry.metadata['tenant_slug'], 'audittest')
        # Email DOMAIN only, never the full address.
        self.assertEqual(entry.metadata['owner_email_domain'], 'example.com')
        self.assertNotIn('audit@example.com', str(entry.metadata))


class PlatformTenantLifecycleTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('lifecycle')
        self.user, self.client = _superuser_client()

    def test_suspend_transitions_active_to_suspended(self):
        response = self.client.post(
            reverse('platform-tenant-suspend', args=[self.tenant.slug]),
            data={'reason': 'Non-payment after 60 days past due'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.SUSPENDED)

    def test_suspend_records_reason_in_audit(self):
        self.client.post(
            reverse('platform-tenant-suspend', args=[self.tenant.slug]),
            data={'reason': 'Customer cancellation request'},
            format='json',
        )
        entry = (
            AuditLog.objects
            .filter(resource_type='platform_tenant', metadata__event='tenant_suspended')
            .latest('timestamp')
        )
        self.assertEqual(entry.metadata['reason'], 'Customer cancellation request')
        self.assertEqual(entry.metadata['previous_status'], 'active')

    def test_suspend_already_suspended_returns_409(self):
        self.tenant.status = Tenant.Status.SUSPENDED
        self.tenant.save()
        response = self.client.post(
            reverse('platform-tenant-suspend', args=[self.tenant.slug]),
            data={'reason': 'Already suspended'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reactivate_transitions_suspended_to_active(self):
        self.tenant.status = Tenant.Status.SUSPENDED
        self.tenant.save()
        response = self.client.post(
            reverse('platform-tenant-reactivate', args=[self.tenant.slug]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_reactivate_non_suspended_returns_409(self):
        # tenant is ACTIVE
        response = self.client.post(
            reverse('platform-tenant-reactivate', args=[self.tenant.slug]),
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reactivate_writes_audit_entry(self):
        self.tenant.status = Tenant.Status.SUSPENDED
        self.tenant.save()
        self.client.post(
            reverse('platform-tenant-reactivate', args=[self.tenant.slug]),
        )
        entry = (
            AuditLog.objects
            .filter(resource_type='platform_tenant', metadata__event='tenant_reactivated')
            .latest('timestamp')
        )
        self.assertEqual(entry.metadata['tenant_slug'], 'lifecycle')


class PlatformTenantUpdateTests(TestCase):
    def setUp(self):
        self.tenant, _ = _make_tenant('updatetest')
        self.user, self.client = _superuser_client()

    def test_update_changes_name(self):
        response = self.client.patch(
            reverse('platform-tenant-detail', args=[self.tenant.slug]),
            data={'name': 'Renamed Spa'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, 'Renamed Spa')

    def test_update_records_changed_fields_in_audit(self):
        self.client.patch(
            reverse('platform-tenant-detail', args=[self.tenant.slug]),
            data={'name': 'Renamed Spa', 'primary_color': '#abc123'},
            format='json',
        )
        entry = (
            AuditLog.objects
            .filter(resource_type='platform_tenant', metadata__event='tenant_updated')
            .latest('timestamp')
        )
        self.assertCountEqual(entry.metadata['fields_changed'], ['name', 'primary_color'])


class PlatformSummaryTests(TestCase):
    def test_returns_status_breakdown_and_recent_signups(self):
        _make_tenant('one', status_value=Tenant.Status.ACTIVE)
        _make_tenant('two', status_value=Tenant.Status.TRIAL)
        _make_tenant('three', status_value=Tenant.Status.SUSPENDED)
        user, client = _superuser_client()

        response = client.get(reverse('platform-summary'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_tenants'], 3)
        self.assertEqual(response.data['by_status']['active'], 1)
        self.assertEqual(response.data['by_status']['trial'], 1)
        self.assertEqual(response.data['by_status']['suspended'], 1)
        self.assertGreaterEqual(len(response.data['recent_signups']), 3)

    def test_summary_blocked_for_non_superuser(self):
        _tenant, owner = _make_tenant('only')
        client = APIClient()
        client.force_login(owner)
        response = client.get(reverse('platform-summary'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
