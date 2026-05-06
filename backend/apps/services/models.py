"""Service catalog — what each tenant offers.

`Service` is the unit a customer books and pays for: a Botox session, a facial,
a laser treatment. Holds duration, price, online-bookable flag, category, a
short SKU-style code, tax rate, and a regular-vs-addon type.

`ServiceCategory` is a tenant-customizable grouping (Injectables, Facials,
Laser, etc.) primarily used for filtering, color-coding, and job-title
eligibility rules (see `eligible_job_titles`).

Pricing is stored in cents to avoid floating-point rounding. Display layer
divides by 100 for dollars. Tax is stored as a decimal percent (e.g. 8.875
for NYC's combined rate); applied at invoice time, not stored on the line.
Internationalization (multiple currencies) is deferred to Phase 0c+ when we
deploy beyond US tenants.

Per-provider service eligibility is enforced category-side via
`ServiceCategory.eligible_job_titles`. The booking calendar (Phase 1D) reads
those rules when populating the provider dropdown for a service.
"""

import re

from django.db import models

from apps.tenants.abstract_models import TenantedModel


def generate_service_code(name: str) -> str:
    """Best-effort SKU-style code from a service name.

    Picks initials from the first 3 words and appends any leading digits
    found in the name. Examples:
        "Botox 20 units"           -> "B20"
        "Botox — 20 units"         -> "BU20" then 20 appended -> "BU20"
        "Hydrafacial"              -> "H"
        "Lip filler (1 syringe)"   -> "LF1"
    Caller is responsible for collision handling (per-tenant uniqueness).
    """
    words = re.findall(r'[A-Za-z]+', name)[:3]
    initials = ''.join(w[0].upper() for w in words) if words else 'SVC'
    nums = re.findall(r'\d+', name)
    suffix = nums[0] if nums else ''
    return f'{initials}{suffix}' or 'SVC'


class ServiceCategory(TenantedModel):
    """Tenant-customizable grouping for services.

    Holds display metadata (color, sort_order) and — more importantly — the
    *eligibility rules* for who can perform services in this category.
    `eligible_job_titles` is the source of truth. When the booking calendar
    lands (Phase 1D), it consults this M2M to filter the provider dropdown
    to staff whose `TenantMembership.job_title` is in this set.

    Empty `eligible_job_titles` = no restriction — any bookable staff member
    can be assigned. New categories ship empty so behavior is permissive
    until Owner/Manager configures rules.
    """

    name = models.CharField(max_length=100)
    color = models.CharField(
        max_length=7,
        default='#6b7280',
        help_text='Hex color used on the calendar block and the service chip.',
    )
    sort_order = models.IntegerField(default=0)
    eligible_job_titles = models.ManyToManyField(
        'tenants.JobTitle',
        blank=True,
        related_name='eligible_categories',
        help_text=(
            'Which job titles can perform services in this category. '
            'Empty = no restriction. Enforced when assigning a provider to an '
            'appointment in this category (Phase 1D).'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('tenant', 'name')]
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Service(TenantedModel):
    """A bookable, billable service offered by the tenant."""

    class ServiceType(models.TextChoices):
        REGULAR = 'regular', 'Regular service'
        ADDON = 'addon', 'Add-on'

    name = models.CharField(max_length=200)
    code = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text=(
            'Short SKU-style identifier. Auto-generated from the name on first save; '
            'editable. Unique within the tenant.'
        ),
    )
    description = models.TextField(blank=True)

    service_type = models.CharField(
        max_length=20,
        choices=ServiceType.choices,
        default=ServiceType.REGULAR,
        help_text='Regular services book on the calendar. Add-ons attach to a regular appointment.',
    )

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='services',
    )

    duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text='Time blocked on the calendar when this service is booked.',
    )
    buffer_minutes = models.PositiveIntegerField(
        default=0,
        help_text='Cleanup / setup time after each appointment, kept off the bookable schedule.',
    )

    price_cents = models.PositiveIntegerField(
        default=0,
        help_text='Price in cents (integer). Divide by 100 for the dollar amount.',
    )
    tax_rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=3,
        default=0,
        help_text='Tax rate as a percent (e.g. 8.875 for NYC combined). Applied at invoice time.',
    )

    is_bookable_online = models.BooleanField(
        default=True,
        help_text='If false, the service is staff-only — does not appear on the public booking page.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive services stay in history (existing appointments / invoices) but cannot be booked.',
    )

    sort_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['tenant', 'is_active', 'name']),
            models.Index(fields=['tenant', 'category']),
            models.Index(fields=['tenant', 'is_bookable_online']),
            models.Index(fields=['tenant', 'service_type']),
            models.Index(fields=['tenant', 'code']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'code'],
                condition=~models.Q(code=''),
                name='services_unique_tenant_code',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def price_dollars(self) -> str:
        """Pretty-printed dollar string for admin/list contexts."""
        return f'${self.price_cents / 100:.2f}'

    def save(self, *args, **kwargs):
        # Auto-generate a SKU code on first save if the user didn't provide one.
        # Retry with a numeric suffix if there's a collision within the tenant.
        if not self.code:
            base = generate_service_code(self.name)
            candidate = base
            attempt = 1
            while Service.objects.filter(
                tenant_id=self.tenant_id, code=candidate,
            ).exclude(pk=self.pk).exists():
                attempt += 1
                candidate = f'{base}-{attempt}'
                if attempt > 50:
                    raise RuntimeError('Could not generate a unique service code after 50 attempts.')
            self.code = candidate
        super().save(*args, **kwargs)
