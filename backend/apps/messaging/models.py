"""Messaging — ad-hoc SMS / MMS conversations between spa staff and
their customers. Distinct from:

  - `apps.appointments.sms` (automated transactional: confirmation
    on booking + 24h reminder),
  - `apps.marketing` (one-to-many promotional campaigns through
    audiences + templates),
  - future `apps.integrations.social` (inbound DMs from Instagram /
    Facebook / WhatsApp — Phase 3F).

One row per message in either direction. Threading is derived from
`(tenant_id, customer_id)` ordering by `created_at` — we don't carry
a separate Conversation entity because each customer can only have
one ongoing SMS thread with the spa (it's their phone number).

PHI posture: every message body is PHI in the medical-spa context
(messages reference appointments, services, treatments). Read access
is audit-logged at the view layer; the model itself stores in
plaintext (encrypted at rest via the RDS storage-encryption KMS
key — same posture as every other PHI surface in the platform).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


class Direction(models.TextChoices):
    """Who sent the message. `OUTBOUND` = staff → customer;
    `INBOUND` = customer → staff (received via Twilio webhook).
    Stored as a string for legibility in JSON dumps + admin."""
    OUTBOUND = 'outbound', 'Outbound (staff → customer)'
    INBOUND = 'inbound', 'Inbound (customer → staff)'


class MessageStatus(models.TextChoices):
    """Lifecycle for outbound messages tracked via Twilio status
    callback. Inbound messages skip this — they're always
    `RECEIVED` on insert.

    `queued / sending / sent / delivered` are progress states;
    `failed / undelivered` are terminal failure states. Mirrors the
    `MarketingSendLog.Status` vocabulary used by the campaign-send
    path so a future refactor can DRY both onto a single delivery-
    tracking helper.
    """
    QUEUED = 'queued', 'Queued'
    SENT = 'sent', 'Sent'
    DELIVERED = 'delivered', 'Delivered'
    FAILED = 'failed', 'Failed'
    RECEIVED = 'received', 'Received (inbound)'


class Message(TenantedModel):
    """A single SMS / MMS exchanged with a customer.

    Direction-aware: outbound rows are created by staff send actions
    (and pre-populated with Twilio's Message SID for delivery
    correlation via the status callback); inbound rows are created
    by the Twilio incoming-message webhook, matched to the customer
    by phone number.
    """

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='messages',
        help_text=(
            'The customer this conversation is with. PROTECT so we '
            "don't lose message history when a customer is "
            'soft-deleted; the audit trail outlives the customer row.'
        ),
    )
    direction = models.CharField(
        max_length=10, choices=Direction.choices,
        db_index=True,
    )
    body = models.TextField(
        help_text='The SMS body. PHI — every read is audit-logged.',
    )
    status = models.CharField(
        max_length=20, choices=MessageStatus.choices,
        default=MessageStatus.QUEUED,
        db_index=True,
    )

    # Twilio correlation. Set on outbound at send-time so the status
    # callback can update this row's `status` field. Set on inbound
    # to the incoming MessageSid (for de-dup + audit traceability).
    provider_message_id = models.CharField(
        max_length=64, blank=True, default='',
        db_index=True,
        help_text='Twilio Message SID. Empty for stub-mode dev sends.',
    )

    # Phone numbers (E.164) participating in this message. `from_`
    # for inbound = the customer's phone; `to` = our TFN. Reversed
    # for outbound. Stored so the audit trail is complete even if
    # the customer's phone changes later on their Customer row.
    from_number = models.CharField(max_length=20, blank=True, default='')
    to_number = models.CharField(max_length=20, blank=True, default='')

    # MMS support: comma-separated list of media URLs Twilio hosts.
    # Empty for plain SMS. v1 stores Twilio's URLs verbatim; future
    # polish copies the bytes to our S3 + signs URLs for tenant
    # data sovereignty (Twilio retains the URLs ~24h).
    media_urls = models.TextField(
        blank=True, default='',
        help_text='Newline-separated list of MMS media URLs hosted on Twilio.',
    )

    # Who sent it (outbound only). Null for inbound — the customer
    # isn't a User, they're a Customer.
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        help_text='Staff member who composed the outbound message. Null for inbound.',
    )

    # Read-tracking — when an operator marks the thread "read." Lets
    # the UI show unread counts per customer thread.
    read_at = models.DateTimeField(null=True, blank=True)

    failure_reason = models.CharField(max_length=500, blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            # Thread-fetch — every load of a conversation does this exact query.
            models.Index(fields=['tenant', 'customer', '-created_at']),
            # Inbox / unread queries — list of customers with recent activity.
            models.Index(fields=['tenant', 'direction', '-created_at']),
        ]

    def __str__(self) -> str:
        preview = (self.body or '')[:40]
        return f'{self.direction}: {self.customer_id} → {preview}'
