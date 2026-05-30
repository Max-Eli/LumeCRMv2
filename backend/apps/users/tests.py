"""Auth tests — covers the deliberately-disjoint customer / platform login surfaces.

Three test classes:
  - LoginSeparationTests — proves you can't sign in to the wrong
    surface, in either direction
  - PlatformAdminAccountTests — covers the createplatformadmin
    management command + the "platform admin must have zero
    memberships" invariant
  - IdleSessionTimeoutTests — proves the HIPAA idle-logoff middleware
    expires sessions after the configured window

Tenant create flow's rejection of platform-admin owner emails is
covered in apps.platform.tests.PlatformTenantCreateTests.
"""

from __future__ import annotations

import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from io import StringIO
from rest_framework import status
from rest_framework.test import APIClient

from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


def _make_tenant_user(email: str, slug: str) -> User:
    """Create a regular tenant user with one active membership."""
    user = User.objects.create_user(email=email, password='test-password')
    create_tenant_with_defaults(name=slug.title(), slug=slug, owner_user=user)
    return user


def _make_platform_admin(email: str) -> User:
    user = User.objects.create_user(email=email, password='test-password')
    user.is_platform_admin = True
    user.save()
    return user


class LoginSeparationTests(TestCase):
    """Proves the customer and platform login surfaces are disjoint."""

    def test_tenant_user_can_use_regular_login(self):
        _make_tenant_user('owner@example.com', 'somespa')
        client = APIClient()
        client.get(reverse('auth-csrf'))
        response = client.post(
            reverse('auth-login'),
            data={'email': 'owner@example.com', 'password': 'test-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['user']['is_platform_admin'])
        self.assertEqual(len(response.data['user']['memberships']), 1)

    def test_platform_admin_blocked_from_regular_login(self):
        """Platform admins posting to /api/auth/login/ get a 401 with
        a structured error code so the frontend can redirect them to
        the platform login page."""
        _make_platform_admin('platform@xn--lumcrm-5ua.com')
        client = APIClient()
        client.get(reverse('auth-csrf'))
        response = client.post(
            reverse('auth-login'),
            data={'email': 'platform@xn--lumcrm-5ua.com', 'password': 'test-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'platform_admin_account')

    def test_platform_admin_can_use_platform_login(self):
        _make_platform_admin('platform@xn--lumcrm-5ua.com')
        client = APIClient()
        client.get(reverse('auth-csrf'))
        response = client.post(
            reverse('auth-platform-login'),
            data={'email': 'platform@xn--lumcrm-5ua.com', 'password': 'test-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['user']['is_platform_admin'])
        self.assertEqual(response.data['user']['memberships'], [])

    def test_tenant_user_blocked_from_platform_login(self):
        """Generic invalid-credentials message — no information leak."""
        _make_tenant_user('owner@example.com', 'somespa')
        client = APIClient()
        client.get(reverse('auth-csrf'))
        response = client.post(
            reverse('auth-platform-login'),
            data={'email': 'owner@example.com', 'password': 'test-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # No code field — same response shape as a wrong password.
        self.assertNotIn('code', response.data)

    def test_wrong_password_returns_generic_error_on_both_surfaces(self):
        _make_platform_admin('p@xn--lumcrm-5ua.com')
        _make_tenant_user('t@example.com', 'tenant')
        client = APIClient()
        client.get(reverse('auth-csrf'))
        # Wrong password on regular surface
        r1 = client.post(
            reverse('auth-login'),
            data={'email': 't@example.com', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(r1.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn('code', r1.data)
        # Wrong password on platform surface
        r2 = client.post(
            reverse('auth-platform-login'),
            data={'email': 'p@xn--lumcrm-5ua.com', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(r2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_endpoint_exposes_is_platform_admin(self):
        admin = _make_platform_admin('p@xn--lumcrm-5ua.com')
        client = APIClient()
        client.force_login(admin)
        response = client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['user']['is_platform_admin'])

    def test_me_endpoint_membership_tenant_includes_lifecycle_fields(self):
        """The /me/ payload's tenant block carries plan + status +
        trial_ends_at + features + grandfathered. The frontend lifecycle
        banner + nav-feature-gating + upsell modal all consume these —
        breaking the shape breaks the operator UX."""
        import datetime as dt
        from django.utils import timezone as djtz
        from apps.tenants.models import Tenant
        from apps.tenants.services import create_tenant_with_defaults

        owner = User.objects.create_user(email='lc-owner@xn--lumcrm-5ua.com', password='x')
        tenant = create_tenant_with_defaults(
            name='Lifecycle Spa', slug='lifecycle-spa',
            owner_user=owner,
            status=Tenant.Status.TRIAL,
            plan=Tenant.Plan.TRIAL,
            trial_ends_at=djtz.now() + dt.timedelta(days=14),
        )
        client = APIClient()
        client.force_login(owner)
        response = client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        memberships = response.data['user']['memberships']
        spa = next(m for m in memberships if m['tenant']['slug'] == 'lifecycle-spa')
        # Every field the frontend banner/modal reads must be present.
        for key in ('plan', 'status', 'trial_ends_at', 'grandfathered', 'features'):
            self.assertIn(key, spa['tenant'], f'missing key {key} on tenant payload')
        self.assertEqual(spa['tenant']['status'], 'trial')
        self.assertEqual(spa['tenant']['plan'], 'trial')
        self.assertFalse(spa['tenant']['grandfathered'])
        # trial_ends_at is ISO-formatted; the frontend parses with Date().
        self.assertIsNotNone(spa['tenant']['trial_ends_at'])
        self.assertIn('T', spa['tenant']['trial_ends_at'])
        # Features is a sorted list of strings (deterministic shape).
        self.assertIsInstance(spa['tenant']['features'], list)
        # Trial inherits Pro features per the catalog.
        self.assertIn('email_marketing', spa['tenant']['features'])

    def test_me_endpoint_active_tenant_has_null_trial_ends_at(self):
        """An active (post-trial) tenant must serialize trial_ends_at
        as null so the frontend banner hides correctly."""
        from apps.tenants.models import Tenant
        from apps.tenants.services import create_tenant_with_defaults

        owner = User.objects.create_user(email='active-owner@xn--lumcrm-5ua.com', password='x')
        create_tenant_with_defaults(
            name='Active Spa', slug='active-spa',
            owner_user=owner,
            status=Tenant.Status.ACTIVE,
            plan=Tenant.Plan.STARTER,
            trial_ends_at=None,
        )
        client = APIClient()
        client.force_login(owner)
        response = client.get(reverse('auth-me'))
        spa = next(
            m for m in response.data['user']['memberships']
            if m['tenant']['slug'] == 'active-spa'
        )
        self.assertEqual(spa['tenant']['status'], 'active')
        self.assertIsNone(spa['tenant']['trial_ends_at'])


class PlatformAdminAccountTests(TestCase):
    """Bootstrap command + invariants on platform admin accounts."""

    def test_createplatformadmin_creates_new_account(self):
        out = StringIO()
        call_command(
            'createplatformadmin',
            email='max@voxtro.io',
            password='supersecret-pw-123',
            first_name='Max',
            last_name='Test',
            interactive=False,
            stdout=out,
        )
        user = User.objects.get(email='max@voxtro.io')
        self.assertTrue(user.is_platform_admin)
        self.assertFalse(user.is_superuser)  # NOT auto-elevated
        self.assertFalse(user.memberships.exists())
        self.assertIn('Created platform admin', out.getvalue())

    def test_createplatformadmin_elevates_existing_user_with_no_memberships(self):
        User.objects.create_user(email='lonely@example.com', password='whatever')
        out = StringIO()
        call_command(
            'createplatformadmin',
            email='lonely@example.com',
            password='supersecret-pw-123',
            interactive=False,
            stdout=out,
        )
        user = User.objects.get(email='lonely@example.com')
        self.assertTrue(user.is_platform_admin)
        self.assertIn('Elevated platform admin', out.getvalue())

    def test_createplatformadmin_refuses_user_with_memberships(self):
        _make_tenant_user('owner@example.com', 'thespa')
        with self.assertRaises(CommandError) as ctx:
            call_command(
                'createplatformadmin',
                email='owner@example.com',
                password='supersecret-pw-123',
                interactive=False,
            )
        self.assertIn('membership', str(ctx.exception).lower())

    def test_tenant_create_rejects_platform_admin_email(self):
        """The platform-side tenant create endpoint rejects any owner
        email belonging to a platform admin — keeps worlds disjoint."""
        admin = _make_platform_admin('admin@xn--lumcrm-5ua.com')
        creator = _make_platform_admin('creator@xn--lumcrm-5ua.com')
        client = APIClient()
        client.force_login(creator)
        response = client.post(
            reverse('platform-tenant-list'),
            data={
                'name': 'Trying',
                'slug': 'trying',
                'owner_email': admin.email,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('owner_email', response.data)


# ── Idle-session timeout (HIPAA §164.312(a)(2)(iii)) ─────────────────


# `override_settings` adds the middleware on top of the default test
# settings (which inherit from base.py — no idle middleware in dev).
# Tightening the window to 60 seconds lets the test simulate idle by
# fast-forwarding `time.time()` rather than literally sleeping.
@override_settings(
    MIDDLEWARE=[
        'corsheaders.middleware.CorsMiddleware',
        'django.middleware.security.SecurityMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.middleware.common.CommonMiddleware',
        'django.middleware.csrf.CsrfViewMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'apps.users.middleware.IdleSessionTimeoutMiddleware',
        'apps.tenants.middleware.TenantMiddleware',
        'apps.tenants.middleware.LocationMiddleware',
        'django.contrib.messages.middleware.MessageMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
    ],
    IDLE_SESSION_TIMEOUT_SECONDS=60,
)
class IdleSessionTimeoutTests(TestCase):
    """Authenticated requests get logged out after `IDLE_SESSION_TIMEOUT_SECONDS`."""

    def setUp(self):
        self.user = _make_tenant_user('idle@example.com', 'idlespa')

    def test_first_request_stamps_session_and_succeeds(self):
        client = APIClient()
        client.force_login(self.user)
        response = client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Session got stamped — proves the middleware ran.
        self.assertIn('_lume_last_activity_at', client.session)

    def test_session_within_window_stays_active(self):
        client = APIClient()
        client.force_login(self.user)
        # First request to seed the timestamp.
        client.get(reverse('auth-me'))
        # Bump the clock 30 seconds — well inside the 60-second window.
        with patch('apps.users.middleware.time.time', return_value=time.time() + 30):
            response = client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_session_past_window_is_logged_out(self):
        client = APIClient()
        client.force_login(self.user)
        client.get(reverse('auth-me'))
        # Two minutes — well past the 60-second window.
        with patch('apps.users.middleware.time.time', return_value=time.time() + 120):
            response = client.get(reverse('auth-me'))
        # MeView requires auth; the middleware drops the session, so
        # DRF returns 403 to an anonymous request. The 403 is the
        # proof of logout — without the middleware, this would 200.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Session activity stamp got cleared on logout.
        self.assertNotIn('_lume_last_activity_at', client.session)

    def test_healthz_is_exempt(self):
        client = APIClient()
        client.force_login(self.user)
        client.get(reverse('auth-me'))
        # Two-minute fast-forward; if /healthz were checked, the
        # middleware would log the user out. We don't care about that
        # for this assertion — we only care that hitting healthz
        # itself returns 200 without touching the session.
        with patch('apps.users.middleware.time.time', return_value=time.time() + 120):
            response = client.get('/healthz/live')
        self.assertEqual(response.status_code, 200)


class MobileAuthTests(TestCase):
    """The JWT `mobile/` auth surface for the staff app (ADR 0030).

    Covers token issuance, the platform-admin / no-membership gates,
    bearer-token request auth, the cross-tenant fail-closed guarantee,
    refresh, and logout-blacklisting.
    """

    def _login(self, client, email, password='test-password'):
        return client.post(
            reverse('mobile-login'),
            data={'email': email, 'password': password},
            format='json',
        )

    def _make_active_tenant_user(self, email, slug):
        """A staff user owning an ACTIVE tenant. `TenantMiddleware` only
        resolves ACTIVE tenants from the `X-Tenant-Slug` header, so any
        test that exercises tenant resolution needs the tenant active."""
        user = User.objects.create_user(email=email, password='test-password')
        create_tenant_with_defaults(
            name=slug.title(), slug=slug, owner_user=user,
            status=Tenant.Status.ACTIVE,
        )
        return user

    def test_login_returns_token_pair_and_user(self):
        _make_tenant_user('staff@example.com', 'mobilespa')
        response = self._login(APIClient(), 'staff@example.com')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(len(response.data['user']['memberships']), 1)

    def test_login_rejects_platform_admin(self):
        _make_platform_admin('admin@xn--lumcrm-5ua.com')
        response = self._login(APIClient(), 'admin@xn--lumcrm-5ua.com')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['code'], 'platform_admin_account')

    def test_login_rejects_bad_password(self):
        _make_tenant_user('staff@example.com', 'badpwspa')
        response = self._login(APIClient(), 'staff@example.com', password='wrong')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_rejects_account_with_no_membership(self):
        User.objects.create_user(email='orphan@example.com', password='test-password')
        response = self._login(APIClient(), 'orphan@example.com')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'no_membership')

    def test_access_token_authenticates_an_api_request(self):
        self._make_active_tenant_user('staff@example.com', 'tokenspa')
        access = self._login(APIClient(), 'staff@example.com').data['access']
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        response = client.get(reverse('auth-me'), HTTP_X_TENANT_SLUG='tokenspa')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['email'], 'staff@example.com')

    def test_request_for_a_tenant_the_user_doesnt_belong_to_is_rejected(self):
        """The mobile equivalent of the web's subdomain isolation: a
        valid token addressed at the wrong workspace fails closed."""
        self._make_active_tenant_user('staff@example.com', 'homespa')
        other_owner = User.objects.create_user(
            email='other@example.com', password='test-password',
        )
        create_tenant_with_defaults(
            name='Other Spa', slug='otherspa', owner_user=other_owner,
            status=Tenant.Status.ACTIVE,
        )
        access = self._login(APIClient(), 'staff@example.com').data['access']
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        response = client.get(reverse('auth-me'), HTTP_X_TENANT_SLUG='otherspa')
        # Denied. DRF downgrades the auth-class rejection to 403 because
        # SessionAuthentication (authenticators[0]) advertises no
        # challenge header — the request is refused either way.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_request_without_tenant_header_still_authenticates(self):
        """No `X-Tenant-Slug` → no tenant to scope against → the token
        still identifies the user (used by tenant-agnostic calls)."""
        _make_tenant_user('staff@example.com', 'noheaderspa')
        access = self._login(APIClient(), 'staff@example.com').data['access']
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        response = client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_refresh_returns_a_new_access_token(self):
        _make_tenant_user('staff@example.com', 'refreshspa')
        refresh = self._login(APIClient(), 'staff@example.com').data['refresh']
        response = APIClient().post(
            reverse('mobile-refresh'), data={'refresh': refresh}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_logout_blacklists_the_refresh_token(self):
        _make_tenant_user('staff@example.com', 'logoutspa')
        login = self._login(APIClient(), 'staff@example.com')
        access, refresh = login.data['access'], login.data['refresh']

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        logout = client.post(
            reverse('mobile-logout'), data={'refresh': refresh}, format='json',
        )
        self.assertEqual(logout.status_code, status.HTTP_204_NO_CONTENT)

        # The blacklisted refresh token can no longer mint an access token.
        retry = APIClient().post(
            reverse('mobile-refresh'), data={'refresh': refresh}, format='json',
        )
        self.assertEqual(retry.status_code, status.HTTP_401_UNAUTHORIZED)
