"""DRF serializers for the gift cards API.

Read-only `GiftCardSerializer` with nested ledger; lookup serializer
for the code-based balance check at checkout; void input.

Sale + redeem flow through invoice action endpoints — no write
serializer here for those.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import GiftCard, GiftCardLedger


class GiftCardLedgerSerializer(serializers.ModelSerializer):
    by_user_email = serializers.EmailField(
        source='by_user.email', read_only=True, allow_null=True,
    )

    class Meta:
        model = GiftCardLedger
        fields = [
            'id',
            'gift_card',
            'kind',
            'amount_cents',
            'invoice',
            'by_user_email',
            'note',
            'recorded_at',
        ]
        read_only_fields = fields


class GiftCardSerializer(serializers.ModelSerializer):
    """Issued gift card with nested ledger. Drives the catalog list,
    customer-profile balance display, and the redemption picker."""

    issued_to_customer_name = serializers.SerializerMethodField()
    purchaser_customer_name = serializers.SerializerMethodField()
    ledger_entries = GiftCardLedgerSerializer(many=True, read_only=True)
    initial_value_dollars = serializers.CharField(read_only=True)
    balance_dollars = serializers.CharField(read_only=True)
    is_redeemable = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_fully_redeemed = serializers.BooleanField(read_only=True)
    voided_by_email = serializers.EmailField(
        source='voided_by.email', read_only=True, allow_null=True,
    )

    class Meta:
        model = GiftCard
        fields = [
            'id',
            'code',
            'issued_to_customer',
            'issued_to_customer_name',
            'issued_to_name',
            'issued_to_email',
            'purchaser_customer',
            'purchaser_customer_name',
            'source_invoice_line',
            'initial_value_cents',
            'initial_value_dollars',
            'balance_cents',
            'balance_dollars',
            'status',
            'issued_at',
            'expires_at',
            'voided_at',
            'voided_by_email',
            'void_reason',
            'notes',
            'is_redeemable',
            'is_expired',
            'is_fully_redeemed',
            'ledger_entries',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def _customer_name(self, customer) -> str | None:
        if customer is None:
            return None
        full = f'{customer.first_name} {customer.last_name}'.strip()
        return full or customer.email

    def get_issued_to_customer_name(self, obj: GiftCard) -> str | None:
        return self._customer_name(obj.issued_to_customer)

    def get_purchaser_customer_name(self, obj: GiftCard) -> str | None:
        return self._customer_name(obj.purchaser_customer)


class GiftCardLookupInputSerializer(serializers.Serializer):
    """Body for `POST /api/gift-cards/lookup/`. The code is presented
    by the customer at checkout; we return balance + redeemability so
    the operator knows whether/how much can be applied."""

    code = serializers.CharField(max_length=20)


class VoidGiftCardInputSerializer(serializers.Serializer):
    """Body for `POST /api/gift-cards/<id>/void/`. Reason persists to
    audit metadata + the card row's `void_reason`."""

    reason = serializers.CharField(
        max_length=200,
        help_text='Why this card is being voided. Required.',
    )
