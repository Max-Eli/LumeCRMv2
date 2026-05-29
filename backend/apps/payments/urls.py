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
    charge_invoice_card,
    payments_onboarding_link,
    payments_summary,
    refund_card_charge,
)
from apps.payments.webhooks import stripe_connect_webhook

urlpatterns = [
    path('summary/', payments_summary, name='payments-summary'),
    path('onboarding-link/', payments_onboarding_link, name='payments-onboarding-link'),
    # Charge + refund actions. Charge is nested under invoice in the
    # URL to make the "what is being paid" explicit; refund is nested
    # under charge because a refund undoes a specific charge.
    path(
        'invoices/<int:invoice_id>/charge-card/',
        charge_invoice_card,
        name='payments-charge-invoice-card',
    ),
    path(
        'charges/<int:charge_id>/refund/',
        refund_card_charge,
        name='payments-refund-charge',
    ),
    path('stripe-connect-webhook/', stripe_connect_webhook, name='payments-stripe-connect-webhook'),
]
