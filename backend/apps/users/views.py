"""Auth API views.

Two completely separate auth surfaces:

  ─── Customer / tenant auth ──────────────────────────────────────
  GET  /api/auth/csrf/             → set csrftoken cookie
  POST /api/auth/login/            → tenant user → 200 { user } | 401
  POST /api/auth/logout/           → 204
  GET  /api/auth/me/               → 200 { user } | 401

  ─── Platform admin auth ─────────────────────────────────────────
  POST /api/auth/platform/login/   → platform admin → 200 { user } | 401

The two flows are mutually exclusive: a platform admin posting to the
tenant /login/ endpoint gets rejected with `code=platform_admin_account`
so the frontend can redirect them to the platform login page. A tenant
user posting to /platform/login/ gets rejected with the same generic
"invalid email or password" — we don't acknowledge that the email
exists on the other surface (no enumeration leak). See ADR (planned)
on auth separation.

Session-cookie auth via Django's session framework. CSRF protection
enforced by DRF's SessionAuthentication on POST/PUT/PATCH/DELETE.
"""

from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


def _serialize_user(user):
    """Standard user payload for /me/ + login responses.

    Includes `is_platform_admin` so the frontend can route appropriately
    (platform admin → /platform; tenant user → /dashboard). Memberships
    are listed only when present; platform admins have none.
    """
    memberships = [
        {
            'tenant': {
                'id': m.tenant_id,
                'name': m.tenant.name,
                'slug': m.tenant.slug,
            },
            'role': m.role,
            'role_display': m.get_role_display(),
            'is_bookable': m.is_bookable,
        }
        for m in user.memberships.filter(is_active=True).select_related('tenant')
    ]
    return {
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_superuser': user.is_superuser,
        'is_platform_admin': user.is_platform_admin,
        'memberships': memberships,
    }


class CSRFView(APIView):
    """Set the CSRF cookie. The frontend hits this once before any POST."""

    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({'detail': 'ok'})


class LoginView(APIView):
    """Tenant-user login. Rejects platform-admin accounts.

    A platform admin posting credentials here gets a structured error
    (`code=platform_admin_account`) so the frontend can redirect them
    to the platform login page. Generic "invalid credentials" for
    everything else — no enumeration leak.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''

        if not email or not password:
            return Response(
                {'detail': 'Email and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response(
                {'detail': 'Invalid email or password.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Platform admins use the dedicated /platform/login/ surface.
        # We don't sign them in here even though the credentials are
        # valid — return a structured error so the frontend can route.
        if user.is_platform_admin:
            return Response(
                {
                    'detail': 'This account belongs to the platform admin surface.',
                    'code': 'platform_admin_account',
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        return Response({'user': _serialize_user(user)})


class PlatformLoginView(APIView):
    """Dedicated login for platform admins.

    Strict gate:
      1. Credentials must validate.
      2. User must have `is_platform_admin=True`.
      3. User must have ZERO active tenant memberships.

    Failures return a generic "invalid email or password" — same
    error a regular tenant user would get if they posted here, no
    information leak about which surface owns the email.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''

        if not email or not password:
            return Response(
                {'detail': 'Email and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=email, password=password)
        generic_unauthorized = Response(
            {'detail': 'Invalid email or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
        if user is None:
            return generic_unauthorized
        if not user.is_platform_admin:
            return generic_unauthorized
        # Defense in depth: platform admins should have zero memberships,
        # but if a buggy code path created one, refuse to log them in.
        if user.memberships.filter(is_active=True).exists():
            return Response(
                {
                    'detail': 'Account state invalid for platform login.',
                    'code': 'platform_admin_with_memberships',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        login(request, user)
        return Response({'user': _serialize_user(user)})


class LogoutView(APIView):
    """Single logout endpoint — works for both surfaces.

    Session-cookie based, so a single logout call clears the session
    regardless of which surface the user signed in through.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Return the current user. Used by both surfaces.

    The response shape is the same; the frontend reads
    `is_platform_admin` to decide which UI surface to render.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'user': _serialize_user(request.user)})
