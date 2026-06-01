"""Add Instagram channel support to the AI inbox.

  - AIConversation gains `channel` (sms|instagram) + `social_thread`
    FK + a new (tenant, customer, channel) unique constraint
    (replacing the old (tenant, customer) one).
  - AIConfig gains the Instagram-specific config fields.

Hand-authored. Depends on integrations.0007 so SocialThread exists
for the social_thread FK. The reverse FK (SocialMessage →
AIConversation) lands in integrations.0008, which depends on THIS
migration so AIConversation exists first.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_inbox', '0001_initial'),
        ('integrations', '0007_social_thread_profile_fields'),
    ]

    operations = [
        # ── AIConversation: channel + social_thread ──
        migrations.AddField(
            model_name='aiconversation',
            name='channel',
            field=models.CharField(
                choices=[('sms', 'SMS'), ('instagram', 'Instagram DM')],
                db_index=True,
                default='sms',
                help_text='Which transport this conversation runs over. SMS goes through Twilio (BAA-covered, PHI-safe); Instagram goes through Meta (NOT BAA-covered — booking-only, no PHI tools). Part of the conversation identity so the same customer can have separate AI state per channel.',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='aiconversation',
            name='social_thread',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ai_conversations',
                to='integrations.socialthread',
                help_text='The Instagram/social thread this conversation replies into. Null for SMS conversations. SET_NULL so deleting a thread does not cascade away the AI audit trail.',
            ),
        ),
        # Swap the unique constraint to include channel.
        migrations.RemoveConstraint(
            model_name='aiconversation',
            name='aiconversation_tenant_customer_unique',
        ),
        migrations.AddConstraint(
            model_name='aiconversation',
            constraint=models.UniqueConstraint(
                fields=('tenant', 'customer', 'channel'),
                name='aiconversation_tenant_customer_channel_unique',
            ),
        ),
        # ── AIConfig: Instagram fields ──
        migrations.AddField(
            model_name='aiconfig',
            name='instagram_enabled',
            field=models.BooleanField(
                db_index=True, default=False,
                help_text='Master switch for the Instagram DM agent. Default False. Requires the tenant to also have a connected Instagram channel (apps.integrations.Connection) and the F_SOCIAL_INTEGRATIONS feature.',
            ),
        ),
        migrations.AddField(
            model_name='aiconfig',
            name='instagram_test_mode',
            field=models.BooleanField(
                default=True,
                help_text='When True, only inbound DMs from instagram_test_username are answered; all others are audit-logged + dropped. Always True at row creation.',
            ),
        ),
        migrations.AddField(
            model_name='aiconfig',
            name='instagram_test_username',
            field=models.CharField(
                blank=True, default='', max_length=120,
                help_text='Instagram @handle (without the @) allowed to interact with the agent while instagram_test_mode is on.',
            ),
        ),
        migrations.AddField(
            model_name='aiconfig',
            name='business_phone',
            field=models.CharField(
                blank=True, default='', max_length=32,
                help_text='Phone number the Instagram agent tells customers to call for account questions (which it cannot answer over a non-BAA channel). Falls back to the primary Location phone when blank.',
            ),
        ),
    ]
