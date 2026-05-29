"""URL routes for the billing app.

Mounted at ``/api/billing/`` from the main urlconf.

  - ``POST /api/billing/portal-session/`` — open Stripe billing portal
  - ``POST /api/billing/stripe-webhook/`` — Stripe webhook receiver
"""

from django.urls import path

from apps.billing.views import stripe_portal_session
from apps.billing.webhooks import stripe_webhook

urlpatterns = [
    path('portal-session/', stripe_portal_session, name='billing-portal-session'),
    path('stripe-webhook/', stripe_webhook, name='billing-stripe-webhook'),
]
