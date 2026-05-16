"""Customer acquisition tracking + Instagram identity fields. ADR 0027.

Adds:
  - `acquisition_source` enum + index (first-touch attribution)
  - `instagram_handle` field + index (social DM matching)
  - `is_social_guest` flag + index (placeholder rows from inbound DMs)

Backfill: every existing customer is classified into the right
acquisition source based on its provenance:

  - Rows with external_source='zenoti'   → 'zenoti_import'
  - Rows with external_source='vagaro'   → 'vagaro_import'
  - All other existing rows              → 'manual' (the model default)

This is a one-time backfill — new rows take their source from the
view layer that creates them (booking page → 'online_booking',
clients/new → 'manual', Zenoti importer → 'zenoti_import',
social DM ingestion → 'instagram'/etc.).
"""

from django.db import migrations, models


def _backfill_acquisition_source(apps, schema_editor):
    """Set the new field based on existing provenance signals."""
    Customer = apps.get_model('customers', 'Customer')

    # Vendor imports already carry their source string.
    Customer.objects.filter(external_source='zenoti').update(
        acquisition_source='zenoti_import',
    )
    Customer.objects.filter(external_source='vagaro').update(
        acquisition_source='vagaro_import',
    )
    # Everything else stays at the field default ('manual'). No
    # explicit UPDATE needed — Django wrote the default at column-add
    # time on the AddField below.


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0003_customer_email_marketing_consent_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='acquisition_source',
            field=models.CharField(
                choices=[
                    ('instagram', 'Instagram DM'),
                    ('facebook', 'Facebook Messenger'),
                    ('whatsapp', 'WhatsApp'),
                    ('online_booking', 'Online booking page'),
                    ('walk_in', 'Walk-in'),
                    ('referral', 'Client referral'),
                    ('zenoti_import', 'Zenoti import'),
                    ('vagaro_import', 'Vagaro import'),
                    ('manual', 'Manually added by staff'),
                    ('other', 'Other'),
                ],
                db_index=True,
                default='manual',
                help_text=(
                    'Where this customer originally entered the CRM. Immutable '
                    'after create. Drives "Revenue by acquisition source" reports.'
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='instagram_handle',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='IG handle without the @ prefix.',
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name='customer',
            name='is_social_guest',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    'True for placeholder rows created by an inbound social DM '
                    'from an unknown sender. Hidden from the main directory.'
                ),
            ),
        ),
        migrations.RunPython(
            _backfill_acquisition_source,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
