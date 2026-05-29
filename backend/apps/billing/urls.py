"""URL routes for the billing app.

Mounted at ``/api/billing/`` from the main urlconf.

  - ``POST /api/billing/portal-session/`` — open Stripe billing portal
  - ``POST /api/billing/stripe-webhook/`` — Stripe webhook receiver
"""

from django.urls import path

from apps.billing.views import (
    billing_summary,
    stripe_portal_session,
    update_addon_quantity,
)
from apps.billing.webhooks import stripe_webhook

urlpatterns = [
    path('summary/', billing_summary, name='billing-summary'),
    path('addon-quantity/', update_addon_quantity, name='billing-addon-quantity'),
    path('portal-session/', stripe_portal_session, name='billing-portal-session'),
    path('stripe-webhook/', stripe_webhook, name='billing-stripe-webhook'),
]
