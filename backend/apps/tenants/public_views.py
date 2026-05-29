"""Public (unauthenticated) endpoints under /api/public/.

Today this is just the self-serve signup endpoint. Demo-request +
lead-capture endpoints land here too when Phase 3 follow-up ships.

Throttled aggressively because these are the only unauthenticated
write endpoints on the platform — they're an obvious target for
spam + abuse. ``AnonRateThrottle`` is keyed by IP (Django checks
``REMOTE_ADDR`` after honoring ``X_FORWARDED_FOR`` when configured),
which is sufficient defense for v1; if we see organized signup
abuse we'll add a CAPTCHA + per-domain throttle.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.signup import (
    SignupError,
    create_signup_session,
)

logger = logging.getLogger(__name__)


# ── Throttles ──────────────────────────────────────────────────────


class SignupThrottle(AnonRateThrottle):
    """5 signup attempts per hour per IP.

    Tight by design — a real medspa owner signs up ONCE; an attacker
    burns through dozens. The signup flow creates a User + Tenant +
    Stripe Customer per attempt, so cheap-to-create-expensive-to-
    clean-up resources sit behind this throttle.

    Stripe-side abuse (fake card testing) is independently caught
    by Stripe's fraud detection on the platform account; this
    throttle just keeps our database + audit log clean.
    """

    scope = 'signup'
    rate = '5/hour'


# ── Errors → HTTP status mapping ───────────────────────────────────


# Each SignupError.code maps to a specific HTTP status so the
# frontend form can surface field-level errors cleanly.
_CODE_TO_STATUS: dict[str, int] = {
    'invalid_input': status.HTTP_400_BAD_REQUEST,
    'invalid_email': status.HTTP_400_BAD_REQUEST,
    'free_email_blocked': status.HTTP_400_BAD_REQUEST,
    'weak_password': status.HTTP_400_BAD_REQUEST,
    'invalid_timezone': status.HTTP_400_BAD_REQUEST,
    'plan_not_self_serve': status.HTTP_400_BAD_REQUEST,
    'baa_not_accepted': status.HTTP_400_BAD_REQUEST,
    'tos_not_accepted': status.HTTP_400_BAD_REQUEST,
    'email_already_in_use': status.HTTP_409_CONFLICT,
    'slug_collision': status.HTTP_409_CONFLICT,
    'slug_unavailable': status.HTTP_409_CONFLICT,
    'stripe_not_configured': status.HTTP_503_SERVICE_UNAVAILABLE,
    'stripe_error': status.HTTP_502_BAD_GATEWAY,
}


# ── Signup endpoint ────────────────────────────────────────────────


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([SignupThrottle])
def public_signup(request: Request) -> Response:
    """``POST /api/public/signup/`` — create a new tenant + owner + trial.

    Body shape (validated in ``apps.tenants.signup.create_signup_session``):

        {
          "business_name": "Acme Med Spa",
          "owner_email": "founder@acmemed.com",
          "owner_password": "...",
          "owner_first_name": "Pat",
          "owner_last_name": "Provider",
          "timezone": "America/New_York",
          "plan": "starter",
          "billing_cycle": "monthly" | "annual",
          "payment_method_id": "pm_...",
          "baa_accepted": true,
          "tos_accepted": true
        }

    Success (201):

        {
          "subdomain": "acmemedspa",
          "login_url": "https://acmemedspa.lume-crm.com/login",
          "verification_email_sent": true
        }

    Error response shape (4xx / 5xx):

        {
          "detail": "Human message",
          "code": "stable_code_string"
        }
    """
    payload = request.data if isinstance(request.data, dict) else {}
    request_meta = {
        'ip': _client_ip(request),
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:400],
    }

    try:
        result = create_signup_session(
            payload=payload, request_meta=request_meta,
        )
    except SignupError as e:
        http_status = _CODE_TO_STATUS.get(e.code, status.HTTP_400_BAD_REQUEST)
        # Log every signup failure with the code (NOT the payload — no
        # PII / password to the log). Ops can see "free_email_blocked
        # spiked 10x" without rummaging through request bodies.
        logger.info('signup.rejected code=%s', e.code)
        return Response(
            {'detail': e.detail, 'code': e.code},
            status=http_status,
        )
    except Exception:  # noqa: BLE001 — unknown failures must not 500 silently
        # We don't want a stray uncaught exception to take down the
        # signup endpoint with a stack trace. Log full detail for
        # ops; return a generic 500 with a stable code.
        logger.exception('signup.unhandled_exception')
        return Response(
            {
                'detail': 'Something went wrong. Please try again or contact support.',
                'code': 'unexpected_error',
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    tenant = result['tenant']
    user = result['user']
    verification_token = result['verification_token']

    # Dispatch the verification email. If the email fails, we still
    # return 201 — the signup IS done; the customer can request
    # another verification email later. Email failures get logged
    # but don't rollback the tenant.
    try:
        _send_verification_email(
            user=user, tenant=tenant, token=verification_token,
        )
        verification_email_sent = True
    except Exception:  # noqa: BLE001
        logger.exception(
            'signup.verification_email_send_failed user=%s', user.id,
        )
        verification_email_sent = False

    # Audit trail — visible in /platform/logs. PII-clean (no email,
    # no name, no card data); references are by id + slug so the
    # operator can pivot via /platform/tenants if needed.
    record(
        action=AuditLog.Action.CREATE,
        resource_type='tenant_signup',
        resource_id=tenant.id,
        request=request,
        metadata={
            'tenant_slug': tenant.slug,
            'plan': tenant.plan,
            'billing_cycle': tenant.billing_cycle,
            'baa_version': tenant.baa_version,
            'tos_version': tenant.tos_version,
            'verification_email_sent': verification_email_sent,
        },
    )

    return Response(
        {
            'subdomain': tenant.slug,
            'login_url': _login_url_for(tenant),
            'verification_email_sent': verification_email_sent,
        },
        status=status.HTTP_201_CREATED,
    )


# ── Helpers ────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str:
    """Best-effort client IP for the audit trail. Honors
    ``X-Forwarded-For`` (which the ALB sets) over ``REMOTE_ADDR``
    (the ALB's own IP). First entry in XFF is the actual client."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',', 1)[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def _login_url_for(tenant) -> str:
    """Public login URL on the tenant's subdomain. Mirrors the
    domain pattern Stripe-connect onboarding uses."""
    from django.conf import settings
    template = getattr(
        settings, 'TENANT_LOGIN_URL_TEMPLATE',
        'https://{tenant_slug}.xn--lumcrm-5ua.com/login',
    )
    return template.replace('{tenant_slug}', tenant.slug)


def _send_verification_email(*, user, tenant, token: str) -> None:
    """Dispatch the verification email via the configured Django mail
    backend (SES in prod; filebased in dev).

    Kept inline rather than in a template module because it's the
    only mail we send during the signup flow + the body is short.
    When the welcome / trial-reminder emails land (Phase 4/5), we'll
    factor a shared template loader.
    """
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    verify_url_template = getattr(
        settings, 'TENANT_VERIFY_EMAIL_URL_TEMPLATE',
        'https://{tenant_slug}.xn--lumcrm-5ua.com/verify-email/{token}',
    )
    verify_url = (
        verify_url_template
        .replace('{tenant_slug}', tenant.slug)
        .replace('{token}', token)
    )

    legal_name = getattr(settings, 'BILLING_LEGAL_NAME', 'Voxtro LLC')
    product_name = getattr(settings, 'BILLING_PRODUCT_NAME', 'Lumè CRM')

    subject = f'Verify your email for {product_name}'
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"Welcome to {product_name}! Click the link below to verify your email:\n\n"
        f"{verify_url}\n\n"
        f"Your 30-day free trial of {tenant.name} on {product_name} has started.\n"
        f"Your card won't be charged until day 31 — you can cancel anytime.\n\n"
        f"Need help? Reply to this email or write support@lume-crm.com.\n\n"
        f"— The {product_name} team\n"
        f"({product_name} is a product of {legal_name}.)\n"
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        # System-level sender — no tenant-branded from-address here
        # because this is OUR transactional mail to the operator
        # (the new tenant owner), not the spa's mail to their customers.
        from_email=getattr(
            settings, 'DEFAULT_FROM_EMAIL',
            f'noreply@{getattr(settings, "DEFAULT_FROM_DOMAIN", "lume-crm.com")}',
        ),
        to=[user.email],
    )
    msg.send(fail_silently=False)
