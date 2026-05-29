"""Tenant + membership + location models that anchor multi-tenancy.

Five models live here:

  - `Tenant` — one row per spa **business** (one account on Lumè). The `slug`
    field doubles as the subdomain (e.g. `acmespa.lume-crm.com`). Resolved
    per-request by `TenantMiddleware`. Tenant holds account-level data only:
    name, slug, status, branding. Per-site data (address, hours, phone) lives
    on `Location` from Phase 1H session 2 onward.
  - `Location` — a physical site within a tenant. A tenant always has at
    least one location (`is_default=True`); multi-site businesses can add
    more. Each location has its own address, hours, and timezone. Resolved
    per-request by `LocationMiddleware`.
  - `JobTitle` — tenant-customizable list of provider/staff titles (Nurse
    Practitioner, Aesthetician, etc.). The `is_clinical` flag gates chart-signing.
    Tenant-scoped, not location-scoped — same title list applies across sites.
  - `TenantMembership` — links a User to a Tenant with a role, optional job title,
    bookable flag, and per-user permission overrides. Role + payroll terms are
    tenant-scoped; which **locations** the person is assigned to lives on
    `MembershipLocation`.
  - `MembershipLocation` — join table assigning a TenantMembership to one or
    more Locations within its tenant. Allows the same person to work at the
    Manhattan + Brooklyn sites of one business while keeping a single
    role/job-title/payroll record.

For permission resolution, see `apps.tenants.permissions`. To onboard a new tenant
correctly (default location + job titles seeded + Owner membership assigned to
the default location in one transaction), use
`apps.tenants.services.create_tenant_with_defaults`.

Backward-compat note (Session 1 of multi-location work): `Tenant` still carries
the per-site fields (`phone`, address, `business_open_time/close_time`) so the
existing `/settings/business` page keeps working unchanged. Session 2 of the
multi-location work moves that page to read/write `Location`, after which the
duplicate fields can be dropped from `Tenant` in a cleanup migration.
"""

import datetime as _dt
import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.utils import timezone as djtz

from apps.tenants.abstract_models import TenantedModel


class Tenant(models.Model):
    """A single spa account. The `slug` is the subdomain identifier.

    Holds business-profile metadata (name, address, timezone, branding) used by
    booking pages and notifications. PHI never lives here — it lives on tenanted
    models that FK into Tenant via `apps.tenants.abstract_models.TenantedModel`.
    """

    class Status(models.TextChoices):
        TRIAL = 'trial', 'Trial'
        ACTIVE = 'active', 'Active'
        # PAST_DUE = a billing charge failed; workspace goes read-only with
        # an upgrade banner until the customer updates payment. After the
        # configured grace window we move them to SUSPENDED.
        PAST_DUE = 'past_due', 'Past due'
        SUSPENDED = 'suspended', 'Suspended'
        CANCELLED = 'cancelled', 'Cancelled'

    class Plan(models.TextChoices):
        # Trial = the 30-day full-feature window before the first charge.
        # Distinct from STARTER so we can tell "card on file, not yet
        # charged" apart from "card charged, on Starter for real".
        TRIAL = 'trial', 'Trial'
        STARTER = 'starter', 'Starter'
        PRO = 'pro', 'Pro'
        ENTERPRISE = 'enterprise', 'Enterprise'

    class BillingCycle(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly'
        ANNUAL = 'annual', 'Annual'

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=63, unique=True, help_text='Subdomain, e.g. "acmespa" → acmespa.lume-crm.com')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)

    # ── Plan + billing ────────────────────────────────────────────────
    # `plan` drives feature gating via apps.tenants.plans.tenant_has_feature
    # and capacity gates via effective_max_staff / effective_max_locations.
    # Existing tenants created before this field landed get TRIAL by
    # default; the 0013 data migration stamps the 2 live spas to PRO +
    # grandfathered so they keep working unchanged.
    plan = models.CharField(
        max_length=20, choices=Plan.choices, default=Plan.TRIAL,
        help_text='Active subscription tier. Drives feature gating + capacity caps.',
    )
    billing_cycle = models.CharField(
        max_length=10, choices=BillingCycle.choices, default=BillingCycle.MONTHLY,
        help_text='Stripe subscription billing cadence.',
    )
    trial_ends_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the 30-day trial expires. Null for tenants that never went through trial (grandfathered + sales-onboarded Enterprise).',
    )
    current_period_end = models.DateTimeField(
        null=True, blank=True,
        help_text='Mirrored from Stripe subscription. End of the current paid period — used to reset monthly usage counters.',
    )
    billing_email = models.EmailField(
        blank=True, default='',
        help_text='Where Stripe sends receipts + dunning. Often differs from the owner email.',
    )
    stripe_customer_id = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Stripe Customer ID for SaaS subscription billing. Empty for grandfathered tenants who never went through Stripe.',
    )
    stripe_subscription_id = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Stripe Subscription ID. Empty for grandfathered tenants.',
    )
    grandfathered = models.BooleanField(
        default=False,
        help_text=(
            'Set True for the original launch spas onboarded before self-serve '
            'pricing existed. Grandfathered tenants are exempt from plan capacity '
            'gates, never get the upgrade banner, and aren\'t enrolled in Stripe '
            'Billing. Plan stays PRO for them as a feature-flag convenience.'
        ),
    )

    # ── Add-on quantities ─────────────────────────────────────────────
    # Mirrors the quantity-based SubscriptionItem entries on the tenant's
    # Stripe Subscription. Keys are stable add-on identifiers
    # ('staff', 'location', 'email_5k', 'email_10k'); values are integer
    # quantities. Synced from Stripe via the customer.subscription.updated
    # webhook so this row is always the local source of truth for
    # capacity checks.
    addon_quantities = models.JSONField(
        default=dict, blank=True,
        help_text='Per-tenant add-on counts: {"staff": 3, "location": 1, "email_5k": 2}. Mirrors Stripe SubscriptionItem quantities.',
    )

    # ── Compliance acknowledgements (click-through audit) ─────────────
    baa_accepted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the owner accepted the Business Associate Agreement during self-serve signup.',
    )
    baa_version = models.CharField(
        max_length=32, blank=True, default='',
        help_text='Version identifier (e.g. "2026-05") of the BAA accepted. Bumped when BAA text changes; old acceptances stay valid for the version they signed.',
    )
    tos_accepted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the owner accepted the Terms of Service during self-serve signup.',
    )
    tos_version = models.CharField(
        max_length=32, blank=True, default='',
        help_text='Version identifier of the ToS accepted.',
    )

    # ── Usage counters (rolling current period) ───────────────────────
    # Incremented atomically by the SMS / email send wrappers. Reset to 0
    # by the billing webhook handler on each customer.subscription.updated
    # event when current_period_end rolls forward. Used to enforce
    # included quotas + report metered overage to Stripe.
    current_period_sms_count = models.PositiveIntegerField(
        default=0,
        help_text='Outbound SMS sent in the current billing period. Reset on period roll.',
    )
    current_period_email_count = models.PositiveIntegerField(
        default=0,
        help_text='Outbound emails sent in the current billing period. Reset on period roll.',
    )

    # Per-site fields (timezone, address, hours, phone, email) USED to
    # live here. They moved to `Location` during the Phase 4E multi-
    # location rollout — every appointment, calendar query, and booking
    # confirmation email now reads them from the relevant `Location`
    # instead. The Tenant model is now strictly account-level data
    # (identity + status + branding).

    # Branding — applied ONLY to client-facing surfaces (the staff login
    # page on the tenant's subdomain, and the public online booking page
    # in Phase 1I). The internal staff CRM stays on the consistent Lumè
    # design system; this is intentional so workers across multiple
    # tenants get one workspace look.
    primary_color = models.CharField(
        max_length=7,
        default='#1f2937',
        help_text='Brand color as hex (e.g. #1f2937). Applied to the login page and public booking page only.',
    )
    logo_url = models.URLField(
        blank=True,
        help_text=(
            'Public URL of the spa\'s logo. Applied to the login page '
            'and public booking page only. Direct upload UI is on the '
            'roadmap; for now paste a URL pointing at a hosted PNG/SVG.'
        ),
    )

    # ── Online booking settings ──────────────────────────────────────
    # Per-tenant configuration for the public booking page (apps.booking).
    # Owner-editable via /org/online-booking. The killswitch defaults
    # ON because new tenants opt in to all customer-facing surfaces by
    # default; an operator can flip it to OFF during off-hours, while
    # rebuilding their service catalog, or to disable online bookings
    # entirely. When OFF, the public endpoints return 404 — same
    # posture as a slug that doesn't exist (we don't leak which spas
    # are simply paused).
    online_booking_enabled = models.BooleanField(
        default=True,
        help_text='Master switch for the public booking page. When off, the booking URL returns 404.',
    )
    online_booking_lead_minutes = models.PositiveIntegerField(
        default=30,
        help_text=(
            'Minimum minutes before a slot can be booked online. '
            'Front desk uses this to guarantee prep time. 30 min is a '
            'reasonable default; busy med-spas often raise this to 120.'
        ),
    )
    online_booking_window_days = models.PositiveIntegerField(
        default=60,
        help_text=(
            'How many days into the future customers can book. Caps '
            'speculative bookings far out (which are also the most '
            'likely to no-show). Set to a small number during peak '
            'season; large during slow seasons.'
        ),
    )
    online_booking_welcome_message = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Optional greeting shown above the service catalog on the '
            'public booking page. Two or three sentences max — used '
            'for seasonal promos, "new patient welcome" copy, or '
            'parking / accessibility notes.'
        ),
    )
    online_booking_cancellation_policy = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Cancellation / no-show policy text shown to customers on '
            'the booking detail page and the manage-booking page. '
            'Plain text; no formatting. Most spas paste their existing '
            '"24-hour notice required" language here.'
        ),
    )

    # Per-tenant SMS sender number. Set manually by the platform
    # admin (Django admin for v1; Platform Admin UI later) after the
    # spa's toll-free number is verified with Twilio. When blank,
    # outbound SMS falls back to `settings.TWILIO_FROM_NUMBER` (the
    # platform-shared default). E.164 format expected — e.g.
    # `+18885551234`. Future polish: validation + a Platform Admin
    # workflow to provision + verify per-tenant TFNs end-to-end.
    twilio_from_number = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text=(
            'Per-tenant SMS sender (E.164, e.g. "+18885551234"). When '
            'blank, falls back to the platform-default TWILIO_FROM_NUMBER. '
            'Recipients see this number as the From; reputation lives '
            'on this number per tenant.'
        ),
    )

    # ── Automated SMS templates ──────────────────────────────────────
    #
    # Operator-editable bodies for the three automated transactional
    # SMS surfaces. Empty = use the shipped default (see
    # `apps.appointments.sms.DEFAULT_*_BODY`). Tokens recognised at
    # render time:
    #
    #   {{first_name}}        — customer first name
    #   {{spa_name}}          — this tenant's name
    #   {{appointment_time}}  — formatted local time of the appointment
    #   {{review_url}}        — review-request template only
    #
    # Operator-typed text is validated for length (1600-char cap, same
    # as the manual send endpoint) but otherwise stored verbatim. The
    # render path's token substitution is a literal `str.replace`, NOT
    # a templating engine — never call any Python expression from
    # user text.
    confirmation_sms_template = models.TextField(
        blank=True, default='',
        help_text=(
            'Custom SMS body sent when an appointment is booked. Empty '
            'falls back to the platform default. Tokens: {{first_name}}, '
            '{{spa_name}}, {{appointment_time}}.'
        ),
    )
    reminder_sms_template = models.TextField(
        blank=True, default='',
        help_text=(
            'Custom SMS body sent 24 hours before the appointment. Empty '
            'falls back to the platform default. Tokens: {{first_name}}, '
            '{{spa_name}}, {{appointment_time}}.'
        ),
    )
    review_request_sms_template = models.TextField(
        blank=True, default='',
        help_text=(
            'Custom SMS body sent after an appointment is marked '
            'completed (waits `review_request_hours_after` hours). Empty '
            'falls back to the platform default. Tokens: {{first_name}}, '
            '{{spa_name}}, {{review_url}}.'
        ),
    )
    review_request_enabled = models.BooleanField(
        default=False,
        help_text=(
            'Explicit opt-in for the post-appointment review-request '
            'SMS. Defaults False so tenants don\'t accidentally send '
            'reviews requests before they\'ve set their Google Review '
            'URL. The cron worker skips this tenant when False.'
        ),
    )
    review_request_hours_after = models.PositiveSmallIntegerField(
        default=24,
        help_text=(
            'How many hours after appointment completion the review '
            'request should go out. 24 (next day) is the industry '
            'default — gives the customer time to enjoy the result + '
            'still keeps the experience fresh in their mind.'
        ),
    )
    google_review_url = models.URLField(
        blank=True, default='',
        max_length=500,
        help_text=(
            "The tenant's Google Place review URL (e.g. "
            'https://g.page/r/CXXXXX/review). Substituted into the '
            '{{review_url}} token. When blank + the template references '
            'the token, the worker skips the send rather than text a '
            'broken link.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class JobTitle(models.Model):
    """Tenant-customizable job title (e.g. 'Nurse Practitioner', 'Aesthetician').

    `is_clinical` gates the ability to sign chart notes / treatment records.
    Each tenant gets a default seed list (see services.create_tenant_with_defaults).
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='job_titles')
    name = models.CharField(max_length=100)
    is_clinical = models.BooleanField(
        default=False,
        help_text='Clinical job titles can sign chart notes and treatment records.',
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('tenant', 'name')]
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class TenantMembership(models.Model):
    """Links a User to a Tenant with a role and per-tenant settings.

    A user can be a member of multiple tenants with different roles per tenant.
    Permission resolution: (ROLE_DEFAULTS[role] ∪ extra_permissions) − revoked_permissions.
    """

    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        MANAGER = 'manager', 'Manager'
        FRONT_DESK = 'front_desk', 'Front Desk'
        PROVIDER = 'provider', 'Provider'
        BOOKKEEPER = 'bookkeeper', 'Bookkeeper'
        MARKETING = 'marketing', 'Marketing'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices)

    job_title = models.ForeignKey(JobTitle, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    is_bookable = models.BooleanField(
        default=False,
        help_text='Whether this person appears in the booking calendar as a bookable resource.',
    )
    is_active = models.BooleanField(default=True)

    extra_permissions = models.JSONField(default=list, blank=True, help_text='Permissions granted on top of role defaults.')
    revoked_permissions = models.JSONField(default=list, blank=True, help_text='Permissions stripped from role defaults.')

    hipaa_training_acknowledged_at = models.DateTimeField(null=True, blank=True)

    # Employment + payroll — per-tenant because the same person can have
    # different terms at different centers (full-time at Spa A, contractor
    # at Spa B). All optional; not required to create a membership. The
    # /staff/employees/[id] page exposes these to owners and managers.
    class EmploymentType(models.TextChoices):
        FULL_TIME = 'full_time', 'Full-time'
        PART_TIME = 'part_time', 'Part-time'
        CONTRACTOR = 'contractor', 'Contractor'

    class PayType(models.TextChoices):
        HOURLY = 'hourly', 'Hourly'
        SALARY = 'salary', 'Salary'
        COMMISSION_ONLY = 'commission_only', 'Commission only'

    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        blank=True,
        help_text='Full-time / part-time / contractor at this tenant.',
    )
    pay_type = models.CharField(
        max_length=20,
        choices=PayType.choices,
        blank=True,
        help_text='How this person is paid. Commission-only means no base pay.',
    )
    pay_rate_cents = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Pay rate in cents. Interpretation depends on pay_type: cents/hour '
            'for HOURLY, cents/year for SALARY, ignored for COMMISSION_ONLY. '
            'Stored as an integer to dodge float rounding on the money path.'
        ),
    )
    hire_date = models.DateField(null=True, blank=True)
    employment_notes = models.TextField(
        blank=True,
        help_text='Internal notes about this employment relationship — visible to owners + managers only.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'tenant')]

    def __str__(self):
        return f"{self.user.email} @ {self.tenant.name} ({self.get_role_display()})"

    def has(self, permission: str) -> bool:
        """Return True if this membership has the given permission, factoring in role defaults and overrides."""
        from .permissions import has_permission
        return has_permission(self, permission)


class Location(models.Model):
    """A physical site within a tenant.

    A tenant always has at least one location (the one created during
    onboarding gets `is_default=True`). Multi-site businesses add more
    locations; the dashboard, calendar, and reports scope to whichever
    location the operator has selected (resolved per-request by
    `LocationMiddleware`).

    Address, business hours, timezone, and phone live here — they vary
    per-site (a Manhattan and Brooklyn location of the same spa have
    different addresses + hours; a NY and LA location of the same spa
    have different timezones).

    Why `is_default` instead of just "the first one": data migrations
    and onboarding need a deterministic fallback when no specific
    location has been chosen yet (e.g. a freshly logged-in user before
    they pick from the location switcher). The default flag survives
    location renames + reorderings; "the first one by id" wouldn't.

    Soft-delete via `is_active=False`. Hard delete is intentionally not
    exposed because appointments, invoices, and payroll records FK into
    Location and the audit trail must be preserved.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='locations')
    name = models.CharField(max_length=120, help_text='Display name, e.g. "Manhattan" or "Brooklyn".')
    slug = models.SlugField(
        max_length=63,
        help_text='URL-safe identifier scoped to the tenant (used by the active-location cookie).',
    )
    is_default = models.BooleanField(
        default=False,
        help_text=(
            'Exactly one location per tenant is the default. Used as the fallback when '
            'no active location is set (fresh login, missing cookie, deleted location). '
            'Enforced by a partial unique index on (tenant, is_default=True).'
        ),
    )
    is_active = models.BooleanField(default=True)

    timezone = models.CharField(
        max_length=50,
        default='America/New_York',
        help_text='IANA timezone for this site. Different sites of the same business may differ.',
    )
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True, help_text='Site-specific contact email; falls back to tenant email if blank.')
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)

    business_open_time = models.TimeField(
        default='08:00',
        help_text='When this site opens. Drives this location\'s calendar day-axis bounds.',
    )
    business_close_time = models.TimeField(
        default='20:00',
        help_text='When this site closes. Drives this location\'s calendar day-axis bounds.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['tenant', 'name']
        constraints = [
            UniqueConstraint(
                fields=['tenant', 'slug'],
                name='unique_location_slug_per_tenant',
            ),
            UniqueConstraint(
                fields=['tenant'],
                condition=Q(is_default=True),
                name='one_default_location_per_tenant',
            ),
        ]

    def __str__(self):
        return f'{self.tenant.name} — {self.name}'


class MembershipLocation(models.Model):
    """Assigns a TenantMembership to a specific Location within its tenant.

    A single membership can have many MembershipLocation rows — that's how
    "Sarah works at both the Manhattan and Brooklyn sites" is represented
    while keeping one canonical role/job-title/payroll record per tenant.

    `is_active` is a per-site soft-toggle: an employee can be temporarily
    suspended at one site without removing them from the other (e.g. moved
    to cover a different location for a quarter). Their tenant-level
    `TenantMembership.is_active` still gates whether they can sign in
    at all.

    Why a join model rather than `MembershipLocation = M2M`: gives us
    space to add per-location overrides later (custom hours, location-
    specific schedule notes, primary-site flag for paystub mailing
    address) without a schema rewrite. For Session 1, only `is_active`
    lives here on top of the FKs.
    """

    membership = models.ForeignKey(
        TenantMembership, on_delete=models.CASCADE, related_name='location_assignments',
    )
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='membership_assignments',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('membership', 'location')]
        ordering = ['location', 'membership']

    def __str__(self):
        return f'{self.membership.user.email} @ {self.location.name}'


class ProviderSchedule(models.Model):
    """Weekly recurring working hours for a staff member at one location.

    1:1 with `MembershipLocation` so the same person can have different
    hours at different sites — Sarah works 9-5 Mon-Fri at Manhattan but
    only Sat 10-3 at Brooklyn. Schedule rows aren't auto-created with
    the assignment; they materialize on first PUT (lazy creation keeps
    `MembershipLocation` writes cheap and lets the editor distinguish
    "no schedule set" from "explicitly off every day").

    `weekly_hours` is JSON keyed by lowercase weekday name with arrays
    of `{start, end}` blocks (HH:MM strings). Empty array = "off that
    day." Multiple blocks per day support split shifts and lunch
    breaks. Validation lives in the serializer (cross-block overlap
    checks aren't expressible as a DB constraint).

    Example::

        {
          "monday":    [{"start": "09:00", "end": "17:00"}],
          "tuesday":   [{"start": "09:00", "end": "13:00"}, {"start": "14:00", "end": "18:00"}],
          "wednesday": [],   # off
          ...
        }

    Calendar consumption: the day view dims any time outside the
    provider's working blocks for the day. Online booking (Phase 1I)
    will only offer slots inside the blocks. No overlap with the
    `Tenant`-level "this person hasn't been assigned anywhere" state —
    if they have no MembershipLocation here, the schedule is moot.

    Effective-from / per-date overrides ("Sarah is off Christmas Eve")
    are intentionally out of scope for v1. PUT replaces the weekly
    template entirely; the audit log captures the before/after for
    history. Per-date exceptions land in a follow-up.
    """

    WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')

    membership_location = models.OneToOneField(
        MembershipLocation,
        on_delete=models.CASCADE,
        related_name='schedule',
    )
    weekly_hours = models.JSONField(
        default=dict,
        help_text=(
            'Per-weekday blocks: {"monday": [{"start": "09:00", "end": "17:00"}], ...}. '
            'Empty array per day = off. Multiple blocks per day support split shifts.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['membership_location']

    def __str__(self):
        return f'Schedule for {self.membership_location}'

    @staticmethod
    def empty_weekly_hours() -> dict:
        """The canonical empty schedule — every day is off. Used as the
        default when a schedule hasn't been set yet, so the API can
        return a consistent shape regardless of whether the row exists."""
        return {day: [] for day in ProviderSchedule.WEEKDAYS}


# ── Staff invitations ─────────────────────────────────────────────────


def _default_invitation_expiry() -> _dt.datetime:
    """7-day default validity window. Tunable later via tenant settings
    if a spa wants longer / shorter; 7d covers a busy spa owner who's
    not in the CRM every day."""
    return djtz.now() + _dt.timedelta(days=7)


def _generate_invitation_token() -> str:
    """43-char URL-safe random token. 256 bits of entropy via
    `secrets.token_urlsafe(32)` — adequate for a 7-day-validity
    single-use invitation token. Stored in the DB as plaintext (it's
    already a secret-class identifier; hashing would prevent
    legitimate token-lookup on accept)."""
    return secrets.token_urlsafe(32)


class Invitation(TenantedModel):
    """A pending invitation to join a tenant as staff.

    Created by an owner / manager via `POST /api/memberships/invite/`.
    The recipient gets an email with a tokenized link
    (`/accept-invitation/<token>`). On accept, a `TenantMembership` is
    created with the role + job_title + is_bookable captured here.

    Replaces the legacy temp-password-on-direct-add flow (still
    available for attaching existing-user accounts that bypass email).
    See ADR 0019.
    """

    email = models.EmailField(
        help_text=(
            'Recipient address. Case-insensitive uniqueness within a tenant '
            'for pending (unaccepted, unexpired) invitations is enforced by '
            'service-layer check before insert — partial-unique-index in DB '
            'is hard to express across `accepted_at IS NULL AND expires_at > now()`.'
        ),
    )
    role = models.CharField(
        max_length=20,
        choices=TenantMembership.Role.choices,
    )
    job_title = models.ForeignKey(
        JobTitle,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text='Optional job-title assignment to apply on accept.',
    )
    is_bookable = models.BooleanField(default=False)

    token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_invitation_token,
        editable=False,
    )
    expires_at = models.DateTimeField(default=_default_invitation_expiry)

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='invitations_sent',
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='invitations_accepted',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'email']),
            models.Index(fields=['tenant', 'accepted_at']),
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        suffix = ' (accepted)' if self.accepted_at else ' (pending)'
        return f'Invitation<{self.email} → {self.tenant.slug}>{suffix}'

    @property
    def is_pending(self) -> bool:
        return self.accepted_at is None and self.expires_at > djtz.now()

    @property
    def is_expired(self) -> bool:
        return self.accepted_at is None and self.expires_at <= djtz.now()
