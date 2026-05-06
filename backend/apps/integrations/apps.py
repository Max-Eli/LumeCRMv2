from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """External integrations — OAuth-connected channels for messaging.

    v1 scope: Meta channels (Facebook Page Messenger, Instagram Business
    DMs, WhatsApp Business). Each is a `Connection` row with the
    OAuth-grant data needed to ingest messages and reply via Meta's
    Graph API + Webhooks.

    Tokens are stored encrypted (Phase 0c production lift will wire
    field-level encryption via `cryptography.fernet`); v1 stores
    placeholder JSON since no real tokens land until Session 2.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.integrations'
    label = 'integrations'
