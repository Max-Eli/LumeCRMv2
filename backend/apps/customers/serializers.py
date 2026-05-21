"""DRF serializers for the customers API.

Two serializers:

  - `CustomerListSerializer` — minimal record for the list view (id, name,
    contact, status, tags). Excludes medical PHI to keep list payloads small
    and to align with HIPAA "minimum necessary" for routine browsing.
  - `CustomerDetailSerializer` — full record including PHI. Used for the
    create/retrieve/update/delete actions where the user has been gated
    through `CustomerPermission`.

Tag association uses `tag_ids` (write-only) for input and `tags` (nested
read-only) for output, so consumers only have to send a list of integers.
"""

from django.utils import timezone as djtz
from rest_framework import serializers

from apps.tenants.permissions import P

from .models import Customer, CustomerTag


# Fields the `CustomerDetailSerializer` redacts when the requesting user
# lacks `VIEW_CLIENT_PHI`. The set tracks 45 CFR 164.514's HIPAA identifiers
# applicable to a CRM record: birthdate, geographic subdivisions smaller than
# state, and any free-text field that routinely contains clinical impressions.
# Contact fields (email, phone) are intentionally NOT redacted: front-desk
# staff need them to call/email about bookings, and the email/phone of a
# spa client is not a HIPAA identifier when not combined with diagnosis.
# See ADR 0017.
PHI_FIELDS = frozenset({
    'date_of_birth', 'sex',
    'address_line1', 'address_line2', 'city', 'state', 'zip_code',
    'emergency_name', 'emergency_phone', 'emergency_relationship',
    'medical_history', 'allergies', 'medications', 'skin_type_fitzpatrick',
    'notes',
})


class CustomerTagSerializer(serializers.ModelSerializer):
    """Read/write serializer for `CustomerTag`."""

    class Meta:
        model = CustomerTag
        fields = ['id', 'name', 'color', 'sort_order']


class ReferralCustomerSerializer(serializers.ModelSerializer):
    """Minimal customer reference used by both ends of a referral link —
    the `referred_by` pointer and the `referred_customers` list on the
    detail record. Identity only (name + code + status), no PHI."""

    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        fields = ['id', 'full_name', 'referral_code', 'status', 'created_at']
        read_only_fields = fields


class CustomerListSerializer(serializers.ModelSerializer):
    """Minimal customer record for the list endpoint — no medical PHI."""

    full_name = serializers.CharField(read_only=True)
    tags = CustomerTagSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id',
            'first_name',
            'last_name',
            'preferred_name',
            'full_name',
            'email',
            'phone',
            'status',
            'tags',
            'created_at',
            # ADR 0027 §6 — surfaced on the list so the merge-target
            # search can filter out social-guest rows (you can't merge
            # a guest into another guest) and so the customer-list UI
            # can flag unmerged guests visually if/when that lands.
            'is_social_guest',
            'instagram_handle',
            'acquisition_source',
        ]
        read_only_fields = fields


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Full customer record for create / retrieve / update."""

    full_name = serializers.CharField(read_only=True)
    tags = CustomerTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=CustomerTag.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source='tags',
    )
    # Referrals (1A.2). `referred_by` is the nested referrer for display;
    # `referred_by_code` is the write-only intake input — an existing
    # client's referral code, resolved tenant-scoped in validation.
    # `referred_customers` is the reverse side: everyone this client
    # brought in.
    referred_by = ReferralCustomerSerializer(read_only=True)
    referred_by_code = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        source='referred_by',
        help_text="An existing client's referral code; resolves to that client.",
    )
    referred_customers = ReferralCustomerSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id',
            # Identity
            'first_name', 'last_name', 'preferred_name', 'full_name',
            'email', 'phone',
            # Demographics
            'date_of_birth', 'sex',
            # Address
            'address_line1', 'address_line2', 'city', 'state', 'zip_code',
            # Emergency contact
            'emergency_name', 'emergency_phone', 'emergency_relationship',
            # Medical
            'medical_history', 'allergies', 'medications', 'skin_type_fitzpatrick',
            # CRM
            'notes', 'referral_source',
            # Marketing — transactional (booking confirmations, reminders)
            'email_opt_in', 'sms_opt_in',
            # Marketing — promotional (campaigns + automations).
            # Per-channel consent + suppression w/ source + timestamp.
            # Suppression always wins over opt-in (ADR 0016).
            'email_marketing_opt_in', 'sms_marketing_opt_in',
            'email_marketing_consent_at', 'sms_marketing_consent_at',
            'email_marketing_consent_source', 'sms_marketing_consent_source',
            'email_marketing_suppressed_at', 'sms_marketing_suppressed_at',
            'email_marketing_suppression_source', 'sms_marketing_suppression_source',
            # Status + tags
            'status', 'tags', 'tag_ids',
            # Referrals (1A.2) — code is auto-generated/read-only;
            # referred_by_code is the write-only intake input.
            'referral_code',
            'referred_by', 'referred_by_code', 'referred_customers',
            # Provenance (read-only)
            'external_id', 'external_source', 'imported_at',
            # Acquisition (ADR 0027 §8a) — first-touch, read-only
            'acquisition_source',
            'instagram_handle',
            'is_social_guest',
            # Timestamps
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'full_name',
            'referral_code',
            'external_id', 'external_source', 'imported_at',
            # acquisition_source is immutable from the API — set on
            # create by whichever view created the customer, never
            # overwritten. See ADR 0027 §8a.
            'acquisition_source',
            'instagram_handle',
            'is_social_guest',
            'created_at', 'updated_at',
            # Consent + suppression metadata: only set by the backend
            # (booking_form, unsubscribe_link, manual ops). The opt-in
            # booleans themselves are writable so an operator can flip
            # them in-app, but the source/timestamp companion fields
            # are stamped by the same code path that flips the boolean.
            'email_marketing_consent_at', 'sms_marketing_consent_at',
            'email_marketing_consent_source', 'sms_marketing_consent_source',
            'email_marketing_suppressed_at', 'sms_marketing_suppressed_at',
            'email_marketing_suppression_source', 'sms_marketing_suppression_source',
        ]

    def _requesting_user_can_view_phi(self) -> bool:
        """True if the request context's membership holds `VIEW_CLIENT_PHI`,
        or the request is from a platform superuser. False otherwise
        (anonymous, missing membership, lacking permission)."""
        request = self.context.get('request')
        if request is None:
            return True
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        if getattr(user, 'is_superuser', False):
            return True
        membership = getattr(request, 'tenant_membership', None)
        if membership is None:
            return False
        return membership.has(P.VIEW_CLIENT_PHI)

    def to_representation(self, instance: Customer) -> dict:
        """Omit PHI fields entirely (not just null them) when the requester
        lacks `VIEW_CLIENT_PHI`. Frontend renders the absent fields as
        unavailable rather than empty — see ADR 0017."""
        data = super().to_representation(instance)
        if not self._requesting_user_can_view_phi():
            for f in PHI_FIELDS:
                data.pop(f, None)
        return data

    def validate_referred_by_code(self, value: str):
        """Resolve a referral code to a Customer in the current tenant.

        Empty input means 'no referrer' (clears the link on update).
        An unknown code is a hard error — surfaced verbatim as the
        new-client form's 'code not found' message. A client cannot be
        their own referrer. The lookup is tenant-scoped so a code from
        another spa never resolves."""
        code = (value or '').strip().upper()
        if not code:
            return None
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None) if request else None
        if tenant is None:
            raise serializers.ValidationError(
                'No tenant context for this request.'
            )
        referrer = (
            Customer.objects
            .filter(tenant=tenant, referral_code=code)
            .first()
        )
        if referrer is None:
            raise serializers.ValidationError(
                f'No client found with referral code “{code}”.'
            )
        if self.instance is not None and referrer.pk == self.instance.pk:
            raise serializers.ValidationError(
                'A client cannot be referred by themselves.'
            )
        return referrer

    def validate(self, attrs: dict) -> dict:
        """Defense-in-depth: a user without `VIEW_CLIENT_PHI` cannot WRITE
        PHI fields either. Otherwise a malicious front-desk user could
        blind-overwrite a medical-history field they can't read. We
        reject the request rather than silently dropping, so the caller
        sees they're not authorized — surfacing the boundary is more
        defensible than swallowing it."""
        if not self._requesting_user_can_view_phi():
            sent_phi = sorted(set(attrs.keys()) & PHI_FIELDS)
            if sent_phi:
                raise serializers.ValidationError({
                    f: 'You do not have permission to set this field.'
                    for f in sent_phi
                })
        return attrs

    def create(self, validated_data: dict) -> Customer:
        """Stamp consent metadata when the operator marks marketing
        opt-in at create time. Mirrors the same stamping logic in
        `update()` — the create form on the front-end pre-checks the
        promotional-consent boxes (front-desk implicit-consent
        pattern, matches Mindbody/Boulevard); leaving them checked is
        treated as an explicit operator-affirmed consent so we record
        `consent_at = now` + `consent_source = 'manual'` per ADR 0016."""
        now = djtz.now()
        if validated_data.get('email_marketing_opt_in') is True:
            validated_data.setdefault('email_marketing_consent_at', now)
            validated_data.setdefault('email_marketing_consent_source', 'manual')
        if validated_data.get('sms_marketing_opt_in') is True:
            validated_data.setdefault('sms_marketing_consent_at', now)
            validated_data.setdefault('sms_marketing_consent_source', 'manual')
        return super().create(validated_data)

    def update(self, instance: Customer, validated_data: dict) -> Customer:
        """Stamp consent metadata when an operator flips a marketing
        opt-in. Suppression is left untouched here — the customer
        unsubscribe link and explicit ops actions are the only paths
        that flip suppression. ADR 0016."""
        now = djtz.now()
        if (
            validated_data.get('email_marketing_opt_in') is True
            and not instance.email_marketing_opt_in
        ):
            instance.email_marketing_consent_at = now
            instance.email_marketing_consent_source = 'manual'
        if (
            validated_data.get('sms_marketing_opt_in') is True
            and not instance.sms_marketing_opt_in
        ):
            instance.sms_marketing_consent_at = now
            instance.sms_marketing_consent_source = 'manual'
        return super().update(instance, validated_data)
