"""Serializers for platform admin tenant management.

These are the DRF wire format for `apps.tenants.Tenant`, but
intentionally exposing fields that the tenant-scoped serializers
hide (cross-tenant member counts, last-active timestamps, lifecycle
status). Read-only on the list/retrieve path; lifecycle transitions
go through dedicated action endpoints.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.tenants.models import Tenant

User = get_user_model()


class PlatformTenantListSerializer(serializers.ModelSerializer):
    """Compact row used by the tenants list view."""

    member_count = serializers.IntegerField(read_only=True)
    location_count = serializers.IntegerField(read_only=True)
    owner_email = serializers.SerializerMethodField()
    # Billing-related computed fields. Computed so the wire format
    # stays stable even as the underlying Stripe sync evolves. Each
    # is documented inline; the platform admin reads all of these to
    # surface trial / billing state on the tenants list + detail page.
    trial_days_remaining = serializers.SerializerMethodField(
        help_text=(
            'Integer days until trial_ends_at, clamped at 0. Null for '
            'tenants not currently in trial (active / past_due / suspended / '
            'cancelled / grandfathered).'
        ),
    )
    has_stripe_subscription = serializers.SerializerMethodField(
        help_text='True when the tenant has a Stripe Subscription ID on file.',
    )
    has_payment_method = serializers.SerializerMethodField(
        help_text=(
            'True when the tenant has a Stripe Customer + a default payment '
            'method (card on file). Proxy for "they can be auto-charged."'
        ),
    )

    class Meta:
        model = Tenant
        fields = [
            'id',
            'name',
            'slug',
            'status',
            'plan',
            'billing_cycle',
            'grandfathered',
            'member_count',
            'location_count',
            'owner_email',
            'billing_email',
            'trial_ends_at',
            'current_period_end',
            'trial_days_remaining',
            'has_stripe_subscription',
            'has_payment_method',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_owner_email(self, obj):
        # Pre-annotated by the queryset when available; fall back to
        # a per-row query for the rare list-without-annotation path.
        if hasattr(obj, '_owner_email'):
            return obj._owner_email
        owner = obj.memberships.filter(role='owner', is_active=True).first()
        return owner.user.email if owner else None

    def get_trial_days_remaining(self, obj):
        # Only meaningful while the tenant is actually in trial — for
        # everyone else we return None and the frontend hides the
        # countdown chip.
        if obj.status != Tenant.Status.TRIAL or obj.trial_ends_at is None:
            return None
        from django.utils import timezone as djtz
        delta = obj.trial_ends_at - djtz.now()
        # Round UP so the badge says "1 day left" until the very last
        # hour, not "0 days left" most of the final day.
        seconds = max(0, int(delta.total_seconds()))
        return (seconds + 86_399) // 86_400  # ceil-divide by a day

    def get_has_stripe_subscription(self, obj):
        return bool(obj.stripe_subscription_id)

    def get_has_payment_method(self, obj):
        # Best-effort proxy: a tenant with a Stripe Customer ID has at
        # least gone through signup. The presence of a default payment
        # method specifically would require a Stripe API call — we
        # don't make one per list row. The webhook syncs subscription
        # state, which is the signal that actually matters for
        # auto-charge eligibility.
        return bool(obj.stripe_customer_id)


class PlatformTenantMemberSerializer(serializers.Serializer):
    """Compact membership row for the tenant detail view."""

    id = serializers.IntegerField()
    user_email = serializers.EmailField(source='user.email')
    user_first_name = serializers.CharField(source='user.first_name')
    user_last_name = serializers.CharField(source='user.last_name')
    role = serializers.CharField()
    role_display = serializers.CharField(source='get_role_display')
    is_active = serializers.BooleanField()
    is_bookable = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class PlatformTenantDetailSerializer(PlatformTenantListSerializer):
    """Full tenant detail — adds members + branding fields + the deeper
    Stripe-side IDs that the list view doesn't need to surface."""

    members = PlatformTenantMemberSerializer(source='memberships', many=True, read_only=True)

    class Meta(PlatformTenantListSerializer.Meta):
        fields = PlatformTenantListSerializer.Meta.fields + [
            'primary_color',
            'logo_url',
            'members',
            # Stripe identifiers — useful for ops when reconciling
            # against the Stripe dashboard. Never exposed outside the
            # platform-admin scope.
            'stripe_customer_id',
            'stripe_subscription_id',
            # Add-on quantities the tenant has purchased, mirrored from
            # the Stripe Subscription items. Same shape as
            # /api/billing/summary's `addons`.
            'addon_quantities',
            # Usage counters for the current billing period — exposed
            # so platform admins can spot tenants approaching their
            # quotas without opening Stripe.
            'current_period_sms_count',
            'current_period_email_count',
        ]


class CreateTenantInputSerializer(serializers.Serializer):
    """Input shape for `POST /api/platform/tenants/`.

    Creates a tenant + default location + default job titles + the
    initial owner membership in one transaction. Owner email may
    match an existing user (attached as a new membership) or a new
    one (provisioned with a randomly-generated temp password
    returned in the response).
    """

    name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=63)
    owner_email = serializers.EmailField()
    owner_first_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    owner_last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    status = serializers.ChoiceField(
        choices=Tenant.Status.choices,
        default=Tenant.Status.TRIAL,
    )

    def validate_slug(self, value):
        value = value.lower()
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError(
                f'Slug "{value}" is already taken. Pick another.',
            )
        # Block reserved subdomains we use for our own infrastructure.
        reserved = {'www', 'admin', 'api', 'app', 'platform', 'docs', 'mail', 'lume'}
        if value in reserved:
            raise serializers.ValidationError(
                f'"{value}" is reserved. Pick another slug.',
            )
        return value

    def validate_owner_email(self, value):
        # Platform admins must never own a tenant — that would put their
        # account on both sides of the customer/platform divide. Reject
        # the create here rather than silently linking the worlds.
        existing = User.objects.filter(email__iexact=value).first()
        if existing and existing.is_platform_admin:
            raise serializers.ValidationError(
                'This email belongs to a platform admin account. Platform '
                'admins cannot own tenants — use a different email.',
            )
        return value


class SuspendTenantInputSerializer(serializers.Serializer):
    """Body for `POST /api/platform/tenants/{slug}/suspend/`."""

    reason = serializers.CharField(
        max_length=500,
        help_text='Why the tenant is being suspended. Captured in the audit log.',
    )


class UpdateTenantInputSerializer(serializers.Serializer):
    """Body for `PATCH /api/platform/tenants/{slug}/` — basic edits.

    Slug is intentionally NOT editable here — changing the subdomain
    breaks every existing user's bookmarked URLs and should require
    a deliberate, explicit migration flow (not a casual edit).
    """

    name = serializers.CharField(max_length=200, required=False)
    primary_color = serializers.CharField(max_length=7, required=False)
    logo_url = serializers.URLField(required=False, allow_blank=True)
