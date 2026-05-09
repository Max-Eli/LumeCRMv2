"""Employee clock-in / clock-out tracking.

A `TimeEntry` is one shift: clock_in_at always set, clock_out_at
nullable while the shift is open. Each employee can have at most
one open entry at a time (enforced in the service layer); closing
the open entry is what "clocks out."

Source field tracks how the punch happened (self / kiosk /
front-desk / manually added) so an auditor reviewing payroll can
distinguish a self-punch from a manager-edited entry.

## v1 scope decisions

- **Self-service only.** Each employee logs in (mobile or desktop)
  and clocks themselves in/out. The "kiosk" mode where front-desk
  punches others on a shared device can land later — adds
  complexity around impersonation auth + a separate "kiosk
  session" concept.
- **No shift schedules**, no overtime calculation, no break
  tracking. The TimeEntry is a raw punch record. Phase 2G
  (payroll exports) will run the math on top.
- **Manager edit/delete**, with audit metadata persisted on the
  row (`edited_at` + `edited_by`). Useful for correcting a forgot-
  to-clock-out entry.

## Compliance posture

### HIPAA
Time tracking is not PHI — punch times don't identify a patient.
Employee identity does flow through (TenantMembership → User), so
audit trail follows standard practice for personnel records.

### SOC 2 (CC7.2)
Audit log on every mutation; the row itself records the actor + edit
timestamp for in-place edits so payroll discrepancies are
reconstructable.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


class TimeEntry(TenantedModel):
    """One shift entry: clock_in → clock_out.

    `clock_out_at` null means the shift is still open. The
    "currently clocked in" list endpoint is a query for open
    entries; the model layer doesn't enforce single-open-per-
    membership at the DB level (race-free clock-in lives in
    `services.clock_in()`).
    """

    class Source(models.TextChoices):
        SELF = 'self', 'Self'
        FRONT_DESK = 'front_desk', 'Front desk'
        KIOSK = 'kiosk', 'Kiosk'
        MANUAL = 'manual', 'Manually added'

    membership = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='time_entries',
        help_text='The employee whose shift this is.',
    )

    clock_in_at = models.DateTimeField(
        db_index=True,
        help_text='When the shift started.',
    )
    clock_out_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='When the shift ended. Null while the shift is open.',
    )

    notes = models.TextField(
        blank=True, default='',
        help_text='Optional note (e.g. "covered for Sarah", "left early").',
    )

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.SELF,
        help_text='How this punch was recorded.',
    )

    # Audit metadata — separate from the AuditLog table because
    # payroll review benefits from seeing the actor + edit time
    # directly on the row.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='User who created this entry.',
    )
    edited_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when an entry is edited after the punch (manager correction).',
    )
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-clock_in_at']
        indexes = [
            models.Index(fields=['tenant', 'membership', '-clock_in_at']),
            # Hot path: "who is currently clocked in?" — open entries.
            models.Index(
                fields=['tenant', 'clock_out_at'],
                name='timetracking_open_idx',
            ),
        ]
        constraints = [
            # clock_out_at must be after clock_in_at when set. NULL
            # is allowed (open shift).
            models.CheckConstraint(
                condition=(
                    models.Q(clock_out_at__isnull=True)
                    | models.Q(clock_out_at__gt=models.F('clock_in_at'))
                ),
                name='time_entries_clock_out_after_clock_in',
            ),
        ]

    def __str__(self):
        if self.clock_out_at is None:
            return f'{self.membership} · open since {self.clock_in_at}'
        return f'{self.membership} · {self.clock_in_at} → {self.clock_out_at}'

    @property
    def is_open(self) -> bool:
        return self.clock_out_at is None

    @property
    def duration_seconds(self) -> int | None:
        """Shift length in seconds, or None while still open."""
        if self.clock_out_at is None:
            return None
        return int((self.clock_out_at - self.clock_in_at).total_seconds())
