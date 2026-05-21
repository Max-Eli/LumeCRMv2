"""Signal handlers wiring `Appointment` lifecycle into invoice creation.

Per ADR 0007: every appointment creates exactly one invoice. We hook
`post_save` on `Appointment`, gated to the create-only path, and create
the corresponding `Invoice` plus a single line item snapshot of the
service.

The whole thing runs inside `transaction.on_commit` is **not** what we
want — we want failure of invoice creation to roll back the appointment
creation. The `post_save` signal already fires inside the parent
transaction (DRF wraps `perform_create` in `atomic()` only via explicit
decorators, but Django's signals fire within whatever transaction the
caller has open). To be safe, we wrap our work in `transaction.atomic()`
ourselves so the join-point is unambiguous:

  - If the appointment was created inside an outer transaction, ours
    becomes a savepoint and rollback propagates.
  - If the appointment was saved without an outer transaction, ours is
    the transaction.

We tolerate the rare case where an `Appointment` is created without a
service (none in current code paths) by gracefully skipping invoice
creation; an audit-log entry records the skip so it's debuggable.
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.audit.services import record

from .models import Invoice, InvoiceLineItem
from .services import assign_invoice_number


@receiver(post_save, sender=Appointment, dispatch_uid='invoices.create_invoice_for_appointment')
def create_invoice_for_appointment(sender, instance: Appointment, created: bool, **kwargs):
    """Create one OPEN invoice with a snapshot line item per new appointment.

    Idempotent on the create flag (does nothing on subsequent saves —
    e.g. status transitions, reschedules). The unique 1:1 constraint on
    `Invoice.appointment` provides a database-level backstop so a bug in
    this handler can't accidentally create two invoices for one
    appointment.
    """
    if not created:
        return

    service = instance.service
    if service is None:
        # Should be impossible (FK is non-null) but defensive: log and skip
        # rather than break appointment creation entirely.
        record(
            action=AuditLog.Action.CREATE,
            resource_type='invoice',
            tenant=instance.tenant,
            metadata={
                'skipped': True,
                'reason': 'appointment_has_no_service',
                'appointment_id': instance.pk,
                'source': 'appointment_signal',
            },
        )
        return

    with transaction.atomic():
        invoice = Invoice.objects.create(
            tenant=instance.tenant,
            customer=instance.customer,
            appointment=instance,
            status=Invoice.Status.OPEN,
            created_by=instance.created_by,
        )
        # Assign the human-readable invoice number (INV-YYYY-NNNN).
        # Must run after the row exists so SELECT FOR UPDATE inside
        # generate_invoice_number can lock against concurrent creates.
        # Retries on collision; see services.assign_invoice_number.
        assign_invoice_number(invoice)
        line = InvoiceLineItem.objects.create(
            invoice=invoice,
            service=service,
            description=service.name,
            quantity=1,
            unit_price_cents=instance.quoted_price_cents or service.price_cents,
            tax_rate_percent=service.tax_rate_percent or 0,
        )
        # Remember which line bills the primary service so the calendar's
        # "change service" action can update the exact line later. Written
        # via QuerySet.update() to avoid re-entering this post_save handler.
        Appointment.objects.filter(pk=instance.pk).update(
            primary_invoice_line=line,
        )
        # Line save() rolls totals up into the invoice; reload so the audit
        # entry captures the recomputed total + the assigned invoice number.
        invoice.refresh_from_db()

        record(
            action=AuditLog.Action.CREATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            user=instance.created_by,
            tenant=instance.tenant,
            metadata={
                'source': 'appointment_signal',
                'appointment_id': instance.pk,
                'service_id': service.pk,
                'total_cents': invoice.total_cents,
            },
        )
