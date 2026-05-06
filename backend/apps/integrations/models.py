"""Integration connection model.

One `Connection` row per (tenant, provider). Stores OAuth-grant data
needed to call the provider's API on the tenant's behalf. v1 only
holds the lifecycle scaffolding — the actual token + refresh flow
ships in Session 2 when Meta app review completes.

`auth_data` is a JSONField (NOT yet encrypted) because v1 contains
no real tokens. Phase 0c production lift wraps this in
`cryptography.fernet` field-level encryption with the key from env;
the field shape doesn't change so the swap is a one-line model edit.
"""

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


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
    # applicable), granted_scopes, token expiry. JSON so we can
    # accommodate the per-provider variation without a schema
    # migration each time. Phase 0c will wrap this in field-level
    # encryption; v1 holds no real tokens so plaintext is acceptable
    # for the placeholder lifecycle.
    auth_data = models.JSONField(default=dict, blank=True)

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
