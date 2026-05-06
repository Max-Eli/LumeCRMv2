"""Retail product catalog — what each tenant sells over the counter.

`Product` is a physical (skincare, supplements, candles) or digital
(gift card top-ups, intake fees) item the tenant rings up at the
register or attaches as a line on a customer's invoice. Distinct from
`services.Service` (bookable on the calendar) and from `Package` /
`Membership` (which bundle services).

Pricing in cents to avoid float rounding (matches Service). Tax rate
stored per-product so high-tax retail vs. tax-exempt consultations
can coexist; rate is snapshotted onto the invoice line at sale time
so historical lines don't drift when an operator updates the
catalog price (financial reporting integrity, SOC 2 PI1.1).

Inventory is tracked as a single integer count. We deliberately do
NOT track lot numbers, expiration dates, or batch codes — those are
features for a real PMS / inventory system. Spas selling regulated
substances (Rx-only retinoids etc.) can flip `track_inventory=False`
and use a paper log if they need stricter chain-of-custody.

HIPAA: products are not PHI. The catalog itself is business config.
The link to a specific customer happens at invoice-line time, and
that surface is already governed by invoice-level audit logging.

SOC 2 (PI1.1, processing integrity): sale-time fields (price, tax
rate, description) are snapshotted onto the invoice line so
subsequent catalog edits cannot alter historical financial records.
"""

import re

from django.db import models

from apps.tenants.abstract_models import TenantedModel


def generate_product_sku(name: str) -> str:
    """Best-effort SKU from a product name.

    Drops 'P-' prefix risk by always producing alpha-then-num.
    Examples:
        "Vitamin C Serum 30ml"     -> "VCS30"
        "Skincare Travel Kit"      -> "STK"
        "12-pack Sunscreen"        -> "PS12"
    Caller is responsible for collision handling (per-tenant unique).
    """
    words = re.findall(r'[A-Za-z]+', name)[:3]
    initials = ''.join(w[0].upper() for w in words) if words else 'PRD'
    nums = re.findall(r'\d+', name)
    suffix = nums[0] if nums else ''
    return f'{initials}{suffix}' or 'PRD'


class ProductCategory(TenantedModel):
    """Tenant-customizable grouping for retail products.

    Pure display + filtering — no eligibility rules, no role gating.
    Categories are how operators slice the retail menu (Skincare,
    Wellness, Gift cards, Add-ons). Single category per product;
    multi-category tagging is out of scope for v1.
    """

    name = models.CharField(max_length=100)
    color = models.CharField(
        max_length=7,
        default='#6b7280',
        help_text='Hex color for the product chip on the catalog list.',
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('tenant', 'name')]
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'product categories'

    def __str__(self):
        return self.name


class Product(TenantedModel):
    """A retail item the tenant sells.

    `stock_quantity` is a signed integer so a backordered item shows
    as negative rather than silently clamping to zero — easier for
    the operator to spot when reconciling. Decrement happens at
    invoice-close time (Phase 1E flow) inside an atomic transaction
    so concurrent sales can't double-decrement.

    `track_inventory=False` is the escape hatch for items where
    stock count is meaningless (gift cards, services billed by the
    minute, etc.). When false, sales still create the invoice line
    but the stock counter is left alone.
    """

    name = models.CharField(max_length=200)
    sku = models.CharField(
        max_length=30,
        blank=True,
        db_index=True,
        help_text=(
            'Stock-keeping unit. Auto-generated from the name on first '
            'save; editable. Unique within the tenant.'
        ),
    )
    description = models.TextField(blank=True)

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )

    # Pricing — cents to avoid float rounding. `cost_cents` (wholesale)
    # is for margin reporting; never exposed to end customers.
    price_cents = models.PositiveIntegerField(
        default=0,
        help_text='Sale price in cents. Snapshotted onto invoice lines.',
    )
    cost_cents = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Wholesale cost in cents (for margin reports). Optional. '
            'Never displayed on customer-facing surfaces.'
        ),
    )
    tax_rate_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text=(
            'Tax rate as a percent (e.g. 8.875 for NYC combined). '
            'Snapshotted onto the invoice line at sale time.'
        ),
    )

    # Inventory
    track_inventory = models.BooleanField(
        default=True,
        help_text=(
            'When false, sales do not decrement stock. Use for gift '
            'cards / digital items / consultation fees.'
        ),
    )
    stock_quantity = models.IntegerField(
        default=0,
        help_text=(
            'Current count on hand. Signed integer so backorders show '
            'as negative rather than clamping to zero.'
        ),
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=0,
        help_text=(
            'When stock_quantity drops to or below this number, the '
            'product is flagged "low stock" on the catalog list. '
            '0 disables the warning.'
        ),
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            'Inactive products stay in history (existing invoice lines) '
            'but cannot be sold on new invoices.'
        ),
    )

    sort_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['tenant', 'is_active', 'name']),
            models.Index(fields=['tenant', 'category']),
            models.Index(fields=['tenant', 'sku']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'sku'],
                condition=~models.Q(sku=''),
                name='products_unique_tenant_sku',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def price_dollars(self) -> str:
        return f'${self.price_cents / 100:.2f}'

    @property
    def is_low_stock(self) -> bool:
        """True when stock at/below threshold AND tracking enabled."""
        if not self.track_inventory:
            return False
        if self.low_stock_threshold == 0:
            return False
        return self.stock_quantity <= self.low_stock_threshold

    def save(self, *args, **kwargs):
        # Auto-generate SKU on first save with collision-retry.
        if not self.sku:
            base = generate_product_sku(self.name)
            candidate = base
            attempt = 1
            while Product.objects.filter(
                tenant_id=self.tenant_id, sku=candidate,
            ).exclude(pk=self.pk).exists():
                attempt += 1
                candidate = f'{base}-{attempt}'
                if attempt > 50:
                    raise RuntimeError(
                        'Could not generate a unique product SKU after 50 attempts.'
                    )
            self.sku = candidate
        super().save(*args, **kwargs)
