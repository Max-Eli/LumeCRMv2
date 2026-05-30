"""Initial migration for the AI SMS inbox app.

Hand-authored (not generated) — review carefully if you regenerate
with makemigrations. The hand-authored shape matches the model
definitions in apps/ai_inbox/models.py and the cross-app FKs into
tenants, customers, and messaging.

This migration is the parent of the messaging extension migration
that adds Message.generated_by_ai + Message.ai_conversation —
because that FK points at AIConversation, AIConversation must
exist first.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('tenants', '0016_tenant_notifications_sent'),
        ('customers', '0005_customer_referred_by'),
        ('messaging', '0003_message_kind'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AIConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(db_index=True, default=False, help_text='Master switch for the tenant. Default False — operator must opt in through the Go-Live modal in /settings/ai-inbox after successful sandbox testing. The API + admin both reject enabling on a tenant whose twilio_from_number is empty.')),
                ('test_mode', models.BooleanField(default=True, help_text='When True, only inbound SMS from test_mode_number is processed; all other inbound numbers are audit-logged and dropped. Always True at row creation.')),
                ('test_mode_number', models.CharField(blank=True, default='', help_text='E.164 phone number that may interact with the AI in test mode.', max_length=20)),
                ('persona', models.TextField(blank=True, default='', help_text='Free-text persona description merged into the system prompt (e.g. "You\'re Avery, the friendly front-desk assistant for the demo medspa"). Must contain NO PHI.', max_length=2000)),
                ('business_hours_json', models.JSONField(blank=True, default=dict, help_text='Hours during which the AI will reply. Mirrors the shape of Location.business_hours_json. Outside hours the AI either stays silent or sends one "we\'re closed" reply per night (config flag, future work).')),
                ('booking_lead_minutes', models.PositiveIntegerField(default=120, help_text='Minimum minutes between now and the earliest bookable slot. Adds friction so an inbound at 8:55am does not book 9:00am.')),
                ('propose_slot_count', models.PositiveSmallIntegerField(default=3, help_text='How many slots the agent may propose per turn (1-9).')),
                ('daily_send_cap', models.PositiveIntegerField(default=100, help_text='Hard daily ceiling on outbound AI messages per tenant. Exceeded → escalate, no further sends today.')),
                ('monthly_exchange_cap', models.PositiveIntegerField(default=500, help_text='Included monthly exchanges for the tenant\'s plan tier. Pro 500, Enterprise 2000. Overage billed via Stripe metered usage (Phase 5).')),
                ('escalation_keywords', models.JSONField(blank=True, default=list, help_text='Extra phrases that force escalation, e.g. ["refund","manager","cancel my card"]. Matched case-insensitively against the inbound body before Claude is called.')),
                ('platform_disabled_at', models.DateTimeField(blank=True, help_text='GLOBAL KILL SWITCH. Settable by platform admins from /platform/tenants/<id>. Non-null = AI dispatch is fully blocked regardless of enabled / test_mode / per-conversation state. Clear by setting back to null (manual operator action).', null=True)),
                ('platform_disabled_reason', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='ai_config', to='tenants.tenant')),
            ],
        ),
        migrations.CreateModel(
            name='AIConversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('active', 'Active'), ('paused', 'Paused by staff'), ('escalated', 'Escalated to human'), ('closed', 'Closed')], db_index=True, default='active', max_length=12)),
                ('paused_at', models.DateTimeField(blank=True, null=True)),
                ('escalated_at', models.DateTimeField(blank=True, null=True)),
                ('escalation_reason', models.CharField(blank=True, default='', max_length=120)),
                ('last_ai_at', models.DateTimeField(blank=True, help_text='Timestamp of the most recent outbound AI message. Used by services/locks.py as the per-conversation reply lock (min 30s between AI sends).', null=True)),
                ('last_inbound_at', models.DateTimeField(blank=True, null=True)),
                ('message_count', models.PositiveIntegerField(default=0, help_text='Cumulative count of inbound + outbound messages in this conversation.')),
                ('exchange_count', models.PositiveIntegerField(default=0, help_text='Cumulative count of inbound→outbound exchanges. One exchange = one inbound + one outbound. Used as the unit of billing for AI overage.')),
                ('pending_proposal', models.JSONField(blank=True, help_text='Two-step booking state. Schema: {service_id, location_id, provider_id, proposed_at, slots: [{index, start_iso, end_iso}]}. Cleared on confirm_booking or expiry.', null=True)),
                ('pending_proposal_expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('customer', models.ForeignKey(help_text='PROTECT so customer deletion forces the conversation to be deleted first (purge_tenant_customers handles the ordering).', on_delete=django.db.models.deletion.PROTECT, related_name='ai_conversations', to='customers.customer')),
                ('paused_by', models.ForeignKey(blank=True, help_text='Staff user who clicked "Pause AI" (null if not paused or user since deleted).', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ai_conversations', to='tenants.tenant')),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('tenant', 'customer'), name='aiconversation_tenant_customer_unique'),
                ],
                'indexes': [
                    models.Index(fields=['tenant', 'status', '-updated_at'], name='ai_inbox_ai_tenant__7e7f3b_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='AIToolCall',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tool_name', models.CharField(db_index=True, max_length=64)),
                ('input_json', models.JSONField(blank=True, default=dict)),
                ('output_json', models.JSONField(blank=True, default=dict)),
                ('success', models.BooleanField(db_index=True, default=True)),
                ('error_message', models.CharField(blank=True, default='', max_length=500)),
                ('latency_ms', models.PositiveIntegerField(default=0)),
                ('model_used', models.CharField(blank=True, default='', help_text='Bedrock model ID that produced this tool call, if applicable.', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tool_calls', to='ai_inbox.aiconversation')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenants.tenant')),
                ('triggered_by_message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='messaging.message')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['tenant', '-created_at'], name='ai_inbox_ai_tenant__6a5c11_idx'),
                    models.Index(fields=['conversation', '-created_at'], name='ai_inbox_ai_convers_b34e92_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='EscalationAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.CharField(choices=[('requested_human', 'Customer asked for a person'), ('clinical_question', 'Clinical question'), ('payment_dispute', 'Payment / refund dispute'), ('complaint', 'Complaint'), ('agent_loop_limit', 'Agent hit tool-call cap'), ('daily_cap_exceeded', 'Tenant daily cap exceeded'), ('safety_outbound_blocked', 'Outbound PHI scanner blocked send'), ('unsupported_request', 'Out-of-scope (reschedule / cancel)'), ('manual_staff', 'Staff manually escalated'), ('agent_error', 'Agent crashed or LLM failed twice')], max_length=120)),
                ('reason_detail', models.TextField(blank=True, default='')),
                ('acknowledged_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('acknowledged_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alerts', to='ai_inbox.aiconversation')),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='customers.customer')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenants.tenant')),
                ('triggering_message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='messaging.message')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['tenant', 'acknowledged_at', '-created_at'], name='ai_inbox_es_tenant__f49a21_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='AIUsageDay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True)),
                ('ai_messages_sent', models.PositiveIntegerField(default=0)),
                ('ai_exchanges', models.PositiveIntegerField(default=0)),
                ('ai_tool_calls', models.PositiveIntegerField(default=0)),
                ('bedrock_input_tokens', models.PositiveIntegerField(default=0)),
                ('bedrock_output_tokens', models.PositiveIntegerField(default=0)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenants.tenant')),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('tenant', 'date'), name='aiusageday_tenant_date_unique'),
                ],
            },
        ),
    ]
