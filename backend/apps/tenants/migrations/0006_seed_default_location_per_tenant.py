"""Backfill: every existing tenant gets one default Location, and every
existing TenantMembership is assigned to it.

This is the data half of the multi-location rollout. Schema migration 0005
created the Location + MembershipLocation tables; this one populates them
so existing tenants don't go from "address on Tenant" to "no addresses
anywhere" between sessions.

What gets copied to the seeded Location:
  - timezone, phone, email
  - address_line1, address_line2, city, state, zip_code
  - business_open_time, business_close_time

The Tenant fields are NOT removed in this migration. They stay as the
source of truth for /settings/business until Session 2 of the multi-
location work moves that page to read/write Location. After that, a
small follow-up migration will drop the duplicates from Tenant.

Why a fixed seed name + slug ("Main" / "main"): deterministic so
follow-up migrations and tests can reference it. Tenants can rename it
freely once the locations UI lands.

Reverse migration: deletes the seeded default Location for each tenant
along with its MembershipLocation rows. Safe because at this point the
data is identical to what's still on Tenant.
"""

from django.db import migrations


def seed_default_locations(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    Location = apps.get_model('tenants', 'Location')
    MembershipLocation = apps.get_model('tenants', 'MembershipLocation')

    for tenant in Tenant.objects.all():
        # Idempotency: if a default already exists (e.g. partial rerun), reuse it.
        location, _created = Location.objects.get_or_create(
            tenant=tenant,
            is_default=True,
            defaults={
                'name': 'Main',
                'slug': 'main',
                'is_active': True,
                'timezone': tenant.timezone,
                'phone': tenant.phone,
                'email': tenant.email,
                'address_line1': tenant.address_line1,
                'address_line2': tenant.address_line2,
                'city': tenant.city,
                'state': tenant.state,
                'zip_code': tenant.zip_code,
                'business_open_time': tenant.business_open_time,
                'business_close_time': tenant.business_close_time,
            },
        )

        # Assign every existing membership to this default location.
        # Use bulk_create with ignore_conflicts so reruns don't error on
        # the unique_together (membership, location).
        memberships = tenant.memberships.all()
        MembershipLocation.objects.bulk_create(
            [
                MembershipLocation(
                    membership=m,
                    location=location,
                    is_active=True,
                )
                for m in memberships
            ],
            ignore_conflicts=True,
        )


def unseed_default_locations(apps, schema_editor):
    """Remove the default Location seeded by the forward migration.

    This cascade-deletes MembershipLocation rows pointing at the default
    location. Safe at this point in the migration history because the
    same address/hours data still lives on Tenant.
    """
    Location = apps.get_model('tenants', 'Location')
    Location.objects.filter(is_default=True, name='Main', slug='main').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0005_location_membershiplocation_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_default_locations, unseed_default_locations),
    ]
