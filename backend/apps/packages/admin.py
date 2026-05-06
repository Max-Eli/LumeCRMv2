from django.contrib import admin

from .models import (
    Package,
    PackageItem,
    PackageRedemption,
    PurchasedPackage,
    PurchasedPackageItem,
)


class PackageItemInline(admin.TabularInline):
    model = PackageItem
    extra = 0
    autocomplete_fields = ('service',)


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'tenant', 'price_cents', 'validity_days', 'is_active')
    list_filter = ('tenant', 'is_active')
    search_fields = ('name', 'sku')
    inlines = [PackageItemInline]


class PurchasedPackageItemInline(admin.TabularInline):
    model = PurchasedPackageItem
    extra = 0
    readonly_fields = ('service', 'service_name', 'quantity_purchased', 'unit_value_cents')


@admin.register(PurchasedPackage)
class PurchasedPackageAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'name', 'tenant', 'status', 'purchased_at', 'expires_at')
    list_filter = ('tenant', 'status')
    search_fields = ('name', 'customer__first_name', 'customer__last_name')
    readonly_fields = (
        'tenant', 'customer', 'source_template', 'source_invoice_line',
        'name', 'description', 'price_cents', 'validity_days',
        'purchased_at', 'expires_at',
    )
    inlines = [PurchasedPackageItemInline]


@admin.register(PackageRedemption)
class PackageRedemptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'purchased_package', 'item', 'quantity', 'redeemed_at', 'by_user')
    list_filter = ('tenant',)
    readonly_fields = (
        'tenant', 'purchased_package', 'item', 'quantity',
        'invoice_line', 'appointment', 'by_user', 'redeemed_at', 'note',
    )
