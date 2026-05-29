"""Django app config for the payments app.

The payments app wraps Stripe Connect — how SPAS charge THEIR
customers for treatments. It is intentionally NOT the SaaS-billing
app (``apps.billing``), which is how Lumè (Voxtro LLC) charges spas
for their Lumè subscription.

Two distinct Stripe integrations, two distinct app boundaries, two
distinct webhook secrets:

  apps.billing      → Stripe Billing (Voxtro LLC's platform account
                      charging spas)
  apps.payments     → Stripe Connect (spa's connected account
                      charging the spa's customers)

The connected-account architecture is **Express** (not Standard,
not Custom) — see ADR queued at docs/decisions/ for the rationale.
"""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = 'apps.payments'
    verbose_name = 'Payments (Stripe Connect)'
    default_auto_field = 'django.db.models.BigAutoField'
