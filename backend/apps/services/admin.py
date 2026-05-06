from django.contrib import admin

from .models import Service, ServiceCategory


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'tenant', 'sort_order')
    list_filter = ('tenant',)
    search_fields = ('name', 'tenant__name')
    autocomplete_fields = ('tenant',)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'code', 'service_type', 'category', 'duration_minutes', 'price_dollars',
        'is_bookable_online', 'is_active', 'tenant',
    )
    list_filter = ('is_active', 'is_bookable_online', 'service_type', 'category', 'tenant')
    search_fields = ('name', 'code', 'description', 'tenant__name')
    autocomplete_fields = ('tenant', 'category')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('tenant', 'name', 'code', 'description', 'service_type', 'category', 'sort_order')}),
        ('Booking', {'fields': ('duration_minutes', 'buffer_minutes', 'is_bookable_online', 'is_active')}),
        ('Pricing', {'fields': ('price_cents', 'tax_rate_percent')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
