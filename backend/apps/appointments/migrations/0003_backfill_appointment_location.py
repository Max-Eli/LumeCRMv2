"""Backfill: every existing appointment is assigned to its tenant's
default `Location`.

Splits the multi-location rollout for appointments into the safe three-
phase pattern:

  0002 — schema: add `location` FK as nullable so existing rows aren't
         rejected by the constraint check at migration time.
  0003 — data: populate `location` for every existing row from its
         tenant's default location (the one Session 1's data migration
         seeded for each tenant).
  0004 — schema: alter `location` to non-null + add per-tenant
         consistency check, finalising the invariant that every
         appointment belongs to one site.

Why split: a single migration can't safely add a non-null FK because
the column briefly exists with NULLs before the backfill runs, which
the non-null check would reject. The three-phase pattern is the
canonical Django approach for adding required FKs to populated tables.

Reverse migration: blanks the `location` so the schema migration that
follows can also reverse cleanly. Safe at this point in history because
the calendar still falls back to the tenant default when location is
missing — no functional regression from rolling back.
"""

from django.db import migrations


def backfill_appointment_location(apps, schema_editor):
    Appointment = apps.get_model('appointments', 'Appointment')
    Location = apps.get_model('tenants', 'Location')

    # Build a {tenant_id: default_location_id} cache so we don't hit
    # the DB once per appointment row. Every tenant has exactly one
    # default (Session 1's partial unique index enforces this).
    default_by_tenant: dict[int, int] = dict(
        Location.objects
        .filter(is_default=True)
        .values_list('tenant_id', 'id')
    )

    # Update in bulk per tenant rather than row-by-row.
    for tenant_id, location_id in default_by_tenant.items():
        Appointment.objects.filter(
            tenant_id=tenant_id, location__isnull=True,
        ).update(location_id=location_id)

    # Sanity check: any unbacked rows left would be a tenant somehow
    # without a default location, which Session 1 promised is impossible.
    # Loud failure here is better than silently shipping nulls into the
    # next migration, which would then 500 on the AlterField to non-null.
    leftover = Appointment.objects.filter(location__isnull=True).count()
    if leftover > 0:
        raise RuntimeError(
            f'{leftover} appointment(s) could not be backfilled with a '
            f'default location. This indicates a tenant without an '
            f'is_default=True location, which violates the Session 1 '
            f'invariant. Investigate via Django shell before continuing.'
        )


def unbackfill_appointment_location(apps, schema_editor):
    Appointment = apps.get_model('appointments', 'Appointment')
    Appointment.objects.update(location=None)


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0002_appointment_location_alter_appointment_provider_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_appointment_location, unbackfill_appointment_location),
    ]
