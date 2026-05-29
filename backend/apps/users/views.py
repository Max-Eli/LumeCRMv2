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

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record


def _serialize_user(user):
    """Standard user payload for /me/ + login responses.

    Includes `is_platform_admin` so the frontend can route appropriately
    (platform admin → /platform; tenant user → /dashboard). Memberships
    are listed only when present; platform admins have none.

    Each membership carries the tenant's ``plan`` + ``grandfathered``
    flag + the resolved ``features`` set so the frontend can gate UI
    surfaces (sidebar nav hides, "this feature is Pro" upsell badges)
    without a second round-trip. The backend remains the source of
    truth — every gated endpoint re-checks via ``PlanFeatureRequired``
    — this is purely about UX correctness.
    """
    from apps.tenants.plans import features_for

    memberships = []
    for m in user.memberships.filter(is_active=True).select_related('tenant'):
        feats = features_for(m.tenant)
        memberships.append({
            'tenant': {
                'id': m.tenant_id,
                'name': m.tenant.name,
                'slug': m.tenant.slug,
                'plan': m.tenant.plan,
                'grandfathered': m.tenant.grandfathered,
                # Serialize as a sorted list (deterministic + JSON-safe;
                # frozenset isn't natively serializable). Frontend
                # builds a Set client-side for membership checks.
                'features': sorted(feats),
            },
            'role': m.role,
            'role_display': m.get_role_display(),
            'is_bookable': m.is_bookable,
        })
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


class ChangePasswordView(APIView):
    """`POST /api/auth/change-password/` — any signed-in user changes
    their own password. All tenant roles (owner / manager / front_desk
    / provider / bookkeeper / marketing) plus platform admins.

    Requires the **current** password to defeat a "stolen session"
    attack (an attacker with a hijacked session cookie shouldn't be
    able to silently lock the real owner out of the account).

    Django's password validators run on `new_password` — minimum
    length, common-passwords list, etc. — so weak choices get a
    structured error pointing at the offending rule.

    The session ID is rotated post-save via
    `update_session_auth_hash` so the current browser stays logged
    in while every other open session is killed (Django's default
    `SESSION_KEY_SALT` behavior). That mirrors what every serious
    SaaS does: change your password → everyone else gets booted.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        current = request.data.get('current_password') or ''
        new_password = request.data.get('new_password') or ''
        confirm = request.data.get('confirm_password') or ''

        if not current or not new_password:
            return Response(
                {'detail': 'Current password and new password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if confirm and confirm != new_password:
            return Response(
                {'confirm_password': "Doesn't match the new password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not request.user.check_password(current):
            return Response(
                {'current_password': 'Incorrect current password.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_password == current:
            return Response(
                {'new_password': 'New password must be different from the current one.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(new_password, user=request.user)
        except DjangoValidationError as exc:
            return Response(
                {'new_password': list(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        # Keep the current browser session valid through the password
        # rotation. Other sessions get invalidated automatically.
        update_session_auth_hash(request, request.user)

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='user',
            resource_id=request.user.id,
            request=request,
            metadata={'fields_changed': ['password']},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyCredentialsView(APIView):
    """`POST /api/auth/verify-credentials/` — does this email +
    password belong to a real, active tenant member?

    Used by the kiosk-mode unlock dialog on the public form-sign
    page (`/sign/[token]`). Front-desk hands the iPad to a customer,
    locks the page; to unlock, ANY staff member at the tenant logs
    in via this endpoint. We deliberately do NOT mutate the request
    session — the customer's anonymous fill session keeps going,
    we just answered "yes, that's a valid staff credential."

    Strict gate:
      1. Credentials must validate against Django's auth backend.
      2. User must have at least one active TenantMembership.
      3. Platform admins are rejected (they're not "staff" at any
         tenant).

    Generic 401 on all failures — same posture as /login/, no
    information leak about which emails exist.
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
        generic = Response(
            {'detail': 'Invalid email or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )
        if user is None:
            return generic
        if user.is_platform_admin:
            return generic
        if not user.memberships.filter(is_active=True).exists():
            return generic

        return Response({'ok': True, 'email': user.email})


# ── Email verification (Phase 3 — self-serve signup) ────────────


class VerifyEmailView(APIView):
    """``POST /api/auth/verify-email/<token>/`` — consume a verification
    token. Marks the User as verified + invalidates the token.

    Public (no auth required) because a brand-new owner hasn't
    logged in yet when they click the link in the email. The token
    itself is the security boundary — 256-bit + single-use + 7-day
    expiry (see ``EmailVerificationToken``).

    Returns 200 on success, 410 Gone on expired / already-used token,
    404 if the token doesn't exist (we don't distinguish to avoid
    leaking whether a token shape is valid).
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, token: str):
        from django.db import transaction
        from django.utils import timezone as djtz

        from apps.users.models import EmailVerificationToken

        # Same generic-404 shape for missing / expired / consumed so
        # an attacker can't probe the token space.
        not_found = Response(
            {
                'detail': 'This verification link is invalid or expired. '
                          'Request a new one from your account settings.',
                'code': 'token_not_valid',
            },
            status=status.HTTP_410_GONE,
        )

        with transaction.atomic():
            try:
                t = (
                    EmailVerificationToken.objects
                    .select_for_update(of=('self',))
                    .select_related('user')
                    .get(token=token)
                )
            except EmailVerificationToken.DoesNotExist:
                return not_found

            if t.used_at is not None or t.expires_at <= djtz.now():
                return not_found

            now = djtz.now()
            t.used_at = now
            t.save(update_fields=['used_at'])

            user = t.user
            if user.email_verified_at is None:
                user.email_verified_at = now
                user.save(update_fields=['email_verified_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='user_email_verification',
            resource_id=user.id,
            request=request,
            metadata={'verified_at': user.email_verified_at.isoformat()},
        )
        return Response({'verified': True, 'email': user.email})
