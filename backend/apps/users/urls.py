"""Auth URL routes.

Two separate login surfaces, deliberately disjoint — see views.py.
"""

from django.urls import path

from .views import CSRFView, LoginView, LogoutView, MeView, PlatformLoginView

urlpatterns = [
    path('csrf/', CSRFView.as_view(), name='auth-csrf'),
    path('login/', LoginView.as_view(), name='auth-login'),
    path('platform/login/', PlatformLoginView.as_view(), name='auth-platform-login'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('me/', MeView.as_view(), name='auth-me'),
]
