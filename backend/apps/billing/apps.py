"""Django app config for the billing app.

The billing app wraps Stripe Billing — how Lumè (legally Voxtro LLC)
charges spas for their SaaS subscription. It is intentionally NOT the
spa-customer payments app — that's ``apps.payments`` (Stripe Connect),
shipping in Phase 2.

No models live here. Subscription state mirrors Stripe and is stored
on ``Tenant`` (``plan``, ``stripe_customer_id``, ``stripe_subscription_id``,
``addon_quantities``, ``current_period_end``, ``trial_ends_at``).
"""

from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = 'apps.billing'
    verbose_name = 'Billing (Stripe subscriptions)'
