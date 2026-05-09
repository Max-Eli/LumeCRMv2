"""Service layer for commission accrual + reversal.

Called by `apps.invoices.Invoice.close()` (accrual) and
`Invoice.reopen()` / `Invoice.void()` (reversal). Centralizes the
sign-conventions + ledger discipline so the invoice transitions
stay readable.

Idempotency:
  - Accruing on an invoice that already has ACCRUAL entries: the
    helper checks for existing UN-REVERSED accruals on each line
    and skips them. So a manual "re-accrue" never double-counts.
  - Reversing an invoice's accruals: only ACCRUAL entries that
    don't already have a REVERSAL are reversed.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.invoices.models import Invoice, InvoiceLineItem

from .models import CommissionEntry, CommissionRule, compute_commission_cents


def _membership_for_line(line: InvoiceLineItem):
    """Find the staff member who earned commission on this line.

    v1: provider on the appointment for service lines. Returns None
    when the line isn't a service or when there's no eligible
    provider (no rule, inactive rule, etc.) — caller skips the
    line in that case.
    """
    if line.service_id is None:
        return None
    appointment = line.invoice.appointment
    if appointment is None:
        return None
    return appointment.provider


def accrue_for_invoice(
    *,
    invoice: Invoice,
    by_user,
) -> list[dict]:
    """Walk every service line on `invoice` and create ACCRUAL
    ledger rows for the assigned provider's commission rule.

    Returns a list of audit-snapshot dicts so the invoice's
    `close()` audit log entry can include them.

    Caller MUST already be inside a transaction (Invoice.close()
    provides that).
    """
    snapshots: list[dict] = []
    for line in invoice.line_items.select_related('service', 'service__category').all():
        membership = _membership_for_line(line)
        if membership is None:
            continue
        # Try to load the rule. Inactive or missing → no accrual.
        try:
            rule = (
                CommissionRule.objects
                .select_related('membership')
                .get(membership=membership, is_active=True)
            )
        except CommissionRule.DoesNotExist:
            continue

        # Skip if there's already an un-reversed accrual on this
        # exact line — defends against manual re-runs.
        existing = CommissionEntry.objects.filter(
            invoice_line=line,
            kind=CommissionEntry.Kind.ACCRUAL,
        ).exclude(
            reversal__isnull=False,
        ).first()
        if existing is not None:
            continue

        category_id = (
            line.service.category_id if line.service is not None else None
        )
        rate = rule.rate_for_category(category_id)
        if rate is None or Decimal(str(rate)) <= 0:
            continue

        amount = compute_commission_cents(
            line_subtotal_cents=line.line_subtotal_cents,
            rate_percent=rate,
        )
        if amount <= 0:
            continue

        entry = CommissionEntry.objects.create(
            tenant=invoice.tenant,
            membership=membership,
            invoice=invoice,
            invoice_line=line,
            kind=CommissionEntry.Kind.ACCRUAL,
            rate_percent=rate,
            line_subtotal_cents=line.line_subtotal_cents,
            amount_cents=amount,
            by_user=by_user,
        )
        snapshots.append({
            'entry_id': entry.pk,
            'membership_id': membership.pk,
            'line_id': line.pk,
            'rate_percent': str(rate),
            'amount_cents': amount,
        })
    return snapshots


@transaction.atomic
def reverse_for_invoice(
    *,
    invoice: Invoice,
    by_user,
) -> list[dict]:
    """For every un-reversed ACCRUAL on this invoice, write a
    matching REVERSAL ledger row. Idempotent — re-running on an
    already-reversed invoice is a no-op.

    Used on invoice REOPEN (so commissions don't double-count
    when the invoice closes again) and could be used on void
    (though void only fires on OPEN invoices that never accrued).
    """
    accruals_to_reverse = (
        CommissionEntry.objects
        .filter(
            invoice=invoice,
            kind=CommissionEntry.Kind.ACCRUAL,
        )
        .exclude(reversal__isnull=False)
    )
    snapshots: list[dict] = []
    for original in accruals_to_reverse:
        reversal = CommissionEntry.objects.create(
            tenant=invoice.tenant,
            membership=original.membership,
            invoice=invoice,
            invoice_line=original.invoice_line,
            kind=CommissionEntry.Kind.REVERSAL,
            rate_percent=original.rate_percent,
            line_subtotal_cents=original.line_subtotal_cents,
            amount_cents=-original.amount_cents,
            reverses=original,
            by_user=by_user,
            note=f'reverses #{original.pk}',
        )
        snapshots.append({
            'reversal_id': reversal.pk,
            'reverses_id': original.pk,
            'membership_id': original.membership_id,
            'amount_cents': reversal.amount_cents,
        })
    return snapshots
