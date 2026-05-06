from django.contrib import admin

from .models import (
    MembershipPlan,
    MembershipPlanItem,
    Subscription,
    SubscriptionItem,
    SubscriptionRedemption,
)


class MembershipPlanItemInline(admin.TabularInline):
    model = MembershipPlanItem
    extra = 0
    autocomplete_fields = ('service',)


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'sku', 'tenant', 'price_cents',
        'billing_interval', 'is_active',
    )
    list_filter = ('tenant', 'billing_interval', 'is_active')
    search_fields = ('name', 'sku')
    inlines = [MembershipPlanItemInline]


class SubscriptionItemInline(admin.TabularInline):
    model = SubscriptionItem
    extra = 0
    readonly_fields = (
        'service', 'service_name', 'quantity_per_cycle', 'unit_value_cents',
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'customer', 'name', 'tenant',
        'status', 'started_at', 'current_period_ends_at',
    )
    list_filter = ('tenant', 'status', 'billing_interval')
    search_fields = ('name', 'customer__first_name', 'customer__last_name')
    readonly_fields = (
        'tenant', 'customer', 'plan', 'source_invoice_line',
        'name', 'description', 'price_cents', 'billing_interval',
        'member_discount_percent',
        'started_at', 'current_period_starts_at', 'current_period_ends_at',
    )
    inlines = [SubscriptionItemInline]


@admin.register(SubscriptionRedemption)
class SubscriptionRedemptionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'subscription', 'item', 'quantity', 'redeemed_at', 'by_user',
    )
    list_filter = ('tenant',)
    readonly_fields = (
        'tenant', 'subscription', 'item', 'quantity',
        'invoice_line', 'appointment', 'by_user', 'redeemed_at', 'note',
    )
