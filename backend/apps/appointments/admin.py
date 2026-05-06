from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        'start_time', 'customer', 'service', 'provider',
        'status', 'tenant',
    )
    list_filter = ('status', 'tenant', 'service__category')
    search_fields = (
        'customer__first_name', 'customer__last_name',
        'service__name', 'service__code',
        'provider__user__email',
    )
    autocomplete_fields = ('tenant', 'customer', 'service', 'provider', 'created_by')
    readonly_fields = (
        'quoted_price_cents',
        'checked_in_at', 'completed_at', 'cancelled_at',
        'created_at', 'updated_at',
    )
    date_hierarchy = 'start_time'
    fieldsets = (
        (None, {
            'fields': ('tenant', 'customer', 'service', 'provider', 'status'),
        }),
        ('Time', {
            'fields': ('start_time', 'end_time'),
        }),
        ('Workflow', {
            'fields': ('checked_in_at', 'completed_at', 'cancelled_at', 'cancelled_reason'),
        }),
        ('Notes & metadata', {
            'fields': ('notes', 'source', 'quoted_price_cents'),
        }),
        ('Provenance', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
