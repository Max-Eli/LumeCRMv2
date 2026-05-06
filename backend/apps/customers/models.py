"""Customer (patient) models — first PHI tables in the system.

`Customer` holds clinic clientele records: identity, demographics, address,
emergency contact, medical history, marketing preferences, and migration
provenance. Inherits from `TenantedModel` so every row is tenant-scoped and
can only be queried via `Customer.objects.for_current_tenant()` in normal
request flow.

`CustomerTag` is a tenant-customizable set of labels (`VIP`, `Postpartum`,
`Allergic to lidocaine`, etc.) attached to customers via M2M.

Photos, treatment notes, and chart records are NOT on this model — those
belong to dedicated `apps.charts` (Phase 4) tables that FK back to Customer.
"""

import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.tenants.abstract_models import TenantedModel


REFERRAL_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no 0, O, 1, I to avoid handwriting mix-ups
REFERRAL_CODE_LENGTH = 8


def generate_referral_code(length: int = REFERRAL_CODE_LENGTH) -> str:
    """Random referral code from the unambiguous alphabet.

    Collision space is ~32^8 ≈ 1 trillion; uniqueness is enforced per-tenant by
    a partial unique constraint on Customer. Callers should retry on the rare
    collision rather than relying on global uniqueness.
    """
    return ''.join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(length))


class CustomerTag(TenantedModel):
    """Tenant-customizable label that can be attached to customers.

    Each tenant defines its own tag list (VIP, Allergic, Frequent No-Show, etc.).
    Tags are display-only metadata — they do NOT grant or restrict permissions.
    """

    name = models.CharField(max_length=50)
    color = models.CharField(
        max_length=7,
        default='#6b7280',
        help_text='Hex color for the chip in the UI, e.g. #6b7280',
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('tenant', 'name')]
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Customer(TenantedModel):
    """A clinic patient / client record. PHI-bearing — handle accordingly.

    Most fields are optional because real-world spas accept walk-ins with
    incomplete data (name + phone, finish the chart at check-in). Only
    `first_name`, `last_name`, and `tenant` are required.

    Front Desk staff can see basic identity + contact info but not the medical
    fields (`medical_history`, `allergies`, `medications`) — that gating is
    enforced at the serializer / API layer based on the user's
    `VIEW_CLIENT_PHI` permission.

    Provenance fields (`external_id`, `external_source`, `imported_at`) trace
    rows back to their origin in cases like the Zenoti migration. `external_id`
    is indexed so re-runs of an import can upsert idempotently.
    """

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'
        BLOCKED = 'blocked', 'Blocked'

    class Sex(models.TextChoices):
        FEMALE = 'female', 'Female'
        MALE = 'male', 'Male'
        OTHER = 'other', 'Other'
        PREFER_NOT_TO_SAY = 'prefer_not_to_say', 'Prefer not to say'

    # Identity
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)

    # Demographics — PHI
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=20, choices=Sex.choices, blank=True)

    # Address — PHI
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)

    # Emergency contact
    emergency_name = models.CharField(max_length=200, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    emergency_relationship = models.CharField(max_length=50, blank=True)

    # Medical — PHI
    medical_history = models.TextField(blank=True)
    allergies = models.TextField(blank=True)
    medications = models.TextField(blank=True)
    skin_type_fitzpatrick = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(6)],
        help_text='Fitzpatrick skin type 1–6 (relevant for laser treatments).',
    )

    # CRM
    notes = models.TextField(blank=True, help_text='General notes — visible to all staff with client access.')
    referral_source = models.CharField(max_length=100, blank=True)

    # Transactional comms preferences. Default True — booking
    # confirmations, appointment reminders, and other transactional
    # messages have implicit consent via the booking itself.
    email_opt_in = models.BooleanField(default=True)
    sms_opt_in = models.BooleanField(default=True)

    # ── Marketing-specific consent (Phase 1L / ADR 0016) ──────────
    # Separate from the transactional fields above because TCPA +
    # CAN-SPAM require **explicit** opt-in for promotional messages.
    # Default FALSE; flipped TRUE only by a deliberate customer act
    # (booking-page checkbox, replied YES, staff recording verbal
    # consent). Suppression below ALWAYS overrides — once a customer
    # opts out, that survives re-imports and re-edits.
    email_marketing_opt_in = models.BooleanField(
        default=False,
        help_text=(
            'Explicit consent for promotional / marketing emails. Default '
            'False per CAN-SPAM. Flip True only with a deliberate customer act.'
        ),
    )
    sms_marketing_opt_in = models.BooleanField(
        default=False,
        help_text=(
            'Explicit consent for promotional / marketing SMS. Default '
            'False per TCPA. Flip True only with a deliberate customer act.'
        ),
    )
    email_marketing_consent_at = models.DateTimeField(null=True, blank=True)
    sms_marketing_consent_at = models.DateTimeField(null=True, blank=True)
    email_marketing_consent_source = models.CharField(
        max_length=50, blank=True, default='',
        help_text="e.g. 'booking_form', 'manual_entry', 'import'",
    )
    sms_marketing_consent_source = models.CharField(
        max_length=50, blank=True, default='',
    )

    # Suppression — beats explicit opt-in. Once set, no marketing
    # send is allowed even if the opt-in flag flips back to True.
    # The audit log captures who flipped suppression so disputed
    # cases have provenance.
    email_marketing_suppressed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sms_marketing_suppressed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    email_marketing_suppression_source = models.CharField(
        max_length=50, blank=True, default='',
        help_text=(
            "e.g. 'unsubscribe_link', 'reply_stop', 'manual', 'bounce', 'complaint'"
        ),
    )
    sms_marketing_suppression_source = models.CharField(
        max_length=50, blank=True, default='',
    )

    # Status + tags
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    tags = models.ManyToManyField(CustomerTag, blank=True, related_name='customers')

    # Referrals (Phase 1A.2 capture layer; reward redemption lands in Phase 2H)
    referral_code = models.CharField(
        max_length=12,
        blank=True,
        db_index=True,
        help_text='Auto-generated; immutable from the API. Unique within the tenant.',
    )

    # Migration provenance
    external_id = models.CharField(max_length=100, blank=True, db_index=True)
    external_source = models.CharField(max_length=50, blank=True, help_text="e.g. 'zenoti', 'vagaro'")
    imported_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'last_name', 'first_name']),
            models.Index(fields=['tenant', 'email']),
            models.Index(fields=['tenant', 'phone']),
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'external_id']),
            models.Index(fields=['tenant', '-created_at']),
        ]
        ordering = ['-created_at']
        constraints = [
            # Partial unique — only enforced for non-empty codes so existing rows
            # without a code don't collide before the backfill runs.
            models.UniqueConstraint(
                fields=['tenant', 'referral_code'],
                condition=~models.Q(referral_code=''),
                name='customers_unique_tenant_referral_code',
            ),
        ]

    def save(self, *args, **kwargs):
        # Auto-generate a referral code on first save, retrying on the rare
        # collision. `tenant` must be set before save (the viewset does this).
        if not self.referral_code:
            for _ in range(20):
                code = generate_referral_code()
                if not Customer.objects.filter(tenant_id=self.tenant_id, referral_code=code).exists():
                    self.referral_code = code
                    break
            else:
                raise RuntimeError('Could not generate a unique referral code after 20 attempts.')
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email or f"Customer #{self.pk}"

    @property
    def full_name(self) -> str:
        """Display name — preferred name if set, otherwise first + last."""
        if self.preferred_name:
            return f"{self.preferred_name} {self.last_name}".strip()
        return f"{self.first_name} {self.last_name}".strip()
