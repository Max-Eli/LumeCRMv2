"""Customer-portal models.

The portal is the customer-facing self-service surface (Phase 3E MVP):
customers log in with a magic link (no password), view their
appointments, manage their profile + marketing consents, and cancel
within the tenant's policy. Distinct from the staff CRM:

  - **Identity**: Customers are `apps.customers.Customer` rows, not
    `apps.users.User`. Django's session/auth middleware (which assumes
    `User`) doesn't apply — we run our own customer-session layer.
  - **Tenant scoping**: A customer belongs to exactly one tenant.
    Their portal session inherits that tenant; cross-tenant data is
    structurally inaccessible because the session FK is to a single
    Customer row.
  - **PHI**: Customers see their OWN PHI (their appointments, their
    profile). They never see other patients' data. Every read is
    audit-logged so we know "Customer X viewed appointment Y at
    timestamp Z."

Two models here form the auth flow:

  - `CustomerPortalToken` — one-time magic link. Email contains a
    URL like `/portal/magic/<token>`; clicking consumes the token,
    creates a session, sets the session cookie, and redirects to
    /portal. Token can only be consumed once + has a short expiry.
  - `CustomerPortalSession` — persistent session cookie value.
    Created on token consumption; expires after a configurable
    idle period. The portal middleware extracts the customer from
    the session cookie on every portal request.

This mirrors the staff `Invitation` + Django session pattern but
purpose-built for the customer-identity surface so we don't have to
co-opt `User` to mean "customer" too (which would force a thousand
cascading "is this user a customer or staff?" checks).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone as djtz

from apps.tenants.abstract_models import TenantedModel


def _generate_portal_token() -> str:
    """High-entropy URL-safe token. Same pattern as form-fill tokens —
    `secrets.token_urlsafe(32)` is 256 bits of entropy in a path-safe
    alphabet. Used for BOTH the magic-link tokens (one-time) AND the
    session cookie values (persistent until expiry)."""
    return secrets.token_urlsafe(32)


# ── Token lifetimes ──────────────────────────────────────────────────
#
# Tunable here so a future security review can tighten without touching
# behaviour. Values match the industry default for healthcare portals:
# short magic-link expiry (so a forwarded email becomes useless quickly)
# + medium session expiry (so the customer doesn't get logged out mid-
# task while filling a form).

MAGIC_LINK_EXPIRY = timedelta(minutes=30)
SESSION_EXPIRY = timedelta(days=14)
# Idle timeout overrides absolute expiry — if the customer doesn't
# touch the portal for this long, the session is considered dead even
# if SESSION_EXPIRY hasn't elapsed.
SESSION_IDLE_TIMEOUT = timedelta(hours=4)


class CustomerPortalToken(TenantedModel):
    """One-time magic-link token sent to the customer's email.

    Issued by `POST /api/portal/auth/request-magic-link/` when a
    customer enters their email on the portal login screen. The
    token is included in the URL of the SES email we send:

        https://<tenant-subdomain>/<host>/portal/magic/<token>

    On `GET /portal/magic/<token>` the frontend POSTs to the
    consume endpoint, which validates the token, creates a
    `CustomerPortalSession`, sets the session cookie, and redirects
    to /portal. The token is single-use — `used_at IS NOT NULL`
    after consumption.

    Security posture:

    - Tokens are 256-bit, URL-safe, generated via `secrets`. Not
      derivable from the customer's email or any other knowable
      input.
    - Short expiry (30 min) — a forwarded / leaked email loses
      utility quickly. Customer can request another instantly.
    - Single-use — `used_at` is set atomically inside the consume
      view's transaction. A replay returns 410 Gone.
    - Stored plaintext (no hashing). The token IS the credential;
      hashing would prevent us from looking up by token value
      without scanning every row. Mitigated by short lifetime +
      single-use + the fact that this column is never exported
      from the DB.
    - Email-enumeration resistance: the request endpoint returns
      the same response (200, "we sent you an email if that
      address is on file") whether or not the email matches a
      customer. Avoids leaking which addresses are clients.
    """

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='portal_tokens',
        help_text=(
            'The customer the magic link will authenticate as. CASCADE '
            'so deleting a customer invalidates any outstanding tokens '
            "for them — we don't want a dangling token granting access "
            'to a removed account.'
        ),
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_portal_token,
        db_index=True,
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Timestamp the token was consumed. Single-use; non-null = spent.',
    )
    requested_ip = models.GenericIPAddressField(
        null=True, blank=True,
        help_text=(
            'IP address that asked for the magic link, for the audit '
            'trail. Not used for any enforcement decision — IPs are '
            'too easy to spoof / share / change to be load-bearing.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['tenant', 'customer', '-created_at']),
        ]

    def __str__(self) -> str:
        state = 'used' if self.used_at else 'pending'
        return f'PortalToken<customer={self.customer_id} {state}>'

    @classmethod
    def issue(cls, *, customer, requested_ip: str | None = None) -> 'CustomerPortalToken':
        """Create + persist a fresh token for `customer`. Called by the
        request-magic-link view; not for direct API use."""
        return cls.objects.create(
            tenant=customer.tenant,
            customer=customer,
            expires_at=djtz.now() + MAGIC_LINK_EXPIRY,
            requested_ip=requested_ip or None,
        )

    @property
    def is_valid(self) -> bool:
        """True iff the token can still be consumed: not yet used, not
        expired. Caller-friendly read; the consume view does its own
        atomic check inside a transaction."""
        return self.used_at is None and djtz.now() < self.expires_at


class CustomerPortalSession(TenantedModel):
    """Persistent session created on magic-link consumption.

    The session cookie sent to the browser carries this row's `token`
    (NOT the magic-link token — separate column). On each portal
    request, the middleware reads the cookie, looks up the session,
    and binds `request.customer`.

    Lifecycle:

    - Created when a `CustomerPortalToken` is consumed.
    - `last_seen_at` is bumped on every authenticated request so the
      idle-timeout check can hit a single timestamp instead of
      reading every recent request.
    - Revoked by the portal logout endpoint (`revoked_at`) or by
      idle/absolute timeout (lazy check on next request).

    No PHI in this row beyond the customer FK; the actual data
    customers see is fetched through endpoints that audit-log the
    read against this session's `customer_id`.
    """

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='portal_sessions',
    )
    token = models.CharField(
        max_length=64, unique=True, default=_generate_portal_token,
        db_index=True,
        help_text='Random session token. Stored in the browser cookie verbatim.',
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the customer logs out (or staff revokes). Once set, the session is dead.',
    )
    issued_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(
        max_length=300, blank=True, default='',
        help_text=(
            'User-Agent of the client that consumed the magic link. '
            'For audit display; not used for any enforcement.'
        ),
    )
    last_seen_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['tenant', 'customer', '-last_seen_at']),
        ]

    def __str__(self) -> str:
        state = 'revoked' if self.revoked_at else 'active'
        return f'PortalSession<customer={self.customer_id} {state}>'

    @classmethod
    def issue(
        cls, *, customer, issued_ip: str | None = None, user_agent: str = '',
    ) -> 'CustomerPortalSession':
        """Mint a fresh session for `customer` after a successful
        magic-link consumption. Caller is responsible for setting the
        cookie on the response."""
        return cls.objects.create(
            tenant=customer.tenant,
            customer=customer,
            expires_at=djtz.now() + SESSION_EXPIRY,
            issued_ip=issued_ip or None,
            user_agent=user_agent[:300],
        )

    @property
    def is_active(self) -> bool:
        """True iff the session can still authenticate a request:
        not revoked, not absolute-expired, and within the idle
        timeout. Checked by the portal middleware on every request."""
        if self.revoked_at is not None:
            return False
        now = djtz.now()
        if now >= self.expires_at:
            return False
        if now >= self.last_seen_at + SESSION_IDLE_TIMEOUT:
            return False
        return True

    def touch(self) -> None:
        """Bump `last_seen_at`. Called by the middleware on each
        authenticated request to refresh the idle window. We use
        `update()` not `save()` to avoid pulling the whole row
        through the ORM, since this happens on every request."""
        type(self).objects.filter(pk=self.pk).update(last_seen_at=djtz.now())
