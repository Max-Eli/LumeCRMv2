"""Gift cards API.

Endpoints under `/api/`:

    GET    /api/gift-cards/              List (?customer=, ?purchaser=, ?status=, ?code=)
    GET    /api/gift-cards/{id}/         Retrieve (with full ledger)
    POST   /api/gift-cards/lookup/       Look up by code (code-only checkout flow)
    POST   /api/gift-cards/{id}/void/    Void an unspent card (Owner/Manager)

Sale + redemption flow through invoice action endpoints in the
next step — not here. Issuing a card from outside an invoice
context (e.g. comping one without a sale) is intentionally not
supported in v1; do it via a $0 invoice line if you need to.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record

from .models import GiftCard
from .permissions import GiftCardPermission
from .serializers import (
    GiftCardLookupInputSerializer,
    GiftCardSerializer,
    VoidGiftCardInputSerializer,
)


class GiftCardViewSet(viewsets.ReadOnlyModelViewSet):
    """List / retrieve issued gift cards + lookup + void.

    Inherits from `ReadOnlyModelViewSet` — sale happens through the
    invoice flow; this surface is for operators looking up balances
    and voiding bad cards.
    """

    serializer_class = GiftCardSerializer
    permission_classes = [GiftCardPermission]

    def get_queryset(self):
        return (
            GiftCard.objects
            .for_current_tenant()
            .select_related(
                'issued_to_customer',
                'purchaser_customer',
                'voided_by',
            )
            .prefetch_related('ledger_entries', 'ledger_entries__by_user')
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        customer = (params.get('customer') or '').strip()
        purchaser = (params.get('purchaser') or '').strip()
        status_filter = (params.get('status') or '').strip().lower()
        code = (params.get('code') or '').strip().upper()
        q = (params.get('q') or '').strip()

        if customer:
            queryset = queryset.filter(issued_to_customer_id=customer)
        if purchaser:
            queryset = queryset.filter(purchaser_customer_id=purchaser)
        if status_filter in {'pending', 'active', 'voided', 'expired'}:
            queryset = queryset.filter(status=status_filter)
        if code:
            queryset = queryset.filter(code__iexact=code)
        if q:
            queryset = queryset.filter(
                Q(code__icontains=q)
                | Q(issued_to_name__icontains=q)
                | Q(issued_to_email__icontains=q)
                | Q(notes__icontains=q),
            )
        return queryset

    # ── Audit-logged read overrides ─────────────────────────────────

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = (
            response.data.get('results', response.data)
            if isinstance(response.data, dict)
            else response.data
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='gift_card_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'customer': request.query_params.get('customer', ''),
                'status': request.query_params.get('status', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='gift_card',
            resource_id=instance.id,
            request=request,
        )
        return Response(self.get_serializer(instance).data)

    # ── Code-based lookup ───────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='lookup')
    def lookup(self, request):
        """Resolve a presented code to a card (in the current tenant).

        Returns 404 when the code doesn't match. Doesn't leak any
        cross-tenant data — `for_current_tenant()` scopes the
        lookup. Returns the full serialized card on hit so the
        operator UI can show balance + status without a follow-up
        retrieve."""
        ser = GiftCardLookupInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        code = ser.validated_data['code'].strip().upper()
        try:
            card = self.get_queryset().get(code__iexact=code)
        except GiftCard.DoesNotExist:
            return Response(
                {'detail': 'No gift card with that code in this spa.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        record(
            action=AuditLog.Action.READ,
            resource_type='gift_card',
            resource_id=card.id,
            request=request,
            metadata={'event': 'lookup_by_code'},
        )
        return Response(self.get_serializer(card).data)

    # ── Void ────────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='void')
    def void(self, request, pk=None):
        """Void an ACTIVE or PENDING card. Refuses on already-VOIDED
        rows. Requires a reason; `voided_at`, `voided_by`, and
        `void_reason` persist on the card row + an ADJUSTMENT ledger
        entry zeroes the balance.

        Refuses if the card has any redemption ledger entries —
        zeroing a partially-spent card would orphan the redemption
        rows that already credited a customer's invoice. Operator
        must reverse those redemptions first.
        """
        from .models import GiftCardLedger

        card = self.get_object()
        ser = VoidGiftCardInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data['reason']

        if card.status == GiftCard.Status.VOIDED:
            return Response(
                {'detail': 'Card is already voided.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Refuse if redeemed against — operator must reverse first.
        redeem_count = card.ledger_entries.filter(
            kind=GiftCardLedger.Kind.REDEEM,
        ).count()
        if redeem_count > 0:
            return Response(
                {
                    'detail': (
                        f'Cannot void: card has {redeem_count} redemption '
                        f'entr{"y" if redeem_count == 1 else "ies"}. '
                        f'Reverse those first.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            locked = (
                GiftCard.objects.select_for_update()
                .get(pk=card.pk)
            )
            previous_status = locked.status
            previous_balance = locked.balance_cents
            now = timezone.now()
            locked.status = GiftCard.Status.VOIDED
            locked.voided_at = now
            locked.voided_by = request.user
            locked.void_reason = reason
            # Zero the balance via an ADJUSTMENT ledger row so the
            # balance == sum(ledger) invariant holds.
            if previous_balance > 0:
                GiftCardLedger.objects.create(
                    tenant=locked.tenant,
                    gift_card=locked,
                    kind=GiftCardLedger.Kind.ADJUSTMENT,
                    amount_cents=-previous_balance,
                    invoice=None,
                    by_user=request.user,
                    note=f'Voided: {reason}',
                )
                locked.balance_cents = 0
            locked.save(update_fields=[
                'status', 'voided_at', 'voided_by', 'void_reason',
                'balance_cents', 'updated_at',
            ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='gift_card',
            resource_id=card.pk,
            request=request,
            metadata={
                'event': 'voided',
                'from_status': previous_status,
                'forfeited_balance_cents': previous_balance,
                'reason': reason,
            },
        )
        card.refresh_from_db()
        return Response(self.get_serializer(card).data)
