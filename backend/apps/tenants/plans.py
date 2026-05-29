"""Plan + feature catalog for the multi-tier SaaS pricing model.

The full pricing plan (Starter / Pro / Enterprise + add-ons + Stripe
billing) is documented at
``~/.claude/plans/abstract-bouncing-trinket.md``. This module is the
canonical source of truth for "what does each tier include" inside the
codebase.

Why a Python catalog instead of a `Plan` model:

  - The tier shape changes at the cadence of marketing decisions, not
    runtime data. A schema migration + deploy is the right friction
    for that.
  - With only three tiers + a small add-on catalog, a hand-edited dict
    is easier to read and review than a many-rows-and-relations model.
  - Pricing strings live in marketing + Stripe (not here) so this
    catalog stays focused on *what the tenant gets*, not what it costs.

Grandfathered tenants — the two original launch spas onboarded before
self-serve existed — always get the full feature set and unlimited
capacity, regardless of their nominal plan. ``grandfathered=True``
short-circuits every helper here.

HIPAA + SOC 2 framing: feature gating is a customer-facing capability
boundary. PHI access controls remain governed by
``apps.tenants.permissions`` (role + permission catalog). The two
systems compose: a tenant must have BOTH the plan (this module) AND
the permission (the permission catalog) for a feature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.tenants.models import Tenant


# ── Feature keys ───────────────────────────────────────────────────────
#
# String constants used as feature identifiers throughout the codebase.
# Group them by domain so it's obvious which features belong together.
# Adding a new feature: add the constant, add it to the relevant plan
# set(s), then reference it from the view via ``PlanFeatureRequired``.


# Always-on features (every tier including Starter; Trial inherits Pro
# so it gets these implicitly too).
F_CORE_CRM = 'core_crm'
F_ONLINE_BOOKING = 'online_booking'
F_FORMS = 'forms'
# Clinical chart notes intentionally ship in every tier — a medspa
# CRM that gates clinical records to Pro defeats its own value prop.
F_CLINICAL_NOTES = 'clinical_notes'
F_PACKAGES = 'packages'
F_MEMBERSHIPS = 'memberships'
F_GIFT_CARDS = 'gift_cards'
F_WAITLIST = 'waitlist'
F_TIME_TRACKING = 'time_tracking'
F_BASIC_REPORTS = 'basic_reports'
F_CUSTOMER_PORTAL_BASIC = 'customer_portal_basic'

# Pro+ features
F_ALL_REPORTS = 'all_reports'
F_SMS_INBOX = 'sms_inbox'
F_EMAIL_MARKETING = 'email_marketing'
F_EMAIL_AUTOMATIONS = 'email_automations'
F_COMMISSIONS = 'commissions'
F_PAYROLL_EXPORT = 'payroll_export'
F_WHITE_LABEL_BASIC = 'white_label_basic'
F_PROVIDER_SCHEDULER = 'provider_scheduler'
F_LINE_DISCOUNTS = 'line_discounts'
F_TENANT_TFN = 'tenant_tfn'
F_CUSTOMER_PORTAL_FULL = 'customer_portal_full'
F_ALL_ROLES = 'all_roles'
F_CUSTOM_MERCHANT = 'custom_merchant'

# Intentionally NOT in any public tier set yet. Grandfathered tenants
# inherit it via the union in ``features_for``. New self-serve Starter
# / Pro / Enterprise signups don't see it in their nav until Meta App
# Review approves the integration and we graduate it into
# ENTERPRISE_FEATURES (and the marketing page lists it as a confirmed
# Enterprise capability). Hiding it from public tiers prevents selling
# something Meta hasn't blessed us to ship.
F_SOCIAL_INTEGRATIONS = 'social_integrations'


STARTER_FEATURES: frozenset[str] = frozenset({
    F_CORE_CRM, F_ONLINE_BOOKING, F_FORMS, F_CLINICAL_NOTES,
    F_PACKAGES, F_MEMBERSHIPS, F_GIFT_CARDS, F_WAITLIST,
    F_TIME_TRACKING, F_BASIC_REPORTS, F_CUSTOMER_PORTAL_BASIC,
})

PRO_FEATURES: frozenset[str] = STARTER_FEATURES | frozenset({
    F_ALL_REPORTS, F_SMS_INBOX, F_EMAIL_MARKETING, F_EMAIL_AUTOMATIONS,
    F_COMMISSIONS, F_PAYROLL_EXPORT, F_WHITE_LABEL_BASIC,
    F_PROVIDER_SCHEDULER, F_LINE_DISCOUNTS, F_TENANT_TFN,
    F_CUSTOMER_PORTAL_FULL, F_ALL_ROLES, F_CUSTOM_MERCHANT,
})

# Enterprise gets everything Pro has today. As features that are
# currently roadmap-only (Meta DM, mobile app, custom domain, SSO,
# public API) ship, add their feature keys here AND only here — they
# graduate to confirmed Enterprise features once Meta App Review /
# Apple App Store approval / dev work clears.
ENTERPRISE_FEATURES: frozenset[str] = PRO_FEATURES | frozenset({
    # (no extra confirmed features yet — placeholder set)
})

# Trial = Pro features (the trial preview). When the trial converts to
# a real plan, the tenant's ``plan`` flips and the feature set follows.
TRIAL_FEATURES = PRO_FEATURES


# ── Plan capacity baselines ────────────────────────────────────────────
#
# ``None`` = unlimited. Add-ons stack on top of the baseline (see
# ``effective_max_*`` helpers). Capacities mirror the public pricing
# page; changes here must also propagate to ``marketing/src/app/pricing``.

_PLAN_CAPACITY: dict[str, dict] = {
    'trial': {
        # Trial inherits Pro capacity so the operator can populate a
        # realistic working spa during the 30-day window.
        'max_staff': 10,
        'max_locations': 3,
        'sms_included': 1_500,
        'email_included': 20_000,
    },
    'starter': {
        'max_staff': 2,
        'max_locations': 1,
        'sms_included': 500,
        'email_included': 2_000,
    },
    'pro': {
        'max_staff': 10,
        'max_locations': 3,
        'sms_included': 1_500,
        'email_included': 20_000,
    },
    'enterprise': {
        'max_staff': None,
        'max_locations': None,
        'sms_included': 5_000,
        'email_included': 100_000,
    },
}

_PLAN_FEATURES: dict[str, frozenset[str]] = {
    'trial': TRIAL_FEATURES,
    'starter': STARTER_FEATURES,
    'pro': PRO_FEATURES,
    'enterprise': ENTERPRISE_FEATURES,
}


# ── Add-on definitions ─────────────────────────────────────────────────
#
# Each add-on is keyed by its identifier (the JSON key on
# ``Tenant.addon_quantities``). ``delta`` is how much one unit of the
# add-on adds to the capacity it scales; ``allowed_plans`` enumerates
# which tiers can buy it (Stripe webhook + the /settings/billing endpoint
# enforce). Pricing strings live in Stripe + the marketing site, not
# here — this catalog only knows about capacity effects.

_ADDONS = {
    'staff': {
        'delta': 1,
        'capacity_key': 'max_staff',
        'allowed_plans': {'starter', 'pro'},
        'max_quantity': None,  # No hard cap; expensive enough to self-limit
    },
    'location': {
        'delta': 1,
        'capacity_key': 'max_locations',
        'allowed_plans': {'pro'},   # Starter can't add locations
        'max_quantity': 2,           # Pro caps at +2 (= 5 total); beyond → Enterprise
    },
    'email_5k': {
        # Starter email pack (5k extra emails per pack per month).
        'delta': 5_000,
        'capacity_key': 'email_included',
        'allowed_plans': {'starter'},
        'max_quantity': None,
    },
    'email_10k': {
        # Pro email pack (10k extra emails per pack — bulk discount).
        'delta': 10_000,
        'capacity_key': 'email_included',
        'allowed_plans': {'pro'},
        'max_quantity': None,
    },
}


# ── Helpers ────────────────────────────────────────────────────────────


def features_for(tenant: 'Tenant') -> frozenset[str]:
    """The full set of feature keys the tenant has access to right now.

    Grandfathered tenants get every feature defined in the catalog —
    they predate the tier structure and were promised the full surface
    they were using. That includes "in-flight" features like
    ``F_SOCIAL_INTEGRATIONS`` that aren't in any public tier set yet:
    a grandfathered spa who wants to try Meta DM can, even though new
    self-serve tenants can't.
    """
    if getattr(tenant, 'grandfathered', False):
        # Union of every plan's feature set + any in-flight features
        # that aren't in a public tier yet (Meta integrations etc.).
        return (
            ENTERPRISE_FEATURES
            | PRO_FEATURES
            | STARTER_FEATURES
            | _IN_FLIGHT_FEATURES
        )
    return _PLAN_FEATURES.get(tenant.plan, frozenset())


# Features that exist in the codebase but aren't yet sellable on any
# public tier — usually waiting on external approval (Meta App Review,
# Apple App Store) or last-mile polish. Listed here so grandfathered
# tenants can use them and so it's easy to graduate them later (just
# add to the relevant tier set + remove from this list).
_IN_FLIGHT_FEATURES: frozenset[str] = frozenset({
    F_SOCIAL_INTEGRATIONS,
})


def tenant_has_feature(tenant: 'Tenant', feature_key: str) -> bool:
    """Convenience predicate for permission classes + UI gating."""
    return feature_key in features_for(tenant)


def _addon_qty(tenant: 'Tenant', addon_key: str) -> int:
    """Number of units of ``addon_key`` the tenant has purchased."""
    raw = (tenant.addon_quantities or {}).get(addon_key, 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _capacity_total(
    tenant: 'Tenant',
    capacity_key: str,
) -> int | None:
    """Sum of plan baseline + every applicable add-on for ``capacity_key``.

    Returns ``None`` when the baseline is unlimited (Enterprise) — the
    caller treats None as "no cap, allow anything." Grandfathered
    tenants also short-circuit to None.
    """
    if getattr(tenant, 'grandfathered', False):
        return None

    plan_caps = _PLAN_CAPACITY.get(tenant.plan, {})
    baseline = plan_caps.get(capacity_key)
    if baseline is None:
        return None

    total = baseline
    for addon_key, spec in _ADDONS.items():
        if spec['capacity_key'] != capacity_key:
            continue
        if tenant.plan not in spec['allowed_plans']:
            # Tenant shouldn't have bought this add-on at all on this
            # plan; ignore it for capacity math. Stripe's checkout +
            # /settings/billing both block purchase, so this is a
            # defensive guard.
            continue
        qty = _addon_qty(tenant, addon_key)
        if spec['max_quantity'] is not None:
            qty = min(qty, spec['max_quantity'])
        total += qty * spec['delta']

    return total


def effective_max_staff(tenant: 'Tenant') -> int | None:
    """Capacity for active TenantMemberships across the tenant.

    Enforced in ``TenantMembership`` create paths. Owner is counted
    against the cap — a Starter spa with ``max_staff=2`` means owner +
    one staff member, not owner + two.
    """
    return _capacity_total(tenant, 'max_staff')


def effective_max_locations(tenant: 'Tenant') -> int | None:
    """Capacity for active Location rows on the tenant.

    Enforced in the Location create path. The default location seeded
    at tenant create counts against the cap.
    """
    return _capacity_total(tenant, 'max_locations')


def effective_monthly_email_quota(tenant: 'Tenant') -> int | None:
    """Per-period inclusive email cap. Sends past this block (do not
    overage-bill) — operators see an explicit upsell to buy another
    email pack rather than getting a surprise invoice."""
    return _capacity_total(tenant, 'email_included')


def effective_monthly_sms_quota(tenant: 'Tenant') -> int | None:
    """Per-period inclusive SMS cap. Sends past this are NOT blocked
    — they're metered to Stripe at the per-msg overage rate. The
    pay-as-you-go pricing is set per tier in the Stripe Product config,
    not here."""
    return _capacity_total(tenant, 'sms_included')


# ── Add-on metadata access (for /settings/billing + Stripe sync) ──────


def allowed_addons_for_plan(plan: str) -> dict[str, dict]:
    """Add-ons the given plan is allowed to purchase, keyed by addon key.

    Returns the full spec dict for each — callers can read ``delta``,
    ``max_quantity``, etc. Used by the /settings/billing endpoint to
    render the right control set per tier.
    """
    return {
        key: dict(spec)
        for key, spec in _ADDONS.items()
        if plan in spec['allowed_plans']
    }


def is_addon_quantity_valid(
    plan: str,
    addon_key: str,
    quantity: int,
) -> tuple[bool, str | None]:
    """Validate a requested add-on quantity for a plan. Returns
    ``(ok, error_message)``. Used by /settings/billing before pushing
    a quantity change to Stripe."""
    spec = _ADDONS.get(addon_key)
    if spec is None:
        return False, f'Unknown add-on "{addon_key}".'
    if plan not in spec['allowed_plans']:
        return False, f'Add-on "{addon_key}" is not available on the {plan} plan.'
    if quantity < 0:
        return False, 'Add-on quantity cannot be negative.'
    if spec['max_quantity'] is not None and quantity > spec['max_quantity']:
        return False, (
            f'Add-on "{addon_key}" is capped at {spec["max_quantity"]} '
            f'units on this plan (upgrade for more).'
        )
    return True, None
