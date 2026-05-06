"""Invoice service helpers.

Right now this module contains the per-tenant invoice-number
generator. Other invoice-related services (PDF rendering, email
delivery, refund flow) will land here as their features ship.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import Invoice

INVOICE_NUMBER_PREFIX = 'INV'

# How many sequence digits to pad to. 4 → up to 9999 invoices per
# tenant per year, which covers any plausible single-spa annual
# volume; we widen this when a tenant approaches the cap.
INVOICE_SEQUENCE_PAD = 4

# Maximum collision-retry attempts before we give up. At single-spa
# scale collisions are vanishingly rare (concurrent creates would have
# to be on the same tenant + same year + millisecond-aligned). 5 is
# generous belt-and-suspenders.
MAX_RETRIES = 5


def generate_invoice_number(tenant, *, year: int | None = None) -> str:
    """Return the next per-tenant invoice number in `INV-YYYY-NNNN` format.

    Uses a `SELECT ... FOR UPDATE` lock on the highest-numbered
    invoice for this tenant + year so concurrent transactions
    serialize. The first-of-year case has no row to lock; the
    `UniqueConstraint` on `(tenant, invoice_number)` is the final
    backstop for that race — callers should wrap the
    `Invoice.objects.create()` in a retry loop (see
    `apps.invoices.signals.create_invoice_for_appointment`).

    `year` defaults to the current calendar year. Sequence resets on
    January 1 — INV-2026-9999 is followed by INV-2027-0001, not
    INV-2026-10000.
    """
    year = year or timezone.now().year
    prefix = f'{INVOICE_NUMBER_PREFIX}-{year}-'

    # `select_for_update` only locks rows it returns. When this query
    # returns the highest existing number, that row is locked; a
    # concurrent transaction calling this function will block on the
    # same row until ours commits, then read the new max. When the
    # query returns None (first invoice of the year), no lock is held —
    # the caller's IntegrityError-retry catches that race.
    last = (
        Invoice.objects
        .select_for_update()
        .filter(tenant=tenant, invoice_number__startswith=prefix)
        .order_by('-invoice_number')
        .first()
    )

    if last and last.invoice_number:
        try:
            last_seq = int(last.invoice_number[len(prefix):])
        except (ValueError, TypeError):
            # Unexpectedly malformed number — should never happen
            # because we control the format. Fall back to 0 so we
            # restart sequencing rather than crash.
            last_seq = 0
    else:
        last_seq = 0

    next_seq = last_seq + 1
    return f'{prefix}{next_seq:0{INVOICE_SEQUENCE_PAD}d}'


def assign_invoice_number(invoice: Invoice) -> None:
    """Assign the next invoice number to a freshly-created invoice.

    Wraps `generate_invoice_number` + a retry loop on collision. The
    caller passes an Invoice that has just been saved with
    `invoice_number=''`; we update it in-place. Idempotent — does
    nothing if the invoice already has a number.

    Must run inside an outer transaction so the SELECT FOR UPDATE
    lock holds. Use this from the signal handler after the Invoice
    row exists.
    """
    if invoice.invoice_number:
        return
    from django.db import IntegrityError
    for attempt in range(MAX_RETRIES):
        try:
            with transaction.atomic():
                number = generate_invoice_number(invoice.tenant)
                Invoice.objects.filter(pk=invoice.pk).update(invoice_number=number)
                invoice.invoice_number = number
                return
        except IntegrityError:
            if attempt == MAX_RETRIES - 1:
                raise
            continue
