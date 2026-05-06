"""Adds the per-tenant invoice_number field + backfills existing rows.

Sequence: (1) add the field with a blank default so existing rows
land with `''`, (2) walk the existing rows grouped by (tenant, year)
and assign sequential INV-YYYY-NNNN numbers in created_at order, then
(3) add the partial unique constraint. Backfill runs BEFORE the
constraint so an idempotent re-run on a partially-numbered table
doesn't double-assign.

Forward backfill is deterministic (sort by created_at, then pk).
Backwards is no-op — drop the field via the migration framework.
"""

from django.conf import settings
from django.db import migrations, models


def backfill_invoice_numbers(apps, schema_editor):
    Invoice = apps.get_model('invoices', 'Invoice')
    # Group by (tenant_id, year) and assign sequential numbers
    # in chronological order. Existing rows with non-empty
    # invoice_number are left alone (idempotent re-run).
    by_bucket: dict[tuple[int, int], int] = {}
    invoices = (
        Invoice.objects
        .filter(invoice_number='')
        .order_by('created_at', 'pk')
    )
    for inv in invoices.iterator():
        year = inv.created_at.year
        key = (inv.tenant_id, year)
        # Seed the bucket from any pre-existing numbers in case
        # backfill is being re-run after a partial completion.
        if key not in by_bucket:
            existing = (
                Invoice.objects
                .filter(
                    tenant_id=inv.tenant_id,
                    created_at__year=year,
                )
                .exclude(invoice_number='')
                .order_by('-invoice_number')
                .values_list('invoice_number', flat=True)
                .first()
            )
            if existing and existing.startswith(f'INV-{year}-'):
                try:
                    by_bucket[key] = int(existing[len(f'INV-{year}-'):])
                except (ValueError, TypeError):
                    by_bucket[key] = 0
            else:
                by_bucket[key] = 0
        by_bucket[key] += 1
        inv.invoice_number = f'INV-{year}-{by_bucket[key]:04d}'
        inv.save(update_fields=['invoice_number'])


def unbackfill_invoice_numbers(apps, schema_editor):
    # Reverse: blank the invoice_number on every row. The field
    # itself is dropped by the AddField reverse op, so this is
    # mostly defensive — keeps the reverse migration clean if a
    # subsequent migration depends on intermediate state.
    Invoice = apps.get_model('invoices', 'Invoice')
    Invoice.objects.update(invoice_number='')


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0004_appointment_location_required'),
        ('customers', '0002_add_referral_code'),
        ('invoices', '0002_backfill_from_appointments'),
        ('tenants', '0008_providerschedule'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='invoice_number',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text=(
                    'Human-readable invoice number, format '
                    'INV-YYYY-NNNN. Per-tenant sequential, resets '
                    'each calendar year.'
                ),
                max_length=20,
            ),
        ),
        # Data step — assign numbers to existing rows BEFORE the
        # unique constraint lands so we don't have a moment where
        # the constraint exists but rows are still blank.
        migrations.RunPython(
            backfill_invoice_numbers,
            reverse_code=unbackfill_invoice_numbers,
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(
                condition=models.Q(('invoice_number', ''), _negated=True),
                fields=('tenant', 'invoice_number'),
                name='invoices_invoice_number_unique_per_tenant',
            ),
        ),
    ]
