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


class Charge(TenantedModel):
    """One successful (or attempted) card charge against an invoice.

    Append-only by design — we never UPDATE a charge once it lands
    in succeeded / failed terminal state. Refunds are tracked as
    separate ``Refund`` rows that reference back, with
    ``refunded_cents`` denormalized here for fast "is this fully
    refunded?" filtering.

    Created in two paths:
      - At "Charge card" submit time (status='pending' initially)
      - Reconciled to terminal state by the ``payment_intent.*``
        webhook handler

    The webhook is the source of truth for terminal state — the
    initial API response from Stripe could be optimistic + we want
    a single code path that handles both the success-on-submit case
    and the 3DS-challenge-then-succeed case identically.

    HIPAA: no PHI here. Card details are stored only as the
    PCI-safe last4 + brand (allowed under SAQ-A). Stripe holds the
    actual PAN.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.PROTECT,
        related_name='charges',
    )
    invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.PROTECT,
        related_name='charges',
        help_text='The invoice this charge pays toward. PROTECT because deleting an invoice with charges on it would silently break the audit trail.',
    )
    merchant_account = models.ForeignKey(
        MerchantAccount,
        on_delete=models.PROTECT,
        related_name='charges',
        help_text='Which spa-side merchant account took the money. Almost always tenant.merchant_account but stored explicitly so the link survives if the spa later switches providers.',
    )

    # ── Amounts (cents, positive ints) ──────────────────────────
    #
    # Stripe sends fee + net in a separate balance_transaction that
    # we fetch when the payment_intent.succeeded webhook lands.
    # ``net_cents`` may briefly be 0 between the initial submit and
    # the webhook landing — the API surface should treat it as
    # "settling" rather than "free."
    amount_cents = models.PositiveIntegerField(
        help_text='Gross charge amount in cents. What the customer\'s card is hit for.',
    )
    fee_cents = models.PositiveIntegerField(
        default=0,
        help_text='Stripe processing fee in cents (2.9%% + 30¢ for standard cards). Filled in when the balance_transaction expands on webhook.',
    )
    net_cents = models.PositiveIntegerField(
        default=0,
        help_text='What lands in the spa\'s Stripe balance — amount_cents − fee_cents.',
    )
    currency = models.CharField(
        max_length=3,
        default='usd',
        help_text='ISO-4217 currency code, lowercase per Stripe convention.',
    )

    # ── Stripe identifiers ──────────────────────────────────────
    stripe_payment_intent_id = models.CharField(
        max_length=64,
        unique=True,
        help_text='Stripe PaymentIntent ID (pi_…). Idempotency key for the webhook handler — a duplicate event with the same PI matches the existing row.',
    )
    stripe_charge_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='Stripe Charge ID (ch_…). Empty until the payment_intent.succeeded webhook lands.',
    )

    # ── State ───────────────────────────────────────────────────
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        help_text='Lifecycle: pending → succeeded | failed. Set succeeded/failed by webhook handler; never UPDATEd after that.',
    )
    failure_code = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='Stripe failure_code on declined / errored payments (e.g. card_declined, expired_card). Helps the operator coach the customer on retry.',
    )
    failure_message = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Human-readable failure message from Stripe. Surfaced in the invoice activity log on failed charges.',
    )

    # ── PCI-safe card descriptors ───────────────────────────────
    # SAQ-A scope: we MAY store last4 + brand. We may NOT store the
    # full PAN, expiration, CVC, or any other card data. Stripe
    # holds the rest.
    last4 = models.CharField(
        max_length=4,
        blank=True,
        default='',
        help_text='Last 4 digits of the card used. PCI SAQ-A compliant; appears on the customer receipt.',
    )
    brand = models.CharField(
        max_length=24,
        blank=True,
        default='',
        help_text='Card brand (visa / mastercard / amex / discover / etc.). Mostly for receipt display.',
    )

    # ── Refund rollup (denormalized for speed) ──────────────────
    refunded_cents = models.PositiveIntegerField(
        default=0,
        help_text='Sum of every Refund row\'s amount_cents for this Charge. Denormalized so list views can filter for fully/partially refunded without joining the ledger.',
    )

    # ── Operator + audit ────────────────────────────────────────
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.PROTECT,
        related_name='charges_initiated',
        null=True, blank=True,
        help_text='Operator who hit "Charge card" on the invoice. Null when the customer self-paid through the portal.',
    )
    initiated_via = models.CharField(
        max_length=24,
        choices=[
            ('operator', 'Operator (invoice page)'),
            ('customer_portal', 'Customer portal (self-pay)'),
        ],
        default='operator',
        help_text='Where the charge originated — useful for analytics and the activity log.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Charge'
        verbose_name_plural = 'Charges'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['invoice', '-created_at']),
        ]
        constraints = [
            # Sanity: a charge cannot refund more than its amount.
            # Application code enforces this in the refund service
            # (with Stripe as the second guard), but the DB check
            # is the cheap defense against a logic bug ever
            # corrupting the ledger.
            models.CheckConstraint(
                check=models.Q(refunded_cents__lte=models.F('amount_cents')),
                name='payments_charge_refunded_lte_amount',
            ),
            models.CheckConstraint(
                check=models.Q(amount_cents__gt=0),
                name='payments_charge_amount_positive',
            ),
        ]

    def __str__(self) -> str:
        return f'Charge #{self.pk} · {self.amount_cents}¢ · {self.status}'

    @property
    def is_succeeded(self) -> bool:
        return self.status == self.Status.SUCCEEDED

    @property
    def refundable_cents(self) -> int:
        """How much of this charge can still be refunded. Used by the
        refund-amount input as a max value."""
        if not self.is_succeeded:
            return 0
        return max(0, self.amount_cents - self.refunded_cents)

    @property
    def is_fully_refunded(self) -> bool:
        return self.is_succeeded and self.refunded_cents >= self.amount_cents


class Refund(TenantedModel):
    """A single refund event against a Charge.

    Append-only ledger — partial refunds + multiple refunds against
    the same charge each get their own row. The ``Charge.refunded_cents``
    rollup is updated atomically in the service layer when a Refund
    is saved.

    Refunds are operator-initiated (no self-serve customer refund
    surface in v1). The webhook handler also creates Refund rows
    when refunds are issued through the Stripe Express dashboard
    directly — same shape, idempotent on ``stripe_refund_id``.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.PROTECT,
        related_name='refunds',
    )
    charge = models.ForeignKey(
        Charge,
        on_delete=models.PROTECT,
        related_name='refunds',
        help_text='The original charge this refund undoes (fully or partially).',
    )

    amount_cents = models.PositiveIntegerField(
        help_text='Refund amount in cents. Must be > 0 and <= charge.refundable_cents at the time the row is created.',
    )
    reason = models.CharField(
        max_length=255,
        help_text='Operator-typed reason. Stripe accepts duplicate / fraudulent / requested_by_customer as standard codes, but we accept free text for the audit trail.',
    )

    stripe_refund_id = models.CharField(
        max_length=64,
        unique=True,
        help_text='Stripe Refund ID (re_…). Idempotency key for the webhook handler.',
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        help_text='Lifecycle: pending → succeeded | failed. Card refunds usually settle in seconds but ACH refunds can take days.',
    )

    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.PROTECT,
        related_name='refunds_issued',
        null=True, blank=True,
        help_text='Operator who issued the refund. Null for refunds issued from Stripe Express dashboard directly (webhook still creates the row for the local ledger).',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Refund'
        verbose_name_plural = 'Refunds'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['charge', '-created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount_cents__gt=0),
                name='payments_refund_amount_positive',
            ),
        ]

    def __str__(self) -> str:
        return f'Refund #{self.pk} · {self.amount_cents}¢ on charge {self.charge_id}'
