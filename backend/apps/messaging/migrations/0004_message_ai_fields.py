"""Add AI-inbox fields to Message + AI choice on MessageKind.

Hand-authored. Three new fields on Message (all optional / default-
falsy so existing rows keep their shape) and one new choice on the
`kind` enum.

Depends on ai_inbox.0001_initial because `ai_conversation` is an FK
into the AIConversation table created there.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0003_message_kind'),
        ('ai_inbox', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='kind',
            field=models.CharField(
                choices=[
                    ('manual', 'Manual (operator-typed)'),
                    ('confirmation', 'Appointment confirmation (automated)'),
                    ('reminder', 'Appointment reminder (automated)'),
                    ('review_request', 'Review request (automated)'),
                    ('ai', 'AI agent reply'),
                ],
                db_index=True,
                default='manual',
                help_text='What triggered the send. Manual = staff typed it in the inbox; the other three are automated transactional SMS mirrored into the thread so the operator can see what the customer saw.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='generated_by_ai',
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text='True for outbound rows the AI agent wrote. Drives the purple bubble + AI pill in the inbox UI. Never True on inbound rows (the AI does not author inbound messages).',
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='ai_conversation',
            field=models.ForeignKey(
                blank=True,
                help_text='Links the message to its AI-agent conversation row. Set on both inbound (when dispatched to the AI) and outbound (when the AI wrote the reply). SET_NULL so closing or deleting an AIConversation does not break the messaging audit trail.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='messages',
                to='ai_inbox.aiconversation',
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='parent_inbound_message_id',
            field=models.PositiveBigIntegerField(
                blank=True,
                db_index=True,
                help_text='For outbound AI replies: the ID of the inbound Message that triggered this turn. Drives per-inbound send idempotency — if the same inbound is processed twice (Twilio retry, double-fire), the second pass becomes a no-op because a row with this parent already exists.',
                null=True,
            ),
        ),
    ]
