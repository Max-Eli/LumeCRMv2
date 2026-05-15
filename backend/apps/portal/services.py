"""Service-layer helpers for the portal — pulled out of views so the
business logic stays testable without going through HTTP and so the
magic-link email can be triggered from anywhere (e.g. an admin
action) in the future."""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone as djtz

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.customers.models import Customer
from apps.tenants.models import Tenant

from .models import CustomerPortalToken

logger = logging.getLogger(__name__)


def find_customer_for_login(*, tenant: Tenant, email: str) -> Customer | None:
    """Resolve `email` to a Customer in `tenant`, or None.

    Email match is case-insensitive. Inactive customers are excluded —
    they exist for history but should not be able to log into the
    portal. We return None (not raise) so the request endpoint can
    return the same "we sent you an email if that's a customer here"
    response whether or not the address matched, defeating
    email-enumeration probes."""
    cleaned = (email or '').strip().lower()
    if not cleaned:
        return None
    try:
        return Customer.objects.get(
            tenant=tenant,
            email__iexact=cleaned,
            status=Customer.Status.ACTIVE,
        )
    except Customer.DoesNotExist:
        return None
    except Customer.MultipleObjectsReturned:
        # Two ACTIVE customers with the same email on one tenant —
        # data quality issue, not a security one. Log + take the
        # oldest (most established) row.
        logger.warning(
            'portal.login.duplicate_email',
            extra={'tenant_slug': tenant.slug, 'email_domain': cleaned.split('@')[-1]},
        )
        return Customer.objects.filter(
            tenant=tenant, email__iexact=cleaned, status=Customer.Status.ACTIVE,
        ).order_by('created_at').first()


def send_magic_link_email(*, customer: Customer, token: CustomerPortalToken, request=None) -> None:
    """Render + dispatch the magic-link email.

    The link points at the tenant's public host so the customer lands
    on their spa's branded portal. In production the host is the
    tenant subdomain (resolved via the same logic the booking page
    uses); in dev we fall back to `settings.PUBLIC_BASE_URL` with the
    tenant slug appended as a path prefix for local testing.

    Body is template-rendered (HTML + plain-text alternates) so the
    tenant's branding (name, logo, primary color) flows through SES
    without us having to bake it into a hard-coded string.

    PHI posture: the email contains the customer's name + the spa
    name + the login link. Treated the same as appointment-
    confirmation email — covered under the TPO (Treatment / Payment /
    Operations) exception and the Twilio/SES BAAs we have in place.
    """
    tenant = customer.tenant
    portal_url = _build_portal_url(tenant=tenant, request=request)
    magic_url = f'{portal_url.rstrip("/")}/portal/magic/{token.token}'

    context = {
        'customer_first_name': customer.first_name or 'there',
        'spa_name': tenant.name,
        'spa_primary_color': tenant.primary_color or '#1f2937',
        'spa_logo_url': tenant.logo_url or '',
        'magic_url': magic_url,
        'expiry_minutes': 30,
    }

    subject = f'Your {tenant.name} sign-in link'
    text_body = render_to_string('portal/email/magic_link.txt', context)
    html_body = render_to_string('portal/email/magic_link.html', context)

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[customer.email],
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.send(fail_silently=False)

    record(
        action=AuditLog.Action.CREATE,
        resource_type='portal_magic_link',
        resource_id=token.id,
        request=request,
        metadata={
            'tenant_slug': tenant.slug,
            'customer_id': customer.id,
            # Domain only — never the full address.
            'email_domain': (customer.email or '').split('@')[-1].lower(),
            'expires_at': token.expires_at.isoformat(),
        },
    )


def _build_portal_url(*, tenant: Tenant, request) -> str:
    """Pick the right public origin for the magic link.

    Production: the request arrives via the tenant subdomain
    (e.g. `acmespa.xn--lumcrm-5ua.com`). Use the request's host
    verbatim so the email link returns the customer to the same
    spa-branded surface they came from.

    Dev / fallback: `PUBLIC_BASE_URL` from settings (typically
    localhost:3000). We don't have subdomain routing locally; the
    portal page handles tenant resolution via a separate signal.
    """
    if request is not None:
        host = request.get_host()
        scheme = 'https' if request.is_secure() else 'http'
        # Skip localhost so the link doesn't break when a developer
        # tests email-send in a non-browser context.
        if 'localhost' not in host and '127.0.0.1' not in host:
            return f'{scheme}://{host}'
    return getattr(settings, 'PUBLIC_BASE_URL', 'http://localhost:3000')


def consume_token(
    *, token_value: str, tenant: Tenant,
) -> CustomerPortalToken | None:
    """Atomically consume a magic-link token.

    Returns the token row on success, None if the token doesn't
    exist, is already used, or has expired. Caller mints the
    `CustomerPortalSession` from the returned token's customer.

    The `tenant` argument is a defense-in-depth check — even if a
    token's value were guessed across tenants, we won't consume one
    that doesn't belong to the requesting host's tenant.
    """
    from django.db import transaction

    with transaction.atomic():
        try:
            token = (
                CustomerPortalToken.objects
                .select_for_update()
                .select_related('customer', 'tenant')
                .get(token=token_value, tenant=tenant)
            )
        except CustomerPortalToken.DoesNotExist:
            return None

        if not token.is_valid:
            return None

        token.used_at = djtz.now()
        token.save(update_fields=['used_at'])

    return token
