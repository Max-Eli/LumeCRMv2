from django.contrib import admin

from .models import GiftCard, GiftCardLedger


class GiftCardLedgerInline(admin.TabularInline):
    model = GiftCardLedger
    extra = 0
    readonly_fields = (
        'kind', 'amount_cents', 'invoice', 'by_user', 'note', 'recorded_at',
    )
    can_delete = False
    show_change_link = False


@admin.register(GiftCard)
class GiftCardAdmin(admin.ModelAdmin):
    list_display = (
        'code', 'tenant', 'status',
        'initial_value_cents', 'balance_cents',
        'issued_to_customer', 'issued_to_name', 'issued_at',
    )
    list_filter = ('tenant', 'status')
    search_fields = ('code', 'issued_to_name', 'issued_to_email')
    readonly_fields = (
        'tenant', 'code', 'source_invoice_line',
        'initial_value_cents', 'balance_cents',
        'issued_at', 'voided_at', 'voided_by',
        'created_at', 'updated_at',
    )
    inlines = [GiftCardLedgerInline]


@admin.register(GiftCardLedger)
class GiftCardLedgerAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'gift_card', 'kind', 'amount_cents',
        'invoice', 'by_user', 'recorded_at',
    )
    list_filter = ('tenant', 'kind')
    readonly_fields = (
        'tenant', 'gift_card', 'kind', 'amount_cents',
        'invoice', 'by_user', 'note', 'recorded_at',
    )
