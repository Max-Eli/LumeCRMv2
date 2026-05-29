"""Self-serve signup service for new spas.

Phase 3 of the self-serve pricing rollout. The single public entry
point is ``create_signup_session`` which:

  1. Validates the input + does a slug-collision sweep.
  2. Creates the User account (rolls back on subsequent failure).
  3. Calls ``apps.tenants.services.create_tenant_with_defaults`` with
     plan='trial' + trial_ends_at=now+30d + BAA/ToS acceptance
     stamped on the row.
  4. Creates the Stripe Customer + attaches the payment method.
  5. Creates the Stripe Subscription with 30-day trial.
  6. Issues an email-verification token.

Atomicity: every DB write is in a single ``transaction.atomic`` block.
Stripe is called inside the transaction so a Stripe-side failure
rolls back the User + Tenant. The trade-off is a Stripe Customer +
Subscription created without a matching local row if the DB commit
itself fails after Stripe — vanishingly rare, and Stripe webhooks
would surface the orphan (we'd void manually). The reverse — local
rows with no Stripe — is worse because the operator could log in
and use the workspace without paying.

Error model: ``SignupError`` is a typed exception with a stable
``code`` and a customer-facing message. The view layer maps codes
to HTTP status (400 / 409 / 502 / 503).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import (
    ValidationError as PasswordValidationError,
    validate_password,
)
from django.db import IntegrityError, transaction
from django.utils import timezone as djtz
from django.utils.text import slugify

from apps.billing.services import (
    StripeBillingError,
    StripeNotConfigured,
    create_customer_for_tenant,
    create_trial_subscription,
    is_configured as billing_is_configured,
)
from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant_with_defaults

if TYPE_CHECKING:
    pass

User = get_user_model()
logger = logging.getLogger(__name__)


# Versioned compliance text — bumped when the BAA / ToS document
# itself changes. The signup endpoint stamps the version the
# customer accepted onto Tenant.baa_version / .tos_version so we
# can prove which document they signed in the audit trail.
BAA_VERSION = '2026-05'
TOS_VERSION = '2026-05'

# Trial length in days. 30 was a deliberate decision (vs 14) — gives a
# spa time to do a full appointment cycle before being charged. See
# the plan file at ~/.claude/plans/abstract-bouncing-trinket.md.
TRIAL_DAYS = 30

# Free-email-provider domains we reject at signup. Soft fence — a
# professional spa has a business email, and we surface a clearer
# error than "your email looks personal." Anyone with a real
# business reason will simply contact sales.
_FREE_EMAIL_DOMAINS = frozenset({
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
    'aol.com', 'icloud.com', 'me.com', 'mac.com', 'live.com',
    'msn.com', 'yandex.com', 'protonmail.com', 'proton.me',
    'ymail.com', 'rocketmail.com', 'mail.com', 'gmx.com',
})

# Slug character allowlist — lowercase alphanumeric + dash, must
# start with alpha, 3-63 chars. Matches the existing Tenant.slug
# constraint shape; we also keep a reserved-words list so signups
# can't squat names that conflict with admin / marketing / etc.
_SLUG_PATTERN = re.compile(r'^[a-z][a-z0-9-]{2,62}$')
_RESERVED_SLUGS = frozenset({
    'admin', 'api', 'app', 'auth', 'billing', 'blog', 'book',
    'booking', 'config', 'console', 'dashboard', 'demo', 'dev',
    'docs', 'email', 'home', 'invoice', 'login', 'mail', 'main',
    'marketing', 'mobile', 'org', 'platform', 'portal', 'pricing',
    'public', 'sales', 'settings', 'signup', 'sign-up', 'social',
    'staff', 'static', 'status', 'stripe', 'support', 'system',
    'test', 'voxtro', 'www',
})


class SignupError(Exception):
    """Raised for any predictable signup failure. The view layer reads
    ``.code`` to choose the HTTP status; ``.detail`` is the human
    message echoed to the caller. NEVER carry PII in the detail — the
    code path that re-raises gets logged with the offending input
    elsewhere."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


# ── Public entry point ──────────────────────────────────────────────


def create_signup_session(*, payload: dict, request_meta: dict) -> dict:
    """Provision a new tenant + owner + Stripe subscription in one
    atomic operation. Returns ``{'tenant': Tenant, 'verification_token': str}``
    on success; raises ``SignupError`` on any failure.

    Args:
        payload: validated input dict — see ``_validate_payload`` for shape.
        request_meta: ``{'ip': str, 'user_agent': str}`` for audit. Caller
            extracts these from the request before invoking the service
            (the service stays request-agnostic so it can be reused from
            tests + future surfaces like a bulk import).
    """
    _check_billing_configured()
    data = _validate_payload(payload)

    # ── Slug collision sweep ─────────────────────────────────────
    proposed_slug = _slugify_business_name(data['business_name'])
    final_slug = _pick_available_slug(proposed_slug)

    # Stripe-side setup: create the Customer + Subscription. Tenant
    # row first so we can stamp metadata pointing back at the tenant
    # ID on the Stripe Customer.
    with transaction.atomic():
        if User.objects.filter(email__iexact=data['owner_email']).exists():
            # Pre-check (before .create) is friendlier than catching
            # the IntegrityError later. Same response shape either way.
            raise SignupError(
                'email_already_in_use',
                'An account already exists with this email. Sign in instead, '
                'or use a different email to provision a separate workspace.',
            )

        try:
            user = User.objects.create_user(
                email=data['owner_email'],
                password=data['owner_password'],
                first_name=data['owner_first_name'],
                last_name=data['owner_last_name'],
            )
        except IntegrityError as e:
            # Race with another signup completing between the check
            # above and the create. Re-raise as a clean SignupError.
            raise SignupError(
                'email_already_in_use',
                'An account already exists with this email.',
            ) from e

        try:
            tenant = create_tenant_with_defaults(
                name=data['business_name'],
                slug=final_slug,
                owner_user=user,
                # Trial-period config — the tenant starts on the
                # trial plan with the chosen plan as the target.
                status=Tenant.Status.TRIAL,
                plan=Tenant.Plan.TRIAL,
                billing_cycle=data['billing_cycle'],
                trial_ends_at=djtz.now() + dt.timedelta(days=TRIAL_DAYS),
                billing_email=data['owner_email'],
                # Compliance acceptance — frozen at signup so the
                # audit trail proves which version they accepted.
                baa_accepted_at=djtz.now(),
                baa_version=BAA_VERSION,
                tos_accepted_at=djtz.now(),
                tos_version=TOS_VERSION,
                # Default location timezone — falls through into the
                # seeded default Location row inside the helper.
                timezone=data['timezone'],
            )
        except IntegrityError as e:
            # Almost certainly a slug collision that slipped past the
            # availability check (concurrent signups racing on the
            # same business name). Re-raise as a clean SignupError;
            # the operator just needs to retry.
            raise SignupError(
                'slug_collision',
                'That workspace name was just claimed. Please try a slightly '
                'different name.',
            ) from e

        # Stripe Customer + Subscription. Failure here rolls the
        # transaction back, so the User + Tenant + Location +
        # Membership all disappear. Customer-on-Stripe orphans are
        # rare (would require Stripe to succeed on Customer.create
        # then fail on Subscription.create) and are surfaced by
        # the dashboard if they do occur — ops can void manually.
        try:
            create_customer_for_tenant(
                tenant,
                billing_email=data['owner_email'],
                payment_method_id=data['payment_method_id'],
            )
            create_trial_subscription(
                tenant,
                plan=data['plan'],
                billing_cycle=data['billing_cycle'],
                trial_days=TRIAL_DAYS,
            )
        except StripeNotConfigured as e:
            raise SignupError(
                'stripe_not_configured',
                'Billing is not configured in this environment.',
            ) from e
        except StripeBillingError as e:
            # Stripe API failure (declined card, invalid PM, network,
            # auth, rate limit). Sanitize the message for the
            # customer-facing response but log full detail for ops.
            logger.exception(
                'Signup Stripe call failed for tenant=%s', tenant.slug,
            )
            raise SignupError(
                'stripe_error',
                'Could not start the trial subscription. Please check the '
                'card details and try again, or contact support.',
            ) from e

        # Email-verification token — separate model (lives in
        # users app) so the magic-link / reset flows can reuse the
        # same machinery. For v1 we issue the token + return it to
        # the caller; the view dispatches the email.
        from apps.users.models import EmailVerificationToken
        verification = EmailVerificationToken.issue(
            user=user,
            requested_ip=request_meta.get('ip') or '',
            requested_user_agent=request_meta.get('user_agent') or '',
        )

    return {
        'tenant': tenant,
        'user': user,
        'verification_token': verification.token,
    }


# ── Validation ──────────────────────────────────────────────────────


def _check_billing_configured() -> None:
    """We can't take a card without Stripe; fail fast with a clear
    error rather than half-creating a tenant + failing on the
    Stripe call later."""
    if not billing_is_configured():
        raise SignupError(
            'stripe_not_configured',
            'Billing is not configured in this environment. Signup is '
            'temporarily unavailable.',
        )


def _validate_payload(payload: dict) -> dict:
    """Return a normalized dict of validated fields, or raise SignupError."""
    def _str(key: str, *, required: bool = True, max_len: int = 200) -> str:
        v = (payload.get(key) or '').strip()
        if required and not v:
            raise SignupError('invalid_input', f'{key} is required.')
        if len(v) > max_len:
            raise SignupError('invalid_input', f'{key} is too long.')
        return v

    business_name = _str('business_name', max_len=200)
    owner_email = _str('owner_email', max_len=254).lower()
    owner_password = payload.get('owner_password') or ''
    owner_first_name = _str('owner_first_name', max_len=100)
    owner_last_name = _str('owner_last_name', max_len=100)
    timezone = _str('timezone', max_len=64)
    plan = (payload.get('plan') or 'starter').strip().lower()
    billing_cycle = (payload.get('billing_cycle') or 'monthly').strip().lower()
    payment_method_id = _str('payment_method_id', max_len=64)
    baa_accepted = bool(payload.get('baa_accepted'))
    tos_accepted = bool(payload.get('tos_accepted'))

    # Email shape — Django's EmailValidator would be more thorough but
    # also rejects perfectly valid edge cases like single-word local
    # parts. The simple shape check matches what most B2B SaaS does.
    if '@' not in owner_email or '.' not in owner_email.split('@', 1)[-1]:
        raise SignupError('invalid_email', 'Enter a valid email address.')

    # Business-email check — soft fence. The sales team handles
    # appeals if a legitimate solo operator gets caught.
    domain = owner_email.split('@', 1)[-1]
    if domain in _FREE_EMAIL_DOMAINS:
        raise SignupError(
            'free_email_blocked',
            'Please sign up with your business email. If you don\'t have one, '
            'contact support@lume-crm.com and we\'ll set up your trial manually.',
        )

    # Password — defer to Django's configured validators (length,
    # commonality, similarity to user attributes).
    try:
        validate_password(owner_password)
    except PasswordValidationError as e:
        raise SignupError('weak_password', ' '.join(e.messages)) from e

    # Plan + billing cycle — only Starter is self-serve. Pro and
    # Enterprise route through the demo flow.
    if plan != 'starter':
        raise SignupError(
            'plan_not_self_serve',
            'Pro and Enterprise plans require a quick demo — please book one '
            'instead.',
        )
    if billing_cycle not in ('monthly', 'annual'):
        raise SignupError('invalid_input', 'billing_cycle must be monthly or annual.')

    # Compliance acknowledgements — both required. NOT a checkbox we
    # silently default-true; the marketing-site form requires an
    # explicit click + posts these as true.
    if not baa_accepted:
        raise SignupError(
            'baa_not_accepted',
            'You must accept the Business Associate Agreement to use a '
            'HIPAA-covered workspace.',
        )
    if not tos_accepted:
        raise SignupError(
            'tos_not_accepted',
            'You must accept the Terms of Service to create a workspace.',
        )

    # Timezone — a known IANA name. Use Python's zoneinfo to validate.
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(timezone)
    except Exception as e:
        raise SignupError(
            'invalid_timezone',
            f'Unknown timezone "{timezone}". Use an IANA name like '
            f'America/New_York.',
        ) from e

    return {
        'business_name': business_name,
        'owner_email': owner_email,
        'owner_password': owner_password,
        'owner_first_name': owner_first_name,
        'owner_last_name': owner_last_name,
        'timezone': timezone,
        'plan': plan,
        'billing_cycle': billing_cycle,
        'payment_method_id': payment_method_id,
    }


def _slugify_business_name(business_name: str) -> str:
    """Generate a candidate slug from the business name. Falls back to
    a generic prefix if slugify strips everything (unusual but possible
    for purely-symbolic names)."""
    candidate = slugify(business_name)[:63]
    if not _SLUG_PATTERN.match(candidate):
        candidate = f'spa-{candidate}'[:63]
    return candidate


def _pick_available_slug(base: str) -> str:
    """Return ``base`` if free, otherwise append `-2`, `-3`, … until
    we find a free + non-reserved slug. Reserved words always fall
    through to the numbered variant.

    Bounded at 99 retries — a tenant whose business name has 99
    other tenants already claiming numbered variants is a problem
    we'd want to investigate (likely spam).
    """
    if base not in _RESERVED_SLUGS and not Tenant.objects.filter(slug=base).exists():
        return base
    for n in range(2, 100):
        candidate = f'{base[:60]}-{n}'[:63]
        if candidate in _RESERVED_SLUGS:
            continue
        if not Tenant.objects.filter(slug=candidate).exists():
            return candidate
    raise SignupError(
        'slug_unavailable',
        'Could not find an available workspace URL. Please use a more '
        'distinctive business name.',
    )
