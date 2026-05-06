"""Waitlist for the public booking surface.

A `WaitlistEntry` records a customer's interest when their preferred
date is fully booked. The operator works the list manually: see who
wants what, contact them when a slot opens (a cancellation, a new
working-hours block, or just calling around), then mark the entry
booked or declined.

State lifecycle:

    waiting ──► contacted ──► booked
        │           │           │
        ▼           ▼           ▼
    declined   declined    (terminal)

`waiting` = newly submitted, no operator action yet (the inbox).
`contacted` = staff reached out; awaiting reply.
`booked` = an actual appointment was created from this entry
           (operator records the link manually for now; v2 wires
           it as an FK).
`declined` = customer passed, schedule changed, etc. Terminal.

`expires_at` isn't set today — entries linger until the operator
clears them. Auto-expiry is a polish item once we have Celery
beat (Phase 1F territory).
"""

from django.db import models

from apps.tenants.abstract_models import TenantedModel


class WaitlistEntry(TenantedModel):
    """A customer's interest in a service when their preferred date
    is fully booked.

    Created from the public booking page (no auth) via
    `POST /api/booking/<slug>/waitlist/`, or by staff from the
    customer profile (Phase 1F polish — not in v1). Scoped to a
    specific service + location; provider is nullable for the
    "anyone available" path. The customer keys back to the existing
    `Customer` table — `find_or_create_customer` matches by phone
    or email so a returning customer's entry attaches to their
    existing record (silently — no welcome-back leak).

    Source provenance (`source='online'`) is captured for audit and
    to help the operator separate self-service entries from staff-
    created ones (when 1F lands) — same pattern as `Appointment.source`.
    """

    class Status(models.TextChoices):
        WAITING = 'waiting', 'Waiting'
        CONTACTED = 'contacted', 'Contacted'
        BOOKED = 'booked', 'Booked'
        DECLINED = 'declined', 'Declined'

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='waitlist_entries',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT,
        related_name='waitlist_entries',
    )
    location = models.ForeignKey(
        'tenants.Location',
        on_delete=models.PROTECT,
        related_name='waitlist_entries',
    )
    # Null = "anyone available." Nullable rather than enumerated
    # because the public form's provider picker has the same
    # "Anyone available" + specific-provider shape as the booking
    # flow itself; the value is whatever the customer picked.
    provider = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='waitlist_entries',
        null=True,
        blank=True,
    )

    preferred_date = models.DateField(
        help_text='The day the customer originally wanted. Operators '
                  'use this as the starting point when looking for an '
                  'opening — flex around it as needed.',
    )
    notes = models.TextField(
        blank=True,
        default='',
        help_text='Optional message from the customer ("mornings preferred", '
                  '"available any time before June"). Plain text.',
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.WAITING,
        db_index=True,
    )

    source = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="e.g. 'online' (public booking page), 'staff' (operator-added)",
    )

    # Status-transition metadata. Populated by the operator panel as
    # they work the list — captures who did what when so the audit
    # trail surfaces in the entry detail without re-querying AuditLog.
    contacted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    booked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Hot path: operator panel filters by tenant + status +
            # preferred_date for "today's waitlist" view.
            models.Index(fields=['tenant', 'status', 'preferred_date']),
            # Customer profile lookup.
            models.Index(fields=['tenant', 'customer', '-created_at']),
        ]

    def __str__(self):
        return (
            f'{self.customer.full_name} · {self.service.name} '
            f'· {self.preferred_date} ({self.get_status_display()})'
        )
