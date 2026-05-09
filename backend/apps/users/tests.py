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
        _make_platform_admin('platform@lumecrm.com')
        client = APIClient()
        client.get(reverse('auth-csrf'))
        response = client.post(
            reverse('auth-login'),
            data={'email': 'platform@lumecrm.com', 'password': 'test-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get('code'), 'platform_admin_account')

    def test_platform_admin_can_use_platform_login(self):
        _make_platform_admin('platform@lumecrm.com')
        client = APIClient()
        client.get(reverse('auth-csrf'))
        response = client.post(
            reverse('auth-platform-login'),
            data={'email': 'platform@lumecrm.com', 'password': 'test-password'},
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
        _make_platform_admin('p@lumecrm.com')
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
            data={'email': 'p@lumecrm.com', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(r2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_endpoint_exposes_is_platform_admin(self):
        admin = _make_platform_admin('p@lumecrm.com')
        client = APIClient()
        client.force_login(admin)
        response = client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['user']['is_platform_admin'])


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
        admin = _make_platform_admin('admin@lumecrm.com')
        creator = _make_platform_admin('creator@lumecrm.com')
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
