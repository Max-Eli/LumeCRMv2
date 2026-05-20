"""Mobile-app auth API — JWT surface for the Lumè staff app.

Deliberately disjoint from the session-cookie web surface in `views.py`
(see ADR 0031). Three endpoints:

  POST /api/auth/mobile/login/    → email+password → { access, refresh, user }
  POST /api/auth/mobile/refresh/  → refresh        → { access, refresh }
  POST /api/auth/mobile/logout/   → blacklist the refresh token → 204

`refresh/` is SimpleJWT's stock `TokenRefreshView`, wired in `urls.py`.

The login response carries the full user payload — including the
`memberships` list — so the app can pick the active workspace
(one membership → straight in; several → a picker). The slug of the
chosen workspace then rides on every API call as `X-Tenant-Slug`.
"""

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .views import _serialize_user


class MobileLoginView(APIView):
    """`POST /api/auth/mobile/login/` — staff app login.

    Mirrors the web `LoginView` posture: platform admins are rejected
    (they use the web console) with the structured
    `platform_admin_account` code; everything else gets a generic 401
    so the endpoint never leaks which emails exist.

    A staff account with zero active memberships is rejected too — the
    app has nothing to show someone who belongs to no workspace.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # login itself carries no credentials yet

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

        if user.is_platform_admin:
            return Response(
                {
                    'detail': 'This account belongs to the platform admin surface.',
                    'code': 'platform_admin_account',
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.memberships.filter(is_active=True).exists():
            return Response(
                {
                    'detail': 'This account has no active workspace.',
                    'code': 'no_membership',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': _serialize_user(user),
            }
        )


class MobileLogoutView(APIView):
    """`POST /api/auth/mobile/logout/` — blacklist the refresh token.

    The access token expires on its own; blacklisting the refresh token
    is what actually ends the session. Idempotent — a missing or
    already-spent token still returns 204 so the app can always treat
    logout as succeeding locally.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('refresh')
        if token:
            try:
                RefreshToken(token).blacklist()
            except TokenError:
                pass  # already invalid / expired — logout stays idempotent
        return Response(status=status.HTTP_204_NO_CONTENT)
