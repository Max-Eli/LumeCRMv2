"""Membership plans + per-customer subscriptions.

A `MembershipPlan` is a tenant-wide catalog template — "Glow Club:
$99/month, includes 1 facial + 10% off everything else." A
`Subscription` is the customer-facing instance: created when Jane
buys the plan on an invoice, drawn down per visit, renewed by
selling a fresh subscription each cycle.

## v1 scope decisions

The plan calls out auto-recurring billing (Phase 2A processor
required). For v1 we explicitly defer the auto-charge — each cycle
is a manual sale on a new invoice, like packages. Owner generates
"Jane's monthly membership invoice" and marks it paid externally.
The lifecycle therefore looks like:

    OPERATOR sells plan on invoice
        ↓ (PENDING)
    Invoice closes
        ↓ (ACTIVE; current_period_started/ends set from billing_interval)
    Customer redeems credits during the period
        ↓ (SubscriptionRedemption ledger rows)
    Operator manually sells next cycle
        ↓ (creates a NEW Subscription; old one transitions to EXPIRED
           via management command or the renewal action)

When Phase 2A lands, an auto-renewal cron picks up subscriptions
whose `current_period_ends_at` is past + `auto_renew=True` and
generates the next-cycle invoice + closes it through the
processor. The data model is forward-compatible: same
`Subscription` rows, same redemption ledger, same invoice line
shape. Only the scheduler is new.

## What we explicitly DON'T model in v1

- **Cycle history**: each Subscription represents ONE billing
  cycle. To see Jane's membership history, query
  `Subscription.objects.filter(customer=jane).order_by(-started_at)`.
  Multi-cycle continuity (rollover credits, "membership age") is
  reasonable but would require a `MembershipEnrollment` parent
  table grouping cycles. Defer until tenants ask.
- **Pause/resume**: status flow is PENDING → ACTIVE → CANCELLED.
  No PAUSED state. If a customer pauses, cancel the current cycle
  and resell when they resume.
- **Auto-apply discount on services**: `member_discount_percent`
  exists on the plan but is not auto-applied at invoice time in
  v1. Operator manually overrides `unit_price_cents` when ringing
  up a discounted service for a member. Auto-apply lands when
  member-aware pricing logic is wired through the invoice flow
  (Phase 2A).
- **Custom subscriptions** (per-customer, off-catalog): packages
  have this; memberships don't, because plans are inherently
  recurring + a "custom recurring deal" is unusual at small spas.
  Catalog is the only path.

## Compliance posture

### HIPAA
Membership data is private but financial, not clinical. Tenant
scoping via `TenantedModel`. Audit logging on every state change.

### SOC 2 (PI1.1)
Sale-time fields snapshotted onto the Subscription instance
(name, description, price_cents, billing_interval,
member_discount_percent, included items). Catalog edits do NOT
alter existing subscriptions.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


def generate_plan_sku(name: str) -> str:
    """Best-effort short SKU from a plan name."""
    words = re.findall(r'[A-Za-z]+', name)[:3]
    initials = ''.join(w[0].upper() for w in words) if words else 'MBR'
    nums = re.findall(r'\d+', name)
    suffix = nums[0] if nums else ''
    return f'{initials}{suffix}' or 'MBR'


# ── Catalog ─────────────────────────────────────────────────────────


class MembershipPlan(TenantedModel):
    """Tenant-wide catalog template for a recurring membership.

    Pricing:
      - `price_cents` is the per-cycle price.
      - `billing_interval` is MONTHLY or ANNUAL. Other intervals
        (quarterly, semi-annual) can be added later as enum values.
      - `member_discount_percent` is the implicit member rate on
        a-la-carte services. NOT auto-applied at invoice time in
        v1; operator overrides manually. Stored for the day
        Phase 2A wires up auto-apply.

    Inventory: plans have no stock concept — selling a plan never
    fails on availability. The included service quotas are the only
    side effect.
    """

    class BillingInterval(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly'
        ANNUAL = 'annual', 'Annual'

    name = models.CharField(max_length=200)
    sku = models.CharField(
        max_length=30,
        blank=True,
        db_index=True,
        help_text=(
            'Short identifier. Auto-generated from the name on first '
            'save; editable. Unique within the tenant.'
        ),
    )
    description = models.TextField(blank=True)

    price_cents = models.PositiveIntegerField(
        default=0,
        help_text='Per-cycle price. Snapshotted onto the source invoice line.',
    )
    tax_rate_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text=(
            'Tax rate as a percent. Whether to tax memberships varies by '
            'jurisdiction; default 0.'
        ),
    )
    billing_interval = models.CharField(
        max_length=20,
        choices=BillingInterval.choices,
        default=BillingInterval.MONTHLY,
        help_text=(
            'How often the membership is billed. Each Subscription '
            'represents one cycle.'
        ),
    )
    member_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=(
            "Implicit member rate on a-la-carte services. Snapshotted "
            "onto the Subscription. Not auto-applied at invoice time "
            "in v1 — operator overrides unit_price_cents manually."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            'Inactive plans stay on past subscriptions but cannot be '
            'sold on new invoices.'
        ),
    )

    sort_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['tenant', 'is_active', 'name']),
            models.Index(fields=['tenant', 'sku']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'sku'],
                condition=~models.Q(sku=''),
                name='membership_plans_unique_tenant_sku',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def price_dollars(self) -> str:
        return f'${self.price_cents / 100:.2f}'

    @property
    def cycle_days(self) -> int:
        """Approximate cycle length for `current_period_ends_at`
        calculation. Annual = 365 days; calendar-month math is
        deferred to a real date helper (Phase 2A) to avoid
        drift on month-length differences."""
        return 365 if self.billing_interval == self.BillingInterval.ANNUAL else 30

    def save(self, *args, **kwargs):
        if not self.sku:
            base = generate_plan_sku(self.name)
            candidate = base
            attempt = 1
            while MembershipPlan.objects.filter(
                tenant_id=self.tenant_id, sku=candidate,
            ).exclude(pk=self.pk).exists():
                attempt += 1
                candidate = f'{base}-{attempt}'
                if attempt > 50:
                    raise RuntimeError(
                        'Could not generate a unique plan SKU after 50 attempts.'
                    )
            self.sku = candidate
        super().save(*args, **kwargs)


class MembershipPlanItem(models.Model):
    """One service inclusion line on a plan: "1 facial per cycle"."""

    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.CASCADE,
        related_name='items',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT,
        related_name='+',
    )
    quantity_per_cycle = models.PositiveIntegerField(
        default=1,
        help_text=(
            'Credits granted at the start of each billing cycle. v1 is '
            'use-it-or-lose-it — unredeemed credits do NOT carry over.'
        ),
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['plan', 'service'],
                name='membership_plan_items_unique_plan_service',
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_per_cycle__gt=0),
                name='membership_plan_items_quantity_positive',
            ),
        ]

    def __str__(self):
        return (
            f'{self.plan} · {self.service} × {self.quantity_per_cycle}/cycle'
        )


# ── Customer-side instance ──────────────────────────────────────────


class Subscription(TenantedModel):
    """One billing cycle of a customer's membership.

    Lifecycle:

        PENDING  ── invoice closes ──► ACTIVE
        ACTIVE   ── operator cancels ─► CANCELLED
        ACTIVE   ── period ends + no renew ─► EXPIRED  (cron-driven)
        PENDING  ── source invoice voided ──► CANCELLED

    Each cycle is a separate Subscription row. To see Jane's full
    membership history, query
    `Subscription.objects.filter(customer=jane).order_by(-started_at)`.
    Phase 2A will introduce a `MembershipEnrollment` parent if
    multi-cycle continuity becomes important.

    `auto_renew` is a forward-compat flag — Phase 2A will read it
    from the auto-renewal cron. v1 ignores it; renewal is manual.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'   # invoice not yet closed
        ACTIVE = 'active', 'Active'
        EXPIRED = 'expired', 'Expired'
        CANCELLED = 'cancelled', 'Cancelled'

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='subscriptions',
    )
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
    )
    source_invoice_line = models.OneToOneField(
        'invoices.InvoiceLineItem',
        on_delete=models.PROTECT,
        related_name='subscription',
        help_text='The invoice line that paid for this cycle.',
    )

    # Snapshots — the plan as of sale time.
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price_cents = models.PositiveIntegerField(default=0)
    billing_interval = models.CharField(
        max_length=20,
        choices=MembershipPlan.BillingInterval.choices,
        default=MembershipPlan.BillingInterval.MONTHLY,
    )
    member_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
    )

    started_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the source invoice closes (PENDING→ACTIVE).',
    )
    current_period_starts_at = models.DateTimeField(null=True, blank=True)
    current_period_ends_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Forward-compat for Phase 2A processor.
    auto_renew = models.BooleanField(
        default=False,
        help_text=(
            'When true (and a payment processor is wired in Phase 2A), '
            'a cron generates next-cycle invoices automatically. v1 '
            'ignores this; renewal is operator-driven.'
        ),
    )

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    cancel_reason = models.CharField(max_length=200, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'customer', 'status']),
            models.Index(fields=['tenant', 'status', 'current_period_ends_at']),
        ]

    def __str__(self):
        return f'{self.customer} · {self.name}'

    @property
    def is_in_period(self) -> bool:
        """True when ACTIVE and inside `[period_start, period_end]`."""
        if self.status != self.Status.ACTIVE:
            return False
        if not self.current_period_ends_at:
            return False
        from django.utils import timezone
        return self.current_period_starts_at <= timezone.now() <= self.current_period_ends_at

    @property
    def is_redeemable(self) -> bool:
        if not self.is_in_period:
            return False
        return self.items.filter(quantity_remaining__gt=0).exists()

    @property
    def total_credits_remaining(self) -> int:
        agg = self.items.aggregate(s=models.Sum('quantity_remaining'))
        return agg['s'] or 0


class SubscriptionItem(models.Model):
    """Per-service balance row for a single Subscription.

    `quantity_remaining` is the only mutating column; everything
    else is snapshotted at sale. Decremented atomically inside the
    redemption transaction so concurrent redeems can't double-spend.
    """

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name='items',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT,
        related_name='+',
    )
    service_name = models.CharField(max_length=200)
    quantity_per_cycle = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField()
    unit_value_cents = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Snapshot of the service's a-la-carte price at sale "
            'time. Used as the redemption line value (analogous to '
            'PurchasedPackageItem.unit_value_cents).'
        ),
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['subscription', 'service'],
                name='subscription_items_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    quantity_remaining__lte=models.F('quantity_per_cycle'),
                ),
                name='subscription_items_remaining_lte_per_cycle',
            ),
        ]

    def __str__(self):
        return (
            f'{self.service_name} · '
            f'{self.quantity_remaining}/{self.quantity_per_cycle}'
        )


class SubscriptionRedemption(TenantedModel):
    """Append-only ledger row per redeem event. Same contract as
    `PackageRedemption` — never edited; reversed by inserting a
    new row with `quantity = -original`."""

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name='redemptions',
    )
    item = models.ForeignKey(
        SubscriptionItem,
        on_delete=models.PROTECT,
        related_name='redemptions',
    )
    quantity = models.IntegerField(
        help_text=(
            'Signed: positive for a normal redeem, negative for a '
            'reversal.'
        ),
    )
    invoice_line = models.OneToOneField(
        'invoices.InvoiceLineItem',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
    )
    appointment = models.ForeignKey(
        'appointments.Appointment',
        on_delete=models.PROTECT,
        related_name='subscription_redemptions',
        null=True,
        blank=True,
    )
    by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='+',
    )
    redeemed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        ordering = ['-redeemed_at']
        indexes = [
            models.Index(fields=['tenant', 'subscription', '-redeemed_at']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0),
                name='subscription_redemptions_quantity_nonzero',
            ),
        ]

    def __str__(self):
        return f'{self.subscription} · {self.item.service_name} · {self.quantity}'
