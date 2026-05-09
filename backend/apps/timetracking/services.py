"""Service-layer helpers for time tracking.

`clock_in()` and `clock_out()` enforce the single-open-shift
invariant atomically — DB row lock + re-check inside the
transaction. The model has no DB-level constraint preventing
multiple open shifts for the same membership because that's
expensive on Postgres (partial unique index works but conflicts
with the composite indexes already in place); the service layer
is the source of truth.
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone as djtz

from apps.tenants.models import TenantMembership

from .models import TimeEntry


class TimeTrackingError(Exception):
    """Raised when a clock-in/out invariant is violated.

    Examples:
      - Trying to clock in while already clocked in
      - Trying to clock out without an open shift
    """


@transaction.atomic
def clock_in(
    *,
    membership: TenantMembership,
    by_user,
    source: str = TimeEntry.Source.SELF,
    at: datetime | None = None,
    notes: str = '',
) -> TimeEntry:
    """Open a new shift for `membership`. Refuses if the membership
    already has an open shift (via row-locked re-check).

    `at` defaults to now; allowing a backdated parameter is mostly
    a v2 thing (manager corrections), but the column accepts it.
    """
    # Lock the membership row and re-check for an open shift inside
    # the lock. Two concurrent clock-ins serialize: the first wins,
    # the second sees the open entry and raises.
    locked = (
        TenantMembership.objects.select_for_update()
        .get(pk=membership.pk)
    )
    open_entry = TimeEntry.objects.filter(
        tenant_id=locked.tenant_id,
        membership=locked,
        clock_out_at__isnull=True,
    ).first()
    if open_entry is not None:
        raise TimeTrackingError(
            f'Already clocked in (since {open_entry.clock_in_at.isoformat()}).',
        )

    return TimeEntry.objects.create(
        tenant_id=locked.tenant_id,
        membership=locked,
        clock_in_at=at or djtz.now(),
        source=source,
        notes=notes,
        created_by=by_user,
    )


@transaction.atomic
def clock_out(
    *,
    membership: TenantMembership,
    by_user,
    at: datetime | None = None,
    notes_append: str = '',
) -> TimeEntry:
    """Close the open shift for `membership`. Refuses when there's
    no open shift to close.

    Locks the open entry inside the transaction so a concurrent
    clock-out (e.g. self + manager simultaneously) only succeeds
    once.
    """
    open_entry = (
        TimeEntry.objects.select_for_update()
        .filter(
            tenant_id=membership.tenant_id,
            membership=membership,
            clock_out_at__isnull=True,
        )
        .first()
    )
    if open_entry is None:
        raise TimeTrackingError('No open shift to clock out of.')

    now = at or djtz.now()
    if now <= open_entry.clock_in_at:
        # Defensive: should never happen with default `now`, but a
        # backdated param could violate the DB CheckConstraint.
        raise TimeTrackingError(
            'Clock-out time must be after clock-in time.',
        )

    open_entry.clock_out_at = now
    if notes_append:
        open_entry.notes = (
            (open_entry.notes + '\n' if open_entry.notes else '')
            + notes_append
        )
    open_entry.save(update_fields=['clock_out_at', 'notes', 'updated_at'])

    # `by_user` is captured here in case it differs from
    # `created_by` (e.g. someone else closed the shift). We don't
    # set `edited_*` on a normal close — those are reserved for
    # post-hoc corrections.
    return open_entry
