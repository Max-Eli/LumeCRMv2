"""Waitlist orchestration — public submit + dedupe.

Public submit reuses `apps.booking.services.find_or_create_customer`
so a returning customer's existing record gets reused silently. The
dedupe rule prevents spam: if a customer already has a `waiting`
entry for the same (service, location, provider, preferred_date),
re-submitting is a no-op (returns the existing entry).
"""

from __future__ import annotations

from django.db import transaction

from apps.booking.services import find_or_create_customer
from apps.services.models import Service
from apps.tenants.models import Location, Tenant, TenantMembership

from .models import WaitlistEntry


@transaction.atomic
def submit_waitlist_entry(
    *,
    tenant: Tenant,
    service: Service,
    location: Location,
    provider: TenantMembership | None,
    preferred_date,
    customer_first_name: str,
    customer_last_name: str,
    customer_email: str,
    customer_phone: str,
    notes: str = '',
) -> tuple[WaitlistEntry, bool]:
    """Create a waitlist entry from public-flow input.

    Returns ``(entry, created)`` where ``created`` is False when an
    identical waiting entry already existed (dedupe path). Caller
    can use the bool to decide whether to log a CREATE audit event
    or skip the audit on a no-op duplicate.

    "Identical" means same (customer, service, location, provider,
    preferred_date, status=waiting). Once an entry transitions out
    of waiting (contacted/booked/declined), a fresh submit creates a
    new entry — the customer is putting themselves back on the list.
    """
    customer, _was_new = find_or_create_customer(
        tenant=tenant,
        first_name=customer_first_name,
        last_name=customer_last_name,
        email=customer_email,
        phone=customer_phone,
    )

    # Dedupe: same customer + same intent + status=waiting → reuse.
    existing = (
        WaitlistEntry.objects
        .filter(
            tenant=tenant,
            customer=customer,
            service=service,
            location=location,
            provider=provider,
            preferred_date=preferred_date,
            status=WaitlistEntry.Status.WAITING,
        )
        .first()
    )
    if existing is not None:
        return existing, False

    entry = WaitlistEntry.objects.create(
        tenant=tenant,
        customer=customer,
        service=service,
        location=location,
        provider=provider,
        preferred_date=preferred_date,
        notes=notes,
        source='online',
    )
    return entry, True
