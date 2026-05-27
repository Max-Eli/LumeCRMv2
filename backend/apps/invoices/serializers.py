"""DRF serializers for the invoices API.

Two serializers:

  - `InvoiceLineItemSerializer` — read-only nested view of a line item.
    Lines are created/edited via service-layer code (the
    appointment-signal handler creates the initial line; richer
    multi-line invoices land in Phase 2A POS).
  - `InvoiceSerializer` — invoice header with nested customer/appointment
    summaries (avoids N+1 round-trips on list views), nested lines,
    derived `is_reopen_window_open` and `reopen_deadline`. All
    money-and-status fields are read-only at this layer; mutations go
    through the action endpoints (`close`, `reopen`, `void`) so each
    state change writes a structured audit log entry.
"""

from rest_framework import serializers

from apps.appointments.models import Appointment
from apps.customers.models import Customer

from .models import Invoice, InvoiceLineItem


class _CustomerSummary(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        # Email + phone are non-PHI contact info, exposed so the invoice
        # UI can show "Send to pat@example.com" on the Email Invoice
        # button without a second round-trip to /api/customers/{id}/.
        # Tracking ADR 0017 — email/phone deliberately excluded from
        # PHI redaction because operational roles need them.
        fields = ['id', 'first_name', 'last_name', 'full_name', 'email', 'phone']
        read_only_fields = fields


class _AppointmentSummary(serializers.ModelSerializer):
    """Just enough appointment context to render an invoice without an
    extra round-trip to the appointments endpoint."""

    service_name = serializers.CharField(source='service.name', read_only=True)
    provider_name = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            'id', 'status', 'start_time', 'end_time',
            'service_name', 'provider_name',
        ]
        read_only_fields = fields

    def get_provider_name(self, obj: Appointment) -> str | None:
        provider = obj.provider
        if not provider:
            return None
        u = provider.user
        full = f'{u.first_name} {u.last_name}'.strip()
        return full or u.email


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = [
            'id',
            'service', 'product', 'package', 'membership_plan',
            'description', 'quantity',
            'unit_price_cents', 'tax_rate_percent',
            'line_subtotal_cents', 'line_tax_cents',
            # Per-line discount fields. `discount_kind` + `discount_input`
            # are the operator's choice; `discount_cents` is the derived
            # cents off; `invoice_discount_share_cents` is this line's
            # absorbed share of the invoice-level discount (set by
            # recalculate_totals). All read-only — write through the
            # PATCH /lines/{pk}/edit/ endpoint.
            'discount_kind', 'discount_input', 'discount_cents',
            'discount_reason', 'invoice_discount_share_cents',
            'created_at',
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    customer = _CustomerSummary(read_only=True)
    appointment = _AppointmentSummary(read_only=True)
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)

    is_reopen_window_open = serializers.BooleanField(read_only=True)
    reopen_deadline = serializers.DateTimeField(read_only=True, allow_null=True)

    closed_by_email = serializers.CharField(
        source='closed_by.email', read_only=True, allow_null=True,
    )
    reopened_by_email = serializers.CharField(
        source='reopened_by.email', read_only=True, allow_null=True,
    )
    voided_by_email = serializers.CharField(
        source='voided_by.email', read_only=True, allow_null=True,
    )
    created_by_email = serializers.CharField(
        source='created_by.email', read_only=True, allow_null=True,
    )

    amount_due_cents = serializers.IntegerField(read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number',
            'customer', 'appointment',
            'status',
            'subtotal_cents', 'tax_cents', 'total_cents',
            # Discount fields. The invoice-level discount layers on top
            # of any per-line discounts and is distributed pro-rata
            # across lines by `recalculate_totals`. Read-only here —
            # mutations go through PATCH /api/invoices/{id}/discount/.
            'invoice_discount_kind', 'invoice_discount_input',
            'invoice_discount_cents', 'invoice_discount_reason',
            'line_discounts_total_cents',
            'gift_card_credits_cents', 'amount_due_cents',
            'payment_method', 'payment_reference',
            'notes',
            'closed_at', 'closed_by_email',
            'reopened_at', 'reopened_by_email', 'reopen_count',
            'voided_at', 'voided_by_email', 'void_reason',
            'created_at', 'updated_at', 'created_by_email',
            'line_items',
            'is_reopen_window_open', 'reopen_deadline',
        ]
        read_only_fields = fields  # mutations go through action endpoints


# ── Action input serializers ────────────────────────────────────────────


class CreateStandaloneInvoiceInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/create-standalone/`."""

    customer_id = serializers.IntegerField(
        help_text='The customer this walk-in sale is billed to.',
    )


class CloseInvoiceInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/close/`."""

    payment_method = serializers.ChoiceField(choices=Invoice.PaymentMethod.choices)
    payment_reference = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default='',
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, default='',
        help_text='Optional staff note appended to the invoice.',
    )


class ReopenInvoiceInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/reopen/`."""

    reason = serializers.CharField(
        max_length=200,
        help_text=(
            'Why this invoice is being reopened. Recorded in the audit '
            'log; required so the reopen has a documented justification.'
        ),
    )


class VoidInvoiceInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/void/`."""

    reason = serializers.CharField(
        max_length=200,
        help_text='Why this invoice is being voided. Required.',
    )


class AddLineInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/add-line/`.

    Caller supplies exactly one of `service_id`, `product_id`, or
    `package_id`. The line snapshots `description`,
    `unit_price_cents`, and `tax_rate_percent` from the source so
    subsequent catalog edits don't drift historical lines (SOC 2
    PI1.1). Optional overrides:

      - `quantity` (default 1) — non-zero positive integer. Forced
        to 1 for package_id (one purchase per line).
      - `unit_price_cents` — override the catalog price for this
        sale (e.g. honoring a member discount or comp rate).
      - `description` — override the snapshot text (rarely needed).

    Adding lines is only allowed on OPEN invoices; the view returns
    409 if the invoice is PAID or VOID.
    """

    service_id = serializers.IntegerField(required=False, allow_null=True)
    product_id = serializers.IntegerField(required=False, allow_null=True)
    package_id = serializers.IntegerField(required=False, allow_null=True)
    membership_plan_id = serializers.IntegerField(
        required=False, allow_null=True,
    )
    quantity = serializers.IntegerField(required=False, default=1, min_value=1)
    unit_price_cents = serializers.IntegerField(
        required=False, allow_null=True, min_value=0,
    )
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=200,
    )

    def validate(self, attrs: dict) -> dict:
        ids = [
            attrs.get('service_id'),
            attrs.get('product_id'),
            attrs.get('package_id'),
            attrs.get('membership_plan_id'),
        ]
        non_null = [v for v in ids if v is not None]
        if len(non_null) != 1:
            raise serializers.ValidationError(
                'Provide exactly one of service_id, product_id, '
                'package_id, or membership_plan_id.',
            )
        return attrs


class RedeemFromPackageInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/redeem-from-package/`.

    Draws down a credit from one of the customer's `PurchasedPackage`
    rows. The view validates that the package is ACTIVE, not
    expired, scoped to this customer (matches the invoice's
    customer), and has remaining quantity for the requested service.
    """

    purchased_package_id = serializers.IntegerField()
    service_id = serializers.IntegerField()
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=200, default='',
    )


class RedeemFromMembershipInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/redeem-from-membership/`.

    Draws down a credit from one of the customer's `Subscription`
    rows. The view validates that the subscription is ACTIVE +
    in-period + customer-matched + the requested service is
    included in the plan + has remaining quantity.
    """

    subscription_id = serializers.IntegerField()
    service_id = serializers.IntegerField()
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=200, default='',
    )


class AddGiftCardSaleInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/add-gift-card-sale/`.

    Sells a gift card on this invoice. The line gets the dollar
    amount the customer is paying, and a PENDING `GiftCard` is
    created tied 1:1 to that line. Invoice close flips the card to
    ACTIVE and writes the ISSUE ledger row.

    Recipient handling:
      - `recipient_customer_id` (preferred) → existing customer
      - `recipient_name` (free text) → for "gift to a non-customer"

    Caller must supply at least one. The purchasing customer comes
    from the invoice header.
    """

    value_cents = serializers.IntegerField(min_value=1)
    recipient_customer_id = serializers.IntegerField(
        required=False, allow_null=True,
    )
    recipient_name = serializers.CharField(
        required=False, allow_blank=True, max_length=200, default='',
    )
    recipient_email = serializers.EmailField(
        required=False, allow_blank=True, max_length=254, default='',
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=500,
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs.get('recipient_customer_id') and not (
            attrs.get('recipient_name', '').strip()
        ):
            raise serializers.ValidationError(
                'Provide either recipient_customer_id or recipient_name '
                "(it's the customer who'll redeem the card).",
            )
        return attrs


class ApplyGiftCardInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/apply-gift-card/`.

    Applies a portion (or all) of a gift card's balance toward this
    invoice. The view validates the card is ACTIVE + not expired +
    has at least `amount_cents` available. Atomic decrement +
    REDEEM ledger row + bump invoice.gift_card_credits_cents.

    Code-based lookup: operator types the code the customer
    presents at checkout.
    """

    code = serializers.CharField(max_length=20)
    amount_cents = serializers.IntegerField(min_value=1)


class CustomPackageItemInputSerializer(serializers.Serializer):
    """One line in a custom (per-customer) package builder."""

    service_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class AddCustomPackageInputSerializer(serializers.Serializer):
    """Body for `POST /api/invoices/{id}/add-custom-package/`.

    Builds a one-off bundle for a single customer rather than
    reusing a catalog `Package`. The shape mirrors the catalog
    surface (name, description, price, validity, items) so the
    builder UI doesn't have to fork.

    Server-side, this creates:
      - an `InvoiceLineItem` with all of (service, product, package)
        null — it's a custom line, not tied to a catalog row;
      - a `PurchasedPackage` with `source_template = NULL` and the
        bundle metadata snapshotted inline;
      - per-service `PurchasedPackageItem` rows for the items.

    Lifecycle is identical to a catalog-derived package: PENDING
    until the invoice closes, then ACTIVE; redeemable through
    the same `redeem-from-package` endpoint.
    """

    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        required=False, allow_blank=True, default='',
    )
    price_cents = serializers.IntegerField(min_value=0)
    tax_rate_percent = serializers.DecimalField(
        max_digits=6, decimal_places=3, required=False, default=0,
    )
    validity_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=0,
    )
    items = CustomPackageItemInputSerializer(many=True)

    def validate_items(self, value: list[dict]) -> list[dict]:
        if not value:
            raise serializers.ValidationError(
                'A custom package needs at least one service item.'
            )
        ids = [row['service_id'] for row in value]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError(
                'Each service may only appear once per package.'
            )
        return value
