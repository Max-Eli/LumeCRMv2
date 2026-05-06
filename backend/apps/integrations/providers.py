"""Per-provider configuration registry.

Single source of truth for the human-facing metadata about each
integration: display name, what it enables, OAuth scopes we'll
request, status copy. Endpoints + the frontend pull from this so we
don't repeat strings across layers.

When adding a provider:
  1. Add the enum value to `Connection.Provider`
  2. Add an entry here with full metadata
  3. The frontend's provider list comes from /api/integrations/
     so no client-side update is needed
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    key: str
    display_name: str
    family: str  # 'meta' for FB/IG/WhatsApp; future: 'google' etc.
    short_description: str
    enables: list[str]
    # OAuth scopes we'll request when the connect flow lights up in
    # Session 2. Documented here so the Meta App review submission
    # uses the exact same list.
    scopes: list[str]
    # Whether the provider's OAuth flow is implemented yet. v1 ships
    # with all `False`; Session 2+ flips them as each provider gets
    # wired up.
    oauth_ready: bool = False


PROVIDERS: dict[str, ProviderConfig] = {
    'meta_facebook': ProviderConfig(
        key='meta_facebook',
        display_name='Facebook Page Messenger',
        family='meta',
        short_description=(
            "Receive Page DMs in Lumè's inbox, reply from any device, "
            'book appointments directly from a conversation.'
        ),
        enables=[
            'Receive Facebook Page messages in the unified inbox',
            'Reply from Lumè — your customer sees the reply on Facebook',
            'Book appointments directly from a conversation',
            'Auto-link to existing client records by name + phone',
        ],
        scopes=[
            'pages_messaging',
            'pages_show_list',
            'pages_read_engagement',
            'pages_manage_metadata',
        ],
        oauth_ready=False,
    ),
    'meta_instagram': ProviderConfig(
        key='meta_instagram',
        display_name='Instagram Business DMs',
        family='meta',
        short_description=(
            'Receive Instagram DMs from your Business account, reply from '
            'Lumè, and convert inquiries into bookings.'
        ),
        enables=[
            'Receive Instagram Business DMs in the unified inbox',
            'Reply from Lumè — your customer sees the reply on Instagram',
            'Book appointments directly from a conversation',
            'Story replies + Mentions land in the same inbox',
        ],
        scopes=[
            'instagram_business_basic',
            'instagram_business_manage_messages',
            'pages_show_list',
        ],
        oauth_ready=False,
    ),
    'meta_whatsapp': ProviderConfig(
        key='meta_whatsapp',
        display_name='WhatsApp Business',
        family='meta',
        short_description=(
            'Receive WhatsApp messages on your Business number, reply from '
            'Lumè, and book appointments inside a conversation.'
        ),
        enables=[
            'Receive WhatsApp Business messages in the unified inbox',
            'Reply from Lumè — your customer sees the reply on WhatsApp',
            'Book appointments directly from a conversation',
            'Send appointment confirmations via WhatsApp',
        ],
        scopes=[
            'whatsapp_business_messaging',
            'whatsapp_business_management',
        ],
        oauth_ready=False,
    ),
}


def get_provider(key: str) -> ProviderConfig | None:
    return PROVIDERS.get(key)


def all_providers() -> list[ProviderConfig]:
    return list(PROVIDERS.values())
