"""Tenant-aware email-from helpers.

Every email leaving Lumè comes from our verified SES sender domain
(`mail.lumècrm.com`) so the platform owns the sender reputation.
But the *display name* that recipients see should be the tenant's
business name — not "Lumè CRM" — so a customer of Acme Spa sees
"Acme Spa" in their inbox, recognizes who it's from, and doesn't
mark it as spam.

This module centralizes that From-line construction + the matching
Reply-To resolution so every email path (invoices, forms, marketing,
invitations, booking confirmations) gets a consistent treatment.

A full per-tenant sender identity (separate DKIM key, per-spa
subdomain like `mail.acmespa.com`) is the right long-term answer
for reputation isolation. That's queued in Phase 4F. For now the
shared `mail.lumècrm.com` subdomain + tenant-branded display names
is the same pattern Mindbody / Boulevard / Fresha use.
"""

from __future__ import annotations

from email.utils import formataddr

from django.conf import settings


def _address_part(from_setting: str) -> str:
    """Extract the bare `addr@domain` from a `'Name <addr@domain>'`
    format string. Falls back to the whole input if no angle
    brackets are present (operator misconfigured DEFAULT_FROM_EMAIL).
    """
    s = (from_setting or '').strip()
    if '<' in s and s.endswith('>'):
        return s[s.rindex('<') + 1:-1].strip()
    return s


def from_address_domain() -> str:
    """Return the domain part of DEFAULT_FROM_EMAIL (e.g.
    'mail.lumècrm.com'). Used as the host portion of programmatic
    addresses like `unsubscribe+<token>@<domain>` in the List-
    Unsubscribe mailto fallback."""
    addr = _address_part(settings.DEFAULT_FROM_EMAIL)
    return addr.split('@', 1)[-1] if '@' in addr else addr


def tenant_from_email(tenant) -> str:
    """Return the `From:` header value for an email sent on behalf
    of `tenant`. Display name = tenant.name; address part =
    settings.DEFAULT_FROM_EMAIL's address.

    Example: tenant.name='Acme Spa' → 'Acme Spa <noreply@mail.lumècrm.com>'.

    `formataddr` handles RFC 2047 MIME encoding when the tenant
    name contains non-ASCII characters (e.g., 'Café Renée') so the
    header is wire-safe.
    """
    addr = _address_part(settings.DEFAULT_FROM_EMAIL)
    display = (getattr(tenant, 'name', None) or 'Lumè CRM').strip()
    return formataddr((display, addr))


def tenant_reply_to(tenant) -> str | None:
    """Return a contact address recipients can reply to, or `None`
    if the tenant has no public-facing email on file.

    Resolution order:
      1. The default location's `email` (tenant.locations[is_default=True]).
      2. Any active location's email (first one with an email set).
      3. None — caller should omit the Reply-To header rather than
         set it to noreply@ (which Gmail flags as spam-correlated).

    Replies routed to a real human inbox at the spa is a small
    deliverability signal AND a real UX win: today replies bounce
    to a noreply we don't even check. With Reply-To set, the
    customer's reply lands wherever the spa already reads email.
    """
    try:
        locations = tenant.locations  # type: ignore[attr-defined]
    except AttributeError:
        return None

    default = locations.filter(is_default=True).exclude(email='').first()
    if default and default.email:
        return default.email

    active = locations.filter(is_active=True).exclude(email='').first()
    if active and active.email:
        return active.email

    return None
