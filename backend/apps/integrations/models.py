"""Integration connection model.

One `Connection` row per (tenant, provider). Stores OAuth-grant data
needed to call the provider's API on the tenant's behalf.

`auth_data` is a TextField holding a Fernet-encrypted JSON blob.
Callers must NEVER read or write the field directly:

  # WRONG — leaks ciphertext / breaks decryption
  connection.auth_data = {'access_token': '...'}

  # CORRECT
  connection.set_auth_data({'access_token': '...'})
  payload = connection.auth_data_dict  # → {'access_token': '...'}

The opaque-string default is deliberate (see ADR 0027 §1) — admin /
DRF / accidental serialisation must NOT leak decrypted tokens.
"""

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel
from .security import decrypt_auth_data, encrypt_auth_data


class Connection(TenantedModel):
    """A tenant's OAuth-connected external integration."""

    class Provider(models.TextChoices):
        META_FACEBOOK = 'meta_facebook', 'Facebook Page Messenger'
        META_INSTAGRAM = 'meta_instagram', 'Instagram Business DMs'
        META_WHATSAPP = 'meta_whatsapp', 'WhatsApp Business'

    class Status(models.TextChoices):
        # No active connection. Default state for a brand-new tenant.
        DISCONNECTED = 'disconnected', 'Disconnected'
        # OAuth flow started but not completed (user clicked "Connect"
        # and is in the middle of the provider's consent screen).
        # Times out if the redirect doesn't come back inside ~10 min.
        CONNECTING = 'connecting', 'Connecting'
        # Active. Tokens valid, webhooks subscribed.
        CONNECTED = 'connected', 'Connected'
        # Was connected; provider rejected our last call (token
        # expired, scope revoked by user, app suspended). Operator
        # needs to reconnect to restore service.
        ERROR = 'error', 'Error'

    provider = models.CharField(max_length=32, choices=Provider.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DISCONNECTED,
        db_index=True,
    )

    # Identifier of the connected account on the provider's side
    # (Page ID, Instagram Business Account ID, WhatsApp Business
    # Account ID). Empty until OAuth completes in Session 2.
    external_id = models.CharField(max_length=128, blank=True, default='')
    # Human-readable name of the connected account, displayed in the
    # settings UI ("Acme Med Spa" instead of "1043...").
    external_name = models.CharField(max_length=256, blank=True, default='')

    # OAuth grant payload — access_token, refresh_token (where
    # applicable), granted_scopes, token expiry. Stored as a Fernet-
    # encrypted JSON blob via `apps.integrations.security`. Always
    # access via `auth_data_dict` / `set_auth_data()` — direct reads
    # produce ciphertext. ADR 0027 § 1.
    auth_data = models.TextField(blank=True, default='')

    # Last successful sync from the provider (most recent webhook
    # delivered, or most recent manual reconcile run). Null until
    # the connection has produced any traffic.
    last_synced_at = models.DateTimeField(null=True, blank=True)

    # Last error metadata — populated when status flips to ERROR.
    # Captured for the operator's reconnection UX ("token expired"
    # vs "scope revoked" vs "app suspended" all need different
    # remediation copy).
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.CharField(max_length=500, blank=True, default='')

    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['provider']
        indexes = [
            models.Index(fields=['tenant', 'provider']),
            models.Index(fields=['tenant', 'status']),
        ]
        constraints = [
            # One connection per (tenant, provider). If a tenant wants
            # to switch the connected Page, the existing row is
            # disconnected first, then a new OAuth flow updates the
            # same row in-place.
            models.UniqueConstraint(
                fields=['tenant', 'provider'],
                name='integrations_one_connection_per_tenant_provider',
            ),
        ]

    def __str__(self):
        return f'{self.get_provider_display()} ({self.get_status_display()})'

    # ── Encrypted auth_data accessors ──────────────────────────────
    #
    # Never read or write `self.auth_data` directly outside these
    # helpers. The raw column is opaque ciphertext.

    @property
    def auth_data_dict(self) -> dict:
        """Decrypt + return the auth payload as a dict. Empty when
        the field has never been written. Raises EncryptionError
        if the ciphertext is corrupt or the key has rotated past."""
        return decrypt_auth_data(self.auth_data)

    def set_auth_data(self, value: dict) -> None:
        """Encrypt + assign. Caller must call `save()` to persist."""
        self.auth_data = encrypt_auth_data(value or {})

    def clear_auth_data(self) -> None:
        """Wipe the auth payload (used on disconnect)."""
        self.auth_data = ''


# ── Social messaging (ADR 0027 §6) ──────────────────────────────────
#
# A SocialThread is one ongoing conversation between the tenant's
# connected social account and one customer. A SocialMessage is one
# inbound or outbound message inside it.
#
# These are deliberately separate from `apps.messaging.Message` (SMS):
#   - Different identifier shape (IG scoped user IDs vs E.164 phone)
#   - Different status enum (Meta delivery receipts vs Twilio lifecycle)
#   - Different opt-out semantics (block-at-IG-level vs STOP keyword)
#   - Different PHI policy (Meta forbids PHI in DMs)
# ADR 0022 anticipated the split.


class SocialThread(TenantedModel):
    """One ongoing conversation per (tenant, provider, external_thread_id).

    `external_thread_id` is whatever stable identifier the provider
    uses for "the other person in this thread" — for Instagram /
    Messenger, that's the PSID (page-scoped user ID) returned in
    webhook payloads as `sender.id`. We never see the user's real
    Instagram user ID; PSIDs are opaque and stable per (page, user).
    """

    class Provider(models.TextChoices):
        INSTAGRAM = 'instagram', 'Instagram'
        FACEBOOK = 'facebook', 'Facebook Messenger'
        WHATSAPP = 'whatsapp', 'WhatsApp'

    provider = models.CharField(
        max_length=16,
        choices=Provider.choices,
        db_index=True,
    )
    connection = models.ForeignKey(
        Connection,
        on_delete=models.PROTECT,
        related_name='social_threads',
        help_text=(
            'The connected account this thread belongs to. PROTECT '
            "because deleting a connection shouldn't erase message "
            'history — disconnect leaves the thread + messages intact.'
        ),
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='social_threads',
        help_text=(
            'The person on the other side. May be a social-guest row '
            '(`is_social_guest=True`) if the operator has not yet '
            'merged this conversation into an existing client record.'
        ),
    )

    external_thread_id = models.CharField(
        max_length=128,
        help_text="Provider-scoped sender ID (Meta PSID, etc.)",
    )
    external_username = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text='Human-readable @handle if known.',
    )

    last_message_at = models.DateTimeField(db_index=True)
    last_inbound_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            'When the customer last sent us a message. Used to enforce '
            "Meta's 24-hour reply window in Session 2."
        ),
    )
    read_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "When an operator last marked this thread read. Null means "
            "unread; we don't track per-message read state on the "
            "operator side, only thread-level."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'provider', 'external_thread_id'],
                name='social_thread_unique_per_tenant_provider_sender',
            ),
        ]
        indexes = [
            # Hot path: inbox list (unread first, recent first).
            models.Index(
                fields=['tenant', '-last_message_at'],
                name='social_thread_inbox_idx',
            ),
            # Per-customer thread lookup from the customer profile.
            models.Index(
                fields=['tenant', 'customer', '-last_message_at'],
                name='social_thread_per_customer_idx',
            ),
        ]

    def __str__(self):
        who = self.external_username or self.external_thread_id
        return f'{self.get_provider_display()} · {who}'


class SocialMessage(TenantedModel):
    """One message in a SocialThread.

    Idempotency: `external_message_id` is the provider's per-message
    ID (Meta `mid`). Unique within tenant so duplicate webhook
    deliveries become a no-op on `IntegrityError`.

    PHI posture: `body` may technically contain anything a customer
    types — including symptoms / treatments / personal health data.
    We treat the message body as PHI for audit + access-control
    purposes (the `apps.audit` log records reads, not content). But
    we do NOT send PHI back through Meta — outbound reply UX (Session
    2) carries an explicit operator-facing banner per ADR 0027 §7.
    """

    class Direction(models.TextChoices):
        OUTBOUND = 'outbound', 'Outbound (staff → customer)'
        INBOUND = 'inbound', 'Inbound (customer → staff)'

    class Status(models.TextChoices):
        RECEIVED = 'received', 'Received'      # inbound, persisted
        QUEUED = 'queued', 'Queued'             # outbound, awaiting send
        SENT = 'sent', 'Sent'                   # outbound, handed to provider
        DELIVERED = 'delivered', 'Delivered'    # provider confirms delivery
        READ = 'read', 'Read by recipient'      # provider read-receipt
        FAILED = 'failed', 'Failed'             # provider rejected

    thread = models.ForeignKey(
        SocialThread,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    direction = models.CharField(
        max_length=16,
        choices=Direction.choices,
        db_index=True,
    )
    body = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Text content of the message. May be empty when the message '
            'is media-only (image / video / sticker).'
        ),
    )
    media_urls = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Newline-separated provider-hosted URLs for media attachments. '
            'These expire (Meta retains for ~24h); a future polish '
            'will copy to our S3 + sign.'
        ),
    )

    external_message_id = models.CharField(
        max_length=128,
        help_text="Provider's per-message ID (Meta `mid`). Used for idempotency.",
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RECEIVED,
        db_index=True,
    )

    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='Staff user who composed the message. Outbound only.',
    )

    received_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the provider reports the message was created on their side.',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Provider-reported read receipt (NOT operator-marked read).',
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            # Idempotency fence: a retried webhook delivery for the
            # same Meta `mid` raises IntegrityError and the caller
            # swallows it. Tenant-scoped because provider IDs are
            # only stable within a single connected account.
            models.UniqueConstraint(
                fields=['tenant', 'external_message_id'],
                name='social_message_unique_external_id',
            ),
        ]
        indexes = [
            # Hot path: render a thread in chronological order.
            models.Index(
                fields=['tenant', 'thread', 'created_at'],
                name='social_msg_thread_chrono_idx',
            ),
            # Status callback lookup (Session 2 delivery receipts).
            models.Index(
                fields=['tenant', 'external_message_id'],
                name='social_msg_external_id_idx',
            ),
        ]

    def __str__(self):
        return f'{self.get_direction_display()} · {self.thread} · {self.body[:40]}'


# ── Data Deletion Requests (Meta Platform Terms requirement) ────────
#
# Meta requires every app that handles user data to provide either a
# "Data Deletion Callback URL" (programmatic — Meta POSTs when a user
# removes the app from their Facebook settings) OR a static "User
# Data Deletion Instructions URL." We implement the callback path
# because it's auditable + automatic.
#
# When a Meta user removes the app, Meta sends a `signed_request`
# POST identifying the user's FB ID. We:
#   1. Verify the HMAC signature using our App Secret
#   2. Look up the Connection by that user ID
#   3. Force-disconnect (clear tokens, status=DISCONNECTED)
#   4. Persist a DataDeletionRequest row so the user can verify
#      processing at the public status URL we return.
#
# We do NOT auto-delete SocialMessage rows. The spa is the data
# controller for their customer interactions (mirrors how Salesforce
# / HubSpot / every B2B CRM handles this) — if an IG user wants their
# message history with a specific spa erased, that's a request to
# the spa, not to us. The user-facing deletion instructions page
# explains this explicitly.


class DataDeletionRequest(models.Model):
    """One row per Meta Data Deletion Callback POST.

    Acts as the audit record for the deletion lifecycle:

        PENDING ──► PROCESSED  (we cleared tokens)
                ─► FAILED      (couldn't match a connection or hit error)

    The `confirmation_code` is the unguessable identifier we hand
    back to Meta in the response; Meta passes it on to the user as a
    "you can verify deletion here" link. The user hits our public
    status endpoint with the code to see the row's current state.

    NOT tenant-scoped — Meta sends one POST per user, and we resolve
    the affected tenant from the user → Connection lookup. Multiple
    connections across multiple tenants for the same user are
    possible (the same person could admin two different spas).
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSED = 'processed', 'Processed'
        FAILED = 'failed', 'Failed'

    # Random URL-safe code Meta hands back to the user so they can
    # verify processing. Indexed because the public status lookup
    # hits this column directly.
    confirmation_code = models.CharField(
        max_length=64, unique=True, db_index=True,
    )

    # Meta user ID + Page IDs affected. user_id is the audit anchor;
    # `affected_page_ids` is a JSON list because one user removing
    # the app can touch multiple Pages (multiple Connections).
    external_user_id = models.CharField(max_length=128, db_index=True)
    affected_page_ids = models.JSONField(default=list, blank=True)
    affected_connection_ids = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )

    error_message = models.CharField(max_length=500, blank=True, default='')

    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['external_user_id', '-requested_at']),
        ]

    def __str__(self):
        return f'DataDeletionRequest({self.confirmation_code}, {self.status})'
