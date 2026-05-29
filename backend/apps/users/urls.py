"""Auth URL routes.

Three login surfaces, deliberately disjoint:
  - tenant + platform session-cookie auth — see views.py
  - the JWT `mobile/` surface for the staff app — see mobile.py + ADR 0031
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.tenants.views import InvitationAcceptView, InvitationLookupView

from .mobile import MobileLoginView, MobileLogoutView
from .views import (
    CSRFView,
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    PlatformLoginView,
    VerifyCredentialsView,
    VerifyEmailView,
)

urlpatterns = [
    path('csrf/', CSRFView.as_view(), name='auth-csrf'),
    path('login/', LoginView.as_view(), name='auth-login'),
    path('platform/login/', PlatformLoginView.as_view(), name='auth-platform-login'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('me/', MeView.as_view(), name='auth-me'),
    path('change-password/', ChangePasswordView.as_view(), name='auth-change-password'),
    # Used by the kiosk-mode unlock on /sign/[token]. Doesn't open a
    # session — just answers "is this a valid staff credential?".
    path('verify-credentials/', VerifyCredentialsView.as_view(), name='auth-verify-credentials'),
    # Staff mobile app — JWT bearer-token auth (ADR 0031). The web
    # surface above is untouched; these are purely additive.
    path('mobile/login/', MobileLoginView.as_view(), name='mobile-login'),
    path('mobile/refresh/', TokenRefreshView.as_view(), name='mobile-refresh'),
    path('mobile/logout/', MobileLogoutView.as_view(), name='mobile-logout'),
    # Public invitation flow — the lookup endpoint lets the accept
    # page show "you've been invited to join Acme Spa" before the
    # recipient sets a password; accept creates the user + membership
    # + logs them in. Both are AllowAny because the recipient isn't
    # authenticated yet by definition. The token IS the identifier.
    # Order matters: `accept/` must come before the catch-all token
    # pattern (`<str:token>`), which would otherwise match `accept`
    # as a token value.
    path('invitation/accept/', InvitationAcceptView.as_view(), name='auth-invitation-accept'),
    path('invitation/<str:token>/', InvitationLookupView.as_view(), name='auth-invitation-lookup'),
    # Self-serve signup email-verification consume. Public (the new
    # owner clicks the link in their inbox before they've logged in).
    path('verify-email/<str:token>/', VerifyEmailView.as_view(), name='auth-verify-email'),
]
