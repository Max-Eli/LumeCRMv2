"""URL routes for the payments app.

Mounted at ``/api/payments/`` from the main urlconf.

This chunk:
  - GET  /api/payments/summary/             — connect status
  - POST /api/payments/onboarding-link/     — start Stripe-hosted onboarding
  - POST /api/payments/stripe-connect-webhook/  — Stripe Connect webhook

Next chunk adds:
  - POST /api/invoices/<id>/charge-card/    — Stripe Elements PaymentIntent
  - POST /api/invoices/<id>/refund/         — refund + ledger entry
"""

from django.urls import path

from apps.payments.views import (
    payments_onboarding_link,
    payments_summary,
)
from apps.payments.webhooks import stripe_connect_webhook

urlpatterns = [
    path('summary/', payments_summary, name='payments-summary'),
    path('onboarding-link/', payments_onboarding_link, name='payments-onboarding-link'),
    path('stripe-connect-webhook/', stripe_connect_webhook, name='payments-stripe-connect-webhook'),
]
