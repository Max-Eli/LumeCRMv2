"""Auth URL routes.

Two separate login surfaces, deliberately disjoint — see views.py.
"""

from django.urls import path

from apps.tenants.views import InvitationAcceptView, InvitationLookupView

from .views import (
    CSRFView,
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    PlatformLoginView,
    VerifyCredentialsView,
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
]
