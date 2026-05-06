"""Gift cards: issued cards + append-only ledger.

A `GiftCard` is a money-credit issued to a customer (or to an
unnamed recipient, for the "buy as a gift" case). It has a unique
code the recipient presents at checkout, an initial value
snapshotted at sale time, and a mutating `balance_cents` that
decrements as it's redeemed.

A `GiftCardLedger` row is the append-only audit trail: one row per
issue, redeem, reversal, or manual adjustment. The balance must
always equal `sum(ledger.amount_cents)` — not enforced as a DB
constraint, but verified by tests + property assertions in the
service-layer code.

Lifecycle:

    OPERATOR sells card on invoice
        ↓ (PENDING GiftCard tied to source line)
    Invoice closes
        ↓ (ACTIVE; ISSUE ledger row written; issued_at set)
    Customer redeems at a future checkout
        ↓ (REDEEM ledger rows; balance decrements)
    balance_cents reaches 0
        ↓ (REDEEMED — derived display state, NOT a DB column)
    Operator manually voids
        ↓ (VOIDED)
    Source invoice voided before close
        ↓ (cascade: VOIDED, source: 'invoice_voided')

## v1 scope decisions

- **No predefined denominations**: operator types in any dollar
  value at sale time. A "common denominations" catalog is easy to
  add later — same model, just a `GiftCardDenomination` parent
  with a list of preset amounts. Most small spas don't need it.
- **No physical-card SKU tracking**: the code IS the card. Tenants
  selling embossed plastic cards keep a paper log of code →
  physical inventory until inventory tracking lands (Phase 4C).
- **Single-tenant codes**: codes are unique within a tenant, NOT
  globally. Cross-tenant collision is fine; a customer can't
  redeem at a different spa anyway. Format `GC-XXXX-YYYY` with
  alphanumerics (excludes I/O/0/1 to avoid confusion).
- **No expiration auto-expiry job in v1**: the `expires_at` field
  exists; redemption checks reject past-expiry cards. A nightly
  cron that flips status to EXPIRED can land later.

## Compliance posture

### HIPAA
Gift card data is private but financial, not clinical. Tenant
scoping via `TenantedModel`. The recipient name + email are
optional and not classified as PHI when standalone — they're like
a contact detail rather than a clinical record.

### SOC 2 (PI1.1)
- `initial_value_cents` is snapshotted at sale time and never
  mutated.
- The ledger is append-only. Reversing a redeem creates a new
  REVERSAL row with positive `amount_cents`, never deletes the
  original.
- Net of all ledger rows for a card == `balance_cents`. This is
  the integrity invariant; service-layer code asserts it on
  every mutation.
"""

from __future__ import annotations

import secrets
import string

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


# Code format: GC-XXXX-YYYY where each block is 4 alphanumeric chars
# excluding I/O/0/1 (visually ambiguous in print). 32 chars × 8 = 32^8
# total combinations = ~1.1 trillion, plenty for a single-tenant
# uniqueness scope.
_CODE_ALPHABET = ''.join(
    c for c in string.ascii_uppercase + string.digits
    if c not in {'I', 'O', '0', '1'}
)
CODE_BLOCK_SIZE = 4
CODE_PREFIX = 'GC'


def generate_gift_card_code() -> str:
    """Return a fresh `GC-XXXX-YYYY` code. Caller is responsible for
    collision retry against the per-tenant uniqueness scope."""
    blocks = [
        ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_BLOCK_SIZE))
        for _ in range(2)
    ]
    return f'{CODE_PREFIX}-{blocks[0]}-{blocks[1]}'


class GiftCard(TenantedModel):
    """One issued gift card. Single source of truth for balance is
    `balance_cents`, kept in sync with the ledger by the service
    layer (tests verify the invariant `balance == sum(ledger)`).
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'         # invoice not yet closed
        ACTIVE = 'active', 'Active'
        VOIDED = 'voided', 'Voided'
        EXPIRED = 'expired', 'Expired'

    code = models.CharField(
        max_length=20,
        db_index=True,
        help_text=(
            "Customer-presented redemption code, format 'GC-XXXX-YYYY'. "
            'Auto-generated on first save; unique within tenant.'
        ),
    )

    issued_to_customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gift_cards_received',
        help_text=(
            "The customer this card was issued to. Null when sold as a gift "
            "to a non-customer (recipient won't be in the system until "
            "they walk in for a redemption)."
        ),
    )
    issued_to_name = models.CharField(
        max_length=200, blank=True, default='',
        help_text=(
            'Recipient name. When `issued_to_customer` is set, this can '
            'be left blank and the customer name is used. Required when '
            'issuing without a customer FK.'
        ),
    )
    issued_to_email = models.EmailField(
        max_length=254, blank=True, default='',
        help_text='Recipient email for the digital-card link (post-MVP).',
    )

    purchaser_customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gift_cards_purchased',
        help_text=(
            'The customer who paid (often != recipient when sold as a gift).'
        ),
    )

    source_invoice_line = models.OneToOneField(
        'invoices.InvoiceLineItem',
        on_delete=models.PROTECT,
        related_name='gift_card_issued',
        help_text='The invoice line that paid for this card.',
    )

    initial_value_cents = models.PositiveIntegerField(
        help_text='Original face value at sale time. Never mutates.',
    )
    balance_cents = models.PositiveIntegerField(
        help_text=(
            'Current redeemable balance. Mutates on every redeem / '
            'reversal / adjustment. Sum of ledger entries should equal '
            'this value (verified in tests).'
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    issued_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the source invoice closes (PENDING→ACTIVE).',
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            'Optional expiration. Null = never. Past-expiry cards are '
            'rejected at redeem-time; a nightly cron to flip status to '
            'EXPIRED is out of scope for v1.'
        ),
    )

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    void_reason = models.CharField(max_length=200, blank=True, default='')

    notes = models.TextField(
        blank=True, default='',
        help_text='Private operator notes — never shown to recipient.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'issued_to_customer']),
            models.Index(fields=['tenant', 'purchaser_customer']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'code'],
                name='gift_cards_unique_tenant_code',
            ),
        ]

    def __str__(self):
        recipient = (
            self.issued_to_name
            or (self.issued_to_customer.full_name if self.issued_to_customer else 'unknown')
        )
        return f'{self.code} ({recipient}) ${self.balance_cents / 100:.2f}'

    @property
    def initial_value_dollars(self) -> str:
        return f'${self.initial_value_cents / 100:.2f}'

    @property
    def balance_dollars(self) -> str:
        return f'${self.balance_cents / 100:.2f}'

    @property
    def is_redeemable(self) -> bool:
        """True when ACTIVE + not expired + balance > 0."""
        if self.status != self.Status.ACTIVE:
            return False
        if self.balance_cents <= 0:
            return False
        if self.expires_at is not None:
            from django.utils import timezone
            if timezone.now() > self.expires_at:
                return False
        return True

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def is_fully_redeemed(self) -> bool:
        """Display state — `balance == 0` and `status == ACTIVE`. Not a
        column because keeping a `REDEEMED` status row in sync would
        require a balance trigger we don't want."""
        return self.status == self.Status.ACTIVE and self.balance_cents == 0

    def save(self, *args, **kwargs):
        if not self.code:
            attempt = 1
            while True:
                candidate = generate_gift_card_code()
                exists = GiftCard.objects.filter(
                    tenant_id=self.tenant_id, code=candidate,
                ).exclude(pk=self.pk).exists()
                if not exists:
                    self.code = candidate
                    break
                attempt += 1
                if attempt > 50:
                    raise RuntimeError(
                        'Could not generate a unique gift card code '
                        'after 50 attempts.'
                    )
        super().save(*args, **kwargs)


class GiftCardLedger(TenantedModel):
    """Append-only ledger entry for a single gift card.

    Sign convention:
      ISSUE / ADJUSTMENT (positive) / REVERSAL → positive amount
      REDEEM / ADJUSTMENT (negative) → negative amount

    Net of all rows for a given card MUST equal that card's
    `balance_cents`. The service layer enforces this on every
    mutation; tests verify the invariant.
    """

    class Kind(models.TextChoices):
        ISSUE = 'issue', 'Issue'                # initial activation
        REDEEM = 'redeem', 'Redeem'             # spent at checkout
        REVERSAL = 'reversal', 'Reversal'       # reverses a redeem
        ADJUSTMENT = 'adjustment', 'Adjustment' # manual correction

    gift_card = models.ForeignKey(
        GiftCard,
        on_delete=models.PROTECT,
        related_name='ledger_entries',
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    amount_cents = models.IntegerField(
        help_text=(
            'Signed: positive for issue / reversal / positive '
            'adjustment, negative for redeem / negative adjustment.'
        ),
    )

    invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.PROTECT,
        related_name='gift_card_ledger_entries',
        null=True,
        blank=True,
        help_text=(
            'The invoice this entry was applied against. Null for '
            'manual adjustments + the initial ISSUE row (which '
            'references the source invoice via gift_card.source_invoice_line).'
        ),
    )

    by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+',
    )
    note = models.CharField(max_length=200, blank=True, default='')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['tenant', 'gift_card', '-recorded_at']),
            models.Index(fields=['tenant', 'invoice']),
        ]
        constraints = [
            # Issue must be positive; redeem must be negative; reversal
            # must be positive. Adjustments are signed-free.
            models.CheckConstraint(
                condition=(
                    (models.Q(kind='issue') & models.Q(amount_cents__gt=0))
                    | (models.Q(kind='redeem') & models.Q(amount_cents__lt=0))
                    | (models.Q(kind='reversal') & models.Q(amount_cents__gt=0))
                    | models.Q(kind='adjustment')
                ),
                name='gift_card_ledger_amount_sign_matches_kind',
            ),
            # Adjustments still must be non-zero — a no-op row is
            # never useful.
            models.CheckConstraint(
                condition=~models.Q(amount_cents=0),
                name='gift_card_ledger_amount_nonzero',
            ),
        ]

    def __str__(self):
        return (
            f'{self.gift_card.code} · {self.kind} · '
            f'${self.amount_cents / 100:+.2f}'
        )
