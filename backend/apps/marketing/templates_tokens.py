"""Personalization-token allowlist + renderer for marketing templates.

The template body uses Mustache-lite syntax: `{{first_name}}`,
`{{tenant_name}}`, etc. At save time the validator parses the body
and rejects any token outside `ALLOWED_TOKENS` — see ADR 0016 §
"MarketingTemplate model" for why specific tokens (especially
clinical service names) are blocked outright.

At send time the renderer expands tokens against a `(customer,
tenant, campaign, location)` context and returns the
ready-to-dispatch body.
"""

from __future__ import annotations

import datetime as dt
import re

from django.conf import settings
from django.utils import timezone

# Token discovery — `{{token}}` with optional whitespace.
TOKEN_PATTERN = re.compile(r'\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}')


# Allowlist. KEEP THIS IN SYNC with the docs in ADR 0016 + the
# frontend `lib/marketing.ts:ALLOWED_TOKENS`. Adding a new token
# requires:
#   1. ADR update (small) — explain why the new token isn't PHI
#   2. Renderer entry below
#   3. Frontend allowlist + UI affordance
ALLOWED_TOKENS = frozenset({
    'first_name',
    'last_name',
    'tenant_name',
    'last_appointment_date',
    'birthday_month',
    'unsubscribe_url',
})


# Tokens we explicitly REJECT with an explanatory message — common
# mistakes the operator might try. Better than a generic "unknown
# token" because the operator learns the rule, not just the symbol.
EXPLICITLY_REJECTED = {
    'last_appointment_service': (
        'Clinical service names are PHI when paired with the spa '
        'as sender. Use last_appointment_date instead.'
    ),
    'service_name': (
        'Clinical service names are PHI. Not allowed in marketing copy.'
    ),
    'medical_history': (
        'Medical history is PHI. Never allowed in marketing copy.'
    ),
    'allergies': (
        'Allergies are PHI. Never allowed in marketing copy.'
    ),
    'medications': (
        'Medications are PHI. Never allowed in marketing copy.'
    ),
}


class TokenValidationError(Exception):
    """Raised when a template body contains a disallowed token."""


def discover_tokens(body: str) -> list[str]:
    """Return all token names (no braces) found in the body, with
    duplicates preserved in order of appearance. The frontend's
    sample-preview renderer uses this to highlight which tokens
    will be expanded."""
    return TOKEN_PATTERN.findall(body or '')


def validate_template_body(body: str) -> None:
    """Raise `TokenValidationError` on the first disallowed token.

    `unsubscribe_url` is REQUIRED for email templates per CAN-SPAM —
    that check lives in the serializer (it has access to the channel)
    rather than here."""
    tokens = discover_tokens(body)
    for token in tokens:
        if token in ALLOWED_TOKENS:
            continue
        if token in EXPLICITLY_REJECTED:
            raise TokenValidationError(
                f'{{{{{token}}}}}: {EXPLICITLY_REJECTED[token]}',
            )
        raise TokenValidationError(
            f'{{{{{token}}}}}: unknown token. Allowed: '
            f'{sorted(ALLOWED_TOKENS)}',
        )


# ── Renderer ────────────────────────────────────────────────────────


def _resolve_token(
    token: str,
    *,
    customer,
    tenant,
    unsubscribe_url: str,
) -> str:
    """Expand a single token to its string value. Returns the empty
    string for tokens that don't have a value for this customer
    (e.g. `last_appointment_date` when the customer has never
    booked) — better than rendering `None` or leaving the raw
    `{{token}}` in the email body.
    """
    if token == 'first_name':
        return (customer.first_name or '').strip()
    if token == 'last_name':
        return (customer.last_name or '').strip()
    if token == 'tenant_name':
        return tenant.name
    if token == 'unsubscribe_url':
        return unsubscribe_url
    if token == 'birthday_month':
        if customer.date_of_birth:
            return customer.date_of_birth.strftime('%B')
        return ''
    if token == 'last_appointment_date':
        # Most-recent COMPLETED appointment (matching the audience
        # filter's "visit" semantic — no-shows don't count).
        from apps.appointments.models import Appointment
        last = (
            Appointment.objects
            .filter(
                tenant=tenant,
                customer=customer,
                status=Appointment.Status.COMPLETED,
            )
            .order_by('-start_time')
            .first()
        )
        if last is None:
            return ''
        # Render in the location's timezone so "May 12" is the spa's
        # calendar day, not UTC.
        try:
            import zoneinfo
            local_tz = zoneinfo.ZoneInfo(last.location.timezone)
        except Exception:
            local_tz = timezone.get_current_timezone()
        return last.start_time.astimezone(local_tz).strftime('%B %-d, %Y')
    # Unreachable — validated at save time. Defensive empty string.
    return ''


def render_body(
    body: str,
    *,
    customer,
    tenant,
    unsubscribe_token: str = '',
) -> str:
    """Render the template body for a single customer.

    `unsubscribe_token` is per-customer-per-campaign; the public
    unsubscribe endpoint resolves it back to the customer + channel
    when the link is clicked. Pass '' for SMS templates (no
    unsubscribe URL needed; STOP keyword serves the role)."""
    if unsubscribe_token:
        unsubscribe_url = (
            f"{settings.PUBLIC_BASE_URL.rstrip('/')}/marketing/unsubscribe/"
            f"{unsubscribe_token}"
        )
    else:
        unsubscribe_url = ''

    def _replace(match: re.Match) -> str:
        token = match.group(1).strip()
        return _resolve_token(
            token,
            customer=customer,
            tenant=tenant,
            unsubscribe_url=unsubscribe_url,
        )

    return TOKEN_PATTERN.sub(_replace, body or '')


def render_preview(
    body: str,
    *,
    customer,
    tenant,
) -> str:
    """Render with a placeholder unsubscribe URL — used by the
    template editor's preview pane. Real sends use `render_body`
    with a per-send token."""
    return render_body(
        body,
        customer=customer,
        tenant=tenant,
        unsubscribe_token='preview-token',
    )
