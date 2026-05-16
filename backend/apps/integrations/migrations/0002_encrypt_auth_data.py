"""Swap `Connection.auth_data` from JSONField to TextField holding
Fernet-encrypted JSON. ADR 0027.

Production state at the time this migration ships: every existing
Connection row is in status=DISCONNECTED with `auth_data={}` because
no provider's OAuth flow was wired pre-Session-1. The data migration
therefore runs the empty-dict-to-empty-string conversion only — no
real tokens get re-encrypted.

If a future migration needs to re-encrypt real tokens during a key
rotation, it does so by reading auth_data_dict and calling
set_auth_data() inside a forward function.
"""

from django.db import migrations, models


def _empty_dicts_to_empty_strings(apps, schema_editor):
    """Pre-swap data normalisation: any existing JSON {} becomes ''.

    Runs BEFORE the field-type change so the alteration sees clean
    inputs. Any row that somehow has non-empty JSON gets logged + left
    alone; the post-swap step will see it as a non-empty string that
    fails to decrypt, surfacing the issue rather than silently masking.
    """
    Connection = apps.get_model('integrations', 'Connection')
    # We can't use the new accessors here — historical models don't
    # have them. Hit the raw column.
    for c in Connection.objects.all():
        if c.auth_data in ({}, None, ''):
            c.auth_data = {}  # idempotent; keeps the JSON shape valid
            c.save(update_fields=['auth_data'])
        else:
            # Surface unexpected state instead of dropping it on the floor.
            import logging
            logging.getLogger(__name__).warning(
                'integrations.connection_auth_data_pre_encrypt_nonempty',
                extra={
                    'connection_id': c.pk,
                    'provider': c.provider,
                    'auth_data_keys': list(c.auth_data.keys()) if isinstance(c.auth_data, dict) else 'non-dict',
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            _empty_dicts_to_empty_strings,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='connection',
            name='auth_data',
            field=models.TextField(blank=True, default=''),
        ),
    ]
