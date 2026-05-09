"""Commission rules + accrual ledger.

A `CommissionRule` is per-staff config: a base percent rate plus
optional per-service-category overrides. Setup happens once (or
when rates change); the rule then drives automatic accrual every
time an invoice that contains that staff member's service lines
gets closed.

A `CommissionEntry` is an append-only ledger row. One per earning
event. Signed amount: positive on accrual, negative on reversal.
Net of all entries for a staff member over a period IS their
commission owed for that period — no separate "settled" column.

## v1 scope decisions

- **Service lines only.** Commission accrues on service lines
  whose appointment has a provider with a CommissionRule. Product /
  package / membership commission requires a sales-attribution
  model (who SOLD vs who PERFORMED) that's deliberately deferred.
- **No tiered rates.** Flat % per service-category. Tiered rates
  ("10% under $5k/period, 15% over") need a period-aggregation
  pass at accrual time; deferred to Phase 2F session 2.
- **No manual adjustments.** Operator can't add ad-hoc earning
  rows in v1; if a manager wants to give a bonus, they do it
  outside the system. Auditable adjustments land later.
- **Accrual at invoice CLOSE.** A booked but unpaid appointment
  produces nothing; only paid revenue counts. Reversal on
  REOPEN/VOID undoes the accrual cleanly.

## Compliance posture

### HIPAA
Commission data is financial, not clinical. Tenant-scoped via
`TenantedModel`. The link to a customer is indirect (entry →
invoice → customer); no PHI on commission rows themselves.

### SOC 2 (PI1.1)
- **Snapshot.** Each entry captures the rate AND the line
  subtotal at the moment of accrual. Subsequent rate changes do
  NOT alter historical entries.
- **Append-only.** Reversing an accrual creates a new row with
  negative `amount_cents` and a `reverses` FK back to the
  original. The original is never edited or deleted. Net per
  (membership, period) is the source of truth.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


def compute_commission_cents(
    *,
    line_subtotal_cents: int,
    rate_percent: Decimal | float | str | int,
) -> int:
    """Calculate commission in cents from a line subtotal + percent
    rate. Decimal math + ROUND_HALF_UP — same convention as
    `apps.invoices.compute_line_tax_cents`.

    A zero rate produces zero — no row should ever be created with
    amount=0.
    """
    if not rate_percent:
        return 0
    rate = Decimal(str(rate_percent))
    if rate <= 0:
        return 0
    sub = Decimal(line_subtotal_cents)
    cents = (sub * rate / Decimal(100)).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP,
    )
    return int(cents)


class CommissionRule(TenantedModel):
    """Per-staff commission rule: base rate + per-category overrides.

    `is_active=False` means accrual stops for this membership
    immediately (e.g. provider went hourly + commission-free).
    Existing entries stay; only future accruals are skipped.
    """

    membership = models.OneToOneField(
        'tenants.TenantMembership',
        on_delete=models.CASCADE,
        related_name='commission_rule',
    )

    base_rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=(
            'Default commission percent on services performed by this '
            'staff member. Overridden per service category via '
            '`CommissionRuleOverride`.'
        ),
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            'When false, no new commission accrues for this staff '
            'member. Existing entries stay.'
        ),
    )

    notes = models.TextField(
        blank=True, default='',
        help_text='Private operator notes (e.g. "raise effective Mar 1").',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['membership__user__last_name', 'membership__user__first_name']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(base_rate_percent__gte=0)
                    & models.Q(base_rate_percent__lte=100)
                ),
                name='commission_rule_base_rate_0_to_100',
            ),
        ]

    def __str__(self):
        return f'{self.membership} · {self.base_rate_percent}%'

    def rate_for_category(
        self, category_id: int | None,
    ) -> Decimal:
        """Resolve the effective rate: per-category override if set,
        otherwise the base rate. Null category falls back to base."""
        if category_id is None:
            return self.base_rate_percent
        override = self.overrides.filter(category_id=category_id).first()
        return (
            override.rate_percent if override is not None
            else self.base_rate_percent
        )


class CommissionRuleOverride(models.Model):
    """One row per (rule, service-category) override.

    Lets "Sarah gets 25% on Botox, 10% on facials" work without
    creating separate rule rows per category. Resolution rule:
    line's category-override wins; falls back to rule.base_rate.
    """

    rule = models.ForeignKey(
        CommissionRule,
        on_delete=models.CASCADE,
        related_name='overrides',
    )
    category = models.ForeignKey(
        'services.ServiceCategory',
        on_delete=models.CASCADE,
        related_name='+',
    )
    rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text='Override percent for services in this category.',
    )

    class Meta:
        ordering = ['category__name']
        constraints = [
            models.UniqueConstraint(
                fields=['rule', 'category'],
                name='commission_overrides_unique_rule_category',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(rate_percent__gte=0)
                    & models.Q(rate_percent__lte=100)
                ),
                name='commission_override_rate_0_to_100',
            ),
        ]

    def __str__(self):
        return f'{self.rule.membership} · {self.category} · {self.rate_percent}%'


class CommissionEntry(TenantedModel):
    """Append-only ledger row.

    Sign convention: positive on accrual, negative on reversal.
    Net per (membership, period) is what's owed.

    `reverses` is set on REVERSAL rows back to the ACCRUAL they
    undo, so an audit can pair them up. The original is never
    edited.
    """

    class Kind(models.TextChoices):
        ACCRUAL = 'accrual', 'Accrual'
        REVERSAL = 'reversal', 'Reversal'

    membership = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='commission_entries',
    )
    invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.PROTECT,
        related_name='commission_entries',
    )
    invoice_line = models.ForeignKey(
        'invoices.InvoiceLineItem',
        on_delete=models.PROTECT,
        related_name='commission_entries',
    )

    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        db_index=True,
    )

    # Snapshots — frozen at the moment of accrual.
    rate_percent = models.DecimalField(max_digits=5, decimal_places=2)
    line_subtotal_cents = models.PositiveIntegerField()
    amount_cents = models.IntegerField(
        help_text='Signed cents: positive on accrual, negative on reversal.',
    )

    reverses = models.OneToOneField(
        'self',
        on_delete=models.PROTECT,
        related_name='reversal',
        null=True,
        blank=True,
        help_text='When kind=REVERSAL, points back at the ACCRUAL row.',
    )

    accrued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    note = models.CharField(max_length=200, blank=True, default='')

    # Audit
    by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+',
    )

    class Meta:
        ordering = ['-accrued_at']
        indexes = [
            # Hot path: per-staff per-period totals.
            models.Index(
                fields=['tenant', 'membership', '-accrued_at'],
                name='commission_per_staff_idx',
            ),
            # Audit lookup: "what did this invoice produce?"
            models.Index(
                fields=['tenant', 'invoice'],
                name='commission_per_invoice_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount_cents=0),
                name='commission_entries_amount_nonzero',
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(kind='accrual') & models.Q(amount_cents__gt=0))
                    | (models.Q(kind='reversal') & models.Q(amount_cents__lt=0))
                ),
                name='commission_entries_amount_sign_matches_kind',
            ),
        ]

    def __str__(self):
        return (
            f'{self.membership} · {self.kind} · '
            f'${self.amount_cents / 100:+.2f}'
        )
