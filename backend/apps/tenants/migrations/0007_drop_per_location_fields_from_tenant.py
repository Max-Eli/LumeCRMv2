"""Cleanup: drop the per-location fields that used to live on `Tenant`.

Phase 4E session 4 cleanup. The address, business hours, timezone,
and contact fields all moved to `Location` in earlier sessions:

  Session 1 (0005 + 0006) — added Location, seeded one default per
                            tenant, copied per-site fields over.
  Session 2 — `/org/locations/[id]` form became the source of truth
              for editing them; `/org/business` stripped its UI.
  Session 4 (this migration) — drop the duplicates from Tenant now
              that no live read paths reference them. The appointment
              calendar / day-window timezone reads from
              `request.location` (with no Tenant fallback after this
              migration).

Reversing this migration would re-add the columns as empty / default
values; the Session 1 backfill source is gone, so don't expect a
clean round-trip if you ever need to roll it back.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0006_seed_default_location_per_tenant'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tenant',
            name='address_line1',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='address_line2',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='business_close_time',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='business_open_time',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='city',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='email',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='phone',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='state',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='timezone',
        ),
        migrations.RemoveField(
            model_name='tenant',
            name='zip_code',
        ),
    ]
