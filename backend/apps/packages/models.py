"""Package catalog + per-customer purchased packages.

A `Package` is a tenant-wide catalog template — "5 facials for $300",
"3 chemical peels + 1 free consultation" — that bundles services at
a discount from a la carte. The catalog row defines what's in the
package and the all-in price.

A `PurchasedPackage` is the customer-facing instance: the row
created when Jane bought "5 facials" on her invoice. It carries
its own balance (`PurchasedPackageItem.quantity_remaining`) and
expiration date, plus snapshots of name + price so subsequent
catalog edits don't drift Jane's record.

A `PackageRedemption` is the ledger entry: one row per redeem
event. Used at a future appointment to record "this $200 facial
was paid for via Jane's package #42, drawing down 1 of her 5
remaining credits."

Custom packages (one-off bundles built per customer rather than
pulled from the catalog) reuse the same `PurchasedPackage` model
with `source_template = NULL`. The customer-package builder UI
inserts the items inline rather than copying from a Package row,
which is why the snapshot fields exist on PurchasedPackage at all.

## Compliance posture

### HIPAA
Packages are not PHI in themselves — a customer's purchase history
is private but financial, not clinical. The link to a customer
goes through `PurchasedPackage.customer` (a tenant-scoped FK);
audit logs on every state change.

### SOC 2 (PI1.1)
Sale-time fields (price, name, validity_days, included items +
quantities) are snapshotted onto the PurchasedPackage / its items
when the source invoice closes. Subsequent edits to the catalog
Package do NOT alter customers who already bought it. Same
discipline as InvoiceLineItem.

Money is in cents. Validity is in days (nullable = no expiration).
"""

from __future__ import annotations

import re

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


def generate_package_sku(name: str) -> str:
    """Best-effort short SKU from a package name."""
    words = re.findall(r'[A-Za-z]+', name)[:3]
    initials = ''.join(w[0].upper() for w in words) if words else 'PKG'
    nums = re.findall(r'\d+', name)
    suffix = nums[0] if nums else ''
    return f'{initials}{suffix}' or 'PKG'


# ── Catalog ─────────────────────────────────────────────────────────


class Package(TenantedModel):
    """Tenant-wide catalog template for a service bundle.

    Pricing:
      - `price_cents` is the all-in package price; the customer pays
        this once when buying. Implicit discount = sum of contained
        services' price_cents − this price.
      - `tax_rate_percent` is snapshotted onto the source invoice
        line at sale time (same pattern as Service / Product).

    Validity:
      - `validity_days` of null = no expiration ("never expires").
      - Otherwise the PurchasedPackage's `expires_at` = purchased_at +
        validity_days. Past that, redemption is rejected at the
        action endpoint with a 409.

    Inventory: packages are not stocked items — there's no SKU count
    to decrement. Purchase always succeeds (subject to invoice
    state). Service redemption is the only side effect.
    """

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
        help_text='All-in package price. Snapshotted onto the invoice line.',
    )
    tax_rate_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text=(
            'Tax rate as a percent. Whether to tax packages varies by '
            'jurisdiction; default 0 lets each tenant set per-package.'
        ),
    )

    validity_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            'Days from purchase before unredeemed credits expire. '
            'Null = never expires.'
        ),
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            'Inactive packages stay on past invoices but cannot be sold '
            'on new invoices.'
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
                name='packages_unique_tenant_sku',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def price_dollars(self) -> str:
        return f'${self.price_cents / 100:.2f}'

    def save(self, *args, **kwargs):
        if not self.sku:
            base = generate_package_sku(self.name)
            candidate = base
            attempt = 1
            while Package.objects.filter(
                tenant_id=self.tenant_id, sku=candidate,
            ).exclude(pk=self.pk).exists():
                attempt += 1
                candidate = f'{base}-{attempt}'
                if attempt > 50:
                    raise RuntimeError(
                        'Could not generate a unique package SKU after 50 attempts.'
                    )
            self.sku = candidate
        super().save(*args, **kwargs)


class PackageItem(models.Model):
    """One row per (Package, Service) inclusion.

    Quantity is the number of credits the customer gets for that
    service — "5 facials" is one row with `quantity=5`. A Package
    can include multiple distinct services (3 facials + 1 lash
    consultation is two rows).

    Held outside `Package` so adding/removing an item is a single
    INSERT/DELETE rather than rewriting an array column. Deleting
    a service that's referenced here is PROTECTED (PROTECT FK)
    because pulling the rug from under a sold package would orphan
    PurchasedPackages — but ALL existing buyers' balances live on
    `PurchasedPackageItem`, which has its own FK to Service, so
    inactivating a service while leaving Package definitions intact
    is the operator workflow.
    """

    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='items',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT,
        related_name='+',
    )
    quantity = models.PositiveIntegerField(
        default=1,
        help_text='Credits granted for this service when the package is sold.',
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['package', 'service'],
                name='package_items_unique_package_service',
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='package_items_quantity_positive',
            ),
        ]

    def __str__(self):
        return f'{self.package} · {self.service} × {self.quantity}'


# ── Customer-side instance + ledger ─────────────────────────────────


class PurchasedPackage(TenantedModel):
    """A package bought by a specific customer.

    Created when an OPEN invoice line for a Package row is added.
    Lifecycle:

        PENDING  ── invoice closes ────────► ACTIVE
        ACTIVE   ── all credits redeemed ──► CONSUMED  (derived; no DB column)
        ACTIVE   ── expires_at passes ─────► EXPIRED   (derived; checked on redeem)
        ACTIVE   ── manually voided ───────► VOIDED
        PENDING  ── invoice voided ────────► VOIDED

    PENDING vs ACTIVE matters because redemption is only allowed
    against ACTIVE packages — you can't draw down credits before
    the customer has paid. The state flip happens in the invoice
    `close()` path, mirroring the inventory decrement helper.

    `source_template` is nullable: null = custom one-off package
    (built ad-hoc for one customer, not from the catalog). The
    snapshot fields (name, description, price_cents) carry the
    information the catalog row would have provided.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'   # invoice not yet closed
        ACTIVE = 'active', 'Active'
        VOIDED = 'voided', 'Voided'

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='purchased_packages',
    )
    source_template = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name='purchases',
        null=True,
        blank=True,
        help_text=(
            'Catalog package this was bought from. Null for custom '
            'one-off packages built per-customer.'
        ),
    )
    source_invoice_line = models.OneToOneField(
        'invoices.InvoiceLineItem',
        on_delete=models.PROTECT,
        related_name='purchased_package',
        null=True,
        blank=True,
        help_text=(
            'The Lumè invoice line that paid for this package. '
            'NULL for rows created by a migration importer (e.g. '
            'Zenoti) — the upstream proof-of-payment lives in '
            '`external_invoice_no` instead.'
        ),
    )

    # ── Migration provenance (Zenoti / Vagaro / etc.) ─────────────
    # When this row was created by an importer rather than a live
    # invoice close, these fields capture the upstream identifiers.
    # The importer uses `(tenant, external_source, external_id)` for
    # idempotent upsert. Live-purchased packages leave them blank.
    external_id = models.CharField(max_length=100, blank=True, db_index=True)
    external_source = models.CharField(
        max_length=50, blank=True,
        help_text="e.g. 'zenoti', 'vagaro'",
    )
    external_invoice_no = models.CharField(
        max_length=100, blank=True,
        help_text=(
            "Upstream invoice / receipt number — the operator's link "
            'back to the original system when researching a balance.'
        ),
    )
    imported_at = models.DateTimeField(null=True, blank=True)

    # Snapshots — the package definition as of purchase time.
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price_cents = models.PositiveIntegerField(default=0)
    validity_days = models.PositiveIntegerField(null=True, blank=True)

    purchased_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the source invoice closes (status flips PENDING→ACTIVE).',
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Computed at purchase time: purchased_at + validity_days.',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    void_reason = models.CharField(max_length=200, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'customer', 'status']),
            models.Index(fields=['tenant', 'status', 'expires_at']),
        ]

    def __str__(self):
        return f'{self.customer} · {self.name}'

    @property
    def is_expired(self) -> bool:
        """True when expires_at is set and now > expires_at."""
        if self.expires_at is None:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at

    @property
    def is_redeemable(self) -> bool:
        """ACTIVE + not expired + at least one credit remaining."""
        if self.status != self.Status.ACTIVE:
            return False
        if self.is_expired:
            return False
        return self.items.filter(quantity_remaining__gt=0).exists()

    @property
    def total_credits_remaining(self) -> int:
        agg = self.items.aggregate(s=models.Sum('quantity_remaining'))
        return agg['s'] or 0


class PurchasedPackageItem(models.Model):
    """Per-service balance row for a single PurchasedPackage.

    The `quantity_remaining` is the only mutating column; everything
    else is snapshotted at purchase. Decremented atomically inside
    the redemption transaction so concurrent redeems can't double-
    consume a credit.
    """

    purchased_package = models.ForeignKey(
        PurchasedPackage,
        on_delete=models.CASCADE,
        related_name='items',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        help_text=(
            'FK to the catalog Service. NULL for migration-imported '
            'rows where the upstream service name did not match any '
            'Lumè Service in the catalog — the snapshot `service_name` '
            'still displays on the customer profile so the operator '
            'can manually map / redeem it after the fact.'
        ),
    )
    # Snapshots — used for display + reporting if the catalog drifts.
    service_name = models.CharField(max_length=200)
    quantity_purchased = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField()
    # Per-credit value at purchase time (price_cents / total quantity
    # across the package would be one option, but more useful is
    # the implicit a-la-carte service price snapshot — see
    # `unit_value_cents` below).
    unit_value_cents = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Snapshot of the service's a-la-carte price at purchase "
            'time. Used as the credit value at redemption (the '
            'redemption invoice line is created at this price with '
            'a 100% discount, so reports show "$200 service paid '
            'for via package").'
        ),
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['purchased_package', 'service'],
                name='purchased_package_items_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_remaining__lte=models.F('quantity_purchased')),
                name='purchased_package_items_remaining_lte_purchased',
            ),
        ]

    def __str__(self):
        return f'{self.service_name} · {self.quantity_remaining}/{self.quantity_purchased}'


class PackageRedemption(TenantedModel):
    """Ledger entry: one row per redemption event.

    Append-only — never edit a redemption. To "undo" a redemption,
    create a reversing redemption with `quantity = -original` (we
    enforce non-zero, signed). Lets the audit trail show the
    sequence of events instead of mutating history.

    `invoice_line` is the redemption-side InvoiceLineItem — the
    $0-with-snapshot-value line that records "free because of
    package #42" on the customer's appointment invoice. Null
    while we still allow standalone redemption (operator marks
    a credit used without an immediate invoice — out of scope
    for v1, but the column is nullable for forward-compat).
    """

    purchased_package = models.ForeignKey(
        PurchasedPackage,
        on_delete=models.PROTECT,
        related_name='redemptions',
    )
    item = models.ForeignKey(
        PurchasedPackageItem,
        on_delete=models.PROTECT,
        related_name='redemptions',
    )
    quantity = models.IntegerField(
        help_text=(
            'Signed: positive for a normal redeem, negative for a '
            'reversal. Net of all rows across an item must equal '
            '(quantity_purchased − quantity_remaining).'
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
        related_name='package_redemptions',
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
            models.Index(fields=['tenant', 'purchased_package', '-redeemed_at']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0),
                name='package_redemptions_quantity_nonzero',
            ),
        ]

    def __str__(self):
        return f'{self.purchased_package} · {self.item.service_name} · {self.quantity}'
