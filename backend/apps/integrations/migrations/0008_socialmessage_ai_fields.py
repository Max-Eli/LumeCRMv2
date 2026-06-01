"""Add AI-agent fields to SocialMessage (Instagram AI agent).

Mirrors the AI fields added to messaging.Message:
  - generated_by_ai (bool)
  - ai_conversation FK → ai_inbox.AIConversation
  - parent_inbound_message_id (per-inbound idempotency)

Depends on ai_inbox.0002 so AIConversation's new shape exists for
the FK target.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0007_social_thread_profile_fields'),
        ('ai_inbox', '0002_instagram_channel'),
    ]

    operations = [
        migrations.AddField(
            model_name='socialmessage',
            name='generated_by_ai',
            field=models.BooleanField(
                db_index=True, default=False,
                help_text='True for outbound rows the Instagram AI agent wrote. Drives the AI bubble + pill in the /social inbox. Never True on inbound rows.',
            ),
        ),
        migrations.AddField(
            model_name='socialmessage',
            name='ai_conversation',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='social_messages',
                to='ai_inbox.aiconversation',
                help_text='Links the message to its AI-agent conversation row. Set on inbound (when dispatched to the AI) and outbound (when the AI wrote it). SET_NULL so closing an AIConversation never breaks the social audit trail.',
            ),
        ),
        migrations.AddField(
            model_name='socialmessage',
            name='parent_inbound_message_id',
            field=models.PositiveBigIntegerField(
                blank=True, null=True, db_index=True,
                help_text='For outbound AI replies: the id of the inbound SocialMessage that triggered this turn. Drives per-inbound idempotency so a retried Meta webhook cannot double-reply.',
            ),
        ),
    ]
