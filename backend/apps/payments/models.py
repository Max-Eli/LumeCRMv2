"""Models for the payments app — spa-customer card processing.

This first chunk of Phase 2 ships ONLY the ``MerchantAccount`` model
that ties a tenant to its Stripe Connect Express account. The
``Charge`` + ``Refund`` models land in the next chunk along with the
"charge card" + "refund card" action endpoints — pausing here lets
the user complete Stripe Connect dashboard setup and smoke-test the
onboarding flow before we build the money-movement layer on top.

Architecture notes:

  - One ``MerchantAccount`` per tenant. ``provider`` distinguishes
    Stripe Connect from a future "custom merchant" path (Worldpay,
    Square, Heartland, Authorize.net) for Pro + Enterprise tenants
    that want to bring their own processor.

  - ``charges_enabled`` / ``payouts_enabled`` / ``details_submitted``
    mirror Stripe's Account object — synced by the
    ``account.updated`` webhook. We read them locally so the UI
    doesn't need a Stripe round-trip just to render the connect
    status.

  - No PHI lives here. Stripe handles all card data (SAQ-A scope).

HIPAA: Stripe is BAA-covered and PCI compliant. The payment flow
never touches our servers with card data — Stripe Elements iframes
handle entry, our backend only sees PaymentIntent IDs. Audit log
captures who connected / disconnected the merchant account.
"""

from __future__ import annotations

from django.db import models

from apps.tenants.abstract_models import TenantedModel


class MerchantAccount(TenantedModel):
    """A tenant's payment-processing relationship.

    Exactly one per tenant; created lazily the first time the owner
    clicks "Set up payments" in /org/payments. ``provider=stripe_connect``
    is the only path live in this chunk — ``custom`` is a placeholder
    for the Pro+ bring-your-own-merchant story that lands later.

    The Stripe-side identifiers + flags here are the authoritative
    local mirror of the connected account. They're refreshed by:
      - The ``account.updated`` webhook (push, when Stripe changes
        anything about the account — KYC completed, charges enabled,
        bank verification, etc.)
      - The ``refresh_account_status`` service call (pull, on demand —
        e.g. operator hits "Refresh" in /org/payments).
    """

    class Provider(models.TextChoices):
        STRIPE_CONNECT = 'stripe_connect', 'Stripe Connect'
        # Bring-your-own-merchant — for Pro + Enterprise tenants with
        # an existing Worldpay / Square / Heartland / Authorize.net
        # relationship. Implementation lands in a later chunk.
        CUSTOM = 'custom', 'Custom merchant'

    tenant = models.OneToOneField(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='merchant_account',
    )

    provider = models.CharField(
        max_length=32,
        choices=Provider.choices,
        default=Provider.STRIPE_CONNECT,
        help_text='Which payment processor this tenant uses. Stripe Connect is the self-serve default; Custom is the Pro+ bring-your-own option.',
    )

    # ── Stripe Connect identifiers + status (mirrored from Stripe) ──
    #
    # All empty for non-Stripe providers. We don't enforce that here
    # because a hypothetical future tenant might run BOTH providers
    # side-by-side (rare but legal); the model just stores whatever
    # the active provider's data is.

    stripe_account_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='Stripe Connected Account ID (e.g. acct_1Abc…). Empty for tenants that haven\'t completed Express onboarding.',
    )
    charges_enabled = models.BooleanField(
        default=False,
        help_text='True when Stripe has approved this account to accept charges. Mirrored from `account.charges_enabled` via the account.updated webhook.',
    )
    payouts_enabled = models.BooleanField(
        default=False,
        help_text='True when Stripe has approved this account to receive payouts to its bank.',
    )
    details_submitted = models.BooleanField(
        default=False,
        help_text='True once the spa completes the Stripe-hosted onboarding form. Until this flips, the connect status UI shows a "complete onboarding" prompt.',
    )

    # ── Lifecycle timestamps ─────────────────────────────────────────
    connected_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the Stripe Express account was first created for this tenant. Used for compliance reporting + ops dashboards.',
    )
    disabled_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the spa explicitly deauthorized the connection (or Stripe disabled it for compliance reasons). Set by the account.application.deauthorized webhook.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Merchant account'
        verbose_name_plural = 'Merchant accounts'
        # OneToOne already enforces uniqueness on tenant, but a named
        # constraint reads more clearly in the DB schema dump.
        constraints = [
            models.UniqueConstraint(
                fields=['tenant'],
                name='payments_one_merchant_account_per_tenant',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.tenant.slug} · {self.get_provider_display()}'

    @property
    def is_ready_to_charge(self) -> bool:
        """Frontend predicate — show the "Charge card" button only
        when this is True. Encapsulates the Stripe-mirror flags into
        a single intent-named check."""
        return (
            self.provider == self.Provider.STRIPE_CONNECT
            and bool(self.stripe_account_id)
            and self.charges_enabled
            and self.payouts_enabled
            and self.details_submitted
            and self.disabled_at is None
        )
