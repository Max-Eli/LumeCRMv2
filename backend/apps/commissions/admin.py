from django.contrib import admin

from .models import (
    CommissionEntry,
    CommissionRule,
    CommissionRuleOverride,
)


class CommissionRuleOverrideInline(admin.TabularInline):
    model = CommissionRuleOverride
    extra = 0
    autocomplete_fields = ('category',)


@admin.register(CommissionRule)
class CommissionRuleAdmin(admin.ModelAdmin):
    list_display = (
        'membership', 'tenant', 'base_rate_percent', 'is_active',
    )
    list_filter = ('tenant', 'is_active')
    search_fields = (
        'membership__user__first_name',
        'membership__user__last_name',
        'membership__user__email',
    )
    inlines = [CommissionRuleOverrideInline]


@admin.register(CommissionEntry)
class CommissionEntryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'tenant', 'membership', 'kind', 'amount_cents',
        'rate_percent', 'accrued_at',
    )
    list_filter = ('tenant', 'kind')
    search_fields = (
        'membership__user__first_name',
        'membership__user__last_name',
    )
    readonly_fields = (
        'tenant', 'membership', 'invoice', 'invoice_line',
        'kind', 'rate_percent', 'line_subtotal_cents', 'amount_cents',
        'reverses', 'note', 'by_user', 'accrued_at',
    )
