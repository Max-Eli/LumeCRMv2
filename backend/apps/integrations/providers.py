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
        # Facebook-Login-for-Business scope names (see meta.py
        # SCOPES_INSTAGRAM for the full list + why). The `business_*`
        # prefixed names belong to a different OAuth flow and Meta
        # rejects them with "Invalid Scopes" when mixed in here.
        scopes=[
            'instagram_basic',
            'instagram_manage_messages',
            'pages_show_list',
            'pages_messaging',
            'pages_manage_metadata',
            'business_management',
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
    """Return a provider with `oauth_ready` derived from env state.

    Each call recomputes `oauth_ready` from settings so deploy-time
    changes to META_APP_ID / META_APP_SECRET pick up without a code
    edit. The dataclass is `frozen=True`, so we return a NEW
    instance with the live flag rather than mutating PROVIDERS.
    """
    base = PROVIDERS.get(key)
    if base is None:
        return None
    return ProviderConfig(
        key=base.key,
        display_name=base.display_name,
        family=base.family,
        short_description=base.short_description,
        enables=base.enables,
        scopes=base.scopes,
        oauth_ready=_is_oauth_ready(base.key),
    )


def all_providers() -> list[ProviderConfig]:
    """Return every provider with its live `oauth_ready` flag."""
    return [get_provider(p.key) for p in PROVIDERS.values()]  # type: ignore[misc]


def _is_oauth_ready(provider_key: str) -> bool:
    """A provider is oauth_ready when BOTH:

      1. The credentials it needs are present in settings, AND
      2. The OAuth flow is implemented for it.

    (1) alone isn't sufficient — having a Meta App ID lets the IG
    flow work, but FB Messenger + WhatsApp share the same App while
    needing their own OAuth + webhook routing that we haven't built
    yet. Flipping their `oauth_ready` to True because IG credentials
    exist would surface a Connect button that 501s.

    Session 1 implements meta_instagram only. Sessions 2-3 add FB
    Messenger + WhatsApp; flip their entries here as each ships.
    """
    from django.conf import settings

    _META_CREDENTIALS_PRESENT = bool(
        getattr(settings, 'META_APP_ID', '')
        and getattr(settings, 'META_APP_SECRET', '')
        and getattr(settings, 'META_WEBHOOK_VERIFY_TOKEN', '')
    )

    if provider_key == 'meta_instagram':
        return _META_CREDENTIALS_PRESENT
    # meta_facebook + meta_whatsapp: OAuth flow not yet implemented.
    if provider_key.startswith('meta_'):
        return False
    return False
