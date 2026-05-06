"""Backfill an Invoice for every existing appointment.

Why this migration exists
-------------------------
ADR 0007 introduces the rule that an appointment cannot be marked
``completed`` except by closing its invoice. Pre-existing appointments
in dev / staging / production already have a wide variety of statuses
(many are already ``completed``). Without an invoice row to reference,
the post-this-migration code paths would have nothing to operate on.

What this migration does
------------------------
For every appointment, create exactly one invoice with one line item
snapshotting the service's price + tax rate at migration time
(snapshotting from the appointment's `quoted_price_cents` if available,
falling back to the service's current `price_cents`).

* If the appointment is in ``Status.COMPLETED``, the invoice is created
  in ``PAID`` status with ``closed_at = appointment.completed_at`` (or
  ``updated_at`` as a fallback). ``closed_by`` is left NULL — there's
  no faithful actor to attribute pre-existing completions to. The audit
  log entry written below records this explicitly.
* If the appointment is in ``Status.CANCELLED`` or ``Status.NO_SHOW``,
  the invoice is created in ``VOID`` status with
  ``void_reason = 'backfill: appointment <status> at migration time'``.
* All other appointments get ``OPEN``.

Each invoice row gets a single ``AuditLog`` entry with
``metadata = {'source': 'backfill_migration_0002', ...}`` so the trail
is traceable post-deploy.

Idempotency
-----------
The migration only creates an invoice for appointments that don't
already have one (defensive — the unique 1:1 constraint on
``Invoice.appointment`` makes this redundant in normal operation, but
the explicit check makes a re-run safe in case anyone re-applies the
migration after a partial failure).

Reverse migration
-----------------
The reverse deletes only the invoices that this migration created
(those with ``metadata.source == 'backfill_migration_0002'`` in their
audit log). Production should never reverse this — there is no clean
reverse for "we already started using these invoice IDs in payment
records" — but local-dev rollback works.
"""

from django.db import migrations
from django.utils import timezone


def backfill_invoices(apps, schema_editor):
    Appointment = apps.get_model('appointments', 'Appointment')
    Invoice = apps.get_model('invoices', 'Invoice')
    InvoiceLineItem = apps.get_model('invoices', 'InvoiceLineItem')
    AuditLog = apps.get_model('audit', 'AuditLog')

    appts = (
        Appointment.objects
        .select_related('service', 'tenant')
        .order_by('id')
    )

    created_count = 0
    skipped_count = 0

    for appt in appts.iterator():
        if Invoice.objects.filter(appointment=appt).exists():
            skipped_count += 1
            continue

        service = appt.service
        if service is None:
            # Defensive — current FK is non-null, but historical data
            # could be wrong. Skip; record in the audit log.
            AuditLog.objects.create(
                action='create',
                resource_type='invoice',
                user=None,
                tenant=appt.tenant,
                metadata={
                    'source': 'backfill_migration_0002',
                    'skipped': True,
                    'reason': 'appointment_has_no_service',
                    'appointment_id': appt.pk,
                },
            )
            skipped_count += 1
            continue

        # Map appointment status → invoice status. The mapping is
        # deliberately conservative: only `completed` becomes `paid`;
        # cancelled/no_show become `void`; everything else is `open`.
        if appt.status == 'completed':
            invoice_status = 'paid'
            closed_at = appt.completed_at or appt.updated_at
            void_reason = ''
            voided_at = None
            payment_method = 'other'  # unknown for legacy data
            payment_reference = ''
        elif appt.status in ('cancelled', 'no_show'):
            invoice_status = 'void'
            closed_at = None
            voided_at = appt.cancelled_at or appt.updated_at
            void_reason = f'backfill: appointment {appt.status} at migration time'
            payment_method = ''
            payment_reference = ''
        else:
            invoice_status = 'open'
            closed_at = None
            voided_at = None
            void_reason = ''
            payment_method = ''
            payment_reference = ''

        unit_price = appt.quoted_price_cents or service.price_cents or 0
        # Recompute tax in pure Python so the migration doesn't import
        # the model methods (which is good practice — model definitions
        # may evolve while the migration must remain stable).
        from decimal import ROUND_HALF_UP, Decimal
        rate = Decimal(str(service.tax_rate_percent or 0))
        line_subtotal = unit_price  # qty=1
        line_tax = (
            int((Decimal(line_subtotal) * rate / Decimal(100)).quantize(
                Decimal('1'), rounding=ROUND_HALF_UP,
            )) if rate > 0 else 0
        )

        invoice = Invoice.objects.create(
            tenant=appt.tenant,
            customer=appt.customer,
            appointment=appt,
            status=invoice_status,
            subtotal_cents=line_subtotal,
            tax_cents=line_tax,
            total_cents=line_subtotal + line_tax,
            payment_method=payment_method,
            payment_reference=payment_reference,
            closed_at=closed_at,
            closed_by=None,
            voided_at=voided_at,
            voided_by=None,
            void_reason=void_reason,
            created_by=appt.created_by_id and getattr(appt, 'created_by', None) or None,
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            service=service,
            description=service.name,
            quantity=1,
            unit_price_cents=unit_price,
            tax_rate_percent=service.tax_rate_percent or 0,
            line_subtotal_cents=line_subtotal,
            line_tax_cents=line_tax,
        )

        AuditLog.objects.create(
            action='create',
            resource_type='invoice',
            resource_id=str(invoice.pk),
            user=None,
            tenant=appt.tenant,
            metadata={
                'source': 'backfill_migration_0002',
                'appointment_id': appt.pk,
                'appointment_status_at_backfill': appt.status,
                'invoice_status': invoice_status,
                'total_cents': invoice.total_cents,
            },
        )
        created_count += 1

    print(
        f'  invoices.backfill: created {created_count} invoice(s), '
        f'skipped {skipped_count} appointment(s) with existing invoices.',
    )


def reverse_backfill(apps, schema_editor):
    """Reverse only invoices created by this migration.

    Identifies them by joining against the AuditLog entries we wrote.
    Safe for local-dev rollback; production should never reverse this.
    """
    Invoice = apps.get_model('invoices', 'Invoice')
    AuditLog = apps.get_model('audit', 'AuditLog')

    backfill_ids = set(
        AuditLog.objects
        .filter(
            resource_type='invoice',
            metadata__source='backfill_migration_0002',
        )
        .exclude(resource_id='')
        .values_list('resource_id', flat=True)
    )

    if not backfill_ids:
        return

    deleted = Invoice.objects.filter(pk__in=backfill_ids).delete()
    print(f'  invoices.backfill (reverse): removed {deleted[0]} invoice row(s).')


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0001_initial'),
        ('appointments', '0001_initial'),
        ('audit', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_invoices, reverse_backfill),
    ]
